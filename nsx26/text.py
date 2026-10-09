"""Text in, words out: the one place that decides what a "word" is.

A word is a run of letters or digits, optionally joined by inner apostrophes or
hyphens ("don't", "well-known", "1887"). Curly apostrophes are kept on the page
(they have their own width) and folded to "'" only when a word is looked up.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

WORD = re.compile(r"[A-Za-z0-9À-ɏ]+(?:['’\-][A-Za-z0-9À-ɏ]+)*")
SENTENCE_END = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+")
START = re.compile(r"^\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.M | re.I)
END = re.compile(r"^\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.M | re.I)


def key(word: str) -> str:
    """How a word is looked up: case folded, curly apostrophe folded."""
    return word.replace("’", "'").lower()


def words(text: str) -> list[str]:
    return WORD.findall(text)


def ends_sentence(token: str) -> bool:
    """True when a visible token closes a sentence ("said." "it?" "end.”")."""
    return bool(re.search(r"[.!?][\"'”’)\]]*$", token))


def strip_gutenberg(raw: str) -> str:
    """The book only: drop the Project Gutenberg header and licence footer."""
    raw = raw.replace("\r\n", "\n")
    s, e = START.search(raw), END.search(raw)
    return raw[s.end() if s else 0:e.start() if e else len(raw)]


def paragraphs(text: str) -> list[str]:
    """Blank-line separated blocks, line breaks joined, italics underscores removed."""
    out = []
    for block in re.split(r"\n\s*\n", text):
        p = " ".join(block.replace("_", "").split())
        if p:
            out.append(p)
    return out


def sentences(paragraph: str) -> list[str]:
    return [s for s in SENTENCE_END.split(paragraph) if s.strip()]


def prose(paragraph: str) -> bool:
    """A paragraph worth setting on a page: real sentences, not a heading or a table."""
    return len(words(paragraph)) >= 25 and (paragraph[:1].isalpha() or paragraph[:1] in "“\"'")


@dataclass(frozen=True)
class Book:
    id: int
    split: str
    author: str
    title: str

    def path(self, root: Path) -> Path:
        return root / f"pg{self.id}.txt"


def catalogue(path: Path) -> list[Book]:
    rows = [r for r in csv.reader(path.read_text(encoding="utf-8").splitlines(), delimiter="\t")
            if r and not r[0].startswith("#")]
    return [Book(int(r[0]), r[1], r[2], r[3]) for r in rows]


def read_book(book: Book, root: Path) -> str:
    p = book.path(root)
    if not p.is_file():
        raise FileNotFoundError(f"{p} is missing: run ./setup.sh (it downloads the corpus)")
    return strip_gutenberg(p.read_text(encoding="utf-8", errors="replace"))


def segments(text: str) -> list[list[str]]:
    """Training units: each sentence as a list of surface words."""
    out = []
    for para in paragraphs(text):
        for s in sentences(para):
            w = words(s)
            if w:
                out.append(w)
    return out


def read_folder(paths: list[Path]) -> list[list[str]]:
    """Any plain-text files (.txt .md .text) under the given paths, in sorted order."""
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.suffix.lower() in {".txt", ".md", ".text"})
        elif p.is_file():
            files.append(p)
        else:
            raise FileNotFoundError(p)
    segs: list[list[str]] = []
    for f in files:
        segs += segments(strip_gutenberg(f.read_text(encoding="utf-8", errors="replace")))
    return segs
