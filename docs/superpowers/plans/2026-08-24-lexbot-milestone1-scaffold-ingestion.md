# LexBot Milestone 1 — Scaffold + Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap the LexBot repository and build a working ingestion pipeline that loads legal documents from `docs/knowledge/`, chunks them, embeds them, and stores them in a persistent ChromaDB vector store — with tests, Docker Compose, and a CLI.

**Architecture:** The ingest pipeline is a small Python package (`ingest/`) with three isolated units: a text chunker, an embedder abstraction (OpenAI/Gemini/fake), and a ChromaDB vector-store wrapper. A CLI (`python -m lexbot_ingest.cli`) wires them together. Vector data persists locally under `data/chroma`; PostgreSQL appears in `docker-compose.yml` now as scaffold for milestone 2.

**Tech Stack:** Python 3.11+, chromadb (persistent), openai, google-genai, python-dotenv, pytest.

**Repo root:** `/home/carlos-diaz/Projects/lexbot` (git repo on `main`).

---

## File structure

```
lexbot/
├── .env.example
├── docker-compose.yml
├── README.md
├── docs/
│   ├── knowledge/
│   │   ├── 01-firm-policies.md
│   │   ├── 02-faq-clients.md
│   │   └── 03-contract-glossary.md
│   └── superpowers/
│       ├── plans/2026-08-24-lexbot-milestone1-scaffold-ingestion.md
│       └── specs/2026-08-24-lexbot-design.md
├── ingest/
│   ├── pyproject.toml
│   ├── src/lexbot_ingest/
│   │   ├── __init__.py
│   │   ├── chunker.py
│   │   ├── embeddings.py
│   │   ├── vector_store.py
│   │   └── cli.py
│   └── tests/
│       ├── test_chunker.py
│       ├── test_vector_store.py
│       └── test_cli.py
└── data/chroma/            (gitignored, created at runtime)
```

---

### Task 1: Scaffold repo structure

**Files:**
- Create: `ingest/pyproject.toml`
- Create: `ingest/src/lexbot_ingest/__init__.py`
- Create: `ingest/tests/__init__.py` (empty)
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `README.md`

- [ ] **Step 1: Create the package skeleton**

```bash
mkdir -p ingest/src/lexbot_ingest ingest/tests
```

`ingest/src/lexbot_ingest/__init__.py`:
```python
"""LexBot ingestion pipeline."""
__version__ = "0.1.0"
```

`ingest/tests/__init__.py`: empty file.

- [ ] **Step 2: Create `ingest/pyproject.toml`**

```toml
[project]
name = "lexbot-ingest"
version = "0.1.0"
description = "LexBot knowledge-base ingestion: chunk, embed, store"
requires-python = ">=3.11"
dependencies = [
    "chromadb>=0.5.0",
    "openai>=1.30.0",
    "google-genai>=0.2.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  db:
    image: pgvector/pgvector:pg15
    environment:
      POSTGRES_USER: lexbot
      POSTGRES_PASSWORD: lexbot
      POSTGRES_DB: lexbot
    ports:
      - "5432:5432"
    volumes:
      - db-data:/var/lib/postgresql/data

volumes:
  db-data:
```

- [ ] **Step 4: Create `.env.example`**

```bash
# Embedding provider: gemini | openai | fake
EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=
OPENAI_API_KEY=
```

- [ ] **Step 5: Create `README.md`**

```markdown
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
```

- [ ] **Step 6: Verify scaffold and commit**

Run: `python -c "import tomllib; tomllib.load(open('ingest/pyproject.toml','rb'))"`
Expected: no output, exit 0 (valid TOML).

```bash
git add ingest/ docker-compose.yml .env.example README.md
git commit -m "chore: scaffold lexbot repo structure"
```

---

### Task 2: Text chunker

**Files:**
- Create: `ingest/src/lexbot_ingest/chunker.py`
- Test: `ingest/tests/test_chunker.py`

- [ ] **Step 1: Write the failing test**

`ingest/tests/test_chunker.py`:
```python
from lexbot_ingest.chunker import Chunk, chunk_text


def test_short_text_is_single_chunk():
    chunks = chunk_text("Short document.", source="a.md")
    assert len(chunks) == 1
    assert chunks[0].text == "Short document."
    assert chunks[0].source == "a.md"
    assert chunks[0].index == 0


def test_long_text_splits_with_overlap():
    text = "word " * 300  # 1500 chars, no boundaries to respect
    chunks = chunk_text(text, source="a.md", chunk_size=400, overlap=50)
    assert len(chunks) >= 3
    assert all(c.index == i for i, c in enumerate(chunks))
    # overlap means consecutive chunks share content
    assert chunks[0].text[-50:] == chunks[1].text[:50]


def test_invalid_sizes_raise():
    import pytest

    with pytest.raises(ValueError):
        chunk_text("x" * 10, source="a.md", chunk_size=100, overlap=100)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ingest && python -m pytest tests/test_chunker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lexbot_ingest'` (package not installed yet).

