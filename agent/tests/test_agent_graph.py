"""Agent graph path tests (AGENT-1, AGENT-2) with FakeLLM + tmp chroma.

FakeLLM scripts the LLM: one AIMessage per invoke. Tool-call path needs two
responses (classify emits the tool_call, compose emits the final answer);
decline paths need one (classify) because compose declines deterministically.
"""

from langchain_core.messages import AIMessage, HumanMessage

from lexbot_agent.graph import build_agent
from lexbot_agent.llm import FakeLLM
from lexbot_ingest.chunker import Chunk
from lexbot_ingest.embeddings import FakeEmbedder
from lexbot_ingest.vector_store import VectorStore


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
    assert any(a["type"] == "notify_whatsapp" for a in final["actions"])