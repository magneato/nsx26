"""Unit and end-to-end tests. Standard library unittest; run from the repository root:

    python -m unittest discover -s tests -v

The end-to-end tests call the real redact/unredact wrappers (.sh on Linux, .cmd on Windows)
in a subprocess and skip themselves only when tesseract is missing.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nsx26.fonts import Metrics, fit_font, font_path, require_font  # noqa: E402
from nsx26.guess import Guesser  # noqa: E402
from nsx26.model import WordModel  # noqa: E402
from nsx26.page import set_page, substitute_names  # noqa: E402
from nsx26.redact import Region, apply, place, redact  # noqa: E402
from nsx26.text import paragraphs, segments, strip_gutenberg  # noqa: E402
from nsx26.unredact import norm, score  # noqa: E402
from nsx26.vision import Box, find_noise_boxes, find_solid_boxes, tesseract  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "passage.txt"
TEXT = FIXTURE.read_text(encoding="utf-8")
FONT = "LiberationSerif-Regular" if font_path("LiberationSerif-Regular") else "DejaVuSerif"


def have_tesseract() -> bool:
    try:
        tesseract()
        return True
    except RuntimeError:
        return False


def tool(name: str) -> list[str]:
    return [str(ROOT / f"{name}.cmd")] if os.name == "nt" else [str(ROOT / f"{name}.sh")]


class TextAndModel(unittest.TestCase):
    def setUp(self):
        self.model = WordModel.train(segments(TEXT), min_count=1)

    def test_gutenberg_markers_are_stripped(self):
        raw = "header\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\nbody text\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\nlicence"
        self.assertEqual(strip_gutenberg(raw).strip(), "body text")

    def test_probabilities_sum_to_one(self):
        m = self.model
        every = np.arange(m.V, dtype=np.int64)
        for u, v in [(0, 0), (m.id["the"], m.id["keeper"]), (m.id["wrote"], m.id["in"]), (1, 1)]:
            self.assertAlmostEqual(float(m.p(u, v, every).sum()), 1.0, places=9)

    def test_vectorised_equals_scalar(self):
        m = self.model
        rng = np.random.default_rng(0)
        u, v, w = (rng.integers(0, m.V, 300) for _ in range(3))
        ref = np.array([m.p1(int(a), int(b), int(c)) for a, b, c in zip(u, v, w)])
        self.assertTrue(np.array_equal(m.p_many(u, v, w), ref))

    def test_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "m.npz"
            self.model.save(p)
            m2 = WordModel.load(p)
            self.assertEqual(m2.words, self.model.words)
            self.assertTrue(np.array_equal(m2.t_cnt, self.model.t_cnt))


class Fonts(unittest.TestCase):
    def test_pages_follow_the_font_metrics(self):
        """Every platform sets test pages at the font's unhinted metrics: a word's inked columns on
        the page match the predicted ink box to within the anti-aliased edge."""
        page = set_page(paragraphs(TEXT), require_font(FONT), 24)
        g = np.asarray(page.image.convert("L"))
        m = Metrics(require_font(FONT))
        for t in [t for t in page.tokens if t.text in ("lighthouse", "harbour", "Tuesday")]:
            dark = (g[t.band[0]:t.band[1], t.x:t.x + t.w] < 128).any(0)
            cols = np.flatnonzero(dark)
            self.assertLessEqual(cols[0], 2, t.text)                 # ink starts at the box's left edge
            self.assertGreaterEqual(cols[-1], t.w - 3, t.text)       # and ends at its right edge
            self.assertLessEqual(abs(t.w - m.ink(t.text, 24)), 2.0, t.text)

    def test_fit_recovers_font_and_size(self):
        path = require_font(FONT)
        f = ImageFont.truetype(str(path), 22)
        samples = []
        for w in set(TEXT.split()[:120]):
            img = Image.new("L", (600, 60), 255)
            ImageDraw.Draw(img).text((10, 10), w, font=f, fill=0)
            cols = np.flatnonzero((np.asarray(img) < 200).any(0))
            if len(cols):
                samples.append((w, float(cols[-1] - cols[0] + 1)))
        fit = fit_font(samples)
        self.assertEqual(fit.name, Path(path).stem)
        self.assertAlmostEqual(fit.size, 22, delta=0.4)


class Vision(unittest.TestCase):
    def page(self) -> Image.Image:
        return set_page(paragraphs(TEXT), require_font(FONT), 24).image

    def test_clean_page_has_no_boxes(self):
        img = self.page()
        self.assertEqual(find_solid_boxes(img), [])
        self.assertEqual(find_noise_boxes(img), [])

    def test_boxes_are_found_to_the_pixel(self):
        page = set_page(paragraphs(TEXT), require_font(FONT), 24)
        img = page.image
        # boxes over real words, as a redaction is drawn: a long word, a short one, and a two-word span
        by = {t.text: t for t in reversed(page.tokens)}
        a, b, c1 = by["harbour"], by["on"], by["lighthouse"]
        c2 = next(t for t in page.tokens if t.line == c1.line and t.x > c1.x)
        want = [Box(t.x, t.band[0], t.w, t.band[1] - t.band[0]) for t in (a, b)]
        want.append(Box(c1.x, c1.band[0], c2.x + c2.w - c1.x, c1.band[1] - c1.band[0]))
        want.sort(key=lambda b: (b.y + b.h // 2, b.x))
        for fill in ("black", "noise"):
            out = apply(img, [Box(b.x, b.y, b.w, b.h) for b in want], fill, np.random.default_rng(1))
            got = find_solid_boxes(out) if fill == "black" else find_noise_boxes(out)
            self.assertEqual([(b.x, b.y, b.w, b.h) for b in got], [(b.x, b.y, b.w, b.h) for b in want], fill)


class Redaction(unittest.TestCase):
    def test_place_pad_and_uniform(self):
        r = Region(100, 50, 70, 30, "x")
        self.assertEqual(place(r, 1000).as_dict()["w"], 70)
        self.assertEqual(place(r, 1000, pad=3).as_dict()["x"], 97)
        b = place(r, 1000, uniform=160)
        self.assertEqual((b.w, b.x), (160, 55))
        self.assertEqual(place(Region(0, 0, 170, 30), 1000, uniform=160).w, 320)

    def test_output_is_flat_and_side_file_has_no_secret(self):
        page = set_page(paragraphs(TEXT), require_font(FONT), 24)
        t = next(t for t in page.tokens if t.text == "Tuesday")
        with tempfile.TemporaryDirectory() as d:
            src, out, key = Path(d) / "p.png", Path(d) / "r.png", Path(d) / "k.json"
            page.image.save(src)
            regions = [Region(t.x, t.band[0], t.w, t.band[1] - t.band[0], t.text)]
            meta = redact(src, out, regions, key_path=key)
            img = Image.open(out)
            self.assertEqual(img.mode, "RGB")
            b = meta["boxes"][0]
            self.assertFalse(np.asarray(img)[b["y"]:b["y"] + b["h"], b["x"]:b["x"] + b["w"]].any())
            side = (out.with_suffix(".json")).read_text(encoding="utf-8")
            self.assertNotIn("Tuesday", side)
            self.assertNotIn(hashlib.sha256(src.read_bytes()).hexdigest(), side)    # original's hash would let a guess be confirmed
            self.assertIn("Tuesday", key.read_text(encoding="utf-8"))

    def test_names_substitution_is_consistent(self):
        paras = ["The ship was seen by Margaret at noon. Later Margaret told the keeper."]
        new, mapping = substitute_names(paras, ["Hotaru", "Kasumi"], random.Random(0))
        self.assertEqual(list(mapping), ["Margaret"])
        self.assertEqual(new[0].count(mapping["Margaret"]), 2)


class Guessing(unittest.TestCase):
    def test_context_and_width_pick_the_word(self):
        model = WordModel.train(segments(TEXT), min_count=1)
        m = Metrics(require_font(FONT))
        g = Guesser(model, m, max_words=1)
        width = round(m.ink("lighthouse", 24))
        cands, n = g.guess(["went", "on", "to", "the"][-3:], ["climbed", "the"], width, 24, False, tol=1.5,
                           pad_max=0.5, sigma=1.0)
        self.assertGreater(n, 0)
        self.assertEqual(cands[0].text, "lighthouse")

    def test_names_join_the_candidates(self):
        model = WordModel.train(segments(TEXT), min_count=1)
        m = Metrics(require_font(FONT))
        g = Guesser(model, m, max_words=1, names=("Utakata", "Hotaru"))
        width = round(m.ink("Utakata", 24))
        cands, _ = g.guess(["seen", "by"], ["at", "noon"], width, 24, False, tol=1.0, pad_max=0.5, sigma=1.0)
        self.assertIn("Utakata", [c.text for c in cands])

    def test_score_matches_boxes_by_overlap(self):
        result = {"boxes": [{"x": 10, "y": 10, "w": 50, "h": 20, "guesses": [{"text": "keeper", "p_model": 0.6}],
                             "texts_that_fit": 3}]}
        answer = {"boxes": [{"x": 11, "y": 10, "w": 50, "h": 20, "text": "Keeper,"}]}
        s = score(result, answer)
        self.assertEqual((s["found"], s["top1"]), (1, 1))
        self.assertEqual(norm("“Keeper,”"), "keeper")


@unittest.skipUnless(have_tesseract(), "tesseract is not installed")
class EndToEnd(unittest.TestCase):
    """The shipped command-line tools, run exactly as a user runs them."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        page = set_page(paragraphs(TEXT), require_font(FONT), 24)
        cls.src = cls.tmp / "page.png"
        page.image.save(cls.src)
        cls.model = cls.tmp / "model.npz"
        subprocess.run(tool("unredact") + ["train", "--corpus", str(FIXTURE), "-o", str(cls.model)], check=True,
                       capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_pair(self, tag: str, *extra: str) -> tuple[dict, dict]:
        red, key = self.tmp / f"{tag}.png", self.tmp / f"{tag}.key.json"
        r = subprocess.run(tool("redact") + [str(self.src), "-o", str(red), "--term", "lighthouse", "--term",
                                             "Tuesday", "--key", str(key), *extra], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(tool("unredact") + [str(red), "--model", str(self.model)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return (json.loads((self.tmp / f"{tag}.guess.json").read_text(encoding="utf-8")),
                json.loads(key.read_text(encoding="utf-8")))

    def test_black_boxes(self):
        res, key = self.run_pair("black")
        s = score(res, key)
        n = len(re.findall(r"\blighthouse\b", TEXT)) + len(re.findall(r"\bTuesday\b", TEXT))
        self.assertEqual(s["boxes"], n)
        self.assertEqual(s["found"], n)
        self.assertEqual(s["false_boxes"], 0)
        self.assertGreaterEqual(s["top5"], n - 1)

    def test_noise_boxes(self):
        res, key = self.run_pair("noise", "--fill", "noise", "--seed", "7")
        s = score(res, key)
        self.assertEqual((s["found"], s["false_boxes"]), (s["boxes"], 0))

    def test_deterministic(self):
        a, _ = self.run_pair("det1")
        b, _ = self.run_pair("det2")
        for r in (a, b):
            r.pop("seconds", None)
            r.pop("image", None)
        self.assertEqual(a, b)

    def test_missing_term_is_reported_not_written(self):
        red, key = self.tmp / "miss.png", self.tmp / "miss.key.json"
        r = subprocess.run(tool("redact") + [str(self.src), "-o", str(red), "--term", "lighthouse", "--term",
                                             "zeppelin", "--key", str(key)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 3)
        self.assertNotIn("zeppelin", key.read_text(encoding="utf-8"))
        self.assertIn("zeppelin", r.stderr)
        self.assertNotIn("zeppelin", red.with_suffix(".json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