- [ ] **Step 3: Create the chunker**

`ingest/src/lexbot_ingest/chunker.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    text: str
    source: str
    index: int


def chunk_text(
    text: str,
    source: str,
    chunk_size: int = 800,
    overlap: int = 100,
) -> list[Chunk]:
    """Split text into overlapping character windows.

    Raises ValueError when overlap >= chunk_size (would loop forever).
    """
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [Chunk(text=text, source=source, index=0)]

    chunks: list[Chunk] = []
    step = chunk_size - overlap
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(Chunk(text=text[start:end], source=source, index=len(chunks)))
        if end == len(text):
            break
        start += step
    return chunks
```

- [ ] **Step 4: Install package and run tests**

Run:
```bash
cd ingest && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/test_chunker.py -v
```
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add ingest/src/lexbot_ingest/chunker.py ingest/tests/test_chunker.py
git commit -m "feat: add overlapping text chunker"
```

---

### Task 3: Embedder abstraction

**Files:**
- Create: `ingest/src/lexbot_ingest/embeddings.py`
- Test: `ingest/tests/test_vector_store.py` (FakeEmbedder used here and in Task 4)

- [ ] **Step 1: Write the failing test for the fake embedder**

`ingest/tests/test_vector_store.py`:
```python
from lexbot_ingest.embeddings import FakeEmbedder


