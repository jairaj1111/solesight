"""SoleSight dashboard — StockX-inspired UI.

Run with:  streamlit run app/streamlit_app.py

Reads everything from the SQLite DB populated by scripts/run_pipeline.py (live) or
scripts/seed_demo.py (synthetic demo data) — the app never hits an external API,
so it loads fast and works offline.

Aesthetic: StockX-inspired marketplace look — pure black background, bold white
type, green/red bid-ask indicators, ticker-style KPIs, and clean data tables.
Layout is three tabs sharing a sidebar brand filter:
  * Overview   — deep dive on one model (KPIs, demand+forecast, sentiment, insight)
  * Leaderboard— rank every tracked model by momentum / interest / sentiment
  * Compare    — overlay the demand trajectories of several models
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from solesight import models
from solesight.db import connect
from solesight.insights import signals

st.set_page_config(page_title="SoleSight", page_icon="👟", layout="wide")

# ---------------------------------------------------------------------------
# Palette — StockX-inspired: near-black background, crisp white, green bids
# ---------------------------------------------------------------------------
PAGE     = "#09090b"          # near-pure black (body bg)
SURFACE  = "#111113"          # card surface
SURFACE2 = "#18181b"          # secondary surface / hover
BORDER   = "#27272a"          # subtle border
INK      = "#fafafa"          # primary text
MUTED    = "#71717a"          # secondary text
MUTED2   = "#a1a1aa"          # tertiary text
ACCENT   = "#00ff87"          # StockX-style neon green
ACCENT_D = "#00cc6a"          # darker green for hover states
RED      = "#ff3b30"          # negative / ask price
GREEN    = "#00ff87"          # positive / bid price
GOLD     = "#f5a623"          # highlight / premium
BLUE     = "#3b82f6"          # chart line blue

POS, NEU, NEG = GREEN, MUTED, RED

CATEGORICAL = ["#00ff87", "#3b82f6", "#f5a623", "#a855f7", "#fb923c", "#ec4899", "#06b6d4"]

BRAND_COLOR = {
    "Jordan":      "#ff3b30",
    "Nike":        "#f5a623",
    "adidas":      "#3b82f6",
    "New Balance": "#71717a",
    "ASICS":       "#a855f7",
}

PLATFORM_NAME  = {"instagram": "Instagram", "tiktok": "TikTok",   "youtube": "YouTube"}
PLATFORM_COLOR = {"instagram": "#ec4899",   "tiktok": "#06b6d4",  "youtube": "#fb923c"}
SOURCE_NAME    = {"stockx": "StockX",       "ebay": "eBay"}
SOURCE_COLOR   = {"stockx": "#00ff87",      "ebay": "#3b82f6"}


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"

_CATALOG_IDX = {m.slug: i for i, m in enumerate(models.CATALOG)}

def model_color(slug: str) -> str:
    return CATEGORICAL[_CATALOG_IDX[slug] % len(CATEGORICAL)]


# ---------------------------------------------------------------------------
# CSS — StockX aesthetic
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

      /* ---------- reset / base ---------- */
      html, body, [class*="css"] {{
          font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
      }}
      .block-container {{
          padding-top: 1.6rem !important;
          padding-bottom: 3rem !important;
          max-width: 1360px !important;
      }}
      h1,h2,h3,h4 {{ font-family: 'Inter', sans-serif !important; font-weight: 800 !important; }}

      /* ---------- top nav bar ---------- */
      .topbar {{
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0 0 1.4rem 0;
          border-bottom: 1px solid {BORDER};
          margin-bottom: 1.6rem;
      }}
      .logo-wrap {{
          display: flex;
          align-items: center;
          gap: 14px;
      }}
      .logo-icon {{
          width: 42px; height: 42px;
          background: {ACCENT};
          border-radius: 10px;
          display: flex; align-items: center; justify-content: center;
          font-size: 1.4rem;
          flex-shrink: 0;
      }}
      .logo-text {{
          font-size: 1.6rem;
          font-weight: 900;
          letter-spacing: -.04em;
          color: {INK};
          line-height: 1;
      }}
      .logo-text span {{ color: {ACCENT}; }}
      .logo-sub {{
          font-size: .68rem;
          font-weight: 600;
          letter-spacing: .18em;
          text-transform: uppercase;
          color: {MUTED};
          margin-top: 2px;
      }}
      .nav-pill {{
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: {SURFACE};
          border: 1px solid {BORDER};
          border-radius: 8px;
          padding: 6px 14px;
          font-size: .75rem;
          font-weight: 600;
          color: {MUTED2};
          letter-spacing: .04em;
      }}
      .nav-pill .dot {{
          width: 7px; height: 7px;
          border-radius: 50%;
          background: {ACCENT};
          animation: pulse 2s infinite;
      }}
      @keyframes pulse {{
          0%, 100% {{ opacity: 1; }}
          50% {{ opacity: .4; }}
      }}

      /* ---------- section headers ---------- */
      .sec {{
          font-size: .72rem;
          font-weight: 700;
          letter-spacing: .14em;
          text-transform: uppercase;
          color: {MUTED};
          margin: 2rem 0 .8rem;
          display: flex;
          align-items: center;
          gap: .6rem;
      }}
      .sec::before {{
          content: '';
          width: 3px;
          height: 14px;
          border-radius: 2px;
          background: {ACCENT};
          display: inline-block;
          flex-shrink: 0;
      }}

      /* ---------- product hero block ---------- */
      .model-header {{
          display: flex;
          flex-direction: column;
          gap: 6px;
          padding: 0 0 1rem 0;
      }}
      .brand-chip {{
          display: inline-block;
          padding: 3px 10px;
          border-radius: 6px;
          font-size: .68rem;
          font-weight: 700;
          letter-spacing: .1em;
          text-transform: uppercase;
          margin-bottom: 4px;
      }}
      .model-name {{
          font-size: 2.2rem;
          font-weight: 900;
          letter-spacing: -.04em;
          line-height: 1.1;
          color: {INK};
      }}
      .retail-line {{
          font-size: .82rem;
          font-weight: 600;
          color: {MUTED};
          margin-top: 4px;
      }}
      .retail-line span {{
          color: {INK};
          font-weight: 700;
      }}

      /* ---------- product photo (transparent PNG floats on the dark surface) ---------- */
      div[data-testid="stImage"] img {{
          background: transparent;
          filter: drop-shadow(0 12px 24px rgba(0,0,0,0.55));
      }}

      /* ---------- KPI ticker tiles ---------- */
      .ticker-row {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
          gap: 10px;
          margin: .3rem 0 .6rem;
      }}
      .ticker {{
          background: {SURFACE};
          border: 1px solid {BORDER};
          border-radius: 10px;
          padding: 14px 16px;
          position: relative;
          overflow: hidden;
          transition: border-color .15s;
      }}
      .ticker:hover {{ border-color: {ACCENT}44; }}
      .ticker-label {{
          font-size: .65rem;
          font-weight: 700;
          letter-spacing: .12em;
          text-transform: uppercase;
          color: {MUTED};
      }}
      .ticker-value {{
          font-size: 2rem;
          font-weight: 800;
          line-height: 1.1;
          color: {INK};
          margin-top: 6px;
          font-variant-numeric: tabular-nums;
          letter-spacing: -.03em;
      }}
      .ticker-delta {{
          font-size: .72rem;
          font-weight: 600;
          margin-top: 4px;
          display: flex;
          align-items: center;
          gap: 3px;
      }}
      .ticker-delta.up   {{ color: {GREEN}; }}
      .ticker-delta.down {{ color: {RED}; }}
      .ticker-delta.flat {{ color: {MUTED}; }}
      .ticker-bar {{
          position: absolute;
          bottom: 0; left: 0; right: 0;
          height: 2px;
          background: {ACCENT};
          opacity: .7;
      }}
      .ticker-bar.down {{ background: {RED}; }}
      .ticker-bar.flat {{ background: {MUTED}; opacity: .3; }}

      /* ---------- price badge (ask/bid pair) ---------- */
      .price-pair {{
          display: inline-flex;
          gap: 10px;
          align-items: center;
          background: {SURFACE};
          border: 1px solid {BORDER};
          border-radius: 10px;
          padding: 10px 16px;
          margin: .4rem 0;
      }}
      .price-box {{
          display: flex;
          flex-direction: column;
          align-items: center;
          min-width: 70px;
      }}
      .price-box-label {{
          font-size: .6rem;
          font-weight: 700;
          letter-spacing: .12em;
          text-transform: uppercase;
          color: {MUTED};
      }}
      .price-box-val {{
          font-size: 1.4rem;
          font-weight: 800;
          letter-spacing: -.02em;
          font-variant-numeric: tabular-nums;
      }}
      .price-box-val.ask {{ color: {RED}; }}
      .price-box-val.bid {{ color: {GREEN}; }}
      .price-divider {{
          width: 1px;
          height: 36px;
          background: {BORDER};
      }}

      /* ---------- insight card ---------- */
      .insight-card {{
          background: linear-gradient(135deg, {_rgba(ACCENT, 0.06)}, {SURFACE} 70%);
          border: 1px solid {_rgba(ACCENT, 0.2)};
          border-left: 3px solid {ACCENT};
          border-radius: 10px;
          padding: 18px 20px;
          font-size: .9rem;
          line-height: 1.7;
          color: {MUTED2};
      }}
      .insight-header {{
          font-size: .65rem;
          font-weight: 700;
          letter-spacing: .14em;
          text-transform: uppercase;
          color: {ACCENT};
          margin-bottom: .6rem;
          display: flex;
          align-items: center;
          gap: 6px;
      }}

      /* ---------- tabs ---------- */
      .stTabs [data-baseweb="tab-list"] {{
          gap: 4px;
          border-bottom: 1px solid {BORDER} !important;
          padding-bottom: 0;
          background: transparent !important;
      }}
      .stTabs [data-baseweb="tab"] {{
          background: transparent !important;
          border: none !important;
          border-bottom: 2px solid transparent !important;
          border-radius: 0 !important;
          padding: 10px 18px !important;
          font-size: .82rem !important;
          font-weight: 600 !important;
          color: {MUTED} !important;
          letter-spacing: .02em;
          transition: color .15s;
      }}
      .stTabs [data-baseweb="tab"]:hover {{ color: {INK} !important; }}
      .stTabs [aria-selected="true"] {{
          color: {INK} !important;
          border-bottom-color: {ACCENT} !important;
      }}
      .stTabs [aria-selected="true"] * {{ color: {INK} !important; }}
      .stTabs [data-baseweb="tab-highlight"] {{ display: none; }}
      .stTabs [data-baseweb="tab-border"] {{ display: none; }}

      /* ---------- data table overrides ---------- */
      [data-testid="stDataFrame"] {{
          border: 1px solid {BORDER} !important;
          border-radius: 10px !important;
          overflow: hidden !important;
      }}

      /* ---------- sidebar ---------- */
      [data-testid="stSidebar"] {{
          background: {SURFACE} !important;
          border-right: 1px solid {BORDER} !important;
      }}
      [data-testid="stSidebar"] .stSelectbox > div > div {{
          background: {PAGE} !important;
          border-color: {BORDER} !important;
      }}

      /* ---------- leaderboard rank badge ---------- */
      .rank-badge {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 28px; height: 28px;
          border-radius: 6px;
          font-size: .78rem;
          font-weight: 800;
          background: {SURFACE2};
          color: {MUTED2};
          border: 1px solid {BORDER};
      }}
      .rank-badge.gold   {{ background: {_rgba(GOLD, 0.15)}; color: {GOLD}; border-color: {_rgba(GOLD, 0.3)}; }}
      .rank-badge.silver {{ background: #52525222; color: #a1a1aa; border-color: #52525244; }}
      .rank-badge.bronze {{ background: {_rgba('#f97316', 0.12)}; color: #f97316; border-color: {_rgba('#f97316', 0.25)}; }}

      /* ---------- info/warning message style ---------- */
      .stAlert {{
          background: {SURFACE} !important;
          border: 1px solid {BORDER} !important;
          border-radius: 10px !important;
          color: {MUTED2} !important;
      }}

      /* ---------- expanders ---------- */
      [data-testid="stExpander"] details {{
          background: {SURFACE} !important;
          border: 1px solid {BORDER} !important;
          border-radius: 10px !important;
      }}
      [data-testid="stExpander"] summary {{
          font-weight: 600 !important;
          font-size: .82rem !important;
          color: {MUTED2} !important;
      }}
      [data-testid="stExpander"] summary:hover {{
          color: {INK} !important;
      }}

      /* ---------- scrollbar ---------- */
      ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
      ::-webkit-scrollbar-track {{ background: {PAGE}; }}
      ::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 3px; }}
      ::-webkit-scrollbar-thumb:hover {{ background: {MUTED}; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Data loaders (cached)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300)
def load_trends(slug: str) -> pd.DataFrame:
    with connect() as conn:
        rows = conn.execute(
            "SELECT date, interest FROM trends WHERE model_slug=? ORDER BY date",
            (slug,)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=300)
def load_forecast(slug: str) -> pd.DataFrame:
    with connect() as conn:
        rows = conn.execute(
            """SELECT horizon_date, yhat, yhat_lower, yhat_upper FROM forecasts
               WHERE model_slug=? AND generated_at=(
                   SELECT MAX(generated_at) FROM forecasts WHERE model_slug=?)
               ORDER BY horizon_date""",
            (slug, slug)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        df["horizon_date"] = pd.to_datetime(df["horizon_date"])
    return df


@st.cache_data(ttl=300)
def load_sentiment(slug: str) -> pd.DataFrame:
    with connect() as conn:
        rows = conn.execute(
            """SELECT created_utc, sentiment, sentiment_label, title, score, subreddit
               FROM reddit_posts WHERE model_slug=? AND sentiment IS NOT NULL
               ORDER BY created_utc""",
            (slug,)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        df["date"] = pd.to_datetime(df["created_utc"], unit="s")
    return df


@st.cache_data(ttl=300)
def load_social(slug: str) -> pd.DataFrame:
    from solesight.ingest import social
    return social.load(slug)


@st.cache_data(ttl=300)
def load_resale(slug: str) -> pd.DataFrame:
    from solesight.ingest import resale
    return resale.load(slug)


@st.cache_data(ttl=300)
def load_insight(slug: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            """SELECT summary FROM insights WHERE model_slug=?
               ORDER BY generated_at DESC LIMIT 1""",
            (slug,)).fetchone()
    return row["summary"] if row else None


@st.cache_data(ttl=300)
def load_leaderboard() -> pd.DataFrame:
    records = []
    for m in models.CATALOG:
        s = signals.snapshot(m.slug)
        records.append({
            "slug": m.slug, "Img": thumb_uri(m.slug),
            "Model": m.name, "Brand": m.brand,
            "Interest": s["recent_14d_interest"],
            "Momentum %": s["momentum_pct"],
            "Sentiment": s["avg_reddit_sentiment"],
            "Buzz": s["social_buzz_index"],
            "Resale ×": s["resale_premium"],
            "Posts": s["reddit_post_count"],
            "Forecast Δ": (None if s["forecast_start"] is None
                           else s["forecast_end_30d"] - s["forecast_start"]),
        })
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------
def sec(label: str) -> None:
    st.markdown(f"<div class='sec'>{label}</div>", unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def thumb_uri(slug: str, width: int = 150) -> str | None:
    """Base64 data URI of a small transparent thumbnail for st.dataframe images."""
    import base64
    from io import BytesIO
    from PIL import Image
    path = models.image_path(slug)
    if not path:
        return None
    im = Image.open(path).convert("RGBA")
    im.thumbnail((width, width))
    buf = BytesIO()
    im.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def hero_image(model) -> None:
    path = models.image_path(model.slug)   # local, background removed
    if path:
        st.image(path, use_container_width=True)
    else:
        color = BRAND_COLOR.get(model.brand, "#71717a")
        st.markdown(
            f"<div style='aspect-ratio:1/1; border-radius:12px; display:flex;"
            f"flex-direction:column; align-items:center; justify-content:center;"
            f"background:linear-gradient(145deg,{color}18,{SURFACE}); "
            f"border:1px solid {BORDER}; color:{MUTED}; text-align:center;'>"
            f"<div style='font-size:3rem'>👟</div>"
            f"<div style='font-size:.7rem; letter-spacing:.1em; color:{MUTED}; padding:0 10px;'>"
            f"{model.name}</div></div>", unsafe_allow_html=True)


def ticker_tile(label: str, value: str, delta: str = "", kind: str = "flat") -> str:
    bar_cls = kind
    delta_html = f"<div class='ticker-delta {kind}'>{delta}</div>" if delta else ""
    return (
        f"<div class='ticker'>"
        f"<div class='ticker-label'>{label}</div>"
        f"<div class='ticker-value'>{value}</div>"
        f"{delta_html}"
        f"<div class='ticker-bar {bar_cls}'></div>"
        f"</div>"
    )


def style_fig(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(t=24, b=16, l=4, r=4),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#a1a1aa", family="Inter, system-ui, sans-serif", size=11),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=SURFACE2,
            bordercolor=BORDER,
            font=dict(color=INK, family="Inter, sans-serif", size=12),
        ),
        legend=dict(
            orientation="h", y=1.08, x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=MUTED2),
        ),
    )
    fig.update_xaxes(
        gridcolor=_rgba(BORDER, 0.4), zeroline=False,
        linecolor=BORDER, tickfont=dict(color=MUTED, size=10),
    )
    fig.update_yaxes(
        gridcolor=_rgba(BORDER, 0.4), zeroline=False,
        linecolor=BORDER, tickfont=dict(color=MUTED, size=10),
    )
    return fig


def demand_chart(trends: pd.DataFrame, forecast: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(
        x=trends["date"], y=trends["interest"],
        name="Interest", mode="lines",
        line=dict(color=ACCENT, width=2),
        fill="tozeroy",
        fillcolor=_rgba(ACCENT, 0.06),
    )
    if not forecast.empty:
        fd = forecast["horizon_date"]
        fig.add_scatter(
            x=fd, y=forecast["yhat_upper"], mode="lines",
            line=dict(width=0), showlegend=False, hoverinfo="skip",
        )
        fig.add_scatter(
            x=fd, y=forecast["yhat_lower"], mode="lines", fill="tonexty",
            line=dict(width=0), name="80% CI",
            fillcolor=_rgba(ACCENT, 0.08), hoverinfo="skip",
        )
        fig.add_scatter(
            x=fd, y=forecast["yhat"], name="Forecast", mode="lines",
            line=dict(dash="dot", color=INK, width=1.5),
        )
        peak = forecast.loc[forecast["yhat"].idxmax()]
        fig.add_scatter(
            x=[peak["horizon_date"]], y=[peak["yhat"]],
            mode="markers+text",
            marker=dict(color=ACCENT, size=10, symbol="circle",
                        line=dict(color=PAGE, width=2)),
            text=["peak"], textposition="top center",
            textfont=dict(color=ACCENT, size=11),
            name="Peak",
        )
    fig = style_fig(fig)
    fig.update_yaxes(title_text="Interest (0–100)", title_font=dict(color=MUTED, size=11))
    return fig


def sentiment_donut(sent: pd.DataFrame) -> go.Figure:
    counts = sent["sentiment_label"].value_counts()
    order = ["positive", "neutral", "negative"]
    values = [int(counts.get(k, 0)) for k in order]
    avg = sent["sentiment"].mean()
    fig = go.Figure(go.Pie(
        labels=["Positive", "Neutral", "Negative"],
        values=values, hole=0.68,
        marker=dict(colors=[POS, NEU, NEG], line=dict(color=PAGE, width=2)),
        sort=False, textinfo="percent",
        textfont=dict(color="#09090b", size=12, family="Inter, sans-serif"),
        hovertemplate="%{label}: %{value} posts<extra></extra>",
    ))
    fig = style_fig(fig, height=260)
    fig.update_layout(
        hovermode=False,
        legend=dict(orientation="h", y=-0.1, font=dict(color=MUTED2, size=11)),
        annotations=[dict(
            text=f"<b style='font-size:22px;color:{INK}'>{avg:+.2f}</b><br>"
                 f"<span style='font-size:11px;color:{MUTED}'>avg mood</span>",
            x=0.5, y=0.5, showarrow=False,
        )],
    )
    return fig


def social_area(sdf: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for p in ["instagram", "tiktok", "youtube"]:
        sub = sdf[sdf["platform"] == p].sort_values("date")
        if sub.empty:
            continue
        fig.add_scatter(
            x=sub["date"], y=sub["engagement"],
            name=PLATFORM_NAME[p], mode="lines",
            stackgroup="one",
            line=dict(width=0.8, color=PLATFORM_COLOR[p]),
            fillcolor=_rgba(PLATFORM_COLOR[p], 0.5),
            hovertemplate="%{y:,}<extra>" + PLATFORM_NAME[p] + "</extra>",
        )
    fig = style_fig(fig, height=300)
    fig.update_yaxes(title_text="Engagements / day", title_font=dict(color=MUTED, size=11))
    return fig


def resale_chart(rdf: pd.DataFrame, retail: float | None) -> go.Figure:
    fig = go.Figure()
    for src in ["stockx", "ebay"]:
        sub = rdf[rdf["source"] == src].sort_values("date")
        if sub.empty:
            continue
        fig.add_scatter(
            x=sub["date"], y=sub["last_sale"],
            name=SOURCE_NAME[src], mode="lines",
            line=dict(color=SOURCE_COLOR[src], width=2),
            hovertemplate="$%{y:.0f}<extra>" + SOURCE_NAME[src] + "</extra>",
        )
    fig = style_fig(fig, height=320)
    if retail:
        fig.add_hline(
            y=retail, line_dash="dot", line_color=MUTED, line_width=1.5,
            annotation_text=f"  Retail ${retail:.0f}",
            annotation_position="bottom right",
            annotation_font_color=MUTED, annotation_font_size=11,
        )
    fig.update_yaxes(title_text="Last sale (USD)", title_font=dict(color=MUTED, size=11))
    return fig


# ---------------------------------------------------------------------------
# Top nav bar
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <div class="topbar">
      <div class="logo-wrap">
        <div class="logo-icon">👟</div>
        <div>
          <div class="logo-text">SOLE<span>SIGHT</span></div>
          <div class="logo-sub">Sneaker Intelligence Platform</div>
        </div>
      </div>
      <div class="nav-pill">
        <div class="dot"></div>
        Live data feed
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
all_brands = sorted({m.brand for m in models.CATALOG})
with st.sidebar:
    st.markdown(
        f"<div style='font-size:.65rem; font-weight:700; letter-spacing:.14em; "
        f"text-transform:uppercase; color:{MUTED}; margin-bottom:1rem;'>Filters</div>",
        unsafe_allow_html=True,
    )
    brands = st.multiselect(
        "Brand", options=all_brands, default=all_brands,
        help="Filter the model list and the other tabs.",
    )
    catalog = [m for m in models.CATALOG if m.brand in brands] or models.CATALOG
    slug = st.selectbox(
        "Sneaker model", options=[m.slug for m in catalog],
        format_func=lambda s: models.get(s).name,
    )
    st.divider()
    st.caption(
        "Data is read from a local SQLite DB. Populate it with "
        "`run_pipeline.py` (live) or `seed_demo.py` (offline demo)."
    )

model = models.get(slug)

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
overview_tab, board_tab, compare_tab = st.tabs(
    ["  Overview  ", "  Leaderboard  ", "  Compare  "]
)


# ===========================================================================
# OVERVIEW
# ===========================================================================
with overview_tab:
    badge_c = BRAND_COLOR.get(model.brand, "#71717a")

    img_col, title_col = st.columns([1, 2.8], vertical_alignment="top")

    with img_col:
        hero_image(model)

    with title_col:
        retail_price = models.retail(slug)

        # Brand chip + model name
        st.markdown(
            f"<div class='model-header'>"
            f"<div><span class='brand-chip' style='background:{badge_c}18;"
            f"color:{badge_c}; border:1px solid {badge_c}44'>{model.brand}</span></div>"
            f"<div class='model-name'>{model.name}</div>"
            f"<div class='retail-line'>Retail Price: "
            f"<span>${retail_price or '—'}</span></div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # Load snapshot early for price pair
        snap = signals.snapshot(slug)
        last_sale  = snap.get("resale_last_sale")
        lowest_ask = snap.get("resale_lowest_ask") or (last_sale * 1.04 if last_sale else None)

        if last_sale or lowest_ask:
            st.markdown(
                f"<div class='price-pair'>"
                f"<div class='price-box'>"
                f"  <div class='price-box-label'>Last Sale</div>"
                f"  <div class='price-box-val bid'>${last_sale:.0f}" if last_sale else
                f"<div class='price-box'><div class='price-box-label'>Last Sale</div>"
                f"<div class='price-box-val bid'>—" ,
                unsafe_allow_html=True,
            )
            st.markdown("</div></div>", unsafe_allow_html=True)

        # Quick stats inline
        prem = snap.get("resale_premium")
        rmom = snap.get("resale_momentum_pct")
        r_arrow = "▲" if (rmom or 0) > 3 else "▼" if (rmom or 0) < -3 else "▬"
        r_color = GREEN if (rmom or 0) > 3 else RED if (rmom or 0) < -3 else MUTED

        if prem:
            st.markdown(
                f"<div style='display:flex; gap:16px; margin-top:.6rem;'>"
                f"<div style='font-size:.78rem; color:{MUTED}'>"
                f"  Resale premium: <b style='color:{GREEN}'>{prem:.1f}×</b>"
                f"</div>"
                f"<div style='font-size:.78rem; color:{MUTED}'>"
                f"  Last 14d trend: <b style='color:{r_color}'>{r_arrow} {abs(rmom or 0):.0f}%</b>"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    trends    = load_trends(slug)
    forecast  = load_forecast(slug)
    sentiment = load_sentiment(slug)
    social_df = load_social(slug)
    resale_df = load_resale(slug)
    insight   = load_insight(slug)

    if "snap" not in dir():
        snap = signals.snapshot(slug)

    def arrow_kind(v):
        kind = "up" if (v or 0) > 3 else "down" if (v or 0) < -3 else "flat"
        arrow = "▲" if kind == "up" else "▼" if kind == "down" else "▬"
        return kind, arrow

    # KPI tiles
    sec("Market Signals")

    mom  = snap["momentum_pct"]
    mom_kind, mom_arrow = arrow_kind(mom)
    buzz = snap["social_buzz_index"]
    bmom = snap["social_buzz_momentum_pct"]
    b_kind, b_arrow = arrow_kind(bmom)
    prem = snap["resale_premium"]
    rmom = snap["resale_momentum_pct"]
    r_kind, r_arrow = arrow_kind(rmom)
    growth = (None if snap["forecast_start"] is None
              else snap["forecast_end_30d"] - snap["forecast_start"])
    g_kind = "up" if (growth or 0) > 0 else "down" if (growth or 0) < 0 else "flat"

    tiles_html = "".join([
        ticker_tile(
            "14-Day Interest",
            "—" if snap["recent_14d_interest"] is None else f"{snap['recent_14d_interest']:.0f}",
            "" if mom is None else f"{mom_arrow} {abs(mom):.0f}% vs prior 14d",
            mom_kind,
        ),
        ticker_tile(
            "Resale Premium",
            "—" if prem is None else f"{prem:.1f}×",
            "" if snap["resale_last_sale"] is None
            else f"${snap['resale_last_sale']:.0f} last sale",
            r_kind,
        ),
        ticker_tile(
            "Social Buzz",
            "—" if buzz is None else f"{buzz:.0f}",
            "" if bmom is None else f"{b_arrow} {abs(bmom):.0f}% · {snap['social_posts_14d']} posts",
            b_kind,
        ),
        ticker_tile(
            "Reddit Mood",
            "—" if snap["avg_reddit_sentiment"] is None
            else f"{snap['avg_reddit_sentiment']:+.2f}",
            f"{snap['reddit_post_count']} posts analyzed",
            "flat",
        ),
        ticker_tile(
            "30-Day Forecast",
            "—" if growth is None else f"{growth:+.0f}",
            "projected Δ interest",
            g_kind,
        ),
        ticker_tile(
            "Forecast Peak",
            "—" if snap["forecast_peak"] is None else f"{snap['forecast_peak']:.0f}",
            snap["forecast_peak_date"] or "",
            "flat",
        ),
    ])
    st.markdown(f"<div class='ticker-row'>{tiles_html}</div>", unsafe_allow_html=True)

    # Demand chart
    sec("Demand Signal · 30-Day Forecast")
    if trends.empty:
        st.info("No trends data yet. Run `python -m scripts.run_pipeline --trends`.")
    else:
        st.plotly_chart(demand_chart(trends, forecast), use_container_width=True)

    # Resale market
    sec("Resale Market · StockX vs eBay")
    if resale_df.empty:
        st.info(
            "No resale data yet. Run `python -m scripts.seed_demo` for offline "
            "demo prices, or wire the adapters in `ingest/resale.py`."
        )
    else:
        st.plotly_chart(resale_chart(resale_df, snap["retail_price"]),
                        use_container_width=True)
        if snap["resale_premium"] is not None:
            st.caption(
                f"Last 14 days — {snap['resale_premium']:.1f}× retail "
                f"(${snap['resale_last_sale']:.0f} avg sale vs "
                f"${snap['retail_price']} MSRP) · {snap['resale_sales_14d']} sales"
            )

    # Sentiment + insight
    left, right = st.columns([1, 1.35])
    with left:
        sec("Reddit Sentiment Mix")
        if sentiment.empty:
            st.info("No sentiment yet. Run `--reddit --sentiment`, or "
                    "`python -m scripts.seed_demo` for offline demo data.")
        else:
            st.plotly_chart(sentiment_donut(sentiment), use_container_width=True)
    with right:
        sec("AI Signal Readout")
        if insight:
            st.markdown(
                f"<div class='insight-card'>"
                f"<div class='insight-header'>🧠 Signal readout</div>"
                f"{insight}"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info("No insight yet. Run `--insights`, or `python -m scripts.seed_demo`.")

    # Social buzz
    sec("Social Buzz · Instagram / TikTok / YouTube")
    if social_df.empty:
        st.info(
            "No social data yet. Run `python -m scripts.seed_demo` for offline "
            "demo buzz, or wire the platform adapters in `ingest/social.py`."
        )
    else:
        st.plotly_chart(social_area(social_df), use_container_width=True)
        eng   = snap["social_platform_engagement"]
        total = sum(eng.values()) or 1
        shares = " · ".join(
            f"{PLATFORM_NAME[p]} {eng.get(p, 0) / total * 100:.0f}%"
            for p in ["instagram", "tiktok", "youtube"]
        )
        st.caption(f"Last 14 days by engagement share — {shares}")

    # Reddit chatter expanders
    if not sentiment.empty:
        with st.expander("🗨️  Recent Reddit chatter"):
            emoji = {"positive": "🟢", "neutral": "⚪", "negative": "🔴"}
            recent = sentiment.sort_values("date", ascending=False).head(12)
            recent = recent.assign(
                Mood=recent["sentiment_label"].map(emoji),
                Score=recent["sentiment"].round(2),
                Sub=recent["subreddit"].map(lambda s: f"r/{s}"),
            )
            st.dataframe(
                recent[["Mood", "title", "Sub", "Score", "score"]].rename(
                    columns={"title": "Post", "score": "Upvotes"}
                ),
                hide_index=True, use_container_width=True,
            )
        with st.expander("📈  Sentiment over time"):
            st.scatter_chart(
                sentiment, x="date", y="sentiment",
                color="sentiment_label", height=280,
            )


# ===========================================================================
# LEADERBOARD
# ===========================================================================
with board_tab:
    st.markdown(
        f"<div style='font-size:1.8rem; font-weight:900; letter-spacing:-.03em;"
        f"color:{INK}; margin-bottom:.3rem;'>Model Leaderboard</div>"
        f"<div style='font-size:.82rem; color:{MUTED}; margin-bottom:1.4rem;'>"
        f"Every tracked model ranked side by side. Filtered by the brands selected in the sidebar.</div>",
        unsafe_allow_html=True,
    )

    board = load_leaderboard()
    board = board[board["Brand"].isin(brands)] if brands else board

    sort_by = st.radio(
        "Rank by",
        ["Momentum %", "Interest", "Resale ×", "Buzz", "Sentiment"],
        horizontal=True,
    )
    board = board.sort_values(sort_by, ascending=False, na_position="last")

    st.dataframe(
        board[["Img", "Model", "Brand", "Interest", "Momentum %", "Resale ×",
               "Buzz", "Sentiment", "Posts", "Forecast Δ"]],
        hide_index=True, use_container_width=True,
        column_config={
            "Img": st.column_config.ImageColumn("", width="small"),
            "Interest": st.column_config.ProgressColumn(
                "14d interest", min_value=0, max_value=100, format="%.0f"),
            "Momentum %": st.column_config.NumberColumn(format="%+.0f%%"),
            "Resale ×": st.column_config.NumberColumn("Resale × retail", format="%.2f×"),
            "Buzz": st.column_config.ProgressColumn("Social buzz", min_value=0, max_value=100, format="%.0f"),
            "Sentiment": st.column_config.NumberColumn(format="%+.2f"),
            "Forecast Δ": st.column_config.NumberColumn("30d forecast Δ", format="%+.0f"),
        },
    )

    sec(f"Top movers by {sort_by}")
    top = board.head(10).sort_values(sort_by)

    # Color bars by value (green positive, red negative)
    bar_colors = [
        GREEN if (v or 0) > 0 else RED if (v or 0) < 0 else MUTED
        for v in top[sort_by]
    ]

    bar = go.Figure(go.Bar(
        x=top[sort_by], y=top["Model"], orientation="h",
        marker=dict(
            color=bar_colors,
            opacity=0.85,
            line=dict(width=0),
        ),
        width=0.62,
        hovertemplate="%{y}: %{x}<extra></extra>",
    ))
    bar = style_fig(bar, height=380)
    bar.update_layout(hovermode="closest")
    bar.update_xaxes(title_text=sort_by, title_font=dict(color=MUTED, size=11))
    st.plotly_chart(bar, use_container_width=True)


# ===========================================================================
# COMPARE
# ===========================================================================
with compare_tab:
    st.markdown(
        f"<div style='font-size:1.8rem; font-weight:900; letter-spacing:-.03em;"
        f"color:{INK}; margin-bottom:.3rem;'>Compare Demand</div>"
        f"<div style='font-size:.82rem; color:{MUTED}; margin-bottom:1.4rem;'>"
        f"Overlay the Google Trends history of several models. Each series is "
        f"normalized to its own peak, comparing <em>shape</em>, not absolute magnitude.</div>",
        unsafe_allow_html=True,
    )

    options = [m.slug for m in catalog]
    picked = st.multiselect(
        "Models to compare", options=options,
        default=options[:min(3, len(options))],
        format_func=lambda s: models.get(s).name,
    )

    if not picked:
        st.info("Pick at least one model above.")
    else:
        fig = go.Figure()
        for s in picked:
            td = load_trends(s)
            if not td.empty:
                fig.add_scatter(
                    x=td["date"], y=td["interest"],
                    mode="lines", name=models.get(s).name,
                    line=dict(color=model_color(s), width=2),
                    hovertemplate="%{y:.0f}<extra>" + models.get(s).name + "</extra>",
                )
        fig = style_fig(fig, height=460)
        fig.update_yaxes(title_text="Interest (0–100)", title_font=dict(color=MUTED, size=11))
        st.plotly_chart(fig, use_container_width=True)

        comp = load_leaderboard()
        comp = comp[comp["slug"].isin(picked)]

        st.dataframe(
            comp[["Model", "Brand", "Interest", "Momentum %", "Resale ×", "Buzz",
                  "Sentiment", "Posts"]],
            hide_index=True, use_container_width=True,
            column_config={
                "Interest": st.column_config.NumberColumn(format="%.0f"),
                "Momentum %": st.column_config.NumberColumn(format="%+.0f%%"),
                "Resale ×": st.column_config.NumberColumn(format="%.2f×"),
                "Buzz": st.column_config.NumberColumn(format="%.0f"),
                "Sentiment": st.column_config.NumberColumn(format="%+.2f"),
            },
        )
