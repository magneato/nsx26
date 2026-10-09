# Changelog

## v0.1.0 "Black Mirror" (2026-10-09)

First public release: two tools and the measurement that connects them.

* `redact.sh` / `redact.cmd`: cover terms (found by OCR, punctuation left visible), regexes or explicit boxes on a
  page image with flattened solid or static boxes; `--pad` and `--uniform` defences; a side file with nothing secret
  in it and an optional private answer key; `sample` sets a test page from the corpus, optionally with stand-in names.
* `unredact.sh` / `unredact.cmd`: pixel-exact box detection (solid and static), tesseract for the visible words,
  font and size by regression, width-and-context ranking with a trigram word model; `--names` / `--names-only` for an
  attacker with a list of candidates; `score` against an answer key; `evaluate` (held-out authors, ten conditions)
  and `evaluate --calibrate` (settings chosen on a held-out training book); `train`.
* Ubuntu 24.04 / 26.04 (`setup.sh`) and Windows 11 (`setup.ps1`, `.cmd` wrappers); CI on both;
  `tools/windows-check/` runs the Windows builds of Python and Tesseract under Wine.
* GitHub Pages site (Jekyll, `docs/`), vector artwork and social preview drawn by `tools/make_art.py`.
