"""Set prose on a page image and remember exactly where every word was drawn.

This is the test bench's ground truth: a page made here knows the ink box of each
word, so a redaction can be scored without trusting OCR on the original.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .fonts import Metrics, metrics
from .text import WORD, ends_sentence

PAGE_W, PAGE_H, MARGIN = 1275, 1650, 140        # US Letter at 150 dpi
PAPER, INK = (255, 255, 255), (20, 20, 20)


@dataclass
class Token:
    text: str
    line: int
    x: int              # ink box, page pixels, right/bottom exclusive
    y: int
    w: int
    h: int
    band: tuple[int, int]   # top and bottom of the line band: every box on a line gets this height
    starts_sentence: bool

    def as_dict(self) -> dict:
        return {"text": self.text, "line": self.line, "x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass
class Page:
    image: Image.Image
    tokens: list[Token]
    font: str
    size: int
    text: str


def set_page(paragraphs: list[str], font_file: Path, size: int, width: int = PAGE_W, height: int = PAGE_H,
             margin: int = MARGIN) -> Page:
    """Left-aligned, word-wrapped paragraphs until the page is full. Words are never split.

    Every glyph is placed where the font's own (unhinted) metrics put it, as PDF renderers do,
    and drawn on its own at that fractional position. Pillow's layout at the real size would round
    each advance to whole pixels when Raqm is missing (the Windows wheels), making the page depend
    on the platform; this way the geometry is the same everywhere."""
    font = ImageFont.truetype(str(font_file), size)
    ref = metrics(str(font_file)).font                    # the same 1000 px font unredact measures with
    k = size / Metrics.REF
    adv = lambda t: ref.getlength(t) * k                   # noqa: E731
    img = Image.new("RGB", (width, height), PAPER)
    d = ImageDraw.Draw(img)
    lead = round(size * 1.45)
    ascent = ref.getmetrics()[0] * k
    asc_top = ref.getbbox("\u00c0Hdlbk|", anchor="ls")[1] * k
    desc_bot = ref.getbbox("gjpqy|", anchor="ls")[3] * k
    y = margin
    tokens: list[Token] = []
    used: list[str] = []
    line_no = 0
    prev_end = True
    for para in paragraphs:
        lines: list[str] = []
        cur = ""
        for w in para.split():
            cand = f"{cur} {w}" if cur else w
            if cur and adv(cand) > width - 2 * margin:
                lines.append(cur)
                cur = w
            else:
                cur = cand
        if cur:
            lines.append(cur)
        if y + lead * min(len(lines), 2) > height - margin:
            break
        kept = []
        for line in lines:
            if y + lead > height - margin:
                break
            base = y + ascent
            for i, ch in enumerate(line):
                if not ch.isspace():
                    d.text((margin + adv(line[:i]), base), ch, font=font, fill=INK, anchor="ls")
            band = (math.floor(base + asc_top) - 2, math.ceil(base + desc_bot) + 2)
            for m in WORD.finditer(line):
                x = margin + adv(line[:m.start()])
                l, t, r, b = ref.getbbox(m.group(), anchor="ls")
                l, t = math.floor(x + l * k), math.floor(base + t * k)
                r, b = math.ceil(x + r * k), math.ceil(base + b * k)
                before = line[:m.start()].rstrip()
                starts = (ends_sentence(before.split()[-1]) if before.split() else prev_end)
                tokens.append(Token(m.group(), line_no, l, t, r - l, b - t, band, starts))
            if line.split():
                prev_end = ends_sentence(line.split()[-1])
            kept.append(line)
            y += lead
            line_no += 1
        used.append(" ".join(kept))
        y += lead // 2
        if len(kept) < len(lines):
            break
    return Page(img, tokens, font_file.stem, size, "\n\n".join(used))


def choose_paragraphs(paras: list[str], rng: random.Random, n: int = 12) -> list[str]:
    """A run of consecutive prose paragraphs from a random place in the book."""
    start = rng.randrange(max(1, len(paras) - n))
    return paras[start:start + n]


def clean_quotes(p: str) -> str:
    """Gutenberg's typography, minus characters that are not prose (asterisms, brackets of notes)."""
    p = re.sub(r"\[[^\]]*\]", "", p)
    return " ".join(p.split())


TITLES = {"I", "Mr", "Mrs", "Miss", "Dr", "Sir", "Lady", "Lord", "St", "Madam", "Captain", "Colonel", "God",
          "Monsieur", "Madame", "Professor", "Doctor", "Major", "General", "King", "Queen", "Prince", "OK"}


def substitute_names(paras: list[str], names: list[str], rng: random.Random) -> tuple[list[str], dict[str, str]]:
    """Replace the passage's proper names with stand-ins, consistently (each name always becomes the
    same stand-in). A proper name here is a capitalised word that is not the first word of a
    sentence, not a title, and never written in lower case anywhere in the passage."""
    text = " ".join(paras)
    lower = {w for w in WORD.findall(text) if w[:1].islower()}
    found: list[str] = []
    for p in paras:
        for m in WORD.finditer(p):
            w = m.group()
            before = p[:m.start()].rstrip().rstrip("\u201C\u2018\"'(\u2014-").rstrip()
            starts = not before or ends_sentence(before.split()[-1]) or p[:m.start()].rstrip().endswith("\u2014")
            if (w[:1].isupper() and not starts and w not in TITLES and w.lower() not in lower
                    and not w.isupper() and "'" not in w and "’" not in w and w not in found):
                found.append(w)
    pool = list(names)
    rng.shuffle(pool)
    mapping = {w: pool[i % len(pool)] for i, w in enumerate(found)}
    if not mapping:
        return paras, {}
    rx = re.compile(r"\b(" + "|".join(re.escape(w) for w in sorted(mapping, key=len, reverse=True)) + r")\b")
    return [rx.sub(lambda m: mapping[m.group()], p) for p in paras], mapping
