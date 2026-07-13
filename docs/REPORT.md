# SoleSight — Technical Report

**Hype, quantified.** An AI-powered consumer-intelligence platform for the
sneaker market — transformer NLP, machine-learning demand forecasting,
generative-AI insights, and an autonomous nightly data pipeline.

- Live index: **https://jairaj1111.github.io/solesight/**
- Repository: **https://github.com/jairaj1111/solesight**
- Architecture diagram: [architecture.png](architecture.png)

---

## 1. Executive summary

SoleSight tracks 90 high-interest sneaker silhouettes across 12 brands and answers one question
continuously: **how much does the market want each shoe right now?**

It ingests five demand signals (search interest, resale pricing, community
sentiment, social buzz, and a statistical forecast), distills them into a single
0–100 **Hype Score** per shoe, generates a plain-English insight for each, and
publishes the ranked index as a public website. The entire loop — ingest, score,
explain, deploy — runs unattended every night on GitHub Actions. The commit
history doubles as an audit log: one automated commit per day, for as long as
the project exists.

The system is **offline-first and degradation-tolerant**: every external source
sits behind an adapter that skips cleanly when credentials are absent and
retries politely when rate-limited. Synthetic demo data (clearly tagged) fills
any gap and deletes itself automatically the first time real data arrives from
that source.

## 2. Architecture

```
Google Trends ─┐                                     ┌─► web/data.json ─► Public Hype Index
eBay Browse ───┤                                     │      (static)      (GitHub Pages)
Reddit ────────┼─► SQLite ─► sentiment ─► Prophet ───┤
Social buzz ───┘  data store   (RoBERTa)  (30-day)   └─► Streamlit dashboard (analyst view)
                     ▲                                          
                     └── nightly GitHub Action: ingest → score → commit → deploy
```

Three layers, deliberately decoupled:

1. **Ingestion** — one adapter per source, all writing to a narrow SQLite schema.
2. **Intelligence** — sentiment scoring, forecasting, composite scoring, and
   natural-language insight generation, all reading one shared signal snapshot.
3. **Publishing** — a generated static payload consumed by two zero-backend
   frontends.

### 2.1 The registry (single source of truth)

The tracked catalog is **data, not code**: `solesight/catalog.json` holds 90
entries (12 brands, 4 categories), each carrying a stable slug
(`aj4-military-black`), display name, brand, category, Google Trends query
term, Reddit match keywords, retail MSRP, and a product-image reference.
`solesight/models.py` loads and validates it. **Every pipeline stage iterates
this registry** — adding a 91st shoe is a one-entry JSON change and requires no
other code; the nightly run picks it up automatically (stalest-first, so new
models are ingested before anything else).

### 2.2 Storage

One SQLite file (`data/solesight.db`, a few MB) with seven narrow tables:

| Table | Grain | Notes |
|---|---|---|
| `trends` | model × day | 0–100 Google search interest |
| `reddit_posts` | post × model | composite PK — one post can signal several models |
| `social` | model × day × platform | posts + engagement per platform |
| `resale` | model × day × source | price, lowest ask, volume (StockX/eBay) |
| `forecasts` | model × horizon-day × generated_at | every night's forecast is preserved |
| `insights` | model × generated_at | latest wins |
| `hype_history` | model × day | daily Hype Score snapshots → real week-over-week movers |

The DB is **committed to the repository**. Unconventional, but deliberate: the
nightly Action needs persistent state between runs, real history (resale prices
over time) must accumulate somewhere, and at this scale git is the simplest
honest database — with free versioning and a complete audit trail.

## 3. Signal ingestion

