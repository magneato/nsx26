#!/usr/bin/env bash
# Build the v0.1.0 release bundle in dist/: the source tree as tracked by git, plus the README.txt
# and preview picture that go on the GitHub release page. Nothing generated from the corpus is included.
#   ./release.sh            then: gh release create v0.1.0 dist/nsx26-0.1.0.tar.gz dist/nsx26-0.1.0.zip ...
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' nsx26/__init__.py)"
NAME="nsx26-${VERSION}"
rm -rf dist && mkdir -p dist
git diff --quiet HEAD -- || { echo "commit your changes first: the bundle is built from git" >&2; exit 1; }
git archive --format=tar.gz --prefix="${NAME}/" -o "dist/${NAME}.tar.gz" HEAD
git archive --format=zip --prefix="${NAME}/" -o "dist/${NAME}.zip" HEAD
cp docs/img/social-preview.png "dist/${NAME}-preview.png"
cat > dist/README.txt <<TXT
nsx26 ${VERSION} "Black Mirror"

redact.sh covers text on a page image with flattened boxes. unredact.sh ranks guesses for what each box
hides, from its width and the visible words around it. unredact.sh evaluate measures how often that works.

Ubuntu 24.04 / 26.04:  tar xzf ${NAME}.tar.gz && cd ${NAME} && ./setup.sh
Windows 11:            unzip ${NAME}.zip, then in PowerShell:  cd ${NAME}; .\\setup.ps1

Then: ./redact.sh --help, ./unredact.sh --help (Windows: .\\redact.cmd, .\\unredact.cmd).
Results, method and limits: README.md and https://magneato.github.io/nsx26/
MIT licence, (c) 2026 Neural Splines LLC.
TXT
(cd dist && sha256sum "${NAME}.tar.gz" "${NAME}.zip" "${NAME}-preview.png" README.txt > SHA256SUMS)
echo "release bundle in dist/:"; ls -1 dist
