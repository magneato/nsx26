"""Draw the project artwork from vector strokes (see vectrex.py). Run tools/make_demo.py first:
the box and the guesses on the card are the first box of docs/demo and unredact's real output for it.


    docs/img/social-preview.png   1280 x 640, for GitHub's social preview setting
    docs/img/hero.svg             the same scene for the web page
    docs/img/mark.svg, docs/favicon.svg   the small mark

    python tools/make_art.py

The guesses drawn under the box are labelled as guesses on purpose: that is the point.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
from vectrex import AMBER, CYAN, GREEN, MAGENTA, WHITE, Scene  # noqa: E402

from nsx26 import CODENAME, __version__  # noqa: E402

OUT = ROOT / "docs" / "img"


def real_box() -> dict:
    """The first box of the words demo and unredact's real guesses for it, right or wrong.
    (No choosing: the card shows what the tool did, not its best moment.)"""
    res = json.loads((ROOT / "docs" / "demo" / "words.guess.json").read_text(encoding="utf-8"))
    return res["boxes"][0]


def page(s: Scene, x: float, y: float, w: float, h: float, box_px: int) -> tuple:
    """A sheet of paper with a folded corner and lines of 'text', one word redacted."""
    f = 26
    s.line([(x, y), (x + w - f, y), (x + w, y + f), (x + w, y + h), (x, y + h), (x, y)], WHITE, 0.75, 2.0)
    s.line([(x + w - f, y), (x + w - f, y + f), (x + w, y + f)], WHITE, 0.5, 1.5)
    # words as short beam strokes; lengths are fixed so the art is the same every time
    rows = [[46, 22, 70, 30, 54], [30, 64, 26, 48, 40, 20], [58, 34, 0, 28, 44], [24, 50, 36, 62, 30],
            [40, 26, 54, 34, 48, 18], [62, 30, 44, 22]]
    lx, ly, gap = x + 26, y + 46, 9
    box = None
    for r, words in enumerate(rows):
        cx = lx
        for n, wl in enumerate(words):
            if wl == 0:                       # the redacted word
                bw = box_px * 2                # the diagram is drawn at twice the page's scale
                box = (cx, ly + r * 30 - 9, bw, 18)
                cx += bw + gap
                continue
            if cx + wl > x + w - 24:
                break
            s.line([(cx, ly + r * 30), (cx + wl, ly + r * 30)], WHITE, 0.55, 2.2)
            cx += wl + gap
    bx, by, bw, bh = box
    s.hatch(bx, by, bw, bh, step=3.0, color=AMBER, gain=0.55, width=1.4)
    s.rect(bx, by, bw, bh, AMBER, 1.0, 2.0)
    s.measure(bx, bx + bw, by + bh + 14, f"{box_px} PX", CYAN, size=10)
    return box


def scene(w: int = 1280, h: int = 640) -> Scene:
    s = Scene(w, h)
    # screen bezel: a vector display's frame, drawn once, faint
    s.rect(18, 18, w - 36, h - 36, WHITE, 0.18, 1.5)

    px, py, pw, ph = 86, 120, 420, 230
    rb = real_box()
    bx, by, bw, bh = page(s, px, py, pw, ph, rb["w"])
    # the black mirror: the box reflects what fits its width, ranked, never certain
    s.text(f"WHAT FITS {rb['w']} PX?", px, py + ph + 52, 14, GREEN, 0.95, 1.8)
    guesses = [(f"{i + 1}  {g['text'].upper()}", f"{g['p_model']:.2f}") for i, g in enumerate(rb["guesses"][:4])]
    for i, (g, p) in enumerate(guesses):
        yy = py + ph + 84 + i * 30
        fade = 1.0 - 0.18 * i
        s.text(g + "?", px, yy, 13, GREEN, fade, 1.6)
        s.text(p, px + 300, yy, 13, GREEN, fade * 0.8, 1.4, anchor="r")
    s.line([(bx + bw / 2, by + bh + 36), (bx + bw / 2, py + ph + 40)], GREEN, 0.35, 1.2)

    # title block
    tx = 600
    s.text("NSX26", tx, 118, 96, WHITE, 1.0, 4.2, spacing=1.05)
    s.line([(tx, 246), (tx + 592, 246)], CYAN, 0.6, 1.6)
    s.text(CODENAME, tx, 272, 34, MAGENTA, 1.0, 2.6)
    s.text("V" + __version__, tx + 592, 284, 18, MAGENTA, 0.8, 1.8, anchor="r")
    s.text("A BOX HIDES THE PIXELS.", tx, 360, 24, WHITE, 0.95, 2.2)
    s.text("NOT ITS WIDTH.", tx, 398, 24, AMBER, 1.0, 2.4)
    s.text("REDACT  ->  UNREDACT  ->  MEASURE", tx, 468, 15, CYAN, 0.85, 1.6)
    s.text("GUESSES, NOT RECOVERY. MEASURED ON", tx, 512, 13, WHITE, 0.6, 1.4)
    s.text("PROSE THE MODEL HAS NEVER SEEN.", tx, 536, 13, WHITE, 0.6, 1.4)
    s.text("GITHUB.COM/MAGNEATO/NSX26", w - 46, h - 52, 12, CYAN, 0.55, 1.3, anchor="r")
    return s


def mark(size: int = 64) -> Scene:
    """The small mark: a redaction bar with its width bracket, in a frame."""
    s = Scene(size, size)
    k = size / 64
    s.rect(4 * k, 4 * k, 56 * k, 56 * k, WHITE, 0.5, 2.5 * k)
    s.hatch(14 * k, 24 * k, 36 * k, 12 * k, step=3 * k, color=AMBER, gain=0.8, width=1.5 * k)
    s.rect(14 * k, 24 * k, 36 * k, 12 * k, AMBER, 1.0, 2.5 * k)
    s.line([(14 * k, 46 * k), (50 * k, 46 * k)], CYAN, 1.0, 2.5 * k)
    s.line([(14 * k, 42 * k), (14 * k, 50 * k)], CYAN, 1.0, 2.5 * k)
    s.line([(50 * k, 42 * k), (50 * k, 50 * k)], CYAN, 1.0, 2.5 * k)
    return s


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = scene()
    s.render().save(OUT / "social-preview.png", optimize=True)
    (OUT / "hero.svg").write_text(s.svg("nsx26 Black Mirror: a box hides the pixels, not its width"),
                                  encoding="utf-8")
    m = mark()
    (OUT / "mark.svg").write_text(m.svg("nsx26"), encoding="utf-8")
    (ROOT / "docs" / "favicon.svg").write_text(m.svg("nsx26"), encoding="utf-8")
    mark(256).render(ss=2).save(OUT / "mark-256.png", optimize=True)
    print("wrote", ", ".join(p.name for p in sorted(OUT.iterdir())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
