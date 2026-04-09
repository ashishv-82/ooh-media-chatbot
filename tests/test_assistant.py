"""US-03/US-05 — tool-use loop and citation extraction tests for core/assistant.py.

These tests stub the Anthropic client and core.retrieval so the suite runs
offline. The point is to verify that the loop:
  - calls search_documents when the model issues a tool_use,
  - numbers chunks globally across multiple tool calls,
  - extracts only valid [N] markers into the citations list,
  - returns an empty citations list on a refusal (empty retrieval),
  - handles both search_documents and get_price_history in a single turn (US-05),
  - produces partial answers when one source is unavailable (US-05 AC4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import core.assistant as assistant_mod
from core.schema import Citation


# ---------- tiny stand-ins for anthropic SDK content blocks ----------


@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class _Response:
    stop_reason: str
    content: list


def _make_citations(*specs: tuple[str, str, int, str]) -> list[Citation]:
    out: list[Citation] = []
    for source_id, period, page, snippet in specs:
        out.append(
            Citation(
                source_id=source_id,
                doc_title=f"oOh!media {period} Annual Report",
                doc_type="annual_report",
                period=period,
                page=page,
                snippet=snippet,
                url="https://investors.oohmedia.com.au/investor-centre/",
            )
        )
    return out


# ---------- happy path: one tool_use → one end_turn with citations ----------


def test_answer_returns_citations_for_supported_question(monkeypatch):
    captured_calls: list[list[dict[str, Any]]] = []

    fake_chunks = _make_citations(
        ("fy24_annual_report", "FY24", 18, "Group revenue rose to A$635.6m..."),
        ("fy24_annual_report", "FY24", 19, "Adjusted underlying EBITDA was A$129m..."),
    )

    def fake_search(query, k=5):
        return fake_chunks

    monkeypatch.setattr(assistant_mod.retrieval, "search", fake_search)

    responses = iter(
        [
            _Response(
                stop_reason="tool_use",
                content=[
                    _ToolUseBlock(
                        id="toolu_1",
                        name="search_documents",
                        input={"query": "FY24 revenue and EBITDA", "k": 5},
                    )
                ],
            ),
            _Response(
                stop_reason="end_turn",
                content=[
                    _TextBlock(
                        text=(
                            "Group revenue rose to A$635.6m in FY24 [1], with "
                            "adjusted underlying EBITDA of A$129m [2]."
                        )
                    )
                ],
            ),
        ]
    )

    def fake_call_messages(messages, **kwargs):
        captured_calls.append(messages)
        return next(responses)

    monkeypatch.setattr(assistant_mod.llm, "call_messages", fake_call_messages)

    result = assistant_mod.answer("What was FY24 revenue and EBITDA?", history=None)

    assert "[1]" in result.text
    assert "[2]" in result.text
    assert len(result.citations) == 2
    assert result.citations[0].period == "FY24"
    assert result.citations[0].page == 18
    assert result.citations[1].page == 19
    # Two API calls: one tool_use, one end_turn.
    assert len(captured_calls) == 2
    # The second call must include the assistant tool_use turn and the user tool_result turn.
    assert captured_calls[1][-2]["role"] == "assistant"
    assert captured_calls[1][-1]["role"] == "user"


# ---------- refusal path: empty retrieval → empty citations ----------


def test_answer_refuses_when_retrieval_is_empty(monkeypatch):
    monkeypatch.setattr(assistant_mod.retrieval, "search", lambda q, k=5: [])

    responses = iter(
        [
            _Response(
                stop_reason="tool_use",
                content=[
                    _ToolUseBlock(
                        id="toolu_1",
                        name="search_documents",
                        input={"query": "FY19 annual report"},
                    )
                ],
            ),
            _Response(
                stop_reason="end_turn",
                content=[
                    _TextBlock(
                        text=(
                            "The FY19 annual report is not in the indexed corpus, "
                            "so I cannot answer this from the available materials."
                        )
                    )
                ],
            ),
        ]
    )
    monkeypatch.setattr(
        assistant_mod.llm, "call_messages", lambda messages, **kw: next(responses)
    )

    result = assistant_mod.answer("What was in the FY19 annual report?", history=None)
    assert result.citations == []
    assert "not in the indexed corpus" in result.text.lower()


# ---------- global numbering across two tool_use rounds ----------


def test_global_citation_numbering_across_two_searches(monkeypatch):
    first_batch = _make_citations(
        ("fy24_annual_report", "FY24", 18, "Revenue A$635.6m"),
        ("fy24_annual_report", "FY24", 19, "EBITDA A$129m"),
    )
    second_batch = _make_citations(
        ("fy25_annual_report", "FY25", 29, "Revenue A$691.4m"),
    )
    batches = iter([first_batch, second_batch])
    monkeypatch.setattr(assistant_mod.retrieval, "search", lambda q, k=5: next(batches))

    responses = iter(
        [
            _Response(
                stop_reason="tool_use",
                content=[_ToolUseBlock(id="t1", name="search_documents", input={"query": "FY24"})],
            ),
            _Response(
                stop_reason="tool_use",
                content=[_ToolUseBlock(id="t2", name="search_documents", input={"query": "FY25"})],
            ),
            _Response(
                stop_reason="end_turn",
                content=[
                    _TextBlock(
                        text=(
                            "FY24 revenue was A$635.6m [1] with EBITDA of A$129m [2]. "
                            "FY25 revenue grew to A$691.4m [3]."
                        )
                    )
                ],
            ),
        ]
    )
    monkeypatch.setattr(
        assistant_mod.llm, "call_messages", lambda messages, **kw: next(responses)
    )

    result = assistant_mod.answer("Compare FY24 and FY25 revenue.", history=None)
    assert len(result.citations) == 3
    # Order matches the [1], [2], [3] markers in the text.
    assert result.citations[0].period == "FY24"
    assert result.citations[1].period == "FY24"
    assert result.citations[2].period == "FY25"


# ---------- bogus markers are silently dropped ----------


def test_invalid_marker_indices_are_dropped(monkeypatch):
    monkeypatch.setattr(
        assistant_mod.retrieval,
        "search",
        lambda q, k=5: _make_citations(("fy24_annual_report", "FY24", 18, "Some text")),
    )
    responses = iter(
        [
            _Response(
                stop_reason="tool_use",
                content=[_ToolUseBlock(id="t1", name="search_documents", input={"query": "x"})],
            ),
            _Response(
                stop_reason="end_turn",
                content=[_TextBlock(text="Real claim [1] and a hallucinated one [99].")],
            ),
        ]
    )
    monkeypatch.setattr(
        assistant_mod.llm, "call_messages", lambda messages, **kw: next(responses)
    )

    result = assistant_mod.answer("anything", history=None)
    assert len(result.citations) == 1
    assert result.citations[0].period == "FY24"


# ---------- US-05: combined document + market data in one turn ----------


def _make_market_citation(period: str, snippet: str) -> Citation:
    return Citation(
        source_id="marketstack_oml_ax",
        doc_title="OML.AX Market Data (Marketstack)",
        doc_type="market_data",
        period=period,
        page=None,
        snippet=snippet,
        url=None,
    )


def test_combined_document_and_market_data_answer(monkeypatch):
    """US-05 AC1-3: model calls both tools and produces combined citations."""
    doc_chunk = _make_citations(("fy24_annual_report", "FY24", 12, "Revenue A$635.6m in FY24"))[0]
    market_chunk = _make_market_citation(
        "2024-07-01/2024-09-30",
        "2024-07-01: close AUD 1.450; 2024-09-30: close AUD 1.520",
    )

    monkeypatch.setattr(
        assistant_mod.retrieval,
        "search",
        lambda q, k=5: [doc_chunk],
    )

    # Simulate _format_price_result returning a market_data Citation by patching
    # _format_price_result directly so we don't need a real API key.
    def fake_format_price(tool_input, start_index):
        text = (
            f"Market data for OML.AX from 2024-07-01 to 2024-09-30.\n"
            f"[{start_index}] OML.AX Market Data (market_data, 2024-07-01/2024-09-30)\n"
            f"{market_chunk.snippet}\n"
            f"Cite this data as [{start_index}] in your answer."
        )
        return (text, {start_index: market_chunk})

    monkeypatch.setattr(assistant_mod, "_format_price_result", fake_format_price)

    responses = iter(
        [
            # Model calls both tools simultaneously in one turn.
            _Response(
                stop_reason="tool_use",
                content=[
                    _ToolUseBlock(
                        id="t1",
                        name="search_documents",
                        input={"query": "FY24 revenue management commentary"},
                    ),
                    _ToolUseBlock(
                        id="t2",
                        name="get_price_history",
                        input={"start": "2024-07-01", "end": "2024-09-30"},
                    ),
                ],
            ),
            _Response(
                stop_reason="end_turn",
                content=[
                    _TextBlock(
                        text=(
                            "Management reported revenue of A$635.6m in FY24 [1]. "
                            "In the following quarter (Q3 2024), the share price moved "
                            "from AUD 1.450 to AUD 1.520 [2]."
                        )
                    )
                ],
            ),
        ]
    )
    monkeypatch.setattr(
        assistant_mod.llm, "call_messages", lambda messages, **kw: next(responses)
    )

    result = assistant_mod.answer(
        "What did management say about revenue in FY24 and how did the share price move after?",
        history=None,
    )

    assert "[1]" in result.text
    assert "[2]" in result.text
    assert len(result.citations) == 2
    # AC2: document citation present
    assert any(c.doc_type == "annual_report" for c in result.citations)
    # AC3: market_data citation present
    assert any(c.doc_type == "market_data" for c in result.citations)
    # AC5: single coherent answer (both markers in same text block, not two fragments)
    assert result.text.count("[1]") >= 1
    assert result.text.count("[2]") >= 1


# ---------- US-06: financial-advice refusal ----------


def test_answer_refuses_financial_advice(monkeypatch):
    """US-06 AC3: assistant declines buy/sell/hold questions without fabricating."""
    # Retrieval is patched but should not be called — model refuses directly.
    monkeypatch.setattr(assistant_mod.retrieval, "search", lambda q, k=5: [])

    responses = iter(
        [
            _Response(
                stop_reason="end_turn",
                content=[
                    _TextBlock(
                        text=(
                            "I'm not able to provide financial advice or investment "
                            "recommendations such as whether to buy, sell, or hold OML shares. "
                            "This assistant is restricted to factual information from "
                            "oOh!media's publicly available investor materials. "
                            "Please consult a licensed financial adviser for investment decisions."
                        )
                    )
                ],
            )
        ]
    )
    monkeypatch.setattr(
        assistant_mod.llm, "call_messages", lambda messages, **kw: next(responses)
    )

    result = assistant_mod.answer("Should I buy OML shares?", history=None)

    # AC3: citations must be empty — no fabricated sources
    assert result.citations == []
    # AC3: refusal text must explain the financial-advice boundary
    lower = result.text.lower()
    assert any(
        phrase in lower
        for phrase in ("financial advice", "investment", "buy", "sell", "hold", "licensed")
    )
    # AC5: no fake document title should appear
    assert "annual report" not in lower
    assert "half-year" not in lower


# ---------- US-06: non-public information refusal ----------


def test_answer_refuses_non_public_information(monkeypatch):
    """US-06 AC2: assistant declines questions about non-public board/internal info."""
    monkeypatch.setattr(assistant_mod.retrieval, "search", lambda q, k=5: [])

    responses = iter(
        [
            _Response(
                stop_reason="end_turn",
                content=[
                    _TextBlock(
                        text=(
                            "I don't have access to non-public company information such as "
                            "private board meeting discussions, internal forecasts, or "
                            "unpublished guidance. My answers are limited to publicly available "
                            "investor materials published by oOh!media."
                        )
                    )
                ],
            )
        ]
    )
    monkeypatch.setattr(
        assistant_mod.llm, "call_messages", lambda messages, **kw: next(responses)
    )

    result = assistant_mod.answer(
        "What did the board discuss at their last private meeting?", history=None
    )

    # AC2: citations must be empty
    assert result.citations == []
    # AC2: refusal must mention non-public boundary
    lower = result.text.lower()
    assert any(
        phrase in lower
        for phrase in ("non-public", "not have access", "board", "internal", "private")
    )
    # AC5: no fabricated sources
    assert "annual report" not in lower


# ---------- US-06: out-of-scope boundary explanation ----------


def test_answer_explains_out_of_scope_boundary(monkeypatch):
    """US-06 AC4: assistant explains the scope boundary for irrelevant questions."""
    # Model searches, finds nothing relevant, and explains the scope.
    monkeypatch.setattr(assistant_mod.retrieval, "search", lambda q, k=5: [])

    responses = iter(
        [
            _Response(
                stop_reason="tool_use",
                content=[
                    _ToolUseBlock(
                        id="toolu_oos",
                        name="search_documents",
                        input={"query": "competitor analysis outdoor advertising industry"},
                    )
                ],
            ),
            _Response(
                stop_reason="end_turn",
                content=[
                    _TextBlock(
                        text=(
                            "This assistant only covers oOh!media's own publicly available "
                            "investor materials. Questions about competitors or general industry "
                            "analysis fall outside the scope of the indexed corpus. "
                            "I cannot provide that information here."
                        )
                    )
                ],
            ),
        ]
    )
    monkeypatch.setattr(
        assistant_mod.llm, "call_messages", lambda messages, **kw: next(responses)
    )

    result = assistant_mod.answer(
        "How does oOh!media compare to its competitors in the outdoor advertising market?",
        history=None,
    )

    # AC4: citations must be empty — no invented comparisons
    assert result.citations == []
    # AC4: response explains scope boundary rather than speculating
    lower = result.text.lower()
    assert any(
        phrase in lower
        for phrase in ("scope", "outside", "only covers", "cannot provide", "indexed corpus")
    )
    # AC5: no fabricated competitor names or document references
    assert "[1]" not in result.text
    assert "[2]" not in result.text


def test_partial_answer_when_market_data_unavailable(monkeypatch):
    """US-05 AC4: answers from docs only when price data is missing, states gap."""
    doc_chunk = _make_citations(("fy24_annual_report", "FY24", 12, "Revenue A$635.6m in FY24"))[0]

    monkeypatch.setattr(
        assistant_mod.retrieval,
        "search",
        lambda q, k=5: [doc_chunk],
    )

    def fake_format_price_unavailable(tool_input, start_index):
        return (
            "No OML.AX price data found for the period 2035-01-01 to 2035-03-31. "
            "The exchange may not have traded on the requested dates.",
            {},
        )

    monkeypatch.setattr(assistant_mod, "_format_price_result", fake_format_price_unavailable)

    responses = iter(
        [
            _Response(
                stop_reason="tool_use",
                content=[
                    _ToolUseBlock(
                        id="t1",
                        name="search_documents",
                        input={"query": "FY24 revenue management commentary"},
                    ),
                    _ToolUseBlock(
                        id="t2",
                        name="get_price_history",
                        input={"start": "2035-01-01", "end": "2035-03-31"},
                    ),
                ],
            ),
            _Response(
                stop_reason="end_turn",
                content=[
                    _TextBlock(
                        text=(
                            "Management reported revenue of A$635.6m in FY24 [1]. "
                            "Market data for Q1 2035 is not available — "
                            "no price data exists for that future period."
                        )
                    )
                ],
            ),
        ]
    )
    monkeypatch.setattr(
        assistant_mod.llm, "call_messages", lambda messages, **kw: next(responses)
    )

    result = assistant_mod.answer(
        "What did management say about revenue in FY24 and how did the share price move in Q1 2035?",
        history=None,
    )

    # AC4: doc citation present, no market_data citation
    assert len(result.citations) == 1
    assert result.citations[0].doc_type == "annual_report"
    assert not any(c.doc_type == "market_data" for c in result.citations)
    # AC4: text explicitly mentions missing market data
    assert "not available" in result.text.lower() or "no price" in result.text.lower()
