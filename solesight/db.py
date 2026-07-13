"""SQLite storage layer.

One tiny wrapper around the stdlib sqlite3 module. We keep the schema narrow and
denormalized: raw signals land in `reddit_posts` and `trends` verbatim, sentiment
scores attach to posts, and Prophet forecasts are cached in `forecasts`.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS reddit_posts (
    id            TEXT NOT NULL,          -- reddit post id
    model_slug    TEXT NOT NULL,          -- a post can match multiple models
    subreddit     TEXT NOT NULL,
    title         TEXT,
    body          TEXT,
    score         INTEGER,
    num_comments  INTEGER,
    created_utc   INTEGER NOT NULL,       -- unix seconds
    sentiment     REAL,                   -- signed [-1, 1], NULL until scored
    sentiment_label TEXT,                 -- positive / neutral / negative
    fetched_at    INTEGER NOT NULL,
    PRIMARY KEY (id, model_slug)
);
CREATE INDEX IF NOT EXISTS idx_reddit_model_time
    ON reddit_posts (model_slug, created_utc);

CREATE TABLE IF NOT EXISTS trends (
    model_slug    TEXT NOT NULL,
    date          TEXT NOT NULL,          -- ISO date (daily)
    interest      REAL NOT NULL,          -- 0-100 Google Trends index
    fetched_at    INTEGER NOT NULL,
    PRIMARY KEY (model_slug, date)
);

CREATE TABLE IF NOT EXISTS forecasts (
    model_slug    TEXT NOT NULL,
    horizon_date  TEXT NOT NULL,          -- ISO date being predicted
    yhat          REAL NOT NULL,          -- predicted demand signal
    yhat_lower    REAL,
    yhat_upper    REAL,
    generated_at  INTEGER NOT NULL,
    PRIMARY KEY (model_slug, horizon_date, generated_at)
);

CREATE TABLE IF NOT EXISTS insights (
    model_slug    TEXT NOT NULL,
    generated_at  INTEGER NOT NULL,
    summary       TEXT NOT NULL,          -- plain-English recommendation (LLM)
    PRIMARY KEY (model_slug, generated_at)
);

CREATE TABLE IF NOT EXISTS social (
    model_slug    TEXT NOT NULL,
    date          TEXT NOT NULL,          -- ISO date (daily)
    platform      TEXT NOT NULL,          -- instagram / tiktok / youtube
    posts         INTEGER NOT NULL,       -- mentions/videos that day
    engagement    INTEGER NOT NULL,       -- likes + comments + views proxy
    fetched_at    INTEGER NOT NULL,
    PRIMARY KEY (model_slug, date, platform)
);
CREATE INDEX IF NOT EXISTS idx_social_model_time
    ON social (model_slug, date);

CREATE TABLE IF NOT EXISTS attention (
    model_slug    TEXT NOT NULL,
    date          TEXT NOT NULL,          -- ISO date (daily)
    source        TEXT NOT NULL,          -- wikipedia (article-level views)
    views         INTEGER NOT NULL,
    fetched_at    INTEGER NOT NULL,
    PRIMARY KEY (model_slug, date, source)
);

CREATE TABLE IF NOT EXISTS availability (
    model_slug    TEXT NOT NULL,
    date          TEXT NOT NULL,          -- ISO date (daily)
    store         TEXT NOT NULL,          -- boutique domain
    price         REAL,                   -- current ask (USD)
    variants_total     INTEGER NOT NULL,  -- sizes listed
    variants_available INTEGER NOT NULL,  -- sizes in stock
    fetched_at    INTEGER NOT NULL,
    PRIMARY KEY (model_slug, date, store)
);

CREATE TABLE IF NOT EXISTS resale (
    model_slug    TEXT NOT NULL,
    date          TEXT NOT NULL,          -- ISO date (daily)
    source        TEXT NOT NULL,          -- stockx / ebay
    last_sale     REAL NOT NULL,          -- avg sale price that day (USD)
    lowest_ask    REAL,                   -- lowest ask / active listing (USD)
    sales_count   INTEGER NOT NULL,       -- sales that day
    fetched_at    INTEGER NOT NULL,
    PRIMARY KEY (model_slug, date, source)
);
CREATE INDEX IF NOT EXISTS idx_resale_model_time
    ON resale (model_slug, date);

CREATE TABLE IF NOT EXISTS hype_history (
    model_slug    TEXT NOT NULL,
    date          TEXT NOT NULL,          -- ISO date the snapshot was taken
    hype          REAL NOT NULL,          -- composite 0-100 Hype Score that day
    PRIMARY KEY (model_slug, date)
);
"""


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a connection with row access by column name; commits on clean exit."""
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Create all tables if they don't exist."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
