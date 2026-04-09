"""US-05 verification script.

Run with: uv run python tests/verify_us05.py
"""
import sys
from core.assistant import answer

VALID_DOC_TYPES = {"annual_report", "half_year_report", "investor_presentation"}


def check_combined():
    print("=== Test 1: Combined document + market data question ===")
    r = answer(
        "What did management say about revenue in the FY24 results, "
        "and how did the share price move in the following quarter?",
        [],
    )
    print(r.text)
    print("---")
    for i, c in enumerate(r.citations, 1):
        print(i, c.doc_type, c.doc_title or c.period, c.snippet[:80])

    has_doc = any(c.doc_type in VALID_DOC_TYPES for c in r.citations)
    has_market = any(c.doc_type == "market_data" for c in r.citations)
    print(f"\nHas doc citation: {has_doc}")
    print(f"Has market_data citation: {has_market}")

    if not has_doc:
        print("FAIL: no document citation found", file=sys.stderr)
        return False
    if not has_market:
        print("FAIL: no market_data citation found", file=sys.stderr)
        return False
    print("PASS: both citation types present")
    return True


def check_missing_market():
    print("\n=== Test 2: Market data out of range (future date) ===")
    r = answer(
        "What did management say about revenue in the FY24 results, "
        "and how did the share price move in Q1 2035?",
        [],
    )
    print(r.text)
    print("---")
    for i, c in enumerate(r.citations, 1):
        print(i, c.doc_type, c.doc_title or c.period, c.snippet[:80])

    has_doc = any(c.doc_type in VALID_DOC_TYPES for c in r.citations)
    has_market = any(c.doc_type == "market_data" for c in r.citations)
    text_lower = r.text.lower()
    mentions_missing = any(
        kw in text_lower
        for kw in ["not available", "unavailable", "no data", "no price", "could not", "missing", "out of range"]
    )

    print(f"\nHas doc citation: {has_doc}")
    print(f"Has market_data citation: {has_market}")
    print(f"Mentions missing data: {mentions_missing}")

    if has_market:
        print("FAIL: should not have market_data citation for future date", file=sys.stderr)
        return False
    print("PASS: correctly handles missing market data side")
    return True


if __name__ == "__main__":
    ok1 = check_combined()
    ok2 = check_missing_market()
    sys.exit(0 if (ok1 and ok2) else 1)
