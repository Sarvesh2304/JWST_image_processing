#!/bin/bash
# SessionStart hook for Claude Code cloud sessions (claude.ai/code, Claude app on iPad/phone/desktop).
# Creates a project virtualenv with the package and its test dependencies so the code, the audit
# checks and the test suite run immediately in a fresh cloud container. Idempotent and non-interactive.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
VENV="$CLAUDE_PROJECT_DIR/.venv"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --quiet --upgrade pip
# The package in editable mode, with developer tools (pytest, ruff) and the frozen legacy
# prototype's dependencies (needed by tests/science/test_legacy_defects.py).
"$VENV/bin/python" -m pip install --quiet -e ".[dev,legacy,imaging,archives]"

# Make the venv the default python for the rest of the session; use a headless matplotlib backend.
{
  echo "export VIRTUAL_ENV=\"$VENV\""
  echo "export PATH=\"$VENV/bin:\$PATH\""
  echo "export MPLBACKEND=Agg"
} >> "$CLAUDE_ENV_FILE"
