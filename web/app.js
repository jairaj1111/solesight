/* SoleSight — The Hype Index. Renders everything from data.json. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

let DATA = null;
let SORT = "hype";
const ACTIVE = new Set();           // active brand filters (empty = all)
const CATS = new Set();             // active category filters (empty = all)
let STAGE_FILTER = null;            // lifecycle stage filter from Launch Radar

const fmtSigned = (v, unit = "") =>
  v == null ? "—" : (v > 0 ? "+" : "") + v + unit;
const deltaClass = (v) => (v == null ? "flat" : v > 1 ? "up" : v < -1 ? "down" : "flat");
const arrow = (v) => (v == null ? "" : v > 1 ? "▲" : v < -1 ? "▼" : "▬");
const esc = (s) => (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;");

init();

async function init() {
  DATA = await fetch("data.json?v=6").then((r) => r.json());
  document.documentElement.style.setProperty("--n", DATA.models.length);
  buildEyebrow();
  buildChips();
  buildHero();
  renderTicker();
  renderFresh();
  renderRadar();
  renderCase();
  renderBacktest();
  renderWorkedExample();
  render();
  wireControls();
  wireReveal();
  wireSheet();
}

/* ---------------- market ticker (top movers, exchange style) ---------------- */
function renderTicker() {
  const track = $("#ticker-track");
  if (!track) return;
  const picks = [...DATA.models]
    .filter((m) => m.momentum != null && m.hype != null)
    .sort((a, b) => Math.abs(b.momentum) - Math.abs(a.momentum))
    .slice(0, 14);
  const item = (m) => `
    <span class="tk-item" data-slug="${m.slug}">
      <span class="tk-name">${esc(m.name)}</span>
      <span class="tk-delta ${deltaClass(m.momentum)}">${arrow(m.momentum)} ${fmtSigned(m.momentum, "%")}</span>
      <span class="tk-hype">${m.hype}</span>
    </span><span class="tk-dot">·</span>`;
  // content twice for a seamless loop
  const half = picks.map(item).join("");
  track.innerHTML = half + half;
  $$(".tk-item", track).forEach((el) => (el.onclick = () => openSheet(el.dataset.slug)));
}

/* ---------------- launch radar (detected demand events + stages) ---------------- */
const STAGE_META = {
  emerging: { label: "Emerging", cls: "st-emerging" },
  heating:  { label: "Heating",  cls: "st-heating" },
  peaking:  { label: "Peaking",  cls: "st-peaking" },
  steady:   { label: "Steady",   cls: "st-steady" },
  cooling:  { label: "Cooling",  cls: "st-cooling" },
  dormant:  { label: "Dormant",  cls: "st-dormant" },
};
const stageBadge = (st) => {
  const m = STAGE_META[st];
  return m ? `<span class="stage-badge ${m.cls}">${m.label}</span>` : "";
};

function renderRadar() {
  const r = DATA.radar;
  if (!r) { $("#radar").style.display = "none"; return; }
  const order = ["emerging", "heating", "peaking", "steady", "cooling", "dormant"];
  $("#radar-stages").innerHTML = order
    .filter((k) => r.stages[k])
    .map((k) => `<button class="radar-stage ${STAGE_META[k].cls}" data-stage="${k}">
        <b>${r.stages[k]}</b><span>${STAGE_META[k].label}</span></button>`)
    .join("");
  // clicking a stage filters the board via the category-free view
  $$("#radar-stages .radar-stage").forEach((el) => (el.onclick = () => {
    STAGE_FILTER = STAGE_FILTER === el.dataset.stage ? null : el.dataset.stage;
    $$("#radar-stages .radar-stage").forEach((b) => b.classList.toggle("on",
      b.dataset.stage === STAGE_FILTER));
    render();
    document.querySelector("#index").scrollIntoView({ behavior: "smooth" });
  }));

  $("#radar-events").innerHTML = r.events.map((e) => {
    const m = DATA.models.find((x) => x.slug === e.slug);
    if (!m) return "";
    const when = new Date(e.date + "T12:00:00").toLocaleDateString("en-US",
      { month: "short", day: "numeric" });
    return `<div class="radar-event" data-slug="${m.slug}">
      <div class="re-img">${img(m, "")}</div>
      <div class="re-main">
        <b>${esc(m.name)}</b>
        <span>${when} · spiked <b>${e.multiple}×</b> over baseline
          (${e.baseline} → ${e.peak})</span>
      </div>
      <div class="re-side">
        ${stageBadge(m.stage)}
        <span class="re-ret">${e.retention_pct == null ? "" :
          `holding ${e.retention_pct}% of peak`}</span>
      </div>
    </div>`;
  }).join("");
  bindCards("#radar-events .radar-event");
  renderDiscovery();
}