| Signal | Source & method | Status |
|---|---|---|
| Search demand | Google Trends via pytrends; explicit ~269-day window (daily resolution ceiling); partial trailing day dropped; tenacity backoff on 429s | **Live** |
| Resale pricing | eBay Browse API: OAuth client-credentials, fixed-price USD listings in the athletic-shoes category, decile-trimmed median (cuts fakes/kids-sizes/typos) | Live once free API keys are set |
| Community sentiment | PRAW scan of 6 subreddits' listings, matched locally against each model's keywords (1 scan ≫ 138 searches) | Live once free API keys are set |
| Social buzz | Per-platform daily engagement, normalized to each model's own peak (0–100, same convention as Trends) | Modeled (no free IG/TikTok API); adapter stubs documented |
| Forecast | Prophet on the trends series | **Live** |

Design rules applied uniformly: idempotent upserts (`ON CONFLICT DO UPDATE`),
volatile fields refresh without clobbering computed ones (sentiment survives
re-ingestion), and synthetic rows carry a sentinel `fetched_at` tag
(`SEED_TAG`) so each source's demo data purges itself on first real ingest.

## 4. The AI layer

### 4.1 Sentiment — transformer with a graceful fallback

Primary scorer: `cardiffnlp/twitter-roberta-base-sentiment-latest`, a RoBERTa
transformer fine-tuned for social-media sentiment. Slang-robust ("these are
fire" scores positive). The 3-class output collapses to one signed score:
`P(positive) − P(negative)` ∈ [−1, 1], stored with its argmax label. Posts are
deduplicated before inference (a post matching two models is scored once).

Fallback: a dependency-free lexicon scorer (sneaker-domain wordlist, negation
flipping, intensifiers) that activates automatically when the transformer stack
isn't installed — which is how sentiment runs inside CI without torch.

### 4.2 Forecasting — Prophet

Per model: fit on the full daily interest series (weekly seasonality on, 80%
intervals), project 30 days, and clip predictions *and* intervals to [0, 100] —
an unbounded linear trend happily walks a bounded index negative. The forecast
contributes the "peak demand date" surfaced in insights, and is refit from
scratch nightly so it always reflects the latest data.

### 4.3 Insight generation — two engines, one contract

Both engines read the same `signals.snapshot(slug)` dict and write the same
`insights` table:

- **Rule engine** (default): threshold banks compose clause functions — trend
  read, forecast direction, sentiment mood, buzz, resale strength, and a
  concrete tactic — into 3–4 deterministic sentences. Free, offline, testable.
- **LLM engine**: the same numbers prompted to OpenAI with a retail-analyst
  system prompt. Auto-selected when `OPENAI_API_KEY` exists.

Because both reason over one snapshot, they can never disagree on facts — only
on phrasing.

## 5. The Hype Score

Each component maps to 0–100, then combines as a weighted mean:

| Component | Weight | Mapping to 0–100 |
|---|---|---|
| Resale premium | 0.26 | (premium − 0.8×) / (2.6× − 0.8×) × 100 |
| Search momentum | 0.24 | 50 + (14d-vs-prior-14d %Δ) × 0.8, clamped |
| Social buzz | 0.20 | already normalized 0–100 |
| Search interest | 0.18 | Google's 0–100 index, 14-day mean |
| Sentiment | 0.12 | (score + 1) / 2 × 100 |

**Weights renormalize over available signals** — a model missing resale data is
scored fairly on the remaining four, not implicitly zeroed. Resale carries the
largest weight because price is the least fakeable signal: people voting with
money.

The score is intentionally **not** a learned model — it's an explainable
composite index (the same species as the S&P 500). Every score decomposes into
five auditable components; explainability is a product feature. (Learning the
weights from outcomes — e.g., sell-out speed — is the natural ML upgrade.)

Daily scores snapshot into `hype_history`, giving the index a memory: true
week-over-week movers rather than instantaneous momentum.

## 6. Publishing

`scripts/build_site.py` renders everything the frontend needs into **one static
`data.json`** (~200 KB): per-model scores, ranks, series (downsampled to chart
resolution), sentiment mixes, insights, and market rollups (brand aggregates,
category aggregates, movers). 

- **Public Hype Index** (`web/`) — framework-free HTML/CSS/JS. One fetch, pure
  DOM rendering: podium, ranked board, brand/category filters, movers, market
  intelligence section, per-shoe detail sheets with charts. Served by GitHub
  Pages' CDN; there is no backend to scale, break, or pay for.
- **Analyst dashboard** (`app/streamlit_app.py`) — the internal view: KPI
  tiles, demand + forecast charts, resale market charts, leaderboard, and
  multi-model comparison.

Both are pure readers of pre-computed data — page loads trigger zero external
API calls and zero model inference.

## 7. Automation

Two GitHub Actions workflows:

- **`pages.yml`** — deploys `web/` to GitHub Pages on any push touching it.
- **`refresh.yml`** — the nightly loop (09:23 UTC): install deps → ingest
  Trends → *(if keys present)* Reddit → sentiment → eBay → refit forecasts →
  regenerate insights → rebuild `data.json` → commit as `github-actions[bot]`
  → deploy Pages.

Reliability decisions worth noting:

- Optional stages are **gated on secret presence** (`if: env.X != ''`) — the
  workflow is green with zero keys configured.
- Flaky external stages are `continue-on-error` — a Google rate-limit night
  degrades to yesterday's data instead of a failed build.
- The refresh workflow deploys Pages **itself**: pushes made with the default
  `GITHUB_TOKEN` intentionally don't trigger sibling workflows (GitHub's
  recursion guard), so relying on `pages.yml` would silently never fire.
