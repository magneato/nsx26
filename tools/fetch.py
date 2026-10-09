"""Download what setup needs, on any OS: the Gutenberg corpus and, if the system lacks them,
the Liberation and DejaVu fonts the test pages are set in. Python standard library only.

    python tools/fetch.py              # idempotent: skips what is already there
    python tools/fetch.py --fonts-only # what the tests need (CI)
"""
from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nsx26.fonts import font_path  # noqa: E402
from nsx26.text import catalogue  # noqa: E402

FONTS = {
    "LiberationSerif-Regular": "https://github.com/liberationfonts/liberation-fonts/files/7261482/"
                               "liberation-fonts-ttf-2.1.5.tar.gz",
    "DejaVuSerif": "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/"
                   "dejavu-fonts-ttf-2.37.zip",
}
UA = {"User-Agent": "nsx26-setup (+https://github.com/magneato/nsx26)"}


def get(url: str) -> bytes:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except OSError as e:
            if attempt == 2:
                raise SystemExit(f"download failed: {url}: {e}")
            time.sleep(3)
    raise AssertionError


def fetch_corpus() -> None:
    root = ROOT / "data" / "corpus"
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for b in catalogue(ROOT / "corpus" / "books.tsv"):
        p = b.path(root)
        if not p.is_file() or p.stat().st_size == 0:
            print(f"fetching Gutenberg #{b.id} {b.title}")
            p.write_bytes(get(f"https://www.gutenberg.org/cache/epub/{b.id}/pg{b.id}.txt"))
            time.sleep(1)                       # be polite to gutenberg.org
        rows.append(f"{b.id}\t{b.split}\t{hashlib.sha256(p.read_bytes()).hexdigest()}\t{b.title}")
    (root / "MANIFEST.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"corpus: {len(rows)} books, sha256 in {root / 'MANIFEST.tsv'}")


def fetch_fonts() -> None:
    dest = ROOT / "data" / "fonts"
    for probe, url in FONTS.items():
        if font_path(probe):
            continue
        print(f"fetching fonts: {url.rsplit('/', 1)[-1]}")
        dest.mkdir(parents=True, exist_ok=True)
        blob = get(url)
        if url.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                for n in z.namelist():
                    if n.lower().endswith(".ttf"):
                        (dest / Path(n).name).write_bytes(z.read(n))
        else:
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as t:
                for m in t.getmembers():
                    if m.isfile() and m.name.lower().endswith(".ttf"):
                        (dest / Path(m.name).name).write_bytes(t.extractfile(m).read())
        font_path.cache_clear()
        if not font_path(probe):
            raise SystemExit(f"{probe} still not found after download")
    print("fonts: ok")


if __name__ == "__main__":
    fetch_fonts()
    if "--fonts-only" not in sys.argv:
        fetch_corpus()
