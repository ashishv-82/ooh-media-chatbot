# CLAUDE.md — Rules for the coding agent

You are building the oOh!media Investor Chat described in `ARCHITECTURE.md`. Read `ARCHITECTURE.md` and the four `Candidate_0*.docx` files before writing code. These rules are non-negotiable.

## Locked stack (do not substitute)

- Python 3.11, managed with `uv`.
- `pdfplumber` for PDF parsing.
- `chromadb` persistent client for the vector store.
- OpenAI `text-embedding-3-small` for embeddings.
- `streamlit` for the web UI.
- Official `mcp` Python SDK (stdio transport) for the second surface.
- `anthropic` SDK, model from env var `ANTHROPIC_MODEL` (default `claude-sonnet-4-6`), for all reasoning.
- Marketstack (v2, HTTPS, symbol `OML.AX`) is the primary `PriceProvider` for OML; Alpha Vantage is kept behind the same interface as a scaffold but does not cover ASX on free tier. See `DECISIONS.md`.

Do not introduce LangChain, LlamaIndex, FAISS, sentence-transformers, FastAPI, or any other framework. If a requirement seems to need one, stop and ask.

## Virtual environment and dependencies

- The project uses `uv`. The venv lives at `.venv/` in the repo root.
- Before running any Python file, shell command, or test, ensure the venv is activated: `source .venv/bin/activate` (or prefix commands with `uv run`).
- Every Python dependency must be installed into the project venv via `uv add <pkg>` (runtime) or `uv add --dev <pkg>` (dev). Never `pip install` globally. Never install a package outside the venv.
- Pin versions in `pyproject.toml`. Do not rely on "latest".

## Folder layout

```
.
├── ARCHITECTURE.md
├── CLAUDE.md
├── DECISIONS.md
├── README.md
├── .env.example
├── pyproject.toml
├── orchestrate.py                # headless Claude Code driver
├── prompts/                      # one prompt file per user story
│   ├── US-01.md ... US-07.md
├── logs/                         # per-story run logs (gitignored)
├── data/
│   ├── pdfs/                     # downloaded oOh!media investor PDFs
│   ├── chroma/                   # persistent ChromaDB directory (gitignored)
│   └── cache/                    # market-data JSON cache (gitignored)
├── core/                         # the ONE reusable capability
│   ├── __init__.py
│   ├── assistant.py              # answer(question, history) -> AnswerWithCitations
│   ├── retrieval.py              # ChromaDB search wrapper
│   ├── embeddings.py             # ONLY module that imports openai
│   ├── llm.py                    # ONLY module that imports anthropic
│   ├── prices.py                 # PriceProvider + AlphaVantage/Marketstack impls
│   ├── ingest.py                 # pdfplumber -> chunks -> Chroma (idempotent)
│   └── schema.py                 # Citation, Chunk, AnswerWithCitations dataclasses
├── app.py                        # Streamlit UI; imports core.assistant only
├── mcp_server.py                 # MCP stdio server; imports core.assistant only
└── tests/
    ├── test_ingest.py
    ├── test_retrieval.py
    ├── test_prices.py
    └── test_assistant.py
```

Rules that follow from this layout:

- `app.py` and `mcp_server.py` must import **only** from `core`. They must not import `openai`, `anthropic`, `chromadb`, or any market-data SDK directly. This is what makes US-07 AC3 ("shared, not rebuilt") true.
- `openai` is imported only in `core/embeddings.py`. `anthropic` is imported only in `core/llm.py`. `chromadb` is imported only in `core/retrieval.py` and `core/ingest.py`.
- `core.assistant.answer()` is the single reasoning entry point for the whole system.

## Citation schema (must survive end-to-end)

Defined in `core/schema.py`. This schema is required by US-03 AC1/AC2/AC4 and US-05 AC2/AC3.

```python
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
    citations: list[Citation]  # ordered, matching the inline markers
```

Every field in `Citation` must be populated during ingestion (for documents) or during the price tool call (for market data) and must flow unchanged into the final `AnswerWithCitations`. The LLM is not allowed to invent, merge, or reword citation fields — it selects them from tool results only. Streamlit and the MCP server both render citations from this structure.

