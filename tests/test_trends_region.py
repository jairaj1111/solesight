"""Google Trends regional-breakdown tests — no network; a fake pytrends client."""
from __future__ import annotations

import pandas as pd
import pytest

from solesight import config, db, models
from solesight.ingest import google_trends


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield


def _model():
    return models.SneakerModel(slug="aj1-chicago", name="Air Jordan 1 Chicago",
                                brand="Jordan", trends_term="Jordan 1 Chicago")


class _FakePytrends:
    def __init__(self, df):
        self._df = df
        self.build_payload_calls: list[dict] = []

    def build_payload(self, *a, **kw):
        self.build_payload_calls.append(kw)

    def interest_by_region(self, *a, **kw):
        return self._df


def test_fetch_model_region_sorts_and_trims_to_top_n(monkeypatch):
    df = pd.DataFrame(
        {"Jordan 1 Chicago": [10, 90, 0, 40, 5, 60, 30, 20, 15, 1]},
        index=["Alabama", "New York", "Wyoming", "Texas", "Utah",
               "California", "Illinois", "Ohio", "Georgia", "Maine"])
    rows = google_trends.fetch_model_region(_FakePytrends(df), _model(), "today 1-m")
    assert len(rows) == google_trends._REGION_TOP_N
    assert rows[0]["region"] == "New York"
    assert rows[0]["interest"] == 90.0
    assert all(r["interest"] > 0 for r in rows)  # zero-interest state dropped


def test_fetch_model_region_empty_when_term_missing():
    df = pd.DataFrame({"Some Other Term": [10]}, index=["Texas"])
    rows = google_trends.fetch_model_region(_FakePytrends(df), _model(), "today 1-m")
    assert rows == []


def test_store_region_persists_and_top_regions_reads_latest_day():
    rows = [
        {"model_slug": "aj1-chicago", "date": "2026-07-01", "region": "New York",
         "interest": 90.0, "fetched_at": 1},
        {"model_slug": "aj1-chicago", "date": "2026-07-01", "region": "Texas",
         "interest": 40.0, "fetched_at": 1},
        {"model_slug": "aj1-chicago", "date": "2026-06-01", "region": "Ohio",
         "interest": 99.0, "fetched_at": 0},
    ]
    assert google_trends.store_region(rows) == 3
    top = google_trends.top_regions("aj1-chicago", limit=5)
    assert [r["region"] for r in top] == ["New York", "Texas"]  # stale day excluded
    assert top[0]["interest"] == 90


def test_store_region_upserts_on_conflict():
    row = {"model_slug": "aj1-chicago", "date": "2026-07-01", "region": "New York",
           "interest": 50.0, "fetched_at": 1}
    google_trends.store_region([row])
    updated = dict(row, interest=75.0, fetched_at=2)
    google_trends.store_region([updated])
    top = google_trends.top_regions("aj1-chicago")
    assert len(top) == 1
    assert top[0]["interest"] == 75


def test_store_region_noop_on_empty_list():
    assert google_trends.store_region([]) == 0


def test_top_regions_empty_for_unknown_model():
    assert google_trends.top_regions("nonexistent-slug") == []


def test_fetch_model_region_defaults_to_30_days_not_the_daily_series_window():
    # The UI caption says "last 30 days" — the actual query must match that,
    # not silently inherit the daily series' ~269-day default (which would
    # blend 9 months of history into what's supposed to read as recent).
    import datetime
    df = pd.DataFrame({"Jordan 1 Chicago": [50]}, index=["Illinois"])
    fake = _FakePytrends(df)
    google_trends.fetch_model_region(fake, _model())   # no explicit timeframe
    assert len(fake.build_payload_calls) == 1
    start_s, end_s = fake.build_payload_calls[0]["timeframe"].split()
    span = (datetime.date.fromisoformat(end_s) - datetime.date.fromisoformat(start_s)).days
    assert span == google_trends._REGION_LOOKBACK_DAYS
