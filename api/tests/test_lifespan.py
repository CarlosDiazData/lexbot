"""Lifespan db-wait retry + pgvector conflict-safe seed tests (AWS-12/13, PGV-3/4).

Injects a small/instant _wait_for_db and fake dependencies so the retry/raise
loop and the unconditional pgvector seed are proven without a real database.
"""

import pytest
from fastapi.testclient import TestClient

from lexbot_api import app as app_mod
from lexbot_api.app import create_app, _wait_for_db
from lexbot_ingest.vector_store import PgVectorStore


class FakeAgent:
    def __init__(self):
        self.inputs = []

    async def ainvoke(self, state):
        return {"messages": [], "intent": "none", "context": [], "sources": [], "actions": []}


class FlakyDb:
    """ping() succeeds after `failures` failures; records apply_schema."""

    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0
        self.schema_applied = False

    def ping(self):
        self.calls += 1
        return self.calls > self.failures

    def apply_schema(self, path=None):
        self.schema_applied = True


class FakePgStore(PgVectorStore):
    """PgVectorStore duck-type that never touches a database."""

    def __init__(self, count=0):
        self._count = count
        self.seeded = False

    def count(self):
        return self._count

    def add_chunks(self, chunks):
        self._count += len(chunks)
        self.seeded = True


# --- _wait_for_db retry/raise (PGV-3) ----------------------------------------

def test_wait_for_db_retries_until_healthy(monkeypatch):
    monkeypatch.setattr(app_mod.time, "sleep", lambda s: None)
    db = FlakyDb(failures=2)
    _wait_for_db(db, attempts=5, base_delay=0.01, max_delay=0.02)
    assert db.calls == 3  # 2 failures then a successful ping


def test_wait_for_db_raises_on_exhaustion(monkeypatch):
    monkeypatch.setattr(app_mod.time, "sleep", lambda s: None)
    db = FlakyDb(failures=99)
    with pytest.raises(RuntimeError):
        _wait_for_db(db, attempts=3, base_delay=0.01, max_delay=0.02)
    assert db.calls == 3, "all attempts consumed before raising"


# --- lifespan: pgvector unconditional conflict-safe seed (PGV-4) -------------

def test_lifespan_pgvector_seeds_unconditionally(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_wait_for_db", lambda database, **k: None)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("the firm requires advance payment")
    store = FakePgStore(count=5)  # non-empty: chroma would skip, pgvector must seed
    app = create_app(agent=FakeAgent(), store=store, db=FlakyDb(), knowledge_dir=docs)

    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert store.seeded, "pgvector seed runs unconditionally (conflict-safe, idempotent)"


def test_health_reports_pgvector_store_count(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_wait_for_db", lambda database, **k: None)
    store = FakePgStore(count=7)
    app = create_app(agent=FakeAgent(), store=store, db=FlakyDb(), knowledge_dir=tmp_path)

    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["vector_count"] == 7
    assert resp.json()["db"] == "ok"
