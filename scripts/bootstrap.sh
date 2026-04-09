#!/usr/bin/env bash
# bootstrap.sh — fresh clone to ready-to-run in one command.
#
#   ./scripts/bootstrap.sh
#
# - Installs uv if missing (via the official installer).
# - Runs `uv sync` to materialise the project venv from pyproject.toml / uv.lock.
# - Copies .env.example -> .env if .env is missing (does not overwrite).
# - Checks the Claude Code CLI is on PATH; if not, prints install instructions
#   but does NOT auto-install it (orchestrate.py needs it for headless runs).
#
# Safe to re-run.

set -euo pipefail

# Always operate from the repo root, regardless of where the script is invoked from.
cd "$(dirname "$0")/.."

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }

bold "==> oOh!media Investor Chat — bootstrap"

# 1. uv
if ! command -v uv >/dev/null 2>&1; then
  yellow "uv not found — installing via the official installer"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # The installer drops uv into ~/.local/bin or ~/.cargo/bin; make sure it's on PATH for this session.
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    red "uv install completed but 'uv' is still not on PATH. Open a new shell and re-run ./bootstrap.sh"
    exit 1
  fi
fi
green "uv: $(uv --version)"

# 2. uv sync — materialise the venv from pyproject.toml (and uv.lock if present)
bold "==> uv sync"
uv sync

# 3. .env
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    green ".env created from .env.example — fill in your API keys before running the app"
  else
    red ".env.example is missing; cannot create .env"
    exit 1
  fi
else
  green ".env already exists — leaving it untouched"
fi

# 4. Claude Code CLI (required by orchestrate.py for headless runs)
bold "==> Claude Code CLI"
if command -v claude >/dev/null 2>&1; then
  green "claude: $(claude --version 2>/dev/null || echo 'installed')"
else
  yellow "Claude Code CLI ('claude') is NOT installed."
  yellow "orchestrate.py drives 'claude -p' headless and will not work without it."
  echo
  echo "  Install instructions: https://docs.claude.com/en/docs/claude-code/setup"
  echo "  (npm: 'npm install -g @anthropic-ai/claude-code', or follow the docs for your platform)"
  echo
  yellow "Bootstrap will NOT auto-install the CLI. Install it manually, then re-run ./bootstrap.sh to verify."
fi

bold "==> Bootstrap complete"
echo "Next: edit .env to add your API keys, then run 'uv run python preflight.py' (after Phase 1.5)."
