# Investor materials — corpus justification (US-02 AC4, AC5)

All five PDFs below were sourced from the oOh!media investor centre at
<https://investors.oohmedia.com.au/investor-centre/> (presentations subpage:
<https://investors.oohmedia.com.au/investor-centre/?page=presentations---webcasts>,
results & reports subpage: <https://investors.oohmedia.com.au/investor-centre/?page=results---reports>).

The selection covers **three document types** across **two reporting periods**,
which exceeds US-02 AC5's "at least two different document types and two
different reporting periods" minimum.

| File | Type | Period | Source |
|---|---|---|---|
| `oOh!media-Annual-Report-2024.pdf` | annual_report | FY24 | investor centre → results & reports |
| `oOh!media-Annual-Report-2025.pdf` | annual_report | FY25 | investor centre → results & reports |
| `2024-Half-Year-Report.pdf` | half_year_report | HY24 | investor centre → results & reports |
| `2025-Half-Year-Report.pdf` | half_year_report | HY25 | investor centre → results & reports |
| `oOh!media-FY25-Results-Presentation.pdf` | investor_presentation | FY25 | investor centre → presentations & webcasts |

## Why this set

- **Annual reports + half-year reports + an investor presentation** covers all
  three document types named in US-02 AC1/AC2.
- **FY24 paired with FY25** (and the matching half-year periods) makes US-05's
  showcase question "what did management say about revenue in the FY24 results
  and how did the share price react over the following quarter?" answerable
  from the corpus.
- **Five files (~36 MB total)** fits comfortably inside the build timebox for
  parsing + embedding while still exercising every doc_type in the schema.

## Adding more documents later

`core/ingest.py` is idempotent (deterministic chunk IDs + Chroma upsert).
To add a new document:

1. Drop the PDF under `data/pdfs/`.
2. Add a `DocSpec` entry to the `DOCS` dict in `core/ingest.py` with a stable
   `source_id`, `doc_title`, `doc_type`, `period`, and `url`.
3. Re-run `uv run python -m core.ingest data/pdfs`. Existing chunks are
   replaced in place; the new doc's chunks are added.
