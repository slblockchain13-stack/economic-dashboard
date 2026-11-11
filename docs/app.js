/* Economic Machine Monitor — live dashboard. Plain JS, no build step, no external libraries.
   Reads data/data.json (written by the update bot) and polls it for changes. */
"use strict";

const DATA_URL = "data/data.json";
const POLL_MS = 120000;
const PH = {early:"Early expansion", mid:"Mid expansion", late:"Late expansion", tight:"Tightening", slow:"Slowdown", rec:"Recession"};
const PH_ABBR = {early:"ERL", mid:"MID", late:"LAT", tight:"TGT", slow:"SLO", rec:"REC"};
const PH_DESC = {
  early:"Growth above trend and accelerating, inflation at or under target.",
  mid:"Growth steady near trend; no pressure either way.",
  late:"Growth above trend with inflation over target: the economy is running hot.",
  tight:"The central bank is raising rates to cool inflation.",
  slow:"Growth under trend and the central bank is easing.",
  rec:"Growth under 0.5%, far below trend, or unemployment jumping.",
};
const CLI = {expansion:"Expansion", downturn:"Downturn", slowdown:"Slowdown", recovery:"Recovery"};
const CLI_COLOR = {expansion:"--ph-early", downturn:"--ph-late", slowdown:"--ph-rec", recovery:"--ph-mid"};
const LT = ["Early: room to borrow", "Mid: debt building", "Late: debt heavy", "Very late: deleveraging pressure"];
const SERIES_COLORS = ["--s1", "--s2", "--s3", "--s4"];
const PLAYBOOK = {
  early:"Equities and cyclical sectors usually lead; credit spreads narrow.",
  mid:"Broad equities still fine; quality and earnings growth matter more.",
  late:"Commodities and value tend to hold up; bonds suffer if rates rise.",
  tight:"Cash and short-term bonds; equities are vulnerable to rate rises.",
  slow:"Long-term government bonds and defensive sectors usually do best.",
  rec:"Bonds first; equities bottom before the economy does, so watch the leading indicator.",
};

let D = null, lastGenerated = null, state = {tab:"world", country:"US", compare:["US","CN","IN","EA"], metric:"gdp", newsCountry:"ALL", newsTopic:"ALL", newsTone:"ALL", sort:{key:"share", dir:-1}, shareMode:"ppp"};
try { const s = JSON.parse(localStorage.getItem("emm-state") || "{}"); Object.assign(state, s); } catch (e) {}
function save() { try { localStorage.setItem("emm-state", JSON.stringify({compare:state.compare, metric:state.metric, shareMode:state.shareMode})); } catch (e) {} }

/* ---------- helpers ---------- */
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const safeUrl = u => /^https?:\/\//i.test(u || "") ? u : "#";
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const f = (v, d = 1, suf = "") => v == null || isNaN(v) ? "–" : (+v).toFixed(d) + suf;
const fp = (v, d = 1) => f(v, d, "%");
const sgn = (v, d = 1, suf = "%") => v == null ? "–" : (v > 0 ? "+" : "") + (+v).toFixed(d) + suf;
const updn = v => v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "";
const big = v => v == null ? "–" : v >= 1e4 ? Math.round(v).toLocaleString("en-US") : v >= 100 ? v.toFixed(1) : v.toFixed(2);
function ago(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400 * 2) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " days ago";
}
const E = k => D.economies[k];
const keys = () => Object.keys(D.economies);
const realKeys = () => keys().filter(k => !E(k).aggregate);
const name = k => k === "WORLD" ? "World" : (E(k) ? E(k).name : k);
const flag = k => k === "WORLD" ? "🌐" : (E(k) ? E(k).flag : "");
const ann = (obj, from = 1990) => Object.entries(obj || {}).map(([y, v]) => [+y, v]).filter(p => p[0] >= from).sort((a, b) => a[0] - b[0]);
const ym = s => { const [y, m] = s.split("-").map(Number); return y + ((m || 1) - 0.5) / 12; };
const mon = (obj, from = "2005-01") => Object.entries(obj || {}).filter(([k]) => k >= from).map(([k, v]) => [ym(k), v]).sort((a, b) => a[0] - b[0]);
const dayx = s => { const d = new Date(s + "T00:00:00Z"); return d.getUTCFullYear() + (d - Date.UTC(d.getUTCFullYear(), 0, 1)) / 31536e6; };
function rolling10(gdp) { const m = new Map(gdp); return gdp.map(([y]) => { const v = []; for (let t = y - 10; t < y; t++) if (m.has(t)) v.push(m.get(t)); return [y, v.length >= 5 ? v.reduce((a, b) => a + b, 0) / v.length : null]; }).filter(p => p[1] != null); }
const md = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
const phasePill = p => p ? `<span class="pill" title="${esc(PH_DESC[p])}" style="--c:var(--ph-${p})"><i></i>${PH[p]}</span>` : `<span class="pill"><i></i>Not enough data</span>`;
const cliPill = c => c ? `<span class="pill" title="OECD leading indicator ${c.level} (${sgn(c.chg3m, 2, "")} over 3 months to ${c.month})" style="--c:var(${CLI_COLOR[c.phase]})"><i></i>Leading: ${CLI[c.phase]}</span>` : "";
const stPill = (label, st) => `<span class="pill st-${st}">${label}: ${st}</span>`;

