"""Thin wrapper around fastembed for text embedding."""

import numpy as np
from fastembed import TextEmbedding

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384


class Embedder:
    """Lazy-loading text embedder backed by fastembed + ONNX Runtime."""

    def __init__(self) -> None:
        self._model: TextEmbedding | None = None

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        if self._model is None:
            self._model = TextEmbedding(MODEL_NAME)
        return list(self._model.embed(texts))
