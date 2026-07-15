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


def load(model_slug: str, real_only_if_available: bool = True) -> pd.DataFrame:
    """Raw daily rows (date, source, last_sale, lowest_ask, sales_count).

    The moment a model has ANY real rows, seeded demo rows are excluded — a
    synthetic StockX price must never blend into (or chart next to) a real eBay
    ask. In a pure-demo database (no real rows anywhere) seeded rows still
    serve, so the offline workflow keeps working.
    """
    with connect() as conn:
        rows = conn.execute(
            """SELECT date, source, last_sale, lowest_ask, sales_count,
                      fetched_at FROM resale
               WHERE model_slug=? ORDER BY date""",
            (model_slug,)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        if real_only_if_available and (df["fetched_at"] != config.SEED_TAG).any():
            df = df[df["fetched_at"] != config.SEED_TAG]
        df = df.drop(columns=["fetched_at"])
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


# --- eBay Browse API (live) --------------------------------------------------
# Free developer keyset from developer.ebay.com. The Browse API returns ACTIVE
# listings, so eBay rows are ask-side: `last_sale` holds the median asking price
# (documented proxy until Marketplace Insights sold-data access is granted),
# `lowest_ask` the cheapest listing, `sales_count` the listing count.
_EBAY_OAUTH = "https://api.ebay.com/identity/v1/oauth2/token"
_EBAY_SEARCH = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_EBAY_CATEGORY = "15709"          # Athletic Shoes
_token_cache: dict = {}


def _ebay_token() -> str:
    """Client-credentials token, cached until near expiry."""
    import base64
    import json
    import time as _time
    import urllib.parse
    import urllib.request

    if _token_cache.get("exp", 0) > _time.time() + 60:
        return _token_cache["tok"]
    basic = base64.b64encode(
        f"{config.EBAY_CLIENT_ID}:{config.EBAY_CLIENT_SECRET}".encode()).decode()
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }).encode()
    req = urllib.request.Request(_EBAY_OAUTH, data=body, headers={
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read())
    _token_cache.update(tok=payload["access_token"],
                        exp=_time.time() + int(payload.get("expires_in", 7200)))
    return _token_cache["tok"]


def _fetch_ebay(model) -> dict | None:
    """One ask-side daily row for `model` from live eBay listings, or None."""
    import json
    import statistics
    import time as _time
    import urllib.parse
    import urllib.request

    from datetime import date as _date

    # conditionIds 1000 = "New" (with box, unworn) — eBay's deadstock. Used
    # pairs would otherwise drag the median below what the market asks for DS.
    query = urllib.parse.urlencode({
        "q": model.trends_term,
        "category_ids": _EBAY_CATEGORY,
        "limit": "50",
        "filter": "buyingOptions:{FIXED_PRICE},priceCurrency:USD,"
                  "conditionIds:{1000}",
    })
    req = urllib.request.Request(f"{_EBAY_SEARCH}?{query}", headers={
        "Authorization": f"Bearer {_ebay_token()}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    })
    with urllib.request.urlopen(req, timeout=25) as resp:
        items = json.loads(resp.read()).get("itemSummaries", [])
    prices = sorted(float(i["price"]["value"]) for i in items
                    if i.get("price", {}).get("value"))
    if len(prices) < 3:          # too thin to be a signal
        return None
    # Trim the top/bottom decile: fakes, kids' sizes and typo listings live there.
    k = max(1, len(prices) // 10)
    core = prices[k:-k] or prices
    return {
        "model_slug": model.slug,
        "date": _date.today().isoformat(),
        "source": "ebay",
        "last_sale": round(statistics.median(core), 2),
        "lowest_ask": round(core[0], 2),
        "sales_count": len(prices),
        "fetched_at": int(_time.time()),
    }


def _purge_seeded(source: str) -> int:
    """Drop synthetic rows for `source` once real data is flowing."""
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM resale WHERE source=? AND fetched_at=?",
            (source, config.SEED_TAG))
    return cur.rowcount


def run() -> None:
    """Ingest live resale data from every source with credentials configured."""
    import time as _time

    if not (config.EBAY_CLIENT_ID and config.EBAY_CLIENT_SECRET):
        raise NotImplementedError(
            "No live resale credentials. Set EBAY_CLIENT_ID / EBAY_CLIENT_SECRET "
            "(free keyset from developer.ebay.com), or run `python -m "
            "scripts.seed_demo` for offline demo resale data. StockX requires "
            "partner-program approval and stays stubbed.")

    from .. import models as _models

    rows, failed = [], []
    for model in _models.CATALOG:
        try:
            row = _fetch_ebay(model)
            if row:
                rows.append(row)
        except Exception as exc:
            failed.append(model.slug)
            print(f"  ! ebay failed for {model.slug}: {exc}")
        _time.sleep(0.4)   # stay polite; Browse API default quota is 5k/day
    n = store(rows)
    purged = _purge_seeded("ebay") if n else 0
    print(f"  resale: ebay -> {n} model-rows stored, {len(failed)} failed"
          + (f", purged {purged} seeded ebay rows" if purged else ""))


if __name__ == "__main__":
    run()
