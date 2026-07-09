"""Seed SYNTHETIC Reddit sentiment + insights so the dashboard renders end-to-end.

This project's live signals come from Reddit (needs API credentials) and a
HuggingFace transformer (needs torch). When neither is available — a fresh clone,
a demo box, CI — the sentiment chart and marketing recommendations sit empty.

This script fabricates *plausible* Reddit chatter for every tracked model and
scores it, then generates insights via the offline rule engine. The volume and
sentiment skew are tied to each model's real Google-Trends momentum, so hot
models read more positive than cooling ones. It is deterministic (fixed seed).

    python -m scripts.seed_demo            # seed all models
    python -m scripts.seed_demo --wipe     # clear synthetic posts first

NB: this is DEMO data, not real Reddit chatter. Do not mix it with a live run —
use --wipe, or delete rows where fetched_at matches this seed.
"""
from __future__ import annotations

import argparse
import random
import time

from datetime import date, timedelta

from solesight import config, db, models
from solesight.db import connect
from solesight.ingest import resale, social
from solesight.insights import rules, signals

# A sentinel we stamp into fetched_at so synthetic rows are easy to find/remove.
SEED_TAG = 970000000  # fixed, recognizable, clearly not a real recent timestamp

_SUBREDDITS = ["Sneakers", "SneakerMarket", "streetwear", "Nike", "Jordans"]

_POSITIVE = [
    "Finally copped the {name} — quality is unreal 🔥",
    "The {name} might be my favorite release this year",
    "{name} on feet, comfiest pair I own",
    "PSA: {name} just restocked, go go go",
    "Worth every penny — {name} review after two weeks",
]
_NEGATIVE = [
    "Disappointed with the {name}, QC is all over the place",
    "Is it just me or is the {name} massively overhyped?",
    "Returned my {name} — sizing runs way off",
    "{name} resale prices are getting ridiculous",
    "Regret the {name}, creasing already",
]
_NEUTRAL = [
    "Thoughts on the {name}? Debating a pickup",
    "{name} sizing — true to size or go down half?",
    "How does the {name} compare to last year's colorway?",
    "Where's the best price on the {name} right now?",
    "{name} legit check please",
]

_POS_T, _NEG_T = 0.15, -0.15   # score -> label thresholds (match rules.py)

# Per-platform character: share of engagement, and engagement-per-post (TikTok/
# YouTube get far more engagement per post than a single IG post).
_PLATFORM = {
    "instagram": {"share": 0.40, "per_post": 320},
    "tiktok":    {"share": 0.45, "per_post": 900},
    "youtube":   {"share": 0.15, "per_post": 6000},
}
_SOCIAL_DAYS = 90   # days of daily buzz history per model
_RESALE_DAYS = 90   # days of daily resale history per model
# Per-source character: price multiplier vs the blended base, and a volume weight.
_SOURCE = {
    "stockx": {"mult": 1.03, "vol": 0.55, "noise": 0.04},   # cleaner, slight premium
    "ebay":   {"mult": 0.97, "vol": 0.45, "noise": 0.09},   # noisier, a bit cheaper
}


def _label(score: float) -> str:
    if score >= _POS_T:
        return "positive"
    if score <= _NEG_T:
        return "negative"
    return "neutral"


def _target_mean(momentum: float | None) -> float:
    """Map trend momentum (%) to a target average sentiment in ~[-0.4, 0.5]."""
    if momentum is None:
        return 0.05
    return max(-0.4, min(0.5, momentum / 60.0))


def _n_posts(recent_interest: float | None, rng: random.Random) -> int:
    """More chatter for higher-interest models; jittered so it looks organic."""
    base = 14 + (recent_interest or 0) * 0.4
    return int(rng.gauss(base, 4)) or 14


def _posts_for(model: models.SneakerModel, rng: random.Random) -> list[dict]:
    snap = signals.snapshot(model.slug)
    mean = _target_mean(snap["momentum_pct"])
    n = max(8, _n_posts(snap["recent_14d_interest"], rng))
    now = int(time.time())

    rows = []
    for i in range(n):
        score = max(-1.0, min(1.0, rng.gauss(mean, 0.35)))
        label = _label(score)
        template = (rng.choice(_POSITIVE) if label == "positive"
                    else rng.choice(_NEGATIVE) if label == "negative"
                    else rng.choice(_NEUTRAL))
        created = now - rng.randint(0, 60 * 86400)   # spread over ~60 days
        upvote_base = 70 if label == "positive" else 40
        rows.append({
            "id": f"seed_{model.slug}_{i}",
            "model_slug": model.slug,
            "subreddit": rng.choice(_SUBREDDITS),
            "title": template.format(name=model.name),
            "body": "",
            "score": max(0, int(rng.gauss(upvote_base, 60))),
            "num_comments": rng.randint(0, 120),
            "created_utc": created,
            "sentiment": round(score, 4),
            "sentiment_label": label,
            "fetched_at": SEED_TAG,
        })
    return rows