/* ---------- charts (SVG, responsive, with hover) ---------- */
function niceTicks(lo, hi, n = 5) {
  if (lo === hi) { lo -= 1; hi += 1; }
  const step0 = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(step0))), r = step0 / mag;
  const step = (r < 1.5 ? 1 : r < 3 ? 2 : r < 7 ? 5 : 10) * mag;
  const t = []; for (let v = Math.floor(lo / step) * step; v <= hi + step * 0.001; v += step) t.push(+v.toFixed(10));
  return t;
}
function lineChart(el, o) {
  const W = Math.max(280, el.clientWidth || 600), H = o.height || 220, m = {l: 40, r: 12, t: 10, b: 22};
  const all = o.series.flatMap(s => s.pts).filter(p => p[1] != null);
  if (!all.length) { el.innerHTML = `<p class="muted small">No data from the source yet.</p>`; return; }
  let x0 = Math.min(...all.map(p => p[0])), x1 = Math.max(...all.map(p => p[0]));
  let ys = all.map(p => p[1]).concat((o.refs || []).map(r => r.y));
  if (o.zero) ys.push(0);
  let y0 = Math.min(...ys), y1 = Math.max(...ys); const pad = (y1 - y0) * 0.08 || 1; y0 -= pad; y1 += pad;
  const yt = niceTicks(y0, y1, H < 180 ? 3 : 5); y0 = Math.min(y0, yt[0]); y1 = Math.max(y1, yt[yt.length - 1]);
  const X = x => m.l + (x - x0) / (x1 - x0 || 1) * (W - m.l - m.r), Y = y => m.t + (1 - (y - y0) / (y1 - y0)) * (H - m.t - m.b);
  const span = x1 - x0, xstep = o.xfmt === "day" ? (span > 0.6 ? 1 / 4 : 1 / 12) : span > 24 ? 5 : span > 10 ? 2 : 1;
  const xt = []; for (let v = Math.ceil(x0 / xstep - 1e-9) * xstep; v <= x1 + 1e-9; v += xstep) xt.push(v);
  const xl = v => o.xfmt === "day" ? new Date(Date.UTC(Math.floor(v), Math.round((v % 1) * 12), 1)).toLocaleDateString("en-GB", {month: "short", year: "2-digit"}) : String(Math.round(v));
  let s = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(o.label || "")}">`;
  if (o.shadeFrom != null && o.shadeFrom < x1) s += `<rect x="${X(Math.max(o.shadeFrom, x0))}" y="${m.t}" width="${X(x1) - X(Math.max(o.shadeFrom, x0))}" height="${H - m.t - m.b}" fill="var(--surface-2)"/><text x="${X(x1) - 4}" y="${m.t + 11}" text-anchor="end">IMF projection</text>`;
  (o.bands || []).forEach(b => { if (b.to >= x0 && b.from <= x1) s += `<rect x="${X(Math.max(b.from, x0))}" y="${m.t}" width="${Math.max(1, X(Math.min(b.to, x1)) - X(Math.max(b.from, x0)))}" height="${H - m.t - m.b}" fill="var(${b.c})" opacity=".13"/>`; });
  yt.forEach(v => { s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/><text x="${m.l - 6}" y="${Y(v) + 3.5}" text-anchor="end">${+v.toFixed(2)}${o.unit || ""}</text>`; });
  xt.forEach(v => { s += `<text x="${X(v)}" y="${H - 5}" text-anchor="middle">${xl(v)}</text>`; });
  if (o.zero && y0 < 0 && y1 > 0) s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--muted)" stroke-width="1"/>`;
  (o.refs || []).forEach(r => { s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(r.y)}" y2="${Y(r.y)}" stroke="var(--ref)" stroke-dasharray="4 4"/><text x="${W - m.r}" y="${Y(r.y) - 4}" text-anchor="end" class="lbl">${esc(r.label)}</text>`; });
  (o.events || []).filter(e => e[0] >= x0 && e[0] <= x1).forEach(e => { s += `<line x1="${X(e[0])}" x2="${X(e[0])}" y1="${m.t}" y2="${H - m.b}" stroke="var(--line)" stroke-dasharray="2 3"><title>${esc(e[0] + ": " + e[1])}</title></line>`; });
  o.series.forEach(se => {
    const pts = se.pts.filter(p => p[1] != null); if (!pts.length) return;
    const solid = se.dashFrom != null ? pts.filter(p => p[0] <= se.dashFrom) : pts;
    const dashed = se.dashFrom != null ? pts.filter(p => p[0] >= se.dashFrom) : [];
    const path = arr => arr.map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join("");
    const w = se.width || 2;
    if (solid.length) s += `<path d="${path(solid)}" fill="none" stroke="var(${se.c})" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round" ${se.dash ? 'stroke-dasharray="5 4"' : ""}/>`;
    if (dashed.length > 1) s += `<path d="${path(dashed)}" fill="none" stroke="var(${se.c})" stroke-width="${w}" stroke-dasharray="5 4" stroke-linecap="round"/>`;
  });
  s += `<g class="hover" style="display:none"><line y1="${m.t}" y2="${H - m.b}" stroke="var(--muted)"/></g><rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent" class="hit"/></svg>`;
  const legend = o.series.length > 1 || o.legend ? `<div class="legend">${o.series.map(se => `<span><i class="${se.dash ? "dash" : ""}" style="--c:var(${se.c})"></i>${esc(se.name)}</span>`).join("")}${(o.bands && o.bandLegend) || ""}</div>` : "";
  el.innerHTML = legend + s + `<div class="tip"></div>`;
  const svg = el.querySelector("svg"), g = svg.querySelector(".hover"), tip = el.querySelector(".tip"), line = g.querySelector("line");
  const xs = [...new Set(all.map(p => p[0]))].sort((a, b) => a - b);
  const fmtx = o.tipx || (v => o.xfmt === "day" ? "" : o.xfmt === "month" ? new Date(Date.UTC(Math.floor(v), Math.floor((v % 1) * 12), 1)).toLocaleDateString("en-GB", {month: "short", year: "numeric"}) : String(Math.round(v)));
  function move(ev) {
    const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * W / r.width;
    const xv = x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0);
    let best = xs[0]; for (const v of xs) if (Math.abs(v - xv) < Math.abs(best - xv)) best = v;
    g.style.display = ""; line.setAttribute("x1", X(best)); line.setAttribute("x2", X(best));
    g.querySelectorAll("circle").forEach(c => c.remove());
    let rows = "";
    o.series.forEach(se => {
      const p = se.pts.find(q => Math.abs(q[0] - best) < 1e-6);
      if (!p || p[1] == null) return;
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("cx", X(p[0])); c.setAttribute("cy", Y(p[1])); c.setAttribute("r", 4.5); c.setAttribute("fill", `var(${se.c})`); c.setAttribute("stroke", "var(--surface)"); c.setAttribute("stroke-width", 2);
      g.appendChild(c);
      rows += `<div class="row"><span><i style="--c:var(${se.c})"></i>${esc(se.name)}</span><b class="num">${o.vfmt ? o.vfmt(p[1]) : (+p[1]).toFixed(2) + (o.unit || "")}</b></div>`;
    });
    const label = o.xfmt === "day" ? (o.dateOf ? o.dateOf(best) : "") : fmtx(best);
    const extra = o.tipExtra ? o.tipExtra(best) : "";
    tip.innerHTML = `<div class="muted small">${esc(label)}${best >= (o.shadeFrom ?? 1e9) ? " · projection" : ""}</div>${rows}${extra}`;
    tip.style.display = "block";
    const left = X(best) / W * r.width, tw = tip.offsetWidth;
    tip.style.left = Math.min(Math.max(0, left + 12 + tw > r.width ? left - tw - 12 : left + 12), r.width - tw) + "px";
    tip.style.top = (svg.offsetTop + 6) + "px";
  }
  svg.addEventListener("pointermove", move); svg.addEventListener("pointerdown", move);
  svg.addEventListener("pointerleave", () => { g.style.display = "none"; tip.style.display = "none"; });
}
function scatter(el, o) {
  const W = Math.max(280, el.clientWidth || 500), H = o.height || 300, m = {l: 44, r: 14, t: 14, b: 34};
  const pts = o.pts.filter(p => p.x != null && p.y != null);
  if (!pts.length) { el.innerHTML = `<p class="muted small">No data yet.</p>`; return; }
  const xr = Math.max(...pts.map(p => Math.abs(p.x - o.xRef))) * 1.25 || 1, yr = Math.max(...pts.map(p => Math.abs(p.y - o.yRef))) * 1.25 || 1;
  const x0 = o.xRef - xr, x1 = o.xRef + xr, y0 = o.yRef - yr, y1 = o.yRef + yr;
  const X = x => m.l + (x - x0) / (x1 - x0) * (W - m.l - m.r), Y = y => m.t + (1 - (y - y0) / (y1 - y0)) * (H - m.t - m.b);
  let s = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(o.label || "")}">`;
  const q = o.quads; // [top-left, top-right, bottom-left, bottom-right] each {t, c}
  const qx = [[m.l, X(o.xRef)], [X(o.xRef), W - m.r]], qy = [[m.t, Y(o.yRef)], [Y(o.yRef), H - m.b]];
  [[0, 0], [1, 0], [0, 1], [1, 1]].forEach(([i, j], n) => {
    s += `<rect x="${qx[i][0]}" y="${qy[j][0]}" width="${qx[i][1] - qx[i][0]}" height="${qy[j][1] - qy[j][0]}" fill="var(${q[n].c})" opacity=".08"/>`;
    s += `<text x="${i ? W - m.r - 6 : m.l + 6}" y="${j ? H - m.b - 6 : m.t + 14}" text-anchor="${i ? "end" : "start"}" class="lbl" style="fill:var(${q[n].c})">${esc(q[n].t)}</text>`;
  });
  niceTicks(y0, y1, 4).forEach(v => { if (v > y0 && v < y1) s += `<text x="${m.l - 6}" y="${Y(v) + 3.5}" text-anchor="end">${+v.toFixed(2)}</text>`; });
  niceTicks(x0, x1, 5).forEach(v => { if (v > x0 && v < x1) s += `<text x="${X(v)}" y="${H - m.b + 14}" text-anchor="middle">${+v.toFixed(2)}</text>`; });
  s += `<line x1="${X(o.xRef)}" x2="${X(o.xRef)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--ref)"/><line x1="${m.l}" x2="${W - m.r}" y1="${Y(o.yRef)}" y2="${Y(o.yRef)}" stroke="var(--ref)"/>`;
  s += `<text x="${(m.l + W - m.r) / 2}" y="${H - 4}" text-anchor="middle">${esc(o.xLabel)}</text><text transform="translate(11 ${(m.t + H - m.b) / 2}) rotate(-90)" text-anchor="middle">${esc(o.yLabel)}</text>`;
  pts.forEach(p => {
    s += `<g class="pt" data-k="${p.k}" style="cursor:pointer"><circle cx="${X(p.x)}" cy="${Y(p.y)}" r="${p.big ? 7 : 5.5}" fill="var(${p.c})" stroke="var(--surface)" stroke-width="2"/><circle cx="${X(p.x)}" cy="${Y(p.y)}" r="14" fill="transparent"/>`;
    s += `<text x="${X(p.x) + 9}" y="${Y(p.y) + 4}" class="lbl">${esc(p.label)}</text><title>${esc(p.title)}</title></g>`;
  });
  el.innerHTML = s + "</svg>";
  el.querySelectorAll(".pt").forEach(g => g.addEventListener("click", () => g.dataset.k !== "WORLD" && go("country/" + g.dataset.k)));
}
function spark(vals, w = 120, h = 28, c = "--s1") {
  if (!vals || vals.length < 2) return "";
  const lo = Math.min(...vals), hi = Math.max(...vals), X = i => i / (vals.length - 1) * w, Y = v => h - 2 - (v - lo) / (hi - lo || 1) * (h - 4);
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${vals.map((v, i) => (i ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1)).join("")}" fill="none" stroke="var(${c})" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
}
function bars(rows, fmt = v => fp(v, 1)) {
  const max = Math.max(...rows.map(r => Math.abs(r.v || 0))) || 1, hasNeg = rows.some(r => r.v < 0);
  return `<div class="bars">${rows.map(r => {
    const w = Math.abs(r.v || 0) / max * (hasNeg ? 50 : 100);
    const left = hasNeg ? (r.v < 0 ? 50 - w : 50) : 0;
    return `<div class="bar" title="${esc(r.title || r.label + ": " + fmt(r.v))}"><span class="lab">${esc(r.label)}</span><span class="track"><span class="fill ${r.v < 0 ? "neg" : ""}" style="left:${left}%;width:${w}%;${r.c ? `background:var(${r.c})` : ""}"></span></span><span class="val">${fmt(r.v)}</span></div>`;
  }).join("")}</div>`;
}
function phaseBands(phases, extraNow) {
  const out = []; Object.entries(phases || {}).forEach(([y, p]) => out.push({from: +y - 0.5, to: +y + 0.5, c: "--ph-" + p}));
  if (extraNow) out.push(extraNow);
  return out;
}

