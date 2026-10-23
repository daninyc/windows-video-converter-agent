import pytest

from media_converter.rag.ingest import chunk_section, lexical

pytestmark = pytest.mark.unit


def test_chunk_boundaries_overlap_and_exact_identifiers():
    class Tokenizer:
        def encode(self, text):
            return list(text)

    text = "中文 libx264 mov_text -map 保留轨道。" * 100
    chunks = chunk_section(text, Tokenizer())
    assert chunks[0][0] == 0 and chunks[-1][1] == len(text)
    assert all(count <= 802 and text[start:end] == piece for start, end, piece, count in chunks)
    assert all(
        previous[1] - following[0] <= 80
        for previous, following in zip(chunks, chunks[1:], strict=False)
    )
    assert "libx264 mov_text -map" in lexical("中文 libx264 mov_text -map")
