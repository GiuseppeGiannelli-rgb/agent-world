"""Tiny BM25 index, ported 1:1 from server/engine/search.js. Used by the
skill library and the brain. No dependencies."""

import math
import re
import unicodedata

STOP = set(
    "the and for with that this from into your you are not but all any can una uno per con che del della delle "
    "dei degli gli le la il lo di da in su tra fra come cosa sono non piu più anche".split(" ")
)

_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_COMBINING_RE = re.compile(r"[̀-ͯ]")  # combining diacritics, after NFD decomposition


def tokenize(text) -> list[str]:
    s = str(text if text is not None else "").lower()
    s = _COMBINING_RE.sub("", unicodedata.normalize("NFD", s))
    return [w for w in _SPLIT_RE.split(s) if len(w) > 2 and w not in STOP]


class Bm25:
    def __init__(self, k1: float = 1.4, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: list[dict] = []
        self.df: dict[str, int] = {}
        self.avg_len = 0.0

    def add(self, id, fields: list[dict]) -> None:
        """fields: [{text, weight}]"""
        tf: dict[str, float] = {}
        length = 0.0
        for f in fields:
            weight = f.get("weight", 1)
            for t in tokenize(f.get("text")):
                tf[t] = tf.get(t, 0) + weight
                length += weight
        for t in tf:
            self.df[t] = self.df.get(t, 0) + 1
        self.docs.append({"id": id, "tf": tf, "len": length})
        self.avg_len = sum(d["len"] for d in self.docs) / len(self.docs)

    def search(self, query: str, k: int = 10) -> list[dict]:
        terms = list(dict.fromkeys(tokenize(query)))
        if not terms:
            return []
        n = len(self.docs)
        scored = []
        for d in self.docs:
            score = 0.0
            for t in terms:
                f = d["tf"].get(t)
                if not f:
                    continue
                df = self.df.get(t, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += idf * ((f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + (self.b * d["len"]) / (self.avg_len or 1))))
            if score > 0:
                scored.append({"id": d["id"], "score": score})
        scored.sort(key=lambda x: -x["score"])
        return scored[:k]
