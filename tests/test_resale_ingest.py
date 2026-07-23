"""eBay resale ingestion tests — no network; a fake urlopen stands in."""
from __future__ import annotations

import json
import urllib.request

import pytest

from solesight import config, db, models
from solesight.ingest import resale


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    resale._token_cache.clear()
    resale._fx_cache.clear()
    yield


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _items(prices_and_urls):
    return {"itemSummaries": [
        {"price": {"value": str(p)}, "itemWebUrl": u} for p, u in prices_and_urls
    ]}


def _fake_urlopen_factory(search_payload, fx_rate=None):
    def _fake_urlopen(req, timeout=None):
        url = req.full_url
        if "oauth2/token" in url:
            return FakeResponse({"access_token": "tok", "expires_in": 7200})
        if "frankfurter" in url or "open.er-api" in url:
            return FakeResponse({"rates": {"USD": fx_rate}})
        return FakeResponse(search_payload)
    return _fake_urlopen


# 5 listings so the decile trim (k=1) drops exactly the top and bottom as
# outliers — matches the real trim behavior instead of assuming raw min.
_LISTINGS = [(90, "https://ebay.com/itm/90"), (100, "https://ebay.com/itm/100"),
             (110, "https://ebay.com/itm/110"), (120, "https://ebay.com/itm/120"),
             (600, "https://ebay.com/itm/600")]


def test_fetch_ebay_captures_lowest_ask_listing_url(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                         _fake_urlopen_factory(_items(_LISTINGS)))
    row = resale._fetch_ebay(models.CATALOG[0])
    assert row is not None
    # 90 and 600 are trimmed as outliers; 100 becomes the reported lowest ask.
    assert row["lowest_ask"] == 100.0
    assert row["listing_url"] == "https://ebay.com/itm/100"
    assert row["last_sale"] == 110.0  # median of the trimmed core [100, 110, 120]


def test_fetch_ebay_too_few_listings_returns_none(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_factory(
        _items([(100, "u1"), (120, "u2")])))
    assert resale._fetch_ebay(models.CATALOG[0]) is None


def test_fetch_ebay_region_converts_to_usd_and_keeps_listing_url(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                         _fake_urlopen_factory(_items(_LISTINGS), fx_rate=1.25))
    row = resale._fetch_ebay_region(models.CATALOG[0], "EBAY_GB", "GBP", "ebay_gb")
    assert row is not None
    assert row["listing_url"] == "https://ebay.com/itm/100"
    assert row["lowest_ask"] == pytest.approx(100 * 1.25)
    assert row["source"] == "ebay_gb"


def test_fetch_ebay_region_returns_none_when_fx_unavailable(monkeypatch):
    def _fake_urlopen(req, timeout=None):
        url = req.full_url
        if "oauth2/token" in url:
            return FakeResponse({"access_token": "tok", "expires_in": 7200})
        if "item_summary" in url:
            return FakeResponse(_items(_LISTINGS))
        raise OSError("network down")  # both FX sources fail
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    assert resale._fetch_ebay_region(models.CATALOG[0], "EBAY_GB", "GBP", "ebay_gb") is None


def test_store_persists_listing_url_and_upserts_on_reingest():
    rows = [{"model_slug": "dunk-low-panda", "date": "2026-01-01", "source": "ebay",
              "last_sale": 150.0, "lowest_ask": 140.0, "sales_count": 10,
              "listing_url": "https://ebay.com/itm/140", "fetched_at": 1}]
    assert resale.store(rows) == 1
    with db.connect() as conn:
        row = conn.execute(
            "SELECT listing_url FROM resale WHERE model_slug='dunk-low-panda'").fetchone()
    assert row["listing_url"] == "https://ebay.com/itm/140"

    # Price moved overnight; the new cheapest listing's URL must replace the old one.
    rows[0].update(lowest_ask=130.0, listing_url="https://ebay.com/itm/130")
    resale.store(rows)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT listing_url, lowest_ask FROM resale WHERE model_slug='dunk-low-panda'"
        ).fetchone()
    assert row["listing_url"] == "https://ebay.com/itm/130"
    assert row["lowest_ask"] == 130.0


def test_store_defaults_listing_url_when_caller_omits_it():
    """scripts/seed_demo.py builds rows without a listing_url key — must not KeyError."""
    rows = [{"model_slug": "dunk-low-panda", "date": "2026-01-01", "source": "stockx",
              "last_sale": 150.0, "lowest_ask": 140.0, "sales_count": 10, "fetched_at": 1}]
    assert resale.store(rows) == 1
    with db.connect() as conn:
        row = conn.execute(
            "SELECT listing_url FROM resale WHERE model_slug='dunk-low-panda'").fetchone()
    assert row["listing_url"] is None
