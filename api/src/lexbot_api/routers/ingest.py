"""POST /ingest — ingest docs/knowledge into the vector store (API-2).

Reuses the ingest package primitives unchanged: load_docs (md/txt files under
the knowledge dir), chunk_text (overlapping windows), VectorStore.add_chunks.
An empty folder is a no-op: {documents: 0, chunks: 0} and nothing added.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Request

from lexbot_ingest.chunker import chunk_text
from lexbot_ingest.cli import load_docs

from ..app import get_knowledge_dir, get_store
from ..schemas import IngestResponse

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: Request, store=Depends(get_store), knowledge_dir: Path = Depends(get_knowledge_dir)):
    documents = 0
    chunks = 0
    for source, text in load_docs(knowledge_dir):
        documents += 1
        new_chunks = chunk_text(text, source=source)
        store.add_chunks(new_chunks)
        chunks += len(new_chunks)
    return IngestResponse(documents=documents, chunks=chunks)