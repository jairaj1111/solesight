"""Prophet forecasting — demand (search interest) and resale price.

Two series are forecast today, both daily and both fit independently per model
(magnitudes are never compared across models):

  * Demand — the Google Trends interest index, bounded [0, 100], so its forecast
    (incl. intervals) is clipped into that range; a raw linear trend can otherwise
    drift negative or above 100.
  * Resale price — the blended home-market (StockX + eBay) daily price in USD,
    floored at 0 (a price can't go negative) but with no ceiling, since resale
    prices can run well past any sensible preset cap.

Reddit buzz/sentiment are surfaced separately today and are the natural next
regressors once we've backfilled enough of their daily history.
"""
from __future__ import annotations

import logging
import time

import pandas as pd

from .. import config, models
from ..db import connect
from ..ingest import resale

# Prophet + cmdstanpy are extremely chatty; quiet them to warnings.
logging.getLogger("prophet").setLevel(logging.WARNING)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

MIN_HISTORY = 30          # fewest daily points we'll fit on
_INTEREST_FLOOR, _INTEREST_CEIL = 0.0, 100.0
_PRICE_FLOOR = 0.0        # resale price forecast: no upper clip


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


def load_resale_series(model_slug: str) -> pd.DataFrame:
    """Load the blended daily resale-price series as a Prophet-ready (ds, y) frame."""
    df = resale.daily_price(model_slug)
    if df.empty:
        return pd.DataFrame(columns=["ds", "y"])
    return df.rename(columns={"date": "ds", "last_sale": "y"})[["ds", "y"]]


def _fit_forecast(df: pd.DataFrame, horizon: int,
                  floor: float | None, ceil: float | None) -> pd.DataFrame | None:
    """Fit Prophet on a (ds, y) frame and return the clipped forecast window."""
    from prophet import Prophet  # lazy: cmdstan model load is slow

    if len(df) < MIN_HISTORY:
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
    if floor is not None or ceil is not None:
        fc[cols] = fc[cols].clip(lower=floor, upper=ceil)
    return fc[["ds", *cols]]


def forecast_model(model_slug: str,
                   horizon: int = config.FORECAST_HORIZON_DAYS) -> pd.DataFrame | None:
    """Fit Prophet on demand (search interest) and return the forecast window."""
    df = load_series(model_slug)
    fc = _fit_forecast(df, horizon, _INTEREST_FLOOR, _INTEREST_CEIL)
    if fc is None:
        print(f"  ! forecast skipped for {model_slug}: only {len(df)} points")
    return fc


def forecast_resale_model(model_slug: str,
                          horizon: int = config.FORECAST_HORIZON_DAYS) -> pd.DataFrame | None:
    """Fit Prophet on the blended resale-price series and return the forecast window."""
    df = load_resale_series(model_slug)
    fc = _fit_forecast(df, horizon, _PRICE_FLOOR, None)
    if fc is None:
        print(f"  ! resale forecast skipped for {model_slug}: only {len(df)} points")
    return fc


def best_marketing_window(fc: pd.DataFrame) -> dict:
    """Peak predicted-demand day in the horizon — a marketing-timing signal."""
    peak = fc.loc[fc["yhat"].idxmax()]
    return {
        "peak_date": peak.ds.date().isoformat(),
        "peak_yhat": round(float(peak.yhat), 1),
        "start_yhat": round(float(fc["yhat"].iloc[0]), 1),
        "end_yhat": round(float(fc["yhat"].iloc[-1]), 1),
    }


def _forecast_rows(model_slug: str, fc: pd.DataFrame, now: int) -> list[dict]:
    return [
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


def store(model_slug: str, fc: pd.DataFrame) -> int:
    rows = _forecast_rows(model_slug, fc, int(time.time()))
    with connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO forecasts
               (model_slug, horizon_date, yhat, yhat_lower, yhat_upper, generated_at)
               VALUES (:model_slug, :horizon_date, :yhat, :yhat_lower, :yhat_upper,
                       :generated_at)""",
            rows,
        )
    return len(rows)


def store_resale(model_slug: str, fc: pd.DataFrame) -> int:
    rows = _forecast_rows(model_slug, fc, int(time.time()))
    with connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO resale_forecasts
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

        # Resale-price forecasting is newer and leans on a thinner, spottier
        # daily series (eBay-only today, 1 row/day with no backfill) than the
        # demand forecast above — its own try/except so a rough fit here never
        # costs a model its (more mature) demand forecast for the night.
        try:
            rfc = forecast_resale_model(model.slug, horizon=horizon)
        except Exception as exc:
            rfc = None
            print(f"  ! resale forecast failed for {model.slug}: {str(exc)[:60]}")
        if rfc is not None:
            rn = store_resale(model.slug, rfc)
            print(f"  resale forecast: {model.slug} -> {rn} days "
                  f"(predicted ${rfc['yhat'].iloc[-1]:.0f} in {horizon}d)")


if __name__ == "__main__":
    from .. import db

    db.init_db()
    run()
