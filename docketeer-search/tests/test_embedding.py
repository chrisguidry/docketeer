"""Tests for the embedding wrapper."""

from unittest.mock import MagicMock, patch

import numpy as np

from docketeer_search.embedding import DIMENSIONS, MODEL_NAME, Embedder


def test_embed_lazy_loads_model():
    fake_model = MagicMock()
    fake_model.embed.return_value = [np.zeros(DIMENSIONS)]

    with patch(
        "docketeer_search.embedding.TextEmbedding", return_value=fake_model
    ) as cls:
        embedder = Embedder()
        assert embedder._model is None

        result = embedder.embed(["hello"])
        cls.assert_called_once_with(MODEL_NAME)
        assert len(result) == 1

        embedder.embed(["again"])
        cls.assert_called_once()
