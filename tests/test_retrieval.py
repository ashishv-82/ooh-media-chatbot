"""US-02 — retrieval shape tests for core/retrieval.py.

Stubs the chroma collection and OpenAI client so the test runs offline.
The point here is to confirm that retrieval returns Citation objects
populated from the chunk metadata, not to test chroma itself.
"""

from __future__ import annotations

import core.retrieval as retrieval_mod
from core.schema import Citation


class _FakeCollection:
    def __init__(self, hits):
        self._hits = hits

    def count(self):
        return len(self._hits)

    def query(self, query_embeddings, n_results, include):
        docs = [[h["doc"] for h in self._hits[:n_results]]]
        metas = [[h["meta"] for h in self._hits[:n_results]]]
        return {"documents": docs, "metadatas": metas}


def test_search_returns_citations(monkeypatch):
    fake_hits = [
        {
            "doc": "Revenue rose to $635m in FY24...",
            "meta": {
                "source_id": "fy24_annual_report",
                "doc_title": "oOh!media FY24 Annual Report",
                "doc_type": "annual_report",
                "period": "FY24",
                "page": 12,
                "url": "https://investors.oohmedia.com.au/investor-centre/",
            },
        },
        {
            "doc": "Operating EBITDA was $129m...",
            "meta": {
                "source_id": "fy24_annual_report",
                "doc_title": "oOh!media FY24 Annual Report",
                "doc_type": "annual_report",
                "period": "FY24",
                "page": 13,
                "url": "https://investors.oohmedia.com.au/investor-centre/",
            },
        },
    ]
    monkeypatch.setattr(retrieval_mod, "_get_collection", lambda: _FakeCollection(fake_hits))
    monkeypatch.setattr(retrieval_mod, "embed_query", lambda q: [0.0, 0.0, 0.0, 0.0])

    results = retrieval_mod.search("revenue", k=2)
    assert len(results) == 2
    assert all(isinstance(r, Citation) for r in results)
    assert results[0].source_id == "fy24_annual_report"
    assert results[0].page == 12
    assert results[0].doc_type == "annual_report"
    assert "Revenue" in results[0].snippet
    assert results[1].page == 13


def test_search_empty_query_returns_nothing():
    assert retrieval_mod.search("") == []
    assert retrieval_mod.search("   ") == []
