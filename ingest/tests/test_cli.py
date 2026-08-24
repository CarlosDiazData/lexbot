from pathlib import Path

from lexbot_ingest.chunker import chunk_text
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


def test_cli_reset_recreates_collection(tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    db_path = tmp_path / "chroma"

    store = VectorStore(path=str(db_path), embedder=FakeEmbedder())
    store.add_chunks(chunk_text("stale content", source="stale.md"))
    assert store.count() == 1

    # Without --reset, stale rows survive an empty ingest
    main(
        [
            "--docs", str(docs),
            "--db-path", str(db_path),
            "--provider", "fake",
        ]
    )
    assert VectorStore(path=str(db_path), embedder=FakeEmbedder()).count() == 1

    # --reset drops the collection before ingest: with nothing to ingest the
    # count returns to 0, proving stale rows were cleared first
    main(
        [
            "--docs", str(docs),
            "--db-path", str(db_path),
            "--provider", "fake",
            "--reset",
        ]
    )
    assert VectorStore(path=str(db_path), embedder=FakeEmbedder()).count() == 0
    output = capsys.readouterr().out
    assert "Ingested 0 chunks" in output