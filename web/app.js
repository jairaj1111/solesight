/* SoleSight — The Hype Index. Renders everything from data.json. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

let DATA = null;
let SORT = "hype";
const ACTIVE = new Set();           // active brand filters (empty = all)

const fmtSigned = (v, unit = "") =>
  v == null ? "—" : (v > 0 ? "+" : "") + v + unit;
const deltaClass = (v) => (v == null ? "flat" : v > 1 ? "up" : v < -1 ? "down" : "flat");
const arrow = (v) => (v == null ? "" : v > 1 ? "▲" : v < -1 ? "▼" : "▬");
const esc = (s) => (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;");

init();

async function init() {
  DATA = await fetch("data.json").then((r) => r.json());
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
  let list = DATA.models.filter((m) => ACTIVE.size === 0 || ACTIVE.has(m.brand));
  const key = SORT;
  list = [...list].sort((a, b) => (b[key] ?? -1e9) - (a[key] ?? -1e9));
  return list;
}

function buildChips() {
  const box = $("#brand-chips");
  const mk = (label, brand) => {
    const el = document.createElement("button");
    el.className = "chip" + (brand === null && ACTIVE.size === 0 ? " on" : "");
    el.textContent = label;
    el.onclick = () => {
      if (brand === null) ACTIVE.clear();
      else ACTIVE.has(brand) ? ACTIVE.delete(brand) : ACTIVE.add(brand);
      $$(".chip", box).forEach((c) => c.classList.remove("on"));
      if (ACTIVE.size === 0) box.firstChild.classList.add("on");
      else $$(".chip", box).forEach((c) => { if (ACTIVE.has(c.dataset.brand)) c.classList.add("on"); });
      render();
    };
    if (brand) el.dataset.brand = brand;
    return el;
  };
  box.appendChild(mk("All", null));
  DATA.brands.forEach((b) => box.appendChild(mk(b, b)));
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
function render() {
  const list = view();
  renderPodium(list.slice(0, 3));
  renderBoard(list.slice(3));
  renderMovers();
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
  const gain = [...DATA.models].filter((m) => m.momentum != null)
    .sort((a, b) => b.momentum - a.momentum).slice(0, 4);
  $("#movers-grid").innerHTML = gain.map((m) => `
    <div class="mover" data-slug="${m.slug}">
      ${img(m, "")}
      <div class="mover-name">${esc(m.name)}</div>
      <div class="mover-delta delta ${deltaClass(m.momentum)}">${arrow(m.momentum)} ${fmtSigned(m.momentum, "%")}</div>
    </div>`).join("");
  bindCards("#movers-grid .mover");
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
