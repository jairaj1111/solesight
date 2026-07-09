"""Prophet demand forecasting.

The demand signal we forecast is the daily Google Trends interest index — a dense,
evenly-spaced 0-100 series Prophet handles well. Two domain adjustments:

  * The series is bounded [0, 100], so we clip the forecast (incl. intervals) into
    that range — a raw linear trend can otherwise drift negative or above 100.
  * Google Trends normalizes each model to its own peak, so we forecast each
    model's own trajectory; magnitudes are never compared across models.

Reddit buzz/sentiment are surfaced separately today and are the natural next
regressors once we've backfilled enough of their daily history.
"""
from __future__ import annotations

import logging
import time

import pandas as pd

from .. import config, models
from ..db import connect

# Prophet + cmdstanpy are extremely chatty; quiet them to warnings.
logging.getLogger("prophet").setLevel(logging.WARNING)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

MIN_HISTORY = 30          # fewest daily points we'll fit on
_INTEREST_FLOOR, _INTEREST_CEIL = 0.0, 100.0


def load_series(model_slug: str) -> pd.DataFrame:
    """Load the daily trends series as a Prophet-ready (ds, y) frame."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT date, interest FROM trends WHERE model_slug=? ORDER BY date",
            (model_slug,),
        ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    return df.rename(columns={"date": "ds", "interest": "y"}).assign(
        ds=lambda d: pd.to_datetime(d["ds"])
    )


def forecast_model(model_slug: str,
                   horizon: int = config.FORECAST_HORIZON_DAYS) -> pd.DataFrame | None:
    """Fit Prophet and return the clipped forecast frame for the horizon window."""
    from prophet import Prophet  # lazy: cmdstan model load is slow

    df = load_series(model_slug)
    if len(df) < MIN_HISTORY:
        print(f"  ! forecast skipped for {model_slug}: only {len(df)} points")
        return None

    m = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality="auto",   # only engages with >=2 years of history
        interval_width=0.8,
    )
    m.fit(df)
    future = m.make_future_dataframe(periods=horizon, freq="D")  # match daily series
    fc = m.predict(future).tail(horizon)

    cols = ["yhat", "yhat_lower", "yhat_upper"]
    fc[cols] = fc[cols].clip(lower=_INTEREST_FLOOR, upper=_INTEREST_CEIL)
    return fc[["ds", *cols]]


def best_marketing_window(fc: pd.DataFrame) -> dict:
    """Peak predicted-demand day in the horizon — a marketing-timing signal."""
    peak = fc.loc[fc["yhat"].idxmax()]
    return {
        "peak_date": peak.ds.date().isoformat(),
        "peak_yhat": round(float(peak.yhat), 1),
        "start_yhat": round(float(fc["yhat"].iloc[0]), 1),
        "end_yhat": round(float(fc["yhat"].iloc[-1]), 1),
    }


def store(model_slug: str, fc: pd.DataFrame) -> int:
    now = int(time.time())
    rows = [
        {
            "model_slug": model_slug,
            "horizon_date": row.ds.date().isoformat(),
            "yhat": float(row.yhat),
            "yhat_lower": float(row.yhat_lower),
            "yhat_upper": float(row.yhat_upper),
            "generated_at": now,
        }
        for row in fc.itertuples()
    ]
    with connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO forecasts
               (model_slug, horizon_date, yhat, yhat_lower, yhat_upper, generated_at)
               VALUES (:model_slug, :horizon_date, :yhat, :yhat_lower, :yhat_upper,
                       :generated_at)""",
            rows,
        )
    return len(rows)


def run(horizon: int = config.FORECAST_HORIZON_DAYS) -> None:
    for model in models.CATALOG:
        fc = forecast_model(model.slug, horizon=horizon)
        if fc is not None:
            n = store(model.slug, fc)
            win = best_marketing_window(fc)
            print(f"  forecast: {model.slug} -> {n} days "
                  f"(peak {win['peak_yhat']} on {win['peak_date']})")


if __name__ == "__main__":
    from .. import db

    db.init_db()
    run()
