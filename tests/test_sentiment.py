"""Sentiment tests — the transformer pipeline is mocked (no download/network)."""
from __future__ import annotations

import time

import pytest

from solesight import config, db
from solesight.nlp import sentiment


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield


@pytest.fixture
def fake_pipeline(monkeypatch):
    """Replace the HF pipeline with a keyword-driven stub."""
    def clf(texts, batch_size=32):
        out = []
        for t in texts:
            low = t.lower()
            if "fire" in low:
                out.append([{"label": "positive", "score": 0.9},
                            {"label": "neutral", "score": 0.07},
                            {"label": "negative", "score": 0.03}])
            elif "terrible" in low:
                out.append([{"label": "positive", "score": 0.03},
                            {"label": "neutral", "score": 0.07},
                            {"label": "negative", "score": 0.9}])
            else:
                out.append([{"label": "positive", "score": 0.2},
                            {"label": "neutral", "score": 0.7},
                            {"label": "negative", "score": 0.1}])
        return out
    monkeypatch.setattr(sentiment, "_pipeline", lambda: clf)


def test_collapse_signed_and_label():
    scores = [{"label": "positive", "score": 0.9},
              {"label": "neutral", "score": 0.07},
              {"label": "negative", "score": 0.03}]
    signed, label = sentiment._collapse(scores)
    assert round(signed, 2) == 0.87 and label == "positive"


def _seed(rows):
    now = int(time.time())
    with db.connect() as c:
        c.executemany(
            """INSERT OR REPLACE INTO reddit_posts
               (id,model_slug,subreddit,title,body,score,num_comments,
                created_utc,sentiment,sentiment_label,fetched_at)
               VALUES (?,?,?,?,?,1,0,?,NULL,NULL,?)""",
            [(i, m, "Sneakers", t, "", now, now) for i, m, t in rows],
        )


def test_score_unscored_dedupes_across_models(fake_pipeline):
    # p2 maps to two models -> two rows, identical text.
    _seed([
        ("p1", "dunk-low-panda", "These are fire"),
        ("p2", "aj1-chicago", "solid pickup honestly"),
        ("p2", "aj4-bred", "solid pickup honestly"),
    ])
    scored = sentiment.score_unscored()
    assert scored == 2  # distinct posts, not rows

    with db.connect() as c:
        p2 = c.execute("SELECT sentiment, sentiment_label FROM reddit_posts "
                       "WHERE id='p2'").fetchall()
    assert len(p2) == 2
    assert p2[0]["sentiment"] == p2[1]["sentiment"]         # same score both rows
    assert all(r["sentiment"] is not None for r in p2)


def test_score_unscored_skips_already_scored(fake_pipeline):
    _seed([("p1", "dunk-low-panda", "These are fire")])
    assert sentiment.score_unscored() == 1
    assert sentiment.score_unscored() == 0  # nothing left to score
