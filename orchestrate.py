"""Headless Claude Code driver for the build phases.

Runs a single phase (or all phases in order) by shelling out to `claude -p`
with the relevant prompt and context, streaming the JSON event log to both
stdout and a per-run timestamped file under `logs/`.

This is intentionally minimal — a phase map, a CLI, and a subprocess. It is
not a framework; it is a re-runnable script you can point a reviewer at.

Usage:
    uv run python orchestrate.py --list
    uv run python orchestrate.py --phase US-02 --dry-run
    uv run python orchestrate.py --phase US-02
    uv run python orchestrate.py --all
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
LOGS_DIR = REPO_ROOT / "logs"
BACKLOG_DIR = REPO_ROOT / "backlog"


@dataclass(frozen=True)
class Phase:
    id: str
    title: str
    prompt_file: Path
    context_files: tuple[str, ...]
    depends_on: tuple[str, ...] = field(default_factory=tuple)


# Build order is dependency-driven, not story-number-driven.
# US-02 -> US-03 -> US-04 -> US-05 -> US-01 -> US-06 -> US-07
PHASES: dict[str, Phase] = {
    "US-02": Phase(
        id="US-02",
        title="Knowledge layer (PDF ingest + ChromaDB)",
        prompt_file=BACKLOG_DIR / "US-02.md",
        context_files=("CLAUDE.md", "ARCHITECTURE.md", "core/schema.py"),
    ),
    "US-03": Phase(
        id="US-03",
        title="Grounded answers with citations",
        prompt_file=BACKLOG_DIR / "US-03.md",
        context_files=("CLAUDE.md", "core/schema.py", "core/retrieval.py"),
        depends_on=("US-02",),
    ),
    "US-04": Phase(
        id="US-04",
        title="Market data via Marketstack v2",
        prompt_file=BACKLOG_DIR / "US-04.md",
        context_files=("CLAUDE.md", "DECISIONS.md", "core/schema.py", "core/assistant.py"),
        depends_on=("US-03",),
    ),
    "US-05": Phase(
        id="US-05",
        title="Combined document + market data answers",
        prompt_file=BACKLOG_DIR / "US-05.md",
        context_files=("CLAUDE.md", "core/assistant.py", "core/llm.py"),
        depends_on=("US-04",),
    ),
    "US-01": Phase(
        id="US-01",
        title="Streamlit chat interface",
        prompt_file=BACKLOG_DIR / "US-01.md",
        context_files=("CLAUDE.md", "core/schema.py", "core/assistant.py"),
        depends_on=("US-05",),
    ),
    "US-06": Phase(
        id="US-06",
        title="Bounded behaviour and refusal rules",
        prompt_file=BACKLOG_DIR / "US-06.md",
        context_files=("CLAUDE.md", "core/assistant.py", "core/llm.py"),
        depends_on=("US-01",),
    ),
    "US-07": Phase(
        id="US-07",
        title="MCP server (stretch)",
        prompt_file=BACKLOG_DIR / "US-07.md",
        context_files=("CLAUDE.md", "core/assistant.py", "core/schema.py"),
        depends_on=("US-06",),
    ),
}

# The order --all walks the map.
ORDERED_PHASES: tuple[str, ...] = ("US-02", "US-03", "US-04", "US-05", "US-01", "US-06", "US-07")


# ---------- prompt assembly ----------

def build_prompt(phase: Phase) -> str:
    if not phase.prompt_file.exists():
        raise FileNotFoundError(f"prompt file missing: {phase.prompt_file}")
    backlog_body = phase.prompt_file.read_text(encoding="utf-8")
    ctx_lines = "\n".join(f"  - {p}" for p in phase.context_files)
    return f"""You are the coding agent for build phase {phase.id} ({phase.title}).

Follow every rule in CLAUDE.md without exception. Before writing any code,
read these files in order so you have the contract and the surrounding context:

{ctx_lines}
  - {phase.prompt_file.relative_to(REPO_ROOT)}

Then implement the user story below verbatim. Hit every acceptance criterion.
Run the verification block at the bottom of the story file before you stop.
If anything is genuinely underspecified, stop and ask one targeted question
rather than guessing.

============================================================
{backlog_body}
============================================================
"""


# ---------- subprocess driver ----------

def _check_claude_cli() -> None:
    if shutil.which("claude") is None:
        sys.exit(
            "error: 'claude' CLI not found on PATH. Install Claude Code "
            "(https://docs.claude.com/en/docs/claude-code/setup) and re-run."
        )


def run_phase(phase: Phase, *, dry_run: bool) -> int:
    prompt = build_prompt(phase)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOGS_DIR / f"{phase.id}_{timestamp}.log"

    print(f"\n=== {phase.id} · {phase.title} ===")
    print(f"prompt-file:   {phase.prompt_file.relative_to(REPO_ROOT)}")
    print(f"context-files: {', '.join(phase.context_files)}")
    print(f"log-file:      {log_path.relative_to(REPO_ROOT)}")

    if dry_run:
        print("\n--- resolved prompt (dry-run) ---")
        print(prompt)
        print("--- end prompt ---")
        return 0

    _check_claude_cli()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Header so the log is self-contained.
    log_path.write_text(
        f"# orchestrate.py — phase {phase.id}\n"
        f"# started: {dt.datetime.now().isoformat()}\n"
        f"# context_files: {list(phase.context_files)}\n"
        f"# prompt_file: {phase.prompt_file.relative_to(REPO_ROOT)}\n"
        f"\n# ----- prompt -----\n{prompt}\n# ----- claude stream-json output -----\n",
        encoding="utf-8",
    )

    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        # Headless runs have no human to approve Write/Edit prompts. acceptEdits
        # auto-approves file writes inside the repo while still gating shell.
        "--permission-mode",
        "acceptEdits",
    ]

    print(f"\nrunning: claude -p <prompt> --output-format stream-json --verbose")
    print("(streaming events; full transcript in the log file)\n")

    with log_path.open("a", encoding="utf-8") as log_fh:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(f"[{phase.id}] {line}")
            sys.stdout.flush()
            log_fh.write(line)
        rc = proc.wait()

    print(f"\n[{phase.id}] exit {rc} · log: {log_path.relative_to(REPO_ROOT)}")
    return rc


def run_all(*, dry_run: bool) -> int:
    for pid in ORDERED_PHASES:
        rc = run_phase(PHASES[pid], dry_run=dry_run)
        if rc != 0:
            print(f"\n{pid} failed (exit {rc}); stopping --all run.")
            return rc
    return 0


def list_phases() -> int:
    print("Build phases (dependency order):\n")
    for pid in ORDERED_PHASES:
        p = PHASES[pid]
        deps = ", ".join(p.depends_on) if p.depends_on else "—"
        print(f"  {p.id}  {p.title}")
        print(f"         prompt:  {p.prompt_file.relative_to(REPO_ROOT)}")
        print(f"         depends: {deps}")
    return 0


# ---------- cli ----------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Drive Claude Code headless through the build phases.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="list the phase map and exit")
    group.add_argument("--phase", choices=sorted(PHASES), help="run a single phase")
    group.add_argument("--all", action="store_true", help="run all phases in order, stop on first failure")
    parser.add_argument("--dry-run", action="store_true", help="print the resolved prompt without calling claude")
    args = parser.parse_args()

    if args.list:
        return list_phases()
    if args.phase:
        return run_phase(PHASES[args.phase], dry_run=args.dry_run)
    if args.all:
        return run_all(dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    sys.exit(main())
