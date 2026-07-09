"""Registry of tracked sneaker models.

Each SneakerModel carries the search terms we feed to Google Trends and Reddit.
`keywords` are OR-matched when scanning Reddit chatter; `trends_term` is the single
query string sent to Google Trends (which only accepts one term per series well).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SneakerModel:
    slug: str                    # stable id used in the DB, e.g. "aj1-chicago"
    name: str                    # display name
    brand: str
    trends_term: str             # Google Trends query
    keywords: tuple[str, ...] = field(default_factory=tuple)  # Reddit match terms

    def matches(self, text: str) -> bool:
        lowered = text.lower()
        return any(k.lower() in lowered for k in self.keywords)


# 20+ tracked models spanning the major hype silhouettes.
CATALOG: list[SneakerModel] = [
    SneakerModel("aj1-chicago", "Air Jordan 1 Chicago", "Jordan",
                 "Air Jordan 1 Chicago", ("jordan 1 chicago", "aj1 chicago", "chicago 1")),
    SneakerModel("aj1-bred", "Air Jordan 1 Bred", "Jordan",
                 "Air Jordan 1 Bred", ("jordan 1 bred", "aj1 bred", "bred toe")),
    SneakerModel("aj4-bred", "Air Jordan 4 Bred", "Jordan",
                 "Air Jordan 4 Bred", ("jordan 4 bred", "aj4 bred")),
    SneakerModel("aj3-black-cement", "Air Jordan 3 Black Cement", "Jordan",
                 "Air Jordan 3 Black Cement", ("jordan 3 black cement", "aj3 cement")),
    SneakerModel("aj11-concord", "Air Jordan 11 Concord", "Jordan",
                 "Air Jordan 11 Concord", ("jordan 11 concord", "aj11 concord")),
    SneakerModel("dunk-low-panda", "Nike Dunk Low Panda", "Nike",
                 "Nike Dunk Low Panda", ("dunk low panda", "panda dunk", "panda dunks")),
    SneakerModel("dunk-low-unc", "Nike Dunk Low UNC", "Nike",
                 "Nike Dunk Low UNC", ("dunk low unc", "unc dunk")),
    SneakerModel("dunk-low-syracuse", "Nike Dunk Low Syracuse", "Nike",
                 "Nike Dunk Low Syracuse", ("dunk syracuse",)),
    SneakerModel("nike-af1-white", "Nike Air Force 1 '07 White", "Nike",
                 "Nike Air Force 1 White", ("air force 1", "af1 white", "triple white af1")),
    SneakerModel("travis-scott-aj1-low", "Travis Scott x Air Jordan 1 Low", "Jordan",
                 "Travis Scott Jordan 1 Low", ("travis scott jordan 1", "ts aj1", "cactus jack 1")),
    SneakerModel("nb-550-white-green", "New Balance 550 White Green", "New Balance",
                 "New Balance 550 White Green", ("nb 550", "new balance 550")),
    SneakerModel("nb-990v5", "New Balance 990v5", "New Balance",
                 "New Balance 990v5", ("990v5", "nb 990")),
    SneakerModel("nb-2002r", "New Balance 2002R", "New Balance",
                 "New Balance 2002R", ("2002r", "nb 2002")),
    SneakerModel("yeezy-350-v2", "adidas Yeezy Boost 350 V2", "adidas",
                 "Yeezy Boost 350 V2", ("yeezy 350", "350 v2", "boost 350")),
    SneakerModel("yeezy-slide", "adidas Yeezy Slide", "adidas",
                 "Yeezy Slide", ("yeezy slide", "yeezy slides")),
    SneakerModel("samba-og", "adidas Samba OG", "adidas",
                 "adidas Samba OG", ("adidas samba", "samba og")),
    SneakerModel("adidas-gazelle", "adidas Gazelle", "adidas",
                 "adidas Gazelle", ("adidas gazelle", "gazelle")),
    SneakerModel("nike-vomero-5", "Nike Zoom Vomero 5", "Nike",
                 "Nike Vomero 5", ("vomero 5", "zoom vomero")),
    SneakerModel("asics-gel-1130", "ASICS Gel-1130", "ASICS",
                 "ASICS Gel 1130", ("gel-1130", "gel 1130", "asics 1130")),
    SneakerModel("asics-gt-2160", "ASICS GT-2160", "ASICS",
                 "ASICS GT 2160", ("gt-2160", "gt 2160")),
    SneakerModel("sb-dunk-low-jarritos", "Nike SB Dunk Low Jarritos", "Nike",
                 "Nike SB Dunk Jarritos", ("sb dunk jarritos", "jarritos dunk")),
    SneakerModel("aj4-military-black", "Air Jordan 4 Military Black", "Jordan",
                 "Air Jordan 4 Military Black", ("jordan 4 military", "aj4 military")),
    SneakerModel("nike-kobe-6-grinch", "Nike Kobe 6 Protro Grinch", "Nike",
                 "Nike Kobe 6 Grinch", ("kobe 6 grinch", "grinch kobe")),
]

BY_SLUG: dict[str, SneakerModel] = {m.slug: m for m in CATALOG}

# Retail MSRP (USD) per model — the baseline the resale premium is measured
# against. Approximate public launch prices; retros vary a little by region/year.
RETAIL: dict[str, int] = {
    "aj1-chicago": 180, "aj1-bred": 180, "aj4-bred": 215, "aj3-black-cement": 210,
    "aj11-concord": 235, "dunk-low-panda": 115, "dunk-low-unc": 115,
    "dunk-low-syracuse": 110, "nike-af1-white": 115, "travis-scott-aj1-low": 150,
    "nb-550-white-green": 120, "nb-990v5": 185, "nb-2002r": 150,
    "yeezy-350-v2": 230, "yeezy-slide": 70, "samba-og": 100, "adidas-gazelle": 100,
    "nike-vomero-5": 160, "asics-gel-1130": 100, "asics-gt-2160": 110,
    "sb-dunk-low-jarritos": 125, "aj4-military-black": 215, "nike-kobe-6-grinch": 190,
}


# StockX image slug per model (the Title-Case-Dashes product id in its 360 image
# CDN path) — the provenance of each local photo. scripts/seed_images fetches
# from these, strips the white background to alpha, and caches the result under
# assets/sneakers/<slug>.png. See image_path() (local) and image_url() (remote).
IMAGE_SLUG: dict[str, str] = {
    "aj1-chicago": "Air-Jordan-1-Retro-Chicago-2015",
    "aj1-bred": "Air-Jordan-1-Retro-Bred-2016",
    "aj4-bred": "Air-Jordan-4-Retro-Bred-2019",
    "aj3-black-cement": "Air-Jordan-3-Retro-Black-Cement-2018",
    "aj11-concord": "Air-Jordan-11-Retro-Concord-2018",
    "dunk-low-panda": "Nike-Dunk-Low-Retro-White-Black-2021",
    "dunk-low-unc": "Nike-Dunk-Low-UNC-2021",
    "dunk-low-syracuse": "Nike-Dunk-Low-SP-Syracuse",
    "nike-af1-white": "Nike-Air-Force-1-Low-White-07",
    "travis-scott-aj1-low": "Air-Jordan-1-Retro-Low-Travis-Scott",
    "nb-550-white-green": "New-Balance-550-White-Green",
    "nb-990v5": "New-Balance-990v5-Grey",
    "nb-2002r": "New-Balance-2002R-Rain-Cloud",
    "yeezy-350-v2": "adidas-Yeezy-Boost-350-V2-Zebra",
    "yeezy-slide": "adidas-Yeezy-Slide-Pure",
    "samba-og": "adidas-Samba-OG-Cloud-White-Core-Black",
    "adidas-gazelle": "adidas-Gazelle-Indoor-College-Navy-Gum",
    "nike-vomero-5": "Nike-Zoom-Vomero-5-SP-Vast-Grey",
    "asics-gel-1130": "ASICS-Gel-1130-White-Clay-Canyon",
    "asics-gt-2160": "ASICS-GT-2160-White-Black",
    "sb-dunk-low-jarritos": "Nike-SB-Dunk-Low-Jarritos",
    "aj4-military-black": "Air-Jordan-4-Retro-Military-Black",
    "nike-kobe-6-grinch": "Nike-Kobe-6-Protro-Grinch",
}

# Local, background-removed product photos live here (PNG with alpha).
_IMAGE_DIR = Path(__file__).resolve().parent.parent / "assets" / "sneakers"


def get(slug: str) -> SneakerModel:
    return BY_SLUG[slug]


def retail(slug: str) -> int | None:
    """Retail MSRP for a model, or None if unknown."""
    return RETAIL.get(slug)


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
