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


# --- Live ingestion adapters (not wired yet) --------------------------------
# Each platform gates on its own token and has real-world limits worth noting:
#   * instagram — Graph API hashtag search is Business/Creator-only, ~30 hashtags
#     per rolling 7 days, no history. Track brand/retailer accounts as a fallback.
#   * tiktok    — Research API requires approval; Display API is per-user.
#   * youtube   — Data API v3 search.list + videos.list gives mention & view counts.
def _fetch_instagram(model, timeframe):  # pragma: no cover - stub
    raise NotImplementedError("wire the Instagram Graph API here")


def _fetch_tiktok(model, timeframe):     # pragma: no cover - stub
    raise NotImplementedError("wire the TikTok API here")


def _fetch_youtube(model, timeframe):    # pragma: no cover - stub
    raise NotImplementedError("wire the YouTube Data API here")


_ADAPTERS = {
    "instagram": _fetch_instagram,
    "tiktok": _fetch_tiktok,
    "youtube": _fetch_youtube,
}


def run() -> None:
    """Live ingestion entry point — not wired yet.

    Kept as a clear signpost: implement the `_fetch_*` adapters above (each gated
    on its config token) and store their rows via `store()`. Until then, use
    `python -m scripts.seed_demo` to populate the `social` table with demo data.
    """
    raise NotImplementedError(
        "Live social ingestion isn't wired. Implement the _fetch_* adapters in "
        "solesight/ingest/social.py, or run `python -m scripts.seed_demo` for "
        "offline demo buzz data."
    )


if __name__ == "__main__":
    run()
