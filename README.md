![SoleSight — The Hype Index](docs/screenshots/banner.png)

# 👟 SoleSight

**Hype, quantified — AI consumer intelligence for the sneaker market.**

[![Nightly data refresh](https://github.com/jairaj1111/solesight/actions/workflows/refresh.yml/badge.svg)](https://github.com/jairaj1111/solesight/actions/workflows/refresh.yml)
[![Deploy to GitHub Pages](https://github.com/jairaj1111/solesight/actions/workflows/pages.yml/badge.svg)](https://github.com/jairaj1111/solesight/actions/workflows/pages.yml)

An end-to-end **AI/ML data product**: transformer-based **NLP** for community
sentiment, **machine-learning time-series forecasting**, an **LLM-powered
insight engine** (generative AI with a deterministic fallback), and a fully
**autonomous data pipeline** — a scheduled agent pulls fresh Google Trends data
nightly, refits the forecasts, recomputes every Hype Score with **predictive
analytics**, and redeploys the site with no human in the loop.

📄 **[Technical report](docs/REPORT.md)** · 🗺️ **[Architecture diagram](docs/architecture.png)**

**▶ Live: [jairaj1111.github.io/solesight](https://jairaj1111.github.io/solesight/)** — the Hype Index: 90 tracked silhouettes across 12 brands, ranked by a composite 0–100 Hype Score, with the hottest 25 featured up front.

| #1 · Air Jordan 4 White Cement | #2 · ASICS Gel-Lyte III | #3 · Air Jordan 1 Bred |
| :---: | :---: | :---: |
| <img src="web/img/aj4-white-cement.png" width="220" alt="AJ4 White Cement"> | <img src="web/img/gel-lyte-iii.png" width="220" alt="ASICS Gel-Lyte III"> | <img src="web/img/aj1-bred.png" width="220" alt="AJ1 Bred"> |
| Hype **68.7** · +223% momentum | Hype **67.8** | Hype **63.4** |

SoleSight aggregates demand signals for **90 sneaker models across 12 brands**
from **Google Trends**, **Reddit**, **social buzz** (Instagram / TikTok /
YouTube), and **resale markets** (StockX / eBay). A **transformer neural network**
(RoBERTa) performs **sentiment analysis** on community chatter, **Facebook
Prophet** generates ML-based 30-day demand forecasts, and a **generative-AI
insight engine** (OpenAI LLM with a deterministic rule-based fallback)
translates the raw signals — including the **resale premium** over retail —
into plain-English marketing recommendations. Served through a public
**Hype Index** site and a **Streamlit** analyst dashboard.

`AI/ML · NLP · Transformers (HuggingFace) · LLM (OpenAI) · Predictive Analytics · Time-Series Forecasting (Prophet) · Autonomous Pipelines (GitHub Actions) · Python · SQLite · Streamlit`

## Architecture

```
Reddit API ─┐
            ├─► ingest ─► SQLite ─► sentiment (HF) ─► forecast (Prophet) ─► insights (OpenAI)
Google ─────┘                                                                     │
Trends                                                                            ▼
                                                                          Streamlit dashboard
```

| Layer      | Module                              | Responsibility                         |
|------------|-------------------------------------|----------------------------------------|
| Registry   | `solesight/models.py`               | 20+ tracked sneaker models             |
| Storage    | `solesight/db.py`                   | SQLite schema + connection helper      |
| Ingestion  | `solesight/ingest/reddit.py`        | Reddit chatter via PRAW                |
| Ingestion  | `solesight/ingest/google_trends.py` | Search interest via pytrends           |
| Ingestion  | `solesight/ingest/social.py`        | Social buzz (IG/TikTok/YouTube) + norm |
| Ingestion  | `solesight/ingest/resale.py`        | Resale price/volume (StockX/eBay)      |
| NLP        | `solesight/nlp/sentiment.py`        | Transformer sentiment scoring          |
| Forecast   | `solesight/forecast/prophet_model.py`| Prophet 30-day demand forecast        |
| Signals    | `solesight/insights/signals.py`     | Shared demand-signal snapshot          |
| Insights   | `solesight/insights/llm.py`         | OpenAI marketing recommendations       |
| Insights   | `solesight/insights/rules.py`       | Offline rule-based recommendations     |
| App        | `app/streamlit_app.py`              | Interactive dashboard (3 tabs)         |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # then fill in Reddit + OpenAI credentials
python -m scripts.init_db     # create the SQLite schema
```

## Quick demo (no API keys)

Google Trends works without credentials, but Reddit needs an API key and
sentiment needs `torch`. To see the **whole** dashboard — sentiment mix, recent
chatter, and marketing recommendations — without either, seed synthetic data:

```bash
python -m scripts.init_db
python -m scripts.run_pipeline --trends --forecast   # real trends + forecast
python -m scripts.seed_demo                          # synthetic sentiment/social/resale + insights
python -m scripts.seed_images                        # HD product photos (background removed)
python -m scripts.build_site                         # generate the Hype Index site
python -m http.server 8600 --directory web           # → open http://localhost:8600
```

`seed_demo` fabricates plausible Reddit chatter (volume and mood tied to each
model's real Trends momentum) and writes rule-based insights. It is clearly
**demo data** — re-run with `--wipe` to clear it before a live ingest.

## Front end — the Hype Index

The primary experience is a bespoke static site in **`web/`**: an editorial
"Hype Index" that ranks every model by a composite **Hype Score** (0–100 blending
resale premium, search momentum, social buzz, search interest and sentiment).
Regenerate its data anytime with `python -m scripts.build_site` (writes
`web/data.json` + copies the transparent product photos into `web/img/`), then
serve `web/` as static files. It reads only the generated JSON — no server logic.

The **Streamlit app** (`app/streamlit_app.py`) remains as the interactive
data/ops view over the same SQLite DB.

## Running the pipeline

```bash
python -m scripts.run_pipeline --all        # every stage
python -m scripts.run_pipeline --trends     # or run individual stages
python -m scripts.run_pipeline --reddit --sentiment
```

The insights stage auto-selects an engine: it uses OpenAI when `OPENAI_API_KEY`
is set, and otherwise falls back to the offline rule engine. Force the offline
engine anytime with `--offline-insights`. Sentiment scoring works the same way:
the transformer when torch is installed, a dependency-free lexicon scorer
otherwise (that's what the nightly CI uses).

## Live data sources

Every stage degrades gracefully, so the platform is honest about what's real:

| Signal | Source | Status | Activate with |
|---|---|---|---|
| Search demand | Google Trends | **Live** (nightly) | nothing — no key needed |
| Demand forecast | Prophet on trends | **Live** (nightly) | nothing |
| Community sentiment | Reddit API | Synthetic until keys set | free app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` |
| Resale (ask-side) | eBay Browse API | Synthetic until keys set | free keyset at [developer.ebay.com](https://developer.ebay.com) → `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` |
| Resale (sold) | StockX | Stubbed | partner-program approval |
| Social buzz | IG / TikTok / YouTube | Modeled | per-platform API tokens (stubs documented in `ingest/social.py`) |

Set the keys locally in `.env`, and for the nightly refresh add them as
**repository secrets** (Settings → Secrets and variables → Actions) with the
same names. The moment real data flows for a source, its synthetic demo rows
are purged automatically. eBay rows reflect **asking prices** (median of live
listings, top/bottom decile trimmed) until Marketplace Insights sold-data
access is granted.

## Dashboard

```bash
streamlit run app/streamlit_app.py
```

## Troubleshooting

- **`Retry.__init__() got an unexpected keyword argument 'method_whitelist'`** —
  pytrends 4.9.x is incompatible with urllib3 v2. We already avoid it by not
  passing `retries`/`backoff_factor` to `TrendReq` (retries run via `tenacity`
  instead), so you shouldn't hit this unless you re-add those args.
- **`Could not load libtorchaudio.so` when scoring sentiment** — a mismatched
  `torchaudio` that transformers tries to import. We don't use audio; uninstall it:
  `pip uninstall -y torchaudio`.
