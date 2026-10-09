"""Make the demo shown on the web page and in the README, by running the shipped tools.

    python tools/make_demo.py

1. `redact sample`: a page of The Adventures of Sherlock Holmes (held out from the word model),
   its proper names replaced by stand-ins from corpus/names.txt.
2. `redact`: hide five ordinary words, chosen by a fixed seed among words that occur once.
3. `unredact` on the redacted file alone, then `unredact score` against the key.
4. The same for the stand-in names, with the attacker holding the 90-name list (`--names-only`).

Everything in docs/demo/ is the tools' own output; nothing is edited by hand.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "demo"


def tool(name: str) -> list[str]:
    return [str(ROOT / f"{name}.cmd")] if os.name == "nt" else [str(ROOT / f"{name}.sh")]


def run(cmd: list[str], log: list[str]) -> str:
    shown = " ".join(Path(c).name if c.startswith(str(ROOT)) else c for c in cmd)
    shown = shown.replace(str(OUT) + os.sep, "")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = (r.stdout + r.stderr).replace(str(OUT) + os.sep, "").replace(str(ROOT) + os.sep, "")
    log.append(f"$ ./{shown}\n{text}")
    if r.returncode not in (0,):
        raise SystemExit(f"failed ({r.returncode}): {shown}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    page = OUT / "page.png"
    run(tool("redact") + ["sample", str(page), "--book", "1661", "--seed", "3", "--names",
                          str(ROOT / "corpus" / "names.txt")], log)
    layout = json.loads(page.with_suffix(".layout.json").read_text(encoding="utf-8"))
    words = [w["text"] for w in layout["words"]]
    once = sorted({w for w in words if words.count(w) == 1 and w.isalpha() and w not in layout["stand_ins"]
                   and len(w) >= 3})
    terms = random.Random(26).sample(once, 5)
    args = []
    for t in terms:
        args += ["--term", t]
    run(tool("redact") + [str(page), "-o", str(OUT / "words.png"), *args, "--key", str(OUT / "words.key.json")], log)
    run(tool("unredact") + [str(OUT / "words.png")], log)
    run(tool("unredact") + ["score", str(OUT / "words.guess.json"), str(OUT / "words.key.json")], log)

    names = layout["stand_ins"][:4]
    args = []
    for t in names:
        args += ["--term", t]
    run(tool("redact") + [str(page), "-o", str(OUT / "names.png"), *args, "--key", str(OUT / "names.key.json")], log)
    run(tool("unredact") + [str(OUT / "names.png"), "--names", str(ROOT / "corpus" / "names.txt"), "--names-only"],
        log)
    run(tool("unredact") + ["score", str(OUT / "names.guess.json"), str(OUT / "names.key.json")], log)
    (OUT / "transcript.txt").write_text("\n".join(log), encoding="utf-8")
    print("\n".join(log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
