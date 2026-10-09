"""Fonts: find them, measure text in them, and work out which one a page was set in.

Widths are measured once at 1000 px and scaled linearly. FreeType at document
sizes agrees with that to about 0.1 px per word (checked in the tests), so one
table serves every size.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import ImageFont

FONT_DIRS = [Path(__file__).resolve().parents[1] / "data" / "fonts", Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
             Path.home() / ".local/share/fonts", Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"),
             Path("C:/Windows/Fonts"), Path.home() / "AppData/Local/Microsoft/Windows/Fonts"]
# Common document faces and their metric-compatible free twins
# (Liberation Serif = Times New Roman widths, Liberation Sans = Arial, Liberation Mono = Courier New).
CANDIDATES = ["LiberationSerif-Regular", "LiberationSans-Regular", "LiberationMono-Regular",
              "DejaVuSerif", "DejaVuSans", "DejaVuSansMono", "Times New Roman", "Arial", "Courier New",
              "FreeSerif", "FreeSans", "Georgia", "Verdana"]


@lru_cache(maxsize=None)
def font_path(name: str) -> Path | None:
    p = Path(name)
    if p.is_file():
        return p
    want = name.lower().replace(" ", "")
    for d in FONT_DIRS:
        if d.is_dir():
            for f in sorted(d.rglob("*")):
                if f.suffix.lower() in (".ttf", ".otf") and f.stem.lower().replace(" ", "") == want:
                    return f
    return None


def require_font(name: str) -> Path:
    p = font_path(name)
    if p is None:
        raise FileNotFoundError(f"font {name!r} is not installed (install fonts-liberation and fonts-dejavu-core)")
    return p


class Metrics:
    """Advance and ink widths of text in one font, at any size."""
    REF = 1000

    def __init__(self, path: Path):
        self.path = Path(path)
        self.name = self.path.stem
        self.font = ImageFont.truetype(str(path), self.REF)
        self.space = self.font.getlength(" ") / self.REF

    def advance(self, text: str, size: float) -> float:
        return self.font.getlength(text) * size / self.REF

    def ink(self, text: str, size: float) -> float:
        """Width from the first inked column to the last."""
        l, _, r, _ = self.font.getbbox(text)
        return (r - l) * size / self.REF

    def table(self, texts: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Per text, at size 1: advance, blank before the first ink, blank after the last ink."""
        adv = np.empty(len(texts))
        lb = np.empty(len(texts))
        rb = np.empty(len(texts))
        for i, t in enumerate(texts):
            a = self.font.getlength(t)
            l, _, r, _ = self.font.getbbox(t) if t else (0, 0, 0, 0)
            adv[i], lb[i], rb[i] = a, l, a - r
        return adv / self.REF, lb / self.REF, rb / self.REF


@lru_cache(maxsize=16)
def metrics(path: str) -> Metrics:
    return Metrics(Path(path))


@dataclass
class FontFit:
    path: str
    name: str
    size: float              # px per em
    offset: float            # measured OCR width minus predicted ink width, px (binarisation shaves the edges)
    residual: float          # median |measured - predicted| over the words used, px
    words_used: int
    ranking: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"font": self.name, "size_px": round(self.size, 3), "ocr_offset_px": round(self.offset, 3),
                "median_residual_px": round(self.residual, 3), "words_used": self.words_used,
                "ranking": self.ranking}


def _robust_line(u: np.ndarray, w: np.ndarray) -> tuple[float, float, np.ndarray]:
    """w = s*u + c, refit twice without the points more than 3 MADs off the line."""
    keep = np.ones(len(u), dtype=bool)
    s, c = 0.0, 0.0
    for _ in range(3):
        s, c = np.polyfit(u[keep], w[keep], 1)
        r = w - (s * u + c)
        mad = max(float(np.median(np.abs(r[keep]))), 0.25)
        keep = np.abs(r) <= 3 * mad
        if keep.sum() < 3:
            break
    return float(s), float(c), w - (s * u + c)


def fit_font(samples: list[tuple[str, float]], names: list[str] | None = None) -> FontFit:
    """Choose the font and size that best explain measured (text, ink width) pairs.

    For each installed candidate, fit width = size * ink_at_1px + offset; the font whose
    line leaves the smallest median residual wins.
    """
    if len(samples) < 5:
        raise RuntimeError("fewer than 5 readable words: the font cannot be measured (pass --font and --size)")
    w = np.array([s[1] for s in samples], dtype=np.float64)
    results = []
    for name in names or CANDIDATES:
        p = font_path(name)
        if p is None:
            continue
        m = metrics(str(p))
        u = np.array([m.ink(t, 1.0) for t, _ in samples])
        if np.ptp(u) <= 0:
            continue
        s, c, r = _robust_line(u, w)
        if s <= 0:
            continue
        results.append((float(np.median(np.abs(r))), m.name, str(p), s, c))
    if not results:
        raise RuntimeError("none of the candidate fonts is installed (install fonts-liberation and fonts-dejavu-core)")
    results.sort()
    res, name, path, s, c = results[0]
    return FontFit(path, name, s, c, res, len(samples),
                   [{"font": n, "size_px": round(sz, 2), "median_residual_px": round(rr, 3)}
                    for rr, n, _, sz, _ in results[:5]])
