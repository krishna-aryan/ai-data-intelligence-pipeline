from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    text: str
    index: int
    total_chunks: int


def chunk_text(
    text: str,
    *,
    max_chars: int = 20000,
    overlap_chars: int = 400,
) -> list[TextChunk]:
    if not text:
        return []

    if len(text) <= max_chars:
        return [TextChunk(chunk_id="chunk-0", text=text, index=0, total_chunks=1)]

    if overlap_chars < 0:
        raise ValueError("overlap_chars must be >= 0")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")

    chunks: list[TextChunk] = []
    start = 0

    while start < len(text):
        end = min(len(text), start + max_chars)
        split_point = _find_split_point(text, start, end, overlap_chars)
        if split_point is None:
            split_point = end

        chunk_text_value = text[start:split_point]
        if not chunk_text_value:
            chunk_text_value = text[start:end]

        chunks.append(
            TextChunk(
                chunk_id=f"chunk-{len(chunks)}",
                text=chunk_text_value,
                index=len(chunks),
                total_chunks=0,
            )
        )

        if split_point >= len(text):
            break

        next_start = split_point - overlap_chars
        if next_start <= start:
            next_start = min(len(text), start + 1)
        start = next_start

    total = len(chunks)
    return [
        TextChunk(chunk_id=chunk.chunk_id, text=chunk.text, index=chunk.index, total_chunks=total)
        for chunk in chunks
    ]


def _find_split_point(text: str, start: int, end: int, overlap_chars: int = 0) -> int | None:
    window = text[start:end]
    if not window:
        return None

    minimum_candidate = start + overlap_chars
    patterns = [
        r"\n\s*\n+",
        r"\n",
        r"(?<=[.!?])\s+",
        r"\s+",
    ]

    for pattern in patterns:
        matches = list(re.finditer(pattern, window))
        if not matches:
            continue

        for match in reversed(matches):
            candidate = start + match.end()
            if candidate < end and candidate > minimum_candidate:
                return candidate

    return end if end < len(text) else None


__all__ = ["TextChunk", "chunk_text"]
