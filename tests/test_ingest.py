"""US-02 — chunking and idempotency tests for core/ingest.py.

These tests do not hit the OpenAI API and do not require any PDFs on disk.
The chunker is pure-string and the idempotency check uses an in-memory
fake collection.
"""

from __future__ import annotations

from core.ingest import chunk_page_text, _chunk_id, _upsert_chunks
from core.schema import Chunk


def test_chunk_page_text_short_text_returns_single_chunk():
    chunks = chunk_page_text("hello world")
    assert chunks == ["hello world"]


def test_chunk_page_text_empty_returns_nothing():
    assert chunk_page_text("") == []
    assert chunk_page_text("   \n  ") == []


def test_chunk_page_text_long_text_slides_with_overlap():
    text = "a" * 2000
    chunks = chunk_page_text(text, size=800, overlap=100)
    assert len(chunks) >= 3
    # every chunk fits inside the window
    assert all(len(c) <= 800 for c in chunks)
    # successive chunks overlap by ~100 chars
    assert chunks[0][-50:] == chunks[1][:50]


def test_chunk_id_is_deterministic():
    c = Chunk(
        source_id="fy24_annual_report",
        doc_title="x",
        doc_type="annual_report",
        period="FY24",
        page=12,
        text="some content",
        url=None,
    )
    assert _chunk_id(c, 0) == "fy24_annual_report:p12:c0"
    assert _chunk_id(c, 3) == "fy24_annual_report:p12:c3"


class _FakeCollection:
    """Records every upsert call so we can assert idempotency."""

    def __init__(self):
        self._store: dict[str, dict] = {}
        self.calls = 0

    def upsert(self, ids, documents, metadatas, embeddings):
        self.calls += 1
        for i, d, m, e in zip(ids, documents, metadatas, embeddings):
            self._store[i] = {"doc": d, "meta": m, "emb": e}

    def count(self):
        return len(self._store)


def test_upsert_is_idempotent(monkeypatch):
    # Stub embed_texts to a deterministic dummy so we don't call OpenAI.
    import core.ingest as ingest_mod

    def fake_embed(texts):
        return [[0.0] * 4 for _ in texts]

    monkeypatch.setattr(ingest_mod, "embed_texts", fake_embed)

    chunks = [
        Chunk(
            source_id="fy24_annual_report",
            doc_title="t",
            doc_type="annual_report",
            period="FY24",
            page=1,
            text="page one chunk one",
            url=None,
        ),
        Chunk(
            source_id="fy24_annual_report",
            doc_title="t",
            doc_type="annual_report",
            period="FY24",
            page=1,
            text="page one chunk two",
            url=None,
        ),
    ]

    coll = _FakeCollection()
    n1 = _upsert_chunks(coll, chunks)
    n2 = _upsert_chunks(coll, chunks)
    assert n1 == 2
    assert n2 == 2
    # Same ids both runs → store size unchanged.
    assert coll.count() == 2
