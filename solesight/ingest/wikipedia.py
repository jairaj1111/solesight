"""Wikipedia pageviews — a silhouette-level *cultural attention* signal.

The Wikimedia REST API returns daily article pageviews with no key required.
Sneaker colorways don't have their own articles, so each tracked model maps to
its silhouette/franchise article ("aj4-bred" → "Air_Jordan"); several models
sharing one article is expected and fine — the signal reads "how much cultural
attention is this franchise getting", which is a different (and steadier) lens
than colorway-level search demand.

Context signal only for now: surfaced in snapshots and the UI, deliberately NOT
weighted into the Hype Score until it earns its place in a backtest.
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import date, timedelta

from .. import models
from ..db import connect

_API = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        "en.wikipedia/all-access/user/{article}/daily/{start}/{end}")
_UA = {"User-Agent": "SoleSight/1.0 (sneaker-market research project)"}
_LOOKBACK_DAYS = 60

# slug prefix -> article. Only high-confidence articles; unmapped models skip.
_PREFIX_ARTICLES = [
    ("aj", "Air_Jordan"), ("travis-scott-aj", "Air_Jordan"),
    ("jumpman-jack", "Air_Jordan"),
    ("dunk-low", "Nike_Dunk"), ("sb-dunk", "Nike_Dunk"),
    ("nike-af1", "Nike_Air_Force_1"),
    ("air-max", "Nike_Air_Max"),
    ("nike-cortez", "Nike_Cortez"),
    ("blazer", "Nike_Blazer"),
    ("nike-shox", "Nike_Shox"),
    ("yeezy", "Adidas_Yeezy"),
    ("samba", "Adidas_Samba"),
    ("adidas-gazelle", "Adidas_Gazelle"),
    ("adidas-superstar", "Adidas_Superstar"),
    ("campus", "Adidas_Campus"),
    ("nb-", "New_Balance"),
    ("chuck-70", "Chuck_Taylor_All-Stars"),
    ("converse", "Chuck_Taylor_All-Stars"),
    ("vans-", "Vans"),
    ("salomon-", "Salomon_Group"),
    ("hoka-", "Hoka_One_One"),
    ("on-", "On_(company)"),
    ("puma-", "Puma_(brand)"),
    ("reebok-", "Reebok"),
    ("asics-", "ASICS"), ("gel-", "ASICS"),
]


def article_for(slug: str) -> str | None:
    for prefix, article in _PREFIX_ARTICLES:
        if slug.startswith(prefix):
            return article
    return None


def _fetch_article(article: str) -> list[tuple[str, int]]:
    end = date.today()
    start = end - timedelta(days=_LOOKBACK_DAYS)
    url = _API.format(article=article,
                      start=start.strftime("%Y%m%d00"),
                      end=end.strftime("%Y%m%d00"))
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        items = json.loads(resp.read()).get("items", [])
    return [(f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}-{i['timestamp'][6:8]}",
             int(i["views"])) for i in items]


def load(model_slug: str):
    """Daily (date, views) rows for one model, oldest first."""
    with connect() as conn:
        return [(r["date"], r["views"]) for r in conn.execute(
            """SELECT date, views FROM attention
               WHERE model_slug=? AND source='wikipedia' ORDER BY date""",
            (model_slug,)).fetchall()]


def run() -> None:
    """Fetch each mapped article once, fan the series out to its models."""
    now = int(time.time())
    articles: dict[str, list[tuple[str, int]]] = {}
    stored = failed = 0
    for m in models.CATALOG:
        art = article_for(m.slug)
        if not art:
            continue
        if art not in articles:
            try:
                articles[art] = _fetch_article(art)
                time.sleep(0.3)
            except Exception as exc:
                articles[art] = []
                failed += 1
                print(f"  ! wikipedia failed for {art}: {exc}")
        rows = [{"model_slug": m.slug, "date": d, "source": "wikipedia",
                 "views": v, "fetched_at": now} for d, v in articles[art]]
        if rows:
            with connect() as conn:
                conn.executemany(
                    """INSERT INTO attention (model_slug, date, source, views, fetched_at)
                       VALUES (:model_slug, :date, :source, :views, :fetched_at)
                       ON CONFLICT(model_slug, date, source) DO UPDATE SET
                           views=excluded.views, fetched_at=excluded.fetched_at""",
                    rows)
            stored += len(rows)
    print(f"  wikipedia: {stored} day-rows across {len(articles)} articles "
          f"({failed} failed)")


if __name__ == "__main__":
    run()
