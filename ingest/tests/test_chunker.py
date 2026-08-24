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


def test_blank_text_yields_no_chunks():
    assert chunk_text("", source="a.md") == []
    assert chunk_text("   \n\t  ", source="a.md") == []