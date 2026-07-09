"""Google Trends ingestion tests — no network; a fake TrendReq returns a frame."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from solesight import config, db, models
from solesight.ingest import google_trends as gt


class FakeTrends:
    """Stands in for pytrends.TrendReq; returns a canned interest frame."""

    def __init__(self, frame: pd.DataFrame):
        self._frame = frame

    def build_payload(self, kw_list, timeframe=None):  # noqa: D401
        self._kw = kw_list

    def interest_over_time(self) -> pd.DataFrame:
        return self._frame


def _daily_frame(term: str, values: list[int], partial_last: bool) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(values), freq="D")
    partial = [False] * len(values)
    if partial_last:
        partial[-1] = True
    return pd.DataFrame({term: values, "isPartial": partial}, index=idx)


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield


def test_default_timeframe_stays_under_daily_threshold():
    tf = gt.default_timeframe()
    start_s, end_s = tf.split(" ")
    span = (date.fromisoformat(end_s) - date.fromisoformat(start_s)).days
    assert span < 270, "window must stay under Google's daily-resolution cutoff"


def test_fetch_drops_partial_trailing_day():
    model = models.get("dunk-low-panda")
    frame = _daily_frame(model.trends_term, [10, 20, 30, 99], partial_last=True)
    rows = gt.fetch_model(FakeTrends(frame), model)
    assert len(rows) == 3                       # partial last day dropped
    assert rows[-1]["interest"] == 30.0         # not the misleading 99
    assert all(r["model_slug"] == "dunk-low-panda" for r in rows)


def test_fetch_empty_frame_returns_empty():
    model = models.get("dunk-low-panda")
    assert gt.fetch_model(FakeTrends(pd.DataFrame()), model) == []


def test_store_upsert_overwrites_same_day():
    rows = [{"model_slug": "dunk-low-panda", "date": "2026-01-01",
             "interest": 10.0, "fetched_at": 1}]
    assert gt.store(rows) == 1
    rows[0].update(interest=55.0, fetched_at=2)
    gt.store(rows)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT interest, fetched_at FROM trends WHERE model_slug='dunk-low-panda'"
        ).fetchone()
    assert row["interest"] == 55.0 and row["fetched_at"] == 2
