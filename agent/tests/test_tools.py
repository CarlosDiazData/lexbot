"""Agent tool contract tests (TOOL-1..TOOL-5).

SQL tools (search_case, register_follow_up) are exercised against a duck-typed
FakeDatabase that raises real psycopg exceptions to prove the DB-down error
JSON path without a live PostgreSQL — the Database SQL itself is verified
against compose PG at unit 6 E2E (Docker daemon unavailable on this host).
notify_telegram uses httpx.MockTransport (no live Telegram, design D7).
"""

import json

import httpx
import psycopg
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt import ToolNode

from lexbot_agent.tools import CaseNotFoundError, build_tools
from lexbot_ingest.chunker import Chunk
from lexbot_ingest.embeddings import FakeEmbedder
from lexbot_ingest.vector_store import VectorStore


class FakeDatabase:
    """Duck-typed Database: records calls, raises real psycopg exceptions to
    exercise the tool's error translation without a live PG."""

    def __init__(self, cases=None, fail_with=None):
        self.cases = cases or []
        self.fail_with = fail_with
        self.inserts = []

    def search_cases(self, query):
        if self.fail_with is not None:
            raise self.fail_with
        q = query.lower()
        return [
            c
            for c in self.cases
            if q in c["case_number"].lower() or q in c["client_name"].lower()
        ]

    def insert_follow_up(self, case_number, description, due_date):
        if self.fail_with is not None:
            raise self.fail_with
        if not any(c["case_number"] == case_number for c in self.cases):
            raise CaseNotFoundError(case_number)
        self.inserts.append(
            {"case_number": case_number, "description": description, "due_date": due_date}
        )
        return 42


def _store(tmp_path) -> VectorStore:
    return VectorStore(path=str(tmp_path / "chroma"), embedder=FakeEmbedder())


def _tools(store, **kwargs):
    return build_tools(store, **kwargs)


def _tool_node(tools):
    return ToolNode(tools)


def _tool_call(name: str, args: dict, call_id: str = "call_1") -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def test_retrieve_knowledge_returns_ranked_chunks(tmp_path):
    store = _store(tmp_path)
    store.add_chunks(
        [
            Chunk(
                text="Billing policies require advance payment for new engagements.",
                source="01-firm-policies.md",
                index=0,
            ),
            Chunk(text="Parking is free for employees.", source="02-faq-clients.md", index=0),
        ]
    )
    [tool, *_] = build_tools(store)
    result = tool.invoke({"query": "billing policy advance payment"})
    assert set(result) == {"results"}
    assert result["results"], "expected at least one ranked chunk"
    first = result["results"][0]
    assert set(first) == {"id", "text", "source", "distance"}
    assert first["source"] == "01-firm-policies.md"
    assert "billing" in first["text"].lower()


def test_retrieve_knowledge_json_contract_and_toolmessage(tmp_path):
    store = _store(tmp_path)
    store.add_chunks([Chunk(text="Confidentiality rules apply to all files.", source="a.md", index=0)])
    [tool, *_] = build_tools(store)
    result = tool.invoke({"query": "confidentiality"})
    # TOOL-5: parseable structured JSON, no free text.
    assert json.loads(json.dumps(result)) == result
    # ToolNode wraps the dict in a ToolMessage whose content is JSON-parseable.
    node = ToolNode([tool])
    state = node.invoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "retrieve_knowledge",
                            "args": {"query": "confidentiality"},
                            "id": "call_1",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        }
    )
    tool_message = state["messages"][-1]
    assert isinstance(tool_message, ToolMessage)
    payload = json.loads(tool_message.content) if isinstance(tool_message.content, str) else tool_message.content
    assert "results" in payload


def test_retrieve_knowledge_auto_seeds_empty_collection(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "seed.md").write_text(
        "The firm requires advance payment for all new engagements."
    )
    store = _store(tmp_path)
    assert store.count() == 0
    [tool, *_] = build_tools(store, docs_dir=docs)
    result = tool.invoke({"query": "advance payment"})
    assert store.count() > 0, "auto-seed should ingest the seed doc"
    assert result["results"]


