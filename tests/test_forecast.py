"""Prophet forecast tests — fits on a small synthetic series (offline)."""
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


def _seed_series(slug: str, n: int, values=None):
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    vals = values if values is not None else [50 + (i % 7) for i in range(n)]
    now = int(time.time())
    with db.connect() as c:
        c.executemany(
            "INSERT INTO trends (model_slug,date,interest,fetched_at) VALUES (?,?,?,?)",
            [(slug, d.date().isoformat(), float(v), now) for d, v in zip(dates, vals)],
        )


def test_forecast_skips_when_too_little_history():
    _seed_series("dunk-low-panda", n=10)
    assert pm.forecast_model("dunk-low-panda") is None


def test_forecast_returns_horizon_rows_clipped():
    _seed_series("dunk-low-panda", n=120)
    fc = pm.forecast_model("dunk-low-panda", horizon=30)
    assert len(fc) == 30
    # Clipping keeps the bounded 0-100 index in range.
    assert fc["yhat_lower"].min() >= 0.0
    assert fc["yhat_upper"].max() <= 100.0
    # Forecast starts the day after the last observed date.
    assert fc["ds"].min() == pd.Timestamp("2026-05-01")


def test_best_marketing_window_reports_peak():
    _seed_series("dunk-low-panda", n=120)
    fc = pm.forecast_model("dunk-low-panda", horizon=30)
    win = pm.best_marketing_window(fc)
    assert set(win) == {"peak_date", "peak_yhat", "start_yhat", "end_yhat"}
    assert win["peak_yhat"] >= win["start_yhat"] or win["peak_yhat"] >= win["end_yhat"]


def test_store_forecast_rows():
    _seed_series("dunk-low-panda", n=120)
    fc = pm.forecast_model("dunk-low-panda", horizon=30)
    assert pm.store("dunk-low-panda", fc) == 30
    with db.connect() as c:
        n = c.execute("SELECT COUNT(*) FROM forecasts WHERE model_slug='dunk-low-panda'"
                      ).fetchone()[0]
    assert n == 30
