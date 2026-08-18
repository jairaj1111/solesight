"""Launch Radar alerts — push freshly detected demand spikes to Discord.

Launch Radar (lifecycle.detect_events) already finds launch-like search-interest
spikes from the stored data; this module is just the delivery layer on top: post
each new event to a Discord webhook the first time it's seen, and remember
what's already been sent (radar_alerts table) so the same spike doesn't get
re-posted every night for as long as it stays in the freshest-10 rollup.

Zero new infrastructure: a Discord incoming webhook is a single URL (no bot,
no app, no third-party service) — the same "no new infra" spirit as how
nightly pipeline failures are already surfaced as GitHub issues rather than
email/SMS. An unset DISCORD_WEBHOOK_URL skips this stage cleanly, same as
every other key-gated adapter.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .. import config, models
from ..db import connect
from . import lifecycle

_FRESH_DAYS = 2   # only alert on events first triggered within this many days
_SITE_URL = "https://jairaj1111.github.io/solesight"


def _already_sent(conn, slug: str, date: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM radar_alerts WHERE model_slug=? AND event_date=?",
        (slug, date)).fetchone()
    return row is not None


def _mark_sent(conn, slug: str, date: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO radar_alerts (model_slug, event_date, sent_at) "
        "VALUES (?, ?, ?)", (slug, date, int(time.time())))


def _post_discord(content: str) -> None:
    body = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        config.DISCORD_WEBHOOK_URL, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=15).read()


def _message(m: models.SneakerModel, event: dict) -> str:
    retention = (f" (holding at {event['retention_pct']}% of peak since)"
                 if event["retention_pct"] is not None else "")
    return (f"**{m.name}** just spiked — search interest hit "
            f"**{event['multiple']}×** its trailing baseline on "
            f"{event['date']}{retention}. {_SITE_URL}/#shoe-{m.slug}")


def run() -> list[dict]:
    """Post any newly detected, still-fresh demand events to Discord.

    Returns the events actually sent (empty if no webhook is configured, or
    nothing new/fresh enough was found)."""
    if not config.DISCORD_WEBHOOK_URL:
        return []

    sent = []
    with connect() as conn:
        for m in models.CATALOG:
            for event in lifecycle.detect_events(m.slug):
                if event["days_ago"] > _FRESH_DAYS:
                    continue
                if _already_sent(conn, m.slug, event["date"]):
                    continue
                try:
                    _post_discord(_message(m, event))
                except (urllib.error.URLError, TimeoutError) as exc:
                    print(f"  ! discord webhook failed for {m.slug}: {str(exc)[:80]}")
                    continue
                _mark_sent(conn, m.slug, event["date"])
                sent.append({"slug": m.slug, **event})
    return sent
