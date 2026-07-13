"""Download a model's full 36-frame 360° rig and cache transparent PNGs.

The StockX 360 CDN exposes img01..img36 (10° apart). This fetches every frame
at web resolution, flood-fills the studio background to alpha (same routine as
seed_images), and writes web/img360/<slug>/f01.png … f36.png. The site's hero
card upgrades to a drag-to-rotate viewer whenever frames exist for a model.

    python -m scripts.seed_360                 # current #1 by Hype Score
    python -m scripts.seed_360 --slug aj1-bred # a specific model
    python -m scripts.seed_360 --force         # re-fetch existing frames
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from solesight import models
from scripts.seed_images import remove_bg

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "web" / "img360"
_UA = {"User-Agent": "Mozilla/5.0"}
FRAMES = 36
WIDTH = 640          # per-frame width — keeps 36 frames to a few MB total


def _frame_url(img_slug: str, i: int) -> str:
    return (f"https://images.stockx.com/360/{img_slug}/Images/{img_slug}"
            f"/Lv2/img{i:02d}.jpg?w={WIDTH}&q=85&fm=jpg")


def top_model_slug() -> str:
    data = json.loads((ROOT / "web" / "data.json").read_text())
    return data["models"][0]["slug"]


def fetch(slug: str, force: bool = False) -> int:
    img_slug = models.IMAGE_SLUG.get(slug)
    if not img_slug:
        raise SystemExit(f"{slug} has no StockX image slug in the catalog")
    out = OUT_ROOT / slug
    out.mkdir(parents=True, exist_ok=True)
    done = 0
    for i in range(1, FRAMES + 1):
        dest = out / f"f{i:02d}.png"
        if dest.exists() and not force:
            done += 1
            continue
        req = urllib.request.Request(_frame_url(img_slug, i), headers=_UA)
        try:
            data = urllib.request.urlopen(req, timeout=25).read()
        except Exception as exc:
            print(f"  ! frame {i:02d} failed: {exc}")
            continue
        if len(data) < 2000 or data[:3] != b"\xff\xd8\xff":
            print(f"  ! frame {i:02d}: not a JPEG")
            continue
        remove_bg(data).save(dest)
        done += 1
        if i % 9 == 0:
            print(f"  {slug}: {i}/{FRAMES} frames")
    return done


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch a model's 360° frames.")
    p.add_argument("--slug", help="model slug (default: current #1 by hype)")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    slug = args.slug or top_model_slug()
    n = fetch(slug, args.force)
    print(f"Done: {n}/{FRAMES} frames for {slug} -> web/img360/{slug}/")


if __name__ == "__main__":
    main()
