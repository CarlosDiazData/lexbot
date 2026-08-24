"""API endpoint tests (API-1/2/3, D5, D6) with injected fakes.

No Docker, no live LLM, no live PG: create_app's DI takes a fake agent
(FakeAgent), a duck-typed store (FakeStore) or a real tmp-chroma VectorStore
with FakeEmbedder, and a fake Database (FakeDb). The lifespan runs inside
TestClient, so the D5 schema apply and D6 auto-seed are exercised for real.
"""

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from lexbot_api.app import create_app
from lexbot_ingest.chunker import Chunk
from lexbot_ingest.embeddings import FakeEmbedder
from lexbot_ingest.vector_store import VectorStore


class FakeAgent:
    """Injected agent: records the state it was invoked with; optionally
    raises so the /chat route's LLM-failure mapping can be proven."""

    def __init__(self, result=None, raise_exc=None):
        self.result = result or _default_result()
        self.raise_exc = raise_exc
        self.inputs = []

    async def ainvoke(self, state):
        self.inputs.append(state)
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.result


class FakeStore:
    """Duck-typed VectorStore for health tests: count + no-op add_chunks."""

    def __init__(self, count=0):
        self._count = count

    def count(self):
        return self._count

    def add_chunks(self, chunks):
        self._count += len(chunks)


class FakeDb:
    """Duck-typed Database: records apply_schema, reports ping status."""

    def __init__(self, ping_ok=True):
        self.ping_ok = ping_ok
        self.schema_applied = False
        self.schema_path = None

    def apply_schema(self, path=None):
        self.schema_applied = True
        self.schema_path = path

    def ping(self):
        return self.ping_ok


def _default_result() -> dict:
    return {
        "messages": [
            AIMessage(
                content="According to 01-firm-policies.md, advance payment is required."
            )
        ],
        "intent": "knowledge",
        "context": [],
        "sources": [
            {
                "id": "01-firm-policies.md:0",
                "text": "The firm requires advance payment.",
                "source": "01-firm-policies.md",
                "distance": 0.1,
            }
        ],
        "actions": [{"type": "retrieve_knowledge", "detail": "1 chunks retrieved"}],
    }


# --- POST /chat (API-1) -------------------------------------------------------

def test_chat_happy_path_returns_answer_sources_actions(tmp_path):
    agent = FakeAgent(result=_default_result())
    app = create_app(
        agent=agent, store=FakeStore(count=1), db=FakeDb(), knowledge_dir=tmp_path
    )
    with TestClient(app) as client:
        resp = client.post("/chat", json={"message": "What are the payment terms?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "According to 01-firm-policies.md, advance payment is required."
    assert body["sources"][0]["source"] == "01-firm-policies.md"
    assert body["actions"][0] == {"type": "retrieve_knowledge", "detail": "1 chunks retrieved"}
    # The agent received the raw message as a HumanMessage.
    sent = agent.inputs[0]["messages"][0]
    assert isinstance(sent, HumanMessage)
    assert sent.content == "What are the payment terms?"


def test_chat_llm_failure_returns_503_retryable(tmp_path):
    agent = FakeAgent(raise_exc=RuntimeError("llm api down"))
    app = create_app(
        agent=agent, store=FakeStore(count=1), db=FakeDb(), knowledge_dir=tmp_path
    )
    with TestClient(app) as client:
        resp = client.post("/chat", json={"message": "hello"})

    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "llm_unavailable"
    assert body["error"]["retryable"] is True
    assert "llm" in body["error"]["message"].lower()


# --- POST /ingest (API-2) -----------------------------------------------------

def test_ingest_populates_store(tmp_path):
    store = VectorStore(path=str(tmp_path / "chroma"), embedder=FakeEmbedder())
    # Pre-seed one chunk so the D6 startup auto-seed skips and /ingest's
    # response reflects only this call.
    store.add_chunks([Chunk(text="pre-existing chunk", source="pre.md", index=0)])
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "01-firm-policies.md").write_text(
        "The firm requires advance payment for engagements over $5k."
    )
    app = create_app(agent=FakeAgent(), store=store, db=FakeDb(), knowledge_dir=docs_dir)

    with TestClient(app) as client:
        resp = client.post("/ingest")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"documents": 1, "chunks": 1}
    assert store.count() == 2, "the doc chunk was added to the collection"


def test_ingest_empty_folder_is_noop(tmp_path):
    store = VectorStore(path=str(tmp_path / "chroma"), embedder=FakeEmbedder())
    store.add_chunks([Chunk(text="pre-existing chunk", source="pre.md", index=0)])
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    app = create_app(agent=FakeAgent(), store=store, db=FakeDb(), knowledge_dir=empty_dir)

    with TestClient(app) as client:
        resp = client.post("/ingest")

    assert resp.status_code == 200
    assert resp.json() == {"documents": 0, "chunks": 0}
    assert store.count() == 1, "no chunks added for an empty folder"


# --- GET /health (API-3) ------------------------------------------------------

def test_health_returns_status_vector_count_db(tmp_path):
    app = create_app(
        agent=FakeAgent(), store=FakeStore(count=7), db=FakeDb(ping_ok=True), knowledge_dir=tmp_path
    )
    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "vector_count": 7, "db": "ok"}


def test_health_reports_db_error_without_failing(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    app = create_app(
        agent=FakeAgent(),
        store=FakeStore(count=0),
        db=FakeDb(ping_ok=False),
        knowledge_dir=empty_dir,
    )
    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200, "API is up even when the db is down"
    assert resp.json()["db"] == "error"


# --- Lifespan (D5 schema apply + D6 auto-seed) --------------------------------

def test_startup_applies_schema_and_auto_seeds_when_empty(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "01-firm-policies.md").write_text(
        "The firm requires advance payment for engagements over $5k."
    )
    store = VectorStore(path=str(tmp_path / "chroma"), embedder=FakeEmbedder())
    fake_db = FakeDb()
    app = create_app(agent=FakeAgent(), store=store, db=fake_db, knowledge_dir=docs_dir)

    with TestClient(app) as client:
        resp = client.get("/health")

    assert fake_db.schema_applied is True, "D5: init.sql applied at startup"
    assert store.count() == 1, "D6: empty store auto-seeded from docs/knowledge"
    assert resp.status_code == 200
    assert resp.json()["vector_count"] == 1