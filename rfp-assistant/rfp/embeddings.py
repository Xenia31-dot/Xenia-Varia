"""Embedding models behind one small interface.

To use another model, write a class with a `name` and an `embed()` method
and register it in `get_embedder()`.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class ChromaDefaultEmbedder:
    """Chroma's bundled all-MiniLM-L6-v2 (ONNX). Runs locally, no API key."""

    name = "minilm"

    def __init__(self) -> None:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        self._fn = DefaultEmbeddingFunction()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._fn(texts)]


class HashingEmbedder:
    """Bag-of-words hashing embedder. Fast and offline; used in tests."""

    name = "hashing"

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.md5(token.encode()).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            vec[index] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


def get_embedder(name: str) -> Embedder:
    if name in ("default", "minilm"):
        return ChromaDefaultEmbedder()
    if name == "hashing":
        return HashingEmbedder()
    raise ValueError(f"Unknown embedder: {name!r}")
