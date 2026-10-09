"""A word model: how likely is each word, given the two words before it.

Interpolated absolute discounting with a Kneser-Ney continuation unigram. Counts
live in sorted int64 arrays (key = context * V + word), so a lookup is a
`searchsorted` and every word that ever followed a context is one contiguous
slice. Training is counting: no randomness, the same corpus gives the same file.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from .text import key

BOS, UNK = 0, 1
DISCOUNT = 0.75
FORMAT = 3


class WordModel:
    def __init__(self, words: list[str], surface: list[str], b_keys: np.ndarray, b_cnt: np.ndarray,
                 t_keys: np.ndarray, t_cnt: np.ndarray, n_words: int, n_sentences: int, source: str = ""):
        self.words, self.surface = words, surface
        self.b_keys, self.b_cnt, self.t_keys, self.t_cnt = b_keys, b_cnt, t_keys, t_cnt
        self.n_words, self.n_sentences, self.source = n_words, n_sentences, source
        self.id = {w: i for i, w in enumerate(words)}
        self.V = V = len(words)
        self.ctx1, inv = np.unique(b_keys // V, return_inverse=True)
        self.ctx1_tot = np.bincount(inv, weights=b_cnt).astype(np.int64)
        self.ctx1_typ = np.bincount(inv).astype(np.int64)
        self.ctx2, inv = np.unique(t_keys // V, return_inverse=True)
        self.ctx2_tot = np.bincount(inv, weights=t_cnt).astype(np.int64)
        self.ctx2_typ = np.bincount(inv).astype(np.int64)
        cont = np.bincount(b_keys % V, minlength=V).astype(np.float64)
        cont[BOS] = 0.0
        cont += 0.5                                  # a little mass for words never seen after anything
        self.p_cont = cont / cont.sum()
        self.common = np.argsort(-self.p_cont, kind="stable")[:4000]

    # ---- training -------------------------------------------------------------------------
    @classmethod
    def train(cls, segments: list[list[str]], max_vocab: int = 100_000, min_count: int = 2,
              source: str = "") -> "WordModel":
        freq: dict[str, int] = {}
        forms: dict[str, dict[str, int]] = {}
        for seg in segments:
            for i, w in enumerate(seg):
                k = key(w)
                freq[k] = freq.get(k, 0) + 1
                f = forms.setdefault(k, {})
                f[w] = f.get(w, 0) + (3 if i else 1)    # a sentence-initial capital says little about spelling
        ranked = sorted((w for w, c in freq.items() if c >= min_count), key=lambda w: (-freq[w], w))[:max_vocab]
        if not ranked:
            raise ValueError("corpus is empty: no word occurs often enough")
        words = ["<s>", "<unk>"] + ranked
        surface = ["<s>", "<unk>"] + [max(forms[w].items(), key=lambda kv: (kv[1], kv[0]))[0] for w in ranked]
        ids = {w: i for i, w in enumerate(words)}
        seq: list[int] = []
        for seg in segments:
            seq += [BOS, BOS] + [ids.get(key(w), UNK) for w in seg]
        a = np.array(seq, dtype=np.int64)
        V = np.int64(len(words))
        b_keys, b_cnt = np.unique(a[:-1] * V + a[1:], return_counts=True)
        t_keys, t_cnt = np.unique((a[:-2] * V + a[1:-1]) * V + a[2:], return_counts=True)
        return cls(words, surface, b_keys, b_cnt.astype(np.int64), t_keys, t_cnt.astype(np.int64),
                   sum(map(len, segments)), len(segments), source)

    # ---- save / load ----------------------------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            np.savez_compressed(
                f, format=np.int64(FORMAT), words=np.array("\n".join(self.words)),
                surface=np.array("\n".join(self.surface)), b_keys=self.b_keys, b_cnt=self.b_cnt,
                t_keys=self.t_keys, t_cnt=self.t_cnt, source=np.array(self.source),
                stats=np.array([self.n_words, self.n_sentences], dtype=np.int64))

    @classmethod
    def load(cls, path: Path) -> "WordModel":
        if not Path(path).is_file():
            raise FileNotFoundError(f"{path}: no word model (run ./setup.sh or ./unredact.sh train)")
        with np.load(path, allow_pickle=False) as z:
            if int(z["format"]) != FORMAT:
                raise ValueError(f"{path}: model format {int(z['format'])}, expected {FORMAT}; retrain it")
            s = z["stats"]
            return cls(str(z["words"]).split("\n"), str(z["surface"]).split("\n"), z["b_keys"], z["b_cnt"],
                       z["t_keys"], z["t_cnt"], int(s[0]), int(s[1]), str(z["source"]))

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    # ---- probabilities --------------------------------------------------------------------
    @staticmethod
    def _lookup(keys: np.ndarray, counts: np.ndarray, q: np.ndarray) -> np.ndarray:
        pos = np.minimum(np.searchsorted(keys, q), len(keys) - 1)
        return np.where(keys[pos] == q, counts[pos], 0)

    @staticmethod
    def _ctx(keys: np.ndarray, tot: np.ndarray, typ: np.ndarray, q: int) -> tuple[int, int]:
        i = int(np.searchsorted(keys, q))
        if i < len(keys) and keys[i] == q:
            return int(tot[i]), int(typ[i])
        return 0, 0

    def p_bigram(self, v: int, w: np.ndarray) -> np.ndarray:
        tot, typ = self._ctx(self.ctx1, self.ctx1_tot, self.ctx1_typ, v)
        if tot == 0:
            return self.p_cont[w]
        c = self._lookup(self.b_keys, self.b_cnt, v * np.int64(self.V) + w)
        return np.maximum(c - DISCOUNT, 0) / tot + DISCOUNT * typ / tot * self.p_cont[w]

    def p(self, u: int, v: int, w: np.ndarray) -> np.ndarray:
        """P(w | u v) for an array of word ids. Sums to 1 over the vocabulary."""
        lower = self.p_bigram(v, w)
        tot, typ = self._ctx(self.ctx2, self.ctx2_tot, self.ctx2_typ, u * self.V + v)
        if tot == 0:
            return lower
        V = np.int64(self.V)
        c = self._lookup(self.t_keys, self.t_cnt, (u * V + v) * V + w)
        return np.maximum(c - DISCOUNT, 0) / tot + DISCOUNT * typ / tot * lower

    def _ctx_many(self, keys: np.ndarray, tot: np.ndarray, typ: np.ndarray, q: np.ndarray):
        i = np.minimum(np.searchsorted(keys, q), len(keys) - 1)
        hit = keys[i] == q
        return np.where(hit, tot[i], 0), np.where(hit, typ[i], 0)

    def p_many(self, u: np.ndarray, v: np.ndarray, w: np.ndarray) -> np.ndarray:
        """P(w[i] | u[i] v[i]) for arrays of contexts and words; equal to `p` element by element."""
        V = np.int64(self.V)
        u, v, w = (np.asarray(a, dtype=np.int64) for a in (u, v, w))
        tot1, typ1 = self._ctx_many(self.ctx1, self.ctx1_tot, self.ctx1_typ, v)
        c1 = self._lookup(self.b_keys, self.b_cnt, v * V + w)
        safe1 = np.maximum(tot1, 1)
        lower = np.where(tot1 > 0, np.maximum(c1 - DISCOUNT, 0) / safe1 + DISCOUNT * typ1 / safe1 * self.p_cont[w],
                         self.p_cont[w])
        tot2, typ2 = self._ctx_many(self.ctx2, self.ctx2_tot, self.ctx2_typ, u * V + v)
        c2 = self._lookup(self.t_keys, self.t_cnt, (u * V + v) * V + w)
        safe2 = np.maximum(tot2, 1)
        return np.where(tot2 > 0, np.maximum(c2 - DISCOUNT, 0) / safe2 + DISCOUNT * typ2 / safe2 * lower, lower)

    def p1(self, u: int, v: int, w: int) -> float:
        return float(self.p(u, v, np.array([w], dtype=np.int64))[0])

    def followers(self, u: int, v: int) -> np.ndarray:
        """Words worth extending a hypothesis with: everything ever seen after (u v) or after v,
        plus the most common continuations. The beam ranks them exactly with `p`."""
        V = np.int64(self.V)
        lo = (u * V + v) * V
        t = self.t_keys[np.searchsorted(self.t_keys, lo):np.searchsorted(self.t_keys, lo + V)] % V
        lo = v * V
        b = self.b_keys[np.searchsorted(self.b_keys, lo):np.searchsorted(self.b_keys, lo + V)] % V
        ids = np.unique(np.concatenate([t, b, self.common]))
        return ids[ids > UNK]

    def ids(self, ws: list[str]) -> list[int]:
        return [self.id.get(key(w), UNK) for w in ws]
