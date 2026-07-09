"""Reddit ingestion tests — no network; a fake submission stands in for PRAW."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from solesight import config, db
from solesight.ingest import reddit


@dataclass
class FakeSubmission:
    id: str
    title: str
    selftext: str = ""
    score: int = 10
    num_comments: int = 3
    created_utc: int = 1_700_000_000
    subreddit: str = "Sneakers"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Point every connect() at a throwaway DB for the duration of a test."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield


def test_match_single_model():
    matched = reddit.match_models("Finally copped the Panda Dunk today!")
    assert [m.slug for m in matched] == ["dunk-low-panda"]


def test_match_multiple_models():
    text = "Comparing my Jordan 1 Chicago against the AJ4 Bred, both heat"
    slugs = {m.slug for m in reddit.match_models(text)}
    assert {"aj1-chicago", "aj4-bred"} <= slugs


def test_no_match_returns_empty():
    assert reddit.match_models("just some random sneakerhead thoughts") == []


def test_store_writes_one_row_per_model():
    post = FakeSubmission(id="abc", title="Jordan 1 Chicago vs AJ4 Bred")
    rows = [reddit._row(post, m, now=123)
            for m in reddit.match_models(reddit._post_text(post))]
    assert reddit.store(rows) == 2
    with db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM reddit_posts WHERE id='abc'").fetchone()[0]
    assert n == 2


def test_upsert_preserves_sentiment_but_refreshes_score():
    post = FakeSubmission(id="xyz", title="Panda Dunk restock", score=5)
    reddit.store([reddit._row(post, reddit.match_models("panda dunk")[0], now=1)])

    # Simulate the NLP stage scoring the post.
    with db.connect() as conn:
        conn.execute("UPDATE reddit_posts SET sentiment=0.9, sentiment_label='positive' "
                     "WHERE id='xyz'")

    # Re-ingest with an updated score; sentiment must survive.
    post.score = 42
    reddit.store([reddit._row(post, reddit.match_models("panda dunk")[0], now=2)])

    with db.connect() as conn:
        row = conn.execute("SELECT score, sentiment, sentiment_label, fetched_at "
                           "FROM reddit_posts WHERE id='xyz'").fetchone()
    assert row["score"] == 42          # volatile field refreshed
    assert row["sentiment"] == 0.9     # sentiment preserved
    assert row["sentiment_label"] == "positive"
    assert row["fetched_at"] == 2
