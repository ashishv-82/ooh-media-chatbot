# Implementation Plan

A phased, schedulable build plan for the oOh!media Investor Chat. This file is the single source of truth during the 2-hour build — every phase below can be dispatched by `orchestrate.py` or run manually, in order. Mark status inline as phases complete.

Total budget: **120 minutes**, with ~10 minutes of contingency at the end.

Build order after scaffolding follows dependency, not story number: **US-02 → US-03 → US-04 → US-05 → US-01 → US-06 → US-07**. Rationale: the knowledge layer must exist before citations; citations before market data; both tools before the combined showcase; backend before UI; refusals once the happy path is stable; MCP only after everything else works.

---

## Phase 1 · Scaffolding

- **Status:** ✅ done 2026-04-09 — layout per CLAUDE.md, uv venv on 3.11.15, `core.schema` populated with Chunk/Citation/AnswerWithCitations, `.env.example` has all 5 keys, import smoke test green
- **Test results:**

  | Check | Command | Result |
  |---|---|---|
  | Import smoke | `python -c "import core; import core.schema"` | ✅ exit 0 |
  | Bootstrap idempotency | `./scripts/bootstrap.sh` | ✅ green (uv install · `uv sync` · `.env` copy · Claude Code CLI check) |
- **Goal:** Repo structure, `uv` venv, empty module files, `.gitignore`, `.env.example`, `README.md` stub, and a `scripts/bootstrap.sh` that takes a fresh clone to a ready-to-run state in one command (installs `uv` if missing, runs `uv sync`, copies `.env.example` -> `.env` if missing, checks the Claude Code CLI is on PATH and instructs the user if not — never auto-installs the CLI). No feature code.
- **Dependencies:** none
- **Context files:** `CLAUDE.md` (folder layout section), `ARCHITECTURE.md`
- **Time budget:** 10 min
- **Acceptance criteria targeted:** none directly — this is enabling work
- **Verification:**
  ```bash
  tree -L 2 -I '.venv|__pycache__'
  source .venv/bin/activate && uv run python -c "import core; import core.schema"
  cat .env.example   # shows all five keys: ANTHROPIC_API_KEY, ANTHROPIC_MODEL, OPENAI_API_KEY, ALPHAVANTAGE_API_KEY, MARKETSTACK_API_KEY
  ./scripts/bootstrap.sh   # idempotent: green on uv, uv sync, .env, and Claude Code CLI check
  ```

---

## Phase 1.5 · Preflight

- **Status:** ✅ done 2026-04-09 — `scripts/preflight.py` validates venv, env vars, Anthropic ping, OpenAI embeddings, Marketstack v2/HTTPS/`OML.AX` (primary), Alpha Vantage (soft WARN — does not cover ASX free tier), ChromaDB persistent client, and PDFs in `data/pdfs/`. All green; AV WARN documented in DECISIONS.md. Marketstack v2 endpoint discovered to work over HTTPS with `OML.AX` — superseding the stale `v1`/HTTP/`OML.XASX` guidance from the Solution Design. CLAUDE.md, ARCHITECTURE.md, DECISIONS.md updated.
- **Test results:** `uv run python scripts/preflight.py` →

  | # | Check | Result |
  |---|---|---|
  | 1 | venv active | ✅ |
  | 2 | required env vars present | ✅ |
  | 3 | Anthropic API ping | ✅ |
  | 4 | OpenAI embeddings ping | ✅ |
  | 5 | Marketstack v2 / HTTPS / `OML.AX` | ✅ primary |
  | 6 | Alpha Vantage `OML.AX` | ⚠️ soft WARN — free tier returns `{}` for ASX (scaffold only) |
  | 7 | ChromaDB persistent client opens `data/chroma/` | ✅ |
  | 8 | PDFs present in `data/pdfs/` | ✅ |
