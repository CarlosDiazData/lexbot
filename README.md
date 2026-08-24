# LexBot

Legal assistant with RAG and agentic AI — portfolio project.

## Quick start (ingestion)

```bash
cd ingest
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env   # add your API keys
python -m lexbot_ingest.cli --docs ../docs/knowledge --db-path ../data/chroma
```

## Verify ingestion

```bash
cd ingest
python -m lexbot_ingest.cli --docs ../docs/knowledge --db-path ../data/chroma --provider fake --reset
# then query:
python -c "from lexbot_ingest.embeddings import FakeEmbedder; from lexbot_ingest.vector_store import VectorStore; [print(r['metadata']['source'], r['distance']) for r in VectorStore(path='../data/chroma', embedder=FakeEmbedder()).query('consultation', n_results=2)]"
```
