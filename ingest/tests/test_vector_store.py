from lexbot_ingest.chunker import Chunk
from lexbot_ingest.embeddings import FakeEmbedder
from lexbot_ingest.vector_store import VectorStore


def test_fake_embedder_is_deterministic_and_fixed_size():
    embedder = FakeEmbedder(dimensions=64)
    first = embedder.embed(["hello world"])
    second = embedder.embed(["hello world"])
    other = embedder.embed(["totally different text"])
    assert first == second
    assert len(first[0]) == 64
    assert first[0] != other[0]


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