- **Goal:** A `preflight.py` script that validates every external dependency before any feature code is written: venv active, required env vars present, Anthropic API reachable (tiny ping), OpenAI embeddings reachable (one short embedding), Alpha Vantage or Marketstack reachable (one cached call), Chroma persistent client can open `data/chroma/`.
- **Dependencies:** Phase 1
- **Context files:** `CLAUDE.md`, `.env.example`
- **Time budget:** 10 min
- **Acceptance criteria targeted:** none directly — this is a cost-saver that catches broken keys and quota issues before the agents start burning time
- **Verification:**
  ```bash
  source .venv/bin/activate
  uv run python preflight.py
  ```
  Expect a checklist output with a green ✓ (or red ✗ with a clear remediation) for each dependency. Non-zero exit on any failure.

---

## Phase 2 · Orchestration driver

- **Status:** ✅ done 2026-04-09 — `orchestrate.py` ships a hard-coded PHASES map (US-02..US-07 in dependency order), `--list` / `--phase` / `--all` / `--dry-run` flags, and shells out to `claude -p ... --output-format stream-json --verbose` with a per-run timestamped log under `logs/<phase>_<ts>.log`. `--list` and `--dry-run` verified; first real `--phase` invocation deferred to Phase 3. **Patched in Phase 5:** added `--permission-mode acceptEdits` to the headless invocation so Write/Edit calls don't deadlock waiting for human approval.
- **Test results:**

  | Check | Command | Result |
  |---|---|---|
  | List phases | `uv run python orchestrate.py --list` | ✅ all 7 phases shown in dependency order |
  | Dry-run a phase | `uv run python orchestrate.py --phase US-02 --dry-run` | ✅ resolved prompt + context list printed, no subprocess spawn |
  | Real headless run (deferred) | `uv run python orchestrate.py --phase US-04` | ✅ exercised end-to-end in Phase 5 — exit 0, stream-json captured to `logs/US-04_<ts>.log` |
- **Goal:** Build `orchestrate.py` as a first-class deliverable. It loads a phase definition (story id + prompt file + context files), shells out to `claude -p` headless with the prompt piped in, streams output to `logs/<phase>.log`, and returns a non-zero exit if the headless run fails. Supports `--phase US-02` to run a single phase and `--all` to run the full post-scaffold sequence.
- **Dependencies:** Phase 1.5
- **Context files:** `CLAUDE.md`, `ARCHITECTURE.md`, `backlog/US-*.md` (as inputs the driver routes)
- **Time budget:** 15 min
- **Acceptance criteria targeted:** none directly — this is the orchestration tooling the brief grades explicitly ("Your orchestration tooling is a deliverable alongside the product itself")
- **Verification:**
  ```bash
  source .venv/bin/activate
  uv run python orchestrate.py --phase US-02 --dry-run   # prints the resolved prompt and context file list without calling claude
  uv run python orchestrate.py --phase US-02             # runs for real, writes logs/US-02.log
  ```
  Confirm `logs/US-02.log` contains the full agent transcript and that re-running the same phase is safe (idempotent).

---

## Phase 3 · US-02 · Knowledge layer

- **Status:** ✅ done 2026-04-09 — 5 PDFs ingested (annual reports FY24/FY25, half-year reports HY24/HY25, FY25 full-year results presentation), 1209 chunks total in `oohmedia_investor` chroma collection. pdfplumber → page-aware sliding-window chunking (800/100, never crossing page boundaries) → OpenAI text-embedding-3-small → Chroma upsert with deterministic IDs `{source_id}:p{page}:c{idx}` for idempotency. Re-run produced 1209 → 1209 (no duplicates). Sample query "revenue and EBITDA in FY24" returned 5 highly relevant chunks across 4 docs with correct page numbers.
- **Test results:**

  | Check | Command | Result |
  |---|---|---|
  | Unit tests | `uv run pytest tests/test_ingest.py tests/test_retrieval.py -q` | ✅ **7 passed in 0.67s** (chunker boundaries, deterministic IDs, idempotent upsert, retrieval shape — mocked, no live OpenAI/Chroma) |
  | Live ingest | `python -m core.ingest data/pdfs` | ✅ 1209 chunks across 5 PDFs in `oohmedia_investor` collection |
  | Idempotency | re-run ingest | ✅ 1209 → 1209 (no duplicates) |
  | Retrieval smoke | "revenue and EBITDA in FY24" | ✅ 5 relevant chunks across 4 docs with correct page numbers |