def test_fake_embedder_is_deterministic_and_fixed_size():
    embedder = FakeEmbedder(dimensions=64)
    first = embedder.embed(["hello world"])
    second = embedder.embed(["hello world"])
    other = embedder.embed(["totally different text"])
    assert first == second
    assert len(first[0]) == 64
    assert first[0] != other[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ingest && python -m pytest tests/test_vector_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lexbot_ingest.embeddings'`.

- [ ] **Step 3: Create the embeddings module**

`ingest/src/lexbot_ingest/embeddings.py`:
```python
import os
from abc import ABC, abstractmethod

from google import genai
from openai import OpenAI


class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


class FakeEmbedder(Embedder):
    """Deterministic term-frequency embedder for tests and local demos.

    Uses the hashing trick: each token maps to a fixed bucket. Documents
    sharing vocabulary get closer vectors, so retrieval tests are meaningful.
    Never use in production.
    """

    def __init__(self, dimensions: int = 64) -> None:
        self._dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self._dimensions
            for token in text.lower().split():
                bucket = (sum(ord(c) for c in token) * 31 + len(token)) % self._dimensions
                vector[bucket] += 1.0
            vectors.append(vector)
        return vectors


class OpenAIEmbedder(Embedder):
    def __init__(self, model: str = "text-embedding-3-small") -> None:
        self._model = model
        self._client = OpenAI()

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]


class GeminiEmbedder(Embedder):
    def __init__(self, model: str = "gemini-embedding-001") -> None:
        self._model = model
        self._client = genai.Client()

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.models.embed_content(model=self._model, contents=texts)
        return [embedding.values for embedding in response.embeddings]


def build_embedder(provider: str | None = None) -> Embedder:
    provider = provider or os.getenv("EMBEDDING_PROVIDER", "gemini")
    if provider == "openai":
        return OpenAIEmbedder()
    if provider == "gemini":
        return GeminiEmbedder()
    if provider == "fake":
        return FakeEmbedder()
    raise ValueError(f"Unknown embedding provider: {provider}")
```

- [ ] **Step 4: Run tests**

Run: `cd ingest && python -m pytest tests/test_vector_store.py -v`
Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add ingest/src/lexbot_ingest/embeddings.py ingest/tests/test_vector_store.py
git commit -m "feat: add embedder abstraction with openai/gemini/fake providers"
```

---

### Task 4: Vector store wrapper

**Files:**
- Create: `ingest/src/lexbot_ingest/vector_store.py`
- Test: `ingest/tests/test_vector_store.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `ingest/tests/test_vector_store.py`:
```python
from lexbot_ingest.chunker import Chunk
from lexbot_ingest.vector_store import VectorStore


def test_add_and_count(tmp_path):
    store = VectorStore(path=str(tmp_path / "chroma"), embedder=FakeEmbedder())
    store.add_chunks([Chunk(text="billing policies", source="a.md", index=0)])
    assert store.count() == 1


def test_query_returns_nearest_chunk(tmp_path):
    store = VectorStore(path=str(tmp_path / "chroma"), embedder=FakeEmbedder())
    store.add_chunks(
        [
            Chunk(text="confidentiality rules", source="a.md", index=0),
            Chunk(text="parking instructions", source="b.md", index=0),
        ]
    )
    results = store.query("confidentiality", n_results=1)
    assert len(results) == 1
    assert results[0]["metadata"]["source"] == "a.md"
    assert "id" in results[0] and "text" in results[0] and "distance" in results[0]


def test_reset_empties_collection(tmp_path):
    store = VectorStore(path=str(tmp_path / "chroma"), embedder=FakeEmbedder())
    store.add_chunks([Chunk(text="anything", source="a.md", index=0)])
    store.reset()
    assert store.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ingest && python -m pytest tests/test_vector_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lexbot_ingest.vector_store'`.

- [ ] **Step 3: Create the vector store wrapper**

`ingest/src/lexbot_ingest/vector_store.py`:
```python
import chromadb

from .chunker import Chunk
from .embeddings import Embedder


class VectorStore:
    def __init__(
        self,
        path: str,
        embedder: Embedder,
        collection_name: str = "legal_kb",
    ) -> None:
        self._client = chromadb.PersistentClient(path=path)
        self._name = collection_name
        self._embedder = embedder
        self._collection = self._client.get_or_create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"}
        )

    def add_chunks(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        embeddings = self._embedder.embed([c.text for c in chunks])
        self._collection.add(
            ids=[f"{c.source}:{c.index}" for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=embeddings,
            metadatas=[
                {"source": c.source, "chunk_index": c.index} for c in chunks
            ],
        )

    def query(self, text: str, n_results: int = 3) -> list[dict]:
        embedding = self._embedder.embed([text])[0]
        result = self._collection.query(
            query_embeddings=[embedding], n_results=n_results
        )
        rows = []
        for i in range(len(result["ids"][0])):
            rows.append(
                {
                    "id": result["ids"][0][i],
                    "text": result["documents"][0][i],
                    "metadata": result["metadatas"][0][i],
                    "distance": result["distances"][0][i],
                }
            )
        return rows

    def count(self) -> int:
        return self._collection.count()

    def reset(self) -> None:
        self._client.delete_collection(self._name)
        self._collection = self._client.get_or_create_collection(
            name=self._name, metadata={"hnsw:space": "cosine"}
        )
```

- [ ] **Step 4: Run tests**

Run: `cd ingest && python -m pytest tests/ -v`
Expected: 7 PASSED (3 chunker + 1 fake embedder + 3 vector store).

- [ ] **Step 5: Commit**

```bash
git add ingest/src/lexbot_ingest/vector_store.py ingest/tests/test_vector_store.py
git commit -m "feat: add chromadb vector store wrapper"
```

---

### Task 5: Ingestion CLI

**Files:**
- Create: `ingest/src/lexbot_ingest/cli.py`
- Test: `ingest/tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`ingest/tests/test_cli.py`:
```python
from pathlib import Path

from lexbot_ingest.cli import main
from lexbot_ingest.embeddings import FakeEmbedder
from lexbot_ingest.vector_store import VectorStore


def test_cli_ingests_docs_and_reports_chunks(tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text("word " * 300, encoding="utf-8")

    exit_code = main(
        [
            "--docs", str(docs),
            "--db-path", str(tmp_path / "chroma"),
            "--provider", "fake",
            "--chunk-size", "400",
            "--overlap", "50",
        ]
    )
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "5 chunks" in output  # 1500 chars, chunk 400, overlap 50 -> step 350 -> 5 chunks

    store = VectorStore(path=str(tmp_path / "chroma"), embedder=FakeEmbedder())
    assert store.count() == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ingest && python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lexbot_ingest.cli'`.

- [ ] **Step 3: Create the CLI**

`ingest/src/lexbot_ingest/cli.py`:
```python
import argparse
from pathlib import Path

from .chunker import chunk_text
from .embeddings import build_embedder
from .vector_store import VectorStore

DOC_EXTENSIONS = {".md", ".txt"}


def load_docs(docs_dir: Path) -> list[tuple[str, str]]:
    docs: list[tuple[str, str]] = []
    for path in sorted(docs_dir.rglob("*")):
        if path.is_file() and path.suffix in DOC_EXTENSIONS:
            docs.append((str(path), path.read_text(encoding="utf-8")))
    return docs


def main(argv: list[str] | None = None) -> int:
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
```

- [ ] **Step 4: Run tests**

Run: `cd ingest && python -m pytest tests/ -v`
Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
git add ingest/src/lexbot_ingest/cli.py ingest/tests/test_cli.py
git commit -m "feat: add ingestion CLI"
```

---

### Task 6: Seed knowledge docs + end-to-end verification

**Files:**
- Create: `docs/knowledge/01-firm-policies.md`
- Create: `docs/knowledge/02-faq-clients.md`
- Create: `docs/knowledge/03-contract-glossary.md`
- Modify: `README.md` (final quick-start with verification query)

- [ ] **Step 1: Create seed documents**

`docs/knowledge/01-firm-policies.md`:
```markdown
# Firm Policies

## Office hours
The firm is open Monday through Friday from 9:00 to 18:00. Consultations are by appointment only.

## Billing
Hourly billing is invoiced monthly. Retainer clients are billed at the start of each month. All invoices are payable within 15 days.

## Confidentiality
All client information is confidential. Documents are stored in encrypted repositories with access limited to the assigned team.

## Communication
Client communication happens through the official channels: email, phone, and the WhatsApp business line. Responses to client messages are expected within one business day.
```

`docs/knowledge/02-faq-clients.md`:
```markdown
# Frequently Asked Questions — Clients

## What should I bring to the first consultation?
Bring a government-issued ID, any contracts or documents related to your case, and a summary of the timeline of events.

## How are fees calculated?
Fees depend on the type of matter: fixed fee for standard procedures, hourly rate for complex work, or contingency for certain civil cases. You receive a written fee agreement before any work begins.

## Can I get advice by phone or WhatsApp?
Yes. Routine questions are answered through the WhatsApp business line during office hours. Anything requiring legal analysis is scheduled as a consultation.

## How long does a contract review take?
Standard contract reviews are delivered within 5 business days. Urgent reviews are available at a premium rate.
```

`docs/knowledge/03-contract-glossary.md`:
```markdown
# Contract Glossary

## Retainer
A retainer is an advance payment that secures the firm's availability and is applied against future invoices.

## Force majeure
Force majeure covers unforeseeable events outside a party's control that prevent contractual performance.

## Indemnity
An indemnity is a contractual obligation to compensate the other party for specified losses.

## Jurisdiction
Jurisdiction determines which courts or arbitration bodies resolve disputes arising from the contract.
```

- [ ] **Step 2: Run the full pipeline end-to-end (fake provider)**

Run:
```bash
cd ingest
python -m lexbot_ingest.cli --docs ../docs/knowledge --db-path ../data/chroma --provider fake --reset
```
Expected: 3 source files listed with chunk counts, final line `Ingested N chunks from 3 documents into 'legal_kb'`.

- [ ] **Step 3: Verify retrieval works**

Run:
```bash
cd ingest && python - <<'EOF'
from lexbot_ingest.embeddings import FakeEmbedder
from lexbot_ingest.vector_store import VectorStore
store = VectorStore(path="../data/chroma", embedder=FakeEmbedder())
for row in store.query("first consultation", n_results=2):
    print(row["metadata"]["source"], row["distance"])
EOF
```
Expected: prints 2 rows; the closest must be `docs/knowledge/02-faq-clients.md` (the only seed doc containing both tokens "first" and "consultation") with a lower distance than the second row.

- [ ] **Step 4: Update README with verification section**

Append to `README.md`:
```markdown
## Verify ingestion

```bash
cd ingest
python -m lexbot_ingest.cli --docs ../docs/knowledge --db-path ../data/chroma --provider fake --reset
# then query:
python -c "from lexbot_ingest.embeddings import FakeEmbedder; from lexbot_ingest.vector_store import VectorStore; [print(r['metadata']['source'], r['distance']) for r in VectorStore(path='../data/chroma', embedder=FakeEmbedder()).query('consultation', n_results=2)]"
```
```

- [ ] **Step 5: Full test pass and commit**

Run: `cd ingest && python -m pytest tests/ -v`
Expected: 8 PASSED.

```bash
git add docs/knowledge/ README.md
git commit -m "feat: add seed knowledge docs and end-to-end ingestion verification"
```

---

## Milestone 1 completion criteria

- [ ] `python -m pytest tests/` passes (8 tests) from `ingest/`
- [ ] `python -m lexbot_ingest.cli --docs ../docs/knowledge --db-path ../data/chroma --provider fake --reset` ingests 3 documents
- [ ] A query returns the FAQ document as nearest neighbor
- [ ] `git log` shows 6 conventional commits, one per task

## Later milestone plans (not part of this plan)

- **Milestone 2 — Agent + API:** LangGraph graph with 4 tools, FastAPI `/chat`, `/ingest`, `/health`; own plan document.
- **Milestone 3 — Chat UI:** React 18 + Vite + Tailwind chat wired to `/chat`.
- **Milestone 4 — n8n + polish:** WhatsApp bridge workflow, README + Mermaid, demo script.
- **Milestone 5 — Production:** CDK stack, GitHub Actions OIDC pipeline, Nginx + Let's Encrypt, pgvector migration, backups, smoke test.