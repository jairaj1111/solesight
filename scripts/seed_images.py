"""Download HD product photos and cache background-removed PNGs locally.

For every model in ``models.IMAGE_SLUG`` this fetches the StockX 360 product
image, flood-fills the white studio background to transparency (keeping interior
whites like midsoles), and writes ``assets/sneakers/<slug>.png``. The dashboard
reads these via ``models.image_path`` so the shoes float on the dark theme.

    python -m scripts.seed_images            # only fetch missing images
    python -m scripts.seed_images --force    # re-fetch everything

Needs Pillow (`pip install pillow`). Network access to images.stockx.com.
"""
from __future__ import annotations

import argparse
import urllib.request
from collections import deque
from io import BytesIO

from PIL import Image

from solesight import models

_UA = {"User-Agent": "Mozilla/5.0"}
_THRESH = 236   # RGB all >= this counts as background white


def download(slug: str) -> bytes | None:
    url = models.image_url(slug, w=1000, q=90)
    if not url:
        return None
    try:
        data = urllib.request.urlopen(
            urllib.request.Request(url, headers=_UA), timeout=25).read()
    except Exception as exc:
        print(f"    ! download failed: {exc}")
        return None
    if len(data) < 2000 or data[:3] != b"\xff\xd8\xff":
        print("    ! not a JPEG")
        return None
    return data


def remove_bg(data: bytes) -> Image.Image:
    """Flood-fill near-white from the image borders to alpha=0."""
    img = Image.open(BytesIO(data)).convert("RGBA")
    w, h = img.size
    px = img.load()
    seen = bytearray(w * h)
    q = deque()

    def is_bg(x, y):
        r, g, b, _ = px[x, y]
        return r >= _THRESH and g >= _THRESH and b >= _THRESH

    for x in range(w):
        for y in (0, h - 1):
            if not seen[y * w + x] and is_bg(x, y):
                seen[y * w + x] = 1; q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not seen[y * w + x] and is_bg(x, y):
                seen[y * w + x] = 1; q.append((x, y))
    while q:
        x, y = q.popleft()
        px[x, y] = (255, 255, 255, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and is_bg(nx, ny):
                seen[ny * w + nx] = 1; q.append((nx, ny))
    return img


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch + de-background product photos.")
    p.add_argument("--force", action="store_true", help="re-fetch existing images")
    args = p.parse_args()

    models._IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    ok = skipped = fail = 0
    for slug in models.IMAGE_SLUG:
        dest = models._IMAGE_DIR / f"{slug}.png"
        if dest.exists() and not args.force:
            skipped += 1; continue
        print(f"  {slug}")
        data = download(slug)
        if not data:
            fail += 1; continue
        remove_bg(data).save(dest)
        ok += 1
    print(f"Done: {ok} fetched, {skipped} skipped, {fail} failed "
          f"({len(list(models._IMAGE_DIR.glob('*.png')))} total on disk)")


if __name__ == "__main__":
    main()
