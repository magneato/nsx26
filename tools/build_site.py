"""Build the GitHub Pages site (docs/index.html, processed by Jekyll) and the README's results table
from results/results.json, so every number shown is one the benchmark produced.

    python tools/build_site.py
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nsx26 import CODENAME, __version__  # noqa: E402

ORDER = ["black", "noise", "scan", "width-only", "pairs", "names", "names-mixed", "pad3", "pad3-known", "uniform"]


def pct(v: float | None) -> str:
    return "-" if v is None else f"{100 * v:.0f}%"


def rows(summary: dict) -> list[dict]:
    return [dict(name=n, **summary[n]) for n in ORDER if n in summary]


def readme_table(rep: dict) -> str:
    out = ["| condition | what the redactor did / what the attacker knows | boxes | found | first guess right "
           "| right answer in top 5 | texts that fit (median) |",
           "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for r in rows(rep["summary"]):
        fits = "-" if r["median_texts_that_fit"] is None else f"{r['median_texts_that_fit']:,.0f}"
        out.append(f"| `{r['name']}` | {r['what']} | {r['boxes']} | {pct(r['found'])} | **{pct(r['top1'])}** "
                   f"| {pct(r['top5'])} | {fits} |")
    s = rep["summary"]["black"]
    out.append("")
    out.append(f"Measured by `{rep['command'].strip()}` ({rep['minutes']} min): {rep['pages']} pages, "
               f"{rep['targets_per_page']} boxes per page per condition, seed {rep['seed']}. Test books (authors absent "
               f"from the word model): {'; '.join(rep['test_books'])}. Fonts {', '.join(rep['fonts'])} at "
               f"{', '.join(map(str, rep['sizes_px']))} px. Word model: {rep['model']['words']:,} words, vocabulary "
               f"{rep['model']['vocabulary']:,}. {rep['tools']['tesseract']}, Python {rep['tools']['python']}, "
               f"numpy {rep['tools']['numpy']}, Pillow {rep['tools']['pillow']}.")
    out.append("")
    out += [f"* {f}" for f in findings(rep)]
    out.append("")
    out.append(f"Of the `black` boxes, {pct(s['in_vocabulary'])} hid words the model knows at all; on those the first "
               f"guess was right {pct(s['top1_if_in_vocabulary'])} of the time. The model's average belief in its "
               f"first guess was {s['mean_belief_of_first_guess']:.2f} against an accuracy of {s['top1']:.2f}: "
               f"its beliefs are {'over' if s['mean_belief_of_first_guess'] > s['top1'] else 'under'}confident and "
               f"should not be read as probabilities.")
    return "\n".join(out)


def findings(rep: dict) -> list[str]:
    """Plain comparisons, every number taken from the results."""
    S = rep["summary"]
    t = lambda n: pct(S[n]["top1"]) if n in S else "-"       # noqa: E731
    t5 = lambda n: pct(S[n]["top5"]) if n in S else "-"      # noqa: E731
    fits = S["black"]["median_texts_that_fit"]
    return [
        f"Width alone leaves a median of {fits:,.0f} texts (one or two words) that fit a box; with the words around "
        f"it the first guess is right {t('black')} of the time, against {t('width-only')} from width alone.",
        f"Random static instead of black: {t('noise')}. The box keeps its width either way.",
        f"Printed and scanned (simulated): {t('scan')}.",
        f"Two words under one box: {t('pairs')}.",
        f"Names: with the 90 stand-in names merely added to the vocabulary, the first guess is right "
        f"{t('names-mixed')} of the time; an attacker who knows the box holds one of those 90 puts the right one "
        f"first {t('names')} of the time and in the top five {t5('names')}.",
        f"Boxes 3 px wider than the ink on each side: {t('pad3')} for an attacker who assumes tight boxes, "
        f"{t('pad3-known')} for one who knows the padding (the wider width window admits more candidates).",
        f"Every box {160} px wide: **{t('uniform')}**.",
    ]


def site_table(rep: dict) -> str:
    trs = []
    for r in rows(rep["summary"]):
        bar = max(1, round(100 * r["top1"]))
        trs.append(
            f'<tr><th scope="row"><code>{html.escape(r["name"])}</code><span class="what-m">{html.escape(r["what"])}</span></th>'
            f'<td class="what">{html.escape(r["what"])}</td>'
            f'<td class="n">{pct(r["found"])}</td>'
            f'<td class="n"><span class="bar" style="--w:{bar}%"></span><b>{pct(r["top1"])}</b></td>'
            f'<td class="n">{pct(r["top5"])}</td></tr>')
    return "\n".join(trs)


PAGE = """---
layout: null
title: nsx26 · Black Mirror
---
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>nsx26 · {codename} v{version}</title>
<meta name="description" content="Redact a page image properly, then measure how much a solid box still gives away. Ranked guesses, not recovery, measured on prose the model has never seen.">
<meta property="og:title" content="nsx26 · {codename} v{version}">
<meta property="og:description" content="A box hides the pixels, not its width. redact.sh + unredact.sh, measured end to end.">
<meta property="og:image" content="{{{{ site.url }}}}{{{{ site.baseurl }}}}/img/social-preview.png">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<style>
:root {{
  --bg: #04060a; --panel: #0a0f16; --line: #1b2633; --ink: #e8f4ff; --dim: #8aa0b4;
  --cyan: #59f2ff; --green: #73ffb3; --amber: #ffb841; --magenta: #ff59cc;
  --glow: 0 0 6px rgba(89, 242, 255, .55), 0 0 18px rgba(89, 242, 255, .25);
  --mono: ui-monospace, "SFMono-Regular", "Cascadia Mono", "DejaVu Sans Mono", Menlo, Consolas, monospace;
}}
* {{ box-sizing: border-box; }}
html {{ background: var(--bg); }}
body {{ margin: 0; background: radial-gradient(ellipse at 50% 0%, #0b1420 0%, var(--bg) 60%) fixed;
  color: var(--ink); font: 16px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
a {{ color: var(--cyan); text-decoration: none; }} a:hover {{ text-shadow: var(--glow); }}
main {{ max-width: 1080px; margin: 0 auto; padding: 0 16px 64px; }}
header.hero {{ padding: 28px 0 8px; }}
header.hero img {{ width: 100%; height: auto; display: block; }}
.lede {{ font-size: 1.15rem; max-width: 760px; color: var(--ink); }}
.lede b {{ color: var(--amber); font-weight: 600; }}
.cta {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 20px 0 8px; }}
.cta a {{ font-family: var(--mono); border: 1px solid var(--cyan); padding: 8px 14px; border-radius: 2px; }}
.cta a.alt {{ border-color: var(--line); color: var(--dim); }}
h2 {{ font-family: var(--mono); font-weight: 500; letter-spacing: .14em; text-transform: uppercase; font-size: 1rem;
  color: var(--cyan); text-shadow: var(--glow); border-top: 1px solid var(--line); padding-top: 28px; margin-top: 48px; }}
h2 span {{ color: var(--dim); text-shadow: none; }}
p, li {{ color: #cfdeeb; }}
code, pre {{ font-family: var(--mono); font-size: .9em; }}
pre {{ background: var(--panel); border: 1px solid var(--line); padding: 14px 16px; overflow-x: auto; color: var(--green); }}
.table-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: .92rem; }}
th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
thead th {{ font-family: var(--mono); font-weight: 500; color: var(--dim); font-size: .8rem; letter-spacing: .06em; }}
td.n {{ text-align: right; font-family: var(--mono); white-space: nowrap; }}
tbody th code {{ color: var(--amber); }}
.bar {{ display: inline-block; height: 8px; width: calc(var(--w) * .6); max-width: 60px; margin-right: 8px;
  background: var(--green); box-shadow: 0 0 8px rgba(115, 255, 179, .6); vertical-align: middle; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }}
figure {{ margin: 0; background: var(--panel); border: 1px solid var(--line); }}
figure img {{ width: 100%; height: auto; display: block; }}
figcaption {{ padding: 10px 12px; font-size: .88rem; color: var(--dim); }}
.steps {{ counter-reset: s; list-style: none; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }}
.steps li {{ background: var(--panel); border: 1px solid var(--line); padding: 14px 16px; }}
.steps li::before {{ counter-increment: s; content: "0" counter(s); font-family: var(--mono); color: var(--magenta);
  display: block; margin-bottom: 6px; }}
.note {{ border-left: 2px solid var(--amber); padding: 4px 14px; color: #cfdeeb; }}
.what-m {{ display: none; }}
@media (max-width: 640px) {{
  .what {{ display: none; }}
  .what-m {{ display: block; font-size: .82rem; color: var(--dim); font-weight: 400; margin-top: 4px; }}
  th, td {{ padding: 8px 6px; }}
  .bar {{ display: none; }}
}}
footer {{ border-top: 1px solid var(--line); margin-top: 56px; padding-top: 18px; color: var(--dim); font-size: .85rem; }}
</style>
</head>
<body>
<main>
<header class="hero">
  <img src="img/hero.svg" alt="NSX26 Black Mirror: a redacted page, the box's width, and the ranked guesses that fit it" width="1280" height="640">
  <p class="lede">A flattened redaction box destroys the pixels under it, but <b>not its own width</b>. In a known font,
  only some words are that wide; the words around the box say which of those fit. <code>nsx26</code> redacts page images
  properly, then measures, on prose the model has never seen, how often that is enough to guess what was hidden.</p>
  <div class="cta">
    <a href="https://github.com/magneato/nsx26">github.com/magneato/nsx26</a>
    <a href="https://github.com/magneato/nsx26/releases/tag/v{version}">v{version} {codename}</a>
    <a class="alt" href="#results">results</a>
    <a class="alt" href="#defend">how to defend</a>
  </div>
</header>

<h2 id="results">Measured <span>// {boxes} boxes per condition, held-out authors</span></h2>
<p>Every row runs the shipped <code>redact</code> on a page, writes the PNG, and gives <code>unredact</code> that file and
nothing else. Words are chosen uniformly at random, of any length, known to the model or not.</p>
<div class="table-wrap"><table>
<thead><tr><th>condition</th><th class="what">what the redactor did / what the attacker knows</th><th>found</th><th>first guess right</th><th>top&nbsp;5</th></tr></thead>
<tbody>
{table}
</tbody></table></div>
<p class="note">The model is {calib}confident: its average belief in its first guess was {belief:.2f}, its accuracy {top1:.2f}.
Treat its numbers as rankings, not probabilities. Reproduce with <code>./unredact.sh evaluate</code>
(seed {seed}, {minutes} min); every case is in <code>results/cases.json</code>.</p>

<ul>
{findings}
</ul>

<h2>One page <span>// the tools' own output, unedited</span></h2>
<div class="grid">
  <figure><a href="demo/words.png"><img src="demo/words-crop.png" alt="Detail: words covered by black boxes" loading="lazy"></a>
    <figcaption>Detail of <code>redact.sh</code>'s output, actual pixels (click for the page).</figcaption></figure>
  <figure><a href="demo/words.guess.png"><img src="demo/words.guess-crop.png" alt="Detail: the same boxes with unredact's first guesses" loading="lazy"></a>
    <figcaption>The same detail of <code>unredact.sh</code>'s picture: first guess and belief per box.</figcaption></figure>
  <figure><a href="demo/names.guess.png"><img src="demo/names.guess-crop.png" alt="Detail: redacted names with guesses from the list" loading="lazy"></a>
    <figcaption>Names, attacker holding the 90-name list: detail.</figcaption></figure>
</div>
<div class="grid" style="margin-top:16px">
  <figure><img src="demo/words.png" alt="A page of prose with five words covered by black boxes" loading="lazy">
    <figcaption><code>redact.sh</code>: five words, solid boxes over their ink, flattened.</figcaption></figure>
  <figure><img src="demo/words.guess.png" alt="The same page with each box showing unredact's first guess in green" loading="lazy">
    <figcaption><code>unredact.sh</code>: each box shows its first guess and the model's belief. {demo_words}</figcaption></figure>
  <figure><img src="demo/names.guess.png" alt="The page with proper names redacted and guessed from a list" loading="lazy">
    <figcaption>Names, with the attacker holding a list of 90 that contains them. {demo_names}</figcaption></figure>
</div>
<pre>{transcript}</pre>

<h2>How it works</h2>
<ol class="steps">
  <li><b>Find the boxes.</b> Solid dark rectangles, or rectangles of random static, located to the pixel.</li>
  <li><b>Read the page.</b> <code>tesseract</code> reads the visible words; their widths fix the font and size by regression.</li>
  <li><b>Width.</b> From a {vocab}-word vocabulary, keep only texts whose ink is as wide as the box.</li>
  <li><b>Context.</b> A trigram word model ranks those by the visible words before and after the box.</li>
</ol>

<h2 id="defend">How to defend</h2>
<ul>
  <li><b>Make every box the same width.</b> <code>redact.sh --uniform 160</code>: the <code>uniform</code> row above.</li>
  <li><b>Remove the text, then reflow.</b> Redact the source document, not a picture of it, so nothing keeps its width.</li>
  <li><b>Pad generously and unpredictably.</b> A known pad only widens the window (<code>pad3-known</code>).</li>
  <li><b>Remember lists.</b> If an adversary can list the candidates, a name is far easier to guess than a word.</li>
</ul>

<h2>What it does not do</h2>
<ul>
  <li>It never recovers pixels. A flattened box has none; every output is a ranked guess, labelled as one.</li>
  <li>It is measured on clean, single-column, left-aligned prose in three common fonts, plus one simulated print-and-scan.
  Justified text, other fonts, real scans and real documents are not measured here; do not assume these numbers carry over.</li>
  <li>Its word model is 19th- and early 20th-century English from Project Gutenberg. It knows that era's words, not yours.</li>
  <li>It does not read PDFs. A PDF "redaction" that only draws a box over live text is a different, worse failure; rasterise and flatten.</li>
</ul>
<p class="note">Use it to audit your own redactions, or on documents you are entitled to examine.</p>

<h2>Run it</h2>
<pre>git clone https://github.com/magneato/nsx26 &amp;&amp; cd nsx26
./setup.sh                      # Ubuntu 24.04 / 26.04  (Windows 11: powershell -ExecutionPolicy Bypass -File .\\setup.ps1)
./redact.sh sample page.png --book 1661 --seed 3
./redact.sh page.png -o red.png --term talk --term dear --key red.key.json
./unredact.sh red.png           # -> red.guess.json, red.guess.png
./unredact.sh score red.guess.json red.key.json
./unredact.sh evaluate          # the table above</pre>

<footer>
  nsx26 v{version} “{codename}” · MIT licence · © 2026 Neural Splines LLC ·
  corpus: public-domain books from <a href="https://www.gutenberg.org/">Project Gutenberg</a>, downloaded at setup, not redistributed ·
  stand-in names: classical Japanese words for weather, seasons and birds.
</footer>
</main>
</body>
</html>
"""


def demo_caption(kind: str) -> str:
    demo = ROOT / "docs" / "demo"
    from nsx26.unredact import score
    s = score(json.loads((demo / f"{kind}.guess.json").read_text(encoding="utf-8")),
              json.loads((demo / f"{kind}.key.json").read_text(encoding="utf-8")))
    return (f"On this page: {s['found']} of {s['boxes']} boxes found, first guess right {s['top1']}, "
            f"right answer in the top five {s['top5']}.")


def crops() -> None:
    """Unscaled crops of the demo pictures around their boxes (same pixels, smaller frame)."""
    from PIL import Image
    demo = ROOT / "docs" / "demo"
    for kind, pics in (("words", ("words.png", "words.guess.png")), ("names", ("names.guess.png",))):
        boxes = json.loads((demo / f"{kind}.guess.json").read_text(encoding="utf-8"))["boxes"]
        b = boxes[len(boxes) // 2]
        cx, cy = b["x"] + b["w"] // 2, b["y"] + b["h"] // 2
        for pic in pics:
            im = Image.open(demo / pic)
            x0 = max(0, min(im.width - 760, cx - 380))
            y0 = max(0, min(im.height - 300, cy - 150))
            im.crop((x0, y0, x0 + 760, y0 + 300)).save(demo / pic.replace(".png", "-crop.png"), optimize=True)


def main() -> int:
    crops()
    rep = json.loads((ROOT / "results" / "results.json").read_text(encoding="utf-8"))
    s = rep["summary"]["black"]
    transcript = (ROOT / "docs" / "demo" / "transcript.txt").read_text(encoding="utf-8")
    page = PAGE.format(
        codename=CODENAME, version=__version__, table=site_table(rep), boxes=s["boxes"],
        calib="over" if s["mean_belief_of_first_guess"] > s["top1"] else "under",
        belief=s["mean_belief_of_first_guess"], top1=s["top1"], seed=rep["seed"], minutes=rep["minutes"],
        vocab=f"{rep['model']['vocabulary']:,}", transcript=html.escape(transcript.strip()),
        demo_words=demo_caption("words"), demo_names=demo_caption("names"),
        findings="\n".join("<li>" + re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(f)) + "</li>"
                            for f in findings(rep)))
    (ROOT / "docs" / "index.html").write_text(page, encoding="utf-8")
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    new = re.sub(r"(<!-- results:start -->\n).*?(\n<!-- results:end -->)",
                 lambda m: m.group(1) + readme_table(rep) + m.group(2), text, flags=re.S)
    readme.write_text(new, encoding="utf-8")
    print("wrote docs/index.html and the README results table")
    return 0


if __name__ == "__main__":
    sys.exit(main())