def test_retrieve_knowledge_empty_results_when_nothing_to_seed(tmp_path):
    empty_docs = tmp_path / "empty_docs"
    empty_docs.mkdir()
    store = _store(tmp_path)
    [tool, *_] = build_tools(store, docs_dir=empty_docs)
    result = tool.invoke({"query": "anything at all"})
    assert result == {"results": []}


# --- search_case (TOOL-2) ---------------------------------------------------

def test_search_case_returns_matching_cases(tmp_path):
    store = _store(tmp_path)
    db = FakeDatabase(
        cases=[
            {
                "case_number": "CASE-1001",
                "client_name": "Acme Corp",
                "status": "open",
                "summary": "Breach of contract claim.",
            },
            {
                "case_number": "CASE-1002",
                "client_name": "Beta Ltd",
                "status": "closed",
                "summary": "Employment dispute.",
            },
        ]
    )
    [_, search_case, _, _] = _tools(store, db=db)
    result = search_case.invoke({"query": "acme"})
    assert set(result) == {"cases"}
    assert len(result["cases"]) == 1
    case = result["cases"][0]
    assert case == {
        "case_number": "CASE-1001",
        "client_name": "Acme Corp",
        "status": "open",
        "summary": "Breach of contract claim.",
    }


def test_search_case_db_down_returns_error_json(tmp_path):
    store = _store(tmp_path)
    db = FakeDatabase(fail_with=psycopg.OperationalError("connection refused"))
    [_, search_case, _, _] = _tools(store, db=db)
    result = search_case.invoke({"query": "acme"})
    # TOOL-5: DB down -> structured error JSON, tool does not raise.
    assert set(result) == {"error"}
    assert result["error"]["code"] == "db_unavailable"
    assert result["error"]["retryable"] is True


# --- register_follow_up (TOOL-3) --------------------------------------------

def test_register_follow_up_inserts_and_returns_id(tmp_path):
    store = _store(tmp_path)
    db = FakeDatabase(cases=[{"case_number": "CASE-1001", "client_name": "Acme Corp"}])
    [_, _, register_follow_up, _] = _tools(store, db=db)
    result = register_follow_up.invoke(
        {"case_number": "CASE-1001", "description": "Call client re: settlement", "due_date": "2026-09-01"}
    )
    assert result == {"id": 42}
    # Insert verified: one row recorded with the exact args passed through.
    assert db.inserts == [
        {
            "case_number": "CASE-1001",
            "description": "Call client re: settlement",
            "due_date": "2026-09-01",
        }
    ]


def test_register_follow_up_due_date_optional(tmp_path):
    store = _store(tmp_path)
    db = FakeDatabase(cases=[{"case_number": "CASE-1001", "client_name": "Acme Corp"}])
    [_, _, register_follow_up, _] = _tools(store, db=db)
    result = register_follow_up.invoke(
        {"case_number": "CASE-1001", "description": "Send draft contract"}
    )
    assert result == {"id": 42}
    assert db.inserts[0]["due_date"] is None


def test_register_follow_up_unknown_case_returns_error_json(tmp_path):
    store = _store(tmp_path)
    db = FakeDatabase(cases=[{"case_number": "CASE-1001", "client_name": "Acme Corp"}])
    [_, _, register_follow_up, _] = _tools(store, db=db)
    result = register_follow_up.invoke(
        {"case_number": "CASE-9999", "description": "Follow up"}
    )
    assert result["error"]["code"] == "case_not_found"
    assert result["error"]["retryable"] is False


def test_register_follow_up_db_down_returns_error_json(tmp_path):
    store = _store(tmp_path)
    db = FakeDatabase(fail_with=psycopg.OperationalError("connection refused"))
    [_, _, register_follow_up, _] = _tools(store, db=db)
    result = register_follow_up.invoke(
        {"case_number": "CASE-1001", "description": "Follow up"}
    )
    assert set(result) == {"error"}
    assert result["error"]["code"] == "db_unavailable"
    assert result["error"]["retryable"] is True