/* ---------- live status ---------- */
function setStatus() {
  if (!D) return;
  const age = Date.now() / 1000 - D.generated_ts, stale = age > 3 * 3600;
  $("#dot").className = "dot" + (stale ? " stale" : "");
  $("#status-text").textContent = (stale ? "Delayed · " : "Live · ") + "updated " + ago(D.generated_ts);
  $("#status").title = `Data generated ${new Date(D.generated_ts * 1000).toLocaleString()}. Markets & news refresh hourly, economic data daily. This page checks for new data every 2 minutes.`;
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 6000); }
async function load(first) {
  try {
    const r = await fetch(DATA_URL + "?t=" + Date.now(), {cache: "no-store"});
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    if (d.generated !== lastGenerated) {
      const was = lastGenerated; D = d; lastGenerated = d.generated;
      if (!first && was) toast(`New data arrived · ${d.changes_this_run || 0} change${d.changes_this_run === 1 ? "" : "s"} detected`);
      render();
    }
    setStatus();
  } catch (e) {
    if (first) $("#view").innerHTML = `<div class="loading">Could not load the data file (${esc(e.message)}). If you opened index.html directly from disk, run it through a web server instead — see README.</div>`;
    $("#status-text").textContent = "Offline · retrying";
    $("#dot").className = "dot stale";
  }
}

/* ---------- routing ---------- */
function go(h) { location.hash = h; }
function route() {
  const h = (location.hash || "#world").slice(1).split("/");
  state.tab = ["world", "country", "compare", "opportunities", "news", "method"].includes(h[0]) ? h[0] : "world";
  if (state.tab === "country" && h[1] && D && D.economies[h[1]]) state.country = h[1];
  document.querySelectorAll("#tabs a").forEach(a => a.setAttribute("aria-current", a.getAttribute("href") === "#" + state.tab ? "page" : "false"));
  render(); window.scrollTo({top: 0});
}
function render() {
  if (!D) return;
  const v = $("#view");
  ({world: renderWorld, country: renderCountry, compare: renderCompare, opportunities: renderOpps, news: renderNews, method: renderMethod})[state.tab](v);
  v.insertAdjacentHTML("beforeend", `<footer><span>Data: IMF, World Bank, BIS, OECD, FRED, Yahoo Finance, CSE, ECB, Google News.</span><span>Generated ${esc(new Date(D.generated_ts * 1000).toUTCString())}.</span><span>Educational tool: rule-based signals, not investment advice.</span></footer>`);
}