/* ---------------- discovery: hyped shoes not yet tracked ---------------- */
function renderDiscovery() {
  const d = DATA.discovery;
  const el = $("#discovery");
  if (!el || !d || !d.length) { if (el) el.innerHTML = ""; return; }
  el.innerHTML = `
    <div class="disc-head">
      <h3>Bubbling up <span>— heating in the press, not yet indexed</span></h3>
      <p>Un-tracked silhouettes the press feeds keep naming. The index nominates
        its own next entries — real editorial attention, not opinion.</p>
    </div>
    <div class="disc-list">
      ${d.map((c) => `<div class="disc-chip">
        <b>${esc(c.name)}</b>
        <span>${c.mentions} mention${c.mentions === 1 ? "" : "s"}${c.outlets > 1 ? ` · ${c.outlets} outlets` : ""}</span>
      </div>`).join("")}
    </div>`;
}

/* ---------------- pipeline freshness (real numbers only) ---------------- */
function renderFresh() {
  const s = DATA.stats;
  if (!s) return;
  const d = new Date(DATA.generated_at * 1000);
  const when = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const live = document.querySelector(".nav-live");
  if (live) live.innerHTML = `<span class="live-dot"></span> Refreshed ${when}`;
  $("#fresh-strip").innerHTML = [
    ["Models tracked", `${s.models} across ${s.brands} brands`],
    ["Daily observations", s.daily_observations.toLocaleString("en-US")],
    ["Forecast days generated", s.forecast_days.toLocaleString("en-US")],
    ...(s.press_articles ? [["Press articles tracked", s.press_articles.toLocaleString("en-US")]] : []),
  ].map(([k, v]) => `<div class="fresh-item"><span>${k}</span><b>${v}</b></div>`).join("");
}

/* ---------------- case study (claims backed by stored data) ---------------- */
function renderCase() {
  const cs = DATA.case_study;
  const m = cs && DATA.models.find((x) => x.slug === cs.slug);
  if (!m) { $("#case").style.display = "none"; return; }
  const surgeName = new Date(cs.surge_month + "-02").toLocaleDateString("en-US", { month: "long", year: "numeric" });
  const baseSpan = `${cs.baseline_months[0]} → ${cs.baseline_months[cs.baseline_months.length - 1]}`;
  const forecastLine = m.forecast_peak_date
    ? `Prophet currently projects its demand peaking around <b>${m.forecast_peak_date}</b> —
       a public call, graded here as the data comes in.`
    : `Its first 30-day forecast generates on the next nightly run — the call
       will appear here and get graded in public.`;
  $("#case-body").innerHTML = `
    <div class="case-card reveal">
      <div class="case-img">${img(m, "")}</div>
      <div class="case-text">
        <div class="case-kicker">${esc(m.brand)} · every number below is reproducible from the stored dataset</div>
        <h3>${esc(m.name)}</h3>
        <p><b>What the signals showed.</b> Through ${baseSpan}, search interest
        averaged just <b>${cs.baseline_avg}</b> on its own 0–100 scale — a quiet
        baseline. In ${surgeName} it surged to an average of
        <b>${cs.surge_avg}</b> — a <b>${cs.surge_multiple}×</b> jump — and has
        held elevated since.</p>
        <p><b>What SoleSight did.</b> The day this model entered the index, its
        14-day momentum (${fmtSigned(m.momentum, "%")}) and sustained intensity
        scored it <b>${m.hype} Hype</b> — ranked <b>#${m.rank}</b> of
        ${DATA.models.length} at build time, ahead of every established
        favorite.</p>
        <p><b>What happens next.</b> ${forecastLine}</p>
      </div>
    </div>`;
}

/* ---------------- backtest: does the signal predict? ---------------- */
function renderBacktest() {
  const b = DATA.backtest;
  const el = $("#predict");
  if (!el) return;
  if (!b || !b.ready) {           // not enough history yet — say so, don't fake it
    $("#bt-body").innerHTML = `<p class="bt-note">Backtest accrues as history
      builds — ${b ? b.samples : 0} samples so far, needs a few hundred. Check back.</p>`;
    return;
  }
  $("#bt-body").innerHTML = `
    <div class="bt-grid reveal">
      <div class="bt-hero">
        <div class="bt-big">${b.hit_rate}%</div>
        <div class="bt-cap">of rising-flagged shoes still held their gain
          <b>${b.horizon_days} days later</b></div>
      </div>
      <div class="bt-compare">
        <div class="bt-bar-row"><span>SoleSight "rising" calls</span>
          <div class="bt-track"><div class="bt-fill acid" style="width:${b.hit_rate}%"></div></div>
          <b>${b.hit_rate}%</b></div>
        <div class="bt-bar-row"><span>Base rate (any shoe, chance)</span>
          <div class="bt-track"><div class="bt-fill" style="width:${b.base_rate}%"></div></div>
          <b>${b.base_rate}%</b></div>
        <div class="bt-lift">▲ +${b.lift} points over chance ·
          correlation ${b.correlation}</div>
      </div>
    </div>
    <div class="bt-foot">
      <span><b>${b.samples.toLocaleString("en-US")}</b> historical checks</span>
      <span><b>${b.rising_calls.toLocaleString("en-US")}</b> rising calls tested</span>
      <span><b>${b.models}</b> models · full search history</span>
    </div>
    <p class="bt-note">Method: for every model and every day with enough history,
      compare 14-day momentum against whether demand stayed above its pre-spike
      baseline ${b.horizon_days} days later. This validates the <b>search-demand</b>
      signal — the score's heaviest input. The resale-premium backtest activates
      once ${b.horizon_days} days of resale history accrue${b.resale_ready ? " — now live" : ` (currently ${b.resale_days})`}.</p>`;
}

