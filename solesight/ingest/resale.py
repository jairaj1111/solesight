"""Resale-market ingestion + helpers (StockX / eBay).

Resale price *is* demand for sneakers: the premium a pair commands over retail
is the cleanest monetary read on hype. We store, per model per day per source,
the average sale price, lowest ask, and number of sales. Derived downstream:
the **resale premium** = last sale ÷ retail MSRP (`models.retail`).

Live ingestion:
  * eBay    — real free API (Browse + Marketplace Insights `getItemSalesReport`)
              gives sold prices and volume; needs an app id (`EBAY_APP_ID`).
  * StockX  — no free public API; the partner API needs approval. Stub for now.

Until the adapters are wired, populate this table with `python -m scripts.seed_demo`.
The storage + `daily_price()` helpers are the reusable core read by
`signals.snapshot()` and the dashboard.
"""
from __future__ import annotations

import pandas as pd

from .. import config
from ..db import connect


def store(rows: list[dict]) -> int:
    """Upsert per-(model, date, source) resale rows."""
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """INSERT INTO resale
                   (model_slug, date, source, last_sale, lowest_ask, sales_count,
                    fetched_at)
               VALUES (:model_slug, :date, :source, :last_sale, :lowest_ask,
                       :sales_count, :fetched_at)
               ON CONFLICT(model_slug, date, source) DO UPDATE SET
                   last_sale   = excluded.last_sale,
                   lowest_ask  = excluded.lowest_ask,
                   sales_count = excluded.sales_count,
                   fetched_at  = excluded.fetched_at""",
            rows,
        )
    return len(rows)


def load(model_slug: str) -> pd.DataFrame:
    """Raw daily rows (date, source, last_sale, lowest_ask, sales_count)."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT date, source, last_sale, lowest_ask, sales_count FROM resale
               WHERE model_slug=? ORDER BY date""",
            (model_slug,)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def daily_price(model_slug: str) -> pd.DataFrame:
    """Blended daily series across sources: mean last_sale, summed sales_count."""
    df = load(model_slug)
    if df.empty:
        return pd.DataFrame(columns=["date", "last_sale", "sales_count"])
    return (df.groupby("date", as_index=False)
              .agg(last_sale=("last_sale", "mean"),
                   sales_count=("sales_count", "sum"))
              .sort_values("date"))


# --- Live ingestion adapters (not wired yet) --------------------------------
def _fetch_ebay(model, timeframe):    # pragma: no cover - stub
    raise NotImplementedError("wire the eBay Browse/Marketplace Insights API here")


def _fetch_stockx(model, timeframe):  # pragma: no cover - stub
    raise NotImplementedError("wire the StockX partner API here")


_ADAPTERS = {"ebay": _fetch_ebay, "stockx": _fetch_stockx}


def run() -> None:
    """Live ingestion entry point — not wired yet.

    Implement the `_fetch_*` adapters (each gated on its config token) and store
    their rows via `store()`. Until then, use `python -m scripts.seed_demo`.
    """
    raise NotImplementedError(
        "Live resale ingestion isn't wired. Implement the _fetch_* adapters in "
        "solesight/ingest/resale.py, or run `python -m scripts.seed_demo` for "
        "offline demo resale data."
    )


if __name__ == "__main__":
    run()
