#!/usr/bin/env bash
# One-time setup on Ubuntu (24.04, 26.04) or Debian: system packages, a Python venv,
# the reference corpus, the word model.
#   ./setup.sh            everything
#   ./setup.sh --no-apt   skip apt (install tesseract-ocr and python3-venv yourself)
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [[ "${1:-}" != "--no-apt" ]] && command -v apt-get >/dev/null; then
    need=()
    command -v tesseract >/dev/null || need+=(tesseract-ocr tesseract-ocr-eng)
    [[ -e /usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf ]] || need+=(fonts-liberation)
    [[ -e /usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf ]] || need+=(fonts-dejavu-core fonts-dejavu-extra)
    python3 -c "import ensurepip" >/dev/null 2>&1 || need+=(python3-venv)
    if ((${#need[@]})); then
        echo "installing: ${need[*]}"
        sudo apt-get update && sudo apt-get install -y "${need[@]}"
    fi
fi
command -v tesseract >/dev/null || { echo "tesseract is required: sudo apt-get install tesseract-ocr" >&2; exit 1; }

[[ -x .venv/bin/python ]] || python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
.venv/bin/python tools/fetch.py
[[ -s data/wordmodel.npz ]] || ./unredact.sh train
echo "ready: ./redact.sh --help   ./unredact.sh --help   ./unredact.sh evaluate"
