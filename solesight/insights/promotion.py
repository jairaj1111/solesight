"""Auto-promote strong Discovery candidates into the tracked catalog.

Discovery (discovery.py) surfaces untracked shoes getting real press
attention, but only as a suggestion list — nothing adds them to the actual
index. This module decides which candidates are trustworthy enough to become
a real tracked model (a new entry in catalog.json, not just a display item),
so the index itself grows when something new is genuinely popping off — no
manual curation step, no waiting for a human to notice.

Deliberately conservative, because this is the one place in the pipeline that
creates a new tracked product — every other stage reads and scores existing
models; this one invents a new row that resale premiums, forecasts and buy
links get built on top of. Two independent bars, both required:

  1. Discovery already requires >=2 mentions to appear at all. Promotion
     raises that: >=3 mentions AND >=2 distinct outlets. A single blog
     repeating itself isn't real traction; several outlets independently
     naming the same shoe is.
  2. Press mentions alone can still be noise — a rumor, a delayed release, a
     misparsed headline. So a live, fresh Google Trends read on the exact
     extracted name is required too: real consumer search interest, not just
     editorial chatter, before anything gets added.

A promoted model starts with retail price and product photo UNKNOWN — there's
no free API for either, and every downstream stage (resale premium, Hype
Score) already treats a missing retail price as "not yet known" and
renormalizes around it. Guessing a number that could be wrong would repeat
exactly the kind of fabricated-data problem this project has otherwise been
careful to avoid; a blank field that gets backfilled later is more honest.
"""
from __future__ import annotations

import json
import re
import time

from . import discovery
from .. import models

_MIN_MENTIONS = 3
_MIN_OUTLETS = 2
_TRENDS_FLOOR = 15.0     # same convention as lifecycle.py's _EVENT_FLOOR
_TRENDS_WINDOW_DAYS = 30 # a brand-new candidate has no long history to window

# Brand -> default category. Best-effort; a human can correct it later same
# as any other catalog field — this just keeps a promoted entry from
# defaulting to a wrong-looking category in the meantime.
_BRAND_CATEGORY = {
    "air jordan": "basketball", "jordan": "basketball", "nike sb": "skate",
    "nike": "lifestyle", "adidas": "lifestyle", "yeezy": "lifestyle",
    "new balance": "running", "asics": "running", "hoka": "running",
    "on": "running", "saucony": "running", "puma": "lifestyle",
    "reebok": "lifestyle", "converse": "skate", "vans": "skate",
    "salomon": "running", "crocs": "lifestyle", "ugg": "lifestyle",
    "timberland": "lifestyle",
}


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return re.sub(r"-+", "-", s)


def _brand_from_name(name: str) -> str:
    lowered = name.lower()
    for brand in discovery._BRANDS:
        if lowered.startswith(brand.lower()):
            # discovery._BRANDS detects "Air Jordan" as a distinct text pattern
            # (official product names almost always say "Air Jordan"), but the
            # catalog's own convention — every hand-curated Jordan entry — uses
            # the brand name "Jordan". Normalize so market rollups never split
            # one brand's stats across two rows.
            return "Jordan" if brand == "Air Jordan" else brand
    return name.split()[0]


def _confirm_trends(term: str) -> float | None:
    """Recent avg Google Trends interest for `term`, or None if it can't be
    fetched or doesn't clear the noise floor — either way, don't promote."""
    from datetime import date, timedelta

    from pytrends.request import TrendReq
    from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                          wait_exponential)

    from ..ingest.google_trends import _RETRYABLE

    @retry(retry=retry_if_exception_type(_RETRYABLE),
           wait=wait_exponential(multiplier=2, min=4, max=60),
           stop=stop_after_attempt(4), reraise=True)
    def _fetch(pytrends, timeframe):
        pytrends.build_payload([term], timeframe=timeframe)
        return pytrends.interest_over_time()

    end = date.today()
    start = end - timedelta(days=_TRENDS_WINDOW_DAYS)
    timeframe = f"{start.isoformat()} {end.isoformat()}"
    try:
        df = _fetch(TrendReq(hl="en-US", tz=360), timeframe)
    except Exception:
        return None
    if df.empty or term not in df.columns:
        return None
    if "isPartial" in df.columns:
        df = df[~df["isPartial"].astype(bool)]
    if df.empty:
        return None
    avg = float(df[term].mean())
    return avg if avg >= _TRENDS_FLOOR else None


def _make_entry(candidate: dict) -> dict:
    name = candidate["name"]
    brand = _brand_from_name(name)
    return {
        "slug": _slugify(name),
        "name": name,
        "brand": brand,
        "category": _BRAND_CATEGORY.get(brand.lower(), "lifestyle"),
        "trends_term": name,
        "keywords": [name.lower()],
        # retail/image deliberately omitted — see module docstring.
    }


def run(limit_checks: int = 10, catalog_path=None,
        confirm=_confirm_trends) -> list[dict]:
    """Check Discovery's top candidates against the promotion bar; append
    whichever pass to the catalog file. Returns the newly-added entries."""
    path = catalog_path or models.CATALOG_PATH
    data = json.loads(path.read_text())
    existing_slugs = {e["slug"] for e in data}

    candidates = discovery.run(limit=limit_checks)
    promoted = []
    for c in candidates:
        if c["mentions"] < _MIN_MENTIONS or c["outlets"] < _MIN_OUTLETS:
            continue
        avg = confirm(c["name"])
        time.sleep(1)   # stay polite to Trends between checks
        if avg is None:
            continue
        entry = _make_entry(c)
        if entry["slug"] in existing_slugs:
            continue    # collision with an existing slug — skip, don't overwrite
        promoted.append(entry)
        existing_slugs.add(entry["slug"])

    if promoted:
        data.extend(promoted)
        path.write_text(json.dumps(data, indent=1))
    return promoted


if __name__ == "__main__":
    added = run()
    print(f"  promotion: added {len(added)} new model(s): {[a['slug'] for a in added]}")
