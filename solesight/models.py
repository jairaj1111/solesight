"""Registry of tracked sneaker models — loaded from catalog.json.

The catalog is DATA, not code: every tracked model lives in
``solesight/catalog.json`` with its search terms, retail price, category and
product-image reference. Adding a model to the index is a one-entry JSON change;
every pipeline stage (ingest, forecast, scoring, insights, site build) iterates
this registry and picks new entries up automatically on the next run.

Each SneakerModel carries the search terms we feed to Google Trends and Reddit.
`keywords` are OR-matched when scanning Reddit chatter; `trends_term` is the
single query string sent to Google Trends (which only accepts one term per
series well).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
CATALOG_PATH = _PKG_DIR / "catalog.json"


@dataclass(frozen=True)
class SneakerModel:
    slug: str                    # stable id used in the DB, e.g. "aj1-chicago"
    name: str                    # display name
    brand: str
    trends_term: str             # Google Trends query
    keywords: tuple[str, ...] = field(default_factory=tuple)  # Reddit match terms
    category: str = "lifestyle"  # basketball / running / lifestyle / skate
    retail_price: int | None = None   # MSRP (USD) — resale-premium baseline
    image_slug: str | None = None     # StockX 360 CDN product id (photo source)
    artist: str | None = None         # musician tied to the shoe (Spotify heat)

    def matches(self, text: str) -> bool:
        lowered = text.lower()
        return any(k.lower() in lowered for k in self.keywords)


def _load() -> list[SneakerModel]:
    entries = json.loads(CATALOG_PATH.read_text())
    catalog = [
        SneakerModel(
            slug=e["slug"], name=e["name"], brand=e["brand"],
            trends_term=e["trends_term"], keywords=tuple(e["keywords"]),
            category=e.get("category", "lifestyle"),
            retail_price=e.get("retail"), image_slug=e.get("image"),
            artist=e.get("artist"),
        )
        for e in entries
    ]
    slugs = [m.slug for m in catalog]
    if len(slugs) != len(set(slugs)):
        dupes = {s for s in slugs if slugs.count(s) > 1}
        raise ValueError(f"catalog.json has duplicate slugs: {dupes}")
    return catalog


CATALOG: list[SneakerModel] = _load()
BY_SLUG: dict[str, SneakerModel] = {m.slug: m for m in CATALOG}

# Backwards-compatible views (kept because scripts iterate/introspect these).
RETAIL: dict[str, int] = {m.slug: m.retail_price for m in CATALOG
                          if m.retail_price is not None}
IMAGE_SLUG: dict[str, str] = {m.slug: m.image_slug for m in CATALOG
                              if m.image_slug}
CATEGORY: dict[str, str] = {m.slug: m.category for m in CATALOG}

# Local, background-removed product photos live here (PNG with alpha).
_IMAGE_DIR = _PKG_DIR.parent / "assets" / "sneakers"


def get(slug: str) -> SneakerModel:
    return BY_SLUG[slug]


def retail(slug: str) -> int | None:
    """Retail MSRP for a model, or None if unknown."""
    return RETAIL.get(slug)


def category(slug: str) -> str:
    """Product category (basketball / running / lifestyle / skate)."""
    return CATEGORY.get(slug, "lifestyle")


def image_path(slug: str) -> str | None:
    """Path to the local transparent product PNG, or None if not downloaded."""
    p = _IMAGE_DIR / f"{slug}.png"
    return str(p) if p.exists() else None


def image_url(slug: str, w: int = 1000, q: int = 90) -> str | None:
    """Remote HD product image URL (StockX 360 CDN) — white background, or None."""
    img = IMAGE_SLUG.get(slug)
    if not img:
        return None
    return (f"https://images.stockx.com/360/{img}/Images/{img}/Lv2/img01.jpg"
            f"?w={w}&q={q}&dpr=2&fm=jpg")
