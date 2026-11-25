import hashlib
import io

import pytest
from PIL import Image

from tchekam.ai import registry
from tchekam.ai.client import strict_json_schema
from tchekam.ai.fake import FakeRefusal
from tchekam.ai.models import AICallLog
from tchekam.ai.product_photo import PURPOSE, forget, is_product_photo
from tchekam.ai.schemas import ProductPhoto

pytestmark = pytest.mark.django_db


def png(color="white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()


def test_product_photo_uses_selected_model_with_the_image_and_a_strict_schema(fake_llm, settings):
    fake_llm.responses[PURPOSE] = ['{"is_product": true}']

    assert is_product_photo(png()) is True

    call = fake_llm.calls[0]
    assert call["purpose"] == "is_product_photo"
    assert call["model"] == settings.OPENROUTER_MODEL
    assert call["schema_model"] is ProductPhoto
    assert call["prompt_version"] == "v1"
    assert call["user_content"][0]["type"] == "image_url"
    assert call["user_content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
    log = AICallLog.objects.get()
    assert (log.purpose, log.success) == ("is_product_photo", True)


def test_schema_is_a_single_required_boolean():
    schema = strict_json_schema(ProductPhoto)

    assert schema["type"] == "object"
    assert schema["properties"] == {"is_product": {"type": "boolean"}}
    assert schema["required"] == ["is_product"]
    assert schema["additionalProperties"] is False


def test_result_is_cached_per_sha256(fake_llm):
    fake_llm.responses[PURPOSE] = ['{"is_product": false}']

    assert is_product_photo(png()) is False
    assert is_product_photo(png()) is False  # identical bytes: no second call

    assert len(fake_llm.calls) == 1


def test_different_images_are_classified_separately(fake_llm):
    fake_llm.responses[PURPOSE] = ['{"is_product": true}', '{"is_product": false}']

    assert is_product_photo(png("white")) is True
    assert is_product_photo(png("black")) is False


def test_model_change_does_not_reuse_the_previous_classification(fake_llm, settings):
    fake_llm.responses[PURPOSE] = ['{"is_product": false}', '{"is_product": true}']
    assert is_product_photo(png()) is False
    settings.OPENROUTER_MODEL = "synthetic/replacement"
    assert is_product_photo(png()) is True
    assert len(fake_llm.calls) == 2


@pytest.mark.parametrize("failure", [RuntimeError("down"), FakeRefusal("x"), None])
def test_failures_return_none_and_are_not_cached(fake_llm, failure):
    fake_llm.responses[PURPOSE] = [failure] if failure is not None else []

    assert is_product_photo(png()) is None

    fake_llm.responses[PURPOSE] = ['{"is_product": true}']
    assert is_product_photo(png()) is True


def test_invalid_output_is_retried_once(fake_llm):
    fake_llm.responses[PURPOSE] = ["not json", '{"is_product": true}']

    assert is_product_photo(png()) is True
    assert len(fake_llm.calls) == 2


def test_unreadable_bytes_make_no_call(fake_llm):
    assert is_product_photo(b"not an image") is None
    assert fake_llm.calls == []


def test_forget_drops_cached_results(fake_llm):
    data = png()
    fake_llm.responses[PURPOSE] = ['{"is_product": true}', '{"is_product": false}']
    is_product_photo(data)

    forget([hashlib.sha256(data).hexdigest()])

    assert is_product_photo(data) is False
    assert len(fake_llm.calls) == 2


def test_shipped_prompt_loads():
    text, version = registry.get_prompt(PURPOSE)

    assert version == "v1"
    assert "is_product" in text
