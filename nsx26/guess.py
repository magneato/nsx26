"""Rank the texts that could sit under one box.

Two facts narrow the search:
  1. width: in a known font and size, the ink of only some words (or short runs of
     words) is as wide as the box;
  2. context: of those, the word model says which suit the visible words around it.

The output is a ranked list of guesses. Each has `p_model`, the model's own belief
that it is the hidden text, normalised over every candidate that fits. It is the
model's belief, not a calibrated probability: `unredact.sh evaluate` measures how
far the two differ. The true text may also simply not be in the vocabulary.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .fonts import Metrics
from .model import BOS, UNK, WordModel
from .text import key


@dataclass
class Candidate:
    text: str
    score: float          # log P(words | left context) + log P(right context | words) [+ width term]
    p_model: float        # exp(score) normalised over all fitting candidates
    ink: float            # predicted ink width, px

    def as_dict(self) -> dict:
        return {"text": self.text, "score": round(self.score, 3), "p_model": round(self.p_model, 4),
                "ink_px": round(self.ink, 2)}


class Guesser:
    """Width tables for one model in one font. Build once, then `guess` per box at any size."""

    def __init__(self, model: WordModel, metrics: Metrics, max_words: int = 2, names: tuple[str, ...] = ()):
        """`names`: extra candidates (an attacker's list of suspects). A name the model has never seen
        shares the model's probability of an unseen word, P(<unk> | context), equally with the
        other unseen names; a name already in the vocabulary keeps its own probability."""
        self.m, self.metrics, self.max_words = model, metrics, max_words
        self.extra = sorted({n for n in names if n and key(n) not in model.id})
        self.K = max(1, len(self.extra))
        surf = list(model.surface) + self.extra
        caps = [s[:1].upper() + s[1:] for s in surf]
        self.space = metrics.space
        self.tab = {}
        for mode, texts in (("plain", surf), ("cap", caps)):
            adv, lb, rb = metrics.table(texts)
            adv[: UNK + 1] = 1e6                      # <s> and <unk> never fit
            single = adv - lb - rb
            fin = adv - rb
            self.tab[mode] = {
                "texts": texts, "adv": adv, "lb": lb, "rb": rb,
                "single": single, "single_order": np.argsort(single, kind="stable"),
                "fin": fin, "fin_order": np.argsort(fin, kind="stable"),
            }
        for t in self.tab.values():
            t["single_sorted"] = t["single"][t["single_order"]]
            t["fin_sorted"] = t["fin"][t["fin_order"]]

    def _window(self, mode: str, field: str, lo: float, hi: float, only_names: bool = False) -> np.ndarray:
        t = self.tab[mode]
        srt, order = t[field + "_sorted"], t[field + "_order"]
        ids = order[np.searchsorted(srt, lo, "left"):np.searchsorted(srt, hi, "right")]
        return ids[ids >= self.m.V] if only_names else ids[ids > UNK]

    def _map(self, ids):
        """Extra names are <unk> to the word model."""
        a = np.asarray(ids, dtype=np.int64)
        return np.where(a >= self.m.V, UNK, a)

    def _p(self, u, v, w: np.ndarray) -> np.ndarray:
        w = np.asarray(w, dtype=np.int64)
        n = len(w)
        p = self.m.p_many(np.broadcast_to(self._map(u), n), np.broadcast_to(self._map(v), n), self._map(w))
        return np.where(w >= self.m.V, p / self.K, p)

    def guess(self, left: list[str], right: list[str], width: float, size: float, starts_sentence: bool,
              tol: float = 2.0, pad_max: float = 0.0, sigma: float = 0.0, top: int = 10,
              beam: int = 200, only_names: bool = False) -> tuple[list[Candidate], int]:
        """Candidates whose ink, at `size` px, lies in [width - 2*pad_max - tol, width + tol].
        `only_names`: the box is known to hold one of the extra names; nothing else is considered.

        Returns the top candidates and how many distinct texts fit the width at all.
        `sigma` > 0 adds a Gaussian width term centred in that window (0 = every fit equal).
        """
        m, s = self.m, size
        lo, hi = (width - 2 * pad_max - tol) / s, (width + tol) / s
        centre = (width - pad_max) / s
        L = [BOS, BOS] + m.ids(left)
        R = m.ids(right)
        first_mode = "cap" if starts_sentence else "plain"
        # hypothesis: (logp, ids, advance used so far at 1px, blank before the first ink at 1px)
        hyps: list[tuple[float, list[int], float, float]] = [(0.0, [], 0.0, 0.0)]
        finals: list[tuple[float, list[int], float]] = []
        for step in range(1 if only_names else self.max_words):
            mode = first_mode if step == 0 else "plain"
            t = self.tab[mode]
            nxt = []
            for lp, seq, used, lb0 in hyps:
                ctx = L + seq
                gap = self.space if seq else 0.0
                if seq:
                    off = used + gap - lb0
                    done = self._window(mode, "fin", lo - off, hi - off)
                    inks = off + t["fin"][done]
                else:
                    done = self._window(mode, "single", lo, hi, only_names)
                    inks = t["single"][done]
                if len(done):
                    p = self._p(ctx[-2], ctx[-1], done)
                    for w, pw, ink in zip(done.tolist(), p.tolist(), inks.tolist()):
                        finals.append((lp + math.log(pw), seq + [w], ink * s))
                if step + 1 < self.max_words and not only_names:
                    cand = m.followers(ctx[-2], ctx[-1])
                    start = used + gap - (lb0 if seq else t["lb"][cand])
                    reach = start + t["adv"][cand] + self.space
                    cand = cand[reach < hi]
                    if len(cand):
                        p = self._p(ctx[-2], ctx[-1], cand)
                        keep = np.argsort(-p, kind="stable")[:beam]
                        for j in keep.tolist():
                            w = int(cand[j])
                            nxt.append((lp + math.log(float(p[j])), seq + [w], used + gap + float(t["adv"][w]),
                                        lb0 if seq else float(t["lb"][w])))
            nxt.sort(key=lambda h: (-h[0], h[1]))
            hyps = nxt[:beam]
        if not finals:
            return [], 0
        # the words after the box rescore every complete candidate, all at once
        lp = np.array([f[0] for f in finals])
        ink = np.array([f[2] for f in finals])
        ctx = [L[-2:] + f[1] for f in finals]
        u = self._map([c[-2] for c in ctx])
        v = self._map([c[-1] for c in ctx])
        for r in R[:2]:
            w = np.full(len(finals), r, dtype=np.int64)
            lp = lp + np.log(m.p_many(u, v, w))
            u, v = v, w
        if sigma > 0:
            lp = lp - 0.5 * ((ink - centre * s) / sigma) ** 2
        scored = [(float(sc), f[1], f[2]) for sc, f in zip(lp.tolist(), finals)]
        scored.sort(key=lambda x: (-x[0], x[1]))
        best = scored[0][0]
        z = sum(math.exp(sc - best) for sc, _, _ in scored)
        out, seen = [], set()
        for sc, seq, ink in scored:
            words = [(self.tab[first_mode] if i == 0 else self.tab["plain"])["texts"][w] for i, w in enumerate(seq)]
            text = " ".join(words)
            if text in seen:
                continue
            seen.add(text)
            if len(out) < top:
                out.append(Candidate(text, sc, math.exp(sc - best) / z, ink))
        return out, len(seen)
