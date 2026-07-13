"""Boutique retail availability via Shopify's public product feeds.

Shopify stores intentionally expose `/products.json` — a paginated public feed
of every product with variants and stock flags. Polling a handful of sneaker
boutiques once a night gives a signal nobody else in this stack has: **retail
sell-through**. "In stock at 1 of 6 boutiques" is a demand statement money
already voted on.

Per store per night: 1-3 requests (paginated), full catalog matched locally
against every tracked model's keywords (same trick as the Reddit scanner —
match one feed against 90 models rather than 90 queries). Best-effort by
design: Shopify's bot protection may 429 some networks; stores that refuse are
skipped and the availability signal simply doesn't render until data exists.

Context signal only — surfaced in snapshots and the UI, not weighted into the
Hype Score until a backtest earns it a slot.
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import date

from .. import models
from ..db import connect

_UA = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json",
}
_PER_PAGE = 250
_MAX_PAGES = 3          # newest ~750 products per store is plenty
_PAUSE = 1.2            # polite gap between requests

# Sneaker boutiques known to run Shopify. Editable data, like the catalog.
STORES = [
    "bdgastore.com",            # Bodega
    "cncpts.com",               # Concepts
    "feature.com",              # Feature
    "lapstoneandhammer.com",    # Lapstone & Hammer
    "socialstatuspgh.com",      # Social Status
    "sneakerpolitics.com",      # Sneaker Politics
]


def _fetch_store(domain: str) -> list[dict]:
    products: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        url = f"https://{domain}/products.json?limit={_PER_PAGE}&page={page}"
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=25) as resp:
            batch = json.loads(resp.read()).get("products", [])
        products.extend(batch)
        if len(batch) < _PER_PAGE:
            break
        time.sleep(_PAUSE)
    return products


def _match_rows(domain: str, products: list[dict], now: int) -> list[dict]:
    today = date.today().isoformat()
    rows = []
    for m in models.CATALOG:
        best = None
        for p in products:
            title = f"{p.get('title', '')} {p.get('vendor', '')}"
            if not m.matches(title):
                continue
            variants = p.get("variants", [])
            if not variants:
                continue
            avail = sum(1 for v in variants if v.get("available"))
            try:
                price = float(variants[0].get("price") or 0) or None
            except (TypeError, ValueError):
                price = None
            cand = {"model_slug": m.slug, "date": today, "store": domain,
                    "price": price, "variants_total": len(variants),
                    "variants_available": avail, "fetched_at": now}
            # prefer the listing with the most sizes (usually the GR release)
            if best is None or cand["variants_total"] > best["variants_total"]:
                best = cand
        if best:
            rows.append(best)
    return rows


def store_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """INSERT INTO availability
                   (model_slug, date, store, price, variants_total,
                    variants_available, fetched_at)
               VALUES (:model_slug, :date, :store, :price, :variants_total,
                       :variants_available, :fetched_at)
               ON CONFLICT(model_slug, date, store) DO UPDATE SET
                   price=excluded.price,
                   variants_total=excluded.variants_total,
                   variants_available=excluded.variants_available,
                   fetched_at=excluded.fetched_at""",
            rows)
    return len(rows)


def snapshot_fields(model_slug: str) -> dict:
    """Latest-day availability rollup for one model."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT store, price, variants_total, variants_available
               FROM availability WHERE model_slug=? AND date=
                 (SELECT MAX(date) FROM availability WHERE model_slug=?)""",
            (model_slug, model_slug)).fetchall()
    if not rows:
        return {"stores_stocking": 0, "sellout_rate": None, "boutique_price": None}
    total = sum(r["variants_total"] for r in rows)
    avail = sum(r["variants_available"] for r in rows)
    prices = [r["price"] for r in rows if r["price"]]
    return {
        "stores_stocking": len(rows),
        "sellout_rate": None if not total else round(1 - avail / total, 2),
        "boutique_price": round(sum(prices) / len(prices), 0) if prices else None,
    }


def run() -> None:
    """Poll every boutique once; skip cleanly on bot-blocks."""
    now = int(time.time())
    stored = blocked = 0
    for domain in STORES:
        try:
            products = _fetch_store(domain)
            n = store_rows(_match_rows(domain, products, now))
            stored += n
            print(f"  boutiques: {domain} -> {len(products)} products, "
                  f"{n} model matches")
        except Exception as exc:
            blocked += 1
            print(f"  ! boutiques: {domain} refused ({str(exc)[:60]})")
        time.sleep(_PAUSE)
    if blocked == len(STORES):
        print("  boutiques: every store refused this network — availability "
              "stays dormant until a run lands (best-effort by design)")
    else:
        print(f"  boutiques: {stored} availability rows from "
              f"{len(STORES) - blocked}/{len(STORES)} stores")


if __name__ == "__main__":
    run()
