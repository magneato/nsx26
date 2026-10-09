"""unredact: guess what each box on a redacted page image hides, and say how sure the model is.

    unredact.sh redacted.png                      # ranked guesses -> redacted.guess.json + .guess.png
    unredact.sh score redacted.guess.json key.json    # compare with redact.sh's answer key
    unredact.sh evaluate                          # the full measured benchmark (see README)
    unredact.sh train                             # rebuild the word model from the corpus

It sees only the image. It finds the boxes, reads the visible words with tesseract,
fits the font and size to those words, and ranks texts whose ink is as wide as each
box by how well they suit the words around it. These are guesses: many texts fit a
box, and the right one is often not first, or not in the vocabulary at all.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import CODENAME, __version__
from .fonts import FontFit, fit_font, font_path, metrics, require_font
from .guess import Guesser
from .model import WordModel
from .text import WORD, catalogue, ends_sentence, key, read_book, segments
from .vision import Box, Word, find_boxes, read_words

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "data" / "wordmodel.npz"

# Search settings. TOL and PAD_MAX were chosen on pages from the TRAINING books
# (`unredact.sh evaluate --calibrate`), never on the held-out test books.
TOL = 1.0
PAD_MAX = 2.0
SIGMA = 1.0
CONTEXT = 3


@dataclass
class Settings:
    tol: float = TOL
    pad_max: float = PAD_MAX
    sigma: float = SIGMA
    max_words: int = 2
    top: int = 10
    font: str | None = None
    size: float | None = None
    names: tuple[str, ...] = ()
    names_only: bool = False


_guessers: dict[tuple, Guesser] = {}


def guesser(model: WordModel, font: str, max_words: int, names: tuple[str, ...] = ()) -> Guesser:
    k = (id(model), font, max_words, names)
    if k not in _guessers:
        _guessers[k] = Guesser(model, metrics(font), max_words, names)
    return _guessers[k]


def read_names(path: Path | None) -> tuple[str, ...]:
    if not path:
        return ()
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return tuple(sorted({ln.split("#", 1)[0].strip() for ln in lines} - {""}))


def context(words: list[Word], boxes: list[Box]) -> list[tuple[list[str], list[str], bool]]:
    """For each box: up to CONTEXT visible words before and after it in reading order, and
    whether it starts a sentence. Context stops at another box."""
    by_line: dict[tuple, list[Word]] = {}
    for w in words:
        by_line.setdefault(w.line, []).append(w)
    seq: list[tuple[float, object]] = [(float(w.order), w) for w in words]
    for b in boxes:
        cy = b.y + b.h / 2
        line = [w for w in words if w.y <= cy <= w.y + w.h or b.y <= w.y + w.h / 2 <= b.y + b.h]
        after = [w for w in line if w.x >= b.x + b.w - 2]
        before = [w for w in line if w.x + w.w <= b.x + 2]
        if after:
            pos = min(w.order for w in after) - 0.5 + b.x / 1e7
        elif before:
            pos = max(w.order for w in before) + 0.5 + b.x / 1e7
        else:
            above = [w for w in words if w.y + w.h <= b.y]
            pos = (max(w.order for w in above) + 0.5 if above else -0.5) + b.x / 1e7
        seq.append((pos, b))
    seq.sort(key=lambda t: t[0])
    where = {id(item): i for i, (_, item) in enumerate(seq)}
    out = []
    for b in boxes:
        i = where[id(b)]
        left: list[str] = []
        j = i - 1
        prev_token = None
        while j >= 0 and isinstance(seq[j][1], Word) and len(left) < CONTEXT:
            tok = seq[j][1].text
            prev_token = prev_token or tok
            if left and ends_sentence(tok):
                break                       # the sentence before the box's sentence is not context
            left = WORD.findall(tok) + left
            j -= 1
        left = left[-CONTEXT:]
        starts = (prev_token is None and (j < 0)) or (prev_token is not None and ends_sentence(prev_token))
        right: list[str] = []
        j = i + 1
        while j < len(seq) and isinstance(seq[j][1], Word) and len(right) < CONTEXT:
            right += WORD.findall(seq[j][1].text)
            if ends_sentence(seq[j][1].text):
                break
            j += 1
        out.append((left if not starts else [], right[:CONTEXT], starts))
    return out


def measure_font(words: list[Word], st: Settings) -> FontFit:
    if st.font and st.size:
        p = require_font(st.font)
        return FontFit(str(p), p.stem, st.size, 0.0, 0.0, 0, [])
    samples = [(w.text, float(w.w)) for w in words
               if w.conf >= 80 and sum(c.isalpha() for c in w.text) >= 3]
    fit = fit_font(samples, [st.font] if st.font else None)
    if st.size:
        fit.size = st.size
    return fit


@dataclass
class Seen:
    """Everything read off the image; guessing needs nothing else."""
    size: tuple[int, int]
    boxes: list[Box]
    contexts: list[tuple[list[str], list[str], bool]]
    fit: FontFit | None


def look(img: Image.Image, st: Settings) -> Seen:
    boxes = find_boxes(img)
    if not boxes:
        return Seen(img.size, [], [], None)
    words = read_words(img, boxes)
    return Seen(img.size, boxes, context(words, boxes), measure_font(words, st))


def guesses(seen: Seen, model: WordModel, st: Settings, use_context: bool = True) -> dict:
    result: dict = {"tool": f"nsx26 unredact {__version__}", "codename": CODENAME,
                    "size": list(seen.size), "font": seen.fit.as_dict() if seen.fit else None, "boxes": [],
                    "note": "Ranked GUESSES. A box keeps its width, not its text; the right answer may be "
                            "ranked low or be missing from the vocabulary."}
    if not seen.boxes:
        return result
    g = guesser(model, seen.fit.path, st.max_words, st.names)
    for b, (left, right, starts) in zip(seen.boxes, seen.contexts):
        if not use_context:
            left, right = [], []
        cands, n_fit = g.guess(left, right, float(b.w), seen.fit.size, starts, st.tol, st.pad_max, st.sigma, st.top,
                            only_names=st.names_only and bool(st.names))
        result["boxes"].append({**b.as_dict(), "left": left, "right": right, "starts_sentence": starts,
                                "texts_that_fit": n_fit, "guesses": [c.as_dict() for c in cands]})
    return result


def analyse(img: Image.Image, model: WordModel, st: Settings) -> dict:
    t0 = time.perf_counter()
    result = guesses(look(img, st), model, st)
    result["seconds"] = round(time.perf_counter() - t0, 3)
    return result


# ---- the picture ----------------------------------------------------------------------------
PHOSPHOR = (120, 255, 190)
DIM = (60, 150, 110)


def annotate(img: Image.Image, result: dict) -> Image.Image:
    """The redacted page with each box as a black mirror: the top guess glows inside it,
    marked with its rank and the model's belief. Nothing is painted back as if recovered."""
    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out)
    fp = font_path("DejaVuSansMono") or font_path("LiberationMono-Regular")
    for i, b in enumerate(result["boxes"], 1):
        x, y, w, h = b["x"], b["y"], b["w"], b["h"]
        d.rectangle([x - 2, y - 2, x + w + 1, y + h + 1], outline=PHOSPHOR, width=1)
        if b["fill"] == "noise":
            d.rectangle([x, y, x + w - 1, y + h - 1], fill=(0, 0, 0))
        if b["guesses"]:
            gtext, p = b["guesses"][0]["text"], b["guesses"][0]["p_model"]
            size = max(8, int(h * 0.6))
            f = ImageFont.truetype(str(fp), size) if fp else ImageFont.load_default()
            while f.getlength(gtext + "?") > w - 2 and size > 7:
                size -= 1
                f = ImageFont.truetype(str(fp), size) if fp else f
            d.text((x + w / 2, y + h / 2), gtext + "?", fill=PHOSPHOR, font=f, anchor="mm")
            tag = f"#{i} p={p:.2f}"
        else:
            tag = f"#{i} no fit"
        tf = ImageFont.truetype(str(fp), 11) if fp else ImageFont.load_default()
        d.text((x, max(0, y - 14)), tag, fill=DIM, font=tf)
    bar = ImageFont.truetype(str(fp), 14) if fp else ImageFont.load_default()
    d.rectangle([0, out.height - 26, out.width, out.height], fill=(0, 0, 0))
    d.text((12, out.height - 20), f"nsx26 unredact {__version__} - ranked guesses, not recovered text",
           fill=PHOSPHOR, font=bar)
    return out


