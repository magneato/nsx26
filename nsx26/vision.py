"""Look at a page image: find the redaction boxes and read the words that are still visible.

* Solid boxes: connected dark regions that fill at least 90% of their bounding box.
* Noise boxes: regions where neighbouring pixels disagree both across and down, which
  random static does almost everywhere and printed text almost nowhere.
* Words: `tesseract`, run with every box painted white first, in reading order.

Every measurement is in whole pixels of the page as given; nothing is resampled.
"""
from __future__ import annotations

import csv
import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int
    fill: str = "solid"        # "solid" or "noise"

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h, "fill": self.fill}

    def iou(self, o: "Box") -> float:
        ix = max(0, min(self.x + self.w, o.x + o.w) - max(self.x, o.x))
        iy = max(0, min(self.y + self.h, o.y + o.h) - max(self.y, o.y))
        inter = ix * iy
        return inter / float(self.w * self.h + o.w * o.h - inter) if inter else 0.0


@dataclass
class Word:
    text: str
    x: int
    y: int
    w: int
    h: int
    conf: float
    line: tuple[int, int, int]
    order: int


def gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.int16)


def _components(mask: np.ndarray, min_run: int) -> list[list[int]]:
    """8-connected components of the horizontal runs in `mask` at least `min_run` long.
    Returns [x0, y0, x1, y1, pixel_count] per component (x1, y1 exclusive)."""
    parent: list[int] = []
    runs: list[tuple[int, int, int]] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    prev: list[int] = []
    padded = np.zeros((mask.shape[0], mask.shape[1] + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    edges = np.diff(padded, axis=1)
    for y in range(mask.shape[0]):
        starts = np.flatnonzero(edges[y] == 1)
        if not len(starts):
            prev = []
            continue
        ends = np.flatnonzero(edges[y] == -1)
        long = (ends - starts) >= min_run
        cur: list[int] = []
        j = 0
        for s, e in zip(starts[long].tolist(), ends[long].tolist()):
            idx = len(runs)
            runs.append((y, s, e))
            parent.append(idx)
            while j < len(prev) and runs[prev[j]][2] < s:
                j += 1
            k = j
            while k < len(prev) and runs[prev[k]][1] <= e:
                a, b = find(idx), find(prev[k])
                if a != b:
                    parent[max(a, b)] = min(a, b)
                k += 1
            cur.append(idx)
        prev = cur
    comp: dict[int, list[int]] = {}
    for i, (y, s, e) in enumerate(runs):
        c = comp.setdefault(find(i), [s, y, e, y + 1, 0])
        c[0], c[1], c[2], c[3] = min(c[0], s), min(c[1], y), max(c[2], e), max(c[3], y + 1)
        c[4] += e - s
    return list(comp.values())


def find_solid_boxes(img: Image.Image, dark: int = 80, min_fill: float = 0.90, min_h: int = 8,
                     min_w: int = 4, min_aspect: float = 0.2) -> list[Box]:
    """Solid dark rectangles, top to bottom, left to right. A box drawn against text touches the
    neighbouring letters, so each dark region is first trimmed back to the columns and rows that
    are almost entirely dark; whatever ink of a letter is attached is shaved off."""
    on = g = gray(img) < dark
    H = g.shape[0]
    out = []
    for x0, y0, x1, y1, _ in _components(on, min_w):
        for _ in range(3):
            sub = on[y0:y1, x0:x1]
            if sub.size == 0:
                break
            cols = np.flatnonzero(sub.mean(0) >= 0.9)
            if not len(cols):
                break
            x0, x1 = x0 + int(cols[0]), x0 + int(cols[-1]) + 1
            rows = np.flatnonzero(on[y0:y1, x0:x1].mean(1) >= 0.9)
            if not len(rows):
                break
            y0, y1 = y0 + int(rows[0]), y0 + int(rows[-1]) + 1
        w, h = x1 - x0, y1 - y0
        if (h >= min_h and w >= min_w and w >= min_aspect * h and h < 0.5 * H
                and on[y0:y1, x0:x1].mean() >= min_fill):
            out.append(Box(x0, y0, w, h, "solid"))
    return sorted(out, key=lambda b: (b.y + b.h // 2, b.x))


def _box_mean(a: np.ndarray, r: int) -> np.ndarray:
    """Mean over a (2r+1)^2 window, edges clamped, via an integral image."""
    p = np.pad(a.astype(np.float64), r + 1, mode="edge")
    s = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    H, W = a.shape
    tot = s[k:k + H, k:k + W] - s[:H, k:k + W] - s[k:k + H, :W] + s[:H, :W]
    return tot / (k * k)


def find_noise_boxes(img: Image.Image, jump: int = 40, busy_min: float = 0.42, mid_min: float = 0.50,
                     min_h: int = 8, min_w: int = 6) -> list[Box]:
    """Rectangles of random static. Two tests, both needed:

    * busy: a pixel differs by more than `jump` from both its right and its lower neighbour.
      Static is busy about half the time; the diagonal strokes of a "w" reach about 0.38.
    * mid-tone: a pixel is neither ink nor paper (48..207). Uniform static is about 62%
      mid-tone; anti-aliased text stays under about 0.47 even inside a glyph.

    Regions passing looser versions of both (9x9 averages) are found coarsely, each edge is
    moved to the last row/column that is still busy, overlapping pieces are merged, and the
    final box must pass both strict tests as a whole."""
    g = gray(img)
    busy = np.zeros(g.shape, dtype=bool)
    busy[:-1, :-1] = (np.abs(np.diff(g, axis=1))[:-1] > jump) & (np.abs(np.diff(g, axis=0))[:, :-1] > jump)
    mid = (g >= 48) & (g <= 207)
    dense = (_box_mean(busy, 4) > busy_min - 0.06) & (_box_mean(mid, 4) > mid_min - 0.05)
    pieces: list[list[int]] = []
    H, W = g.shape
    for x0, y0, x1, y1, _ in _components(dense, 3):
        X0, Y0, X1, Y1 = max(0, x0 - 6), max(0, y0 - 6), min(W, x1 + 6), min(H, y1 + 6)
        sub = busy[Y0:Y1, X0:X1]
        cols = np.flatnonzero(sub.mean(0) > 0.15)
        rows = np.flatnonzero(sub.mean(1) > 0.15)
        if not len(cols) or not len(rows):
            continue
        pieces.append([X0 + int(cols[0]), Y0 + int(rows[0]), X0 + int(cols[-1]) + 1, Y0 + int(rows[-1]) + 1])
    merged = True
    while merged:
        merged = False
        for i in range(len(pieces)):
            for j in range(i + 1, len(pieces)):
                a, b = pieces[i], pieces[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    pieces[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del pieces[j]
                    merged = True
                    break
            if merged:
                break
    out = []
    for x0, y0, x1, y1 in pieces:
        inside = (slice(y0, y1), slice(x0, x1))
        if (y1 - y0 >= min_h and x1 - x0 >= min_w and y1 - y0 < 0.5 * H
                and busy[inside].mean() > busy_min and mid[inside].mean() > mid_min):
            out.append(Box(x0, y0, x1 - x0, y1 - y0, "noise"))
    return sorted(out, key=lambda b: (b.y + b.h // 2, b.x))


def find_boxes(img: Image.Image) -> list[Box]:
    boxes = find_solid_boxes(img)
    for nb in find_noise_boxes(img):
        if not any(nb.iou(b) > 0.3 for b in boxes):
            boxes.append(nb)
    return sorted(boxes, key=lambda b: (b.y + b.h // 2, b.x))


def tesseract() -> str:
    """The tesseract program: $NSX26_TESSERACT, then PATH, then the usual Windows install folders."""
    import os
    for c in (os.environ.get("NSX26_TESSERACT"), shutil.which("tesseract"),
              r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if c and Path(c).is_file():
            return str(c)
    raise RuntimeError("tesseract is not installed (Ubuntu: ./setup.sh; Windows: .\\setup.ps1), "
                       "or set NSX26_TESSERACT to its path")


def read_words(img: Image.Image, boxes: list[Box], lang: str = "eng") -> list[Word]:
    """Visible words in reading order. Needs the `tesseract` program."""
    exe = tesseract()
    clean = img.convert("RGB")
    d = ImageDraw.Draw(clean)
    for b in boxes:
        d.rectangle([b.x - 1, b.y - 1, b.x + b.w, b.y + b.h], fill="white")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "page.png"
        clean.save(p)
        out = subprocess.run([exe, str(p), "-", "-l", lang, "--psm", "3", "--dpi", "150", "tsv"],
                             check=True, capture_output=True, text=True, encoding="utf-8").stdout
    words = []
    for r in csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE):
        if r.get("level") != "5" or not (r.get("text") or "").strip():
            continue
        words.append(Word(r["text"].strip(), int(r["left"]), int(r["top"]), int(r["width"]), int(r["height"]),
                          float(r["conf"]), (int(r["block_num"]), int(r["par_num"]), int(r["line_num"])),
                          len(words)))
    return words
