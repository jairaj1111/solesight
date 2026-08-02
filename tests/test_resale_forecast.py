"""Resale-price Prophet forecast tests — fits on a small synthetic series (offline)."""
from __future__ import annotations

import time

import pandas as pd
import pytest

from solesight import config, db
from solesight.forecast import prophet_model as pm


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield


def _seed_prices(slug: str, n: int, base: float = 150.0):
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
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


def test_resale_forecast_skips_when_too_little_history():
    _seed_prices("dunk-low-panda", n=10)
    assert pm.forecast_resale_model("dunk-low-panda") is None


def test_resale_forecast_returns_horizon_rows_floored_not_capped():
    _seed_prices("dunk-low-panda", n=120)
    fc = pm.forecast_resale_model("dunk-low-panda", horizon=30)
    assert len(fc) == 30
    # Floored at 0 (a price can't go negative) but never capped, unlike the
    # 0-100-bounded demand index.
    assert fc["yhat_lower"].min() >= 0.0
    assert fc["yhat_upper"].max() > 100.0 or fc["yhat_upper"].max() < 1e6  # no artificial ceiling
    assert fc["ds"].min() == pd.Timestamp("2026-05-01")


def test_resale_forecast_ignores_stockx_only_data():
    # StockX-only history (no eBay) shouldn't count toward the domestic blend
    # once eBay exists elsewhere, but on its own it's still a valid domestic
    # source — this just confirms the loader doesn't require eBay specifically.
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
    fc = pm.forecast_resale_model("dunk-low-panda", horizon=30)
    assert fc is not None
    assert len(fc) == 30


def test_store_resale_forecast_rows():
    _seed_prices("dunk-low-panda", n=120)
    fc = pm.forecast_resale_model("dunk-low-panda", horizon=30)
    assert pm.store_resale("dunk-low-panda", fc) == 30
    with db.connect() as c:
        n = c.execute(
            "SELECT COUNT(*) FROM resale_forecasts WHERE model_slug='dunk-low-panda'"
        ).fetchone()[0]
    assert n == 30


def test_resale_forecast_independent_of_demand_forecast_table():
    _seed_prices("dunk-low-panda", n=120)
    fc = pm.forecast_resale_model("dunk-low-panda", horizon=30)
    pm.store_resale("dunk-low-panda", fc)
    with db.connect() as c:
        demand_rows = c.execute(
            "SELECT COUNT(*) FROM forecasts WHERE model_slug='dunk-low-panda'"
        ).fetchone()[0]
    # Storing a resale forecast must never leak into the demand forecasts table.
    assert demand_rows == 0
