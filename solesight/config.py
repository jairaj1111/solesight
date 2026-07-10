"""Central configuration for SoleSight.

Reads secrets and overrides from the environment (.env), and exposes them as
plain module-level constants so the rest of the codebase never touches os.environ
directly.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (one level above this package).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- Storage ---
DB_PATH = Path(os.getenv("SOLESIGHT_DB_PATH", PROJECT_ROOT / "data" / "solesight.db"))

# --- Reddit ---
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "solesight:v0.1")

# Subreddits we scan for sneaker/streetwear chatter.
REDDIT_SUBREDDITS = [
    "Sneakers",
    "SneakerMarket",
    "Repsneakers",
    "streetwear",
    "Nike",
    "Jordans",
]

# Listings scanned per subreddit and how many posts to pull from each.
# "new" gives recency (fresh demand), "hot" gives currently-popular chatter.
REDDIT_LISTINGS = ("new", "hot")
REDDIT_SCAN_LIMIT = 300

# --- OpenAI ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# --- Social ---
# Platforms we track for "buzz" (mention volume + engagement). Each needs its own
# API token when ingested live; offline demo data is produced by scripts/seed_demo.
SOCIAL_PLATFORMS = ("instagram", "tiktok", "youtube")
INSTAGRAM_TOKEN = os.getenv("INSTAGRAM_TOKEN", "")   # Graph API (Business/Creator)
TIKTOK_TOKEN = os.getenv("TIKTOK_TOKEN", "")         # TikTok Research/Display API
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")   # YouTube Data API v3

# --- Resale ---
# Marketplaces we track for resale price/volume. eBay has a real free API
# (Browse + Marketplace Insights); StockX requires partner-program approval.
RESALE_SOURCES = ("stockx", "ebay")
# eBay developer keyset (free at developer.ebay.com): App ID = client id,
# Cert ID = client secret. EBAY_APP_ID kept as a legacy alias.
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID", os.getenv("EBAY_APP_ID", ""))
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET", "")
STOCKX_API_KEY = os.getenv("STOCKX_API_KEY", "")     # StockX partner API

# Synthetic rows written by scripts/seed_demo.py carry this fetched_at sentinel,
# so live ingestion can purge demo data the moment real data starts flowing.
SEED_TAG = 970000000

# --- NLP ---
SENTIMENT_MODEL = os.getenv(
    "SENTIMENT_MODEL", "cardiffnlp/twitter-roberta-base-sentiment-latest"
)

# --- Google Trends ---
# Google Trends returns DAILY data only for windows under ~270 days; longer spans
# come back weekly/monthly. We stay under that threshold to keep a daily series.
TRENDS_LOOKBACK_DAYS = 269
TRENDS_REQUEST_PAUSE = 2.0   # seconds between model requests (rate-limit courtesy)

# --- Forecasting ---
FORECAST_HORIZON_DAYS = 30


def require(name: str) -> str:
    """Fetch a required env var or raise a clear error."""
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value