/* ---------------- worked example (live numbers, real formula) ---------------- */
function renderWorkedExample() {
  const box = $("#worked-example");
  if (!box) return;
  const W = { resale: 0.26, momentum: 0.24, buzz: 0.20, interest: 0.18, sentiment: 0.12 };
  const m = DATA.models[0];
  const clamp = (x) => Math.max(0, Math.min(100, x));
  const comp = {
    resale: m.resale_premium == null ? null : clamp((m.resale_premium - 0.8) / 1.8 * 100),
    momentum: m.momentum == null ? null : clamp(50 + m.momentum * 0.8),
    buzz: m.buzz == null ? null : clamp(m.buzz),
    interest: m.interest == null ? null : clamp(m.interest),
    sentiment: m.sentiment == null ? null : clamp((m.sentiment + 1) / 2 * 100),
  };
  const raw = {
    resale: m.resale_premium == null ? "—" : `${m.resale_premium}× retail`,
    momentum: m.momentum == null ? "—" : fmtSigned(m.momentum, "%"),
    buzz: m.buzz == null ? "—" : `${m.buzz}/100`,
    interest: m.interest == null ? "—" : `${m.interest}/100`,
    sentiment: m.sentiment == null ? "—" : `${m.sentiment > 0 ? "+" : ""}${m.sentiment}`,
  };
  const names = { resale: "Resale premium", momentum: "Search momentum",
                  buzz: "Social buzz", interest: "Search intensity",
                  sentiment: "Community mood" };
  let num = 0, den = 0;
  const rows = Object.keys(W).map((k) => {
    const v = comp[k];
    if (v != null) { num += W[k] * v; den += W[k]; }
    return `<tr><td>${names[k]}</td><td>${raw[k]}</td>
      <td>${v == null ? "—" : v.toFixed(0)}</td><td>×${W[k]}</td></tr>`;
  }).join("");
  const score = den ? num / den : null;
  box.innerHTML = `
    <p class="tm-model">${esc(m.name)} — today's #1</p>
    <table class="tm-table">
      <thead><tr><th>Signal</th><th>Raw</th><th>0–100</th><th>Weight</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="tm-final">Weighted mean → <b>${score == null ? "—" : score.toFixed(1)} Hype</b>
    ${Math.abs((score ?? 0) - (m.hype ?? 0)) < 0.4 ? "— matching the published score." : ""}</p>`;
}

function buildEyebrow() {
  const d = new Date(DATA.generated_at * 1000);
  const wk = d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
  $("#hero-eyebrow").textContent = `The Hype Index · Week of ${wk}`;
}

/* ---------------- filtering + sorting ---------------- */
function view() {
  let list = DATA.models.filter((m) =>
    (ACTIVE.size === 0 || ACTIVE.has(m.brand)) &&
    (CATS.size === 0 || CATS.has(m.category)) &&
    (STAGE_FILTER == null || m.stage === STAGE_FILTER));
  const key = SORT;
  list = [...list].sort((a, b) => (b[key] ?? -1e9) - (a[key] ?? -1e9));
  return list;
}

function chipRow(boxSel, values, set, allLabel) {
  const box = $(boxSel);
  const mk = (label, val) => {
    const el = document.createElement("button");
    el.className = "chip" + (val === null && set.size === 0 ? " on" : "");
    el.textContent = label;
    el.onclick = () => {
      if (val === null) set.clear();
      else set.has(val) ? set.delete(val) : set.add(val);
      $$(".chip", box).forEach((c) => c.classList.remove("on"));
      if (set.size === 0) box.firstChild.classList.add("on");
      else $$(".chip", box).forEach((c) => { if (set.has(c.dataset.val)) c.classList.add("on"); });
      render();
    };
    if (val) el.dataset.val = val;
    return el;
  };
  box.appendChild(mk(allLabel, null));
  values.forEach((v) => box.appendChild(mk(v[0].toUpperCase() + v.slice(1), v)));
}

function buildChips() {
  chipRow("#brand-chips", DATA.brands, ACTIVE, "All brands");
  chipRow("#cat-chips", DATA.categories || [], CATS, "All categories");
}

