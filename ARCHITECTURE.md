# Architecture — Investor Chat for oOh!media

Grounded in `Candidate_01_Candidate_Brief.docx`, `Candidate_02_Product_Requirements_Document.docx`, `Candidate_03_Product_Solution_Design.docx`, and `Candidate_04_User_Stories.docx`.

## Product in one line

> "A chatbot that answers investor questions about oOh!media using the company's public investor materials and market data." — Candidate Brief

The assistant must be "a reusable capability, multiple surfaces, grounded answers" (Solution Design) exposed via a web chat **and** a second surface, with every substantive claim traceable to a source (PRD, NFR: Grounding).

## Components

The Solution Design names five capabilities; this architecture maps one-to-one:

1. **Chat interface (US-01, FR-01).** Streamlit web app. Maintains per-session history, streams tokens, surfaces backend errors as visible messages rather than blank screens (US-01 AC4).
2. **Knowledge layer (US-02, FR-02).** A local corpus of oOh!media public PDFs from `https://investors.oohmedia.com.au/investor-centre/`, parsed with pdfplumber, chunked with page-level provenance, embedded with OpenAI `text-embedding-3-small`, and persisted in ChromaDB. Covers "at least two different document types and two different reporting periods" (US-02 AC5). Re-running ingest adds new docs without a rebuild (US-02 AC6).
3. **Market data (US-04, FR-04).** A `PriceProvider` interface with two implementations behind it. **Marketstack v2** (HTTPS, symbol `OML.AX`, endpoint `https://api.marketstack.com/v2/eod`) is the primary provider — its free tier covers ASX. **Alpha Vantage** is kept as a secondary scaffold but does not cover ASX on free tier (`OML.AX` returns an empty `{}`); the interface lets us swap if a paid AV plan or another provider arrives later. All responses cached to disk on first call. See `DECISIONS.md` for the rationale.
4. **Answer assembly (US-03, US-05, US-06, FR-03/05/07).** A single `core.assistant.answer(question, history)` function. Calls Claude Sonnet via the Anthropic API with two tools exposed: `search_documents` and `get_price_history`. Sonnet decides which tool(s) to call; the function returns a structured `AnswerWithCitations`. This is the one and only reasoning entry point in the system.
5. **Reusable capability (US-07, FR-06).** A stdio MCP server built on the official MCP Python SDK, exposing one tool (`ask_oohmedia_investor_chat`) that imports and calls `core.assistant.answer()` directly. No reasoning logic lives in the MCP server itself — it is a thin adapter, which is what makes US-07 AC3 ("shared, not rebuilt") visibly true.

## Data flow

```
 ingest (one-off, idempotent)
   investor PDFs --> pdfplumber --> chunks+page metadata --> OpenAI embeddings --> ChromaDB

 query (per question)
   user --> Streamlit  \
                        >--> core.assistant.answer() --> Anthropic Sonnet (tool-use loop)
   Claude Desktop/MCP  /                                    |
                                                            |-- search_documents  --> ChromaDB --> cited chunks
                                                            |-- get_price_history --> PriceProvider --> cached OML data
                                                            v
                                                 AnswerWithCitations (text + sources[])
```

Both surfaces enter through the same `core.assistant.answer()` function. Neither surface talks to Anthropic, OpenAI, Chroma, or the market-data APIs directly.

## Locked stack (one-line rationale each)

| Layer | Choice | Rationale |
|---|---|---|
| Language / runtime | Python 3.11 + `uv` | Richest RAG ecosystem; `uv` gives sub-second env setup inside the 2h timebox. |
| PDF parsing | `pdfplumber` | Text-native oOh!media PDFs parse cleanly and pdfplumber gives page numbers for free, which US-03 AC4 needs. |
| Vector store | ChromaDB (persistent, local) | Single-directory embedded store, zero ops, satisfies "everything runs locally" (PRD non-goal on cloud). |
| Embeddings | OpenAI `text-embedding-3-small` | Cheap enough to re-embed the corpus freely; strong quality on financial prose. |
| Web UI | Streamlit | `st.chat_message` / `st.chat_input` / `st.write_stream` give US-01 in ~30 lines. |
| Second surface | Official MCP Python SDK (stdio) | Brief explicitly name-checks Claude Desktop (FR-06); MCP is the canonical fit. |
| Reasoning LLM | Anthropic Claude Sonnet (direct API, `ANTHROPIC_MODEL` env) | Native tool-use loop cleanly implements the US-05 router without a hand-rolled classifier. |
| Market data | Marketstack v2 (primary, HTTPS, `OML.AX`) + Alpha Vantage (secondary scaffold), both behind a `PriceProvider` interface | Marketstack free tier covers ASX on v2; AV free tier does not cover ASX. Interface lets us swap if that ever changes. See `DECISIONS.md`. |
| Orchestration | `orchestrate.py` driving `claude -p` headless, per-story prompt files, per-story logs | Directly satisfies the brief's "programmatically drives AI coding agents through the backlog". |

## Out of scope (explicit)

Quoted from the PRD "Non-goals" and the Candidate Brief "Constraints":

- "Production visual design or enterprise SSO integration."
- "Ingesting non-public or internal company data." / "No non-public company information."
- "Providing financial advice, forward-looking statements, or trading capability."
- "Cloud deployment. Everything runs locally for this release."
- ASX announcements page ingestion is deferred — "this page loads content dynamically" (Solution Design), and US-02 AC5 only requires two document **types** and two periods, which annual reports + investor presentations satisfy.
- Full corpus ingestion — "It does not need to ingest the entire archive" (Solution Design).
- Authentication, multi-user sessions, persistent chat history across restarts.
