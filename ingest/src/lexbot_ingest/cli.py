import argparse
from pathlib import Path

from dotenv import load_dotenv

from .chunker import chunk_text
from .embeddings import build_embedder
from .vector_store import VectorStore

DOC_EXTENSIONS = {".md", ".txt"}


def load_docs(docs_dir: Path) -> list[tuple[str, str]]:
    docs: list[tuple[str, str]] = []
    for path in sorted(docs_dir.rglob("*")):
        if path.is_file() and path.suffix in DOC_EXTENSIONS:
            # Basename only: the agent renders {source} as [source] citation
            # tags (graph.py) — a raw path would leak into user-facing answers.
            docs.append((path.name, path.read_text(encoding="utf-8")))
    return docs


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # DEV: honor .env.example quick-start (README documents cp .env.example .env)
    parser = argparse.ArgumentParser(description="Ingest legal docs into the vector store")
    parser.add_argument("--docs", required=True, type=Path, help="Directory with source documents")
    parser.add_argument("--db-path", default="./data/chroma", help="ChromaDB persistent path")
    parser.add_argument("--collection", default="legal_kb")
    parser.add_argument("--provider", default=None, help="openai | gemini | fake")
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--overlap", type=int, default=100)
    parser.add_argument("--reset", action="store_true", help="Drop and recreate the collection")
    args = parser.parse_args(argv)

    store = VectorStore(
        path=args.db_path,
        collection_name=args.collection,
        embedder=build_embedder(args.provider),
    )
    if args.reset:
        store.reset()

    docs = load_docs(args.docs)
    total = 0
    for source, text in docs:
        chunks = chunk_text(
            text, source=source, chunk_size=args.chunk_size, overlap=args.overlap
        )
        store.add_chunks(chunks)
        total += len(chunks)
        print(f"  {source}: {len(chunks)} chunks")
    print(f"Ingested {total} chunks from {len(docs)} documents into '{args.collection}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())