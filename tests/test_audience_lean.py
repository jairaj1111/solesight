"""Audience-age-lean inference tests — pure function, no network/DB."""
from __future__ import annotations

from solesight.insights import audience


def test_tiktok_heavy_skews_gen_z():
    result = audience.lean({"tiktok": 900, "instagram": 50, "youtube": 20, "bluesky": 0})
    assert result["label"] == "Skews Gen Z"


def test_bluesky_heavy_skews_millennial_plus():
    result = audience.lean({"tiktok": 10, "instagram": 20, "youtube": 30, "bluesky": 900})
    assert result["label"] == "Skews Millennial+"


def test_even_mix_lands_broad_band():
    result = audience.lean({"tiktok": 100, "instagram": 100, "youtube": 100, "bluesky": 100})
    assert result["label"] == "Broad — Gen Z to Millennial"


def test_no_engagement_returns_none():
    assert audience.lean({"tiktok": 0, "instagram": 0, "youtube": 0, "bluesky": 0}) is None
    assert audience.lean({}) is None


def test_unknown_platform_keys_are_ignored():
    result = audience.lean({"tiktok": 500, "some_new_platform": 10_000_000})
    assert result["label"] == "Skews Gen Z"


def test_result_always_includes_a_range_string_not_exact_age():
    result = audience.lean({"tiktok": 500})
    assert isinstance(result["range"], str)
    assert "-" in result["range"]
