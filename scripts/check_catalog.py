"""Flag catalog entries that auto-discovery left incomplete.

New models can enter ``solesight/catalog.json`` two ways: a manual add (full
metadata) or auto-discovery promoting a trending search term (bare-bones —
often just slug/name/brand/trends_term, no retail price, no product photo,
and a default "lifestyle" category that may not fit). This scans the live
catalog for exactly that gap so it can be caught on a cadence instead of only
when a shoe happens to hit the top of the index and someone notices the
blank photo.

Checks against what's actually true on disk / in the catalog, not against
a separate bookkeeping field — a model with no local PNG is a real gap, but
one with a photo already in ``assets/sneakers/`` is fine even if its "image"
source-tracking field happens to be unset.

    python -m scripts.check_catalog
"""
from __future__ import annotations

from solesight import models


def main() -> None:
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


if __name__ == "__main__":
    main()