# ---- scoring --------------------------------------------------------------------------------
def norm(text: str) -> str:
    return " ".join(key(w) for w in WORD.findall(text))


def score(result: dict, answer: dict, iou: float = 0.5) -> dict:
    """Match found boxes to the key's boxes (IoU >= 0.5) and check the guesses against the text."""
    found = [Box(b["x"], b["y"], b["w"], b["h"]) for b in result["boxes"]]
    used: set[int] = set()
    rows = []
    for k in answer["boxes"]:
        kb = Box(k["x"], k["y"], k["w"], k["h"])
        best, bi = 0.0, -1
        for i, f in enumerate(found):
            v = kb.iou(f)
            if i not in used and v > best:
                best, bi = v, i
        row = {"text": k["text"], "found": best >= iou, "rank": None, "p_top": None, "texts_that_fit": None}
        if best >= iou:
            used.add(bi)
            g = result["boxes"][bi]["guesses"]
            row["texts_that_fit"] = result["boxes"][bi]["texts_that_fit"]
            ranks = [r for r, c in enumerate(g, 1) if norm(c["text"]) == norm(k["text"])]
            row["rank"] = ranks[0] if ranks else None
            row["p_top"] = g[0]["p_model"] if g else None
        rows.append(row)
    n = len(rows)
    return {"boxes": n, "found": sum(r["found"] for r in rows),
            "top1": sum(r["rank"] == 1 for r in rows), "top5": sum(bool(r["rank"]) and r["rank"] <= 5 for r in rows),
            "false_boxes": len(found) - len(used), "rows": rows}


