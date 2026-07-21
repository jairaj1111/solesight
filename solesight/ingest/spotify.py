"""Spotify artist heat — a cultural-demand signal for musician-collab shoes.

Sneaker culture and music culture are the same culture. A Travis Scott or Yeezy
silhouette rides its artist's cultural wave, so an artist's Spotify standing is
a genuine leading indicator for those shoes. Spotify's free client-credentials
API exposes two clean numbers per artist:

  * popularity — Spotify's own 0-100 score (recent stream/engagement weighted)
  * followers  — total Spotify followers

We fetch each *unique* artist once and fan the result out to every shoe tied to
them (same trick as the Wikipedia adapter). Key-gated and best-effort: with no
`SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` the stage skips cleanly, and only
the ~8 artist-collab models carry the signal at all.

Context signal only — surfaced in snapshots and the UI, NOT weighted into the
Hype Score until a backtest earns it a slot.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.parse
import urllib.request
from datetime import date

from .. import config, models
from ..db import connect

_TOKEN_URL = "https://accounts.spotify.com/api/token"
_SEARCH_URL = "https://api.spotify.com/v1/search"


def _token() -> str:
    """Client-credentials OAuth token (no user login needed)."""
    if not (config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET):
        raise NotImplementedError(
            "Spotify skipped: set SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET")
    creds = f"{config.SPOTIFY_CLIENT_ID}:{config.SPOTIFY_CLIENT_SECRET}"
    basic = base64.b64encode(creds.encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(_TOKEN_URL, data=body, headers={
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())["access_token"]


def _fetch_artist(name: str, token: str) -> dict | None:
    """Search Spotify for an artist; return the best (most-followed) match."""
    q = urllib.parse.urlencode({"q": name, "type": "artist", "limit": "5"})
    req = urllib.request.Request(f"{_SEARCH_URL}?{q}",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        items = json.loads(resp.read()).get("artists", {}).get("items", [])
    if not items:
        return None
    best = max(items, key=lambda a: a.get("followers", {}).get("total", 0))
    return {"popularity": int(best.get("popularity", 0)),
            "followers": int(best.get("followers", {}).get("total", 0))}


def snapshot_fields(model_slug: str) -> dict:
    """Latest artist-heat numbers for one model (empty for non-collab shoes)."""
    m = models.get(model_slug)
    if not m.artist:
        return {"artist": None, "artist_popularity": None, "artist_followers": None}
    with connect() as conn:
        row = conn.execute(
            """SELECT popularity, followers FROM artist_heat
               WHERE artist=? ORDER BY date DESC LIMIT 1""",
            (m.artist,)).fetchone()
    return {
        "artist": m.artist,
        "artist_popularity": row["popularity"] if row else None,
        "artist_followers": row["followers"] if row else None,
    }


def run() -> None:
    """Fetch each unique collab artist once; store one row per artist per day."""
    token = _token()          # raises NotImplementedError if keys absent -> skips
    artists = sorted({m.artist for m in models.CATALOG if m.artist})
    if not artists:
        print("  spotify: no artist-tagged models in the catalog")
        return
    today, now, stored = date.today().isoformat(), int(time.time()), 0
    for name in artists:
        try:
            data = _fetch_artist(name, token)
        except Exception as exc:
            print(f"  ! spotify: {name} failed ({str(exc)[:60]})")
            continue
        if not data:
            continue
        with connect() as conn:
            conn.execute(
                """INSERT INTO artist_heat (artist, date, popularity, followers, fetched_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(artist, date) DO UPDATE SET
                       popularity=excluded.popularity,
                       followers=excluded.followers,
                       fetched_at=excluded.fetched_at""",
                (name, today, data["popularity"], data["followers"], now))
        stored += 1
        print(f"  spotify: {name} -> popularity {data['popularity']}, "
              f"{data['followers']:,} followers")
        time.sleep(0.3)
    print(f"  spotify: {stored}/{len(artists)} artists updated")


if __name__ == "__main__":
    run()
