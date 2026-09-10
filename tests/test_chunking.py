from src.llm.chunking import TextChunk, chunk_text


def test_small_document_returns_single_chunk():
    text = "This is a short document."
    chunks = chunk_text(text, max_chars=200, overlap_chars=20)

    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].index == 0
    assert chunks[0].total_chunks == 1


def test_large_document_splits_into_multiple_chunks():
    text = "Section A\n\nThis is paragraph one. It has several sentences.\n\nSection B\n\nThis is paragraph two. It also has several sentences."
    chunks = chunk_text(text, max_chars=90, overlap_chars=10)

    assert len(chunks) > 1
    assert all(len(chunk.text) > 0 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.total_chunks == len(chunks) for chunk in chunks)


def test_paragraph_boundary_preferred_over_sentence_or_whitespace():
    text = "Intro paragraph.\n\nSecond paragraph with more detail.\n\nThird paragraph."
    chunks = chunk_text(text, max_chars=45, overlap_chars=5)

    assert len(chunks) > 1
    assert all("\n\n" in chunk.text or len(chunk.text) <= 45 for chunk in chunks)


def test_sentence_and_whitespace_fallback_are_valid():
    text = "Alpha beta gamma delta. Epsilon zeta eta theta. Iota kappa lambda mu."
    chunks = chunk_text(text, max_chars=30, overlap_chars=5)

    assert len(chunks) > 1
    assert all(chunk.text.strip() for chunk in chunks)


def test_hard_character_boundary_fallback():
    text = "word " * 100
    chunks = chunk_text(text, max_chars=40, overlap_chars=5)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 40 for chunk in chunks)


def test_overlap_keeps_boundary_context():
    text = "one two three four five six seven eight nine ten"
    chunks = chunk_text(text, max_chars=24, overlap_chars=6)

    assert len(chunks) > 1
    assert chunks[0].text != chunks[1].text
    assert any(chunks[0].text[-6:] == chunks[1].text[:6] for _ in [0])


def test_chunk_ordering_and_metadata_are_deterministic():
    text = "A B C D E F G H I J K L M N O"
    chunks = chunk_text(text, max_chars=12, overlap_chars=3)

    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert [chunk.total_chunks for chunk in chunks] == [len(chunks)] * len(chunks)
    assert all(isinstance(chunk.chunk_id, str) and chunk.chunk_id for chunk in chunks)


def test_chunk_text_preserves_original_text_contents():
    text = "Alpha\n\nBeta\n\nGamma"
    chunks = chunk_text(text, max_chars=12, overlap_chars=2)

    combined = "".join(chunk.text for chunk in chunks)
    assert combined.startswith("Alpha")
    assert "Beta" in combined
    assert "Gamma" in combined
