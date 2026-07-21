"""Discovery radar — sneakers heating up in the press but NOT yet tracked.

SoleSight tracks a curated 90. But the same press feeds it already reads name
dozens of *other* shoes every week — the ones about to matter. Rather than
guess what to add, this lets the data nominate: it re-reads the sneaker-press
RSS feeds, throws away every headline that matches a shoe we already track, and
from what's left extracts the brand-anchored product name, tallying which
un-tracked silhouettes are getting the most coverage across the most outlets.

The output is a ranked "bubbling up" list — a shortlist of onboarding
candidates surfaced by real editorial attention, not opinion. Keyless and
free; it reuses the exact feeds the press adapter already polls.

This is discovery, not a scored signal — a candidate here isn't in the Hype
Score until it's curated into the catalog (a one-line JSON add).
"""
from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict

from .. import models
from ..ingest.press import FEEDS, _UA

# Brand anchors — a headline's shoe name almost always starts at one of these.
_BRANDS = [
    "Air Jordan", "Jordan", "Nike SB", "Nike", "adidas", "Yeezy", "New Balance",
    "ASICS", "Puma", "Reebok", "Converse", "Vans", "Salomon", "Hoka", "On",
    "Saucony", "Crocs", "UGG", "Timberland",
]
_BRAND_RE = re.compile(r"\b(" + "|".join(re.escape(b) for b in _BRANDS) + r")\b[\w’'\-. ]{2,44}", re.I)

# Words that mark the end of the product name and start of the sentence's verb
# clause — we cut the phrase here so "Nike Air Max Is Releasing Soon" -> "Nike Air Max".
_STOP = re.compile(
    r"\b(is|are|was|were|to|the|a|an|will|would|gets?|got|drops?|dropping|"
    r"releas\w*|coming|comes?|has|have|and|with|for|in|on|of|arriv\w*|returns?|"
    r"unveil\w*|reveal\w*|debut\w*|makes?|brings?|adds?|now|this|that|its?|"
    r"official|first|new|latest|just|set|slated|lands?|hits?)\b.*$", re.I)


def _clean(phrase: str) -> str:
    phrase = re.sub(r"\s+", " ", phrase).strip(" -–—:·|")
    phrase = _STOP.sub("", phrase).strip(" -–—:·|")
    return phrase


def _fetch_titles(url: str) -> list[str]:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        root = ET.fromstring(resp.read())
    return [(it.findtext("title") or "").strip() for it in root.iter("item")]


def run(limit: int = 10) -> list[dict]:
    """Ranked un-tracked shoe candidates from the live press feeds."""
    # counts[name] = {"mentions": int, "outlets": set(outlet)}
    counts: dict[str, dict] = defaultdict(lambda: {"mentions": 0, "outlets": set()})
    seen_titles: set[str] = set()

    for outlet, url in FEEDS:
        try:
            titles = _fetch_titles(url)
        except Exception:
            continue
        for title in titles:
            key = title.lower()
            if not title or key in seen_titles:
                continue
            seen_titles.add(key)
            if any(m.matches(title) for m in models.CATALOG):
                continue                       # already tracked — not a discovery
            for match in _BRAND_RE.finditer(title):
                name = _clean(match.group(0))
                if len(name.split()) < 2 or len(name) < 6:
                    continue                   # too generic ("Nike", "adidas")
                rec = counts[name]
                rec["mentions"] += 1
                rec["outlets"].add(outlet)

    ranked = sorted(
        ({"name": n, "mentions": d["mentions"], "outlets": len(d["outlets"])}
         for n, d in counts.items()),
        key=lambda x: (x["mentions"], x["outlets"]), reverse=True,
    )
    # keep only candidates with real traction (seen more than once)
    return [c for c in ranked if c["mentions"] >= 2][:limit]


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
