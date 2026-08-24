"""M1 embedding regression guards (REG-1: EMB-2)."""

import pytest

from lexbot_ingest.embeddings import build_embedder


def test_unknown_provider_raises_value_error():
    with pytest.raises(ValueError):
        build_embedder("bogus")