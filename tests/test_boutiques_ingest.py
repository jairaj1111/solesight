"""Boutique availability ingestion tests — no network; a fake Shopify feed."""
from __future__ import annotations

import pytest

from solesight import config, db
from solesight.ingest import boutiques


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield


def _product(handle, total=5, available=3, price="150.00", with_handle=True):
    variants = [{"available": True, "price": price} for _ in range(available)]
    variants += [{"available": False, "price": price} for _ in range(total - available)]
    p = {"title": "Nike Dunk Low Panda", "vendor": "Nike", "variants": variants}
    if with_handle:
        p["handle"] = handle
    return p


def test_match_rows_builds_real_product_url():
    rows = boutiques._match_rows("kith.com", [_product("nkdl-panda-001")], now=123)
    row = next(r for r in rows if r["model_slug"] == "dunk-low-panda")
    assert row["url"] == "https://kith.com/products/nkdl-panda-001"
    assert row["variants_total"] == 5
    assert row["variants_available"] == 3


def test_match_rows_missing_handle_yields_none_url():
    products = [_product("unused", with_handle=False)]
    rows = boutiques._match_rows("kith.com", products, now=123)
    row = next(r for r in rows if r["model_slug"] == "dunk-low-panda")
    assert row["url"] is None


def test_match_rows_prefers_listing_with_most_sizes():
    products = [_product("small-drop", total=2, available=1),
                _product("full-run", total=10, available=4)]
    rows = boutiques._match_rows("kith.com", products, now=123)
    row = next(r for r in rows if r["model_slug"] == "dunk-low-panda")
    # The GR listing (most sizes) wins over a smaller/limited drop.
    assert row["url"] == "https://kith.com/products/full-run"
    assert row["variants_total"] == 10


def test_match_rows_skips_products_with_no_variants():
    products = [{"title": "Nike Dunk Low Panda", "vendor": "Nike", "handle": "empty",
                 "variants": []}]
    rows = boutiques._match_rows("kith.com", products, now=123)
    assert not any(r["model_slug"] == "dunk-low-panda" for r in rows)


def test_store_rows_persists_and_updates_url_on_reingest():
    rows = [{"model_slug": "dunk-low-panda", "date": "2026-01-01", "store": "kith.com",
              "price": 150.0, "variants_total": 5, "variants_available": 3,
              "url": "https://kith.com/products/v1", "fetched_at": 1}]
    assert boutiques.store_rows(rows) == 1
    with db.connect() as conn:
        row = conn.execute(
            "SELECT url FROM availability WHERE model_slug='dunk-low-panda'").fetchone()
    assert row["url"] == "https://kith.com/products/v1"

    # Store swapped which listing is the GR (most sizes) overnight.
    rows[0].update(url="https://kith.com/products/v2", variants_available=1)
    boutiques.store_rows(rows)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT url, variants_available FROM availability "
            "WHERE model_slug='dunk-low-panda'").fetchone()
    assert row["url"] == "https://kith.com/products/v2"
    assert row["variants_available"] == 1
