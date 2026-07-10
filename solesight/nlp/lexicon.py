"""Dependency-free lexicon sentiment scorer — the no-torch fallback.

A small, sneaker-aware VADER-style scorer: weighted keyword lexicon, negation
flipping, intensifiers, and emoji. Used by `sentiment.py` whenever transformers/
torch isn't installed (fresh clones, the nightly CI Action) so real Reddit
chatter can still be scored. Less accurate than the transformer — that tradeoff
is deliberate and documented; install torch+transformers to upgrade in place.

Returns the same contract as the transformer path: (signed score in [-1, 1],
label in {positive, neutral, negative}).
"""
from __future__ import annotations

import re

# token -> weight. Sneaker-community vocabulary included alongside general terms.
_LEXICON: dict[str, float] = {
    # positive — general
    "love": 2.5, "loved": 2.5, "amazing": 3.0, "great": 2.0, "good": 1.5,
    "beautiful": 2.5, "perfect": 3.0, "best": 2.5, "awesome": 2.5, "excellent": 3.0,
    "happy": 2.0, "worth": 1.5, "recommend": 2.0, "favorite": 2.5, "solid": 1.5,
    # positive — sneaker slang
    "fire": 3.0, "heat": 2.5, "grail": 3.0, "clean": 2.0, "crispy": 2.5,
    "comfy": 2.5, "comfiest": 3.0, "comfortable": 2.5, "fresh": 2.0, "steal": 2.0,
    "cop": 1.5, "copped": 1.5, "w": 2.0, "banger": 2.5, "underrated": 1.5,
    "unreal": 2.5, "insane": 1.5, "restocked": 1.0, "beaters": 0.5,
    # negative — general
    "hate": -2.5, "terrible": -3.0, "awful": -3.0, "bad": -1.5, "worst": -2.5,
    "disappointed": -2.5, "disappointing": -2.5, "regret": -2.5, "cheap": -1.5,
    "poor": -2.0, "broke": -2.0, "return": -1.5, "returned": -2.0, "refund": -2.0,
    # negative — sneaker slang
    "overhyped": -2.5, "overpriced": -2.5, "ridiculous": -2.0, "fake": -2.0,
    "fakes": -2.0, "creasing": -2.0, "creased": -2.0, "qc": -1.0, "flaw": -2.0,
    "flaws": -2.0, "l": -2.0, "brick": -2.5, "bricked": -2.5, "scuff": -1.5,
    "glue": -1.5, "stiff": -1.0, "narrow": -0.5, "backdoored": -2.5, "bot": -1.0,
    "bots": -1.5, "reseller": -1.0, "resellers": -1.5,
}
_EMOJI = {"🔥": 2.5, "❤️": 2.0, "😍": 2.5, "💯": 2.0, "🙌": 1.5, "👀": 0.5,
          "😭": -0.5, "💀": -1.0, "🤮": -2.5, "👎": -2.0, "😤": -1.0}
_NEGATORS = {"not", "no", "never", "isnt", "isn't", "aint", "ain't", "dont",
             "don't", "doesnt", "doesn't", "wasnt", "wasn't", "cant", "can't"}
_INTENSIFIERS = {"very": 1.4, "so": 1.3, "really": 1.3, "super": 1.4,
                 "extremely": 1.6, "absolutely": 1.5, "kinda": 0.7, "bit": 0.7}

_POS_T, _NEG_T = 0.15, -0.15    # score -> label cutoffs (match rules.py)
_TOKEN = re.compile(r"[a-z']+")


def score_text(text: str) -> tuple[float, str]:
    """Score one string -> (signed score in [-1, 1], label)."""
    tokens = _TOKEN.findall(text.lower())
    total, hits = 0.0, 0
    for i, tok in enumerate(tokens):
        w = _LEXICON.get(tok)
        if w is None:
            continue
        window = tokens[max(0, i - 3):i]
        if any(t in _NEGATORS for t in window):
            w = -w * 0.8
        for t in window:
            w *= _INTENSIFIERS.get(t, 1.0)
        total += w
        hits += 1
    for emo, w in _EMOJI.items():
        n = text.count(emo)
        if n:
            total += w * min(n, 3)
            hits += 1
    if not hits:
        return 0.0, "neutral"
    # squash: ±1 hit of weight 3 ≈ ±0.6; saturates toward ±1 with agreement
    signed = max(-1.0, min(1.0, total / (abs(total) + 4.0) * 2.0))
    label = ("positive" if signed >= _POS_T else
             "negative" if signed <= _NEG_T else "neutral")
    return round(signed, 4), label


def score_texts(texts: list[str]) -> list[tuple[float, str]]:
    return [score_text(t) for t in texts]
