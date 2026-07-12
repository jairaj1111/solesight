/* SoleSight — The Hype Index. Renders everything from data.json. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

let DATA = null;
let SORT = "hype";
const ACTIVE = new Set();           // active brand filters (empty = all)
const CATS = new Set();             // active category filters (empty = all)

const fmtSigned = (v, unit = "") =>
  v == null ? "—" : (v > 0 ? "+" : "") + v + unit;
const deltaClass = (v) => (v == null ? "flat" : v > 1 ? "up" : v < -1 ? "down" : "flat");
const arrow = (v) => (v == null ? "" : v > 1 ? "▲" : v < -1 ? "▼" : "▬");
const esc = (s) => (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;");

init();

async function init() {
  DATA = await fetch("data.json?v=2").then((r) => r.json());
  document.documentElement.style.setProperty("--n", DATA.models.length);
  buildEyebrow();
  buildChips();
  buildHero();
  render();
  wireControls();
  wireReveal();
  wireSheet();
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
    (CATS.size === 0 || CATS.has(m.category)));
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
  $("#hero-feature").innerHTML = `
    <div class="hf-glow"></div>
    <div class="hf-rankpill">#1 · Most hyped</div>
    <div class="hf-img">${img(m, "")}</div>
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
  $("#hero-feature").onclick = () => openSheet(m.slug);
  countUp($("#hero-feature [data-count]"));
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
    <div class="sheet-eyebrow">Rank #${m.rank} · ${esc(m.brand)}</div>
    <div class="sheet-title">${esc(m.name)}</div>
    <div class="sheet-hype"><b>${m.hype ?? "—"}</b><span class="of">/ 100 hype</span>
      <span class="delta ${deltaClass(m.momentum)}" style="margin-left:auto">${arrow(m.momentum)} ${fmtSigned(m.momentum, "%")} search</span></div>
    <div class="sheet-photo">${img(m, "")}</div>

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

    <h4>Marketing readout</h4>
    <div class="sheet-insight">${esc(m.insight) || "No insight available."}</div>

    <h4>Demand &amp; 30-day forecast</h4>
    ${demandChart(m)}

    <h4>Resale · StockX vs eBay</h4>
    ${resaleChart(m)}
    <div class="legend">
      <span><i style="background:var(--stockx)"></i>StockX</span>
      <span><i style="background:var(--ebay)"></i>eBay</span>
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