/* ---------------- hero (overall #1) ---------------- */
function buildHero() {
  const m = DATA.models.find((x) => x.rank === 1);
  const photo = m.has_360
    ? `<div class="hf-360" id="hf-360">${img(m, "")}
         <span class="hf-360-pill">↻ 360° — drag to spin</span></div>`
    : img(m, "");
  $("#hero-feature").innerHTML = `
    <div class="hf-glow"></div>
    <div class="hf-rankpill">#1 · Most hyped</div>
    <div class="hf-img">${photo}</div>
    <div class="hf-meta">
      <div><div class="hf-brand">${esc(m.brand)}</div>
        <div class="hf-name">${esc(m.name)}</div></div>
      <div class="hf-score"><b data-count="${m.hype}">0</b><span>Hype score</span></div>
    </div>
    <div class="hf-stats">
      <div class="hf-stat"><b>${m.resale_premium ?? "—"}×</b><span>Resale</span></div>
      <div class="hf-stat"><b>${fmtSigned(m.momentum, "%")}</b><span>Momentum</span></div>
      <div class="hf-stat"><b>${m.buzz ?? "—"}</b><span>Buzz</span></div>
      <div class="hf-stat"><b>$${m.resale_last ?? "—"}</b><span>Last sale</span></div>
    </div>`;
  $("#hero-feature").onclick = () => { if (!SPIN_DRAGGED) openSheet(m.slug); };
  countUp($("#hero-feature [data-count]"));
  if (m.has_360) init360(m.slug);
}

/* ---------------- 360° hero viewer ---------------- */
let SPIN_DRAGGED = false;   // suppress the card's click-to-open after a drag

function init360(slug) {
  const box = $("#hf-360");
  const imgEl = box.querySelector("img");
  if (!imgEl) return;
  const N = 36;
  const frames = [];
  let loaded = 0, frame = 0, auto = null, ready = false;

  // lazy-preload all frames after first paint; upgrade once complete
  for (let i = 1; i <= N; i++) {
    const im = new Image();
    im.src = `img360/${slug}/f${String(i).padStart(2, "0")}.png`;
    im.onload = () => { if (++loaded === N) { ready = true; startAuto(); } };
    frames.push(im);
  }
  const show = (i) => {
    frame = ((i % N) + N) % N;
    imgEl.src = frames[frame].src;
  };
  const startAuto = () => {
    if (auto || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    auto = setInterval(() => show(frame + 1), 110);
  };
  const stopAuto = () => { clearInterval(auto); auto = null; };

  let dragging = false, startX = 0, startFrame = 0;
  box.style.touchAction = "pan-y";
  box.addEventListener("pointerdown", (e) => {
    if (!ready) return;
    dragging = true; SPIN_DRAGGED = false;
    startX = e.clientX; startFrame = frame;
    stopAuto();
    box.setPointerCapture(e.pointerId);
  });
  box.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - startX;
    if (Math.abs(dx) > 6) SPIN_DRAGGED = true;
    show(startFrame + Math.round(dx / 12));   // ~12px per 10° frame
  });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    setTimeout(() => (SPIN_DRAGGED = false), 80);
    setTimeout(startAuto, 2600);
  };
  box.addEventListener("pointerup", end);
  box.addEventListener("pointercancel", end);
  box.addEventListener("mouseenter", stopAuto);
  box.addEventListener("mouseleave", () => ready && !dragging && startAuto());
}

/* ---------------- render podium + board + movers ---------------- */
// The index features the top FEATURED models by the active sort; the rest of
// the universe stays one click away ("Show the full index").
const FEATURED = 25;
let SHOW_ALL = false;

function render() {
  const list = view();
  renderPodium(list.slice(0, 3));
  const rest = SHOW_ALL ? list.slice(3) : list.slice(3, FEATURED);
  renderBoard(rest);
  renderBoardFoot(list.length);
  renderMovers();
  renderMarket();
}

function renderBoardFoot(total) {
  const foot = $("#board-foot");
  if (total <= FEATURED) { foot.innerHTML = ""; return; }
  foot.innerHTML = SHOW_ALL
    ? `<button class="btn btn-ghost" id="show-toggle">Show featured top ${FEATURED} only</button>`
    : `<button class="btn btn-ghost" id="show-toggle">Show the full index — all ${total} models</button>`;
  $("#show-toggle").onclick = () => { SHOW_ALL = !SHOW_ALL; render(); };
}

function renderPodium(top) {
  $("#podium").innerHTML = top.map((m) => `
    <div class="pod reveal" data-slug="${m.slug}">
      <div class="pod-glow"></div>
      <div class="pod-rank">${m.rank}</div>
      <div class="pod-img">${img(m, "")}</div>
      <div class="pod-brand">${esc(m.brand)}</div>
      <div class="pod-name">${esc(m.name)}</div>
      <div class="pod-foot">
        <div class="pod-score">${m.hype ?? "—"}<small>Hype</small></div>
        <div class="delta ${deltaClass(m.momentum)}">${arrow(m.momentum)} ${fmtSigned(m.momentum, "%")}</div>
      </div>
    </div>`).join("");
  bindCards("#podium .pod");
  wireReveal();
}

function renderBoard(rest) {
  $("#board").innerHTML = rest.map((m) => `
    <div class="row" data-slug="${m.slug}">
      <div class="row-rank">${m.rank}</div>
      <div class="row-thumb">${img(m, "")}</div>
      <div class="row-name"><b>${esc(m.name)}</b><span>${esc(m.brand)}</span></div>
      <div class="row-spark col-hide">${spark(m.trend)}</div>
      <div class="row-metric col-hide"><b>${m.resale_premium ?? "—"}×</b><span>Resale</span></div>
      <div class="row-metric"><span class="delta ${deltaClass(m.momentum)}">${arrow(m.momentum)} ${fmtSigned(m.momentum, "%")}</span><span>Momentum</span></div>
      <div class="row-hype"><b>${m.hype ?? "—"}</b></div>
    </div>`).join("");
  bindCards("#board .row");
}