# ---- commands -------------------------------------------------------------------------------
def train(out: Path, corpus: list[Path], max_vocab: int) -> int:
    t0 = time.perf_counter()
    if corpus:
        from .text import read_folder
        segs = read_folder(corpus)
        source = "folders: " + ", ".join(str(p) for p in corpus)
    else:
        books = [b for b in catalogue(ROOT / "corpus" / "books.tsv") if b.split == "train"]
        segs = []
        for b in books:
            segs += segments(read_book(b, ROOT / "data" / "corpus"))
        source = "corpus/books.tsv train split: " + ", ".join(str(b.id) for b in books)
    model = WordModel.train(segs, max_vocab=max_vocab, source=source)
    model.save(out)
    print(f"{out}: {model.n_words:,} words in {model.n_sentences:,} sentences, vocabulary {model.V - 2:,}, "
          f"{len(model.t_keys):,} trigrams ({time.perf_counter() - t0:.1f}s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "evaluate":
        from .bench import main as bench_main
        return bench_main(argv[1:])
    if argv and argv[0] == "train":
        ap = argparse.ArgumentParser(prog="unredact.sh train")
        ap.add_argument("-o", "--output", type=Path, default=DEFAULT_MODEL)
        ap.add_argument("--corpus", type=Path, nargs="*", default=[], help="text files/folders instead of the books")
        ap.add_argument("--max-vocab", type=int, default=100_000)
        a = ap.parse_args(argv[1:])
        return train(a.output, a.corpus, a.max_vocab)
    if argv and argv[0] == "score":
        ap = argparse.ArgumentParser(prog="unredact.sh score")
        ap.add_argument("result", type=Path)
        ap.add_argument("key", type=Path)
        a = ap.parse_args(argv[1:])
        s = score(json.loads(a.result.read_text(encoding="utf-8")), json.loads(a.key.read_text(encoding="utf-8")))
        for r in s["rows"]:
            print(f"  {'found' if r['found'] else 'MISSED':6} rank {r['rank'] or '-':>2}  {r['text']}")
        print(f"{s['boxes']} boxes: {s['found']} found, first guess right {s['top1']}, "
              f"in top five {s['top5']}, {s['false_boxes']} false box(es)")
        return 0

    ap = argparse.ArgumentParser(prog="unredact.sh", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--json", type=Path, default=None, help="default IMAGE.guess.json")
    ap.add_argument("-o", "--output", type=Path, default=None, help="annotated image, default IMAGE.guess.png")
    ap.add_argument("--font", default=None, help="skip font detection: font name or file")
    ap.add_argument("--size", type=float, default=None, help="skip size detection: px per em")
    ap.add_argument("--words", type=int, default=2, help="most words one box may hide (default 2)")
    ap.add_argument("--pad-max", type=float, default=PAD_MAX, help=f"boxes may be up to this many px wider "
                    f"than the ink on each side (default {PAD_MAX})")
    ap.add_argument("--tol", type=float, default=TOL, help=f"width tolerance px (default {TOL})")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--names", type=Path, default=None,
                    help="extra candidates, one per line (e.g. a list of suspects; see corpus/names.txt)")
    ap.add_argument("--names-only", action="store_true",
                    help="every box holds one of --names: rank only those (by width, then context)")
    a = ap.parse_args(argv)
    if not a.image.is_file():
        print(f"{a.image}: no such file", file=sys.stderr)
        return 2
    model = WordModel.load(a.model)
    img = Image.open(a.image)
    st = Settings(a.tol, a.pad_max, SIGMA, a.words, a.top, a.font, a.size, read_names(a.names), a.names_only)
    res = analyse(img, model, st)
    res["image"] = a.image.name
    res["model"] = {"file": a.model.name, "sha256": WordModel.digest(a.model), "source": model.source}
    stem = a.image.with_suffix("")
    jp = a.json or Path(f"{stem}.guess.json")
    op = a.output or Path(f"{stem}.guess.png")
    jp.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    annotate(img, res).save(op)
    if res["font"]:
        f = res["font"]
        print(f"font {f['font']} {f['size_px']:.2f}px (median residual {f['median_residual_px']:.2f}px "
              f"over {f['words_used']} words)")
    for i, b in enumerate(res["boxes"], 1):
        g = ", ".join(f"{c['text']} ({c['p_model']:.2f})" for c in b["guesses"][:5]) or "nothing fits"
        print(f"  #{i} {b['w']}px {b['fill']:5}  {' '.join(b['left'])} [{g}] {' '.join(b['right'])}")
    print(f"{len(res['boxes'])} box(es); guesses -> {jp}, picture -> {op}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
