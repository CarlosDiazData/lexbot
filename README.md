# LexBot

Legal assistant with RAG and agentic AI — a portfolio project for a legal-firm internship.

LexBot ingests a firm's knowledge base (policies, FAQs, contract glossaries), answers legal questions grounded in those documents, searches case records, and registers follow-ups. The project is built incrementally: **Milestone 1** delivered the ingestion pipeline, **Milestone 2** adds the conversational agent and API; later milestones add the UI, n8n integration, and production deployment.

> [!NOTE]
> Current status: **Milestones 1–2 complete** — ingestion pipeline (chunk → embed → ChromaDB), LangGraph agent with 4 tools, FastAPI surface, and PostgreSQL schema. 46 passing tests.

## Features

- **Text chunking** — deterministic overlapping character windows (`Chunk` + `chunk_text()`)
- **Embedder abstraction** — pluggable providers (OpenAI, Gemini, Fake) behind a single `Embedder` ABC, with a keyless dev fallback
- **Vector store** — ChromaDB persistent wrapper with cosine similarity (`add` / `query` / `count` / `reset`)
- **Ingestion CLI** — `python -m lexbot_ingest.cli` wires chunking → embedding → storage end to end
- **LangGraph agent** — intent classification, tool dispatch, and answer composition with source citations
- **4 agent tools** — `retrieve_knowledge` (ChromaDB), `search_case` (PostgreSQL), `register_follow_up` (PostgreSQL), `notify_whatsapp` (webhook stub)
- **FastAPI surface** — `POST /chat`, `POST /ingest`, `GET /health`
- **Hermetic tests** — Fake embedder + scripted FakeLLM keep the suite offline and deterministic

## Architecture

```
POST /chat {message}
  → agent: classify_intent (LLM tool selection)
      → tools (ToolNode)
          retrieve_knowledge → ChromaDB (data/chroma, "legal_kb")
          search_case / register_follow_up → PostgreSQL (cases, follow_ups)
          notify_whatsapp → webhook stub
      → compose_answer → {answer, sources, actions}
```

End-to-end architecture:

```
ingest/ → agent/ → api/ → ui/ → n8n/ → db/ → infra/
```

## Repository layout

| Path | Description |
|---|---|
| `ingest/` | Python package: chunker, embeddings, vector store, CLI |
| `agent/` | LangGraph agent: state, LLM factory, tools, graph |
| `api/` | FastAPI app: routers (chat, ingest, health), schemas, Dockerfile |
| `db/` | Idempotent PostgreSQL schema (`cases`, `follow_ups`) |
| `docs/knowledge/` | Seed knowledge documents (policies, FAQ, glossary) |
| `docs/superpowers/` | Design spec and Milestone 1 implementation plan |
| `docker-compose.yml` | PostgreSQL (pgvector) + API service |
| `.env.example` | Environment template (providers, API keys, database) |

## Getting started

### Prerequisites

- Python 3.11+
- Docker (for the API + PostgreSQL stack)
- (Optional) API keys for real LLM/embedding providers — OpenAI or Gemini

### 1. Ingestion pipeline (CLI)

```bash
cd ingest
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env   # add your API keys
python -m lexbot_ingest.cli --docs ../docs/knowledge --db-path ../data/chroma --provider fake --reset
```

> [!TIP]
> Without API keys, `build_embedder()` falls back to the Fake embedder with a warning — the pipeline runs fully offline for development.

### 2. Agent + API (Docker)

```bash
docker compose up -d --build
curl localhost:8000/health
```

Then chat with the agent:

```bash
curl -X POST localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What are the confidentiality rules?"}'
```

The API auto-seeds the knowledge base on first start. Without LLM keys it boots with a deterministic fake path; add `GEMINI_API_KEY` (or `OPENAI_API_KEY` + `LLM_PROVIDER=openai`) to `.env` for real answers.

### Run the tests

```bash
cd ingest && python -m pytest tests/ -v    # 13 tests
cd agent  && python -m pytest tests/ -v    # 26 tests
cd api    && python -m pytest tests/ -v    # 7 tests
```

## Technology stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Agent framework | LangGraph ≥ 0.2, langchain-core ≥ 0.3 |
| LLMs | Google Gemini (`gemini-embedding-001`, `gemini-2.0-flash`), OpenAI (`text-embedding-3-small`) |
| Embeddings | OpenAI, Google Gemini, built-in Fake |
| Vector store | ChromaDB ≥ 0.5 (persistent client, cosine) |
| API | FastAPI, uvicorn, pydantic |
| Database | PostgreSQL 15 + pgvector (Docker Compose), psycopg 3 |
| CLI | argparse |
| Tests | pytest |
| Frontend (planned) | React 18 |
| Orchestration (planned) | n8n, AWS CDK |

## Roadmap

- [x] **Milestone 1** — Scaffold + ingestion pipeline
- [x] **Milestone 2** — Agent + API (LangGraph, FastAPI)
- [ ] **Milestone 3** — Web UI (React)
- [ ] **Milestone 4** — n8n + WhatsApp integration
- [ ] **Milestone 5** — Production deployment (AWS CDK)

## Documentation

- [Design spec](docs/superpowers/specs/2026-08-24-lexbot-design.md)
- [Milestone 1 implementation plan](docs/superpowers/plans/2026-08-24-lexbot-milestone1-scaffold-ingestion.md)