def _social_for(model: models.SneakerModel, rng: random.Random) -> list[dict]:
    """Daily per-platform buzz for one model over ~90 days.

    Engagement volume scales with the model's real Trends interest, and its slope
    is tied to Trends momentum so buzz and search move together. Weekly bumps
    (weekends) + noise keep it organic.
    """
    snap = signals.snapshot(model.slug)
    interest = snap["recent_14d_interest"] or 10.0
    momentum = snap["momentum_pct"] or 0.0
    base = 180 + interest * 90                       # bigger models buzz more
    slope = max(-0.6, min(0.9, momentum / 80.0))     # rising trend -> rising buzz
    now = int(time.time())
    start = date.fromtimestamp(now) - timedelta(days=_SOCIAL_DAYS - 1)

    rows = []
    for d in range(_SOCIAL_DAYS):
        day = start + timedelta(days=d)
        ramp = 1 + slope * (d / _SOCIAL_DAYS)        # linear drift over the window
        weekend = 1.18 if day.weekday() >= 5 else 1.0
        total = max(0.0, base * ramp * weekend * rng.gauss(1.0, 0.22))
        for platform, prof in _PLATFORM.items():
            eng = int(total * prof["share"] * rng.gauss(1.0, 0.15))
            rows.append({
                "model_slug": model.slug,
                "date": day.isoformat(),
                "platform": platform,
                "posts": max(0, round(eng / prof["per_post"])),
                "engagement": max(0, eng),
                "fetched_at": SEED_TAG,
            })
    return rows


def _resale_for(model: models.SneakerModel, rng: random.Random) -> list[dict]:
    """Daily per-source resale prices over ~90 days.

    The resale *premium* over retail scales with the model's Trends interest
    (hyped pairs sell over MSRP; sleepers sit near or below), and drifts with
    Trends momentum. StockX reads slightly higher/cleaner than eBay.
    """
    snap = signals.snapshot(model.slug)
    interest = snap["recent_14d_interest"] or 10.0
    momentum = snap["momentum_pct"] or 0.0
    retail = models.retail(model.slug) or 150
    premium0 = 0.85 + (interest / 100.0) * 1.8        # ~0.9x (cold) .. ~2.6x (hot)
    slope = max(-0.5, min(0.8, momentum / 90.0))
    now = int(time.time())
    start = date.fromtimestamp(now) - timedelta(days=_RESALE_DAYS - 1)

    rows = []
    for d in range(_RESALE_DAYS):
        day = start + timedelta(days=d)
        premium = premium0 * (1 + slope * (d / _RESALE_DAYS)) * rng.gauss(1.0, 0.05)
        base = retail * max(0.6, premium)
        for source, prof in _SOURCE.items():
            last = round(base * prof["mult"] * rng.gauss(1.0, prof["noise"]), 2)
            sales = max(0, int(rng.gauss(interest * 0.35 + 3, 4) * prof["vol"]))
            rows.append({
                "model_slug": model.slug,
                "date": day.isoformat(),
                "source": source,
                "last_sale": last,
                "lowest_ask": round(last * rng.uniform(1.02, 1.08), 2),
                "sales_count": sales,
                "fetched_at": SEED_TAG,
            })
    return rows


def store(rows: list[dict]) -> int:
    with connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO reddit_posts
                   (id, model_slug, subreddit, title, body, score, num_comments,
                    created_utc, sentiment, sentiment_label, fetched_at)
               VALUES (:id, :model_slug, :subreddit, :title, :body, :score,
                       :num_comments, :created_utc, :sentiment, :sentiment_label,
                       :fetched_at)""",
            rows,
        )
    return len(rows)


def wipe() -> int:
    with connect() as conn:
        n = conn.execute("DELETE FROM reddit_posts WHERE fetched_at=?",
                         (SEED_TAG,)).rowcount
        n += conn.execute("DELETE FROM social WHERE fetched_at=?",
                          (SEED_TAG,)).rowcount
        n += conn.execute("DELETE FROM resale WHERE fetched_at=?",
                          (SEED_TAG,)).rowcount
    return n


def main() -> None:
    p = argparse.ArgumentParser(description="Seed synthetic sentiment + insights.")
    p.add_argument("--wipe", action="store_true",
                   help="remove previously seeded synthetic posts first")
    args = p.parse_args()

    db.init_db()
    if args.wipe:
        print(f"  wiped {wipe()} synthetic posts")

    rng = random.Random(1337)
    posts = buzz = resale_rows = 0
    for model in models.CATALOG:
        posts += store(_posts_for(model, rng))
        buzz += social.store(_social_for(model, rng))
        resale_rows += resale.store(_resale_for(model, rng))
    print(f"  seeded {posts} Reddit posts + {buzz} social rows + {resale_rows} "
          f"resale rows across {len(models.CATALOG)} models")

    print("  generating rule-based insights...")
    rules.run()
    print("Done.")


if __name__ == "__main__":
    main()
