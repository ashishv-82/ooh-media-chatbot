# Decisions Log

A running log of technical and product decisions made during the build. Append new entries at the bottom. Do not rewrite history — if a decision is reversed, add a new entry that supersedes the old one and link back.

## Format

Each entry uses the following structure:

```
### YYYY-MM-DD — <short decision title>

- **Decision:** <one sentence stating what was decided>
- **Rationale:** <why; reference the candidate docs or user stories where relevant>
- **Alternatives considered:** <one line each>
- **Supersedes:** <link to prior entry, if any>
```

## Example entry

### 2026-04-09 — Use ChromaDB persistent client as the vector store

- **Decision:** Store document embeddings in a local ChromaDB persistent client at `data/chroma/`, single collection `oohmedia_investor`.
- **Rationale:** Satisfies the PRD non-goal on cloud deployment ("Everything runs locally for this release") and US-02 AC6 ("Adding new documents in the future does not require rebuilding the system from scratch") with an idempotent re-ingest. Zero ops inside the 2h timebox.
- **Alternatives considered:** FAISS + pickle (more glue code); SQLite + sqlite-vec (more setup); BM25 only (weaker on paraphrased investor questions).
- **Supersedes:** —

---

<!-- Append new decisions below this line -->

### 2026-04-09 — Marketstack v2 over HTTPS with `OML.AX` is the primary `PriceProvider`

- **Decision:** Use Marketstack v2 (`https://api.marketstack.com/v2/eod`) with the symbol `OML.AX` as the primary price provider for OML. Keep `AlphaVantageProvider` and `MarketstackProvider` (v1) classes as scaffolds behind the `PriceProvider` interface, but at runtime select Marketstack v2 first; Alpha Vantage is a soft secondary that we expect to fail for ASX symbols.
- **Rationale:** Verified empirically during Phase 1.5 preflight against the actual user keys:
  - **Alpha Vantage free tier does not cover ASX listings.** `function=TIME_SERIES_DAILY&symbol=OML.AX` returns `200 OK` with body `{}` (no `Note`, no `Information`). `AAPL` works fine on the same key — coverage is the issue, not the key.
  - **Marketstack v1 over HTTP rejects ASX symbols on free tier with `406 Not Acceptable`.** Both `OML.XASX` and `OML.AX` return 406; AAPL on v1 returns 200. The 406 is plan-level, not symbol-format.
  - **Marketstack v2 over HTTPS with `OML.AX` works on free tier.** Returned a real EOD row (close $0.97) with `total: 2505` historical rows available. Quota header `x-quota-remaining: 9989/10000` confirms the call counted normally and the plan permits it.
- **Implications for the docs the brief shipped:** The Solution Design's guidance that "Marketstack free tier is HTTPS-restricted" and that the symbol is `OML.XASX` is **stale for the v2 endpoint**. CLAUDE.md and ARCHITECTURE.md updated to reflect v2/HTTPS/`OML.AX`.
- **Alternatives considered:**
  - **yfinance** as a third provider — clean, no key, full ASX coverage, but a stack change CLAUDE.md says to stop and ask before making. Not needed once v2 was found.
  - **Twelve Data free tier** — another signup; v2 unblocks us without it.
  - **Pay for Alpha Vantage premium** — not appropriate for an assessment.
  - **Static CSV snapshot** — would have worked for the showcase but is not extensible.
- **Supersedes:** —

