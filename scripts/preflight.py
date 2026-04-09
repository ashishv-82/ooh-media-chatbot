"""Preflight: validate every external dependency before any feature code runs.

Run from repo root:

    uv run python scripts/preflight.py

Each check prints PASS / FAIL / WARN with a clear remediation hint.
Exits non-zero on any FAIL. WARN does not affect exit code.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Always operate from the repo root, regardless of where the script is invoked.
REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)

# Load .env into os.environ so the rest of the script sees the keys.
try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except Exception:  # noqa: BLE001
    pass  # The env-vars check below will fail loudly if anything is missing.


# ---------- output helpers ----------

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"

_failures: list[str] = []
_warnings: list[str] = []


def _line(label: str, status: str, colour: str, detail: str = "") -> None:
    print(f"  [{colour}{status}{RESET}] {label}" + (f"  - {detail}" if detail else ""))


def passed(label: str, detail: str = "") -> None:
    _line(label, "PASS", GREEN, detail)


def failed(label: str, detail: str) -> None:
    _failures.append(label)
    _line(label, "FAIL", RED, detail)


def warned(label: str, detail: str) -> None:
    _warnings.append(label)
    _line(label, "WARN", YELLOW, detail)


def section(title: str) -> None:
    print(f"\n{BOLD}== {title}{RESET}")


# ---------- checks ----------

def check_venv() -> None:
    section("Virtual environment")
    in_venv = sys.prefix != sys.base_prefix
    expected = REPO_ROOT / ".venv"
    if not in_venv:
        warned(
            "running inside a venv",
            "not in a venv - prefer 'uv run python scripts/preflight.py' or 'source .venv/bin/activate'",
        )
        return
    try:
        if Path(sys.prefix).resolve() == expected.resolve():
            passed("project .venv active", str(expected))
        else:
            warned(
                "project .venv active",
                f"venv is {sys.prefix}, expected {expected}. uv run handles this automatically.",
            )
    except OSError as e:
        warned("project .venv active", str(e))


REQUIRED_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MARKETSTACK_API_KEY")


def check_env_vars() -> None:
    section("Environment variables")
    for key in REQUIRED_KEYS:
        if os.environ.get(key, "").strip():
            passed(key, "set")
        else:
            failed(key, f"missing - add it to .env in the repo root")
    model = os.environ.get("ANTHROPIC_MODEL", "").strip() or "claude-sonnet-4-6"
    passed("ANTHROPIC_MODEL", model)


def check_anthropic() -> None:
    section("Anthropic API")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        failed("anthropic ping", "ANTHROPIC_API_KEY not set; skipping")
        return
    model = os.environ.get("ANTHROPIC_MODEL", "").strip() or "claude-sonnet-4-6"
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=4,
            messages=[{"role": "user", "content": "ping"}],
        )
        if resp.content:
            passed("anthropic ping", f"{model} responded")
        else:
            failed("anthropic ping", "empty response from messages.create")
    except Exception as e:  # noqa: BLE001
        failed("anthropic ping", f"{type(e).__name__}: {e}")


def check_openai_embeddings() -> None:
    section("OpenAI embeddings")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        failed("openai embedding", "OPENAI_API_KEY not set; skipping")
        return
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        resp = client.embeddings.create(
            model="text-embedding-3-small",
            input="oohmedia preflight check",
        )
        vec = resp.data[0].embedding
        if len(vec) == 1536:
            passed("text-embedding-3-small", f"vector length {len(vec)}")
        else:
            failed("text-embedding-3-small", f"unexpected vector length {len(vec)}")
    except Exception as e:  # noqa: BLE001
        failed("text-embedding-3-small", f"{type(e).__name__}: {e}")


CACHE_DIR = REPO_ROOT / "data" / "cache"


def check_market_data() -> None:
    """Marketstack v2 over HTTPS with `OML.AX` is the primary (and only) provider for OML."""
    section("Market data")
    ms_key = os.environ.get("MARKETSTACK_API_KEY", "").strip()
    if not ms_key:
        failed("marketstack v2", "MARKETSTACK_API_KEY not set - add it to .env")
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    cache_path = CACHE_DIR / "preflight_marketstack_v2_OML.AX.json"
    if cache_path.exists():
        passed("marketstack v2 (cached)", str(cache_path.relative_to(REPO_ROOT)))
        return
    try:
        import httpx

        r = httpx.get(
            "https://api.marketstack.com/v2/eod",
            params={
                "access_key": ms_key,
                "symbols": "OML.AX",
                "limit": 1,
            },
            timeout=20.0,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("data"):
            cache_path.write_text(json.dumps(data))
            sample = data["data"][0]
            detail = (
                f"OML.AX close={sample.get('close')} on {sample.get('date','?')[:10]}, "
                f"cached to {cache_path.relative_to(REPO_ROOT)}"
            )
            passed("marketstack v2 live", detail)
        else:
            failed(
                "marketstack v2 live",
                f"no data in response: {json.dumps(data)[:200]}",
            )
    except Exception as e:  # noqa: BLE001
        failed("marketstack v2 live", f"{type(e).__name__}: {e}")


def check_chroma() -> None:
    section("ChromaDB")
    chroma_dir = REPO_ROOT / "data" / "chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(chroma_dir))
        name = "preflight_probe"
        try:
            client.delete_collection(name)
        except Exception:  # noqa: BLE001
            pass
        coll = client.create_collection(name)
        coll.add(ids=["probe-1"], documents=["hello"], metadatas=[{"k": "v"}])
        n = coll.count()
        client.delete_collection(name)
        if n == 1:
            passed("persistent client", str(chroma_dir.relative_to(REPO_ROOT)))
        else:
            failed("persistent client", f"unexpected count {n}")
    except Exception as e:  # noqa: BLE001
        failed("persistent client", f"{type(e).__name__}: {e}")


def check_pdfs() -> None:
    section("Investor PDFs")
    pdf_dir = REPO_ROOT / "data" / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(p for p in pdf_dir.glob("*.pdf"))
    if pdfs:
        passed("data/pdfs/", f"{len(pdfs)} file(s): " + ", ".join(p.name for p in pdfs))
        return
    warned(
        "data/pdfs/",
        (
            "no PDFs yet - fixed in Phase 3 (US-02). "
            "Download from https://investors.oohmedia.com.au/investor-centre/ "
            "at minimum two doc types across two periods (e.g. FY24 annual report + an investor presentation, "
            "and one more period). Save them under data/pdfs/ and add a SOURCES.md listing url, type, period."
        ),
    )


# ---------- main ----------

def main() -> int:
    print(f"{BOLD}oOh!media Investor Chat - preflight{RESET}")
    check_venv()
    check_env_vars()
    # Stop early if required env vars are missing - the API calls would just fail noisily.
    if _failures:
        print(f"\n{RED}{BOLD}preflight FAILED{RESET}: {len(_failures)} issue(s) - {', '.join(_failures)}")
        print("Fix the env-var issues above and re-run.")
        return 1
    check_anthropic()
    check_openai_embeddings()
    check_market_data()
    check_chroma()
    check_pdfs()

    print()
    if _failures:
        print(f"{RED}{BOLD}preflight FAILED{RESET}: {len(_failures)} issue(s) - {', '.join(_failures)}")
        if _warnings:
            print(f"{YELLOW}warnings:{RESET} {len(_warnings)} - {', '.join(_warnings)}")
        return 1
    if _warnings:
        print(f"{GREEN}{BOLD}preflight OK{RESET} with {len(_warnings)} warning(s) - {', '.join(_warnings)}")
    else:
        print(f"{GREEN}{BOLD}preflight OK{RESET} - all checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
