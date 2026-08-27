"""build_store() env-matrix tests (AWS-11, PGV-1).

Proves STORE_PROVIDER dispatch without a live DB or real Chroma writes:
DEFAULT_CHROMA_PATH is redirected to a tmp dir and the PgVectorStore symbol is
stubbed to a recorder so the pgvector branch is proven by the factory's
dispatcher — PgVectorStore itself is covered by the ingest store tests.
"""

import pytest

from lexbot_ingest import vector_store as vs
from lexbot_ingest.vector_store import VectorStore, build_store


@pytest.fixture()
def iso_env(monkeypatch, tmp_path):
    """Isolated env + tmp chroma path; no STORE_PROVIDER / DATABASE_URL set."""
    monkeypatch.delenv("STORE_PROVIDER", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(vs, "DEFAULT_CHROMA_PATH", str(tmp_path / "chroma"))
    # No API keys -> build_embedder falls back to FakeEmbedder (no network).
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


class FakePgVectorStore:
    """Records the dsn passed by the factory for the pgvector branch."""

    def __init__(self, dsn, embedder, **kwargs):
        self.dsn = dsn
        self.embedder = embedder
        self.kwargs = kwargs


def test_unset_defaults_to_chroma(iso_env):
    store = build_store()
    assert isinstance(store, VectorStore)


def test_chroma_explicit(iso_env, monkeypatch):
    monkeypatch.setenv("STORE_PROVIDER", "chroma")
    store = build_store()
    assert isinstance(store, VectorStore)


def test_pgvector_with_dsn_builds_pgvector_store(iso_env, monkeypatch):
    monkeypatch.setenv("STORE_PROVIDER", "pgvector")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/lexbot")
    monkeypatch.setattr(vs, "PgVectorStore", FakePgVectorStore)
    store = build_store()
    assert isinstance(store, FakePgVectorStore)
    assert store.dsn == "postgresql://u:p@db:5432/lexbot"


def test_pgvector_without_dsn_falls_back_to_chroma(iso_env, monkeypatch):
    monkeypatch.setenv("STORE_PROVIDER", "pgvector")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = build_store()
    assert isinstance(store, VectorStore)


def test_unknown_provider_raises(iso_env, monkeypatch):
    monkeypatch.setenv("STORE_PROVIDER", "bogus")
    with pytest.raises(ValueError):
        build_store()
