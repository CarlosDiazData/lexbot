"""retrieve_knowledge tool contract tests (TOOL-1, TOOL-5)."""

import json

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt import ToolNode

from lexbot_agent.tools import build_tools
from lexbot_ingest.chunker import Chunk
from lexbot_ingest.embeddings import FakeEmbedder
from lexbot_ingest.vector_store import VectorStore


def _store(tmp_path) -> VectorStore:
    return VectorStore(path=str(tmp_path / "chroma"), embedder=FakeEmbedder())


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
    [tool] = build_tools(store)
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
    [tool] = build_tools(store)
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
    [tool] = build_tools(store, docs_dir=docs)
    result = tool.invoke({"query": "advance payment"})
    assert store.count() > 0, "auto-seed should ingest the seed doc"
    assert result["results"]


def test_retrieve_knowledge_empty_results_when_nothing_to_seed(tmp_path):
    empty_docs = tmp_path / "empty_docs"
    empty_docs.mkdir()
    store = _store(tmp_path)
    [tool] = build_tools(store, docs_dir=empty_docs)
    result = tool.invoke({"query": "anything at all"})
    assert result == {"results": []}