/* ---------- WORLD ---------- */
function marketTiles() {
  return `<div class="tiles">${D.markets.map(m => {
    const val = m.unit === "pct" ? f(m.price, 2, "%") : (m.unit === "usd" ? "$" : "") + big(m.price);
    return `<div class="tile" title="${esc(m.label)} · last ${esc(m.date)}${m.stale ? " (source unavailable: last known value)" : ""}"><div class="k">${esc(m.label)}</div><div class="v">${val}</div>
      <div class="d"><span class="${updn(m.day_chg)}">${sgn(m.day_chg, 2)}</span> day · <span class="${updn(m.ret_12m)}">${sgn(m.ret_12m, 1)}</span> 1y</div>${spark(m.spark && m.spark.close, 120, 26, m.day_chg >= 0 ? "--s3" : "--s2")}</div>`;
  }).join("")}</div>`;
}
function changesFeed(filterKey) {
  const list = (D.changes || []).filter(c => !filterKey || c.key === filterKey).slice(0, 40);
  if (!list.length) return `<p class="muted small">No changes logged yet. The bot compares each run with the last one and lists what moved here: cycle phases, rate decisions, leading-indicator releases and big market moves.</p>`;
  return `<div class="feed">${list.map(c => `<div class="item"><span class="tone z" title="${esc(c.kind)}">${{cycle: "◔", cli: "↗", rates: "%", screen: "★", markets: "≋"}[c.kind] || "•"}</span><span class="t">${esc(c.text)}</span><span class="m"><span>${ago(c.ts)}</span><span class="tag">${esc(c.kind)}</span></span></div>`).join("")}</div>`;
}
function newsList(items, showCountry) {
  if (!items || !items.length) return `<p class="muted small">No headlines right now.</p>`;
  return `<div class="feed">${items.map(n => `<div class="item"><span class="tone ${n.tone > 0 ? "p" : n.tone < 0 ? "n" : "z"}" title="Tone: ${n.tone > 0 ? "positive" : n.tone < 0 ? "negative" : "neutral"}">${n.tone > 0 ? "+" : n.tone < 0 ? "−" : "·"}</span>
    <a class="t" href="${esc(safeUrl(n.link))}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>
    <span class="m">${showCountry ? `<span>${flag(n._k)} ${esc(name(n._k))}</span>` : ""}<span>${esc(n.source)}</span><span>${ago(n.ts)}</span>${(n.topics || []).map(t => `<span class="tag">${esc(t)}</span>`).join("")}</span></div>`).join("")}</div>`;
}
function renderWorld(v) {
  const w = D.world, n = w.now, Y = D.year;
  const cnt = n.phase_counts || {};
  v.innerHTML = `
  <section><p class="eyebrow">World economy · ${Y}</p><h2 style="margin:4px 0 8px">The global picture</h2><p class="lede">${md(w.summary)}</p></section>
  <section class="tiles">
    <div class="tile"><div class="k">World GDP growth ${Y} (IMF)</div><div class="v">${fp(n.gdp)}</div><div class="d">Trend ${fp(n.trend)} · ${Y - 1}: ${fp(n.gdp_prev)}</div></div>
    <div class="tile"><div class="k">World inflation ${Y}</div><div class="v">${fp(n.cpi)}</div><div class="d">${Y - 1}: ${fp(n.cpi_prev)}</div></div>
    <div class="tile"><div class="k">G20 leading indicator</div><div class="v">${f(n.cli && n.cli.level, 2)}</div><div class="d">${n.cli ? CLI[n.cli.phase] + " · " + n.cli.month : "–"}</div></div>
    <div class="tile"><div class="k">G7 leading indicator</div><div class="v">${f(n.cli_g7 && n.cli_g7.level, 2)}</div><div class="d">${n.cli_g7 ? CLI[n.cli_g7.phase] + " · " + n.cli_g7.month : "–"}</div></div>
    <div class="tile"><div class="k">World GDP (nominal)</div><div class="v">$${f(n.gdp_usd / 1000, 1)}tn</div><div class="d">IMF estimate for ${Y}</div></div>
    <div class="tile"><div class="k">Where the ${realKeys().length} economies sit</div><div class="d" style="white-space:normal;margin-top:4px">${Object.keys(PH).filter(p => cnt[p]).map(p => `<span class="pill" style="--c:var(--ph-${p});margin:0 3px 3px 0"><i></i>${PH[p]} ${cnt[p]}</span>`).join("")}</div></div>
  </section>
  <section><div class="panel-head"><div><h3>Global markets</h3><p>Latest close, day change and 1-year change. Refreshed every hour.</p></div></div>${marketTiles()}</section>
  <section class="grid g2">
    <div class="panel"><div class="panel-head"><div><h3>Business-cycle clock (OECD leading indicators)</h3><p>Level vs 100 (long-run trend) and the 3-month change. Economies move clockwise: recovery → expansion → downturn → slowdown. Click a dot to open the country.</p></div></div><div class="chart" id="clock"></div></div>
    <div class="panel"><div class="panel-head"><div><h3>Growth vs inflation map, ${Y}</h3><p>Growth gap to each economy's 10-year trend, against inflation gap to its target (IMF projections). Top-right is running hot; bottom-left is cooling.</p></div></div><div class="chart" id="gimap"></div></div>
  </section>
  <section class="grid g2">
    <div class="panel"><div class="panel-head"><div><h3>Weight in the world economy, ${Y}</h3><p>Share of world GDP. PPP adjusts for price levels; nominal uses market exchange rates.</p></div>
      <select id="sharemode" aria-label="Share measure"><option value="ppp">At PPP</option><option value="nominal">Nominal US$</option><option value="contrib">Contribution to world growth (pts)</option></select></div><div id="shares"></div>
      <p class="muted small" style="margin-top:8px">Euro area is left out because it overlaps Germany and France.</p></div>
    <div class="panel"><div class="panel-head"><div><h3>World growth and inflation</h3><p>Annual %, IMF World Economic Outlook. Shaded years are projections.</p></div></div><div class="chart" id="wgrowth"></div></div>
  </section>
  <section class="panel"><div class="panel-head"><div><h3>Major economies side by side</h3><p>Latest values. Click a column to sort, a row to open the country.</p></div></div><div class="tablewrap" id="cmpTable"></div></section>
  <section class="grid g2">
    <div class="panel"><div class="panel-head"><div><h3>Leading indicators: G20, G7 and the big four</h3><p>OECD composite leading indicators, 100 = long-run trend.</p></div></div><div class="chart" id="wcli"></div></div>
    <div class="panel"><div class="panel-head"><div><h3>What changed</h3><p>Logged automatically by the update bot each run.</p></div></div>${changesFeed()}</div>
  </section>
  <section class="panel"><div class="panel-head"><div><h3>Global headlines</h3><p>Google News, past 3 days. Tone is scored by keyword rules.</p></div></div>${newsList(D.news.by.WORLD)}</section>`;

  const clockPts = keys().filter(k => E(k).now.cli).map(k => ({k, x: E(k).now.cli.chg3m, y: E(k).now.cli.level, label: k, c: CLI_COLOR[E(k).now.cli.phase], title: `${name(k)}: ${E(k).now.cli.level} (${sgn(E(k).now.cli.chg3m, 2, "")} over 3 months, ${E(k).now.cli.month}) · ${CLI[E(k).now.cli.phase]}`}));
  if (n.cli) clockPts.push({k: "WORLD", x: n.cli.chg3m, y: n.cli.level, label: "G20", big: true, c: "--ink", title: `G20: ${n.cli.level}`});
  scatter($("#clock"), {pts: clockPts, xRef: 0, yRef: 100, xLabel: "3-month change", yLabel: "Leading indicator level", label: "Business cycle clock",
    quads: [{t: "Downturn", c: CLI_COLOR.downturn}, {t: "Expansion", c: CLI_COLOR.expansion}, {t: "Slowdown", c: CLI_COLOR.slowdown}, {t: "Recovery", c: CLI_COLOR.recovery}]});
  const gi = realKeys().map(k => { const x = E(k).now.inputs || {}; return {k, x: x.gdp != null && x.trend != null ? +(x.gdp - x.trend).toFixed(2) : null, y: x.cpi != null && x.target != null ? +(x.cpi - x.target).toFixed(2) : null, label: k, c: E(k).now.phase ? "--ph-" + E(k).now.phase : "--muted", title: `${name(k)}: growth ${fp(x.gdp)} vs trend ${fp(x.trend)}, inflation ${fp(x.cpi)} vs ${fp(x.target)} · ${PH[E(k).now.phase] || ""}`}; });
  scatter($("#gimap"), {pts: gi, xRef: 0, yRef: 0, xLabel: "Growth minus 10-year trend (pts)", yLabel: "Inflation minus target (pts)", label: "Growth vs inflation",
    quads: [{t: "Stagflation risk", c: "--ph-tight"}, {t: "Overheating", c: "--ph-late"}, {t: "Cooling / slack", c: "--ph-slow"}, {t: "Goldilocks", c: "--ph-early"}]});
  const sm = $("#sharemode"); sm.value = state.shareMode;
  const drawShares = () => {
    const mode = state.shareMode;
    const rows = realKeys().map(k => ({label: `${flag(k)} ${name(k)}`, v: mode === "ppp" ? E(k).now.share_ppp : mode === "nominal" ? E(k).now.share_nominal : (n.growth_contrib || {})[k]})).filter(r => r.v != null).sort((a, b) => b.v - a.v);
    $("#shares").innerHTML = bars(rows, v => mode === "contrib" ? f(v, 2) : fp(v, 1));
  };
  sm.onchange = () => { state.shareMode = sm.value; save(); drawShares(); }; drawShares();
  lineChart($("#wgrowth"), {series: [{name: "World GDP growth", c: "--s1", pts: ann(w.series.gdp, 2000), dashFrom: Y - 1}, {name: "World inflation", c: "--s2", pts: ann(w.series.cpi, 2000), dashFrom: Y - 1}], unit: "%", zero: true, shadeFrom: Y - 0.5, events: [[2008, "Global financial crisis"], [2020, "COVID-19"]], label: "World growth and inflation"});
  const big4 = ["US", "CN", "DE", "IN"].filter(k => E(k) && E(k).monthly.cli);
  lineChart($("#wcli"), {series: [{name: "G20", c: "--ink", width: 2.5, pts: mon(w.monthly.cli_G20, "2021-07")}, ...big4.map((k, i) => ({name: name(k), c: SERIES_COLORS[i], pts: mon(E(k).monthly.cli, "2021-07")}))], refs: [{y: 100, label: "Trend = 100"}], xfmt: "month", label: "Leading indicators"});
  drawTable();
}
const COLS = [
  {k: "name", t: "Economy", l: true, v: k => name(k), h: k => `${flag(k)} ${esc(name(k))}`},
  {k: "share", t: "World share PPP", v: k => E(k).now.share_ppp, h: k => fp(E(k).now.share_ppp)},
  {k: "gdp", t: "Growth", v: k => E(k).now.inputs.gdp, h: k => fp(E(k).now.inputs.gdp)},
  {k: "gap", t: "vs trend", v: k => E(k).now.inputs.gdp != null && E(k).now.inputs.trend != null ? E(k).now.inputs.gdp - E(k).now.inputs.trend : null, h: function (k) { const x = this.v(k); return `<span class="${updn(x)}">${sgn(x, 1, "")}</span>`; }},
  {k: "cpi", t: "Inflation", v: k => E(k).now.inputs.cpi, h: k => fp(E(k).now.inputs.cpi)},
  {k: "rate", t: "Policy rate", v: k => E(k).now.rate, h: k => fp(E(k).now.rate, 2)},
  {k: "real", t: "Real rate", v: k => E(k).now.real_rate, h: k => fp(E(k).now.real_rate)},
  {k: "y10", t: "10y yield", v: k => E(k).now.y10, h: k => fp(E(k).now.y10, 2)},
  {k: "gov", t: "Govt debt", v: k => E(k).now.metrics.gov_debt, h: k => fp(E(k).now.metrics.gov_debt, 0)},
  {k: "ca", t: "Current acct", v: k => E(k).now.metrics.ca, h: k => fp(E(k).now.metrics.ca)},
  {k: "eq", t: "Stocks 1y", v: k => E(k).now.equity && E(k).now.equity.ret_12m, h: function (k) { const x = this.v(k); return `<span class="${updn(x)}">${sgn(x)}</span>`; }},
  {k: "phase", t: "Cycle phase", l: true, v: k => Object.keys(PH).indexOf(E(k).now.phase), h: k => phasePill(E(k).now.phase)},
  {k: "cli", t: "Leading ind.", l: true, v: k => E(k).now.cli ? E(k).now.cli.level : null, h: k => E(k).now.cli ? cliPill(E(k).now.cli).replace("Leading: ", "") : `<span class="muted">n/a</span>`},
  {k: "lt", t: "Debt cycle", l: true, v: k => E(k).now.lt_score, h: k => E(k).now.lt_stage != null ? esc(LT[E(k).now.lt_stage].split(":")[0]) : "–"},
  {k: "score", t: "Screen", v: k => E(k).screen.score100, h: k => `<b class="num">${E(k).screen.score100}</b>`},
];
function drawTable() {
  const s = state.sort, col = COLS.find(c => c.k === s.key) || COLS[1];
  const ks = keys().slice().sort((a, b) => { const x = col.v(a), y = col.v(b); if (x == null) return 1; if (y == null) return -1; return (x > y ? 1 : x < y ? -1 : 0) * s.dir; });
  $("#cmpTable").innerHTML = `<table><thead><tr>${COLS.map(c => `<th class="${c.l ? "l" : ""}" data-k="${c.k}" aria-sort="${c.k === s.key ? (s.dir > 0 ? "ascending" : "descending") : "none"}">${c.t}${c.k === s.key ? (s.dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>
    <tbody>${ks.map(k => `<tr data-k="${k}">${COLS.map(c => `<td class="${c.l ? "l" : ""} ${c.l ? "" : "num"}">${c.h.call(c, k)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  document.querySelectorAll("#cmpTable th").forEach(th => th.onclick = () => { state.sort = {key: th.dataset.k, dir: th.dataset.k === s.key ? -s.dir : -1}; drawTable(); });
  document.querySelectorAll("#cmpTable tbody tr").forEach(tr => tr.onclick = () => go("country/" + tr.dataset.k));
}

/* ---------- COUNTRY ---------- */
function renderCountry(v) {
  const k = state.country, c = E(k), n = c.now, x = n.inputs || {}, Y = D.year, sc = c.screen;
  const eq = n.equity || {}, fx = n.fx || {};
  const yrs = []; for (let y = 2000; y <= D.last_actual; y++) yrs.push(y);
  v.innerHTML = `
  <section><div class="chips" role="group" aria-label="Choose economy">${keys().map(kk => `<button class="chip" aria-pressed="${kk === k}" data-k="${kk}">${flag(kk)} ${esc(name(kk))}</button>`).join("")}</div></section>
  <section><p class="eyebrow">${esc(c.region)} · ${esc(c.cb)}</p><h2 style="margin:4px 0 8px;font-size:26px">${c.flag} ${esc(c.name)}</h2>
    <div class="pills" style="margin-bottom:10px">${phasePill(n.phase)}${cliPill(n.cli)}${n.lt_stage != null ? `<span class="pill" title="${esc(LT[n.lt_stage])}">Debt cycle: ${esc(LT[n.lt_stage].split(":")[0])}</span>` : ""}${stPill("Stocks", sc.equities.stance)}${stPill("Bonds", sc.bonds.stance)}${stPill("Currency", sc.currency.stance)}</div>
    <p class="lede">${md(c.summary)}</p></section>
  <section class="tiles">
    ${tile(`GDP growth ${Y} (IMF)`, fp(x.gdp), `10-yr trend ${fp(x.trend)}`)}
    ${tile(`Inflation ${Y}`, fp(x.cpi), `Target ${fp(c.target)}`)}
    ${tile("Policy rate", fp(n.rate, 2), n.rate_date ? `${n.rate_date} · 12m ${sgn(n.rate_chg_12m, 2, "")}` : "No policy rate")}
    ${tile("Real policy rate", fp(n.real_rate), "Rate minus inflation")}
    ${tile("10-year bond yield", fp(n.y10, 2), n.y10_date || "No free source")}
    ${tile("Unemployment", fp(last(c.series.unemp, Y)), `${Y} (IMF)`)}
    ${tile("Government debt", fp(n.metrics.gov_debt, 0), "% of GDP")}
    ${tile("Private credit", fp(lastv(c.series.credit), 0), "% of GDP (BIS)")}
    ${tile("Current account", fp(n.metrics.ca), "% of GDP")}
    ${tile("FX reserves", f(n.metrics.reserves_months, 1, " mo"), "Months of imports")}
    ${tile(`${c.ccy} per US$`, fx.per_usd ? big(fx.per_usd) : "–", fx.chg_12m != null ? `<span class="${updn(fx.chg_12m)}">${sgn(fx.chg_12m)}</span> vs USD 1y` : (fx.note || ""))}
    ${tile(esc(c.index_name), big(eq.price), `<span class="${updn(eq.day_chg)}">${sgn(eq.day_chg, 2)}</span> day · <span class="${updn(eq.ret_12m)}">${sgn(eq.ret_12m)}</span> 1y`)}
  </section>
  <section class="panel"><div class="panel-head"><div><h3>Business-cycle phase by year</h3><p>Computed by the rules in "How it works". The last cell is ${Y}, using IMF projections and the latest policy rate. Hover a cell for the reasoning.</p></div>
    <div class="legend">${Object.keys(PH).map(p => `<span><i class="box" style="--c:var(--ph-${p});opacity:1;border-radius:2px"></i>${PH[p]}</span>`).join("")}</div></div>
    <div class="ribbon">${yrs.map(y => { const p = c.phases[y]; return `<div class="cell ${p ? "" : "none"}" style="${p ? `--c:var(--ph-${p})` : ""}" title="${y}: ${p ? PH[p] + " — " + PH_DESC[p] : "not enough data"}">${p ? PH_ABBR[p] : "–"}</div>`; }).join("")}<div class="cell proj ${n.phase ? "" : "none"}" style="${n.phase ? `--c:var(--ph-${n.phase})` : ""}" title="${Y} (projection): ${n.phase ? PH[n.phase] : "n/a"}">${n.phase ? PH_ABBR[n.phase] : "–"}</div></div>
    <div class="yrs">${yrs.map(y => `<span>${String(y).slice(2)}</span>`).join("")}<span>${String(Y).slice(2)}p</span></div></section>
  <section class="grid g3">
    <div class="panel"><h3>Stocks: ${sc.equities.stance}</h3>${screenList(sc.equities.why)}<p class="muted small" style="margin-top:8px">${esc(PLAYBOOK[n.phase] || "")}</p></div>
    <div class="panel"><h3>Bonds: ${sc.bonds.stance}</h3>${screenList(sc.bonds.why)}</div>
    <div class="panel"><h3>Currency: ${sc.currency.stance}</h3>${screenList(sc.currency.why)}</div>
  </section>
  <section class="grid g2">
    <div class="panel"><div class="panel-head"><div><h3>Risks to watch</h3></div><span class="pill">Screen score <b class="num">${sc.score100}</b>/100</span></div>${sc.risks.length ? `<ul class="why">${sc.risks.map(r => `<li class="risk">${esc(r)}</li>`).join("")}</ul>` : `<p class="muted small">No rule-based red flags right now.</p>`}</div>
    <div class="panel"><h3>Long-term debt cycle</h3>${n.lt_score != null ? `<div class="meter"><b style="left:${n.lt_score * 100}%"></b></div><div class="scale"><span>Early</span><span>Mid</span><span>Late</span><span>Very late</span></div><p style="margin-top:8px"><b>${esc(LT[n.lt_stage])}</b> (score ${f(n.lt_score, 2)})</p><ul class="why">${n.lt_why.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : `<p class="muted small">Not enough data.</p>`}</div>
  </section>
  <section class="grid g2">
    <div class="panel"><div class="panel-head"><div><h3>Growth vs trend</h3><p>Real GDP growth with phase shading; dashed years are IMF projections.</p></div></div><div class="chart" id="c-gdp"></div></div>
    <div class="panel"><div class="panel-head"><div><h3>Inflation vs target</h3><p>CPI inflation, annual average.</p></div></div><div class="chart" id="c-cpi"></div></div>
    <div class="panel"><div class="panel-head"><div><h3>Policy rate and 10-year yield</h3><p>Monthly. A falling policy rate means easing.</p></div></div><div class="chart" id="c-rate"></div></div>
    <div class="panel"><div class="panel-head"><div><h3>OECD leading indicator</h3><p>Turns 6–9 months before the economy. 100 = trend.</p></div></div><div class="chart" id="c-cli"></div></div>
    <div class="panel"><div class="panel-head"><div><h3>Debt, % of GDP</h3><p>Government (IMF), households and companies (BIS).</p></div></div><div class="chart" id="c-debt"></div></div>
    <div class="panel"><div class="panel-head"><div><h3>${esc(c.index_name)}</h3><p>Daily closes, last 12 months${eq.note ? " · " + esc(eq.note) : ""}.</p></div></div><div class="chart" id="c-eq"></div></div>
  </section>
  <section class="grid g2">
    <div class="panel"><div class="panel-head"><div><h3>Latest news</h3><p>Past 7 days · tone ${n.news_tone.n ? `${n.news_tone.pos} positive, ${n.news_tone.neg} negative of ${n.news_tone.n}` : "n/a"}</p></div></div>${newsList(D.news.by[k])}</div>
    <div class="panel"><div class="panel-head"><div><h3>What changed</h3></div></div>${changesFeed(k)}
      ${c.notes.length ? `<h3 style="margin-top:14px">Data notes</h3><ul class="why">${c.notes.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
      <h3 style="margin-top:14px">Sources</h3><ul class="why small">${Object.entries(c.sources).map(([kk, s]) => `<li>${esc(s)}</li>`).join("")}</ul></div>
  </section>`;
  v.querySelectorAll(".chip").forEach(b => b.onclick = () => go("country/" + b.dataset.k));
  const gdp = ann(c.series.gdp, 1995);
  const now = n.phase ? {from: Y - 0.5, to: Y + 0.5, c: "--ph-" + n.phase} : null;
  lineChart($("#c-gdp"), {series: [{name: "GDP growth", c: "--s1", pts: gdp.filter(p => p[0] >= 2000), dashFrom: Y - 1}, {name: "10-year trend", c: "--ref", dash: true, pts: rolling10(gdp).filter(p => p[0] >= 2000)}], unit: "%", zero: true, bands: phaseBands(c.phases, now), events: c.events, label: "GDP growth",
    tipExtra: y => c.phases[Math.round(y)] || (Math.round(y) === Y && n.phase) ? `<div class="muted small">${PH[c.phases[Math.round(y)] || n.phase]}</div>` : ""});
  lineChart($("#c-cpi"), {series: [{name: "Inflation", c: "--s2", pts: ann(c.series.cpi, 2000), dashFrom: Y - 1}], refs: [{y: c.target, label: `Target ${c.target}%`}], unit: "%", zero: true, shadeFrom: Y - 0.5, events: c.events, label: "Inflation"});
  const rs = [];
  if (c.monthly.rate) rs.push({name: "Policy rate", c: "--s1", pts: stepify(mon(c.monthly.rate, "2010-01"))});
  if (c.monthly.y10) rs.push({name: "10-year yield", c: "--s2", pts: mon(c.monthly.y10, "2010-01")});
  if (rs.length) lineChart($("#c-rate"), {series: rs, unit: "%", zero: true, xfmt: "month", label: "Rates"}); else $("#c-rate").innerHTML = `<p class="muted small">${esc(c.notes[0] || "No free source for rates.")}</p>`;
  if (c.monthly.cli) lineChart($("#c-cli"), {series: [{name: "Leading indicator", c: "--s3", pts: mon(c.monthly.cli, "2010-01")}], refs: [{y: 100, label: "Trend"}], xfmt: "month", label: "Leading indicator"});
  else $("#c-cli").innerHTML = `<p class="muted small">The OECD does not publish a leading indicator for ${esc(c.name)}. Use the cycle phase and news instead.</p>`;
  const ds = [{name: "Government", c: "--s1", pts: ann(c.series.gov, 2000).filter(p => p[0] <= D.last_actual)}];
  if (c.series.hh) ds.push({name: "Households", c: "--s2", pts: ann(c.series.hh, 2000)});
  if (c.series.corp) ds.push({name: "Companies", c: "--s3", pts: ann(c.series.corp, 2000)});
  lineChart($("#c-debt"), {series: ds, unit: "%", label: "Debt"});
  if (eq.spark && eq.spark.close.length > 1) {
    const dates = eq.spark.dates, xs = dates.map(dayx);
    lineChart($("#c-eq"), {series: [{name: c.index_name, c: "--s1", pts: xs.map((x, i) => [x, eq.spark.close[i]])}], xfmt: "day", vfmt: v => big(v), dateOf: x => dates[xs.indexOf(x)] || "", label: c.index_name});
  } else $("#c-eq").innerHTML = `<p class="muted small">Price history builds up from daily bot runs. Latest: ${big(eq.price)} (${esc(eq.date || "")}).</p>`;
}
function stepify(pts) { const out = []; pts.forEach((p, i) => { if (i) out.push([p[0] - 1e-4, pts[i - 1][1]]); out.push(p); }); return out.filter((p, i) => i % 1 === 0); }
const tile = (k, v, d) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`;
const last = (s, y) => s ? s[y] ?? s[y - 1] : null;
const lastv = s => { if (!s) return null; const ks = Object.keys(s).sort(); return s[ks[ks.length - 1]]; };
const screenList = why => why.length ? `<ul class="why">${why.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : `<p class="muted small" style="margin-top:6px">No strong signal either way.</p>`;

/* ---------- COMPARE ---------- */
const METRICS = {
  gdp: {t: "GDP growth (annual %)", get: k => ann(E(k).series.gdp, 2000), unit: "%", proj: true},
  cpi: {t: "Inflation (annual %)", get: k => ann(E(k).series.cpi, 2000), unit: "%", proj: true},
  unemp: {t: "Unemployment rate", get: k => ann(E(k).series.unemp, 2000), unit: "%", proj: true},
  rate: {t: "Policy rate (monthly)", get: k => mon(E(k).monthly.rate, "2010-01"), unit: "%", m: true},
  y10: {t: "10-year bond yield (monthly)", get: k => mon(E(k).monthly.y10, "2010-01"), unit: "%", m: true},
  cli: {t: "OECD leading indicator", get: k => mon(E(k).monthly.cli, "2015-01"), m: true},
  gov: {t: "Government debt, % of GDP", get: k => ann(E(k).series.gov, 2000), unit: "%", proj: true},
  credit: {t: "Private credit, % of GDP", get: k => ann(E(k).series.credit, 2000), unit: "%"},
  ca: {t: "Current account, % of GDP", get: k => ann(E(k).series.ca, 2000), unit: "%", proj: true},
  eq: {t: "Stock index, rebased to 100 a year ago", get: k => { const e = E(k).now.equity; if (!e || !e.spark || e.spark.close.length < 20) return []; const b = e.spark.close[0]; return e.spark.dates.map((d, i) => [dayx(d), e.spark.close[i] / b * 100]); }, day: true},
};
function renderCompare(v) {
  const sel = state.compare.filter(k => D.economies[k]).slice(0, 4);
  const mt = METRICS[state.metric] || METRICS.gdp;
  v.innerHTML = `
  <section><p class="eyebrow">Compare</p><h2 style="margin:4px 0 8px">Up to four economies side by side</h2></section>
  <section class="panel"><div class="panel-head"><div><h3>Pick economies</h3><p>${sel.length}/4 selected. Colours stay with the economy.</p></div>
    <select id="metric" aria-label="Measure">${Object.entries(METRICS).map(([kk, m]) => `<option value="${kk}" ${kk === state.metric ? "selected" : ""}>${m.t}</option>`).join("")}</select></div>
    <div class="chips">${keys().map(kk => { const i = sel.indexOf(kk); return `<button class="chip" aria-pressed="${i >= 0}" data-k="${kk}">${i >= 0 ? `<span class="sw" style="background:var(${SERIES_COLORS[i]})"></span>` : ""}${flag(kk)} ${esc(name(kk))}</button>`; }).join("")}</div>
    <div class="chart" id="cmpchart" style="margin-top:14px"></div></section>
  <section class="tablewrap"><table><thead><tr><th class="l">Measure</th>${sel.map(kk => `<th>${flag(kk)} ${esc(name(kk))}</th>`).join("")}</tr></thead><tbody>${[
    ["Cycle phase", kk => phasePill(E(kk).now.phase), 1], ["Leading indicator", kk => E(kk).now.cli ? cliPill(E(kk).now.cli).replace("Leading: ", "") : "n/a", 1],
    ["GDP growth " + D.year, kk => fp(E(kk).now.inputs.gdp)], ["10-year trend", kk => fp(E(kk).now.inputs.trend)], ["Inflation " + D.year, kk => fp(E(kk).now.inputs.cpi)],
    ["Policy rate", kk => fp(E(kk).now.rate, 2)], ["Real rate", kk => fp(E(kk).now.real_rate)], ["10y yield", kk => fp(E(kk).now.y10, 2)],
    ["Government debt", kk => fp(E(kk).now.metrics.gov_debt, 0)], ["Current account", kk => fp(E(kk).now.metrics.ca)],
    ["Debt-cycle stage", kk => E(kk).now.lt_stage != null ? esc(LT[E(kk).now.lt_stage].split(":")[0]) : "–", 1],
    ["Stocks 1y", kk => sgn(E(kk).now.equity && E(kk).now.equity.ret_12m)], ["Stocks screen", kk => stPill("", E(kk).screen.equities.stance).replace(": ", ""), 1],
    ["Bonds screen", kk => stPill("", E(kk).screen.bonds.stance).replace(": ", ""), 1], ["Screen score", kk => E(kk).screen.score100],
  ].map(([lab, fn, raw]) => `<tr style="cursor:default"><td class="l">${lab}</td>${sel.map(kk => `<td class="${raw ? "" : "num"}">${fn(kk)}</td>`).join("")}</tr>`).join("")}</tbody></table></section>`;
  $("#metric").onchange = e => { state.metric = e.target.value; save(); renderCompare(v); };
  v.querySelectorAll(".chip").forEach(b => b.onclick = () => {
    const kk = b.dataset.k, i = state.compare.indexOf(kk);
    if (i >= 0) state.compare.splice(i, 1); else if (state.compare.length < 4) state.compare.push(kk); else toast("Four at most: remove one first");
    save(); renderCompare(v);
  });
  const series = sel.map((kk, i) => ({name: name(kk), c: SERIES_COLORS[i], pts: mt.get(kk), dashFrom: mt.proj ? D.year - 1 : null}));
  lineChart($("#cmpchart"), {series, unit: mt.unit || "", zero: !mt.day && state.metric !== "cli", shadeFrom: mt.proj ? D.year - 0.5 : null, xfmt: mt.day ? "day" : mt.m ? "month" : null, legend: true, height: 300, refs: state.metric === "cli" ? [{y: 100, label: "Trend"}] : mt.day ? [{y: 100, label: "A year ago"}] : [], label: mt.t});
  if (sel.length === 0) $("#cmpchart").innerHTML = `<p class="muted">Pick at least one economy.</p>`;
}

/* ---------- OPPORTUNITIES ---------- */
function renderOpps(v) {
  const ks = keys().slice().sort((a, b) => E(b).screen.score100 - E(a).screen.score100);
  v.innerHTML = `
  <section><p class="eyebrow">Opportunities</p><h2 style="margin:4px 0 8px">Where the cycle favours each asset class</h2>
  <p class="lede">Each economy is screened with fixed rules: its cycle phase and leading indicator, the direction of interest rates, market momentum, real interest rates, inflation trend, external balances and this week's news tone. The score blends stocks (50%), bonds (25%) and currency (25%). The reasons are listed so you can disagree with them.</p></section>
  <section class="banner"><b>Not investment advice.</b> These are mechanical signals for learning and research. They ignore valuations, fees, taxes and your own situation. Check them against other sources and, for real decisions, a licensed adviser.</section>
  <section class="panel">${ks.map(k => { const s = E(k).screen; return `<div class="opp">
    <div><h3 data-k="${k}">${flag(k)} ${esc(name(k))}</h3><div class="pills" style="margin-top:6px">${phasePill(E(k).now.phase)}${cliPill(E(k).now.cli)}</div>${s.risks.length ? `<ul class="why">${s.risks.slice(0, 3).map(r => `<li class="risk">${esc(r)}</li>`).join("")}</ul>` : ""}</div>
    <div class="col">${stPill("Stocks", s.equities.stance)}${screenList(s.equities.why.slice(0, 3))}</div>
    <div class="col">${stPill("Bonds", s.bonds.stance)}${screenList(s.bonds.why.slice(0, 3))}</div>
    <div class="col">${stPill("Currency", s.currency.stance)}${screenList(s.currency.why.slice(0, 3))}</div>
    <div class="score" title="Screen score out of 100">${s.score100}</div></div>`; }).join("")}</section>
  <section class="panel"><h3>Cycle playbook: what has tended to work in each phase</h3><div class="tablewrap" style="margin-top:10px"><table><tbody>${Object.keys(PH).map(p => `<tr style="cursor:default"><td class="l">${phasePill(p)}</td><td class="l" style="white-space:normal">${esc(PH_DESC[p])}</td><td class="l" style="white-space:normal">${esc(PLAYBOOK[p])}</td><td class="l" style="white-space:normal">${realKeys().filter(k => E(k).now.phase === p).map(k => flag(k) + " " + esc(name(k))).join(", ") || "<span class='muted'>none now</span>"}</td></tr>`).join("")}</tbody></table></div></section>`;
  v.querySelectorAll(".opp h3").forEach(h => h.onclick = () => go("country/" + h.dataset.k));
}

/* ---------- NEWS ---------- */
function renderNews(v) {
  const all = [];
  Object.entries(D.news.by).forEach(([k, arr]) => (arr || []).forEach(n => all.push({...n, _k: k})));
  const topics = [...new Set(all.flatMap(n => n.topics || []))].sort();
  const filt = all.filter(n => (state.newsCountry === "ALL" || n._k === state.newsCountry) && (state.newsTopic === "ALL" || (n.topics || []).includes(state.newsTopic)) && (state.newsTone === "ALL" || String(n.tone) === state.newsTone)).sort((a, b) => b.ts - a.ts);
  const tones = keys().map(k => ({label: `${flag(k)} ${name(k)}`, v: E(k).now.news_tone.n ? E(k).now.news_tone.score * 100 : 0, title: `${name(k)}: ${E(k).now.news_tone.pos} positive, ${E(k).now.news_tone.neg} negative of ${E(k).now.news_tone.n}`})).sort((a, b) => b.v - a.v);
  v.innerHTML = `
  <section><p class="eyebrow">News bot</p><h2 style="margin:4px 0 8px">Headlines by economy</h2><p class="lede">Collected hourly from Google News (Bing News as backup). Each headline is tagged by topic and scored positive, negative or neutral with keyword rules, which are simple and sometimes wrong, so read the article before acting on it.</p></section>
  <section class="grid g2" style="grid-template-columns:minmax(0,2fr) minmax(0,1fr)">
    <div class="panel"><div class="panel-head"><div><h3>${filt.length} headlines</h3></div><div class="chips">
      <select id="nc" aria-label="Economy"><option value="ALL">All economies</option><option value="WORLD">🌐 World</option>${keys().map(k => `<option value="${k}">${flag(k)} ${esc(name(k))}</option>`).join("")}</select>
      <select id="nt" aria-label="Topic"><option value="ALL">All topics</option>${topics.map(t => `<option>${esc(t)}</option>`).join("")}</select>
      <select id="no" aria-label="Tone"><option value="ALL">Any tone</option><option value="1">Positive</option><option value="-1">Negative</option><option value="0">Neutral</option></select></div></div>
      ${newsList(filt.slice(0, 150), true).replace('class="feed"', 'class="feed" style="max-height:none"')}</div>
    <div class="panel"><div class="panel-head"><div><h3>News tone this week</h3><p>Positive minus negative headlines, as % of all.</p></div></div>${bars(tones, v => sgn(v, 0, ""))}</div>
  </section>`;
  $("#nc").value = state.newsCountry; $("#nt").value = state.newsTopic; $("#no").value = state.newsTone;
  $("#nc").onchange = e => { state.newsCountry = e.target.value; renderNews(v); };
  $("#nt").onchange = e => { state.newsTopic = e.target.value; renderNews(v); };
  $("#no").onchange = e => { state.newsTone = e.target.value; renderNews(v); };
}

/* ---------- METHOD ---------- */
function renderMethod(v) {
  const bad = (D.health || []).filter(h => !h.ok);
  v.innerHTML = `
  <section><p class="eyebrow">How it works</p><h2 style="margin:4px 0 8px">The machine behind the dashboard</h2>
  <p class="lede">A small bot (a Python script run by GitHub Actions) wakes up every hour. It pulls markets, exchange rates and headlines, and once a day the slower economic data. It runs the rules below, writes one data file and republishes the site. This page checks for that file every 2 minutes, so it updates by itself.</p></section>
  <section class="grid g2">
    <div class="panel"><h3>Data health</h3>
      <p class="small" style="margin-top:6px">Last run: <b>${esc(new Date(D.generated_ts * 1000).toLocaleString())}</b> (${ago(D.generated_ts)}). Economic data last fetched ${ago(D.macro_fetched_ts)}.</p>
      ${bad.length ? `<p class="small" style="margin-top:8px">${bad.length} source warning${bad.length > 1 ? "s" : ""} on the latest run. Each affected series keeps its last good value:</p><ul class="why small">${bad.slice(0, 12).map(h => `<li>${esc(h.source)}: ${esc(h.detail)}</li>`).join("")}</ul>` : `<p class="small up" style="margin-top:8px">All sources responded on the latest run.</p>`}
      <h3 style="margin-top:14px">Update schedule</h3><ul class="why small"><li>Markets, FX, news: every hour</li><li>IMF, World Bank, BIS, OECD, FRED: once a day (they publish monthly to yearly)</li><li>The page re-checks every 2 minutes and shows a notice when new data lands</li></ul></div>
    <div class="panel"><h3>Short-term business cycle (yearly rules, checked in order)</h3><ul class="why">
      <li><b>Recession</b>: growth under 0.5%, more than 3.5 pts under its 10-year trend, or unemployment up more than 0.8 pts.</li>
      <li><b>Tightening</b>: the central bank raised rates by more than 0.25 pts while inflation is more than 0.5 pts over target.</li>
      <li><b>Late expansion</b>: growth above trend and inflation more than 0.5 pts over target.</li>
      <li><b>Slowdown</b>: growth at or under trend and rates being cut.</li>
      <li><b>Early expansion</b>: growth above trend, inflation near or under target, and growth speeding up.</li>
      <li><b>Mid expansion</b>: everything else.</li></ul>
      <p class="small muted" style="margin-top:6px">The current year uses IMF projections for growth and inflation and the latest monthly policy rate. Before a central bank adopted an inflation target, the 10-year median inflation is the benchmark.</p></div>
    <div class="panel"><h3>OECD business-cycle clock</h3><p class="small" style="margin-top:6px">The composite leading indicator tracks orders, confidence, spreads and share prices, and turns 6–9 months before GDP. Above 100 and rising is <b>expansion</b>, above 100 and falling is <b>downturn</b>, below 100 and falling is <b>slowdown</b>, below 100 and rising is <b>recovery</b>. Recovery is historically the best entry point for stocks. Uses the 3-month change.</p></div>
    <div class="panel"><h3>Long-term debt cycle</h3><p class="small" style="margin-top:6px">After Ray Dalio's framework, a 0–1 score from: government debt against an advanced- or emerging-economy yardstick, total non-financial debt, its 10-year change, whether rates have needed the zero bound since 2008, whether bond yields sit above nominal growth, and any sovereign default in the last 10 years. Under 0.3 is early, under 0.5 mid, under 0.7 late, above that very late.</p></div>
    <div class="panel"><h3>Investment screen</h3><p class="small" style="margin-top:6px"><b>Stocks</b>: cycle phase, leading indicator, 12-month rate direction, momentum (above the 200-day average), a dip from the 1-year high while the cycle turns up, and news tone. <b>Bonds</b>: real policy rate, the inflation trend, slowing growth, the yield above inflation, and the debt load. <b>Currency</b>: current account, reserves, real rate and 12-month trend. Over +1.25 is Favourable, under −0.75 is Cautious. Score out of 100 = 50% stocks, 25% bonds, 25% currency.</p></div>
    <div class="panel"><h3>Sources</h3><ul class="why small"><li>IMF World Economic Outlook (DataMapper API): growth, inflation, unemployment, debt, current account, GDP, projections</li><li>World Bank: reserves, fallbacks</li><li>BIS: policy rates, private credit, debt-service ratios</li><li>OECD: composite leading indicators</li><li>FRED (St. Louis Fed): 10-year bond yields</li><li>Yahoo Finance: stock indices, commodities, VIX</li><li>Colombo Stock Exchange: ASPI</li><li>ECB (Frankfurter) and open.er-api: exchange rates</li><li>Google News / Bing News RSS: headlines</li></ul></div>
  </section>
  <section class="disclaimer">Built for education and research. Every label comes from published rules over public data; nothing is hand-picked. Signals are not investment advice.</section>`;
}

/* ---------- boot ---------- */
(function initTheme() {
  let t = null; try { t = localStorage.getItem("emm-theme"); } catch (e) {}
  if (t) document.documentElement.dataset.theme = t;
  $("#theme").onclick = () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const nx = cur === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = nx;
    try { localStorage.setItem("emm-theme", nx); } catch (e) {}
  };
})();
window.addEventListener("hashchange", route);
let rz, lastW = innerWidth; window.addEventListener("resize", () => { if (innerWidth === lastW) return; lastW = innerWidth; clearTimeout(rz); rz = setTimeout(() => { const y = scrollY; render(); scrollTo(0, y); }, 200); });
load(true).then(route);
setInterval(() => load(false), POLL_MS);
setInterval(setStatus, 30000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(false); });
