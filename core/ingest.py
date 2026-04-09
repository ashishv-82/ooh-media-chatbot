"""Ingest oOh!media investor PDFs into ChromaDB.

pdfplumber → page-aware sliding-window chunks → OpenAI embeddings → Chroma upsert.

Idempotent: deterministic chunk IDs (`{source_id}:p{page}:c{idx}`) + Chroma upsert
means re-running on the same corpus replaces in place rather than duplicating.

CLI:
    uv run python -m core.ingest data/pdfs

Importing chromadb is allowed in this module and `core/retrieval.py` only.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import chromadb
import pdfplumber

from core.embeddings import embed_texts
from core.schema import Chunk

# ---------- corpus mapping ----------
# Hard-coded because the corpus for this build is small and pinned. Adding a new
# document is one new entry here plus dropping the file under data/pdfs/.

INVESTOR_CENTRE = "https://investors.oohmedia.com.au/investor-centre/"


@dataclass(frozen=True)
class DocSpec:
    source_id: str
    doc_title: str
    doc_type: str  # annual_report | half_year_report | investor_presentation
    period: str
    url: str


DOCS: dict[str, DocSpec] = {
    "oOh!media-Annual-Report-2024.pdf": DocSpec(
        source_id="fy24_annual_report",
        doc_title="oOh!media FY24 Annual Report",
        doc_type="annual_report",
        period="FY24",
        url=INVESTOR_CENTRE,
    ),
    "oOh!media-Annual-Report-2025.pdf": DocSpec(
        source_id="fy25_annual_report",
        doc_title="oOh!media FY25 Annual Report",
        doc_type="annual_report",
        period="FY25",
        url=INVESTOR_CENTRE,
    ),
    "2024-Half-Year-Report.pdf": DocSpec(
        source_id="hy24_half_year_report",
        doc_title="oOh!media HY24 Half Year Report",
        doc_type="half_year_report",
        period="HY24",
        url=INVESTOR_CENTRE,
    ),
    "2025-Half-Year-Report.pdf": DocSpec(
        source_id="hy25_half_year_report",
        doc_title="oOh!media HY25 Half Year Report",
        doc_type="half_year_report",
        period="HY25",
        url=INVESTOR_CENTRE,
    ),
    "oOh!media-FY25-Results-Presentation.pdf": DocSpec(
        source_id="fy25_results_presentation",
        doc_title="oOh!media FY25 Full Year Results Presentation",
        doc_type="investor_presentation",
        period="FY25",
        url=INVESTOR_CENTRE,
    ),
}


# ---------- chunking ----------

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def chunk_page_text(text: str, *, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Sliding-window chunker that never crosses the boundary it was given."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    step = size - overlap
    if step <= 0:
        step = size
    i = 0
    while i < len(text):
        chunk = text[i : i + size].strip()
        if chunk:
            chunks.append(chunk)
        if i + size >= len(text):
            break
        i += step
    return chunks


def parse_pdf(path: Path, spec: DocSpec) -> list[Chunk]:
    """Parse a single PDF into per-page Chunks."""
    out: list[Chunk] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            raw = page.extract_text() or ""
            for chunk_text in chunk_page_text(raw):
                out.append(
                    Chunk(
                        source_id=spec.source_id,
                        doc_title=spec.doc_title,
                        doc_type=spec.doc_type,
                        period=spec.period,
                        page=page.page_number,  # 1-indexed
                        text=chunk_text,
                        url=spec.url,
                    )
                )
    return out


# ---------- chroma ----------

COLLECTION_NAME = "oohmedia_investor"
CHROMA_PATH = Path("data/chroma")


def _open_collection() -> "chromadb.api.models.Collection.Collection":
    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    # embedding_function=None — we always supply our own vectors via core.embeddings.
    # This avoids Chroma trying to download its 79 MB default ONNX model.
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=None,  # type: ignore[arg-type]
        metadata={"hnsw:space": "cosine"},
    )


def _chunk_id(chunk: Chunk, idx: int) -> str:
    return f"{chunk.source_id}:p{chunk.page}:c{idx}"


def _upsert_chunks(collection, chunks: list[Chunk]) -> int:
    if not chunks:
        return 0
    # Group chunks by (source_id, page) so we can index within-page chunks deterministically.
    counters: dict[tuple[str, int], int] = {}
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []
    for c in chunks:
        key = (c.source_id, c.page or 0)
        idx = counters.get(key, 0)
        counters[key] = idx + 1
        ids.append(_chunk_id(c, idx))
        docs.append(c.text)
        metas.append(
            {
                "source_id": c.source_id,
                "doc_title": c.doc_title,
                "doc_type": c.doc_type,
                "period": c.period,
                "page": c.page if c.page is not None else -1,
                "url": c.url or "",
            }
        )
    embeddings = embed_texts(docs)
    # Upsert in slices so we don't blow past Chroma's per-call limit on big corpora.
    SLICE = 256
    for start in range(0, len(ids), SLICE):
        end = start + SLICE
        collection.upsert(
            ids=ids[start:end],
            documents=docs[start:end],
            metadatas=metas[start:end],
            embeddings=embeddings[start:end],
        )
    return len(ids)


# ---------- public entry ----------

def ingest(pdf_dir: str | Path) -> dict:
    """Ingest every known PDF in `pdf_dir`. Idempotent.

    Returns a small report dict with per-doc chunk counts and the total
    collection size after the run.
    """
    pdf_dir = Path(pdf_dir)
    if not pdf_dir.is_dir():
        raise FileNotFoundError(f"pdf_dir does not exist: {pdf_dir}")

    collection = _open_collection()
    per_doc: dict[str, int] = {}
    total_added = 0

    for filename, spec in DOCS.items():
        path = pdf_dir / filename
        if not path.exists():
            print(f"  [skip] {filename} — not present in {pdf_dir}")
            continue
        print(f"  [parse] {filename} ({spec.doc_type}, {spec.period})")
        chunks = parse_pdf(path, spec)
        n = _upsert_chunks(collection, chunks)
        per_doc[filename] = n
        total_added += n
        print(f"           {n} chunks upserted")

    total = collection.count()
    return {
        "per_doc": per_doc,
        "added": total_added,
        "collection_count": total,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m core.ingest <pdf_dir>", file=sys.stderr)
        return 2
    report = ingest(argv[1])
    print()
    print("== ingest report ==")
    for f, n in report["per_doc"].items():
        print(f"  {n:>5}  {f}")
    print(f"  -----")
    print(f"  {report['added']:>5}  total upserted this run")
    print(f"  {report['collection_count']:>5}  collection count after run")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
