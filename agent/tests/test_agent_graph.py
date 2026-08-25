"""Agent graph path tests (AGENT-1, AGENT-2) with FakeLLM + tmp chroma.

FakeLLM scripts the LLM: one AIMessage per invoke. Tool-call path needs two
responses (classify emits the tool_call, compose emits the final answer);
decline and non-knowledge paths need one (classify) because compose composes
deterministically from the tool JSON payload.
"""

import psycopg
from langchain_core.messages import AIMessage, HumanMessage

from lexbot_agent.graph import build_agent
from lexbot_agent.llm import FakeLLM
from lexbot_ingest.chunker import Chunk
from lexbot_ingest.embeddings import FakeEmbedder
from lexbot_ingest.vector_store import VectorStore


class FakeDatabase:
    """Minimal duck-typed Database for graph-level SQL intent tests (mirrors
    the richer fake in test_tools.py; kept local to avoid import-mode
    coupling between the two test modules)."""

    def __init__(self, cases=None, fail_with=None):
        self.cases = cases or []
        self.fail_with = fail_with

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
            from lexbot_agent.tools import CaseNotFoundError

            raise CaseNotFoundError(case_number)
        return 42


def _store(tmp_path) -> VectorStore:
    store = VectorStore(path=str(tmp_path / "chroma"), embedder=FakeEmbedder())
    store.add_chunks(
        [
            Chunk(
                text="The firm requires advance payment for engagements over $5k.",
                source="01-firm-policies.md",
                index=0,
            ),
            Chunk(
                text="Client onboarding requires a signed engagement letter.",
                source="02-faq-clients.md",
                index=0,
            ),
        ]
    )
    return store


def _tool_call(name: str, args: dict, call_id: str = "call_1") -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def test_tool_call_routes_to_tools_and_cites_sources(tmp_path):
    store = _store(tmp_path)
    llm = FakeLLM(
        responses=[
            AIMessage(
                content="",
                tool_calls=[_tool_call("retrieve_knowledge", {"query": "advance payment terms"})],
            ),
            AIMessage(
                content="According to 01-firm-policies.md, the firm requires advance payment for engagements over $5k."
            ),
        ]
    )
    app = build_agent(llm=llm, store=store)
    final = app.invoke({"messages": [HumanMessage(content="What are the payment terms?")]})

    assert final["intent"] == "knowledge"
    assert final["sources"], "retrieval used -> sources must be cited"
    assert final["sources"][0]["source"] == "01-firm-policies.md"
    assert any(a["type"] == "retrieve_knowledge" for a in final["actions"])
    last = final["messages"][-1]
    assert isinstance(last, AIMessage)
    assert "advance payment" in last.content.lower()


def test_no_tool_call_declines_gracefully(tmp_path):
    store = _store(tmp_path)
    llm = FakeLLM(responses=[AIMessage(content="Hello! How can I help?")])
    app = build_agent(llm=llm, store=store)
    final = app.invoke({"messages": [HumanMessage(content="What is the weather in Madrid?")]})

    assert final["intent"] == "out_of_scope"
    assert final["sources"] == []
    assert final["actions"] == []
    last = final["messages"][-1]
    assert isinstance(last, AIMessage)
    assert "outside my scope" in last.content.lower()


def test_empty_retrieval_declines_and_offers_notify(tmp_path):
    store = VectorStore(path=str(tmp_path / "chroma"), embedder=FakeEmbedder())
    empty_docs = tmp_path / "empty_docs"
    empty_docs.mkdir()
    llm = FakeLLM(
        responses=[
            AIMessage(
                content="",
                tool_calls=[_tool_call("retrieve_knowledge", {"query": "obscure tax ruling"})],
            )
        ]
    )
    app = build_agent(llm=llm, store=store, docs_dir=empty_docs)
    final = app.invoke({"messages": [HumanMessage(content="Tell me about that obscure ruling")]})

    last = final["messages"][-1]
    assert isinstance(last, AIMessage)
    assert "couldn't find" in last.content.lower()
    assert final["sources"] == []
    assert any(a["type"] == "notify_telegram" for a in final["actions"])


# --- Non-knowledge intents (case / follow_up / notify) compose per intent ---
# (carry-forward from WU3: these used to fall into the empty-retrieval decline.)

