"""PgVectorStore tests (AWS-9, PGV-2/PGV-4) — RED-first.

Requires a real PostgreSQL 15+ with the pgvector extension. The tests run
against a `legal_kb_embeddings` table created by the fixture with FakeEmbedder
dimensions (64), so they do not depend on the production 3072-dim DDL. When
TEST_DATABASE_URL is unset the whole module skips (CI gates the real run with a
pgvector/pgvector:pg15 service container).

Tests here mirror test_vector_store.py's Chroma coverage (same Chunk fixture)
so the pgvector return shape is proven identical to Chroma — tools.py reads
metadata.source / distance unchanged.
"""

import os

import psycopg
import pytest

from lexbot_ingest.chunker import Chunk
from lexbot_ingest.embeddings import FakeEmbedder
from lexbot_ingest.vector_store import PgVectorStore

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql://test:test@localhost:5432/test"
)
DIMS = 64

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL unset — requires a pgvector-enabled PostgreSQL",
)


@pytest.fixture()
def pg_store():
    """A PgVectorStore backed by a fresh vector(64) table (FakeEmbedder dims)."""
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                "CREATE TABLE IF NOT EXISTS legal_kb_embeddings ("
                "id BIGSERIAL PRIMARY KEY, "
                "chunk_id TEXT NOT NULL UNIQUE, "
                "source TEXT NOT NULL, "
                "chunk_index INT NOT NULL, "
                "text TEXT NOT NULL, "
                "embedding vector(64) NOT NULL, "
                "created_at TIMESTAMPTZ DEFAULT now())"
            )
    store = PgVectorStore(
        dsn=TEST_DATABASE_URL, embedder=FakeEmbedder(dimensions=DIMS), dimensions=DIMS
    )
    store.reset()  # TRUNCATE any rows left by a previous test
    yield store
    store.reset()


def _chunks():
    return [
        Chunk(text="confidentiality rules", source="a.md", index=0),
        Chunk(text="parking instructions", source="b.md", index=0),
    ]


def test_add_and_count(pg_store):
    pg_store.add_chunks([Chunk(text="billing policies", source="a.md", index=0)])
    assert pg_store.count() == 1


def test_query_returns_nearest_chunk_in_chroma_shape(pg_store):
    pg_store.add_chunks(_chunks())
    results = pg_store.query("confidentiality", n_results=1)
    assert len(results) == 1
    row = results[0]
    # Exact Chroma return shape: {id, text, metadata:{source, chunk_index}, distance}
    assert set(row) == {"id", "text", "metadata", "distance"}
    assert row["metadata"]["source"] == "a.md"
    assert row["metadata"]["chunk_index"] == 0
    assert row["id"] == "a.md:0"
    assert row["text"] == "confidentiality rules"
    assert isinstance(row["distance"], float)


def test_reset_empties_table(pg_store):
    pg_store.add_chunks([Chunk(text="anything", source="a.md", index=0)])
    assert pg_store.count() == 1
    pg_store.reset()
    assert pg_store.count() == 0


def test_duplicate_chunk_id_is_idempotent(pg_store):
    chunk = Chunk(text="billing policies", source="a.md", index=0)
    pg_store.add_chunks([chunk])
    pg_store.add_chunks([chunk])  # same chunk_id -> ON CONFLICT DO NOTHING
    assert pg_store.count() == 1, "re-adding the same chunk_id must not duplicate"


def test_dim_mismatch_raises_on_validation(pg_store):
    # The fixture table is vector(64); asking for 3072 dims must fail fast via
    # atttypmod validation instead of corrupting queries.
    with pytest.raises(ValueError):
        store = PgVectorStore(
            dsn=TEST_DATABASE_URL,
            embedder=FakeEmbedder(dimensions=DIMS),
            dimensions=3072,
        )
        store.validate_dimensions()

    with pytest.raises(ValueError):
        PgVectorStore(
            dsn=TEST_DATABASE_URL,
            embedder=FakeEmbedder(dimensions=DIMS),
            dimensions=3072,
            validate_at_init=True,
        )
