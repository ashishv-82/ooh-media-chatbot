"""The single reasoning entry point for the system.

`answer(question, history) -> AnswerWithCitations` runs the Anthropic
tool-use loop with one tool (`search_documents`) backed by core/retrieval.
US-04 will plug a second tool (`get_price_history`) into the same loop
without changing the answer assembly.
"""

from __future__ import annotations

import re
from typing import Any

from core import llm, prices, retrieval
from core.schema import AnswerWithCitations, Citation

# Hard cap on the tool-use loop. Defensive — should never trip in normal use.
MAX_ITERATIONS = 6


# ---------- tool dispatch ----------

def _format_tool_result(citations: list[Citation], start_index: int) -> tuple[str, dict[int, Citation]]:
    """Render retrieved chunks as a human-numbered evidence block.

    Returns (text_for_model, {global_index: citation}). Numbering is global
    across the whole turn so a second search call cannot collide with the
    first call's citation indices.
    """
    if not citations:
        return (
            "No matching documents in the indexed corpus. "
            "Treat this as a refusal trigger and tell the user explicitly "
            "that the information is not in the indexed materials.",
            {},
        )
    chunks_by_index: dict[int, Citation] = {}
    lines = [
        f"Found {len(citations)} chunks. "
        "Cite each one in your answer by its bracketed [N] index. "
        "Do not invent or merge citations.\n"
    ]
    for offset, cit in enumerate(citations):
        idx = start_index + offset
        chunks_by_index[idx] = cit
        page = f"p.{cit.page}" if cit.page is not None else "n/a"
        lines.append(
            f"[{idx}] {cit.doc_title} ({cit.doc_type}, {cit.period}, {page})\n"
            f"{cit.snippet}\n"
        )
    return ("\n".join(lines), chunks_by_index)


def _run_search_tool(tool_input: dict[str, Any]) -> list[Citation]:
    query = (tool_input or {}).get("query", "")
    k = int((tool_input or {}).get("k", 5))
    if not query:
        return []
    return retrieval.search(query, k=k)


def _format_price_result(
    tool_input: dict[str, Any], start_index: int
) -> tuple[str, dict[int, Citation]]:
    """Call the price provider and format the result as an evidence block.

    Returns (text_for_model, {global_index: Citation}).
    """
    inp = tool_input or {}
    start = inp.get("start", "")
    end = inp.get("end", "")

    if not start or not end:
        return ("Invalid price tool call: 'start' and 'end' are required.", {})

    provider = prices.get_provider()
    if provider is None:
        return (
            "Market data is unavailable: no price provider API key is configured "
            "(set MARKETSTACK_API_KEY or ALPHAVANTAGE_API_KEY).",
            {},
        )

    result = provider.get_price_history(start, end)

    if not result.get("available"):
        error = result.get("error", "unknown error")
        return (
            f"Market data is temporarily unavailable: {error}. "
            "Do not guess or fabricate prices.",
            {},
        )

    data: list[dict[str, Any]] = result.get("data", [])
    if not data:
        return (
            f"No OML.AX price data found for the period {start} to {end}. "
            "The exchange may not have traded on the requested dates.",
            {},
        )

    source = result.get("source", "unknown")
    period_str = f"{start}/{end}"

    # Build a compact snippet: all rows if ≤ 10, else first+last with count.
    rows_sorted = sorted(data, key=lambda r: r.get("date", ""))
    if len(rows_sorted) <= 10:
        snippet_lines = [
            f"{_fmt_date(r['date'])}: close AUD {r['close']:.3f}"
            for r in rows_sorted
        ]
    else:
        head = rows_sorted[:5]
        tail = rows_sorted[-5:]
        snippet_lines = (
            [f"{_fmt_date(r['date'])}: close AUD {r['close']:.3f}" for r in head]
            + [f"... ({len(rows_sorted) - 10} rows omitted) ..."]
            + [f"{_fmt_date(r['date'])}: close AUD {r['close']:.3f}" for r in tail]
        )
    snippet = "; ".join(snippet_lines)

    citation = Citation(
        source_id=f"{source}_{prices.SYMBOL.replace('.', '_').lower()}",
        doc_title=f"OML.AX Market Data ({source.capitalize()})",
        doc_type="market_data",
        period=period_str,
        page=None,
        snippet=snippet,
        url=None,
    )

    idx = start_index
    text = (
        f"Market data for {prices.SYMBOL} from {start} to {end} "
        f"(source: {source}, {len(rows_sorted)} trading days).\n\n"
        f"[{idx}] OML.AX Market Data (market_data, {period_str})\n"
        f"{snippet}\n\n"
        "Cite this data as [" + str(idx) + "] in your answer. "
        "Quote exact dates and prices. "
        "Do not fabricate values not shown above."
    )
    return (text, {idx: citation})


