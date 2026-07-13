"""Social buzz ingestion + normalization (Instagram / TikTok / YouTube).

"Buzz" = how much a model is being posted about and engaged with on social. We
store, per model per day per platform, the number of posts/videos mentioning it
and a combined engagement proxy (likes + comments + views). The dashboard and the
insight engines read a *normalized* daily buzz series (0-100, scaled to each
model's own peak — exactly like Google Trends interest) so buzz is comparable to
the other signals.

Live ingestion needs a per-platform API token (see solesight/config.py) and is
left as adapter stubs below — the realistic constraints are documented there.
Until those are wired, populate this table with `python -m scripts.seed_demo`,
which fabricates plausible buzz tied to each model's real Trends momentum.

The storage + normalization helpers here are the reusable core: seed_demo writes
through `store()`, and `signals.snapshot()` reads through `buzz_frame()` /
`platform_breakdown()`.
"""
from __future__ import annotations

import pandas as pd

from .. import config
from ..db import connect


def store(rows: list[dict]) -> int:
    """Upsert per-(model, date, platform) buzz rows."""
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """INSERT INTO social
                   (model_slug, date, platform, posts, engagement, fetched_at)
               VALUES (:model_slug, :date, :platform, :posts, :engagement, :fetched_at)
               ON CONFLICT(model_slug, date, platform) DO UPDATE SET
                   posts      = excluded.posts,
                   engagement = excluded.engagement,
                   fetched_at = excluded.fetched_at""",
            rows,
        )
    return len(rows)


def load(model_slug: str) -> pd.DataFrame:
    """Raw daily rows for one model (date, platform, posts, engagement)."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT date, platform, posts, engagement FROM social
               WHERE model_slug=? ORDER BY date""",
            (model_slug,)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def buzz_frame(model_slug: str) -> pd.DataFrame:
    """Daily total engagement across platforms, normalized to a 0-100 buzz index.

    Normalization mirrors Google Trends: divide by the model's own peak day so the
    series describes *shape* on a common 0-100 scale.
    """
    df = load(model_slug)
    if df.empty:
        return pd.DataFrame(columns=["date", "engagement", "posts", "buzz"])
    daily = (df.groupby("date", as_index=False)[["engagement", "posts"]].sum()
               .sort_values("date"))
    peak = daily["engagement"].max()
    daily["buzz"] = (daily["engagement"] / peak * 100.0) if peak else 0.0
    return daily


def platform_breakdown(model_slug: str, days: int = 14) -> dict[str, int]:
    """Recent engagement totals per platform (last `days` of available data)."""
    df = load(model_slug)
    if df.empty:
        return {}
    cutoff = df["date"].max() - pd.Timedelta(days=days)
    recent = df[df["date"] > cutoff]
    return {p: int(recent.loc[recent["platform"] == p, "engagement"].sum())
            for p in config.SOCIAL_PLATFORMS}


# --- Live ingestion adapters -------------------------------------------------
# Platform notes:
#   * bluesky   — REAL and keyless; lives in ingest/bluesky.py (posts + buzz).
#   * youtube   — Data API v3, free key (YOUTUBE_API_KEY). search.list costs 100
#     quota units per call, so we spend the 10k/day budget on the ~90 stalest
#     models: one search + one stats batch each.
#   * instagram — Graph API hashtag search is Business/Creator-only, ~30 hashtags
#     per rolling 7 days, no history. Stays modeled until that changes.
#   * tiktok    — Research API requires approval; Display API is per-user. Same.
_YT_SEARCH = "https://www.googleapis.com/youtube/v3/search"
_YT_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"


def _yt_get(url: str, params: dict) -> dict:
    import json
    import urllib.parse
    import urllib.request

    qs = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{qs}", timeout=20) as resp:
        return json.loads(resp.read())


def _fetch_youtube(model, days: int = 14) -> list[dict]:
    """Daily (posts, engagement) rows from recent videos mentioning the model."""
    import time as _time
    from datetime import datetime, timedelta, timezone

    published_after = (datetime.now(timezone.utc) - timedelta(days=days)
                       ).strftime("%Y-%m-%dT%H:%M:%SZ")
    search = _yt_get(_YT_SEARCH, {
        "part": "id,snippet", "q": model.trends_term, "type": "video",
        "order": "date", "publishedAfter": published_after, "maxResults": 25,
        "key": config.YOUTUBE_API_KEY})
    items = search.get("items", [])
    ids = [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]
    stats = {}
    if ids:
        vids = _yt_get(_YT_VIDEOS, {"part": "statistics", "id": ",".join(ids),
                                    "key": config.YOUTUBE_API_KEY})
        stats = {v["id"]: v.get("statistics", {}) for v in vids.get("items", [])}

    from collections import defaultdict
    daily = defaultdict(lambda: {"posts": 0, "eng": 0})
    now = int(_time.time())
    for it in items:
        vid = it.get("id", {}).get("videoId")
        day = it.get("snippet", {}).get("publishedAt", "")[:10]
        if not vid or not day:
            continue
        st = stats.get(vid, {})
        eng = int(st.get("viewCount", 0)) + int(st.get("likeCount", 0)) * 10
        daily[day]["posts"] += 1
        daily[day]["eng"] += eng
    return [{"model_slug": model.slug, "date": d, "platform": "youtube",
             "posts": v["posts"], "engagement": v["eng"], "fetched_at": now}
            for d, v in daily.items()]


def _purge_seeded(platform: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM social WHERE platform=? AND fetched_at=?",
            (platform, config.SEED_TAG))
    return cur.rowcount


def run() -> None:
    """Ingest live social buzz from every platform with credentials configured.

    Bluesky runs separately (ingest/bluesky.py — keyless). Here: YouTube when
    YOUTUBE_API_KEY is set; Instagram/TikTok remain modeled pending viable APIs.
    """
    import time as _time

    if not config.YOUTUBE_API_KEY:
        raise NotImplementedError(
            "No live social credentials. Set YOUTUBE_API_KEY (free key from "
            "console.cloud.google.com) for real YouTube buzz; Bluesky runs "
            "keyless via the --social stage already; Instagram/TikTok stay "
            "modeled until their APIs allow it.")

    from .. import models as _models

    rows, failed = [], 0
    for model in _models.CATALOG:
        try:
            rows.extend(_fetch_youtube(model))
        except Exception as exc:
            failed += 1
            print(f"  ! youtube failed for {model.slug}: {exc}")
            if failed >= 5:
                print("  ! youtube: too many failures (quota?) — stopping early")
                break
        _time.sleep(0.2)
    n = store(rows)
    purged = _purge_seeded("youtube") if n else 0
    print(f"  social: youtube -> {n} daily rows, {failed} failed"
          + (f", purged {purged} seeded youtube rows" if purged else ""))


if __name__ == "__main__":
    run()
