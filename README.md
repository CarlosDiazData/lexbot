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