function renderMovers() {
  // Once the nightly snapshots have accrued a week of history, movers rank by
  // real 7-day Hype Score change; until then, search momentum stands in.
  const hasHist = DATA.models.some((m) => m.hype_delta_7d != null);
  const key = hasHist ? "hype_delta_7d" : "momentum";
  const unit = hasHist ? "" : "%";
  $("#movers-sub").textContent = hasHist
    ? "Biggest 7-day Hype Score changes, up and down."
    : "Biggest search-momentum swings, up and down (7-day hype deltas unlock as nightly history accrues).";
  const ranked = [...DATA.models].filter((m) => m[key] != null)
    .sort((a, b) => b[key] - a[key]);
  const picks = [...ranked.slice(0, 2).map((m) => [m, "Heating up"]),
                 ...ranked.slice(-2).reverse().map((m) => [m, "Cooling off"])];
  $("#movers-grid").innerHTML = picks.map(([m, tag]) => `
    <div class="mover" data-slug="${m.slug}">
      <div class="mover-tag ${tag === "Heating up" ? "hot" : "cold"}">${tag}</div>
      ${img(m, "")}
      <div class="mover-name">${esc(m.name)}</div>
      <div class="mover-delta delta ${deltaClass(m[key])}">${arrow(m[key])} ${fmtSigned(m[key], unit)}</div>
    </div>`).join("");
  bindCards("#movers-grid .mover");
}

/* ---------------- market intelligence ---------------- */
function renderMarket() {
  const mkt = DATA.market || {};
  const rows = mkt.brands || [];
  const maxHype = Math.max(...rows.map((r) => r.avg_hype || 0), 1);
  $("#mkt-brands").innerHTML = `
    <div class="mkt-row mkt-head">
      <div>Brand</div><div>Models</div><div class="mkt-wide">Avg hype</div>
      <div>Resale ×</div><div>Momentum</div><div>Top 10</div>
    </div>` + rows.map((r) => `
    <div class="mkt-row">
      <div class="mkt-brand">${esc(r.name)}</div>
      <div>${r.models}</div>
      <div class="mkt-wide"><div class="mkt-bar">
        <div class="mkt-fill" style="width:${((r.avg_hype || 0) / maxHype) * 100}%"></div>
      </div><b>${r.avg_hype == null ? "—" : r.avg_hype.toFixed(1)}</b></div>
      <div>${r.avg_premium == null ? "—" : r.avg_premium.toFixed(2) + "×"}</div>
      <div><span class="delta ${deltaClass(r.avg_momentum)}">${arrow(r.avg_momentum)} ${fmtSigned(r.avg_momentum == null ? null : Math.round(r.avg_momentum), "%")}</span></div>
      <div>${r.top10}/${r.models}</div>
    </div>`).join("");

  $("#mkt-cats").innerHTML = (mkt.categories || []).map((c) => `
    <div class="mkt-cat">
      <div class="mkt-cat-name">${esc(c.name)}</div>
      <div class="mkt-cat-hype">${c.avg_hype == null ? "—" : c.avg_hype.toFixed(1)}</div>
      <div class="mkt-cat-sub">avg hype · ${c.models} model${c.models === 1 ? "" : "s"}</div>
    </div>`).join("");
}

function bindCards(sel) {
  $$(sel).forEach((el) => (el.onclick = () => openSheet(el.dataset.slug)));
}

function img(m, cls) {
  if (!m.img) return `<div class="noimg">👟</div>`;
  return `<img class="${cls}" src="${m.img}" alt="${esc(m.name)}" loading="lazy" />`;
}

/* ---------------- controls / reveal ---------------- */
function wireControls() {
  $$("#sort-seg button").forEach((b) => (b.onclick = () => {
    SORT = b.dataset.sort;
    $$("#sort-seg button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    render();
  }));
}

function wireReveal() {
  const io = new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  }), { threshold: 0.12 });
  $$(".reveal:not(.in)").forEach((el) => io.observe(el));
}