def test_case_search_intent_composes_case_answer(tmp_path):
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
    llm = FakeLLM(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("search_case", {"query": "acme"})])
        ]
    )
    app = build_agent(llm=llm, store=store, db=db)
    final = app.invoke({"messages": [HumanMessage(content="What is the status of case acme?")]})

    assert final["intent"] == "case"
    last = final["messages"][-1]
    assert isinstance(last, AIMessage)
    assert "CASE-1001" in last.content
    assert "open" in last.content
    assert "acme" in last.content.lower()
    assert final["sources"] == [], "no retrieval used -> sources empty (AGENT-2)"
    assert any(a["type"] == "search_case" for a in final["actions"])


def test_case_search_no_matches_composes_gracefully(tmp_path):
    store = _store(tmp_path)
    db = FakeDatabase(cases=[])
    llm = FakeLLM(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("search_case", {"query": "nope"})])
        ]
    )
    app = build_agent(llm=llm, store=store, db=db)
    final = app.invoke({"messages": [HumanMessage(content="Find case zzz")]})

    assert final["intent"] == "case"
    last = final["messages"][-1]
    assert isinstance(last, AIMessage)
    assert "couldn't find any matching cases" in last.content.lower()
    assert final["sources"] == []


def test_case_search_db_down_surfaces_error_gracefully(tmp_path):
    store = _store(tmp_path)
    db = FakeDatabase(fail_with=psycopg.OperationalError("connection refused"))
    llm = FakeLLM(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("search_case", {"query": "acme"})])
        ]
    )
    app = build_agent(llm=llm, store=store, db=db)
    final = app.invoke({"messages": [HumanMessage(content="What is the status of case acme?")]})

    # TOOL-5: error JSON is surfaced gracefully — the agent continues with a
    # deterministic answer instead of crashing or misdeclining.
    assert final["intent"] == "case"
    last = final["messages"][-1]
    assert isinstance(last, AIMessage)
    assert "unavailable" in last.content.lower()
    assert final["sources"] == []
    assert final["actions"][0]["detail"] == "error: db_unavailable"


def test_follow_up_intent_composes_confirmation(tmp_path):
    store = _store(tmp_path)
    db = FakeDatabase(cases=[{"case_number": "CASE-1001", "client_name": "Acme Corp"}])
    llm = FakeLLM(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call(
                        "register_follow_up",
                        {"case_number": "CASE-1001", "description": "Call client re: settlement"},
                    )
                ],
            )
        ]
    )
    app = build_agent(llm=llm, store=store, db=db)
    final = app.invoke(
        {"messages": [HumanMessage(content="Please follow up on CASE-1001")]}
    )

    assert final["intent"] == "follow_up"
    last = final["messages"][-1]
    assert isinstance(last, AIMessage)
    assert "follow-up registered" in last.content.lower()
    assert "42" in last.content
    assert final["sources"] == []
    assert final["actions"][0]["detail"] == "registered id 42"


def test_follow_up_unknown_case_surfaces_error_gracefully(tmp_path):
    store = _store(tmp_path)
    db = FakeDatabase(cases=[{"case_number": "CASE-1001", "client_name": "Acme Corp"}])
    llm = FakeLLM(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call(
                        "register_follow_up",
                        {"case_number": "CASE-9999", "description": "Follow up"},
                    )
                ],
            )
        ]
    )
    app = build_agent(llm=llm, store=store, db=db)
    final = app.invoke({"messages": [HumanMessage(content="Follow up on CASE-9999")]})

    assert final["intent"] == "follow_up"
    last = final["messages"][-1]
    assert isinstance(last, AIMessage)
    assert "couldn't find that case number" in last.content.lower()
    assert final["actions"][0]["detail"] == "error: case_not_found"


def test_notify_intent_composes_status(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    store = _store(tmp_path)
    llm = FakeLLM(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call(
                        "notify_telegram",
                        {"chat_id": "123456", "message": "Hello"},
                    )
                ],
            )
        ]
    )
    app = build_agent(llm=llm, store=store)
    final = app.invoke(
        {"messages": [HumanMessage(content="Notify the team about the meeting")]}
    )

    assert final["intent"] == "notify"
    last = final["messages"][-1]
    assert isinstance(last, AIMessage)
    assert "no telegram bot token" in last.content.lower()
    assert "stub" in last.content.lower()
    assert final["sources"] == []
    assert final["actions"][0]["detail"] == "stub"