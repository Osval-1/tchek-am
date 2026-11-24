import numpy as np
import pytest

from tchekam.imaging import embedder
from tchekam.imaging.models import EMBEDDING_DIM

from .helpers import VARIANTS, structured_image


def cosine(a, b):
    return float(np.dot(a, b))


def test_fake_embedder_is_deterministic_normalised_512d():
    img = structured_image(4)
    first, second = embedder.FakeEmbedder().embed(img), embedder.FakeEmbedder().embed(img)
    assert first == second
    assert len(first) == EMBEDDING_DIM
    assert np.linalg.norm(first) == pytest.approx(1.0)


def test_fake_embedder_similar_phash_gives_similar_vectors():
    fake = embedder.FakeEmbedder()
    original = fake.embed(structured_image(4))
    near = fake.embed(VARIANTS["recompressed"](structured_image(4)))
    far = fake.embed(structured_image(2))
    assert cosine(original, near) > cosine(original, far)


def test_get_embedder_follows_settings(settings):
    assert isinstance(embedder.get_embedder(), embedder.FakeEmbedder)
    settings.EMBEDDER_BACKEND = "nope"
    with pytest.raises(ValueError):
        embedder.get_embedder()


@pytest.mark.ml
def test_open_clip_embeddings_match_variants_and_reject_unrelated():
    pytest.importorskip("open_clip")
    pytest.importorskip("torch")
    clip = embedder.OpenClipEmbedder()
    original_img = structured_image(4)
    original = clip.embed(original_img)
    assert len(original) == EMBEDDING_DIM
    assert np.linalg.norm(original) == pytest.approx(1.0, abs=1e-4)
    for name, make in VARIANTS.items():
        assert cosine(original, clip.embed(make(original_img))) >= 0.92, name
    assert cosine(original, clip.embed(structured_image(2))) < 0.92