## Refusal rules (US-06, non-negotiable)

The assistant must:

1. **Never fabricate.** No made-up document content, share prices, dates, or citations. If `search_documents` returns nothing relevant, say so explicitly.
2. **Never imply access to non-public data.** No internal forecasts, board materials, unpublished guidance, or "I have heard that…".
3. **Never produce financial advice or forward guidance.** No buy/sell/hold, no price targets, no predictions. When asked, explain the boundary.
4. **Decline out-of-scope questions explicitly.** Say what is missing (e.g. "the FY23 annual report is not in the indexed corpus") rather than going silent or speculating.
5. **Partial answers are allowed** when one source is available and the other is not (US-05 AC4), but the missing side must be stated.

These rules live in the system prompt inside `core/llm.py` and are also enforced by returning empty tool results when no evidence is found — the model must handle empty results as a refusal trigger, not as license to guess.

## Framework gotchas the agent must handle

- **ChromaDB**: use `PersistentClient(path="data/chroma")`. Pin `chromadb` in `pyproject.toml` — minor versions have broken the client API before. Use a single named collection, e.g. `oohmedia_investor`.
- **pdfplumber**: always close the PDF (`with pdfplumber.open(...) as pdf`). Strip `None` from `page.extract_text()`. Record `page.page_number` (1-indexed) on every chunk.
- **Streamlit**: keep conversation state in `st.session_state.messages`. Stream responses with `st.write_stream`. Catch exceptions from `core.assistant.answer()` and render them inside `st.error(...)` — US-01 AC4 requires visible errors, not blank screens or hangs.
- **Anthropic tool-use**: implement the full tool-use loop (model returns `tool_use` → run tool → send `tool_result` → loop until `stop_reason == "end_turn"`). Do not stop after the first turn.
- **MCP Python SDK**: expose exactly one tool, `ask_oohmedia_investor_chat(question: str)`. The server must run on stdio and log to stderr only — stdout is reserved for the MCP protocol.
- **Marketstack (primary for OML)**: use the **v2** endpoint over **HTTPS** with symbol **`OML.AX`** — `https://api.marketstack.com/v2/eod?access_key=...&symbols=OML.AX`. Free tier supports HTTPS and ASX coverage on v2. (The Solution Design's `v1`/HTTP/`OML.XASX` guidance is stale; see `DECISIONS.md`.) Cache every response as JSON in `data/cache/` keyed by `{provider}_{symbol}_{function}_{params}.json`. Read from cache first, always.
- **Alpha Vantage (secondary, scaffold)**: free tier is 25 requests/day and **does not cover ASX listings** — `OML.AX` returns an empty `{}`. Implementation is kept behind the `PriceProvider` interface for extensibility, but Marketstack is the actual provider for OML. Same caching rules apply.
- **Secrets**: read from `os.environ`. Never hardcode keys. Maintain `.env.example` with `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `OPENAI_API_KEY`, `ALPHAVANTAGE_API_KEY`, `MARKETSTACK_API_KEY`.

## Commit message style

Conventional Commits, lowercase type, short imperative subject, no trailing period.

- `feat:` new user-visible capability (e.g. `feat: add streamlit chat ui for us-01`)
- `fix:` bug fix
- `docs:` documentation only
- `chore:` tooling, deps, config, gitignore
- `refactor:` code change that neither fixes a bug nor adds a feature
- `test:` adding or fixing tests
- `perf:` performance work

One commit per user story wherever practical; reference the story id in the body (e.g. `implements US-03`).

## Running tests

Tests live in `tests/` and use `pytest`.

```bash
source .venv/bin/activate    # or prefix with: uv run
uv run pytest -q             # run all tests
uv run pytest tests/test_retrieval.py -q   # run one file
```

Every user story should land with at least one test that exercises the happy path through `core/`. Tests must not hit the real Anthropic, OpenAI, Alpha Vantage, or Marketstack APIs — mock the clients or use recorded fixtures under `tests/fixtures/`.

## When in doubt

Stop and ask. Do not invent requirements, do not pick alternate libraries, and do not weaken the refusal rules to make a test pass.
