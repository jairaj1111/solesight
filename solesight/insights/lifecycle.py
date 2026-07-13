"""Lifecycle stages + demand-event detection ("Launch Radar").

Two data-backed views of each model's demand curve:

**Stage** — where the model sits in its hype lifecycle, classified from the
shape of its own search-interest series (all thresholds are relative to the
model's own history, consistent with how Trends data works):

  * emerging — clearly accelerating from a low base
  * heating  — rising with real interest behind it
  * peaking  — at or near its own all-time band
  * cooling  — receding from a recent peak
  * dormant  — low and flat

**Demand events** — launch-like spikes detected from the data itself: a day
whose interest reaches ≥3× the model's trailing 90-day median (and ≥15 in
absolute terms, so noise on dead-quiet models doesn't fire). We deliberately
detect events rather than scrape release calendars — every event is verifiable
from the stored series. A `releases` calendar adapter can layer real dates on
top later; detected events keep working either way.
"""
from __future__ import annotations

from statistics import median

from .. import models
from ..db import connect

# --- stage thresholds (fractions of the model's own peak, % momentum) --------
_PEAK_BAND = 0.80        # recent level ≥80% of own max  -> peaking
_DORMANT_LEVEL = 0.22    # recent level <22% of own max and flat -> dormant
_HOT, _COOL = 12.0, -12.0   # momentum cutoffs (%)
_RECENT_PEAK_DAYS = 75   # a peak this recent can still be "cooling" off

# --- event detection ----------------------------------------------------------
_EVENT_MULTIPLE = 3.0    # spike ≥3× trailing median
_EVENT_FLOOR = 15.0      # ...and at least this absolute interest
_BASELINE_DAYS = 90      # trailing window for the median baseline
_MIN_BASELINE_DAYS = 30  # need at least this much history before detecting
_COOLDOWN_DAYS = 45      # one event per window; ignore echoes


def _series(slug: str) -> list[tuple[str, float]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT date, interest FROM trends WHERE model_slug=? ORDER BY date",
            (slug,)).fetchall()
    return [(r["date"], float(r["interest"])) for r in rows]


def stage(slug: str, momentum_pct: float | None = None) -> str | None:
    """Classify the model's lifecycle stage from its own series shape."""
    s = _series(slug)
    if len(s) < 28:
        return None
    vals = [v for _, v in s]
    peak = max(vals) or 1.0
    recent = sum(vals[-14:]) / 14
    prior = sum(vals[-28:-14]) / 14
    if momentum_pct is None:
        momentum_pct = ((recent - prior) / prior * 100.0) if prior else 0.0
    level = recent / peak
    days_since_peak = len(vals) - 1 - vals.index(max(vals))

    if level >= _PEAK_BAND:
        return "peaking"
    if momentum_pct >= _HOT:
        return "emerging" if level < 0.45 else "heating"
    if momentum_pct <= _COOL and days_since_peak <= _RECENT_PEAK_DAYS:
        return "cooling"
    if level < _DORMANT_LEVEL:
        return "dormant"
    return "cooling" if momentum_pct <= _COOL else "steady"


def detect_events(slug: str) -> list[dict]:
    """Launch-like demand spikes, verifiable from the stored series."""
    s = _series(slug)
    events: list[dict] = []
    last_event_i = -10_000
    for i in range(_MIN_BASELINE_DAYS, len(s)):
        date, v = s[i]
        window = [x for _, x in s[max(0, i - _BASELINE_DAYS):i]]
        base = median(window)
        threshold = max(_EVENT_MULTIPLE * base, _EVENT_FLOOR)
        if v >= threshold and (i - last_event_i) >= _COOLDOWN_DAYS and base > 0:
            # local peak: the highest day within a week of the trigger
            peak_slice = s[i:min(i + 7, len(s))]
            peak_date, peak_v = max(peak_slice, key=lambda t: t[1])
            after = [x for _, x in s[i + 7: i + 35]]
            retention = (sum(after) / len(after) / peak_v * 100) if after and peak_v else None
            events.append({
                "slug": slug,
                "date": peak_date,
                "baseline": round(base, 1),
                "peak": round(peak_v, 1),
                "multiple": round(peak_v / base, 1) if base else None,
                "retention_pct": None if retention is None else round(retention),
                "days_ago": len(s) - 1 - i,
            })
            last_event_i = i
    return events


def radar() -> dict:
    """Catalog-wide rollup: stage distribution + the freshest demand events."""
    stages: dict[str, int] = {}
    all_events: list[dict] = []
    for m in models.CATALOG:
        st = stage(m.slug)
        if st:
            stages[st] = stages.get(st, 0) + 1
        all_events.extend(detect_events(m.slug))
    all_events.sort(key=lambda e: e["date"], reverse=True)
    return {"stages": stages, "events": all_events[:10]}
