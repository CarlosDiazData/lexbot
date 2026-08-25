"""API endpoint tests (API-1/2/3, D5, D6) with injected fakes.

No Docker, no live LLM, no live PG: create_app's DI takes a fake agent
(FakeAgent), a duck-typed store (FakeStore) or a real tmp-chroma VectorStore
with FakeEmbedder, and a fake Database (FakeDb). The lifespan runs inside
TestClient, so the D5 schema apply and D6 auto-seed are exercised for real.
"""

import json

import httpx
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from lexbot_api.app import create_app
from lexbot_api.routers.telegram import UpdateIdCache
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


# --- CORS (API-4) -------------------------------------------------------------

def test_cors_preflight_default_origin_echoes_allow_origin(tmp_path, monkeypatch):
    """API-4.1: CORS_ORIGINS unset → preflight from http://localhost:5173
    (the default) gets HTTP 200 with Access-Control-Allow-Origin echoed."""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    app = create_app(
        agent=FakeAgent(), store=FakeStore(count=1), db=FakeDb(), knowledge_dir=tmp_path
    )
    with TestClient(app) as client:
        resp = client.options(
            "/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_preflight_disallowed_origin_gets_no_allow_headers(tmp_path, monkeypatch):
    """API-4.2: an origin outside CORS_ORIGINS must not receive CORS allow
    headers. starlette answers the disallowed preflight with 400 and no
    Access-Control-Allow-Origin."""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    app = create_app(
        agent=FakeAgent(), store=FakeStore(count=1), db=FakeDb(), knowledge_dir=tmp_path
    )
    with TestClient(app) as client:
        resp = client.options(
            "/chat",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert resp.status_code == 400
    assert "access-control-allow-origin" not in resp.headers


def test_cors_comma_split_origins_all_echoed(tmp_path, monkeypatch):
    """D9: CORS_ORIGINS is a comma-separated list; every configured origin is
    allowed and echoed back on preflight."""
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, http://localhost:4173")
    app = create_app(
        agent=FakeAgent(), store=FakeStore(count=1), db=FakeDb(), knowledge_dir=tmp_path
    )
    with TestClient(app) as client:
        for origin in ("http://localhost:5173", "http://localhost:4173"):
            resp = client.options(
                "/chat",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                },
            )
            assert resp.status_code == 200
            assert resp.headers["access-control-allow-origin"] == origin


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


# --- POST /webhook/telegram (TG-1) -------------------------------------------

TELEGRAM_UPDATE = {
    "update_id": 101,
    "message": {"chat": {"id": 12345}, "text": "hello from telegram"},
}
TELEGRAM_SECRET = "topsecret"
SECRET_HEADER = {"X-Telegram-Bot-Api-Secret-Token": TELEGRAM_SECRET}
TELEGRAM_ANSWER = "According to 01-firm-policies.md, advance payment is required."


def _telegram_client(handler) -> httpx.AsyncClient:
    """AsyncClient on MockTransport for the TelegramClient DI seam (D4)."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_webhook_happy_path_replies_to_sender_chat(tmp_path, monkeypatch):
    agent = FakeAgent(result=_default_result())
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_URL", raising=False)
    app = create_app(
        agent=agent,
        store=FakeStore(count=1),
        db=FakeDb(),
        knowledge_dir=tmp_path,
        telegram_http_client=_telegram_client(handler),
    )

    with TestClient(app) as client:
        resp = client.post("/webhook/telegram", json=TELEGRAM_UPDATE, headers=SECRET_HEADER)

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # TG-1.1: the agent was invoked with the raw text as a HumanMessage.
    assert len(agent.inputs) == 1
    sent = agent.inputs[0]["messages"][0]
    assert isinstance(sent, HumanMessage)
    assert sent.content == "hello from telegram"
    # One sendMessage to the sender's chat, plain text, no parse_mode (TG-5.1).
    assert len(calls) == 1
    assert str(calls[0].url).endswith("/bot123:TESTTOKEN/sendMessage")
    assert json.loads(calls[0].content) == {"chat_id": 12345, "text": TELEGRAM_ANSWER}


def test_webhook_wrong_secret_returns_401_no_invocation(tmp_path, monkeypatch):
    agent = FakeAgent()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    app = create_app(
        agent=agent, store=FakeStore(count=1), db=FakeDb(), knowledge_dir=tmp_path
    )

    with TestClient(app) as client:
        resp = client.post(
            "/webhook/telegram",
            json=TELEGRAM_UPDATE,
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
        )

    assert resp.status_code == 401, "TG-1.2: wrong secret must be rejected"
    assert resp.json()["error"]["code"] == "unauthorized"
    assert agent.inputs == [], "no agent invocation on a rejected update"


def test_webhook_missing_secret_returns_401_no_invocation(tmp_path, monkeypatch):
    agent = FakeAgent()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    app = create_app(
        agent=agent, store=FakeStore(count=1), db=FakeDb(), knowledge_dir=tmp_path
    )

    with TestClient(app) as client:
        resp = client.post("/webhook/telegram", json=TELEGRAM_UPDATE)

    assert resp.status_code == 401, "TG-1.2: missing header must be rejected"
    assert resp.json()["error"]["code"] == "unauthorized"
    assert agent.inputs == []


def test_webhook_fail_closed_when_secret_unset(tmp_path, monkeypatch):
    agent = FakeAgent()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    app = create_app(
        agent=agent, store=FakeStore(count=1), db=FakeDb(), knowledge_dir=tmp_path
    )

    with TestClient(app) as client:
        # Even a "correct" header must be rejected: the secret is unset, so
        # there is nothing to compare against (D5 fail closed).
        resp = client.post("/webhook/telegram", json=TELEGRAM_UPDATE, headers=SECRET_HEADER)

    assert resp.status_code == 401, "D5: unset secret rejects every update"
    assert agent.inputs == []


def test_webhook_duplicate_update_id_invoked_once(tmp_path, monkeypatch):
    agent = FakeAgent(result=_default_result())
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_URL", raising=False)
    app = create_app(
        agent=agent,
        store=FakeStore(count=1),
        db=FakeDb(),
        knowledge_dir=tmp_path,
        telegram_http_client=_telegram_client(handler),
    )

    with TestClient(app) as client:
        first = client.post("/webhook/telegram", json=TELEGRAM_UPDATE, headers=SECRET_HEADER)
        # Telegram retry: same update_id delivered again.
        second = client.post("/webhook/telegram", json=TELEGRAM_UPDATE, headers=SECRET_HEADER)

    assert first.status_code == 200 and second.status_code == 200
    assert len(agent.inputs) == 1, "TG-1.3: retry must not re-invoke the agent"
    assert len(calls) == 1, "TG-1.3: retry must not duplicate the reply"


def test_webhook_non_message_update_is_noop(tmp_path, monkeypatch):
    agent = FakeAgent()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_URL", raising=False)
    app = create_app(
        agent=agent,
        store=FakeStore(count=1),
        db=FakeDb(),
        knowledge_dir=tmp_path,
        telegram_http_client=_telegram_client(handler),
    )

    update = {"update_id": 102, "message": {"chat": {"id": 12345}}}  # no text
    with TestClient(app) as client:
        resp = client.post("/webhook/telegram", json=update, headers=SECRET_HEADER)

    assert resp.status_code == 200, "TG-1.4: non-message update is acknowledged"
    assert agent.inputs == [], "TG-1.4: no agent run for non-message updates"
    assert calls == [], "TG-1.4: no reply for non-message updates"


def test_webhook_no_token_acknowledges_without_processing(tmp_path, monkeypatch):
    agent = FakeAgent()
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    app = create_app(
        agent=agent, store=FakeStore(count=1), db=FakeDb(), knowledge_dir=tmp_path
    )

    with TestClient(app) as client:
        resp = client.post("/webhook/telegram", json=TELEGRAM_UPDATE, headers=SECRET_HEADER)

    assert resp.status_code == 200, "TG-3.1: stub mode acknowledges"
    assert agent.inputs == [], "TG-3.1: stub mode never processes or replies"


def test_update_id_cache_evicts_fifo_at_maxsize():
    cache = UpdateIdCache(maxsize=3)
    for i in range(4):
        assert cache.check(i) is False, "fresh update_id is recorded"
    # FIFO: 0 was evicted when 3 arrived; 1..3 remain cached.
    assert cache.check(1) is True
    assert cache.check(2) is True
    assert cache.check(3) is True
    assert cache.check(0) is False, "D2: evicted id is treated as fresh again"


# --- Lifespan setWebhook guard (D1) ------------------------------------------

def test_lifespan_setwebhook_when_token_and_url_set(tmp_path, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com/webhook/telegram")
    app = create_app(
        agent=FakeAgent(),
        store=FakeStore(count=1),
        db=FakeDb(),
        knowledge_dir=tmp_path,
        telegram_http_client=_telegram_client(handler),
    )

    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert len(calls) == 1, "D1: setWebhook called once at startup"
    assert str(calls[0].url).endswith("/bot123:TESTTOKEN/setWebhook")
    assert json.loads(calls[0].content) == {"url": "https://example.com/webhook/telegram"}


def test_lifespan_skips_setwebhook_when_token_unset(tmp_path, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com/webhook/telegram")
    app = create_app(
        agent=FakeAgent(),
        store=FakeStore(count=1),
        db=FakeDb(),
        knowledge_dir=tmp_path,
        telegram_http_client=_telegram_client(handler),
    )

    with TestClient(app) as client:
        client.get("/health")

    assert calls == [], "D1: no setWebhook without a bot token"


def test_lifespan_skips_setwebhook_when_url_unset(tmp_path, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_URL", raising=False)
    app = create_app(
        agent=FakeAgent(),
        store=FakeStore(count=1),
        db=FakeDb(),
        knowledge_dir=tmp_path,
        telegram_http_client=_telegram_client(handler),
    )

    with TestClient(app) as client:
        client.get("/health")

    assert calls == [], "D1: no setWebhook without a webhook URL"


def test_lifespan_setwebhook_non2xx_keeps_booting(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False, "description": "boom"})

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com/webhook/telegram")
    app = create_app(
        agent=FakeAgent(),
        store=FakeStore(count=1),
        db=FakeDb(),
        knowledge_dir=tmp_path,
        telegram_http_client=_telegram_client(handler),
    )

    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200, "D1 fail-soft: non-2xx setWebhook keeps booting"


def test_lifespan_setwebhook_transport_error_keeps_booting(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com/webhook/telegram")
    app = create_app(
        agent=FakeAgent(),
        store=FakeStore(count=1),
        db=FakeDb(),
        knowledge_dir=tmp_path,
        telegram_http_client=_telegram_client(handler),
    )

    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200, "D1 fail-soft: transport error keeps booting"
