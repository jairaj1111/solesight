"""Flag catalog entries that auto-discovery left incomplete.

New models can enter ``solesight/catalog.json`` two ways: a manual add (full
metadata) or auto-discovery promoting a trending search term (bare-bones —
often just slug/name/brand/trends_term, no retail price, no product photo,
and a default "lifestyle" category that may not fit). This scans the live
catalog for exactly that gap so it can be caught on a cadence instead of only
when a shoe happens to hit the top of the index and someone notices the
blank photo.

Also reports materials coverage — unlike photo/retail, materials is
intentionally partial (backfilled for the top-hype shoes as a batch, not
required for every entry), so this checks whether the *current* top-N by
hype (from the last ``build_site`` run) still has gaps, not the whole
catalog.

Checks against what's actually true on disk / in the catalog, not against
a separate bookkeeping field — a model with no local PNG is a real gap, but
one with a photo already in ``assets/sneakers/`` is fine even if its "image"
source-tracking field happens to be unset.

    python -m scripts.check_catalog            # photo/retail gaps + top-25 materials coverage
    python -m scripts.check_catalog --top 50   # check materials coverage in the top 50 instead
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from solesight import models

DATA_JSON = Path(__file__).resolve().parent.parent / "web" / "data.json"


def _photo_retail_gaps() -> None:
    no_photo = [m.slug for m in models.CATALOG if models.image_path(m.slug) is None]
    no_retail = [m.slug for m in models.CATALOG if m.retail_price is None]

    if not no_photo and not no_retail:
        print(f"All {len(models.CATALOG)} catalog entries have a photo and a retail price.")
        return

    if no_photo:
        print(f"Missing product photo ({len(no_photo)}):")
        for slug in no_photo:
            print(f"  {slug}")
    if no_retail:
        print(f"Missing retail price ({len(no_retail)}):")
        for slug in no_retail:
            print(f"  {slug}")


def _materials_gaps(top_n: int) -> None:
    have = sum(1 for m in models.CATALOG if m.materials)
    print(f"\nMaterials: {have}/{len(models.CATALOG)} catalog entries have it.")

    if not DATA_JSON.exists():
        print("  (run scripts/build_site first to check coverage in the current top "
              f"{top_n} by hype)")
        return
    ranked = sorted(json.loads(DATA_JSON.read_text())["models"], key=lambda m: m["rank"])
    missing = [m for m in ranked[:top_n] if not m.get("materials")]
    if missing:
        print(f"Missing from the current top {top_n} by hype ({len(missing)}):")
        for m in missing:
            print(f"  #{m['rank']} {m['slug']}")
    else:
        print(f"Current top {top_n} by hype all have it.")


def main() -> None:
    p = argparse.ArgumentParser(description="Flag catalog entries auto-discovery left incomplete.")
    p.add_argument("--top", type=int, default=25,
                    help="how many top-hype models to check for materials coverage (default 25)")
    args = p.parse_args()
    _photo_retail_gaps()
    _materials_gaps(args.top)


if __name__ == "__main__":
    main()
