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
const SERIES_COLORS = ["--s1", "--s2", "--s3", "--s4"];
const PLAYBOOK = {
  early:"Equities and cyclical sectors usually lead; credit spreads narrow.",
  mid:"Broad equities still fine; quality and earnings growth matter more.",
  late:"Commodities and value tend to hold up; bonds suffer if rates rise.",
  tight:"Cash and short-term bonds; equities are vulnerable to rate rises.",
  slow:"Long-term government bonds and defensive sectors usually do best.",
  rec:"Bonds first; equities bottom before the economy does, so watch the leading indicator.",
};

let D = null, lastGenerated = null, state = {tab:"world", country:"US", year:null, local:null, inflMode:"annual", compare:["US","CN","IN","EA"], metric:"gdp", newsCountry:"ALL", newsTopic:"ALL", newsTone:"ALL", sort:{key:"share", dir:-1}, shareMode:"ppp"};
try { const s = JSON.parse(localStorage.getItem("emm-state") || "{}"); Object.assign(state, s); } catch (e) {}
function save() { try { localStorage.setItem("emm-state", JSON.stringify({compare:state.compare, metric:state.metric, shareMode:state.shareMode, inflMode:state.inflMode})); } catch (e) {} }

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
/* An economy as the page should show it. Where the bot supplies a second reading of the current year based on the
   latest monthly inflation (Sri Lanka), the reader chooses which one to use; the choice applies on every tab. */
