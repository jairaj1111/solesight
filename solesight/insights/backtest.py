"""Backtest — does the momentum signal actually predict forward demand?

SoleSight's Hype Score leans hardest on *momentum* (search interest, recent 14
days vs. the prior 14). That's the predictive engine — everything else largely
confirms. So the honest question a recruiter or a brand analyst asks first is:
**when momentum flagged a shoe as rising, did demand actually hold up weeks
later — more often than chance?**

We can answer that today because the trends table carries ~9 months of daily
history per model. This walks every model's series day by day, and for every
point with enough history on both sides records one sample:

    signal  = momentum at day T                (recent-14 vs prior-14, %)
    outcome = did demand HOLD its gain H days later, vs the pre-spike baseline?

"Catching a riser" doesn't mean the shoe climbs forever — hype spikes always
mean-revert. It means the new, higher demand *sticks*: H days later the shoe is
still elevated above where it started, not back to baseline. So the outcome
compares forward demand against the pre-window (prior) baseline, and we measure
whether "momentum was rising" predicted "gain held" better than the base rate.

Scope note (kept honest on the site): this validates the *search-demand*
prediction, which is the score's heaviest input. The resale-premium version
needs 30-60 days of resale history to accrue before it can be measured; the
`resale_ready` flag reports whether we're there yet.
"""
from __future__ import annotations

from .. import models
from ..db import connect

_HORIZON = 30           # days ahead we test the prediction against
_WIN = 14               # momentum window (matches signals.py)
_RISING = 10.0          # momentum % above which we call a shoe "rising"
_ELEVATED = 5.0         # forward demand % above which the outcome counts as "up"


def _series(conn, slug: str) -> list[float]:
    rows = conn.execute(
        "SELECT interest FROM trends WHERE model_slug=? ORDER BY date",
        (slug,)).fetchall()
    return [float(r["interest"]) for r in rows]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def run() -> dict:
    """Compute the momentum→forward-demand backtest across all models."""
    samples: list[tuple[float, float]] = []   # (momentum_T, forward_change)
    with connect() as conn:
        for m in models.CATALOG:
            s = _series(conn, m.slug)
            # need 2 windows of history before T and a full horizon after it
            for t in range(2 * _WIN, len(s) - _HORIZON):
                prior = _mean(s[t - 2 * _WIN:t - _WIN])
                recent = _mean(s[t - _WIN:t])
                if prior <= 0 or recent <= 0:
                    continue
                momentum = (recent - prior) / prior * 100.0
                fwd = _mean(s[t:t + _HORIZON])
                # "Did the gain hold?" — forward demand vs the pre-spike baseline.
                held = (fwd - prior) / prior * 100.0
                samples.append((momentum, held))

    n = len(samples)
    if n < 100:                       # too little to claim anything
        return {"ready": False, "samples": n}

    # Base rate: how often does demand rise over any window, regardless of signal?
    base_rate = sum(1 for _, f in samples if f >= _ELEVATED) / n

    # Conditional rate: among "rising" calls, how often did demand hold up?
    rising = [f for mom, f in samples if mom >= _RISING]
    hit_rate = (sum(1 for f in rising if f >= _ELEVATED) / len(rising)
                if rising else 0.0)

    # Pearson correlation between momentum and forward change (linear-signal test).
    corr = _pearson([mom for mom, _ in samples], [f for _, f in samples])

    # Is the resale-premium backtest measurable yet? (needs horizon of history)
    with connect() as conn:
        resale_days = conn.execute(
            "SELECT COUNT(DISTINCT date) n FROM resale WHERE source='ebay'"
        ).fetchone()["n"]

    return {
        "ready": True,
        "samples": n,
        "models": len(models.CATALOG),
        "horizon_days": _HORIZON,
        "hit_rate": round(hit_rate * 100, 1),      # % of rising calls that held up
        "base_rate": round(base_rate * 100, 1),    # % baseline (chance)
        "lift": round((hit_rate - base_rate) * 100, 1),   # points above chance
        "correlation": round(corr, 3),
        "rising_calls": len(rising),
        "resale_ready": resale_days >= _HORIZON,
        "resale_days": resale_days,
    }


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n == 0:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
