"""Reddit community chatter via public subreddit RSS — no API key required.

Reddit closed self-service API registration (new apps sit in an approval queue
that can take weeks or never clear), and the `.json` endpoints now 403 without
OAuth. But every subreddit still publishes a public **RSS feed** — the same
kind of intended-for-consumption feed the sneaker-press adapter reads. We poll
a handful of sneaker subreddits' hot feeds, match posts against the catalog,
and route them through the community-mood pipeline like every other source.

Best-effort by design: Reddit rate-limits RSS, so a throttled feed is skipped
and the others carry on. If the official PRAW app is ever approved,
`ingest/reddit.py` layers richer data (scores, comments) on top; this keyless
path means community mood never has to wait on that queue.
"""
from __future__ import annotations

import time
import urllib.request
import xml.etree.ElementTree as ET

from .. import config, models
from . import _community

_UA = {"User-Agent": "script:solesight:v1.0 (sneaker-market research; by /u/solesight)"}
_NS = {"a": "http://www.w3.org/2005/Atom"}
_PAUSE = 4.0          # Reddit throttles RSS hard — space requests generously


def _fetch_sub(sub: str) -> list[dict]:
    url = f"https://www.reddit.com/r/{sub}/.rss?limit=50"
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        root = ET.fromstring(resp.read())
    out = []
    for e in root.findall("a:entry", _NS):
        title = (e.findtext("a:title", default="", namespaces=_NS) or "").strip()
        content = _community.strip_html(
            e.findtext("a:content", default="", namespaces=_NS) or "")
        eid = (e.findtext("a:id", default="", namespaces=_NS) or "").strip()
        updated = (e.findtext("a:updated", default="", namespaces=_NS) or "")
        out.append({"title": title, "text": f"{title} {content}".strip(),
                    "id": eid, "updated": updated})
    return out


def _rows(sub: str, posts: list[dict], now: int) -> list[dict]:
    rows = []
    for p in posts:
        if not p["text"]:
            continue
        matched = [m for m in models.CATALOG if m.matches(p["text"])]
        if not matched:
            continue
        try:
            ts = int(time.mktime(time.strptime(p["updated"][:19], "%Y-%m-%dT%H:%M:%S")))
        except Exception:
            ts = now
        pid = "rddt_" + (p["id"].split("/")[-1] or p["id"])[-24:]
        for m in matched:
            rows.append({
                "id": pid, "model_slug": m.slug, "subreddit": sub,
                "title": p["title"][:300], "body": "",
                "score": 0, "num_comments": 0,
                "created_utc": ts, "fetched_at": now,
            })
    return rows


def run() -> None:
    now = int(time.time())
    all_rows: list[dict] = []
    blocked = 0
    subs = config.REDDIT_SUBREDDITS
    for sub in subs:
        try:
            posts = _fetch_sub(sub)
        except Exception as exc:
            blocked += 1
            print(f"  ! reddit-rss: r/{sub} throttled/failed ({str(exc)[:40]})")
            time.sleep(_PAUSE)
            continue
        all_rows.extend(_rows(sub, posts, now))
        time.sleep(_PAUSE)
    if blocked == len(subs):
        print("  reddit-rss: every subreddit throttled this run (best-effort)")
        return
    n_posts = _community.store_posts(all_rows)
    n_buzz = _community.store_buzz(all_rows, "reddit", now)
    purged = _community.purge_seeded_posts() if n_posts else 0
    print(f"  reddit-rss: {n_posts} community posts from "
          f"{len(subs) - blocked}/{len(subs)} subreddits, {n_buzz} buzz rows"
          + (f", purged {purged} seeded" if purged else ""))


if __name__ == "__main__":
    run()
