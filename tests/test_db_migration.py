"""Schema migration tests — new columns land on pre-existing tables in place."""
from __future__ import annotations

import sqlite3

from solesight import config, db


def test_migrate_adds_missing_columns_to_legacy_table(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    # Simulate a pre-migration DB: resale/availability without the newer columns.
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE resale (
        model_slug TEXT, date TEXT, source TEXT, last_sale REAL,
        lowest_ask REAL, sales_count INTEGER, fetched_at INTEGER,
        PRIMARY KEY (model_slug, date, source))""")
    conn.execute("""CREATE TABLE availability (
        model_slug TEXT, date TEXT, store TEXT, price REAL,
        variants_total INTEGER, variants_available INTEGER, fetched_at INTEGER,
        PRIMARY KEY (model_slug, date, store))""")
    conn.execute("INSERT INTO resale VALUES ('slug','2026-01-01','ebay',100,90,5,1)")
    conn.commit()
    conn.close()

    db.init_db(path)

    with db.connect(path) as c:
        assert "listing_url" in {r["name"] for r in c.execute("PRAGMA table_info(resale)")}
        assert "url" in {r["name"] for r in c.execute("PRAGMA table_info(availability)")}
        # Pre-existing row survives the migration; the new column is just NULL.
        row = c.execute(
            "SELECT listing_url FROM resale WHERE model_slug='slug'").fetchone()
        assert row["listing_url"] is None


def test_migrate_is_idempotent_across_repeated_runs(tmp_path, monkeypatch):
    path = tmp_path / "fresh.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init_db(path)
    db.init_db(path)  # must not raise "duplicate column name" the second time
    db.init_db(path)
    with db.connect(path) as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(resale)")}
        assert "listing_url" in cols


def test_fresh_db_already_has_migrated_columns(tmp_path, monkeypatch):
    """A brand-new DB gets the columns straight from SCHEMA, no ALTER needed."""
    path = tmp_path / "brandnew.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init_db(path)
    with db.connect(path) as c:
        assert "listing_url" in {r["name"] for r in c.execute("PRAGMA table_info(resale)")}
        assert "url" in {r["name"] for r in c.execute("PRAGMA table_info(availability)")}