- Empty-diff nights skip the commit (`git diff --cached --quiet`).

## 8. Honesty & limitations

- **Signal provenance is explicit** (also disclosed in the site footer): search
  demand and forecasts are live; resale and community sentiment go live with
  free API keys; social buzz is modeled (tied to real Trends momentum) pending
  a viable API.
- eBay rows are **ask-side** (active listings), documented as a proxy until
  Marketplace Insights (sold-data) access is granted. StockX has no public API;
  its adapter is stubbed pending partner approval.
- Google Trends is **relative** (each model normalized to its own peak), so
  cross-model comparisons use momentum and levels, never raw magnitudes.
- Product imagery is sourced from StockX's CDN with provenance recorded per
  model; for commercial use, imagery should be licensed or replaced.
- 90 models across 12 brands is a curated index, not the whole market. The
  catalog lives in `solesight/catalog.json` — expansion is a data change, not a
  code change — and the nightly ingest refreshes the *stalest* N models per run
  (`TRENDS_MAX_PER_RUN`), so the universe can keep growing without ever
  bursting past polite API budgets. The site features the top 25; the full
  index is one click away.

## 9. Roadmap

1. **Activate live keys** — eBay + Reddit secrets flip 4 of 5 signals to real.
0. ~~Conversational analyst + launch tracking~~ — **shipped**: Ask SoleSight
   (dual-engine chat: deterministic intents + Claude tool-use over data tools)
   and Launch Radar (data-detected demand events + lifecycle stages).
2. **Brand/category intelligence depth** — richer rollups, complaint-theme
   extraction from real chatter ("sizing complaints spiking on Dunks").
3. **Learned scoring** — regress Hype components against observed outcomes
   (sell-out speed, price trajectory) to replace hand-tuned weights.
4. **Alerts** — breakout detection (score jumps N points) → email/Discord.
5. **"SoleSight for Brands"** — enterprise-facing page: trend monitoring,
   launch performance, competitive benchmarking.

## 10. Stack

Python (pandas, pytrends, PRAW, Prophet, HuggingFace transformers, Pillow) ·
SQLite · vanilla HTML/CSS/JS · Streamlit · Plotly · GitHub Actions · GitHub
Pages · OpenAI (optional, auto-detected)

---

*Report generated July 2026. The live index updates itself nightly — check the
repo's commit history for the heartbeat.*
