"""Vector-display artwork: one set of polylines, rendered as a glowing PNG or as SVG.

A Vectrex draws with a beam, not pixels: lines are bright cores in a phosphor bloom,
the beam dwells (and glows hotter) where a stroke turns, and colour comes from a
plastic overlay laid over a white screen. This module does the same in numpy: draw
the cores, add three blurred copies, tone-map, then multiply by the overlay.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# Stroke font on a 4 x 6 grid (y down), advance 6. Angular, like the console's own lettering.
_O = [(1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)]
_P = [(0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)]
GLYPHS: dict[str, list[list[tuple[float, float]]]] = {
    "A": [[(0, 6), (0, 2), (2, 0), (4, 2), (4, 6)], [(0, 4), (4, 4)]],
    "B": [[(0, 3), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3), (0, 6), (3, 6), (4, 5), (4, 4), (3, 3)]],
    "C": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5)]],
    "D": [[(0, 0), (0, 6), (2, 6), (4, 4), (4, 2), (2, 0), (0, 0)]],
    "E": [[(4, 0), (0, 0), (0, 6), (4, 6)], [(0, 3), (3, 3)]],
    "F": [[(4, 0), (0, 0), (0, 6)], [(0, 3), (3, 3)]],
    "G": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5), (4, 3), (2, 3)]],
    "H": [[(0, 0), (0, 6)], [(4, 0), (4, 6)], [(0, 3), (4, 3)]],
    "I": [[(1, 0), (3, 0)], [(2, 0), (2, 6)], [(1, 6), (3, 6)]],
    "J": [[(4, 0), (4, 5), (3, 6), (1, 6), (0, 5)]],
    "K": [[(0, 0), (0, 6)], [(4, 0), (0, 3), (4, 6)]],
    "L": [[(0, 0), (0, 6), (4, 6)]],
    "M": [[(0, 6), (0, 0), (2, 3), (4, 0), (4, 6)]],
    "N": [[(0, 6), (0, 0), (4, 6), (4, 0)]],
    "O": [_O],
    "P": [_P],
    "Q": [_O, [(2, 4), (4, 6)]],
    "R": [_P, [(2, 3), (4, 6)]],
    "S": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 2), (1, 3), (3, 3), (4, 4), (4, 5), (3, 6), (1, 6), (0, 5)]],
    "T": [[(0, 0), (4, 0)], [(2, 0), (2, 6)]],
    "U": [[(0, 0), (0, 5), (1, 6), (3, 6), (4, 5), (4, 0)]],
    "V": [[(0, 0), (2, 6), (4, 0)]],
    "W": [[(0, 0), (1, 6), (2, 3), (3, 6), (4, 0)]],
    "X": [[(0, 0), (4, 6)], [(4, 0), (0, 6)]],
    "Y": [[(0, 0), (2, 3), (4, 0)], [(2, 3), (2, 6)]],
    "Z": [[(0, 0), (4, 0), (0, 6), (4, 6)]],
    "0": [_O, [(0, 5), (4, 1)]],
    "1": [[(1, 1), (2, 0), (2, 6)], [(1, 6), (3, 6)]],
    "2": [[(0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (0, 6), (4, 6)]],
    "3": [[(0, 0), (4, 0), (2, 2), (3, 2), (4, 3), (4, 5), (3, 6), (1, 6), (0, 5)]],
    "4": [[(3, 6), (3, 0), (0, 4), (4, 4)]],
    "5": [[(4, 0), (0, 0), (0, 3), (3, 3), (4, 4), (4, 5), (3, 6), (0, 6)]],
    "6": [[(3, 0), (1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (3, 3), (0, 3)]],
    "7": [[(0, 0), (4, 0), (1, 6)]],
    "8": [[(1, 3), (0, 2), (0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (3, 3), (1, 3), (0, 4), (0, 5), (1, 6), (3, 6),
           (4, 5), (4, 4), (3, 3)]],
    "9": [[(4, 3), (1, 3), (0, 2), (0, 1), (1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6)]],
    ".": [[(2, 5.6), (2, 6)]],
    ",": [[(2, 5.4), (1.4, 7)]],
    "-": [[(1, 3), (3, 3)]],
    ":": [[(2, 1.6), (2, 2.0)], [(2, 4.6), (2, 5.0)]],
    "/": [[(0, 6), (4, 0)]],
    "'": [[(2, 0), (2, 1.5)]],
    "(": [[(3, 0), (2, 1), (2, 5), (3, 6)]],
    ")": [[(1, 0), (2, 1), (2, 5), (1, 6)]],
    "?": [[(0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (2, 3.5), (2, 4.4)], [(2, 5.6), (2, 6)]],
    "!": [[(2, 0), (2, 4.2)], [(2, 5.6), (2, 6)]],
    "=": [[(0.5, 2), (3.5, 2)], [(0.5, 4), (3.5, 4)]],
    "<": [[(4, 0), (0, 3), (4, 6)]],
    ">": [[(0, 0), (4, 3), (0, 6)]],
    "|": [[(2, -1), (2, 7)]],
    "+": [[(2, 1), (2, 5)], [(0, 3), (4, 3)]],
    "%": [[(0, 6), (4, 0)], [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], [(3, 5), (4, 5), (4, 6), (3, 6), (3, 5)]],
    "#": [[(1, 0), (1, 6)], [(3, 0), (3, 6)], [(0, 2), (4, 2)], [(0, 4), (4, 4)]],
    " ": [],
}
ADVANCE = 6.0

# Colours: what the white phosphor looks like through each tint of the overlay.
WHITE = (0.92, 0.97, 1.0)
CYAN = (0.35, 0.95, 1.0)
GREEN = (0.45, 1.0, 0.70)
AMBER = (1.0, 0.72, 0.25)
MAGENTA = (1.0, 0.35, 0.80)


@dataclass
class Stroke:
    points: list[tuple[float, float]]
    color: tuple[float, float, float] = WHITE
    gain: float = 1.0
    width: float = 2.0


@dataclass
class Scene:
    w: int
    h: int
    strokes: list[Stroke] = field(default_factory=list)

    def line(self, pts, color=WHITE, gain=1.0, width=2.0):
        self.strokes.append(Stroke([(float(x), float(y)) for x, y in pts], color, gain, width))

    def text(self, s: str, x: float, y: float, size: float, color=WHITE, gain=1.0, width=2.0,
             anchor: str = "l", spacing: float = 1.0) -> float:
        """Draw `s` with cap height `size`. Returns the drawn width."""
        k = size / 6.0
        adv = ADVANCE * spacing
        total = (len(s) * adv - (adv - 4)) * k
        if anchor == "m":
            x -= total / 2
        elif anchor == "r":
            x -= total
        for i, ch in enumerate(s.upper()):
            for poly in GLYPHS.get(ch, GLYPHS["?"]):
                self.line([(x + (i * adv + px) * k, y + py * k) for px, py in poly], color, gain, width)
        return total

    def rect(self, x, y, w, h, color=WHITE, gain=1.0, width=2.0):
        self.line([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)], color, gain, width)

    def hatch(self, x, y, w, h, step=4.0, color=WHITE, gain=0.6, width=1.5):
        """A filled box the way a vector display fills: one beam sweep per scan line."""
        yy = y
        while yy <= y + h + 1e-6:
            self.line([(x, yy), (x + w, yy)], color, gain, width)
            yy += step

    def measure(self, x0, x1, y, label, color=CYAN, size=12.0, gain=0.9):
        """A dimension line |<-- label -->| between x0 and x1."""
        self.line([(x0, y - 8), (x0, y + 8)], color, gain, 1.5)
        self.line([(x1, y - 8), (x1, y + 8)], color, gain, 1.5)
        mid = (x0 + x1) / 2
        self.line([(x0, y), (x1, y)], color, gain, 1.5)
        a = min(7.0, (x1 - x0) / 4)
        self.line([(x0 + a, y - 4), (x0, y), (x0 + a, y + 4)], color, gain, 1.5)
        self.line([(x1 - a, y - 4), (x1, y), (x1 - a, y + 4)], color, gain, 1.5)
        self.text(label, mid, y + 10, size, color, gain, 1.5, anchor="m")

    # ---- raster ---------------------------------------------------------------------------
    def render(self, ss: int = 2, background=(4, 6, 10)) -> Image.Image:
        W, H = self.w * ss, self.h * ss
        acc = np.zeros((H, W, 3), dtype=np.float32)
        for st in self.strokes:
            layer = Image.new("L", (W, H), 0)
            d = ImageDraw.Draw(layer)
            pts = [(x * ss, y * ss) for x, y in st.points]
            d.line(pts, fill=255, width=max(1, round(st.width * ss)), joint="curve")
            r = st.width * ss * 0.65                    # beam dwell: hotter where the stroke starts, turns, ends
            for x, y in pts:
                d.ellipse([x - r, y - r, x + r, y + r], fill=255)
            a = np.asarray(layer, dtype=np.float32) / 255.0 * st.gain
            acc += a[..., None] * np.array(st.color, dtype=np.float32)
        core = Image.fromarray(np.clip(acc * 255 / max(1.0, acc.max()), 0, 255).astype(np.uint8), "RGB")
        scale = max(1.0, float(acc.max()))
        glow = np.zeros_like(acc)
        for radius, weight in ((2 * ss, 0.9), (7 * ss, 0.55), (22 * ss, 0.35)):
            b = np.asarray(core.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32) / 255.0 * scale
            glow += b * weight
        light = acc + glow
        light = 1.0 - np.exp(-1.6 * light)                # phosphor saturates to white-hot
        bg = np.array(background, dtype=np.float32) / 255.0
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        vign = 1.0 - 0.55 * (((xx / W - 0.5) ** 2 + (yy / H - 0.5) ** 2) / 0.5)
        out = bg * vign[..., None] + light
        img = Image.fromarray(np.clip(out * 255, 0, 255).astype(np.uint8), "RGB")
        return img.resize((self.w, self.h), Image.LANCZOS) if ss > 1 else img

    # ---- svg ------------------------------------------------------------------------------
    def svg(self, title: str = "", css_class: str = "vec") -> str:
        def hexc(c):
            return "#%02x%02x%02x" % tuple(int(255 * v) for v in c)
        paths = []
        for st in self.strokes:
            d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in st.points)
            paths.append(f'<path d="{d}" stroke="{hexc(st.color)}" stroke-opacity="{min(1.0, st.gain):.2f}" '
                         f'stroke-width="{st.width:.1f}"/>')
        t = f"<title>{title}</title>" if title else ""
        return (f'<svg class="{css_class}" viewBox="0 0 {self.w} {self.h}" xmlns="http://www.w3.org/2000/svg" '
                f'role="img"{" aria-label=" + repr(title) if title else ""}>{t}'
                '<defs><filter id="glow" x="-20%" y="-20%" width="140%" height="140%">'
                '<feGaussianBlur stdDeviation="1.6" result="a"/><feGaussianBlur stdDeviation="5" result="b"/>'
                '<feMerge><feMergeNode in="b"/><feMergeNode in="a"/><feMergeNode in="SourceGraphic"/></feMerge>'
                '</filter></defs>'
                '<g fill="none" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow)">'
                + "".join(paths) + "</g></svg>")
