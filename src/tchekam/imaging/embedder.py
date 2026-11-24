"""Image embeddings behind a small interface. Only this module may import torch or open_clip."""

import threading
from typing import Protocol

import numpy as np
from django.conf import settings
from PIL import Image as PILImage

from . import hashing
from .models import EMBEDDING_DIM


class Embedder(Protocol):
    def embed(self, image: PILImage.Image) -> list[float]:
        """A unit-length vector of EMBEDDING_DIM floats."""
        ...


class FakeEmbedder:
    """Deterministic stand-in for tests: each of the 64 pHash bits becomes +-1 over 8 dimensions.

    Cosine similarity is 1 - d/32 for pHashes at Hamming distance d, so near-duplicates stay close.
    """

    def embed(self, image: PILImage.Image) -> list[float]:
        value = hashing.to_unsigned(hashing.phash(image))
        bits = np.array([(value >> i) & 1 for i in range(64)], dtype=np.float64)
        vector = np.repeat(bits * 2 - 1, EMBEDDING_DIM // 64)
        return (vector / np.linalg.norm(vector)).tolist()


class OpenClipEmbedder:
    """ViT-B-32 (laion2b_s34b_b79k) on CPU. The model loads on first use, once per process."""

    MODEL = "ViT-B-32"
    PRETRAINED = "laion2b_s34b_b79k"
    _lock = threading.Lock()
    _loaded: tuple | None = None

    @classmethod
    def _load(cls):
        with cls._lock:
            if cls._loaded is None:
                import open_clip  # heavy: deliberately imported lazily
                import torch

                model, _, preprocess = open_clip.create_model_and_transforms(
                    cls.MODEL, pretrained=cls.PRETRAINED, device="cpu"
                )
                model.eval()
                cls._loaded = (model, preprocess, torch)
            return cls._loaded

    def embed(self, image: PILImage.Image) -> list[float]:
        model, preprocess, torch = self._load()
        with torch.no_grad():
            features = model.encode_image(preprocess(image).unsqueeze(0))
            features = features / features.norm(dim=-1, keepdim=True)
        return features[0].tolist()


def get_embedder() -> Embedder:
    backend = settings.EMBEDDER_BACKEND
    if backend == "fake":
        return FakeEmbedder()
    if backend == "openclip":
        return OpenClipEmbedder()
    raise ValueError(f"Unknown EMBEDDER_BACKEND: {backend!r}")
