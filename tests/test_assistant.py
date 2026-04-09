"""US-03 — tool-use loop and citation extraction tests for core/assistant.py.

These tests stub the Anthropic client and core.retrieval so the suite runs
offline. The point is to verify that the loop:
  - calls search_documents when the model issues a tool_use,
  - numbers chunks globally across multiple tool calls,
  - extracts only valid [N] markers into the citations list,
  - returns an empty citations list on a refusal (empty retrieval).
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
