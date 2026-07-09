"""Pull daily search-interest for each model from Google Trends via pytrends.

Google Trends returns a 0-100 relative-interest index. Two things to know:

  * Resolution depends on window length: under ~270 days you get DAILY data,
    longer spans collapse to weekly/monthly. We request an explicit ~269-day
    range so the series stays daily (matching the 30-day daily forecast).
  * The final day is usually flagged `isPartial` (incomplete) and dips
    artificially — we drop those rows so the forecast isn't fed a false decline.

Each model is queried on its own so its 0-100 scale is normalized to its own
peak; that's the right granularity for per-model forecasting (we never compare
raw magnitudes across models).
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
from pytrends.request import TrendReq
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

from .. import config, models
from ..db import connect

# pytrends raises this (subclass of requests exceptions) on 429s and API hiccups.
try:  # import path has moved across pytrends versions
    from pytrends.exceptions import ResponseError, TooManyRequestsError
    _RETRYABLE = (ResponseError, TooManyRequestsError)
except ImportError:  # pragma: no cover
    from pytrends.exceptions import ResponseError
    _RETRYABLE = (ResponseError,)


@dataclass
class TrendsSummary:
    days: Counter = field(default_factory=Counter)
    failed: list[str] = field(default_factory=list)

    def report(self) -> None:
        total = sum(self.days.values())
        print(f"  trends: stored {total} day-rows across "
              f"{len(self.days)} models ({len(self.failed)} failed)")
        for slug in self.failed:
            print(f"    ! {slug}")


def default_timeframe(lookback_days: int = config.TRENDS_LOOKBACK_DAYS) -> str:
    """An explicit 'YYYY-MM-DD YYYY-MM-DD' window that yields daily resolution."""
    end = date.today()
    start = end - timedelta(days=lookback_days)
    return f"{start.isoformat()} {end.isoformat()}"


@retry(
    retry=retry_if_exception_type(_RETRYABLE),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _interest_over_time(pytrends: TrendReq, term: str, timeframe: str) -> pd.DataFrame:
    pytrends.build_payload([term], timeframe=timeframe)
    return pytrends.interest_over_time()


def fetch_model(pytrends: TrendReq, model: models.SneakerModel,
                timeframe: str | None = None) -> list[dict]:
    """Return daily interest rows for one model (partial trailing day dropped)."""
    now = int(time.time())
    df = _interest_over_time(pytrends, model.trends_term,
                             timeframe or default_timeframe())
    if df.empty or model.trends_term not in df.columns:
        return []
    if "isPartial" in df.columns:
        df = df[~df["isPartial"].astype(bool)]

    series = df[model.trends_term]
    _warn_if_not_daily(series, model.slug)
    return [
        {
            "model_slug": model.slug,
            "date": idx.date().isoformat(),
            "interest": float(val),
            "fetched_at": now,
        }
        for idx, val in series.items()
    ]


def _warn_if_not_daily(series: pd.Series, slug: str) -> None:
    """Sanity check: flag if Google gave us weekly data despite the daily window."""
    if len(series) < 3:
        return
    gap_days = series.index.to_series().diff().dt.days.median()
    if gap_days and gap_days > 2:
        print(f"  ! {slug}: got ~{gap_days:.0f}-day spacing (expected daily); "
              f"forecast frequency should match")


def store(rows: list[dict]) -> int:
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """INSERT INTO trends (model_slug, date, interest, fetched_at)
               VALUES (:model_slug, :date, :interest, :fetched_at)
               ON CONFLICT(model_slug, date) DO UPDATE SET
                   interest   = excluded.interest,
                   fetched_at = excluded.fetched_at""",
            rows,
        )
    return len(rows)


def run(timeframe: str | None = None,
        pause: float = config.TRENDS_REQUEST_PAUSE) -> TrendsSummary:
    """Ingest trends for all models, pausing between calls to dodge rate limits."""
    # NB: don't pass retries/backoff_factor — pytrends 4.9.x builds a urllib3 Retry
    # with the removed `method_whitelist` kwarg, which breaks on urllib3 v2. We
    # retry via tenacity around _interest_over_time instead.
    pytrends = TrendReq(hl="en-US", tz=360)
    summary = TrendsSummary()
    for model in models.CATALOG:
        try:
            n = store(fetch_model(pytrends, model, timeframe))
            summary.days[model.slug] = n
            print(f"  trends: {model.slug} -> {n} days")
        except Exception as exc:
            summary.failed.append(model.slug)
            print(f"  ! trends failed for {model.slug}: {exc}")
        time.sleep(pause)
    summary.report()
    return summary


if __name__ == "__main__":
    from .. import db

    db.init_db()
    run()