let viewCache = {};
const E = k => {
  const e = D.economies[k];
  if (!e || !e.monthly_view || state.inflMode !== "monthly") return e;
  const key = k + D.generated;
  if (!viewCache[key]) { const m = e.monthly_view; viewCache = {...viewCache, [key]: {...e, now: {...e.now, phase: m.phase, inputs: m.inputs}, screen: m.screen, summary: m.summary}}; }
  return viewCache[key];
};
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
const cliPill = c => c ? `<span class="pill" title="${esc(c.label || "OECD leading indicator")} ${c.level} (${sgn(c.chg3m, 2, "")} over 3 months to ${c.month})" style="--c:var(${CLI_COLOR[c.phase]})"><i></i>Leading: ${CLI[c.phase]}</span>` : "";
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
  state.tab = ["world", "country", "compare", "machine", "opportunities", "news", "method"].includes(h[0]) ? h[0] : "world";
  if (state.tab === "country" && h[1] && D && D.economies[h[1]]) state.country = h[1];
  document.querySelectorAll("#tabs a").forEach(a => a.setAttribute("aria-current", a.getAttribute("href") === "#" + state.tab ? "page" : "false"));
  render(); window.scrollTo({top: 0});
}
function render() {
  if (!D) return;
  const v = $("#view");
  ({world: renderWorld, country: renderCountry, compare: renderCompare, machine: renderMachine, opportunities: renderOpps, news: renderNews, method: renderMethod})[state.tab](v);
  v.insertAdjacentHTML("beforeend", `<footer><span>Data: IMF, World Bank, BIS, OECD, FRED, Eurostat, central banks and treasuries (CBSL, MAS, CFETS, Tesouro Nacional), Yahoo Finance, CSE, ECB, Google News.</span><span>Generated ${esc(new Date(D.generated_ts * 1000).toUTCString())}.</span><span>Educational tool: rule-based signals, not investment advice.</span></footer>`);
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
  return `<div class="feed">${list.map(c => `<div class="item"><span class="tone z" title="${esc(c.kind)}">${{cycle: "◔", cli: "↗", rates: "%", screen: "★", markets: "≋", debt: "∿"}[c.kind] || "•"}</span><span class="t">${esc(c.text)}</span><span class="m"><span>${ago(c.ts)}</span><span class="tag">${esc(c.kind)}</span></span></div>`).join("")}</div>`;
}
function newsList(items, showCountry) {
  if (!items || !items.length) return `<p class="muted small">No headlines right now.</p>`;
  return `<div class="feed">${items.map(n => `<div class="item"><span class="tone ${n.tone > 0 ? "p" : n.tone < 0 ? "n" : "z"}" title="Tone: ${n.tone > 0 ? "positive" : n.tone < 0 ? "negative" : "neutral"}">${n.tone > 0 ? "+" : n.tone < 0 ? "−" : "·"}</span>
    <a class="t" href="${esc(safeUrl(n.link))}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>
    <span class="m">${showCountry ? `<span>${flag(n._k)} ${esc(name(n._k))}</span>` : ""}<span>${esc(n.source)}</span><span>${ago(n.ts)}</span>${(n.topics || []).map(t => `<span class="tag">${esc(t)}</span>`).join("")}</span></div>`).join("")}</div>`;
}
function renderWorld(v) {
  const w = D.world, n = w.now, Y = D.year;
  const cnt = {}; realKeys().forEach(k => { const p = E(k).now.phase; if (p) cnt[p] = (cnt[p] || 0) + 1; });
  v.innerHTML = `
  <section><p class="eyebrow">World economy · ${Y}</p><h2 style="margin:4px 0 8px">The global picture</h2><p class="lede">${md(w.summary)}</p></section>
  ${aiPanel("world")}
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
    <div class="panel"><div class="panel-head"><div><h3>Business-cycle clock (leading indicators)</h3><p>OECD composite leading indicators; the euro area uses the European Commission's sentiment indicator. Level vs 100 (long-run trend) and the 3-month change. Economies move clockwise: recovery → expansion → downturn → slowdown. Click a dot to open the country.</p></div></div><div class="chart" id="clock"></div></div>
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
  wireAi("world");
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
  {k: "lt", t: "Long-term debt cycle", l: true, v: k => E(k).now.lt ? E(k).now.lt.pos : null, h: k => { const l = E(k).now.lt; return l ? `<span class="pill" title="${esc(l.rule)}" style="--c:var(${LTS[l.stage].c})"><i></i>${esc(LTS[l.stage].s)}</span>` : "–"; }},
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

/* Countries, Compare and The Machine tabs live in cycles.js */
const tile = (k, v, d) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`;

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
      ${state.local ? `<p style="margin-top:10px"><button class="btn" id="refresh-now" type="button">Refresh data now</button> <span class="muted small" id="refresh-status">Running on this computer: data refreshes when the dashboard starts and every hour while its window stays open.</span></p>` : ""}
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
    <div class="panel"><h3>Long-term debt cycle</h3><p class="small" style="margin-top:6px">After Ray Dalio's framework. A 0–1 <b>debt-pressure score</b> comes from government debt against an advanced- or emerging-economy yardstick, total non-financial debt, its 10-year change, whether rates have needed the zero bound since 2008, and whether interest rates sit above nominal growth. The score, plus the signs of a debt crisis and its repair, place each economy on five stages: early, bubble building, top, deleveraging, normalisation. The four deleveraging levers and the three rules of thumb are read from budget, revenue, credit and productivity data. <a href="#machine">The Machine</a> tab lists every rule.</p></div>
    <div class="panel"><h3>Investment screen</h3><p class="small" style="margin-top:6px"><b>Stocks</b>: cycle phase, leading indicator, 12-month rate direction, momentum (above the 200-day average), a dip from the 1-year high while the cycle turns up, and news tone. <b>Bonds</b>: real policy rate, the inflation trend, slowing growth, the yield above inflation, and the debt load. <b>Currency</b>: current account, reserves, real rate and 12-month trend. Over +1.25 is Favourable, under −0.75 is Cautious. Score out of 100 = 50% stocks, 25% bonds, 25% currency.</p></div>
    <div class="panel"><h3>Sources</h3><ul class="why small"><li>IMF World Economic Outlook (DataMapper API): growth, inflation, unemployment, debt, current account, GDP, projections</li><li>World Bank: reserves, fallbacks</li><li>BIS: policy rates, private credit, debt-service ratios</li><li>OECD: composite leading indicators</li><li>FRED (St. Louis Fed): 10-year bond yields</li><li>Yahoo Finance: stock indices, commodities, VIX</li><li>Colombo Stock Exchange: ASPI</li><li>ECB (Frankfurter) and open.er-api: exchange rates</li><li>Google News / Bing News RSS: headlines</li><li>Central Bank of Sri Lanka: policy rate, Treasury bill and bond yields, monthly CCPI inflation</li><li>Colombo Stock Exchange: All Share index and its history</li><li>China Foreign Exchange Trade System, Tesouro Nacional (Brazil), Monetary Authority of Singapore: 10-year government bond yields</li><li>European Commission via Eurostat: euro-area economic sentiment</li></ul></div>
  </section>
  <section class="disclaimer">Built for education and research. Every label comes from published rules over public data; nothing is hand-picked. Signals are not investment advice.</section>`;
  const rb = $("#refresh-now");
  if (rb) rb.onclick = async () => { rb.disabled = true;
    try { const r = await fetch("api/refresh", {method: "POST", headers: {"Content-Type": "application/json", "X-Dashboard": "local"}, body: "{}"}); $("#refresh-status").textContent = (await r.json()).text; }
    catch (e) { $("#refresh-status").textContent = "Could not reach the local dashboard server."; }
    setTimeout(() => { rb.disabled = false; }, 60000); };
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
/* served by run_local.py? then the Ask AI button and "Refresh now" are available */
fetch("api/status", {cache: "no-store"}).then(r => r.ok ? r.json() : null).then(s => { if (s && s.local) { state.local = s; if (D) render(); } }).catch(() => {});
load(true).then(route);
setInterval(() => load(false), POLL_MS);
setInterval(setStatus, 30000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(false); });
