"""Streamlit chat UI. Imports only from `core`.

Implemented in US-01.
"""

from __future__ import annotations

import streamlit as st

from core.assistant import answer
from core.schema import Citation


def _md(text: str) -> str:
    """Escape `$` so Streamlit's markdown renderer doesn't treat dollar
    amounts as LaTeX math delimiters. Without this, "$635.6m" gets parsed
    as inline math and renders as garbled KaTeX output.
    """
    return text.replace("$", "\\$") if text else text


def _render_citations(citations: list[Citation]) -> None:
    """Render a numbered citation list under an answer."""
    if not citations:
        return
    with st.expander(f"Sources ({len(citations)})"):
        for i, cit in enumerate(citations, start=1):
            page_label = f", p. {cit.page}" if cit.page is not None else ""
            header = f"**[{i}] {cit.doc_title}** — {cit.doc_type}, {cit.period}{page_label}"
            if cit.url:
                header += f"  \n[{cit.url}]({cit.url})"
            st.markdown(_md(header))
            st.caption(_md(cit.snippet))


st.set_page_config(page_title="oOh!media Investor Chat", page_icon="📈")
st.title("oOh!media Investor Chat")
st.caption("Ask questions about oOh!media investor materials.")

# session_state schema:
#   messages: list of {role, content, citations}
#   citations is list[Citation] for assistant turns, None for user turns
if "messages" not in st.session_state:
    st.session_state.messages = []

# Render prior conversation turns
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(_md(msg["content"]))
        if msg.get("citations"):
            _render_citations(msg["citations"])

# Input box — returns None when empty
prompt = st.chat_input("Ask a question about oOh!media...")

if prompt:
    # Show the user's message immediately
    with st.chat_message("user"):
        st.markdown(_md(prompt))

    # Build history: everything already in state (user + assistant turns)
    # assistant.answer() appends the current question itself, so we pass
    # only the prior turns here.
    prior_history = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages
    ]

    # Persist the user turn
    st.session_state.messages.append(
        {"role": "user", "content": prompt, "citations": None}
    )

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                result = answer(prompt, prior_history)
            except Exception as exc:
                st.error(f"Something went wrong: {exc}")
                st.stop()

        st.markdown(_md(result.text))
        _render_citations(result.citations)

    # Persist the assistant turn (with citations for re-rendering on reload)
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result.text,
            "citations": result.citations,
        }
    )
