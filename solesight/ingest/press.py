"""Sneaker press coverage — Google News + the big sneaker blogs, keyless.

Editorial coverage is a leading indicator the other signals miss: Hypebeast
writes the story *before* search spikes and resale moves. Two collection modes,
both free RSS with zero keys:

* **Blog feeds** — Hypebeast, Sneaker News, Nice Kicks, Sneaker Bar Detroit,
  Highsnobiety each expose one RSS feed; every headline is matched locally
  against all 90 tracked models (same one-feed-vs-whole-catalog trick as the
  Reddit scanner and boutique feeds).
* **Google News RSS** — one search-feed request per model (the model's quoted
  name), which sweeps the entire long tail of outlets: Complex, Footwear News,
  Sole Retriever, regional press. Capped via ``PRESS_GNEWS_MAX`` and paced.

Context signal only — surfaced in snapshots and the UI, not weighted into the
Hype Score until a backtest earns it a slot. Best-effort by design: any feed
that refuses is skipped and the section simply doesn't render for that model.
"""
from __future__ import annotations

import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .. import models
from ..db import connect

_UA = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/rss+xml, application/xml, text/xml",
}
_MAX_AGE_DAYS = 45      # ignore stale archive items
_PAUSE = 1.0            # polite gap between Google News queries

# Sneaker press with public RSS. Editable data, like the catalog.
# (Complex has no RSS — its stories arrive via the Google News sweep below.)
FEEDS = [
    ("Hypebeast", "https://hypebeast.com/footwear/feed"),
    ("Hypebeast", "https://hypebeast.com/feed"),
    ("Sneaker News", "https://sneakernews.com/feed/"),
    ("Nice Kicks", "https://www.nicekicks.com/feed/"),
    ("Sneaker Bar Detroit", "https://sneakerbardetroit.com/feed/"),
    ("Highsnobiety", "https://www.highsnobiety.com/feed/"),
    ("Sole Retriever", "https://www.soleretriever.com/rss.xml"),
    ("Sneaker Freaker", "https://www.sneakerfreaker.com/rss.xml"),
]

_GNEWS = ("https://news.google.com/rss/search?q={q}"
          "&hl=en-US&gl=US&ceid=US:en")


def _looks_spammy(title: str, outlet: str | None) -> bool:
    """Filter the SEO chaff Google News search feeds attract.

    Two cheap tells: outlets whose names aren't mostly Latin script (scraper
    sites reposting sneaker listings), and keyword-stuffed titles that repeat
    the same token three or more times ("Jordan ... JORDAN ... Jordan 11").
    """
    if outlet:
        ascii_ratio = sum(c.isascii() for c in outlet) / len(outlet)
        if ascii_ratio < 0.7:
            return True
    counts: dict[str, int] = {}
    for tok in title.lower().split():
        tok = tok.strip("\"'“”‘’().,–-")
        if len(tok) >= 3 and tok.isalpha():
            counts[tok] = counts.get(tok, 0) + 1
            if counts[tok] >= 3:
                return True
    return False


def _fetch_items(url: str) -> list[dict]:
    """Parse one RSS feed into [{title, url, source, published}] rows."""
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        root = ET.fromstring(resp.read())
    cutoff = datetime.now(timezone.utc) - timedelta(days=_MAX_AGE_DAYS)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        try:
            pub = parsedate_to_datetime(item.findtext("pubDate") or "")
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if pub < cutoff:
            continue
        # Google News items carry the originating outlet in <source>.
        outlet = (item.findtext("source") or "").strip() or None
        if _looks_spammy(title, outlet):
            continue
        if outlet and title.endswith(f" - {outlet}"):
            title = title[: -len(outlet) - 3].rstrip()
        items.append({"title": title, "url": link, "source": outlet,
                      "published": pub.date().isoformat()})
    return items


def _store(rows: list[dict]) -> int:
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """INSERT INTO press (model_slug, source, url, title, published, fetched_at)
               VALUES (:model_slug, :source, :url, :title, :published, :fetched_at)
               ON CONFLICT(model_slug, url) DO UPDATE SET
                   title=excluded.title, published=excluded.published,
                   fetched_at=excluded.fetched_at""",
            rows)
    return len(rows)


def _dedup_titles(rows: list) -> list:
    """The same story often arrives via a blog feed AND Google News — keep one."""
    seen, out = set(), []
    for r in rows:
        key = " ".join(r["title"].lower().split())
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def snapshot_fields(model_slug: str) -> dict:
    """Trailing-14-day coverage rollup for one model."""
    since = (date.today() - timedelta(days=14)).isoformat()
    with connect() as conn:
        rows = conn.execute(
            """SELECT title, source FROM press
               WHERE model_slug=? AND published>=?""",
            (model_slug, since)).fetchall()
    deduped = _dedup_titles(rows)
    outlets = {r["source"] for r in deduped if r["source"]}
    return {"press_14d": len(deduped),
            "press_outlets_14d": len(outlets)}


def headlines(model_slug: str, limit: int = 5) -> list[dict]:
    """Newest distinct headlines for one model (for the UI)."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT title, source, url, published FROM press
               WHERE model_slug=? ORDER BY published DESC LIMIT 40""",
            (model_slug,)).fetchall()
    return [{"title": r["title"], "source": r["source"],
             "url": r["url"], "published": r["published"]}
            for r in _dedup_titles(rows)][:limit]


def run() -> None:
    now = int(time.time())
    stored = 0

    # 1) Blog feeds: one request each, matched against the whole catalog.
    for outlet, url in FEEDS:
        try:
            items = _fetch_items(url)
        except Exception as exc:
            print(f"  ! press: {outlet} feed refused ({str(exc)[:60]})")
            continue
        rows = [{"model_slug": m.slug, "source": outlet, "url": it["url"],
                 "title": it["title"], "published": it["published"],
                 "fetched_at": now}
                for it in items for m in models.CATALOG
                if m.matches(it["title"])]
        stored += _store(rows)
        print(f"  press: {outlet} -> {len(items)} items, {len(rows)} model matches")
        time.sleep(_PAUSE)

    # 2) Google News: one search feed per model — sweeps the long tail of outlets.
    cap = int(os.environ.get("PRESS_GNEWS_MAX", "90"))
    hits = failed = 0
    for m in models.CATALOG[:cap] if cap < len(models.CATALOG) else models.CATALOG:
        q = urllib.parse.quote(f'"{m.name}"')
        try:
            items = _fetch_items(_GNEWS.format(q=q))
        except Exception as exc:
            failed += 1
            if failed <= 3:
                print(f"  ! press: google news failed for {m.slug} ({str(exc)[:60]})")
            time.sleep(_PAUSE)
            continue
        rows = [{"model_slug": m.slug,
                 "source": it["source"] or "Google News", "url": it["url"],
                 "title": it["title"], "published": it["published"],
                 "fetched_at": now} for it in items]
        stored += _store(rows)
        hits += len(rows)
        time.sleep(_PAUSE)
    print(f"  press: google news -> {hits} articles across "
          f"{min(cap, len(models.CATALOG))} models ({failed} failed) · "
          f"{stored} rows stored total")


if __name__ == "__main__":
    run()
