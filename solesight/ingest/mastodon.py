"""Mastodon ingestion — a third live community source, no key required.

Mastodon's public hashtag timelines are open and unauthenticated. We pull a
few sneaker hashtags from the flagship instance, then match each post against
the whole catalog (same one-feed-vs-90-models trick as press/boutiques). Real
posts feed community mood (via the sentiment pipeline) and daily buzz.

Keyless and best-effort: if the instance is unreachable the stage skips and the
other community sources carry on.
"""
from __future__ import annotations

import json
import time
import urllib.request

from .. import models
from . import _community

_HOST = "https://mastodon.social"
_TAGS = ("sneakers", "sneakerhead", "kicks", "sneakercommunity", "airjordan")
_UA = {"User-Agent": "SoleSight/1.0 (sneaker-market research; solesight index)"}
_LIMIT = 40


def _fetch_tag(tag: str) -> list[dict]:
    url = f"{_HOST}/api/v1/timelines/tag/{tag}?limit={_LIMIT}"
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _rows(posts: list[dict], now: int) -> list[dict]:
    rows = []
    for p in posts:
        text = _community.strip_html(p.get("content", ""))
        if not text:
            continue
        matched = [m for m in models.CATALOG if m.matches(text)]
        if not matched:
            continue
        created = p.get("created_at", "")
        try:
            ts = int(time.mktime(time.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")))
        except Exception:
            ts = now
        pid = "masto_" + str(p.get("id", ""))
        for m in matched:
            rows.append({
                "id": pid, "model_slug": m.slug, "subreddit": "mastodon",
                "title": text[:300], "body": "",
                "score": int(p.get("favourites_count") or 0),
                "num_comments": int(p.get("replies_count") or 0),
                "created_utc": ts, "fetched_at": now,
            })
    return rows


def run() -> None:
    now = int(time.time())
    seen: set[str] = set()
    all_rows: list[dict] = []
    blocked = 0
    for tag in _TAGS:
        try:
            posts = _fetch_tag(tag)
        except Exception as exc:
            blocked += 1
            print(f"  ! mastodon: #{tag} failed ({str(exc)[:50]})")
            continue
        fresh = [p for p in posts if str(p.get("id")) not in seen]
        seen.update(str(p.get("id")) for p in posts)
        all_rows.extend(_rows(fresh, now))
        time.sleep(0.3)
    if blocked == len(_TAGS):
        print("  mastodon: instance unreachable — skipped")
        return
    n_posts = _community.store_posts(all_rows)
    n_buzz = _community.store_buzz(all_rows, "mastodon", now)
    purged = _community.purge_seeded_posts() if n_posts else 0
    print(f"  mastodon: {n_posts} community posts, {n_buzz} daily buzz rows"
          + (f", purged {purged} seeded" if purged else ""))


if __name__ == "__main__":
    run()
