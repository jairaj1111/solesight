"""Shared demand-signal snapshot for a single model.

Both the OpenAI insight engine (`llm.py`) and the offline rule-based engine
(`rules.py`) reason over the *same* numbers, so their recommendations never
disagree on the underlying facts. The dashboard's leaderboard reuses it too.

A snapshot rolls the three raw signals into a compact dict:
  * Google Trends  -> recent 14-day interest, momentum vs the prior 14 days
  * Prophet        -> forecast start/end/peak over the 30-day horizon
  * Reddit         -> average sentiment plus positive/neutral/negative counts
Any field is ``None`` when the underlying table has no rows for the model.
"""
from __future__ import annotations

import pandas as pd

from .. import models
from ..db import connect
from ..ingest import resale, social


def _latest_forecast(conn, slug: str) -> pd.DataFrame:
    return pd.DataFrame(
        [dict(r) for r in conn.execute(
            """SELECT horizon_date, yhat FROM forecasts
               WHERE model_slug=? AND generated_at=(
                   SELECT MAX(generated_at) FROM forecasts WHERE model_slug=?)
               ORDER BY horizon_date""",
            (slug, slug)).fetchall()]
    )


def snapshot(model_slug: str) -> dict:
    """Assemble every numeric demand signal we have for one model."""
    with connect() as conn:
        trends = pd.DataFrame(
            [dict(r) for r in conn.execute(
                "SELECT date, interest FROM trends WHERE model_slug=? ORDER BY date",
                (model_slug,)).fetchall()]
        )
        fc = _latest_forecast(conn, model_slug)
        sent = conn.execute(
            """SELECT AVG(sentiment) avg_s, COUNT(*) n,
                      SUM(sentiment_label='positive') pos,
                      SUM(sentiment_label='neutral')  neu,
                      SUM(sentiment_label='negative') neg
               FROM reddit_posts
               WHERE model_slug=? AND sentiment IS NOT NULL""",
            (model_slug,)).fetchone()

    recent = float(trends["interest"].tail(14).mean()) if not trends.empty else None
    prior = (float(trends["interest"].tail(28).head(14).mean())
             if len(trends) >= 28 else None)
    momentum = ((recent - prior) / prior * 100.0
                if recent is not None and prior else None)

    # Social buzz: normalized 0-100 daily series (like Trends). Recent 14-day
    # level + momentum vs the prior 14 days, plus recent per-platform totals.
    buzz = social.buzz_frame(model_slug)
    buzz_recent = float(buzz["buzz"].tail(14).mean()) if not buzz.empty else None
    buzz_prior = (float(buzz["buzz"].tail(28).head(14).mean())
                  if len(buzz) >= 28 else None)
    buzz_momentum = ((buzz_recent - buzz_prior) / buzz_prior * 100.0
                     if buzz_recent is not None and buzz_prior else None)
    social_posts = (int(buzz["posts"].tail(14).sum()) if not buzz.empty else 0)

    # Resale: recent avg sale price, premium over retail, price momentum, volume.
    price = resale.daily_price(model_slug)
    retail = models.retail(model_slug)
    r_recent = float(price["last_sale"].tail(14).mean()) if not price.empty else None
    r_prior = (float(price["last_sale"].tail(28).head(14).mean())
               if len(price) >= 28 else None)
    r_momentum = ((r_recent - r_prior) / r_prior * 100.0
                  if r_recent is not None and r_prior else None)
    r_premium = (r_recent / retail if r_recent is not None and retail else None)
    r_sales = int(price["sales_count"].tail(14).sum()) if not price.empty else 0

    f_start = float(fc["yhat"].iloc[0]) if not fc.empty else None
    f_end = float(fc["yhat"].iloc[-1]) if not fc.empty else None
    if not fc.empty:
        peak = fc.loc[fc["yhat"].idxmax()]
        f_peak_date, f_peak = peak["horizon_date"], float(peak["yhat"])
    else:
        f_peak_date, f_peak = None, None

    return {
        "recent_14d_interest": recent,
        "prior_14d_interest": prior,
        "momentum_pct": momentum,
        "forecast_start": f_start,
        "forecast_end_30d": f_end,
        "forecast_peak": f_peak,
        "forecast_peak_date": f_peak_date,
        "avg_reddit_sentiment": sent["avg_s"],
        "reddit_post_count": sent["n"] or 0,
        "sentiment_positive": sent["pos"] or 0,
        "sentiment_neutral": sent["neu"] or 0,
        "sentiment_negative": sent["neg"] or 0,
        "social_buzz_index": buzz_recent,
        "social_buzz_momentum_pct": buzz_momentum,
        "social_posts_14d": social_posts,
        "social_platform_engagement": social.platform_breakdown(model_slug),
        "retail_price": retail,
        "resale_last_sale": r_recent,
        "resale_premium": r_premium,
        "resale_momentum_pct": r_momentum,
        "resale_sales_14d": r_sales,
        "hype_score": _hype_score(recent, momentum, buzz_recent,
                                  sent["avg_s"], r_premium),
    }


# Weights for the composite Hype Score (renormalized over available signals).
_HYPE_WEIGHTS = {
    "interest": 0.18, "momentum": 0.24, "buzz": 0.20,
    "sentiment": 0.12, "resale": 0.26,
}


def _clamp01_100(x: float) -> float:
    return max(0.0, min(100.0, x))


def _hype_score(interest, momentum, buzz, sentiment, premium) -> float | None:
    """Blend the five signals into a single 0-100 hype index.

    Each component is mapped onto a 0-100 scale, then combined as a weighted
    average over whichever signals are present (weights renormalized), so a model
    missing (say) resale data still gets a sensible score from the rest.
    """
    comps = {
        "interest": interest if interest is None else _clamp01_100(interest),
        "momentum": None if momentum is None else _clamp01_100(50 + momentum * 0.8),
        "buzz": buzz if buzz is None else _clamp01_100(buzz),
        "sentiment": None if sentiment is None
        else _clamp01_100((sentiment + 1) / 2 * 100),
        "resale": None if premium is None
        else _clamp01_100((premium - 0.8) / (2.6 - 0.8) * 100),
    }
    num = sum(_HYPE_WEIGHTS[k] * v for k, v in comps.items() if v is not None)
    den = sum(_HYPE_WEIGHTS[k] for k, v in comps.items() if v is not None)
    return round(num / den, 1) if den else None
