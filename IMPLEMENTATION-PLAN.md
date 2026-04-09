# Implementation Plan

A phased, schedulable build plan for the oOh!media Investor Chat. This file is the single source of truth during the 2-hour build — every phase below can be dispatched by `orchestrate.py` or run manually, in order. Mark status inline as phases complete.

Total budget: **120 minutes**, with ~10 minutes of contingency at the end.

Build order after scaffolding follows dependency, not story number: **US-02 → US-03 → US-04 → US-05 → US-01 → US-06 → US-07**. Rationale: the knowledge layer must exist before citations; citations before market data; both tools before the combined showcase; backend before UI; refusals once the happy path is stable; MCP only after everything else works.

---

## Phase 1 · Scaffolding

- **Status:** ✅ done 2026-04-09 — layout per CLAUDE.md, uv venv on 3.11.15, `core.schema` populated with Chunk/Citation/AnswerWithCitations, `.env.example` has all 5 keys, import smoke test green
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

- **Status:** ✅ done 2026-04-09 — `orchestrate.py` ships a hard-coded PHASES map (US-02..US-07 in dependency order), `--list` / `--phase` / `--all` / `--dry-run` flags, and shells out to `claude -p ... --output-format stream-json --verbose` with a per-run timestamped log under `logs/<phase>_<ts>.log`. `--list` and `--dry-run` verified; first real `--phase` invocation deferred to Phase 3.
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

- **Status:** ✅ done 2026-04-09 — 5 PDFs ingested (annual reports FY24/FY25, half-year reports HY24/HY25, FY25 full-year results presentation), 1209 chunks total in `oohmedia_investor` chroma collection. pdfplumber → page-aware sliding-window chunking (800/100, never crossing page boundaries) → OpenAI text-embedding-3-small → Chroma upsert with deterministic IDs `{source_id}:p{page}:c{idx}` for idempotency. Re-run produced 1209 → 1209 (no duplicates). Sample query "revenue and EBITDA in FY24" returned 5 highly relevant chunks across 4 docs with correct page numbers. 7 unit tests pass (chunker + idempotency + retrieval-shape, all mocked, no live API).
- **Goal:** Download a justifiable set of oOh!media investor PDFs, implement `core/ingest.py` and `core/retrieval.py`, populate ChromaDB with page-level citation metadata. Write `data/pdfs/SOURCES.md`.
- **Dependencies:** Phase 2
- **Context files:** `backlog/US-02.md`, `CLAUDE.md`, `ARCHITECTURE.md`, `core/schema.py`
- **Time budget:** 15 min
- **Acceptance criteria targeted:** US-02 AC1–6
- **Verification:** see `backlog/US-02.md#verification`

---

## Phase 4 · US-03 · Grounded answers with citations

- **Status:** ☐ not started
- **Goal:** Implement `core/llm.py` and `core/assistant.py` with the Anthropic tool-use loop and a `search_documents` tool. First end-to-end answer path.
- **Dependencies:** Phase 3
- **Context files:** `backlog/US-03.md`, `CLAUDE.md`, `core/schema.py`, `core/retrieval.py`
- **Time budget:** 15 min
- **Acceptance criteria targeted:** US-03 AC1–4
- **Verification:** see `backlog/US-03.md#verification`

---

## Phase 5 · US-04 · Market data

- **Status:** ☐ not started
- **Goal:** Implement `core/prices.py` with `PriceProvider`, Alpha Vantage and Marketstack adapters, disk cache. Register a `get_price_history` tool in `core/assistant.py`.
- **Dependencies:** Phase 4
- **Context files:** `backlog/US-04.md`, `CLAUDE.md`, `core/assistant.py`
- **Time budget:** 15 min
- **Acceptance criteria targeted:** US-04 AC1–4
- **Verification:** see `backlog/US-04.md#verification`

---

## Phase 6 · US-05 · Combined document + market data

- **Status:** ☐ not started
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
