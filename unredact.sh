#!/usr/bin/env bash
# Rank guesses for what each box on a redacted page image hides. ./unredact.sh --help
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PY="${HERE}/.venv/bin/python"; [[ -x "$PY" ]] || PY="$(command -v python3)"
PYTHONPATH="${HERE}${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m nsx26.unredact "$@"
