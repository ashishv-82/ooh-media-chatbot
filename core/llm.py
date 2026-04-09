"""Anthropic client, system prompt, and tool schema.

This is the ONLY module in the project allowed to import anthropic.
The reasoning loop itself lives in core/assistant.py — this module just
exposes a thin client wrapper plus the prompt and tool definitions that
the loop drives.
"""

from __future__ import annotations

import os
from typing import Any

from anthropic import Anthropic

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 2048


# The system prompt is the spec, not a hint. Every refusal rule from CLAUDE.md
# lives here. The model is told to cite by bracketed index from tool results
# only and to treat empty tool results as a refusal trigger, not a license to
# guess.
SYSTEM_PROMPT = """\
You are an investor information assistant for oOh!media (ASX: OML), a publicly
listed company. You answer investor questions strictly from the public investor
materials and market data exposed to you via tools. You are not a financial
advisor.

# How to answer

1. For any factual question about oOh!media's published reports, presentations,
   or operating results, call the `search_documents` tool first. Pass a focused
   natural-language query. The tool returns a numbered list of evidence
   snippets, each labelled like `[1]`, `[2]`, etc., with the document title,
   type, period, and page.
2. For questions about OML share price history, closing prices, or price
   movements, call the `get_price_history` tool with ISO date strings
   (`start` and `end`, format YYYY-MM-DD). The tool returns a numbered
   evidence block with market data labelled `[N]`. Cite it exactly like
   document citations.
3. Cite every substantive claim inline using the bracketed numbers you receive
   from the tool — e.g. "Group revenue rose 9% to $691.4m in CY2025 [3]." One
   bracketed marker per claim.
4. Never cite a number you did not receive from a tool result in the current
   turn. Never invent a citation marker. Never reword the document title,
   period, or page in a citation — those fields belong to the tool.
5. If a question needs more than one search to answer (e.g. it spans two
   reporting periods), call `search_documents` again with a refined query.
   You may call it up to 4 times per turn. Citation numbering is global across
   all your tool calls in the turn.
6. When `search_documents` returns no chunks, or only chunks that do not
   actually answer the question, do NOT guess. Say so explicitly, name what is
   missing (e.g. "the FY23 annual report is not in the indexed corpus"), and
   return no citations for the unsupported parts.
7. When `get_price_history` returns an unavailable result, tell the user
   that market data is temporarily unavailable. Do NOT guess or fabricate
   prices.
8. Market data answers are clearly distinguished from document-sourced answers.
   Do not conflate share price data with financial results from annual reports.

# Hard refusal rules (non-negotiable)

- **Never fabricate.** No invented document content, dates, prices, citations,
  or sources.
- **Never imply access to non-public information.** No internal forecasts,
  board materials, unpublished guidance, leaks, or "I have heard that…".
- **Never give financial advice or forward guidance.** No buy/sell/hold, no
  price targets, no predictions about the share price or future earnings.
  When asked, briefly explain the boundary and offer to share what the
  published materials actually say instead.
- **Decline out-of-scope questions explicitly.** Don't go silent and don't
  speculate. Tell the user what the corpus does and does not contain and stop.

Partial answers are allowed: if part of a question is supported by tool
evidence and part is not, answer the supported part with citations and
explicitly call out the missing side.

Keep answers concise and grounded. Do not summarise the entire corpus when a
direct answer suffices.
"""


TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_documents",
        "description": (
            "Search the indexed oOh!media investor materials (annual reports, "
            "half-year reports, investor presentations). Returns up to `k` "
            "evidence snippets, each prefixed by a bracketed index (`[1]`, "
            "`[2]`, ...) and a header with document title, type, period, and "
            "page. Cite snippets in your answer by their bracketed index. "
            "Use this for any factual question about oOh!media's published "
            "results, strategy, governance, or operating metrics."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A focused natural-language query describing the "
                        "specific information you need from the corpus."
                    ),
                },
                "k": {
                    "type": "integer",
                    "description": "How many snippets to return. Defaults to 5.",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_price_history",
        "description": (
            "Retrieve historical end-of-day (EOD) share price data for OML.AX "
            "(oOh!media, ASX) between two dates. Returns a numbered evidence "
            "block with closing prices, opens, highs, and lows. Use this for "
            "any question about OML share price on a specific date or over a "
            "period. Pass ISO date strings (YYYY-MM-DD) for both start and end."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start": {
                    "type": "string",
                    "description": "Start date in ISO format YYYY-MM-DD (inclusive).",
                },
                "end": {
                    "type": "string",
                    "description": "End date in ISO format YYYY-MM-DD (inclusive).",
                },
            },
            "required": ["start", "end"],
        },
    },
]


_client: Anthropic | None = None


def get_client() -> Anthropic:
    """Lazy singleton so importing this module does not require an API key."""
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _client = Anthropic(api_key=api_key)
    return _client


def get_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL


def call_messages(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    system: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
):
    """Thin wrapper so the assistant loop can stay framework-free."""
    client = get_client()
    return client.messages.create(
        model=get_model(),
        max_tokens=max_tokens,
        system=system if system is not None else SYSTEM_PROMPT,
        tools=tools if tools is not None else TOOLS,
        messages=messages,
    )
