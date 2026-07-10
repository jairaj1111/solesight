"""Market-intelligence aggregations across the whole catalog.

Where ``signals.snapshot`` answers "how is this one model doing?", this module
answers the questions a brand analyst asks of the *market*:

  * brand_rollups()      — per-brand averages: hype, resale premium, momentum,
                           sentiment, and share of the top-10.
  * category_rollups()   — the same cut by product category.
  * record_hype_snapshot() / hype_delta() — daily Hype Score history, so movers
                           can be measured as real change over time rather than
                           inferred from search momentum alone.
  * sentiment_summary()  — a human-readable digest of Reddit mood per model:
                           positive share plus the dominant praise/complaint
                           theme (keyword buckets over scored posts).

Everything reads the same SQLite tables the rest of the pipeline writes; the
snapshot recorder is invoked from scripts/build_site.py so history accrues one
row per model per day as the nightly refresh runs.
"""
from __future__ import annotations

from datetime import date, timedelta

from .. import models
from ..db import connect
from . import signals

# --- Hype history ------------------------------------------------------------


def record_hype_snapshot(snaps: dict[str, dict] | None = None,
                         on: str | None = None) -> int:
    """Upsert today's Hype Score for every model. Returns rows written."""
    day = on or date.today().isoformat()
    snaps = snaps or {m.slug: signals.snapshot(m.slug) for m in models.CATALOG}
    rows = [(slug, day, s["hype_score"]) for slug, s in snaps.items()
            if s.get("hype_score") is not None]
    with connect() as conn:
        conn.executemany(
            """INSERT INTO hype_history (model_slug, date, hype)
               VALUES (?, ?, ?)
               ON CONFLICT(model_slug, date) DO UPDATE SET hype=excluded.hype""",
            rows)
    return len(rows)


def hype_delta(slug: str, days: int = 7) -> float | None:
    """Change in Hype Score vs the closest snapshot >= `days` ago.

    None until enough history has accrued (needs a snapshot at least `days-1`
    days older than the latest one, so early runs don't report noise).
    """
    with connect() as conn:
        latest = conn.execute(
            "SELECT date, hype FROM hype_history WHERE model_slug=? "
            "ORDER BY date DESC LIMIT 1", (slug,)).fetchone()
        if not latest:
            return None
        cutoff = (date.fromisoformat(latest["date"])
                  - timedelta(days=days)).isoformat()
        base = conn.execute(
            "SELECT hype FROM hype_history WHERE model_slug=? AND date<=? "
            "ORDER BY date DESC LIMIT 1", (slug, cutoff)).fetchone()
    return round(latest["hype"] - base["hype"], 1) if base else None


# --- Rollups -----------------------------------------------------------------


def _avg(vals: list) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _rollup(group: dict[str, list[dict]], top10: set[str]) -> list[dict]:
    out = []
    for name, snaps in sorted(group.items()):
        out.append({
            "name": name,
            "models": len(snaps),
            "avg_hype": _avg([s["hype_score"] for s in snaps]),
            "avg_premium": _avg([s["resale_premium"] for s in snaps]),
            "avg_momentum": _avg([s["momentum_pct"] for s in snaps]),
            "avg_sentiment": _avg([s["avg_reddit_sentiment"] for s in snaps]),
            "top10": sum(1 for s in snaps if s["_slug"] in top10),
        })
    out.sort(key=lambda r: -(r["avg_hype"] or 0))
    return out


def _grouped(snaps: dict[str, dict], keyfn) -> tuple[dict, set]:
    ranked = sorted(snaps.items(), key=lambda kv: -(kv[1]["hype_score"] or 0))
    top10 = {slug for slug, _ in ranked[:10]}
    group: dict[str, list[dict]] = {}
    for slug, s in snaps.items():
        s = {**s, "_slug": slug}
        group.setdefault(keyfn(slug), []).append(s)
    return group, top10


def brand_rollups(snaps: dict[str, dict] | None = None) -> list[dict]:
    snaps = snaps or {m.slug: signals.snapshot(m.slug) for m in models.CATALOG}
    group, top10 = _grouped(snaps, lambda slug: models.get(slug).brand)
    return _rollup(group, top10)


def category_rollups(snaps: dict[str, dict] | None = None) -> list[dict]:
    snaps = snaps or {m.slug: signals.snapshot(m.slug) for m in models.CATALOG}
    group, top10 = _grouped(snaps, models.category)
    return _rollup(group, top10)


# --- Sentiment digest ----------------------------------------------------------

# Keyword buckets for what people praise/complain about. Matched against the
# text of scored posts; the dominant bucket per polarity becomes the digest.
_THEMES = {
    "sizing & fit": ("sizing", "size", "fit", "true to size", "runs "),
    "comfort": ("comfort", "comfiest", "cushion"),
    "quality": ("quality", "qc", "creasing", "crease", "build"),
    "resale price": ("resale", "price", "expensive", "overpriced", "ridiculous"),
    "availability": ("restock", "sold out", "raffle", "availability"),
    "styling": ("colorway", "on feet", "clean", "style", "look"),
}


def _top_theme(rows: list[str]) -> str | None:
    counts: dict[str, int] = {}
    for text in rows:
        lowered = text.lower()
        for theme, kws in _THEMES.items():
            if any(k in lowered for k in kws):
                counts[theme] = counts.get(theme, 0) + 1
    return max(counts, key=counts.get) if counts else None


def sentiment_summary(slug: str) -> dict | None:
    """Digest of Reddit mood: positive share + dominant praise/complaint theme."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT title, body, sentiment_label FROM reddit_posts
               WHERE model_slug=? AND sentiment IS NOT NULL""",
            (slug,)).fetchall()
    if not rows:
        return None
    texts = {"positive": [], "negative": []}
    for r in rows:
        if r["sentiment_label"] in texts:
            texts[r["sentiment_label"]].append(f"{r['title']} {r['body'] or ''}")
    n = len(rows)
    return {
        "posts": n,
        "positive_pct": round(len(texts["positive"]) / n * 100),
        "praise": _top_theme(texts["positive"]),
        "complaint": _top_theme(texts["negative"]),
    }
