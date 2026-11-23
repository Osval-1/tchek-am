import base64
import io
import json
import struct
import zlib

import pytest
from PIL import Image

from tchekam.ai.extraction import MAX_IMAGES, PURPOSE, extract_evidence
from tchekam.ai.fake import FakeRefusal
from tchekam.ai.models import AICallLog
from tchekam.ai.schemas import Extraction

pytestmark = pytest.mark.django_db


def png(size=(8, 8), color="white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def payload(**overrides) -> str:
    data = {
        "phone_numbers": ["677 12 34 56"],
        "account_names": [{"name": "Jean Testeur", "provider": "momo"}],
        "amounts_xaf": [25000],
        "transaction_ids": ["TX-0001"],
        "dates": ["2026-11-20"],
        "operator": "mtn",
        "product": "iPhone 15",
        "scam_type": "fake_product",
        "summary": "Payment sent for a phone that never arrived.",
        "evidence_kinds": ["chat", "momo_sms"],
        "tamper_observations": [],
        "payment_proof_candidate": True,
    }
    data.update(overrides)
    return json.dumps(data)


IMAGES = [(png(), "image/png"), (png(), "image/jpeg")]


def extract(images=IMAGES, transcript=None, story=None, lang="fr"):
    return extract_evidence(images, transcript, story, lang)


def test_success_returns_a_validated_extraction(fake_llm):
    fake_llm.responses[PURPOSE] = [payload()]

    result = extract()

    assert isinstance(result, Extraction)
    assert result.extraction_failed is False
    assert result.phone_numbers == ["+237677123456"]
    assert result.account_names[0].name == "Jean Testeur"
    assert result.amounts_xaf == [25000]
    assert result.scam_type == "fake_product"
    assert result.evidence_kinds == ["chat", "momo_sms"]
    assert result.payment_proof_candidate is True
    assert AICallLog.objects.count() == 1


def test_request_uses_vision_model_effort_and_cached_prompt(fake_llm, settings):
    settings.AI_MODEL_VISION = "claude-sonnet-5-5"
    fake_llm.responses[PURPOSE] = [payload()]

    extract(transcript="il a dit 690000000", story="je voulais un phone", lang="en")

    [call] = fake_llm.calls
    assert call["model"] == "claude-sonnet-5-5"
    assert call["effort"] == "medium"
    assert call["max_tokens"] == 4096
    assert call["prompt_version"] == "v1"
    assert call["use_fallback"] is True
    assert call["schema_model"] is Extraction
    content = call["user_content"]
    assert [b["type"] for b in content] == ["image", "image", "text"]
    assert content[0]["source"]["media_type"] == "image/png"
    assert base64.b64decode(content[0]["source"]["data"]) == IMAGES[0][0]
    text = content[-1]["text"]
    assert "English" in text and "il a dit 690000000" in text and "je voulais un phone" in text
    # Volatile values stay out of the cached system prompt.
    assert "il a dit" not in call["system"]


def test_fallback_follows_setting(fake_llm, settings):
    settings.AI_REFUSAL_FALLBACK = False
    fake_llm.responses[PURPOSE] = [payload()]

    extract()

    assert fake_llm.calls[0]["use_fallback"] is False


def test_invalid_json_is_retried_exactly_once_then_succeeds(fake_llm):
    fake_llm.responses[PURPOSE] = ["not json at all", payload()]

    result = extract()

    assert result.extraction_failed is False
    assert len(fake_llm.calls) == 2
    assert AICallLog.objects.count() == 2


def test_two_invalid_outputs_give_a_partial_result(fake_llm):
    fake_llm.responses[PURPOSE] = ["{}", '{"phone_numbers": 3}', payload()]

    result = extract()

    assert len(fake_llm.calls) == 2  # exactly one retry; the third response is never used
    assert result.extraction_failed is True
    assert result.phone_numbers == [] and result.account_names == []
    assert result.scam_type == "other" and result.summary == ""
    assert result.evidence_kinds == ["other", "other"]
    assert result.payment_proof_candidate is False
    assert list(AICallLog.objects.values_list("success", flat=True)) == [False, False]


def test_refusal_fails_without_retry(fake_llm):
    fake_llm.responses[PURPOSE] = [FakeRefusal("general_harms"), payload()]

    result = extract()

    assert result.extraction_failed is True
    assert len(fake_llm.calls) == 1
    assert AICallLog.objects.get().error == "refusal:general_harms"


def test_api_error_fails_without_retry(fake_llm):
    fake_llm.responses[PURPOSE] = [ConnectionError("down"), payload()]

    assert extract().extraction_failed is True
    assert len(fake_llm.calls) == 1


def test_numbers_are_normalised_invalid_dropped_and_deduped(fake_llm):
    fake_llm.responses[PURPOSE] = [
        payload(
            phone_numbers=[
                "+237 6 77 12 34 56",
                "677123456",  # duplicate of the first once normalised
                "00237 690 00 00 00",
                "12345",  # not a number
                "+33 6 12 34 56 78",  # foreign
                "",
            ]
        )
    ]

    assert extract().phone_numbers == ["+237677123456", "+237690000000"]


def test_names_are_whitespace_collapsed_and_deduped_by_normalised_form(fake_llm):
    fake_llm.responses[PURPOSE] = [
        payload(
            account_names=[
                {"name": "  Jean  Testeur ", "provider": "momo"},
                {"name": "JEAN TESTEUR", "provider": "om"},
                {"name": "   ", "provider": "unknown"},
                {"name": "Éloïse Fictive", "provider": "om"},
            ]
        )
    ]

    names = extract().account_names

    assert [(n.name, n.provider) for n in names] == [
        ("Jean Testeur", "momo"),
        ("Éloïse Fictive", "om"),
    ]


def test_non_positive_amounts_are_dropped(fake_llm):
    fake_llm.responses[PURPOSE] = [payload(amounts_xaf=[0, -500, 15000])]

    assert extract().amounts_xaf == [15000]


@pytest.mark.parametrize(
    ("kinds", "expected"),
    [
        (["chat"], ["chat", "other"]),
        (["chat", "momo_sms", "post"], ["chat", "momo_sms"]),
        ([], ["other", "other"]),
    ],
)
def test_evidence_kinds_match_the_number_of_images(fake_llm, kinds, expected):
    fake_llm.responses[PURPOSE] = [payload(evidence_kinds=kinds)]

    assert extract().evidence_kinds == expected


def encoded(fmt: str, mode="RGB", size=(8, 8), color="white") -> bytes:
    buf = io.BytesIO()
    extra = {"transparency": 0} if mode == "P" else {}  # palette index 0 is transparent
    Image.new(mode, size, color).save(buf, format=fmt, **extra)
    return buf.getvalue()


def sent_images(fake_llm) -> list[tuple[str, Image.Image]]:
    return [
        (b["source"]["media_type"], Image.open(io.BytesIO(base64.b64decode(b["source"]["data"]))))
        for b in fake_llm.calls[0]["user_content"]
        if b["type"] == "image"
    ]


@pytest.mark.parametrize("label", ["application/pdf", "audio/ogg", "video/mp4", "text/plain"])
def test_non_image_labels_are_skipped_and_keep_their_slot(fake_llm, label):
    fake_llm.responses[PURPOSE] = [payload(evidence_kinds=["momo_sms", "post"])]
    images = [(png(), "image/png"), (png(), label), (png(), "image/png")]

    result = extract(images=images)

    assert len(sent_images(fake_llm)) == 2
    assert result.evidence_kinds == ["momo_sms", "other", "post"]


def test_media_type_comes_from_the_bytes_not_the_label(fake_llm):
    fake_llm.responses[PURPOSE] = [payload(evidence_kinds=["chat", "chat", "chat"])]
    jpeg, webp, png_bytes = encoded("JPEG"), encoded("WEBP"), png()
    images = [(jpeg, "image/png"), (webp, "image/jpeg"), (png_bytes, "application/octet-stream")]

    extract(images=images)

    content = [b for b in fake_llm.calls[0]["user_content"] if b["type"] == "image"]
    assert [b["source"]["media_type"] for b in content] == ["image/jpeg", "image/webp", "image/png"]
    # Native formats under the size limit are sent byte for byte.
    assert [base64.b64decode(b["source"]["data"]) for b in content] == [jpeg, webp, png_bytes]


@pytest.mark.parametrize(
    ("data", "label", "media_type", "fmt"),
    [
        (lambda: encoded("GIF"), "image/gif", "image/jpeg", "JPEG"),
        (lambda: encoded("BMP"), "image/bmp", "image/jpeg", "JPEG"),
        (lambda: encoded("TIFF"), "image/tiff", "image/jpeg", "JPEG"),
        (lambda: encoded("GIF", mode="P"), "image/gif", "image/png", "PNG"),  # transparent
        (
            lambda: encoded("TIFF", mode="RGBA", color=(0, 0, 0, 0)),
            "image/tiff",
            "image/png",
            "PNG",
        ),
    ],
    ids=["gif", "bmp", "tiff", "transparent-gif", "transparent-tiff"],
)
def test_other_formats_are_converted(fake_llm, data, label, media_type, fmt):
    fake_llm.responses[PURPOSE] = [payload(evidence_kinds=["chat"])]

    result = extract(images=[(data(), label)])

    [(sent_type, image)] = sent_images(fake_llm)
    assert (sent_type, image.format) == (media_type, fmt)
    assert result.evidence_kinds == ["chat"]


def test_unreadable_bytes_with_an_image_label_are_skipped(fake_llm):
    fake_llm.responses[PURPOSE] = [payload(evidence_kinds=["post"])]

    result = extract(images=[(b"GIF89a", "image/gif"), (png(), "image/png")])

    assert len(sent_images(fake_llm)) == 1
    assert result.evidence_kinds == ["other", "post"]


def test_images_beyond_the_cap_are_not_sent(fake_llm):
    fake_llm.responses[PURPOSE] = [payload(evidence_kinds=["chat"] * MAX_IMAGES)]
    images = [(png(), "image/png")] * (MAX_IMAGES + 2)

    result = extract(images=images)

    content = fake_llm.calls[0]["user_content"]
    assert sum(b["type"] == "image" for b in content) == MAX_IMAGES
    assert result.evidence_kinds == ["chat"] * MAX_IMAGES + ["other", "other"]


def test_large_images_are_downscaled(fake_llm, monkeypatch):
    from tchekam.ai import extraction

    monkeypatch.setattr(extraction, "MAX_IMAGE_BYTES", 1000)
    fake_llm.responses[PURPOSE] = [payload(evidence_kinds=["chat"])]
    big = png(size=(3000, 1000), color="red")
    assert len(big) > 1000

    extract(images=[(big, "image/png")])

    block = fake_llm.calls[0]["user_content"][0]
    assert block["source"]["media_type"] == "image/jpeg"
    shrunk = Image.open(io.BytesIO(base64.b64decode(block["source"]["data"])))
    assert max(shrunk.size) == 1568


def test_text_only_extraction_works(fake_llm):
    fake_llm.responses[PURPOSE] = [payload(evidence_kinds=["chat"])]

    result = extract(images=[], story="He asked me to pay 677123456 first")

    assert result.evidence_kinds == []
    assert [b["type"] for b in fake_llm.calls[0]["user_content"]] == ["text"]


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_header(width: int, height: int, pad_to: int = 0) -> bytes:
    """A PNG signature and IHDR claiming the given size, with no real pixel data."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    data = PNG_SIGNATURE + struct.pack(">I", len(ihdr)) + chunk
    data += struct.pack(">I", zlib.crc32(chunk))
    return data + b"\0" * max(0, pad_to - len(data))


@pytest.mark.parametrize(
    "bomb",
    [
        # Over Pillow's hard limit: Image.open raises DecompressionBombError.
        pytest.param(lambda big: png_header(20000, 20000, pad_to=big), id="huge-over-5mb"),
        # Over Pillow's warning limit: the warning is turned into an error.
        pytest.param(lambda big: png_header(10000, 10000), id="warning-under-5mb"),
        # Under Pillow's limits but over our own pixel cap.
        pytest.param(lambda big: png_header(8000, 8000), id="own-cap-under-5mb"),
        pytest.param(lambda big: png_header(8000, 8000, pad_to=big), id="own-cap-over-5mb"),
    ],
)
def test_decompression_bombs_are_skipped_without_raising(fake_llm, bomb):
    from tchekam.ai import extraction

    fake_llm.responses[PURPOSE] = [payload(evidence_kinds=["chat"])]
    images = [(bomb(extraction.MAX_IMAGE_BYTES + 1), "image/png"), (png(), "image/png")]

    result = extract(images=images)

    content = fake_llm.calls[0]["user_content"]
    assert [b["type"] for b in content] == ["image", "text"]
    assert base64.b64decode(content[0]["source"]["data"]) == images[1][0]
    assert result.evidence_kinds == ["other", "chat"]


@pytest.mark.parametrize("oversized", [True, False], ids=["over-5mb", "under-5mb"])
def test_unreadable_images_are_skipped(fake_llm, oversized):
    from tchekam.ai import extraction

    fake_llm.responses[PURPOSE] = [payload(evidence_kinds=[])]
    size = extraction.MAX_IMAGE_BYTES + 1 if oversized else 100
    junk = PNG_SIGNATURE + b"\x07" * size

    result = extract(images=[(junk, "image/png")])

    assert [b["type"] for b in fake_llm.calls[0]["user_content"]] == ["text"]
    assert result.evidence_kinds == ["other"]
    assert result.extraction_failed is False


@pytest.mark.parametrize(
    "term",
    [
        "scammer",
        "Scammers",
        "scam artist",
        "fraudster",
        "FRAUD",
        "fraudeur",
        "fraude",
        "arnaqueur",
        "escroc",
        "voleur",
        "feyman",
        "thief",
    ],
)
def test_accusatory_terms_blank_the_summary_and_drop_observations(fake_llm, term):
    fake_llm.responses[PURPOSE] = [
        payload(
            summary=f"The seller is a {term}, he took 25000.",
            tamper_observations=[
                f"Image 1: this {term} edited the amount",
                "Image 2: the timestamp differs from the status bar",
            ],
        )
    ]

    result = extract()

    assert result.summary == ""
    assert result.summary_filtered is True
    assert result.tamper_observations == ["Image 2: the timestamp differs from the status bar"]
    assert result.extraction_failed is False


def test_terms_only_match_whole_words(fake_llm):
    summary = "Paid 25000 at the Thiefville market; the post mentions escroquerie prevention."
    observation = "Image 1: the fraudulently-styled logo is blurred"
    fake_llm.responses[PURPOSE] = [payload(summary=summary, tamper_observations=[observation])]

    result = extract()

    assert result.summary_filtered is False
    assert result.summary == summary
    assert result.tamper_observations == [observation]


def test_neutral_output_is_not_filtered(fake_llm):
    fake_llm.responses[PURPOSE] = [payload()]

    result = extract()

    assert result.summary_filtered is False
    assert result.summary == "Payment sent for a phone that never arrived."


def test_very_tall_screenshots_are_shrunk_only_to_the_api_side_limit(fake_llm):
    from tchekam.ai.extraction import MAX_IMAGE_BYTES, MAX_SIDE_SENT

    fake_llm.responses[PURPOSE] = [payload(evidence_kinds=["chat"])]
    tall = encoded("JPEG", size=(1080, 9000))
    assert len(tall) < MAX_IMAGE_BYTES

    extract(images=[(tall, "image/jpeg")])

    [(media_type, image)] = sent_images(fake_llm)
    assert media_type == "image/jpeg"
    assert max(image.size) == MAX_SIDE_SENT == 7500
    assert image.size == (900, 7500)  # aspect ratio kept


def test_tall_screenshots_within_the_limit_are_sent_unchanged(fake_llm):
    fake_llm.responses[PURPOSE] = [payload(evidence_kinds=["chat"])]
    tall = encoded("JPEG", size=(1080, 6000))

    extract(images=[(tall, "image/jpeg")])

    block = fake_llm.calls[0]["user_content"][0]
    assert base64.b64decode(block["source"]["data"]) == tall
