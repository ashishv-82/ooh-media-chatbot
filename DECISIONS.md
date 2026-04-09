# Decisions Log

A running log of technical and product decisions made during the build. Append new entries at the bottom. Do not rewrite history - if a decision is reversed, add a new entry that supersedes the old one and link back.

## Table of contents

- [Decision summary](#decision-summary)
- [D1 - ChromaDB as the vector store](#d1--chromadb-as-the-vector-store)
- [D2 - Marketstack v2 as the price provider](#d2--marketstack-v2-as-the-price-provider)

---

## Decision summary

| # | Date | Decision | Supersedes |
|---|---|---|---|
| D1 | 2026-04-09 | Use ChromaDB persistent client as the vector store | - |
| D2 | 2026-04-09 | Marketstack v2 / HTTPS / `OML.AX` as the primary PriceProvider | - |

---

## D1 - ChromaDB as the vector store

**Date:** 2026-04-09

**Decision:** Store document embeddings in a local ChromaDB persistent client at `data/chroma/`, single collection `oohmedia_investor`.

**Rationale:** Satisfies the PRD non-goal on cloud deployment ("Everything runs locally for this release") and US-02 AC6 ("Adding new documents in the future does not require rebuilding the system from scratch") with an idempotent re-ingest. Zero ops inside the 2h timebox.

**Alternatives considered:**

| Option | Why not |
|---|---|
| FAISS + pickle | More glue code for persistence and metadata |
| SQLite + sqlite-vec | More setup; overkill for a single-collection local store |
| BM25 only | Weaker on paraphrased investor questions |

---

## D2 - Marketstack v2 as the price provider

**Date:** 2026-04-09

**Decision:** Use Marketstack v2 (`https://api.marketstack.com/v2/eod`) with symbol `OML.AX` as the primary price provider for OML.

**Rationale:** The Solution Design's guidance (`v1` / HTTP / `OML.XASX`) is stale for the v2 endpoint. Verified empirically during Phase 1.5 preflight:

| Provider / Endpoint | Symbol | Result |
|---|---|---|
| Alpha Vantage free tier | `OML.AX` | `200 OK` with empty body `{}` - ASX not covered |
| Marketstack v1 / HTTP | `OML.AX` | `406 Not Acceptable` - plan-level block on free tier |
| Marketstack v1 / HTTP | `OML.XASX` | `406 Not Acceptable` - same block |
| **Marketstack v2 / HTTPS** | **`OML.AX`** | **200 OK** - real EOD data (close $0.97, 2,505 rows available) |

Quota header `x-quota-remaining: 9989/10000` confirmed the call counted normally on the free plan.

**Alternatives considered:**

| Option | Why not |
|---|---|
| yfinance | No API key needed and full ASX coverage, but a stack change CLAUDE.md says to stop and ask before making. Not needed once v2 was found |
| Twelve Data free tier | Another signup; Marketstack v2 already works |
| Alpha Vantage premium | Not appropriate for an assessment |
| Static CSV snapshot | Works for the showcase but not extensible |
