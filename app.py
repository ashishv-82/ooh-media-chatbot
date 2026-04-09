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


st.set_page_config(page_title="oOh!Media Investor Chat", page_icon="📈")

# Widen the default centered column and match the bottom input bar
st.markdown(
    """<style>
    .block-container { max-width: 56rem !important; }
    [data-testid="stBottomBlockContainer"] { max-width: 56rem !important; margin-left: auto; margin-right: auto; }
    </style>""",
    unsafe_allow_html=True,
)

st.markdown("<h1 style='text-align:center'>oOh!Media Investor Chat</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center;color:grey'>Ask questions about oOh!Media investor materials.</p>", unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []

# ── Capture new user input ──
prompt = st.chat_input("Ask a question about oOh!Media...")
if prompt:
    prior_history = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages
    ]
    # Append user message and a "thinking" placeholder for the assistant.
    # The loop below renders both so they always come from one code path.
    st.session_state.messages.append(
        {"role": "user", "content": prompt, "citations": None}
    )
    st.session_state.messages.append(
        {"role": "assistant", "content": None, "citations": None,
         "_pending": True, "_question": prompt, "_history": prior_history}
    )

# ── Single rendering loop — sole source of truth ──
for msg in st.session_state.messages:
    if msg.get("_pending"):
        # Render the spinner; answer() blocks here so the placeholder stays visible
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    result = answer(msg["_question"], msg["_history"])
                except Exception as exc:
                    st.error(f"Something went wrong: {exc}")
                    st.stop()
            st.markdown(_md(result.text))
            _render_citations(result.citations)
        # Replace the placeholder with the real answer in state, then rerun
        # so the next render loop sees a plain message (no _pending flag).
        idx = st.session_state.messages.index(msg)
        st.session_state.messages[idx] = {
            "role": "assistant",
            "content": result.text,
            "citations": result.citations,
        }
        st.rerun()
    else:
        with st.chat_message(msg["role"]):
            st.markdown(_md(msg["content"]))
            if msg.get("citations"):
                _render_citations(msg["citations"])