def _fmt_date(date_str: str) -> str:
    """Extract YYYY-MM-DD from an ISO datetime string."""
    return date_str[:10] if date_str else ""


# ---------- citation extraction ----------

_CITATION_PATTERN = re.compile(r"\[(\d+)\]")


def _extract_and_renumber(
    text: str, chunks_by_index: dict[int, Citation]
) -> tuple[str, list[Citation]]:
    """Pull `[N]` markers out of the final answer text in order of first
    appearance, drop any markers the model invented, and renumber the
    surviving markers to a contiguous `[1], [2], [3], ...` sequence so
    `citations[i-1]` is the source for marker `[i]` in the rendered text.

    Returns the rewritten text and the matching ordered Citation list.
    """
    # First pass: discover which valid global indices the model actually used,
    # in order of first appearance in the text.
    order: list[int] = []
    for m in _CITATION_PATTERN.finditer(text):
        idx = int(m.group(1))
        if idx in chunks_by_index and idx not in order:
            order.append(idx)

    # Build the global -> sequential renumbering map.
    renumber = {old: new for new, old in enumerate(order, start=1)}

    # Second pass: rewrite every marker. Valid ones are renumbered;
    # invalid ones (model errors) are stripped from the text.
    def _replace(match: re.Match) -> str:
        old = int(match.group(1))
        if old in renumber:
            return f"[{renumber[old]}]"
        return ""

    rewritten = _CITATION_PATTERN.sub(_replace, text)
    citations = [chunks_by_index[old] for old in order]
    return rewritten, citations


# ---------- main entry ----------

def _block_text(content: list[Any]) -> str:
    return "".join(getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text")


def answer(
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> AnswerWithCitations:
    """Single reasoning entry point.

    `history` is a list of prior `{"role": "user"|"assistant", "content": str}`
    turns from the same session, oldest first. It is passed through to the
    Anthropic messages API verbatim. The current `question` is appended as a
    new user turn before the loop starts.
    """
    messages: list[dict[str, Any]] = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})

    chunks_by_index: dict[int, Citation] = {}
    next_index = 1

    for _ in range(MAX_ITERATIONS):
        response = llm.call_messages(messages)
        stop_reason = getattr(response, "stop_reason", None)
        content = list(getattr(response, "content", []) or [])

        if stop_reason == "tool_use":
            # Append the model's tool-use turn verbatim — Anthropic requires the
            # original content blocks back when we send the tool_result.
            messages.append({"role": "assistant", "content": content})

            tool_results: list[dict[str, Any]] = []
            for block in content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if block.name == "search_documents":
                    found = _run_search_tool(getattr(block, "input", {}) or {})
                    text, new_chunks = _format_tool_result(found, next_index)
                    chunks_by_index.update(new_chunks)
                    next_index += len(new_chunks)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": text,
                        }
                    )
                elif block.name == "get_price_history":
                    text, new_chunks = _format_price_result(
                        getattr(block, "input", {}) or {}, next_index
                    )
                    chunks_by_index.update(new_chunks)
                    next_index += len(new_chunks)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": text,
                        }
                    )
                else:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Unknown tool: {block.name}",
                            "is_error": True,
                        }
                    )

            messages.append({"role": "user", "content": tool_results})
            continue

        # Any other stop_reason — including end_turn, max_tokens, stop_sequence —
        # is the end of the loop. Extract the assistant text and the citations
        # actually present in it.
        text = _block_text(content)
        text, citations = _extract_and_renumber(text, chunks_by_index)
        return AnswerWithCitations(text=text, citations=citations)

    # Loop exhausted without an end_turn. Refusal, no citations.
    return AnswerWithCitations(
        text=(
            "I wasn't able to converge on an answer within the allowed number of "
            "tool calls. Please rephrase or narrow the question."
        ),
        citations=[],
    )
