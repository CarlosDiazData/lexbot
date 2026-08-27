import logging
import os
from pathlib import Path

import chromadb
import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from .chunker import Chunk
from .embeddings import Embedder, build_embedder

logger = logging.getLogger(__name__)

# repo_root/data/chroma — ingest/src/lexbot_ingest/vector_store.py -> parents[3]
DEFAULT_CHROMA_PATH = str(Path(__file__).resolve().parents[3] / "data" / "chroma")


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


class PgVectorStore:
    """pgvector-backed store (AWS deploy, PGV-2).

    Mirrors VectorStore's public surface so tools.py is untouched. Connections
    are opened per call (psycopg.connect) — same seam as Database._connect.
    `add_chunks` embeds once and inserts with ON CONFLICT (chunk_id) DO NOTHING
    in a single transaction; `query` uses cosine distance (<=>) and returns the
    exact Chroma return shape {id, text, metadata:{source, chunk_index}, distance}.
    Dimensions are validated at init against the table's atttypmod.
    """

    def __init__(
        self,
        dsn: str,
        embedder: Embedder,
        table: str = "legal_kb_embeddings",
        dimensions: int = 3072,
    ) -> None:
        self._dsn = dsn
        self._embedder = embedder
        self._table = table
        self._dimensions = dimensions
        self._validate_dimensions()

    def _connect(self):
        conn = psycopg.connect(self._dsn)
        register_vector(conn)  # adapt list<->vector in params/rows
        return conn

    def _validate_dimensions(self) -> None:
        """Fail fast if the table's embedding dims don't match `dimensions`.

        pgvector stores the declared vector(n) length directly in atttypmod
        (verified empirically: vector(3) -> atttypmod 3).
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = %s::regclass AND attname = 'embedding'",
                    (self._table,),
                )
                row = cur.fetchone()
        if row is None:
            raise ValueError(f"table '{self._table}' has no 'embedding' column")
        actual = row[0]
        if actual != self._dimensions:
            raise ValueError(
                f"embedding dimension mismatch: table '{self._table}' is "
                f"vector({actual}) but the store is configured for {self._dimensions} dims"
            )

    def add_chunks(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        embeddings = self._embedder.embed([c.text for c in chunks])
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {self._table} "
                    "(chunk_id, source, chunk_index, text, embedding) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (chunk_id) DO NOTHING",
                    [
                        (f"{c.source}:{c.index}", c.source, c.index, c.text, emb)
                        for c, emb in zip(chunks, embeddings)
                    ],
                )

    def query(self, text: str, n_results: int = 3) -> list[dict]:
        embedding = Vector(self._embedder.embed([text])[0])
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT chunk_id, source, chunk_index, text, "
                    f"embedding <=> %s AS distance "
                    f"FROM {self._table} ORDER BY embedding <=> %s LIMIT %s",
                    (embedding, embedding, n_results),
                )
                rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "text": r[3],
                "metadata": {"source": r[1], "chunk_index": r[2]},
                "distance": float(r[4]),
            }
            for r in rows
        ]

    def count(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {self._table}")
                return cur.fetchone()[0]

    def reset(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE {self._table}")


def build_store(provider: str | None = None) -> VectorStore | PgVectorStore:
    """STORE_PROVIDER factory: chroma (default) | pgvector.

    Mirrors build_embedder's dev posture: pgvector with no DATABASE_URL warns
    and falls back to Chroma so local dev keeps working without a database.
    """
    provider = provider or os.getenv("STORE_PROVIDER", "chroma")
    if provider == "chroma":
        return VectorStore(path=DEFAULT_CHROMA_PATH, embedder=build_embedder())
    if provider == "pgvector":
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            logger.warning(
                "STORE_PROVIDER=pgvector but DATABASE_URL is unset — falling back to "
                "Chroma (set DATABASE_URL to use the pgvector store)"
            )
            return VectorStore(path=DEFAULT_CHROMA_PATH, embedder=build_embedder())
        return PgVectorStore(dsn=dsn, embedder=build_embedder())
    raise ValueError(f"Unknown store provider: {provider}")