# --- notify_telegram (TOOL-4) ------------------------------------------------

def test_notify_telegram_stub_when_no_token(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    store = _store(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("stub mode must not send requests")

    transport = httpx.MockTransport(handler)
    [_, _, _, notify_telegram] = _tools(
        store, http_client=httpx.Client(transport=transport)
    )
    result = notify_telegram.invoke({"chat_id": "123456", "message": "Hello"})
    assert result == {"status": "stub"}


def test_notify_telegram_posts_sendmessage(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    store = _store(tmp_path)
    [_, _, _, notify_telegram] = _tools(
        store, http_client=httpx.Client(transport=transport), bot_token="TEST_TOKEN"
    )
    result = notify_telegram.invoke({"chat_id": "123456", "message": "Hello"})
    assert result == {"status": "sent"}
    assert captured["url"] == "https://api.telegram.org/botTEST_TOKEN/sendMessage"
    assert captured["json"] == {"chat_id": "123456", "text": "Hello"}
    # TG-5.1: plain text — no parse_mode in the sendMessage body.
    assert "parse_mode" not in captured["json"]


def test_notify_telegram_rate_limited_returns_retry_after(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry after 30",
                "parameters": {"retry_after": 30},
            },
        )

    transport = httpx.MockTransport(handler)
    store = _store(tmp_path)
    [_, _, _, notify_telegram] = _tools(
        store, http_client=httpx.Client(transport=transport), bot_token="TEST_TOKEN"
    )
    result = notify_telegram.invoke({"chat_id": "123456", "message": "Hello"})
    assert set(result) == {"error"}
    assert result["error"]["code"] == "telegram_rate_limited"
    assert result["error"]["retryable"] is True
    assert result["error"]["retry_after"] == 30


def test_notify_telegram_unknown_chat_returns_error_json(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "ok": False,
                "error_code": 400,
                "description": "Bad Request: chat not found",
            },
        )

    transport = httpx.MockTransport(handler)
    store = _store(tmp_path)
    [_, _, _, notify_telegram] = _tools(
        store, http_client=httpx.Client(transport=transport), bot_token="TEST_TOKEN"
    )
    result = notify_telegram.invoke({"chat_id": "999", "message": "Hello"})
    assert set(result) == {"error"}
    assert result["error"]["code"] == "chat_not_found"
    assert result["error"]["retryable"] is False


def test_notify_telegram_missing_chat_id_returns_error_json(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("missing chat_id must not send a request")

    transport = httpx.MockTransport(handler)
    store = _store(tmp_path)
    [_, _, _, notify_telegram] = _tools(
        store, http_client=httpx.Client(transport=transport), bot_token="TEST_TOKEN"
    )
    result = notify_telegram.invoke({"chat_id": "", "message": "Hello"})
    assert set(result) == {"error"}
    assert result["error"]["code"] == "chat_id_missing"
    assert result["error"]["retryable"] is False


def test_notify_telegram_falls_back_to_env_chat_id(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    store = _store(tmp_path)
    [_, _, _, notify_telegram] = _tools(
        store, http_client=httpx.Client(transport=transport), bot_token="TEST_TOKEN"
    )
    result = notify_telegram.invoke({"chat_id": "", "message": "Hello"})
    assert result == {"status": "sent"}
    assert captured["json"]["chat_id"] == "987654"


def test_notify_telegram_unreachable_returns_error_json(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    store = _store(tmp_path)
    [_, _, _, notify_telegram] = _tools(
        store, http_client=httpx.Client(transport=transport), bot_token="TEST_TOKEN"
    )
    result = notify_telegram.invoke({"chat_id": "123456", "message": "Hello"})
    assert set(result) == {"error"}
    assert result["error"]["code"] == "telegram_unreachable"
    assert result["error"]["retryable"] is True


# --- TOOL-5: JSON-only contract through ToolNode ------------------------------

def test_database_apply_schema_executes_each_statement(monkeypatch, tmp_path):
    """D5: apply_schema runs db/init.sql statement-by-statement (psycopg3
    executes one statement per cursor.execute). Verifies the split logic with
    a fake connection — no live PG needed."""
    import lexbot_agent.tools as tools_module

    executed = []

    class FakeCursor:
        def __init__(self):
            self._rows = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql):
            executed.append(sql)

    class FakeConn:
        def __init__(self):
            self._cursor = FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return self._cursor

    init_sql = tmp_path / "init.sql"
    init_sql.write_text(
        "CREATE TABLE IF NOT EXISTS cases (id SERIAL PRIMARY KEY);\n"
        "CREATE TABLE IF NOT EXISTS follow_ups (id SERIAL PRIMARY KEY);\n"
    )

    db = tools_module.Database(dsn="postgresql://fake")
    monkeypatch.setattr(db, "_connect", lambda: FakeConn())
    db.apply_schema(init_sql)

    assert len(executed) == 2
    assert "CREATE TABLE IF NOT EXISTS cases" in executed[0]
    assert "CREATE TABLE IF NOT EXISTS follow_ups" in executed[1]


def test_database_ping_reports_reachability(monkeypatch):
    """API health: ping() returns True on SELECT 1, False on psycopg error."""
    import lexbot_agent.tools as tools_module

    class FakeCursor:
        def __init__(self):
            self._rows = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql):
            pass

    class FakeConn:
        def __init__(self):
            self._cursor = FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return self._cursor

    db = tools_module.Database(dsn="postgresql://fake")
    monkeypatch.setattr(db, "_connect", lambda: FakeConn())
    assert db.ping() is True

    def broken_connect():
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(db, "_connect", broken_connect)
    assert db.ping() is False


def test_all_tools_json_contract_and_toolmessage(tmp_path, monkeypatch):
    """Every tool returns JSON-parseable structured output, and ToolNode wraps
    each one in a ToolMessage whose content is JSON-parseable — the agent
    continues on tool results without parsing free text (TOOL-5)."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    store = _store(tmp_path)
    db = FakeDatabase(
        cases=[
            {
                "case_number": "CASE-1001",
                "client_name": "Acme Corp",
                "status": "open",
                "summary": "Breach of contract claim.",
            }
        ]
    )
    tools = _tools(store, db=db)
    node = _tool_node(tools)

    calls = [
        _tool_call("retrieve_knowledge", {"query": "confidentiality"}, "call_1"),
        _tool_call("search_case", {"query": "acme"}, "call_2"),
        _tool_call("register_follow_up", {"case_number": "CASE-1001", "description": "Follow up"}, "call_3"),
        _tool_call("notify_telegram", {"chat_id": "123456", "message": "Hello"}, "call_4"),
    ]
    state = node.invoke(
        {
            "messages": [
                AIMessage(content="", tool_calls=calls),
            ]
        }
    )
    tool_messages = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 4
    for message in tool_messages:
        payload = json.loads(message.content) if isinstance(message.content, str) else message.content
        assert isinstance(payload, dict)
        assert json.loads(json.dumps(payload)) == payload


def test_sql_tools_db_down_json_passes_through_toolnode(tmp_path):
    """DB down -> error JSON still flows through ToolNode as a ToolMessage so
    the graph can compose a graceful answer (TOOL-5, agent continues)."""
    store = _store(tmp_path)
    db = FakeDatabase(fail_with=psycopg.OperationalError("connection refused"))
    [_, search_case, _, _] = _tools(store, db=db)
    node = _tool_node([search_case])
    state = node.invoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[_tool_call("search_case", {"query": "acme"})],
                )
            ]
        }
    )
    tool_message = state["messages"][-1]
    assert isinstance(tool_message, ToolMessage)
    payload = json.loads(tool_message.content) if isinstance(tool_message.content, str) else tool_message.content
    assert payload["error"]["code"] == "db_unavailable"