- **Goal:** Download a justifiable set of oOh!media investor PDFs, implement `core/ingest.py` and `core/retrieval.py`, populate ChromaDB with page-level citation metadata. Write `data/pdfs/SOURCES.md`.
- **Dependencies:** Phase 2
- **Context files:** `backlog/US-02.md`, `CLAUDE.md`, `ARCHITECTURE.md`, `core/schema.py`
- **Time budget:** 15 min
- **Acceptance criteria targeted:** US-02 AC1–6
- **Verification:** see `backlog/US-02.md#verification`

---

## Phase 4 · US-03 · Grounded answers with citations

- **Status:** ✅ done 2026-04-09 — `core/llm.py` ships the Anthropic client, locked system prompt (refusal rules baked in), and `search_documents` tool schema; `core/assistant.py` runs the full tool-use loop with global citation numbering across multiple `search_documents` calls per turn, post-hoc `[N]` extraction with renumbering to a contiguous `[1]..[N]` sequence, and silent dropping of hallucinated markers. Empty retrieval surfaces a refusal trigger in the tool result so the model refuses with no citations.
- **Test results:** `uv run pytest tests/test_assistant.py -q` → **4 passed in 0.64s**

  | # | Test | Verifies | Result |
  |---|---|---|---|
  | 1 | `test_answer_returns_citations_for_supported_question` | happy path: one `tool_use` → one `end_turn` → 2 citations | ✅ |
  | 2 | `test_answer_refuses_when_retrieval_is_empty` | empty retrieval → refusal text + zero citations | ✅ |
  | 3 | `test_global_citation_numbering_across_two_searches` | global numbering across two `search_documents` calls in one turn | ✅ |
  | 4 | `test_invalid_marker_indices_are_dropped` | hallucinated marker `[99]` stripped from text and citations | ✅ |

  All four stub the Anthropic client and `core.retrieval` — no live API.

  | Check | Command | Result |
  |---|---|---|
  | Live smoke | "What did management say about revenue in the FY24 annual report, and what changed in FY25?" | ✅ multi-doc answer, 5 contiguous citations across FY24 AR, FY25 AR, FY25 results pres, HY25 HYR; markers `[1]..[5]` map 1-to-1 to citations list |
- **Goal:** Implement `core/llm.py` and `core/assistant.py` with the Anthropic tool-use loop and a `search_documents` tool. First end-to-end answer path.
- **Dependencies:** Phase 3
- **Context files:** `backlog/US-03.md`, `CLAUDE.md`, `core/schema.py`, `core/retrieval.py`
- **Time budget:** 15 min
- **Acceptance criteria targeted:** US-03 AC1–4
- **Verification:** see `backlog/US-03.md#verification`

---

## Phase 5 · US-04 · Market data

