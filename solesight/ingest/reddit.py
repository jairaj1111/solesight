"""Pull sneaker/streetwear chatter from Reddit via PRAW.

Strategy: rather than running one search per model per subreddit (23 x 6 API
calls), we scan each subreddit's recent listings *once* and match every tracked
model against each post locally. A post that mentions two models becomes a demand
signal for both — hence the composite (id, model_slug) key.

Sentiment is left NULL here; the NLP stage fills it in. Re-running ingestion
refreshes volatile fields (score, comment count) via upsert but preserves any
sentiment already computed, so we never pay to re-score unchanged posts.
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterator

import praw

from .. import config, models
from ..db import connect


@dataclass
class ScanSummary:
    scanned: int = 0                                    # unique posts examined
    stored: int = 0                                     # (post, model) rows written
    per_model: Counter = field(default_factory=Counter)

    def report(self) -> None:
        print(f"  reddit: scanned {self.scanned} posts, stored {self.stored} rows")
        for slug, n in self.per_model.most_common():
            print(f"    {slug:26} {n}")


def client(read_only: bool = True) -> praw.Reddit:
    """Application-only OAuth client — no user login needed to read public posts."""
    reddit = praw.Reddit(
        client_id=config.require("REDDIT_CLIENT_ID"),
        client_secret=config.require("REDDIT_CLIENT_SECRET"),
        user_agent=config.REDDIT_USER_AGENT,
        check_for_async=False,
    )
    reddit.read_only = read_only
    return reddit


def _post_text(post) -> str:
    return f"{post.title}\n{getattr(post, 'selftext', '') or ''}"


def match_models(text: str) -> list[models.SneakerModel]:
    """Return every tracked model whose keywords appear in `text`."""
    lowered = text.lower()
    return [m for m in models.CATALOG
            if any(kw.lower() in lowered for kw in m.keywords)]


def scan_subreddit(reddit: praw.Reddit, name: str,
                   listings: tuple[str, ...] = config.REDDIT_LISTINGS,
                   limit: int = config.REDDIT_SCAN_LIMIT) -> Iterator:
    """Yield unique submissions across the given listings of one subreddit."""
    seen: set[str] = set()
    subreddit = reddit.subreddit(name)
    for listing in listings:
        try:
            fetch = getattr(subreddit, listing)
            # `top` needs a time window; `new`/`hot`/`rising` don't accept one.
            gen = (fetch(time_filter="year", limit=limit) if listing == "top"
                   else fetch(limit=limit))
            for post in gen:
                if post.id in seen:
                    continue
                seen.add(post.id)
                yield post
        except Exception as exc:  # network / auth / private sub / rate limit
            print(f"  ! r/{name} '{listing}' failed: {exc}")


def _row(post, matched: models.SneakerModel, now: int) -> dict:
    return {
        "id": post.id,
        "model_slug": matched.slug,
        "subreddit": str(post.subreddit),
        "title": post.title,
        "body": getattr(post, "selftext", "") or "",
        "score": int(post.score),
        "num_comments": int(post.num_comments),
        "created_utc": int(post.created_utc),
        "fetched_at": now,
    }


def store(rows: list[dict]) -> int:
    """Upsert rows. Volatile fields refresh; sentiment is preserved on conflict."""
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
                   title        = excluded.title,
                   body         = excluded.body,
                   fetched_at   = excluded.fetched_at""",
            rows,
        )
    return len(rows)


def run(limit: int = config.REDDIT_SCAN_LIMIT,
        listings: tuple[str, ...] = config.REDDIT_LISTINGS) -> ScanSummary:
    """Scan all configured subreddits and store matched posts."""
    reddit = client()
    summary = ScanSummary()
    now = int(time.time())
    for name in config.REDDIT_SUBREDDITS:
        rows: list[dict] = []
        for post in scan_subreddit(reddit, name, listings, limit):
            summary.scanned += 1
            for m in match_models(_post_text(post)):
                rows.append(_row(post, m, now))
                summary.per_model[m.slug] += 1
        summary.stored += store(rows)  # store per-subreddit for incremental progress
    summary.report()
    return summary


if __name__ == "__main__":
    from .. import db

    db.init_db()
    run()
