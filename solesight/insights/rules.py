"""Offline, rule-based insight engine.

A deterministic alternative to the OpenAI path in ``llm.py``: it turns the same
signal snapshot into a plain-English marketing recommendation without any API
key or network call. Great for local demos, tests, and CI — and a sane fallback
when ``OPENAI_API_KEY`` is unset.

The write path mirrors ``llm.generate`` exactly (same ``insights`` table), so the
dashboard can't tell which engine produced a given recommendation.
"""
from __future__ import annotations

import time

from .. import models
from ..db import connect
from . import signals

# Momentum thresholds (percent change, recent 14d vs prior 14d).
_HOT, _WARM, _COOL = 15.0, 3.0, -15.0
# Average-sentiment thresholds on the signed [-1, 1] score.
_POS, _NEG = 0.15, -0.15


def _trend_clause(momentum: float | None) -> str:
    if momentum is None:
        return "Search interest is holding steady"
    if momentum >= _HOT:
        return f"Search interest is surging (+{momentum:.0f}% vs the prior two weeks)"
    if momentum >= _WARM:
        return f"Search interest is ticking up (+{momentum:.0f}% vs the prior two weeks)"
    if momentum <= _COOL:
        return f"Search interest is cooling fast ({momentum:.0f}% vs the prior two weeks)"
    if momentum < -_WARM:
        return f"Search interest is softening ({momentum:.0f}% vs the prior two weeks)"
    return "Search interest is flat versus the prior two weeks"


def _forecast_clause(s: dict) -> str:
    start, end, peak, peak_date = (s["forecast_start"], s["forecast_end_30d"],
                                   s["forecast_peak"], s["forecast_peak_date"])
    if start is None or end is None:
        return "no 30-day forecast is available yet"
    slope = end - start
    direction = ("keep climbing" if slope > 3 else
                 "keep sliding" if slope < -3 else "stay flat")
    window = f" with demand peaking around {peak_date}" if peak_date else ""
    return f"Prophet expects the next 30 days to {direction}{window}"


def _sentiment_clause(s: dict) -> str:
    n, avg = s["reddit_post_count"], s["avg_reddit_sentiment"]
    if not n or avg is None:
        return "Reddit chatter is too thin to read"
    mood = ("positive" if avg >= _POS else
            "negative" if avg <= _NEG else "mixed")
    return (f"Reddit sentiment is {mood} ({avg:+.2f} across {n} posts, "
            f"{s['sentiment_positive']} positive / {s['sentiment_negative']} negative)")


_PLATFORM_NAME = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube"}


def _buzz_clause(s: dict) -> str | None:
    idx, mom = s["social_buzz_index"], s["social_buzz_momentum_pct"]
    if idx is None:
        return None
    eng = {k: v for k, v in (s.get("social_platform_engagement") or {}).items() if v}
    top = max(eng, key=eng.get) if eng else None
    trend = ("spiking" if (mom or 0) >= _HOT else
             "building" if (mom or 0) >= _WARM else
             "fading" if (mom or 0) <= _COOL else "steady")
    lead = f", led by {_PLATFORM_NAME.get(top, top)}" if top else ""
    return f"Social buzz is {trend} (index {idx:.0f}/100{lead})"


def _resale_clause(s: dict) -> str | None:
    prem, last, mom = (s["resale_premium"], s["resale_last_sale"],
                       s["resale_momentum_pct"])
    if prem is None or last is None:
        return None
    drift = ("climbing" if (mom or 0) >= 5 else
             "softening" if (mom or 0) <= -5 else "holding")
    strength = ("a strong monetization signal" if prem >= 1.5 else
                "a healthy premium" if prem >= 1.1 else
                "near retail" if prem >= 0.95 else "below retail")
    return (f"Resale is {drift} at {prem:.1f}× retail (${last:.0f} last sale) — "
            f"{strength}")


def _tactic(s: dict) -> str:
    momentum = s["momentum_pct"] or 0.0
    peak_date = s["forecast_peak_date"]
    when = f" ahead of the {peak_date} peak" if peak_date else ""
    if momentum >= _HOT:
        return (f"Front-load paid spend and restock now{when}; ride the wave while "
                "intent is high.")
    if momentum >= _WARM:
        return (f"Tee up a mid-funnel push{when} — the audience is warming and "
                "conversion cost should be efficient.")
    if momentum <= _COOL:
        return ("Pull back on prospecting and shift budget to retargeting warm "
                "audiences to protect ROAS while demand recedes.")
    return ("Hold spend steady and lean on organic/UGC content to keep the model "
            "top-of-mind until a clearer signal emerges.")


def recommend(model: models.SneakerModel, s: dict) -> str:
    """Compose a 3-4 sentence recommendation from a signal snapshot."""
    buzz = _buzz_clause(s)
    social = f" {buzz}." if buzz else ""
    resale = _resale_clause(s)
    resale = f" {resale}." if resale else ""
    return (
        f"{_trend_clause(s['momentum_pct'])} for the {model.name}, and "
        f"{_forecast_clause(s)}. {_sentiment_clause(s)}.{social}{resale} {_tactic(s)}"
    )


def generate(model_slug: str) -> str:
    """Generate and persist an offline recommendation for one model."""
    model = models.get(model_slug)
    summary = recommend(model, signals.snapshot(model_slug))
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO insights (model_slug, generated_at, summary) "
            "VALUES (?, ?, ?)",
            (model_slug, int(time.time()), summary),
        )
    return summary


def run() -> None:
    for model in models.CATALOG:
        generate(model.slug)
        print(f"  insight (rules): {model.slug} -> ok")


if __name__ == "__main__":
    from .. import db

    db.init_db()
    run()
