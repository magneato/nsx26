"""redact: cover text on a page image with flattened boxes.

    redact.sh page.png -o out.png --term "Irene Adler" --term Bohemia
    redact.sh page.png -o out.png --regex "[0-9]{3}-[0-9]{4}" --fill noise
    redact.sh page.png -o out.png --term Holmes --uniform 160      # every box the same width
    redact.sh sample page.png --book 1661 --seed 3                  # make a test page from the corpus

The output is a new RGB PNG built from the edited pixel array: no layers, no
alpha, no text chunks, nothing under the box. Two side files may be written:

* `OUT.json` (always): what anyone holding the redacted image can see anyway:
  box geometry, fill, the tool version. No redacted text, no hash of the original.
* `--key FILE` (only when asked): the redacted text and the original's hash. It is
  the answer key for `unredact.sh score`; keep it as private as the original.

A box hides pixels, not its own width. `unredact.sh evaluate` measures how much
that width gives away, and how much `--pad` and `--uniform` take back.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from . import __version__
from .text import WORD, key
from .vision import Box, Word, gray, read_words


@dataclass
class Region:
    """One thing to hide: the ink of some text, and the band of the line it sits on."""
    x: int
    y: int
    w: int
    h: int
    text: str = ""


def _letters(g: np.ndarray, word: Word) -> tuple[int, int] | None:
    """Left and right (exclusive) ink columns of the word's letters, leaving out the quotes and
    punctuation tesseract glued to it. Every letter and digit crosses the middle of the x-height
    band; commas, full stops, quotes and apostrophes at the ends do not. So the letters run from
    the first to the last column with ink in that middle band (only trimmed on a side where the
    text really has punctuation)."""
    m = WORD.search(word.text)
    if not m:
        return None
    lead, trail = m.start() > 0, m.end() < len(word.text)
    ink = g[word.y:word.y + word.h, word.x:word.x + word.w] < 200
    cols = np.flatnonzero(ink.any(0))
    if not len(cols):
        return None
    rows = ink.sum(1)
    core = np.flatnonzero(rows >= 0.5 * rows.max())          # the x-height band carries the most ink
    r0, r1 = int(core[0]), int(core[-1])
    mid = ink[r0 + (r1 - r0) * 3 // 10:r1 - (r1 - r0) * 3 // 10 + 1].any(0)
    through = np.flatnonzero(mid)
    if not len(through):
        return None
    x0 = int(through[0]) if lead else int(cols[0])
    x1 = int(through[-1]) + 1 if trail else int(cols[-1]) + 1
    return word.x + x0, word.x + x1


def _grow(g: np.ndarray, x0: int, x1: int, y0: int, y1: int, limit: int = 2) -> tuple[int, int]:
    """Widen by up to `limit` px a side while the next column still holds faint anti-aliased ink."""
    W = g.shape[1]
    for _ in range(limit):
        if x0 > 0 and (g[y0:y1, x0 - 1] < 250).any():
            x0 -= 1
    for _ in range(limit):
        if x1 < W and (g[y0:y1, x1] < 250).any():
            x1 += 1
    return x0, x1


def find_terms(img: Image.Image, terms: list[str], patterns: list[str]) -> tuple[list[Region], list[str]]:
    """Every occurrence of each term (a word or a run of words on one line, case-insensitive)
    and of each regex (matched against single visible words). Returns regions and the terms
    that were not found."""
    words = read_words(img, [])
    g = gray(img)
    lines: dict[tuple, list[Word]] = {}
    for w in words:
        lines.setdefault(w.line, []).append(w)
    band = {k: (min(w.y for w in ws) - 3, max(w.y + w.h for w in ws) + 3) for k, ws in lines.items()}
    found: list[Region] = []
    missing = []
    wanted = [[key(t) for t in WORD.findall(term)] for term in terms]
    for term, want in zip(terms, wanted):
        hits = 0
        for ln, ws in lines.items():
            keys = [key(m.group()) if (m := WORD.search(w.text)) else "" for w in ws]
            for i in range(len(ws) - len(want) + 1):
                if want and keys[i:i + len(want)] == want:
                    a, b = _letters(g, ws[i]), _letters(g, ws[i + len(want) - 1])
                    if a and b:
                        found.append(_region(g, a[0], b[1], band[ln], " ".join(w.text for w in ws[i:i + len(want)])))
                        hits += 1
        if not hits:
            missing.append(term)
    for pat in patterns:
        rx = re.compile(pat)
        hits = 0
        for ln, ws in lines.items():
            for w in ws:
                m = WORD.search(w.text)
                if m and rx.fullmatch(m.group()):
                    a = _letters(g, w)
                    if a:
                        found.append(_region(g, a[0], a[1], band[ln], w.text))
                        hits += 1
        if not hits:
            missing.append(f"/{pat}/")
    return found, missing


def _region(g: np.ndarray, x0: int, x1: int, band: tuple[int, int], text: str) -> Region:
    y0, y1 = max(0, band[0]), min(g.shape[0], band[1])
    x0, x1 = _grow(g, x0, x1, y0, y1)
    return Region(x0, y0, x1 - x0, y1 - y0, text)


def place(r: Region, page_w: int, pad: int = 0, uniform: int = 0) -> Box:
    """The box drawn for a region: the ink, plus `pad` px a side, or rounded up to a multiple of
    `uniform` px and centred on the ink. A box that would cross the page edge is slid back inside
    (never narrowed, so a uniform box stays uniform); only a box wider than the page is clipped."""
    x, w = int(r.x) - pad, int(r.w) + 2 * pad
    if uniform:
        w2 = uniform * max(1, math.ceil(w / uniform))
        x, w = x - (w2 - w) // 2, w2
    w = min(w, page_w)
    x = min(max(0, x), page_w - w)
    return Box(x, int(r.y), w, int(r.h))


def apply(img: Image.Image, boxes: list[Box], fill: str = "black",
          rng: np.random.Generator | None = None) -> Image.Image:
    """Flatten: a fresh RGB array, every box overwritten, then verified."""
    a = np.array(img.convert("RGB"), dtype=np.uint8)
    rng = rng or np.random.default_rng(secrets.randbits(128))
    painted = []
    for b in boxes:
        if fill == "noise":
            patch = rng.integers(0, 256, size=(b.h, b.w, 1), dtype=np.uint8).repeat(3, axis=2)
        else:
            patch = np.zeros((b.h, b.w, 3), dtype=np.uint8)
        a[b.y:b.y + b.h, b.x:b.x + b.w] = patch
        painted.append(patch)
    for b, patch in zip(boxes, painted):
        # boxes may overlap; whatever is in a box now must be fill written by this function
        region = a[b.y:b.y + b.h, b.x:b.x + b.w]
        if fill != "noise" and region.any():
            raise AssertionError(f"box {b.as_dict()} is not solid after flattening")
    out = Image.fromarray(a, "RGB")
    out.info.clear()
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def redact(src: Path, out: Path, regions: list[Region], fill: str = "black", pad: int = 0, uniform: int = 0,
           seed: int | None = None, key_path: Path | None = None, meta_path: Path | None = None,
           image: Image.Image | None = None) -> dict:
    img = image if image is not None else Image.open(src)
    img.load()
    boxes = [place(r, img.width, pad, uniform) for r in regions]
    for b in boxes:
        b.fill = "noise" if fill == "noise" else "solid"
    rng = np.random.default_rng(seed) if seed is not None else None
    flat = apply(img, boxes, fill, rng)
    out.parent.mkdir(parents=True, exist_ok=True)
    flat.save(out, format="PNG", optimize=False)
    check = Image.open(out)
    if check.mode != "RGB" or set(check.info) - {"dpi"}:
        raise AssertionError(f"{out}: expected a plain RGB PNG, got mode {check.mode} with {sorted(check.info)}")
    meta = {
        "tool": f"nsx26 redact {__version__}",
        "image": out.name,
        "sha256": sha256(out),
        "size": [flat.width, flat.height],
        "fill": fill,
        "pad_px": pad,
        "uniform_px": uniform,
        "boxes": [b.as_dict() for b in boxes],
    }
    mp = meta_path or out.with_suffix(".json")
    mp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    if key_path:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(json.dumps({
            "warning": "ANSWER KEY: contains the redacted text. Keep it as private as the original.",
            "original_sha256": sha256(src) if src and Path(src).is_file() else None,
            "redacted_sha256": meta["sha256"],
            "boxes": [{**b.as_dict(), "text": r.text, "ink": [r.x, r.y, r.w, r.h]} for b, r in zip(boxes, regions)],
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta


def parse_box(s: str) -> Region:
    text = ""
    if ":" in s:
        s, text = s.split(":", 1)
    x, y, w, h = (int(v) for v in s.split(","))
    return Region(x, y, w, h, text)


def make_sample(out: Path, book_id: int, seed: int, font: str, size: int, root: Path,
                names: Path | None = None) -> int:
    import random

    from .page import choose_paragraphs, clean_quotes, set_page
    from .fonts import require_font
    from .text import catalogue, paragraphs, prose, read_book

    books = {b.id: b for b in catalogue(root / "corpus" / "books.tsv")}
    if book_id not in books:
        print(f"book {book_id} is not in corpus/books.tsv", file=sys.stderr)
        return 2
    paras = [clean_quotes(p) for p in paragraphs(read_book(books[book_id], root / "data" / "corpus")) if prose(p)]
    chosen = choose_paragraphs(paras, random.Random(seed))
    mapping: dict[str, str] = {}
    if names:
        from .page import substitute_names
        pool = sorted({ln.split("#", 1)[0].strip() for ln in names.read_text(encoding="utf-8").splitlines()} - {""})
        chosen, mapping = substitute_names(chosen, pool, random.Random(seed))
    page = set_page(chosen, require_font(font), size)
    out.parent.mkdir(parents=True, exist_ok=True)
    page.image.save(out, format="PNG")
    layout = out.with_suffix(".layout.json")
    layout.write_text(json.dumps({"book": book_id, "seed": seed, "font": page.font, "size_px": size,
                                  "stand_ins": sorted(set(mapping.values()) & {t.text for t in page.tokens}),
                                  "words": [t.as_dict() for t in page.tokens]}, indent=1, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(f"{out}: {len(page.tokens)} words of {books[book_id].title} in {page.font} {size}px (layout: {layout})")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[1]
    if argv and argv[0] == "sample":
        ap = argparse.ArgumentParser(prog="redact.sh sample", description="set a corpus page as a test image")
        ap.add_argument("output", type=Path)
        ap.add_argument("--book", type=int, default=1661, help="Gutenberg id from corpus/books.tsv (default 1661)")
        ap.add_argument("--seed", type=int, default=1, help="which passage (default 1)")
        ap.add_argument("--font", default="LiberationSerif-Regular")
        ap.add_argument("--size", type=int, default=24, help="px per em (default 24)")
        ap.add_argument("--names", type=Path, default=None,
                        help="replace the passage's proper names with words from this list (e.g. corpus/names.txt)")
        a = ap.parse_args(argv[1:])
        return make_sample(a.output, a.book, a.seed, a.font, a.size, root, a.names)

    ap = argparse.ArgumentParser(prog="redact.sh", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--term", action="append", default=[], help="text to hide wherever it is visible (repeatable)")
    ap.add_argument("--regex", action="append", default=[], help="hide every word fully matching this (repeatable)")
    ap.add_argument("--box", action="append", default=[], help="X,Y,W,H[:text] to cover exactly (repeatable)")
    ap.add_argument("--fill", choices=["black", "noise"], default="black")
    ap.add_argument("--pad", type=int, default=0, help="widen every box by N px each side")
    ap.add_argument("--uniform", type=int, default=0, help="make every box a multiple of N px wide (the defence)")
    ap.add_argument("--seed", type=int, default=None, help="reproducible noise fill (default: fresh OS entropy)")
    ap.add_argument("--key", type=Path, default=None, help="also write the private answer key here")
    ap.add_argument("--json", type=Path, default=None, help="side file (default OUTPUT.json)")
    a = ap.parse_args(argv)
    if not a.input.is_file():
        print(f"{a.input}: no such file", file=sys.stderr)
        return 2
    if a.output.resolve() == a.input.resolve():
        print("refusing to overwrite the original: choose a different --output", file=sys.stderr)
        return 2
    regions = [parse_box(b) for b in a.box]
    missing: list[str] = []
    if a.term or a.regex:
        found, missing = find_terms(Image.open(a.input), a.term, a.regex)
        regions += found
    if not regions:
        print("nothing to redact: no --box given and no --term/--regex found on the page", file=sys.stderr)
        return 1
    meta = redact(a.input, a.output, regions, a.fill, a.pad, a.uniform, a.seed, a.key, a.json)
    print(f"{a.output}: {len(meta['boxes'])} box(es), fill {a.fill}, sha256 {meta['sha256'][:16]}")
    for m in missing:
        # stderr only: the side file must not name what was meant to be hidden
        print(f"not found on the page (nothing covered): {m}", file=sys.stderr)
    return 3 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
