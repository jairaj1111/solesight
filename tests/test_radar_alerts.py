"""Launch Radar alert tests — no network; urlopen is monkeypatched.

Uses a real catalog slug (models.CATALOG[0]) so lifecycle.detect_events sees
a genuine SneakerModel, but writes its own synthetic trends series into a
throwaway DB rather than touching the real one.
"""
from __future__ import annotations

import json

import pytest

from solesight import config, db, models
from solesight.insights import alerts


def _seed_spike(path, slug):
    db.init_db(path)
    with db.connect(path) as conn:
        for day in range(40):
            conn.execute(
                "INSERT INTO trends (model_slug, date, interest, fetched_at) "
                "VALUES (?, ?, ?, 0)", (slug, f"2026-01-{day + 1:02d}", 5.0))
        # 40 low-baseline days then one clear spike — well past both the
        # multiple (>=3x) and absolute (>=15) floors in lifecycle.py.
        conn.execute(
            "INSERT INTO trends (model_slug, date, interest, fetched_at) "
            "VALUES (?, '2026-02-10', 50.0, 0)", (slug,))


def _fake_post(monkeypatch, calls):
    monkeypatch.setattr(alerts, "_post_discord", lambda content: calls.append(content))


def test_no_webhook_configured_sends_nothing(tmp_path, monkeypatch):
    path = tmp_path / "radar.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "")
    _seed_spike(path, models.CATALOG[0].slug)

    assert alerts.run() == []


def test_fresh_spike_gets_posted_once(tmp_path, monkeypatch):
    path = tmp_path / "radar.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    slug = models.CATALOG[0].slug
    _seed_spike(path, slug)

    calls = []
    _fake_post(monkeypatch, calls)

    sent = alerts.run()

    assert len(sent) == 1
    assert sent[0]["slug"] == slug
    assert len(calls) == 1
    assert models.CATALOG[0].name in calls[0]
    assert f"#shoe-{slug}" in calls[0]


def test_same_event_is_not_reposted_on_a_later_run(tmp_path, monkeypatch):
    path = tmp_path / "radar.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    slug = models.CATALOG[0].slug
    _seed_spike(path, slug)

    calls = []
    _fake_post(monkeypatch, calls)

    first = alerts.run()
    second = alerts.run()

    assert len(first) == 1
    assert second == []
    assert len(calls) == 1   # not called again on the second run


def test_webhook_failure_does_not_mark_event_sent(tmp_path, monkeypatch):
    path = tmp_path / "radar.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    slug = models.CATALOG[0].slug
    _seed_spike(path, slug)

    import urllib.error

    def _boom(content):
        raise urllib.error.URLError("no network in tests")

    monkeypatch.setattr(alerts, "_post_discord", _boom)

    assert alerts.run() == []   # failed to send, so nothing counted as sent
    with db.connect(path) as conn:
        row = conn.execute("SELECT 1 FROM radar_alerts").fetchone()
    assert row is None   # and nothing was recorded as sent either
