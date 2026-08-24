# LexBot

Legal assistant with RAG and agentic AI — a portfolio project for a legal-firm internship.

LexBot ingests a firm's knowledge base (policies, FAQs, contract glossaries) and answers legal questions grounded in those documents. The project is built incrementally: **Milestone 1 (current)** delivers a tested ingestion pipeline; later milestones add the agent, API, UI, and production deployment.

> [!NOTE]
> Current status: **Milestone 1 complete** — ingestion pipeline (chunk → embed → ChromaDB) with 8 passing tests and a working CLI.

## Features

- **Text chunking** — deterministic overlapping character windows (`Chunk` + `chunk_text()`)
- **Embedder abstraction** — pluggable providers (OpenAI, Gemini, Fake) behind a single `Embedder` ABC
- **Vector store** — ChromaDB persistent wrapper with cosine similarity (`add` / `query` / `count` / `reset`)
- **Ingestion CLI** — `python -m lexbot_ingest.cli` wires chunking → embedding → storage end to end
- **Hermetic tests** — the Fake embedder keeps the whole test suite offline and deterministic

## Architecture

```
docs/knowledge/*.md ──▶ chunk_text ──▶ Embedder ──▶ ChromaDB (data/chroma, collection "legal_kb")
                                                        │
                                            query("…") ──▶ nearest chunks
```

Planned end-to-end architecture (later milestones):

```
ingest/ → agent/ → api/ → ui/ → n8n/ → db/ → infra/
```

## Repository layout

| Path | Description |
|---|---|
| `ingest/` | Python package: chunker, embeddings, vector store, CLI |
| `ingest/tests/` | Pytest suite (8 tests) |
| `docs/knowledge/` | Seed knowledge documents (policies, FAQ, glossary) |
| `docs/superpowers/` | Design spec and Milestone 1 implementation plan |
| `docker-compose.yml` | PostgreSQL/pgvector scaffold (for Milestone 2) |
| `.env.example` | Environment template (embedding provider + API keys) |

## Getting started

### Prerequisites

- Python 3.11+
- (Optional) API keys for real embedding providers — OpenAI or Gemini

### Install

```bash
cd ingest
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env   # add your API keys
```

### Ingest the knowledge base

```bash
cd ingest
python -m lexbot_ingest.cli --docs ../docs/knowledge --db-path ../data/chroma
```

Use `--provider fake` for a fully offline run (no API keys needed):

```bash
python -m lexbot_ingest.cli --docs ../docs/knowledge --db-path ../data/chroma --provider fake --reset
```

### Query

```bash
python -c "from lexbot_ingest.embeddings import FakeEmbedder; from lexbot_ingest.vector_store import VectorStore; [print(r['metadata']['source'], r['distance']) for r in VectorStore(path='../data/chroma', embedder=FakeEmbedder()).query('first consultation', n_results=2)]"
```

### Run the tests

```bash
cd ingest
python -m pytest tests/ -v
```

> [!TIP]
> Re-running the CLI without `--reset` on an existing collection can raise duplicate-ID errors — `--reset` is the documented idempotent path. Use it before switching embedding providers (ChromaDB collections have fixed dimensionality).

## Technology stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Embeddings | OpenAI (`text-embedding-3-small`), Google Gemini (`gemini-embedding-001`), built-in Fake |
| Vector store | ChromaDB ≥ 0.5 (persistent client, cosine) |
| CLI | argparse |
| Tests | pytest |
| Database scaffold | PostgreSQL 15 + pgvector (Docker Compose) |
| Frontend (planned) | React 18 |
| Orchestration (planned) | n8n, LangGraph, FastAPI, AWS CDK |

## Roadmap

- [x] **Milestone 1** — Scaffold + ingestion pipeline
- [ ] **Milestone 2** — Agent + API (LangGraph, FastAPI)
- [ ] **Milestone 3** — Web UI (React)
- [ ] **Milestone 4** — n8n + WhatsApp integration
- [ ] **Milestone 5** — Production deployment (AWS CDK)

## Documentation

- [Design spec](docs/superpowers/specs/2026-08-24-lexbot-design.md)
- [Milestone 1 implementation plan](docs/superpowers/plans/2026-08-24-lexbot-milestone1-scaffold-ingestion.md)