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