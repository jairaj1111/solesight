"""Resale-price Prophet forecast tests — fits on a small synthetic series (offline)."""
from __future__ import annotations

import time

import pandas as pd
import pytest

from solesight import config, db
from solesight.forecast import prophet_model as pm
from solesight.ingest import resale


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield


def _seed_prices(slug: str, n: int, base: float = 150.0, start="2026-01-01"):
    dates = pd.date_range(start, periods=n, freq="D")
    now = int(time.time())
    with db.connect() as c:
        c.executemany(
            """INSERT INTO resale
                   (model_slug, date, source, last_sale, lowest_ask, sales_count,
                    listing_url, fetched_at)
               VALUES (?,?,'ebay',?,?,?,NULL,?)""",
            [(slug, d.date().isoformat(), base + (i % 5) * 2, base + (i % 5) * 2 + 5,
              3, now) for i, d in enumerate(dates)],
        )


def _seed_trends(slug: str, n: int, start="2026-01-01", values=None):
    dates = pd.date_range(start, periods=n, freq="D")
    vals = values if values is not None else [50 + (i % 10) for i in range(n)]
    now = int(time.time())
    with db.connect() as c:
        c.executemany(
            "INSERT INTO trends (model_slug,date,interest,fetched_at) VALUES (?,?,?,?)",
            [(slug, d.date().isoformat(), float(v), now) for d, v in zip(dates, vals)],
        )


def test_resale_forecast_skips_when_too_little_history_and_no_trends_to_backfill_from():
    _seed_prices("dunk-low-panda", n=10)
    fc, estimated = pm.forecast_resale_model("dunk-low-panda")
    assert fc is None
    assert estimated is False


def test_resale_forecast_returns_horizon_rows_floored_not_capped():
    _seed_prices("dunk-low-panda", n=120)
    fc, estimated = pm.forecast_resale_model("dunk-low-panda", horizon=30)
    assert len(fc) == 30
    assert estimated is False   # plenty of real history, no backfill needed
    # Floored at 0 (a price can't go negative) but never capped, unlike the
    # 0-100-bounded demand index.
    assert fc["yhat_lower"].min() >= 0.0
    assert fc["ds"].min() == pd.Timestamp("2026-05-01")


def test_resale_forecast_ignores_stockx_only_data():
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    now = int(time.time())
    with db.connect() as c:
        c.executemany(
            """INSERT INTO resale
                   (model_slug, date, source, last_sale, lowest_ask, sales_count,
                    listing_url, fetched_at)
               VALUES (?,?,'stockx',?,?,?,NULL,?)""",
            [("dunk-low-panda", d.date().isoformat(), 200.0, 210.0, 2, now) for d in dates],
        )
    fc, estimated = pm.forecast_resale_model("dunk-low-panda", horizon=30)
    assert fc is not None
    assert len(fc) == 30
    assert estimated is False


def test_store_resale_forecast_rows_with_estimated_flag():
    _seed_prices("dunk-low-panda", n=120)
    fc, estimated = pm.forecast_resale_model("dunk-low-panda", horizon=30)
    assert pm.store_resale("dunk-low-panda", fc, estimated=estimated) == 30
    with db.connect() as c:
        rows = c.execute(
            "SELECT estimated FROM resale_forecasts WHERE model_slug='dunk-low-panda'"
        ).fetchall()
    assert len(rows) == 30
    assert all(r["estimated"] == 0 for r in rows)   # real history, not backfilled


def test_resale_forecast_independent_of_demand_forecast_table():
    _seed_prices("dunk-low-panda", n=120)
    fc, estimated = pm.forecast_resale_model("dunk-low-panda", horizon=30)
    pm.store_resale("dunk-low-panda", fc, estimated=estimated)
    with db.connect() as c:
        demand_rows = c.execute(
            "SELECT COUNT(*) FROM forecasts WHERE model_slug='dunk-low-panda'"
        ).fetchone()[0]
    # Storing a resale forecast must never leak into the demand forecasts table.
    assert demand_rows == 0


# --- resale.estimate_backfill() ----------------------------------------------

def test_estimate_backfill_empty_without_any_real_price():
    _seed_trends("dunk-low-panda", n=40)
    assert resale.estimate_backfill("dunk-low-panda").empty


def test_estimate_backfill_empty_without_enough_trends_history():
    _seed_prices("dunk-low-panda", n=1)
    assert resale.estimate_backfill("dunk-low-panda").empty


def test_estimate_backfill_anchors_shape_on_real_trends_and_real_price():
    # Rising search interest into today should shape a rising estimated trend.
    _seed_trends("dunk-low-panda", n=30, values=[20 + i for i in range(30)])
    _seed_prices("dunk-low-panda", n=1, base=200.0, start="2026-01-30")
    est = resale.estimate_backfill("dunk-low-panda", days=29)
    assert len(est) == 29
    assert (est["y"] >= 0).all()
    # Earlier days had lower relative interest -> lower estimated price than
    # the anchor, since the trend was rising into today.
    assert est["y"].iloc[0] < est["y"].iloc[-1]


def test_resale_forecast_uses_backfill_and_flags_it_when_real_history_is_thin():
    # 15 real price days (< MIN_HISTORY) but 45 real days of Trends history —
    # enough for estimate_backfill to top the series up past the 30-day bar.
    _seed_trends("dunk-low-panda", n=45, start="2025-12-17")
    _seed_prices("dunk-low-panda", n=15, base=180.0, start="2026-01-16")
    fc, estimated = pm.forecast_resale_model("dunk-low-panda", horizon=30)
    assert fc is not None
    assert estimated is True
    n = pm.store_resale("dunk-low-panda", fc, estimated=estimated)
    with db.connect() as c:
        rows = c.execute(
            "SELECT estimated FROM resale_forecasts WHERE model_slug='dunk-low-panda'"
        ).fetchall()
    assert n == 30
    assert all(r["estimated"] == 1 for r in rows)


def test_estimate_backed_forecast_is_bounded_near_todays_real_anchor():
    # A short, mostly-modeled series gives Prophet's linear trend very little
    # to anchor on and it can otherwise extrapolate wildly (e.g. a $180 shoe
    # "predicted" near $0 or several multiples up) — the estimate-backed path
    # must stay within a sane band of today's real price, unlike a genuine
    # real-data forecast which is free to call a real breakout.
    _seed_trends("dunk-low-panda", n=45, start="2025-12-17",
                 values=[5 + i * 3 for i in range(45)])  # sharp synthetic runup
    _seed_prices("dunk-low-panda", n=15, base=180.0, start="2026-01-16")
    fc, estimated = pm.forecast_resale_model("dunk-low-panda", horizon=30)
    assert estimated is True
    anchor = 180.0 + (14 % 5) * 2   # last seeded price (see _seed_prices)
    assert fc["yhat"].min() >= anchor * 0.6 - 0.01
    assert fc["yhat"].max() <= anchor * 1.6 + 0.01
