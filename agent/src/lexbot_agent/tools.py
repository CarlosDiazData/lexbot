"""Agent tools. TOOL-5 contract: every tool returns structured JSON (a dict),
never free text — ToolNode wraps the dict into a JSON ToolMessage.

WU2 ships retrieve_knowledge (TOOL-1). build_tools is a factory so tests can
inject a tmp Chroma store + FakeEmbedder (design D4 DI pattern).
"""

from pathlib import Path

from langchain_core.tools import tool

from lexbot_ingest.chunker import chunk_text
from lexbot_ingest.cli import load_docs
from lexbot_ingest.vector_store import VectorStore

# repo_root/docs/knowledge — agent/src/lexbot_agent/tools.py → parents[3]
DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "docs" / "knowledge"

RETRIEVAL_TOP_K = 3


def seed_knowledge(store: VectorStore, docs_dir: Path) -> int:
    """Ingest docs/knowledge into the store (design D6 auto-seed). Returns the
    number of chunks added. Idempotent by contract: caller only seeds when
    store.count() == 0.
    """
    total = 0
    for source, text in load_docs(docs_dir):
        chunks = chunk_text(text, source=source)
        store.add_chunks(chunks)
        total += len(chunks)
    return total


def build_tools(
    store: VectorStore,
    docs_dir: Path | None = None,
) -> list:
    """Build the tool list bound to a concrete store.

    docs_dir overrides the auto-seed source (defaults to docs/knowledge);
    tests pass an empty dir to exercise the empty-retrieval path.
    """
    knowledge_dir = docs_dir or DEFAULT_KNOWLEDGE_DIR

    @tool
    def retrieve_knowledge(query: str) -> dict:
        """Retrieve relevant firm knowledge chunks for a legal question. Use
        when the user asks about firm policies, client FAQs, or contract
        terms. Returns ranked chunks with source metadata."""
        # D6: dev convenience — seed once when the collection is empty so a
        # fresh store still answers. Seeding produced nothing (e.g. no docs
        # dir) -> empty retrieval, which the graph turns into a decline.
        if store.count() == 0:
            seed_knowledge(store, knowledge_dir)
        if store.count() == 0:
            return {"results": []}
        results = store.query(query, n_results=RETRIEVAL_TOP_K)
        return {
            "results": [
                {
                    "id": row["id"],
                    "text": row["text"],
                    "source": row["metadata"]["source"],
                    "distance": row["distance"],
                }
                for row in results
            ]
        }

    return [retrieve_knowledge]