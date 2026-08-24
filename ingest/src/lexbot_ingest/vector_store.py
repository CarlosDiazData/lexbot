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