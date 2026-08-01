"""Infers a general audience-age lean per model from its social platform mix.

This is NOT real demographic data — none of the platforms we pull from
(bluesky, instagram, tiktok, youtube) expose viewer age for public content,
and we don't fabricate it. What we do have is each model's actual engagement
split across platforms, and each platform's own well-documented public
audience skew (the kind of age distribution Pew Research / Statista publish
for TikTok vs. YouTube vs. Bluesky). Blending the two gives a defensible
*lean* — a TikTok-heavy shoe reads younger, a Bluesky-heavy one reads older —
always reported as a broad range, never a point estimate or exact age.
"""
from __future__ import annotations

# Representative midpoint age per platform, used only as a weighting anchor —
# never shown to the user directly, only the resulting banded range is.
_PLATFORM_MIDPOINT = {
    "tiktok": 20,
    "instagram": 26,
    "youtube": 30,
    "bluesky": 32,
}

# Ordered ascending by upper bound; the first band whose bound exceeds the
# weighted midpoint wins.
_BANDS = [
    (22, "Skews Gen Z", "teens-early 20s"),
    (27, "Gen Z / young Millennial", "late teens-20s"),
    (31, "Broad — Gen Z to Millennial", "20s-30s"),
    (float("inf"), "Skews Millennial+", "late 20s-40s"),
]


def lean(platform_engagement: dict[str, int]) -> dict | None:
    """Weighted-average audience-age lean from a model's platform engagement mix.

    Returns None when there's no engagement to weight (nothing to infer from).
    """
    weighted = [(v, _PLATFORM_MIDPOINT[p]) for p, v in platform_engagement.items()
                if v and p in _PLATFORM_MIDPOINT]
    total = sum(v for v, _ in weighted)
    if not total:
        return None
    midpoint = sum(v * mp for v, mp in weighted) / total
    label, span = next((l, s) for bound, l, s in _BANDS if midpoint < bound)
    return {"label": label, "range": span}
