"""Shared storage helpers for community-text sources.

Bluesky, Mastodon, Tumblr and YouTube comments all land the same way: each post
goes into `reddit_posts` (so the sentiment pipeline scores it and feeds the
community-mood signal), and daily aggregates go into `social` (feeding the
buzz signal). This module centralizes that write path so every source stays
one thin fetch-and-match adapter.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict

from .. import config
from ..db import connect
from . import social as social_mod

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(html: str) -> str:
    """Mastodon/Tumblr post bodies are HTML; reduce to plain text."""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html or "")).strip()


def store_posts(rows: list[dict]) -> int:
    """Upsert community posts (unscored — sentiment.py fills them in later)."""
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """INSERT INTO reddit_posts
                   (id, model_slug, subreddit, title, body, score, num_comments,
                    created_utc, sentiment, sentiment_label, fetched_at)
               VALUES (:id, :model_slug, :subreddit, :title, :body, :score,
                       :num_comments, :created_utc, NULL, NULL, :fetched_at)
               ON CONFLICT(id, model_slug) DO UPDATE SET
                   score        = excluded.score,
                   num_comments = excluded.num_comments,
                   fetched_at   = excluded.fetched_at""",
            rows,
        )
    return len(rows)


def store_buzz(rows: list[dict], platform: str, now: int) -> int:
    """Aggregate matched posts into daily social-buzz rows for one platform."""
    daily = defaultdict(lambda: {"posts": 0, "eng": 0})
    for r in rows:
        day = time.strftime("%Y-%m-%d", time.gmtime(r["created_utc"]))
        slot = daily[(r["model_slug"], day)]
        slot["posts"] += 1
        slot["eng"] += r["score"] + r["num_comments"]
    buzz = [{"model_slug": slug, "date": day, "platform": platform,
             "posts": v["posts"], "engagement": v["eng"], "fetched_at": now}
            for (slug, day), v in daily.items()]
    return social_mod.store(buzz)


def purge_seeded_posts() -> int:
    """Drop synthetic demo posts once any real community data is flowing."""
    with connect() as conn:
        cur = conn.execute("DELETE FROM reddit_posts WHERE fetched_at=?",
                           (config.SEED_TAG,))
    return cur.rowcount
