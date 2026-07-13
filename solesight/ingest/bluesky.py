"""Bluesky ingestion — REAL community chatter, no API key required.

Bluesky's AppView exposes an open, unauthenticated full-text post search
(`app.bsky.feed.searchPosts`). For every tracked model we search its keywords,
then store each hit twice, mirroring how the platform treats community data:

  * the post itself goes into the community-posts table (`reddit_posts`, with
    `subreddit='bluesky'`) so the existing sentiment pipeline scores it and the
    sentiment-summary/mood features run on REAL text;
  * daily aggregates (post count + likes/reposts/replies engagement) go into
    the `social` table under `platform='bluesky'`, making part of the social
    buzz signal live.

On the first successful run, seeded synthetic community posts purge themselves
(same self-replacement rule as every other source).
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict

from .. import config, models
from ..db import connect
from . import social as social_mod

# public.api.bsky.app is the documented public host; api.bsky.app also answers
# unauthenticated and is reachable from more networks. Try both.
_HOSTS = ("https://api.bsky.app", "https://public.api.bsky.app")
_UA = {"User-Agent": "SoleSight/1.0 (sneaker-market research; solesight index)"}
_LIMIT = 100          # max page size
_PER_MODEL_QUERIES = 2  # top keywords per model — stay polite


def _search(query: str) -> list[dict]:
    qs = urllib.parse.urlencode({"q": query, "limit": _LIMIT, "sort": "latest"})
    last_err = None
    for host in _HOSTS:
        try:
            req = urllib.request.Request(
                f"{host}/xrpc/app.bsky.feed.searchPosts?{qs}", headers=_UA)
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read()).get("posts", [])
        except Exception as exc:      # try next host
            last_err = exc
    raise RuntimeError(f"bluesky search failed on all hosts: {last_err}")


def _post_rows(model: models.SneakerModel, posts: list[dict], now: int) -> list[dict]:
    rows = []
    for p in posts:
        rec = p.get("record", {})
        text = rec.get("text", "")
        if not text or not model.matches(text):
            continue          # keyword matched by search, but confirm locally
        created = rec.get("createdAt", "")
        try:
            ts = int(time.mktime(time.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")))
        except Exception:
            continue
        rows.append({
            "id": "bsky_" + p.get("cid", p.get("uri", ""))[-24:],
            "model_slug": model.slug,
            "subreddit": "bluesky",
            "title": text[:300],
            "body": "",
            "score": int(p.get("likeCount") or 0),
            "num_comments": int(p.get("replyCount") or 0),
            "created_utc": ts,
            "fetched_at": now,
        })
    return rows


def _store_posts(rows: list[dict]) -> int:
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


def _buzz_rows(rows: list[dict], now: int) -> list[dict]:
    """Aggregate matched posts into per-day social rows for the buzz signal."""
    daily = defaultdict(lambda: {"posts": 0, "eng": 0})
    for r in rows:
        day = time.strftime("%Y-%m-%d", time.gmtime(r["created_utc"]))
        slot = daily[(r["model_slug"], day)]
        slot["posts"] += 1
        slot["eng"] += r["score"] + r["num_comments"]
    return [{"model_slug": slug, "date": day, "platform": "bluesky",
             "posts": v["posts"], "engagement": v["eng"], "fetched_at": now}
            for (slug, day), v in daily.items()]


def _purge_seeded_posts() -> int:
    with connect() as conn:
        cur = conn.execute("DELETE FROM reddit_posts WHERE fetched_at=?",
                           (config.SEED_TAG,))
    return cur.rowcount


def run() -> None:
    """Search Bluesky for every model; store posts + daily buzz aggregates."""
    now = int(time.time())
    all_rows: list[dict] = []
    failed = 0
    for model in models.CATALOG:
        queries = list(model.keywords[:_PER_MODEL_QUERIES]) or [model.trends_term]
        posts: list[dict] = []
        for q in queries:
            try:
                posts.extend(_search(f'"{q}"'))
            except Exception as exc:
                failed += 1
                print(f"  ! bluesky failed for {model.slug} ({q!r}): {exc}")
                break
            time.sleep(0.25)
        all_rows.extend(_post_rows(model, posts, now))

    n_posts = _store_posts(all_rows)
    n_buzz = social_mod.store(_buzz_rows(all_rows, now))
    purged = _purge_seeded_posts() if n_posts else 0
    print(f"  bluesky: {n_posts} community posts, {n_buzz} daily buzz rows, "
          f"{failed} query failures"
          + (f", purged {purged} seeded community posts" if purged else ""))


if __name__ == "__main__":
    run()