function countUp(el) {
  if (!el) return;
  const target = parseFloat(el.dataset.count) || 0;
  const t0 = performance.now(), dur = 1100;
  const tick = (t) => {
    const p = Math.min(1, (t - t0) / dur);
    const e = 1 - Math.pow(1 - p, 3);
    el.textContent = (target * e).toFixed(1);
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/* ---------------- sparkline ---------------- */
function spark(series) {
  if (!series || series.length < 2) return "";
  const vs = series.map((p) => p.v), min = Math.min(...vs), max = Math.max(...vs) || 1;
  const W = 120, H = 34, pad = 3;
  const pts = series.map((p, i) => {
    const x = pad + (i / (series.length - 1)) * (W - 2 * pad);
    const y = H - pad - ((p.v - min) / (max - min || 1)) * (H - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}"><polyline class="spark-line" points="${pts}"/></svg>`;
}

/* ---------------- detail sheet ---------------- */
function wireSheet() {
  $("#sheet-backdrop").onclick = closeSheet;
  document.addEventListener("keydown", (e) => e.key === "Escape" && closeSheet());
}
function closeSheet() {
  $("#sheet").classList.remove("on");
  $("#sheet").setAttribute("aria-hidden", "true");
  $("#sheet-backdrop").classList.remove("on");
}
const STORE_NAMES = {
  "kith.com": "Kith", "undefeated.com": "Undefeated",
  "www.a-ma-maniere.com": "A Ma Mani\u00e8re",
  "store.unionlosangeles.com": "Union LA", "extrabutterny.com": "Extra Butter",
  "shopnicekicks.com": "Nice Kicks", "packershoes.com": "Packer",
  "notre-shop.com": "Notre", "xhibition.co": "Xhibition",
  "bdgastore.com": "Bodega", "cncpts.com": "Concepts", "feature.com": "Feature",
  "lapstoneandhammer.com": "Lapstone & Hammer",
  "socialstatuspgh.com": "Social Status", "sneakerpolitics.com": "Sneaker Politics",
};

/* Price ladder: retail tick, boutique-shelf dots, eBay median-ask diamond
   on one number line — the arbitrage view. Skips when there's nothing to place. */
function priceLadder(m) {
  const shelf = (m.stockists || []).filter((s) => s.price);
  const ebay = m.resale_last;
  if (!m.retail || (!shelf.length && !ebay)) return "";
  const W = 500, H = 110, L = 14, R = 14, base = 70;
  const vals = [m.retail, ...(ebay ? [ebay] : []), ...shelf.map((s) => s.price)];
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.08, 8);
  const X = (v) => L + ((v - (lo - pad)) / ((hi + pad) - (lo - pad))) * (W - L - R);
  let prevX = -99, lift = 0;
  const placed = shelf.map((s) => ({ x: X(s.price), s })).sort((a, b) => a.x - b.x)
    .map((d) => {
      lift = d.x - prevX < 11 ? lift + 11 : 0;
      prevX = d.x;
      return { ...d, lift };
    });
  const dots = placed.map((d) => `<g><title>${esc(STORE_NAMES[d.s.store] || d.s.store)} — $${Math.round(d.s.price)}</title>
        <circle cx="${d.x}" cy="${base - d.lift}" r="11" fill="transparent"/>
        <circle cx="${d.x}" cy="${base - d.lift}" r="5" fill="var(--pos)" stroke="var(--paper)" stroke-width="2"/></g>`).join("");
  const rx = X(m.retail);
  const ex = ebay ? X(ebay) : 0;
  // keep the eBay label clear of any dot stack near it
  const liftNear = ebay ? Math.max(0, ...placed.filter((d) => Math.abs(d.x - ex) < 70).map((d) => d.lift)) : 0;
  // name the stores that anchor the range (all of them when there are ≤3);
  // the rest stay on hover and in the stockist list above
  let toLabel = placed.length <= 3 ? placed
    : [placed[0], placed[placed.length - 1]].filter((d, i, a) => a.indexOf(d) === i);
  toLabel = toLabel.filter((d, i) => {
    const prev = toLabel[i - 1];
    return !prev || d.x - prev.x >= 110 || Math.abs(d.lift - prev.lift) >= 22;
  });
  const eLabY = base - 18 - liftNear;
  const storeLabels = toLabel.map((d) => {
    const y = base - d.lift - 13;
    if (ebay && Math.abs(d.x - ex) < 95 && Math.abs(y - eLabY) < 13) return "";
    const name = (STORE_NAMES[d.s.store] || d.s.store).toUpperCase();
    const lab = `${name} $${Math.round(d.s.price)}`;
    const half = lab.length * 2.9;
    return `<text x="${Math.min(Math.max(d.x, half + 4), W - half - 4)}" y="${y}" text-anchor="middle"
      class="pl-store">${esc(lab)}</text>`;
  }).join("");
  const ebaySvg = !ebay ? "" : `
    <g><title>eBay median ask — $${Math.round(ebay)}</title>
      <circle cx="${ex}" cy="${base}" r="12" fill="transparent"/>
      <path d="M ${ex} ${base - 8} l 8 8 l -8 8 l -8 -8 Z" fill="var(--ebay)" stroke="var(--paper)" stroke-width="2"/></g>
    <text x="${Math.min(Math.max(ex, 58), W - 58)}" y="${base - 18 - liftNear}" text-anchor="middle" class="pl-lab">EBAY ASK $${Math.round(ebay)}</text>`;
  return `<h4>Where it trades</h4>
    <svg class="chart pl" viewBox="0 0 ${W} ${H}">
      <line x1="${L}" y1="${base}" x2="${W - R}" y2="${base}" stroke="var(--line-2)" stroke-width="2"/>
      <line x1="${rx}" y1="${base - 12}" x2="${rx}" y2="${base + 12}" stroke="var(--ink-3)" stroke-width="2.5"/>
      <text x="${Math.min(Math.max(rx, 44), W - 44)}" y="${base + 30}" text-anchor="middle" class="pl-lab">RETAIL $${m.retail}</text>
      ${dots}${storeLabels}${ebaySvg}
    </svg>
    <div class="legend"><span><i style="background:var(--ink-3)"></i>Retail</span>${shelf.length
      ? `<span><i style="background:var(--pos)"></i>Boutique shelves (${shelf.length})</span>` : ""}${ebay
      ? `<span><i style="background:var(--ebay)"></i>eBay median ask</span>` : ""}</div>`;
}

const EVENT_LABELS = {
  release: "release news", restock: "restock", collab: "collab",
  rumor: "leaks & rumors", market: "resale market", review: "style & reviews",
  coverage: "coverage",
};

function openSheet(slug) {
  const m = DATA.models.find((x) => x.slug === slug);
  if (!m) return;
  const bar = (lab, val, acid) => `
    <div class="bar-row"><div class="lab">${lab}</div>
      <div class="bar-track"><div class="bar-fill ${acid ? "acid" : ""}" data-w="${val ?? 0}"></div></div>
      <div class="bar-val">${val == null ? "—" : Math.round(val)}</div></div>`;
  const sentPct = m.sentiment == null ? null : ((m.sentiment + 1) / 2) * 100;
  const resalePct = m.resale_premium == null ? null
    : Math.max(0, Math.min(100, ((m.resale_premium - 0.8) / 1.8) * 100));
  const mom = m.momentum == null ? null : Math.max(0, Math.min(100, 50 + m.momentum * 0.8));

  $("#sheet").innerHTML = `
    <button class="sheet-close" onclick="(${closeSheet.toString()})()">×</button>
    <div class="sheet-eyebrow">Rank #${m.rank} · ${esc(m.brand)} ${stageBadge(m.stage)}</div>
    <div class="sheet-title">${esc(m.name)}</div>
    <div class="sheet-hype"><b>${m.hype ?? "—"}</b><span class="of">/ 100 hype</span>
      <span class="delta ${deltaClass(m.momentum)}" style="margin-left:auto">${arrow(m.momentum)} ${fmtSigned(m.momentum, "%")} search</span></div>
    <div class="sheet-photo">${img(m, "")}</div>

    <div class="sheet-facts">
      ${m.stores_stocking ? `<details class="sf-details">
        <summary class="sf"><b>${m.stores_stocking}</b><span>boutiques stocking${m.sellout_rate != null ? ` · ${Math.round(m.sellout_rate * 100)}% of sizes sold out` : ""} <em class="sf-more">which stores?</em></span></summary>
        <div class="stockists">${(m.stockists || []).map((s) => {
          const pct = s.total ? s.avail / s.total : 0;
          const cls = pct === 0 ? "gone" : pct < 0.34 ? "low" : "ok";
          return `<div class="stk-row">
            <span class="stk-name">${STORE_NAMES[s.store] || s.store}</span>
            <span class="stk-price">${s.price ? "$" + Math.round(s.price) : ""}</span>
            <span class="stk-bar"><i class="${cls}" style="width:${Math.round(pct * 100)}%"></i></span>
            <span class="stk-sizes ${cls}">${pct === 0 ? "sold out" : s.avail + "/" + s.total + " sizes"}</span>
          </div>`; }).join("")}</div>
      </details>` : `<div class="sf sf-none"><b>0</b><span>of 15 tracked boutiques have it on shelves — sold through at retail or never a general release</span></div>`}
      ${m.wiki_views ? `<div class="sf"><b>${m.wiki_views.toLocaleString()}</b><span>Wikipedia views/day${m.wiki_momentum != null ? ` · ${fmtSigned(m.wiki_momentum, "%")}` : ""} (silhouette)</span></div>` : ""}
    </div>

    ${priceLadder(m)}

    <h4>Signal breakdown</h4>
    <div class="bars">
      ${bar("Hype", m.hype, true)}
      ${bar("Interest", m.interest)}
      ${bar("Momentum", mom)}
      ${bar("Buzz", m.buzz)}
      ${bar("Sentiment", sentPct)}
      ${bar("Resale", resalePct)}
    </div>

    ${m.sent_summary ? `
    <h4>Community pulse</h4>
    <div class="pulse">
      <div class="pulse-pct ${m.sent_summary.positive_pct >= 50 ? "up" : "down"}">${m.sent_summary.positive_pct}%<span>positive</span></div>
      <div class="pulse-notes">
        <div>${m.sent_summary.posts} scored posts</div>
        ${m.sent_summary.praise ? `<div>Praised for <b>${esc(m.sent_summary.praise)}</b></div>` : ""}
        ${m.sent_summary.complaint ? `<div>Top complaint: <b>${esc(m.sent_summary.complaint)}</b></div>` : ""}
      </div>
    </div>` : ""}

    ${(m.press && m.press.length) ? `
    <h4>In the press</h4>
    <div class="press-count">${m.press_14d
      ? `<b>${m.press_14d}</b> stor${m.press_14d === 1 ? "y" : "ies"} in 14 days${m.press_outlets > 1 ? ` · ${m.press_outlets} outlets` : ""}${m.press_momentum != null ? ` · <span class="delta ${deltaClass(m.press_momentum)}">${arrow(m.press_momentum)} ${fmtSigned(m.press_momentum, "%")} coverage</span>` : ""}${m.press_event && m.press_event !== "coverage" ? ` · mostly ${EVENT_LABELS[m.press_event] || m.press_event}` : ""}`
      : `Latest coverage — live via Google News &amp; sneaker-press RSS`}</div>
    <div class="press-list">
      ${m.press.map((p) => `<a class="press-row" href="${esc(p.url)}" target="_blank" rel="noopener">
        <span class="press-title">${esc(p.title)}</span>
        <span class="press-meta">${esc(p.source || "Google News")} · ${p.published}${p.event && p.event !== "coverage" ? ` <i class="press-tag pt-${p.event}">${EVENT_LABELS[p.event] || p.event}</i>` : ""}</span>
      </a>`).join("")}
    </div>` : ""}

    <h4>Marketing readout</h4>
    <div class="sheet-insight">${esc(m.insight) || "No insight available."}</div>

    <h4>Demand &amp; 30-day forecast</h4>
    ${demandChart(m)}

    <h4>Resale ${(m.resale_series || {}).stockx?.length ? "· StockX vs eBay" : "· live eBay asks"}</h4>
    ${resaleChart(m)}
    <div class="legend">
      ${(m.resale_series || {}).stockx?.length ? `<span><i style="background:var(--stockx)"></i>StockX</span>` : ""}
      ${(m.resale_series || {}).ebay?.length ? `<span><i style="background:var(--ebay)"></i>eBay median ask</span>` : ""}
      <span><i style="background:var(--ink-3)"></i>Retail $${m.retail ?? "—"}</span>
    </div>
  `;
  $("#sheet").classList.add("on");
  $("#sheet").setAttribute("aria-hidden", "false");
  $("#sheet-backdrop").classList.add("on");
  requestAnimationFrame(() =>
    $$("#sheet .bar-fill").forEach((f) => (f.style.width = f.dataset.w + "%")));
}

/* ---------------- SVG charts ---------------- */
function demandChart(m) {
  const hist = m.trend || [], fc = m.forecast || [];
  if (!hist.length) return "<p style='color:var(--ink-3)'>No data.</p>";
  const W = 500, H = 190, L = 6, R = 6, T = 10, B = 18;
  const all = [...hist.map((p) => p.v), ...fc.map((p) => p.v), ...fc.map((p) => p.hi)];
  const max = Math.max(...all, 10), n = hist.length + fc.length;
  const X = (i) => L + (i / (n - 1)) * (W - L - R);
  const Y = (v) => T + (1 - v / max) * (H - T - B);
  const hp = hist.map((p, i) => `${X(i)},${Y(p.v)}`);
  const area = `${L},${Y(0)} ${hp.join(" ")} ${X(hist.length - 1)},${Y(0)}`;
  const fcLine = fc.map((p, i) => `${X(hist.length + i)},${Y(p.v)}`);
  const band = [
    ...fc.map((p, i) => `${X(hist.length + i)},${Y(p.hi)}`),
    ...fc.map((p, i) => `${X(hist.length + fc.length - 1 - i)},${Y(p.lo)}`),
  ].join(" ");
  const seam = hist.length ? `${X(hist.length - 1)},${Y(hist[hist.length - 1].v)} ` : "";
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">
    <polygon points="${area}" fill="var(--acid)" opacity=".18"/>
    <polyline points="${hp.join(" ")}" fill="none" stroke="var(--ink)" stroke-width="2.2" stroke-linejoin="round"/>
    <polygon points="${band}" fill="var(--ink)" opacity=".07"/>
    <polyline points="${seam}${fcLine.join(" ")}" fill="none" stroke="var(--ink-2)" stroke-width="2" stroke-dasharray="3 3"/>
  </svg>`;
}

function resaleChart(m) {
  const rs = m.resale_series || {}, sx = rs.stockx || [], eb = rs.ebay || [];
  if (!sx.length && !eb.length) return "<p style='color:var(--ink-3)'>No resale data.</p>";
  const W = 500, H = 170, L = 6, R = 6, T = 10, B = 14;
  const vals = [...sx, ...eb].map((p) => p.v).concat(m.retail || []);
  const min = Math.min(...vals) * 0.96, max = Math.max(...vals) * 1.04;
  const line = (arr, color) => {
    if (!arr.length) return "";
    const pts = arr.map((p, i) => {
      const x = L + (i / (arr.length - 1)) * (W - L - R);
      const y = T + (1 - (p.v - min) / (max - min || 1)) * (H - T - B);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`;
  };
  let retailY = null;
  if (m.retail) retailY = T + (1 - (m.retail - min) / (max - min || 1)) * (H - T - B);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">
    ${retailY != null ? `<line x1="${L}" x2="${W - R}" y1="${retailY}" y2="${retailY}" stroke="var(--ink-3)" stroke-width="1" stroke-dasharray="4 4"/>` : ""}
    ${line(eb, "var(--ebay)")}
    ${line(sx, "var(--stockx)")}
  </svg>`;
}
