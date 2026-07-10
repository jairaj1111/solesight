"""Transformer-based sentiment scoring for Reddit posts.

Uses a HuggingFace pipeline (default: cardiffnlp twitter-roberta 3-class model).
We collapse the 3-class softmax into a single signed score in [-1, 1]:
    score = P(positive) - P(negative)
and store the argmax label alongside it.

Because a post that mentions two models is stored as two rows (composite key
id+model_slug) with identical text, we score each distinct post *once* and write
the result to every row sharing that id — no wasted inference.
"""
from __future__ import annotations

from functools import lru_cache

from .. import config
from ..db import connect

_MAX_CHARS = 512   # keep well under the model's token limit
_BATCH = 32        # texts per pipeline call


@lru_cache(maxsize=1)
def _pipeline():
    # Imported lazily so the app starts without loading torch until first use.
    from transformers import pipeline

    return pipeline(
        "sentiment-analysis",
        model=config.SENTIMENT_MODEL,
        top_k=None,        # return all class scores
        truncation=True,
    )


def _collapse(scores: list[dict]) -> tuple[float, str]:
    """Turn the model's per-class scores into (signed_score, argmax_label)."""
    by_label = {d["label"].lower(): d["score"] for d in scores}
    signed = by_label.get("positive", 0.0) - by_label.get("negative", 0.0)
    label = max(by_label, key=by_label.get)
    return signed, label


def score_texts(texts: list[str]) -> list[tuple[float, str]]:
    """Batch-score a list of texts.

    Uses the transformer pipeline when available; otherwise falls back to the
    dependency-free lexicon scorer (see nlp/lexicon.py) so scoring still works
    on machines and CI runners without torch. Same (score, label) contract.
    """
    if not texts:
        return []
    clipped = [t[:_MAX_CHARS] for t in texts]
    try:
        pipe = _pipeline()
    except ImportError:
        from . import lexicon
        print("  sentiment: transformers not installed — using lexicon fallback")
        return lexicon.score_texts(clipped)
    results = pipe(clipped, batch_size=_BATCH)
    return [_collapse(r) for r in results]


def score_text(text: str) -> tuple[float, str]:
    """Score a single string."""
    return score_texts([text])[0]


def score_unscored() -> int:
    """Score every distinct unscored post; write results to all its rows.

    Returns the number of distinct posts scored.
    """
    with connect() as conn:
        # One row per post id, even if it maps to several models.
        rows = conn.execute(
            """SELECT id, title, body FROM reddit_posts
               WHERE sentiment IS NULL GROUP BY id"""
        ).fetchall()

        pending = [(r["id"], f"{r['title']} {r['body'] or ''}".strip()) for r in rows]
        pending = [(pid, text) for pid, text in pending if text]
        if not pending:
            return 0

        scored = 0
        for i in range(0, len(pending), _BATCH):
            chunk = pending[i:i + _BATCH]
            results = score_texts([text for _, text in chunk])
            updates = [(signed, label, pid)
                       for (pid, _), (signed, label) in zip(chunk, results)]
            conn.executemany(
                "UPDATE reddit_posts SET sentiment=?, sentiment_label=? WHERE id=?",
                updates,
            )
            scored += len(updates)
    return scored


def run() -> None:
    n = score_unscored()
    print(f"  sentiment: scored {n} distinct posts")


if __name__ == "__main__":
    from .. import db

    db.init_db()
    run()
