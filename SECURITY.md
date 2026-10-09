# Security and responsible use

`nsx26` never recovers hidden pixels: a flattened box has none. It ranks guesses from a box's width and the
visible words around it, and it measures how often that works. Its purpose is to let people check, before they
publish, whether their own redactions leak, and to show which defences work (`--uniform` does).

Use it on your own documents or on documents you are entitled to examine. Do not use it to try to reveal
information that others are legally or ethically entitled to keep private.

If you find a way in which `redact.sh` itself leaves recoverable information in its output (pixels, metadata,
side files), please open a private security advisory on GitHub rather than a public issue.
