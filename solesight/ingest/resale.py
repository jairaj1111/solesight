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
                    listing_url, fetched_at)
               VALUES (:model_slug, :date, :source, :last_sale, :lowest_ask,
                       :sales_count, :listing_url, :fetched_at)
               ON CONFLICT(model_slug, date, source) DO UPDATE SET
                   last_sale   = excluded.last_sale,
                   lowest_ask  = excluded.lowest_ask,
                   sales_count = excluded.sales_count,
                   listing_url = excluded.listing_url,
                   fetched_at  = excluded.fetched_at""",
            [{**r, "listing_url": r.get("listing_url")} for r in rows],
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


# US eBay + (future) StockX are the canonical "home market" for the premium.
# International rows (ebay_gb, ebay_de) live in the same table but are read
# separately, so they never pollute the headline US premium.
_DOMESTIC = ("ebay", "stockx")


def daily_price(model_slug: str) -> pd.DataFrame:
    """Blended daily HOME-MARKET series: mean last_sale, summed sales_count."""
    df = load(model_slug)
    if df.empty:
        return pd.DataFrame(columns=["date", "last_sale", "sales_count"])
    df = df[df["source"].isin(_DOMESTIC)]
    if df.empty:
        return pd.DataFrame(columns=["date", "last_sale", "sales_count"])
    return (df.groupby("date", as_index=False)
              .agg(last_sale=("last_sale", "mean"),
                   sales_count=("sales_count", "sum"))
              .sort_values("date"))


def premiums_by_region(model_slug: str, retail: int | None) -> dict:
    """Latest resale premium (× retail) per marketplace — US vs UK vs DE.

    International rows are stored already converted to USD, so all three are
    directly comparable against the USD retail price.
    """
    if not retail:
        return {}
    df = load(model_slug)
    if df.empty:
        return {}
    labels = {"ebay": "us", "ebay_gb": "uk", "ebay_de": "de"}
    out = {}
    for src, region in labels.items():
        sub = df[df["source"] == src]
        if sub.empty:
            continue
        latest = sub[sub["date"] == sub["date"].max()]
        price = float(latest["last_sale"].mean())
        out[region] = round(price / retail, 2)
    return out


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
    priced = sorted(
        ((float(i["price"]["value"]), i.get("itemWebUrl")) for i in items
         if i.get("price", {}).get("value")),
        key=lambda pu: pu[0])
    if len(priced) < 3:          # too thin to be a signal
        return None
    # Trim the top/bottom decile: fakes, kids' sizes and typo listings live there.
    k = max(1, len(priced) // 10)
    core = priced[k:-k] or priced
    return {
        "model_slug": model.slug,
        "date": _date.today().isoformat(),
        "source": "ebay",
        "last_sale": round(statistics.median(p for p, _ in core), 2),
        "lowest_ask": round(core[0][0], 2),
        "sales_count": len(priced),
        "listing_url": core[0][1],   # real listing for the lowest ask
        "fetched_at": int(_time.time()),
    }


# --- international eBay marketplaces (same key, different marketplace id) -----
# eBay's Browse API serves every marketplace off one keyset — just swap the
# X-EBAY-C-MARKETPLACE-ID header and the priceCurrency filter. Frankfurter
# (European Central Bank rates, keyless) converts the result to USD so UK/DE
# asks are directly comparable to the US premium.
_FX_URL = "https://api.frankfurter.app/latest"
_fx_cache: dict = {}
_MARKETPLACES = [
    # (source label, marketplace id, currency)
    ("ebay_gb", "EBAY_GB", "GBP"),
    ("ebay_de", "EBAY_DE", "EUR"),
]


def _usd_rate(currency: str) -> float | None:
    """1 unit of `currency` in USD, cached per run.

    Tries Frankfurter (ECB) first, then open.er-api as a fallback — a single FX
    source going down must never silently kill the international signal.
    """
    if currency == "USD":
        return 1.0
    if currency in _fx_cache:
        return _fx_cache[currency]
    import json
    import urllib.parse
    import urllib.request
    ua = {"User-Agent": "SoleSight/1.0 (sneaker-market research)"}
    sources = [
        (f"{_FX_URL}?" + urllib.parse.urlencode({"from": currency, "to": "USD"}),
         lambda d: d["rates"]["USD"]),
        (f"https://open.er-api.com/v6/latest/{currency}",
         lambda d: d["rates"]["USD"]),
    ]
    for url, pick in sources:
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=ua), timeout=15) as resp:
                rate = float(pick(json.loads(resp.read())))
            _fx_cache[currency] = rate
            return rate
        except Exception:
            continue
    return None


def _fetch_ebay_region(model, marketplace: str, currency: str, source: str) -> dict | None:
    """One deadstock ask-side row for `model` on a non-US marketplace, in USD."""
    import json
    import statistics
    import time as _time
    import urllib.parse
    import urllib.request
    from datetime import date as _date

    query = urllib.parse.urlencode({
        "q": model.trends_term,
        "category_ids": _EBAY_CATEGORY,
        "limit": "50",
        "filter": f"buyingOptions:{{FIXED_PRICE}},priceCurrency:{currency},"
                  "conditionIds:{1000}",
    })
    req = urllib.request.Request(f"{_EBAY_SEARCH}?{query}", headers={
        "Authorization": f"Bearer {_ebay_token()}",
        "X-EBAY-C-MARKETPLACE-ID": marketplace,
    })
    with urllib.request.urlopen(req, timeout=25) as resp:
        items = json.loads(resp.read()).get("itemSummaries", [])
    priced = sorted(
        ((float(i["price"]["value"]), i.get("itemWebUrl")) for i in items
         if i.get("price", {}).get("value")),
        key=lambda pu: pu[0])
    if len(priced) < 3:
        return None
    rate = _usd_rate(currency)
    if not rate:
        return None
    k = max(1, len(priced) // 10)
    core = priced[k:-k] or priced
    return {
        "model_slug": model.slug,
        "date": _date.today().isoformat(),
        "source": source,
        "last_sale": round(statistics.median(p for p, _ in core) * rate, 2),  # native -> USD
        "lowest_ask": round(core[0][0] * rate, 2),
        "sales_count": len(priced),
        "listing_url": core[0][1],   # real listing for the lowest ask
        "fetched_at": int(_time.time()),
    }


def run_international() -> None:
    """Fetch UK + DE deadstock asks (USD-converted) for the cross-market spread."""
    import time as _time
    if not (config.EBAY_CLIENT_ID and config.EBAY_CLIENT_SECRET):
        return
    from .. import models as _models
    for source, marketplace, currency in _MARKETPLACES:
        rows, failed = [], 0
        for model in _models.CATALOG:
            try:
                row = _fetch_ebay_region(model, marketplace, currency, source)
                if row:
                    rows.append(row)
            except Exception:
                failed += 1
            _time.sleep(0.4)
        n = store(rows)
        print(f"  resale: {source} -> {n} model-rows stored (USD-converted), "
              f"{failed} failed")


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
    # International asks (UK/DE) for the cross-market premium spread.
    try:
        run_international()
    except Exception as exc:
        print(f"  ! resale international skipped: {str(exc)[:60]}")


if __name__ == "__main__":
    run()
