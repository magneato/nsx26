#!/usr/bin/env bash
# Cover text on a page image with flattened boxes. ./redact.sh --help
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PY="${HERE}/.venv/bin/python"; [[ -x "$PY" ]] || PY="$(command -v python3)"
PYTHONPATH="${HERE}${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m nsx26.redact "$@"
