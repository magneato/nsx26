# Runs inside the container with the repository at C:\nsx26 (copied, so the host tree is untouched).
set -u
mkdir -p /wine/drive_c/nsx26 && tar -C /src --exclude=./.venv --exclude=./data --exclude=./results/pages --exclude=./dist -cf - . | tar -C /wine/drive_c/nsx26 -xf -
cd /wine/drive_c/nsx26
step() { echo "=== $*"; "$@"; rc=$?; echo "=== rc=$rc"; [ $rc -eq 0 ] || exit $rc; }
PY='C:\nsx26\.venv\Scripts\python.exe'
step wine 'C:\Python312\python.exe' -c "import sys, os; print(sys.version, os.name, sys.stdout.encoding)"
step wine 'C:\Python312\python.exe' -m venv 'C:\nsx26\.venv'
step wine "$PY" -m pip install --quiet -r requirements.txt
step wine "$PY" tools\\fetch.py --fonts-only
step wine "$PY" -m unittest discover -s tests -v
step wine cmd /c 'C:\nsx26\unredact.cmd' train --corpus tests\\fixtures -o m.npz
step wine cmd /c 'C:\nsx26\redact.cmd' --help
echo WINDOWS-CHECK-OK
