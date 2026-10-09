"""unredact.sh evaluate: the measured answer to "how much does a redaction box give away?"

For each page: set a passage from a held-out book (authors the word model never saw)
in one of several fonts and sizes, pick words uniformly at random (any word, any
length, in the vocabulary or not), redact them with `redact` exactly as the CLI
does, write the PNG to disk, then run `unredact` on that file alone and score its
guesses against the answer key. Every condition uses the same pages and words.

    unredact.sh evaluate                   # default: 24 pages x 6 words, ~5 minutes
    unredact.sh evaluate --pages 4         # quick look
    unredact.sh evaluate --calibrate       # tune tolerances on a TRAINING book held out from a temporary model
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import PIL
from PIL import Image, ImageFilter

from . import CODENAME, __version__
from .fonts import require_font
from .model import UNK, WordModel
from .page import Page, choose_paragraphs, clean_quotes, set_page, substitute_names
from .redact import Region, redact
from .text import catalogue, key, paragraphs, prose, read_book, segments
from .unredact import DEFAULT_MODEL, PAD_MAX, ROOT, Seen, Settings, guesses, look, read_names, score

FONTS = ["LiberationSerif-Regular", "LiberationSans-Regular", "DejaVuSerif"]
SIZES = [20, 22, 24, 26]


@dataclass(frozen=True)
class Condition:
    name: str
    what: str
    fill: str = "black"
    pad: int = 0
    uniform: int = 0
    scan: bool = False
    pairs: bool = False
    pad_max: float | None = None       # attacker setting; None = the default
    no_context: bool = False
    image_of: str | None = None        # reuse the images of another condition
    names: bool = False                # proper names replaced by stand-ins; attacker holds the stand-in list
    names_only: bool = False           # ... and knows each box holds one of them


CONDITIONS = [
    Condition("black", "solid box over the ink of one word"),
    Condition("noise", "the same boxes filled with random static", fill="noise"),
    Condition("scan", "solid box, then printed and scanned (blur, grain, JPEG q75)", scan=True),
    Condition("width-only", "solid box, attacker ignores the words around it", no_context=True, image_of="black"),
    Condition("pairs", "one box over two consecutive words", pairs=True),
    Condition("pad3", f"box 3 px wider than the ink each side; attacker assumes up to {PAD_MAX:g}", pad=3),
    Condition("pad3-known", "same boxes; attacker knows the padding is up to 3", pad=3, pad_max=3.0, image_of="pad3"),
    Condition("names", "solid box over a proper name; attacker knows it is one of 90 listed names",
              names=True, names_only=True),
    Condition("names-mixed", "same boxes; the 90 names are only added to the vocabulary",
              names=True, image_of="names"),
    Condition("uniform", "the defence: every box 160 px wide (multiples of 160 if longer)", uniform=160),
]
NAMES_FILE = ROOT / "corpus" / "names.txt"


def scanned(img: Image.Image, rng: np.random.Generator) -> Image.Image:
    """A printer-and-scanner stand-in: slight blur, sensor grain, JPEG at quality 75."""
    g = img.convert("RGB").filter(ImageFilter.GaussianBlur(0.8))
    a = np.asarray(g, dtype=np.float32) + rng.normal(0, 6, size=(g.height, g.width, 1))
    g = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
    buf = io.BytesIO()
    g.save(buf, format="JPEG", quality=75)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def pick(page: Page, rng: random.Random, n: int, pairs: bool, only: set[str] | None = None) -> list[Region]:
    """n targets on n different lines, uniformly over the page's words (or adjacent word pairs),
    or over the words in `only`."""
    toks = page.tokens if only is None else [t for t in page.tokens if t.text in only]
    if pairs:
        units = [(a, b) for a, b in zip(toks, toks[1:]) if a.line == b.line]
    else:
        units = [(t, t) for t in toks]
    order = list(range(len(units)))
    rng.shuffle(order)
    out, lines = [], set()
    for i in order:
        a, b = units[i]
        if a.line in lines:
            continue
        lines.add(a.line)
        text = a.text if a is b else f"{a.text} {b.text}"
        out.append(Region(a.x, a.band[0], b.x + b.w - a.x, a.band[1] - a.band[0], text))
        if len(out) == n:
            break
    return out


def book_paragraphs(book, root: Path) -> list[str]:
    return [clean_quotes(p) for p in paragraphs(read_book(book, root)) if prose(p)]


def tool_versions() -> dict:
    from .vision import tesseract
    tv = subprocess.run([tesseract(), "--version"], capture_output=True, text=True).stdout.splitlines()
    return {"python": platform.python_version(), "numpy": np.__version__, "pillow": PIL.__version__,
            "tesseract": tv[0] if tv else "?", "platform": platform.platform()}


def corpus_digest(root: Path, books) -> dict:
    return {str(b.id): hashlib.sha256(b.path(root).read_bytes()).hexdigest()[:16] for b in books}


def make_cases(books, pages: int, per_page: int, seed: int, out: Path, conditions: list[Condition],
               log=print):
    """Set every page, redact it under every condition and write the files. Yields
    (page index, condition, redacted image path, answer key path)."""
    corpus_root = ROOT / "data" / "corpus"
    paras = {b.id: book_paragraphs(b, corpus_root) for b in books}
    out.mkdir(parents=True, exist_ok=True)
    for i in range(pages):
        rng = random.Random(seed * 100_003 + i)
        book = books[i % len(books)]
        font, size = FONTS[(i // len(books)) % len(FONTS)], SIZES[rng.randrange(len(SIZES))]
        page_paras = choose_paragraphs(paras[book.id], rng)
        page = set_page(page_paras, require_font(font), size)
        src = out / f"page{i:03d}.png"
        page.image.save(src)
        singles = pick(page, random.Random(rng.random()), per_page, pairs=False)
        doubles = pick(page, random.Random(rng.random()), per_page, pairs=True)
        src_n, named = src, []
        if any(c.names for c in conditions):
            nrng = random.Random(rng.random())
            paras_n, mapping = substitute_names(page_paras, list(read_names(NAMES_FILE)), nrng)
            page_n = set_page(paras_n, require_font(font), size)
            src_n = out / f"page{i:03d}.names-original.png"
            page_n.image.save(src_n)
            named = pick(page_n, nrng, per_page, pairs=False, only=set(mapping.values()))
        made: dict[str, Path] = {}
        log(f"page {i:3d}  {book.title[:30]:30}  {font} {size}px")
        for c in conditions:
            regions = named if c.names else doubles if c.pairs else singles
            if not regions or (c.image_of and c.image_of not in made):
                continue
            kp = out / f"page{i:03d}.{c.image_of or c.name}.key.json"
            if c.image_of:
                rp = made[c.image_of]
            else:
                rp = out / f"page{i:03d}.{c.name}.png"
                redact(src_n if c.names else src, rp, regions, c.fill, c.pad, c.uniform, seed=seed + i, key_path=kp,
                       meta_path=rp.with_suffix(".json"))
                if c.scan:
                    scanned(Image.open(rp), np.random.default_rng(seed + i)).save(rp)
                made[c.name] = rp
            yield i, c, rp, kp


def run(model: WordModel, books, pages: int, per_page: int, seed: int, out: Path, conditions: list[Condition],
        settings: Settings, log=print) -> dict:
    rows: dict[str, list[dict]] = {c.name: [] for c in conditions}
    secs: dict[str, float] = {c.name: 0.0 for c in conditions}
    false: dict[str, int] = {c.name: 0 for c in conditions}
    seen_cache: dict[Path, Seen] = {}
    for i, c, rp, kp in make_cases(books, pages, per_page, seed, out, conditions, log):
        st = Settings(settings.tol, c.pad_max if c.pad_max is not None else settings.pad_max, settings.sigma,
                      settings.max_words, 10, names=read_names(NAMES_FILE) if c.names else (), names_only=c.names_only)
        t0 = time.perf_counter()
        if rp not in seen_cache:
            seen_cache[rp] = look(Image.open(rp), st)
        res = guesses(seen_cache[rp], model, st, use_context=not c.no_context)
        secs[c.name] += time.perf_counter() - t0
        s = score(res, json.loads(kp.read_text(encoding="utf-8")))
        for r in s["rows"]:
            r["oov"] = any(model.id.get(key(w), UNK) == UNK for w in r["text"].split())
            r["page"] = i
            r["font_found"] = res["font"]["font"] if res["font"] else None
            r["size_found"] = res["font"]["size_px"] if res["font"] else None
        rows[c.name] += s["rows"]
        false[c.name] += s["false_boxes"]
    summary = {}
    for c in conditions:
        r = rows[c.name]
        n = len(r)
        if not n:
            continue
        found = [x for x in r if x["found"]]
        hits = [x for x in found if x["rank"] == 1]
        p = [x["p_top"] for x in found if x["p_top"] is not None]
        summary[c.name] = {
            "what": c.what, "boxes": n,
            "found": round(len(found) / n, 4),
            "top1": round(len(hits) / n, 4),
            "top5": round(sum(1 for x in found if x["rank"] and x["rank"] <= 5) / n, 4),
            "in_vocabulary": round(sum(not x["oov"] for x in r) / n, 4),
            "top1_if_in_vocabulary": round(len([x for x in hits if not x["oov"]]) / max(1, sum(not x["oov"] for x in r)), 4),
            "median_texts_that_fit": float(np.median([x["texts_that_fit"] for x in found])) if found else None,
            "mean_belief_of_first_guess": round(float(np.mean(p)), 4) if p else None,
            "false_boxes": false[c.name],
            "seconds_per_page": round(secs[c.name] / max(1, pages), 2),
        }
    return {"summary": summary, "rows": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="unredact.sh evaluate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", type=int, default=24)
    ap.add_argument("--words", type=int, default=6, help="redacted words (or pairs) per page")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, default=ROOT / "results")
    ap.add_argument("--only", nargs="*", default=None, help="condition names to run")
    ap.add_argument("--calibrate", action="store_true",
                    help="sweep tolerances on a training book held out from a temporary model")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    cat = catalogue(ROOT / "corpus" / "books.tsv")
    corpus_root = ROOT / "data" / "corpus"
    if a.calibrate:
        return calibrate(cat, corpus_root, a)
    model = WordModel.load(a.model)
    test = [b for b in cat if b.split == "test"]
    leaked = [b for b in test if f" {b.id}" in model.source or f"{b.id}," in model.source]
    if leaked or "train split" not in model.source:
        print(f"refusing: the model was not trained on the train split alone ({model.source!r})", file=sys.stderr)
        return 2
    wanted = set(a.only or [c.name for c in CONDITIONS])
    wanted |= {c.image_of for c in CONDITIONS if c.name in wanted and c.image_of}
    conds = [c for c in CONDITIONS if c.name in wanted]
    print(f"nsx26 {__version__} evaluate: {a.pages} pages x {a.words} targets, held-out books: "
          + "; ".join(f"{b.title} ({b.author})" for b in test))
    res = run(model, test, a.pages, a.words, a.seed, a.out / "pages", conds, Settings())
    report = {
        "nsx26": __version__, "codename": CODENAME,
        "command": "unredact.sh evaluate " + " ".join(argv or []),
        "pages": a.pages, "targets_per_page": a.words, "seed": a.seed,
        "fonts": FONTS, "sizes_px": SIZES,
        "test_books": [f"{b.title} ({b.author}, Gutenberg {b.id})" for b in test],
        "model": {"sha256": WordModel.digest(a.model), "words": model.n_words, "vocabulary": model.V - 2,
                  "source": model.source},
        "corpus_sha256_16": corpus_digest(corpus_root, cat),
        "settings": {"tol_px": Settings().tol, "pad_max_px": Settings().pad_max, "sigma_px": Settings().sigma,
                     "max_words": Settings().max_words},
        "tools": tool_versions(),
        "minutes": round((time.perf_counter() - t0) / 60, 1),
        "summary": res["summary"],
    }
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (a.out / "cases.json").write_text(json.dumps(res["rows"], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print_table(report["summary"])
    print(f"-> {a.out / 'results.json'} ({report['minutes']} min)")
    return 0


def print_table(summary: dict) -> None:
    print(f"\n{'condition':12} {'boxes':>5} {'found':>6} {'top1':>6} {'top5':>6} {'fits':>6}  belief")
    for name, s in summary.items():
        print(f"{name:12} {s['boxes']:5d} {s['found']:6.1%} {s['top1']:6.1%} {s['top5']:6.1%} "
              f"{(s['median_texts_that_fit'] or 0):6.0f}  {s['mean_belief_of_first_guess'] or 0:.2f}")


def calibrate(cat, corpus_root: Path, a) -> int:
    """Choose TOL / PAD_MAX / SIGMA without touching the test books: hold one training book out of a
    temporary model and sweep the settings on pages set from that book."""
    held = next(b for b in cat if b.id == 158)               # Emma: left out of this temporary model only
    segs = []
    for b in cat:
        if b.split == "train" and b.id != held.id:
            segs += segments(read_book(b, corpus_root))
    model = WordModel.train(segs, source="calibration: train split minus 158")
    out = a.out / "calibration"
    cases = []
    for i, c, rp, kp in make_cases([held], a.pages, a.words, a.seed + 1, out, [CONDITIONS[0]]):
        cases.append((look(Image.open(rp), Settings()), json.loads(kp.read_text(encoding="utf-8"))))
    table = []
    for tol in (1.0, 1.5, 2.0, 3.0):
        for pm in (0.0, 1.0, 2.0):
            for sg in (0.0, 1.0, 2.0):
                st = Settings(tol, pm, sg)
                hits = top5 = n = 0
                for seen, answer in cases:
                    sc = score(guesses(seen, model, st), answer)
                    hits, top5, n = hits + sc["top1"], top5 + sc["top5"], n + sc["boxes"]
                table.append({"tol": tol, "pad_max": pm, "sigma": sg, "top1": round(hits / n, 4),
                              "top5": round(top5 / n, 4)})
                print(f"tol {tol:3.1f} pad_max {pm:3.1f} sigma {sg:3.1f}: top1 {hits / n:.3f} top5 {top5 / n:.3f}")
    best = max(table, key=lambda t: (t["top1"], t["top5"], -t["tol"]))
    (out / "calibration.json").write_text(json.dumps({"held_out_training_book": held.title, "pages": a.pages,
                                                      "boxes": n, "grid": table, "best": best}, indent=2) + "\n",
                                                encoding="utf-8")
    print(f"best: {best}")
    return 0