- **Status:** ✅ done 2026-04-09 — driven end-to-end via `orchestrate.py --phase US-04` (first real headless build phase). `core/prices.py` ships a `PriceProvider` ABC, `MarketstackProvider` (v2/HTTPS/`OML.AX`, primary), `AlphaVantageProvider` (scaffold — free tier doesn't cover ASX), deterministic disk cache under `data/cache/{provider}_{symbol}_{function}_{params}.json` (read-first, always), and a `get_provider()` factory. `core/llm.py` registers a second tool `get_price_history(start, end)` and the system prompt now instructs the model to call it for OML price questions, cite with `doc_type="market_data"`, and surface unavailability explicitly. `core/assistant.py` dispatches the new tool in the loop with global citation numbering shared across both tools. **`orchestrate.py` patched**: added `--permission-mode acceptEdits` to the `claude -p` invocation so headless writes don't deadlock on permission prompts. **`backlog/US-04.md` corrected**: Marketstack v2/HTTPS/`OML.AX` documented as primary, AV demoted to scaffold, stale `.docx` context references removed.
- **Test results:**

  | Suite | Command | Result |
  |---|---|---|
  | Prices unit tests | `uv run pytest tests/test_prices.py -q` | ✅ **11 passed in 0.07s** (cache hit/miss, factory selection, Marketstack parse, AV empty-on-ASX scaffold path, unavailable surfaces error — all stubbed, no live HTTP) |
  | Assistant unit tests | `uv run pytest tests/test_assistant.py -q` | ✅ **4 passed in 0.64s** (US-03 suite still green after the second-tool wiring) |
  | Full suite | `uv run pytest -q` | ✅ **22 passed in 0.69s** |

  | Check | Command | Result |
  |---|---|---|
  | Live smoke | "What was the OML closing price on 28 February 2025?" | ✅ **AUD $1.50 [1]**, `doc_type="market_data"`, `period="2025-02-28/2025-02-28"` |
  | Cache hit on re-run | mtime of `data/cache/marketstack_OML_AX_eod_2025-02-28_2025-02-28.json` | ✅ unchanged across two runs → zero API calls on re-run |
  | Headless orchestration | `uv run python orchestrate.py --phase US-04` | ✅ exit 0, full transcript in `logs/US-04_<ts>.log` (after `--permission-mode acceptEdits` patch) |
- **Goal:** Implement `core/prices.py` with `PriceProvider`, Alpha Vantage and Marketstack adapters, disk cache. Register a `get_price_history` tool in `core/assistant.py`.
- **Dependencies:** Phase 4
- **Context files:** `backlog/US-04.md`, `CLAUDE.md`, `core/assistant.py`
- **Time budget:** 15 min
- **Acceptance criteria targeted:** US-04 AC1–4
- **Verification:** see `backlog/US-04.md#verification`

---

## Phase 6 · US-05 · Combined document + market data

- **Status:** ✅ done 2026-04-09 — driven via `orchestrate.py --phase US-05`. No changes to `core/prices.py`, `core/retrieval.py`, or `core/assistant.py` (the tool-use loop already supports both tools and shares global citation numbering across them — this was the explicit DoD). System prompt in `core/llm.py` extended with three new instructions: (3) call BOTH tools for questions that span documents and market data and weave the evidence into one integrated answer with distinct inline markers, (8) when one source is missing, answer fully from the available source and explicitly state what's missing rather than refusing the whole question, and (9) the partial-answer rule. Two new tests added to `tests/test_assistant.py` covering the combined-tools happy path and the partial-answer-when-market-data-unavailable path. Helper script `scripts/verify_us05.py` (live API harness) added for end-to-end checks. **`backlog/US-05.md` corrected**: stale `.docx` context refs removed.
- **Test results:**

  | Suite | Command | Result |
  |---|---|---|
  | Assistant unit tests | `uv run pytest tests/test_assistant.py -q` | ✅ **6 passed in 1.01s** (4 prior US-03 tests + 2 new US-05 tests, all stubbed — no live API) |
  | Full suite | `uv run pytest -q` | ✅ **24 passed in 0.80s** |

  | # | New US-05 test | Verifies | Result |
  |---|---|---|---|
  | 1 | `test_combined_document_and_market_data_answer` | model calls both tools in one turn; both `annual_report` and `market_data` citations present; AC1–3, AC5 | ✅ |
  | 2 | `test_partial_answer_when_market_data_unavailable` | model still answers from documents when price tool returns empty; explicit "missing" mention; AC4 | ✅ |

  | Check | Command / Question | Result |
  |---|---|---|
  | Headless orchestration | `uv run python orchestrate.py --phase US-05` | ✅ exit 0 success, 30 turns, full transcript in `logs/US-05_<ts>.log` |
  | Live showcase (the brief's named scenario) | "What did management say about revenue in the FY24 results, and how did the share price move in the following quarter?" | ✅ one coherent multi-paragraph answer; **8 citations**: 6 document (FY24 AR ×3, FY25 AR ×1, HY24 HYR ×2) + **2 `market_data`** (Marketstack OML.AX, Feb–May 2025); reported AUD 1.575 → 1.680 (~13% rise) tied explicitly back to management's optimistic FY24 commentary |
  | AC4 partial answer (future date) | "What did management say about FY24 revenue, and what was the OML closing price on 14 February 2030?" | ✅ document side answered with 3 doc citations; market side explicitly refused with "Market data... is **not available**... I will not fabricate a figure"; zero `market_data` citations in the list |
- **Goal:** Validate and, if needed, refine the system prompt so the tool-use loop can call both tools in a single turn and produce one coherent answer. Minimal new code — this is mostly prompt work and tests.
- **Dependencies:** Phase 5
- **Context files:** `backlog/US-05.md`, `CLAUDE.md`, `core/assistant.py`, `core/llm.py`, `Candidate_01_Candidate_Brief.docx`
- **Time budget:** 10 min
- **Acceptance criteria targeted:** US-05 AC1–5
- **Verification:** see `backlog/US-05.md#verification`

---

## Phase 7 · US-01 · Streamlit chat interface

- **Status:** ☐ not started
- **Goal:** Build `app.py` on top of the working `core.assistant.answer()`. Session history, streaming, visible error handling, citation rendering.
- **Dependencies:** Phase 6
- **Context files:** `backlog/US-01.md`, `CLAUDE.md`, `core/schema.py`, `core/assistant.py`
- **Time budget:** 15 min
- **Acceptance criteria targeted:** US-01 AC1–5
- **Verification:** see `backlog/US-01.md#verification`

---

## Phase 8 · US-06 · Bounded behaviour

- **Status:** ☐ not started
- **Goal:** Harden the system prompt for the four refusal rules, ensure empty tool results produce empty-citation refusals, add `tests/test_assistant.py` covering the four refusal scenarios with a mocked Anthropic client.
- **Dependencies:** Phase 7
- **Context files:** `backlog/US-06.md`, `CLAUDE.md` (refusal rules), `core/llm.py`, `core/assistant.py`
- **Time budget:** 10 min
- **Acceptance criteria targeted:** US-06 AC1–5
- **Verification:** see `backlog/US-06.md#verification`

---

## Phase 9 · US-07 · MCP server (stretch)

- **Status:** ☐ not started
- **Goal:** Build `mcp_server.py` as a thin stdio MCP adapter over `core.assistant.answer()`. Document Claude Desktop setup in `README.md`.
- **Dependencies:** Phase 8
- **Context files:** `backlog/US-07.md`, `CLAUDE.md`, `core/assistant.py`, `core/schema.py`
- **Time budget:** 15 min
- **Acceptance criteria targeted:** US-07 AC1–5
- **Verification:** see `backlog/US-07.md#verification`

---

## Phase 10 · Polish and submission

- **Status:** ☐ not started
- **Goal:** Finalise `README.md` (run instructions, architecture summary, Claude Desktop snippet, citations for any scaffolds used per the brief's constraints). Confirm `.env.example` is complete. Review `DECISIONS.md`. Stop the screen recording.
- **Dependencies:** Phase 9 (or Phase 8 if US-07 was skipped)
- **Context files:** `README.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `CLAUDE.md`
- **Time budget:** 10 min
- **Acceptance criteria targeted:** submission requirements from `Candidate_01_Candidate_Brief.docx`
- **Verification:**
  ```bash
  source .venv/bin/activate
  uv run pytest -q
  streamlit run app.py   # smoke test one question from each of US-03, US-04, US-05
  ```
  Then: repo is committed, `.env` is gitignored, `.env.example` is present, recording is saved.
