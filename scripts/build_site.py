"""Generate the static Hype Index site's data from the SQLite DB.

Reads every model's signal snapshot plus its trend/forecast/resale series, copies
the background-removed product photos into web/img/, and writes web/data.json —
the single payload the web/ frontend renders. Pure read-only; run it after the
pipeline or seed_demo whenever the underlying data changes.

    python -m scripts.build_site
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from solesight import models
from solesight.db import connect
from solesight.ingest import resale
from solesight.insights import signals

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
IMG_OUT = WEB / "img"


def _downsample(rows: list[dict], n: int = 70) -> list[dict]:
    if len(rows) <= n:
        return rows
    step = len(rows) / n
    return [rows[int(i * step)] for i in range(n)]


def _trend(slug: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT date, interest FROM trends WHERE model_slug=? ORDER BY date",
            (slug,)).fetchall()
    series = [{"d": r["date"], "v": round(r["interest"], 1)} for r in rows]
    return _downsample(series)


def _forecast(slug: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT horizon_date, yhat, yhat_lower, yhat_upper FROM forecasts
               WHERE model_slug=? AND generated_at=(
                   SELECT MAX(generated_at) FROM forecasts WHERE model_slug=?)
               ORDER BY horizon_date""", (slug, slug)).fetchall()
    return [{"d": r["horizon_date"], "v": round(r["yhat"], 1),
             "lo": round(r["yhat_lower"], 1), "hi": round(r["yhat_upper"], 1)}
            for r in rows]


def _resale_series(slug: str) -> dict:
    df = resale.load(slug)
    out: dict[str, list[dict]] = {}
    if df.empty:
        return out
    for src in ("stockx", "ebay"):
        sub = df[df["source"] == src].sort_values("date")
        rows = [{"d": d.strftime("%Y-%m-%d"), "v": round(float(v), 0)}
                for d, v in zip(sub["date"], sub["last_sale"])]
        out[src] = _downsample(rows, 60)
    return out


def _insight(slug: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT summary FROM insights WHERE model_slug=? "
            "ORDER BY generated_at DESC LIMIT 1", (slug,)).fetchone()
    return row["summary"] if row else None


def _round(x, n=1):
    return None if x is None else round(x, n)


def build() -> dict:
    records = []
    for m in models.CATALOG:
        s = signals.snapshot(m.slug)
        img = models.image_path(m.slug)
        records.append({
            "slug": m.slug, "name": m.name, "brand": m.brand,
            "retail": s["retail_price"],
            "img": f"img/{m.slug}.png" if img else None,
            "hype": s["hype_score"],
            "interest": _round(s["recent_14d_interest"], 0),
            "momentum": _round(s["momentum_pct"], 0),
            "buzz": _round(s["social_buzz_index"], 0),
            "buzz_momentum": _round(s["social_buzz_momentum_pct"], 0),
            "sentiment": _round(s["avg_reddit_sentiment"], 2),
            "posts": s["reddit_post_count"],
            "sentiment_mix": {"pos": s["sentiment_positive"],
                              "neu": s["sentiment_neutral"],
                              "neg": s["sentiment_negative"]},
            "platforms": s["social_platform_engagement"],
            "resale_last": _round(s["resale_last_sale"], 0),
            "resale_premium": _round(s["resale_premium"], 2),
            "resale_momentum": _round(s["resale_momentum_pct"], 0),
            "sales": s["resale_sales_14d"],
            "forecast_delta": _round(
                None if s["forecast_start"] is None
                else s["forecast_end_30d"] - s["forecast_start"], 0),
            "forecast_peak": _round(s["forecast_peak"], 0),
            "forecast_peak_date": s["forecast_peak_date"],
            "insight": _insight(m.slug),
            "trend": _trend(m.slug),
            "forecast": _forecast(m.slug),
            "resale_series": _resale_series(m.slug),
        })
    records.sort(key=lambda r: -(r["hype"] or 0))
    for i, r in enumerate(records, 1):
        r["rank"] = i
    return {"generated_at": int(time.time()),
            "brands": sorted({m.brand for m in models.CATALOG}),
            "models": records}


def main() -> None:
    WEB.mkdir(exist_ok=True)
    IMG_OUT.mkdir(exist_ok=True)
    copied = 0
    for m in models.CATALOG:
        src = models.image_path(m.slug)
        if src:
            shutil.copyfile(src, IMG_OUT / f"{m.slug}.png")
            copied += 1
    data = build()
    (WEB / "data.json").write_text(json.dumps(data, indent=None))
    print(f"  wrote web/data.json ({len(data['models'])} models), "
          f"copied {copied} images")


if __name__ == "__main__":
    main()
