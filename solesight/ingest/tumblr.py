"""Tumblr ingestion — a niche but real community source (free key).

Tumblr's API v2 exposes posts by tag (`/v2/tagged`). It needs a free OAuth
consumer key (`TUMBLR_API_KEY`) as an `api_key` query param — no user login.
We pull a few sneaker tags and match posts against the catalog, feeding
community mood + buzz like the other text sources.

Key-gated and best-effort: absent a key, the stage skips cleanly.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from .. import config, models
from . import _community

_URL = "https://api.tumblr.com/v2/tagged"
_TAGS = ("sneakers", "sneakerhead", "kicks", "jordans")
_UA = {"User-Agent": "SoleSight/1.0 (sneaker-market research; solesight index)"}


def _fetch_tag(tag: str) -> list[dict]:
    qs = urllib.parse.urlencode({"tag": tag, "api_key": config.TUMBLR_API_KEY,
                                 "limit": 20})
    req = urllib.request.Request(f"{_URL}?{qs}", headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read()).get("response", [])


def _text_of(post: dict) -> str:
    """A tagged post can be text/photo/link — pull whatever caption it has."""
    parts = [post.get("summary", ""), post.get("caption", ""),
             post.get("title", ""), post.get("body", "")]
    return _community.strip_html(" ".join(p for p in parts if p))


def _rows(posts: list[dict], now: int) -> list[dict]:
    rows = []
    for p in posts:
        text = _text_of(p)
        if not text:
            continue
        matched = [m for m in models.CATALOG if m.matches(text)]
        if not matched:
            continue
        ts = int(p.get("timestamp") or now)
        pid = "tumblr_" + str(p.get("id", ""))
        for m in matched:
            rows.append({
                "id": pid, "model_slug": m.slug, "subreddit": "tumblr",
                "title": text[:300], "body": "",
                "score": int(p.get("note_count") or 0), "num_comments": 0,
                "created_utc": ts, "fetched_at": now,
            })
    return rows


def run() -> None:
    if not config.TUMBLR_API_KEY:
        raise NotImplementedError("Tumblr skipped: set TUMBLR_API_KEY")
    now = int(time.time())
    seen: set[str] = set()
    all_rows: list[dict] = []
    for tag in _TAGS:
        try:
            posts = _fetch_tag(tag)
        except Exception as exc:
            print(f"  ! tumblr: #{tag} failed ({str(exc)[:50]})")
            continue
        fresh = [p for p in posts if str(p.get("id")) not in seen]
        seen.update(str(p.get("id")) for p in posts)
        all_rows.extend(_rows(fresh, now))
        time.sleep(0.3)
    n_posts = _community.store_posts(all_rows)
    n_buzz = _community.store_buzz(all_rows, "tumblr", now)
    purged = _community.purge_seeded_posts() if n_posts else 0
    print(f"  tumblr: {n_posts} community posts, {n_buzz} daily buzz rows"
          + (f", purged {purged} seeded" if purged else ""))


if __name__ == "__main__":
    run()
