"""ChromaDB search wrapper.

Importing chromadb is allowed in this module and `core/ingest.py` only.
Returns Citation objects ready for the LLM tool result.
"""

from __future__ import annotations

from pathlib import Path

import chromadb

from core.embeddings import embed_query
from core.schema import Citation

COLLECTION_NAME = "oohmedia_investor"
CHROMA_PATH = Path("data/chroma")

_collection = None


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=None,  # type: ignore[arg-type]
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def search(query: str, k: int = 5) -> list[Citation]:
    """Top-k retrieval. Returns ordered Citation objects.

    The snippet field carries the chunk text — that becomes the evidence
    the model cites inline.
    """
    if not query.strip():
        return []
    collection = _get_collection()
    if collection.count() == 0:
        return []
    qvec = embed_query(query)
    res = collection.query(
        query_embeddings=[qvec],
        n_results=k,
        include=["documents", "metadatas"],
    )
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    out: list[Citation] = []
    for doc, meta in zip(docs, metas):
        page_val = meta.get("page", -1)
        out.append(
            Citation(
                source_id=meta.get("source_id", ""),
                doc_title=meta.get("doc_title", ""),
                doc_type=meta.get("doc_type", ""),
                period=meta.get("period", ""),
                page=page_val if isinstance(page_val, int) and page_val > 0 else None,
                snippet=doc,
                url=meta.get("url") or None,
            )
        )
    return out
