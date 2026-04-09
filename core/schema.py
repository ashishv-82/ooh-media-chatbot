"""Citation, Chunk, and AnswerWithCitations dataclasses.

This schema is the contract between every layer of the system: ingest populates
it, retrieval and the price provider return it, the LLM selects from it, and
both surfaces (Streamlit + MCP) render from it. Fields must flow end-to-end
unchanged — the LLM is not allowed to invent, merge, or reword them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Chunk:
    """A retrievable unit produced by ingest. Carries everything needed to
    construct a Citation if this chunk is used in an answer."""

    source_id: str
    doc_title: str
    doc_type: str  # "annual_report" | "half_year_report" | "investor_presentation"
    period: str  # e.g. "FY24", "HY25"
    page: int | None
    text: str
    url: str | None = None


@dataclass
class Citation:
    source_id: str          # stable id, e.g. "fy24_annual_report"
    doc_title: str          # e.g. "oOh!media FY24 Annual Report"
    doc_type: str           # "annual_report" | "half_year_report" | "investor_presentation" | "market_data"
    period: str             # e.g. "FY24", "HY25", or ISO date range for market data
    page: int | None        # page number for PDFs, None for market data
    snippet: str            # the exact text or data point used
    url: str | None         # investor-centre URL if known


@dataclass
class AnswerWithCitations:
    text: str               # the answer, with inline markers like [1], [2]
    citations: list[Citation] = field(default_factory=list)
