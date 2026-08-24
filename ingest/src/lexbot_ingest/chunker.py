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