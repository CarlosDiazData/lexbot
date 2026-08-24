from lexbot_ingest.embeddings import FakeEmbedder


def test_fake_embedder_is_deterministic_and_fixed_size():
    embedder = FakeEmbedder(dimensions=64)
    first = embedder.embed(["hello world"])
    second = embedder.embed(["hello world"])
    other = embedder.embed(["totally different text"])
    assert first == second
    assert len(first[0]) == 64
    assert first[0] != other[0]