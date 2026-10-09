#!/usr/bin/env bash
# Check the Windows code paths under Wine (needs docker; ~5 GB image, first build ~10 min).
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
docker build -t nsx26-windows-check "$HERE"
docker run --rm -v "$HERE/../..:/src:ro" -v "$HERE/steps.sh:/steps.sh:ro" nsx26-windows-check bash /steps.sh
