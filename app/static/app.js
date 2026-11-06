/* TickLens front end: lightweight-charts v5 + WebSocket to the Python engine. */
(() => {
"use strict";
const LW = LightweightCharts;
const $ = (s) => document.querySelector(s);
const QS = new URLSearchParams(location.search);
const SLOT = Math.max(0, Math.min(3, +QS.get("slot") || 0));   // multi-chart layout: 0 = this page, 1..3 = embedded charts
const EMBED = SLOT > 0;
const SKEY = EMBED ? `ltv.state.${SLOT}` : "ltv.state";
if (EMBED) document.documentElement.classList.add("embed");
const TFS = [["1m", 60], ["3m", 180], ["5m", 300], ["15m", 900], ["30m", 1800], ["1h", 3600], ["1D", 86400], ["1W", 604800], ["1M", 2592000]];
let TZ = 0;                                                // display offset of the chosen timezone (chart settings)
const loc = (t) => t + TZ;

// ------------------------------------------------------------------ state
const DEFAULT = {
  source: "yf", symbol: "RELIANCE", tf: 300, chartType: "candles", theme: "dark",
  indicators: [], // {id, ref, code, inputs, visible}
  watchlist: ["NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN"],   // app names, any source
};
let S;
let HAD_STATE = false;
try { HAD_STATE = !!localStorage.getItem(SKEY); } catch { /* storage unavailable */ }
try { S = Object.assign({}, DEFAULT, JSON.parse(localStorage.getItem(SKEY) || "{}")); } catch { S = { ...DEFAULT }; }
// One name per instrument for every source (server maps RELIANCE -> RELIANCE.NS / RELIND, NIFTY -> ^NSEI / NIFTY)
const IDX_ALIASES = { "^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "CNXBAN": "BANKNIFTY", "NIFTY_FIN_SERVICE.NS": "FINNIFTY",
  "NIFFIN": "FINNIFTY", "^CNXIT": "NIFTYIT", "CNXIT": "NIFTYIT", "^BSESN": "SENSEX", "BSESEN": "SENSEX", "BSE-BANK.BO": "BANKEX" };
const canon = (x) => { const s = String(x).trim().toUpperCase().replace(/\s+/g, " "); return IDX_ALIASES[s] || s.replace(/\.NS$/, ""); };
if (!["yf", "breeze", "tv"].includes(S.source)) S.source = "yf";
const SRC_NAME = { yf: "Yahoo", breeze: "Breeze", tv: "TradingView" };
// each symbol carries its source: TradingView names have an exchange prefix (MCX:GOLD1!), F&O is Breeze only,
// the rest remember the source they were picked from (shared by every chart of the layout)
const FNO_RE = /^(\S+) \d{2}[A-Z]{3}\d{2} (FUT|\S+ (CE|PE))$/;
const symSrcMap = () => { try { return JSON.parse(localStorage.getItem("ltv.symsrc") || "{}"); } catch { return {}; } };
const srcFor = (sym) => {
  sym = String(sym);
  if (sym.includes(":")) return "tv";
  if (FNO_RE.test(sym)) return "breeze";
  const s = symSrcMap()[sym] || S.source;
  return s === "breeze" && !S.breezeOk ? "yf" : s;
};
const setSymSrc = (sym, src) => {
  if (!src || String(sym).includes(":")) return;
  const m = symSrcMap(); m[sym] = src;
  try { localStorage.setItem("ltv.symsrc", JSON.stringify(m)); } catch { /* storage unavailable */ }
};
const SRC_TAG = { yf: "YF", breeze: "Breeze", tv: "TV" };
// listing exchange shown next to every Indian symbol: BSE (SENSEX, BANKEX, their F&O, .BO, BSE:), MCX, else NSE
const BSE_IDX = new Set(["SENSEX", "BANKEX"]);
const NSE_IDX = new Set(["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYIT", "NIFTYNXT50", "INDIAVIX"]);
function exchOf(sym) {
  const s = String(sym).toUpperCase();
  const ex = s.includes(":") ? s.split(":")[0] : "";
  if (ex) return ["NSE", "BSE", "MCX"].includes(ex) ? ex : "";
  const base = s.split(" ")[0];
  if (BSE_IDX.has(base) || s.endsWith(".BO")) return "BSE";
  if (NSE_IDX.has(base) || FNO_RE.test(s)) return "NSE";
  return /[.^=/]|-USD$/.test(s) ? "" : "NSE";
}
const exTag = (ex) => (ex ? `<i class="ex-tag ${ex.toLowerCase()}" title="Listed on ${ex}">${ex}</i>` : "");
S.symbol = canon(S.symbol);
S.chart = Object.assign({}, LTVSettings.DEFAULTS, S.chart || {});
const CS = S.chart;                // chart settings (settings.js dialog + price-scale menu)
function tzOffset(tz) {
  if (tz === "local") return -new Date().getTimezoneOffset() * 60;
  const zone = tz === "exchange" ? "Asia/Kolkata" : tz;
  try {
    const now = new Date(), at = (z) => Date.parse(now.toLocaleString("en-US", { timeZone: z }));
    return Math.round((at(zone) - at("UTC")) / 60000) * 60;
  } catch { return 19800; }
}
TZ = tzOffset(CS.timezone);
// migrate old {source, symbol} entries, drop non-NSE sim/crypto rows, de-duplicate
const cleanList = (items) => [...new Set((items || []).filter((w) => typeof w === "string" || ["yf", "breeze", "nse"].includes(w.source))
  .map((w) => canon(typeof w === "string" ? w : w.symbol)))];
// several named watchlists; S.watchlist is always the items array of the current one
if (!Array.isArray(S.watchlists) || !S.watchlists.length) S.watchlists = [{ name: "Watchlist", items: S.watchlist || DEFAULT.watchlist }];
S.watchlists = S.watchlists.map((l, i) => ({ name: String(l.name || `List ${i + 1}`), items: cleanList(l.items) }));
S.wlActive = Math.min(Math.max(0, S.wlActive | 0), S.watchlists.length - 1);
S.watchlist = S.watchlists[S.wlActive].items;
// status-line inputs / values are now off by default for every indicator: drop flags saved under the old default once
if (!S.legendV2) {
  for (const it of S.indicators || []) if (it.style) { delete it.style.showInputs; delete it.style.showValues; }
  S.legendV2 = true;
}
const save = () => {
  try {
    localStorage.setItem(SKEY, JSON.stringify({
      ...S, indicators: S.indicators.map(({ id, ref, code, inputs, visible, style }) => ({ id, ref, code, inputs, visible, style })),
    }));
  } catch { /* storage unavailable */ }
};

const RP_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M11.5 6v12L3 12zM21 6v12l-8.5-6z"/></svg>';
const RP_SPEEDS = [10, 7, 5, 3, 1, 0.5, 0.3, 0.1];
const RP = { mode: null, t: null, step: null, speed: 1, playing: false, end: false, busy: false, timer: null, sent: 0, view: null };
let bars = [];                    // [t,o,h,l,c,v] UTC seconds
const inds = new Map();           // id -> runtime indicator
let scripts = [];                 // catalogue from /api/scripts
let editingId = null;
let hideInds = false;          // "Hide indicators" from the drawing toolbar             // indicator bound to the editor

// ------------------------------------------------------------------ chart
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
document.documentElement.dataset.theme = S.theme;
const chart = LW.createChart($("#chart"), {
  autoSize: true,
  layout: { attributionLogo: true, panes: { separatorColor: css("--border") } },
  crosshair: { mode: LW.CrosshairMode.Normal },
  rightPriceScale: { borderVisible: false },
  timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 8 },
});
function applyTheme() {
  document.documentElement.dataset.theme = S.theme;
  applyChartSettings();
}

let mainSeries, markersApi;
let barColors = new Map();       // bar time -> [body, border] from indicators' barcolor()
let zones = null;                 // LTVZones renderer (indicator boxes/labels/lines/tables)
// volume is drawn by the "Volume" indicator (builtins/volume.py)

function makeMain() {
  if (mainSeries) chart.removeSeries(mainSeries);
  const up = css("--up"), down = css("--down");
  const t = S.chartType;
  if (t === "line") mainSeries = chart.addSeries(LW.LineSeries, { color: css("--accent"), lineWidth: 2 });
  else if (t === "area") mainSeries = chart.addSeries(LW.AreaSeries, { lineColor: css("--accent"), topColor: "rgba(41,98,255,.35)", bottomColor: "rgba(41,98,255,0)" });
  else if (t === "bars") mainSeries = chart.addSeries(LW.BarSeries, { upColor: CS.upColor || up, downColor: CS.downColor || down });
  else mainSeries = chart.addSeries(LW.CandlestickSeries, candleOpts());
  markersApi = LW.createSeriesMarkers(mainSeries, []);
  priceLines = {};
  alertLines = [];
  tradeLines = [];
  applyMainOpts();
  setMainData();
  refreshMarkers();
  paintAlertLines();
  paintTradeLines();
}
// paper trades of this symbol: entry / SL / target / exit-limit lines with live P&L (trades live in the host page)
let tradeLines = [], tradeDrag = null;
function paintTradeLines() {
  if (!mainSeries) return;
  if (tradeDrag) return;                      // keep the line under the mouse while dragging
  const list = window.top.LTVTrade?.linesFor?.(S.symbol) || [];
  if (list.length === tradeLines.length && list.every((l, i) => tradeLines[i].key === l.id + l.k)) {
    list.forEach((l, i) => { tradeLines[i].spec = l; tradeLines[i].line.applyOptions({ price: l.price, color: l.color, title: l.title }); });
    return;
  }
  for (const l of tradeLines) { try { mainSeries.removePriceLine(l.line); } catch { /* series replaced */ } }
  tradeLines = list.map((l) => ({ key: l.id + l.k, spec: l, line: mainSeries.createPriceLine({ price: l.price, color: l.color, lineWidth: l.width || 1,
    lineStyle: l.style ?? 2, axisLabelVisible: true, title: l.title }) }));
}
// trade / order lines are moved only by their price-axis label, never by the line itself (the chart pans / zooms freely over the lines)
function onPriceAxis(x) {
  const left = !!chart.options().leftPriceScale?.visible, w = chart.priceScale(left ? "left" : "right").width();
  const W = $("#chart").getBoundingClientRect().width;
  return w > 0 && (left ? x <= w : x >= W - w);
}
function tradeLineAt(x, y) {
  if (!onPriceAxis(x)) return null;
  const tol = document.body.classList.contains("m") ? 14 : 10;     // half the height of the axis label box
  let best = null;
  for (const l of tradeLines) {
    if (!l.spec.drag) continue;
    const ly = mainSeries.priceToCoordinate(l.spec.price);
    if (ly != null && Math.abs(ly - y) <= tol && (!best || Math.abs(ly - y) < best.d)) best = { l, d: Math.abs(ly - y) };
  }
  return best?.l || null;
}
{
  const wrapEl = $("#chartWrap"), chartEl = $("#chart");
  const xy = (e) => { const r = chartEl.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  const LBL = { sl: "SL", target: "TGT", exitLimit: "EXIT LMT" };
  wrapEl.addEventListener("pointerdown", (e) => {
    if (tradeDrag || e.button !== 0 || !mainSeries || !tradeLines.length) return;
    const l = tradeLineAt(...xy(e)); if (!l) return;
    e.preventDefault(); e.stopPropagation();
    tradeDrag = { l, pid: e.pointerId, moved: false };
    chart.applyOptions({ handleScroll: false, handleScale: false });
    try { wrapEl.setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
  }, true);
  wrapEl.addEventListener("pointermove", (e) => {
    if (!mainSeries) return;
    const [x, y] = xy(e);
    if (tradeDrag) {
      e.stopPropagation(); e.preventDefault();
      const p = mainSeries.coordinateToPrice(y); if (p == null) return;
      const px = Math.round(p * 20) / 20, l = tradeDrag.l;
      if (px !== l.spec.price) tradeDrag.moved = true;
      l.spec.price = px;
      l.line.applyOptions({ price: px, title: LBL[l.spec.k] ? `${LBL[l.spec.k]} ${fmt(px, mainPrecision())}` : l.spec.title });
      return;
    }
    if (tradeLines.length) chartEl.style.cursor = tradeLineAt(x, y) ? "ns-resize" : "";
  }, true);
  // always hand pan / zoom back to the chart (also when the pointer is lost: pointercancel, capture lost, window blur)
  const end = (e, commit = true) => {
    if (!tradeDrag) return;
    e?.stopPropagation?.();
    const { l, moved, pid } = tradeDrag;
    tradeDrag = null;
    chart.applyOptions({ handleScroll: true, handleScale: true });
    try { wrapEl.releasePointerCapture(pid); } catch { /* not captured */ }
    if (commit && moved) window.top.LTVTrade?.setLevel(l.spec.id, l.spec.k, l.spec.price);
    else paintTradeLines();
  };
  wrapEl.addEventListener("pointerup", (e) => end(e), true);
  wrapEl.addEventListener("pointercancel", (e) => end(e, false), true);
  wrapEl.addEventListener("lostpointercapture", (e) => end(e), true);
  window.addEventListener("blur", () => end(null, false));
}
// price alerts of this symbol as dashed lines (alerts live in the host page's sidebar)
let alertLines = [];
function paintAlertLines() {
  for (const l of alertLines) { try { mainSeries.removePriceLine(l); } catch { /* series replaced */ } }
  alertLines = [];
  const list = window.top.LTVSide?.alertsFor?.(S.symbol) || [];
  for (const a of list) alertLines.push(mainSeries.createPriceLine({ price: a.price, color: a.active ? "#f2994a" : "#787b86", lineWidth: 1, lineStyle: 2,
    axisLabelVisible: true, title: `⏰ ${a.ind ? a.ind.title + " " : ""}${a.cond === "cross" ? "Crossing" : a.cond === "above" ? "Above" : "Below"}` }));
  for (const o of window.top.LTVSide?.ordersFor?.(S.symbol) || []) alertLines.push(mainSeries.createPriceLine({ price: o.price, color: o.side === "buy" ? "#2962ff" : "#f23645",
    lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: `${o.side === "buy" ? "Buy" : "Sell"} ${o.qty} ${o.type}` }));
}

function haOf(i, prev) {
  const [t, o, h, l, c] = bars[i];
  const hc = (o + h + l + c) / 4;
  const ho = prev ? (prev.open + prev.close) / 2 : (o + c) / 2;
  return { time: loc(t), open: ho, high: Math.max(h, ho, hc), low: Math.min(l, ho, hc), close: hc };
}
let ha = [];
function point(i) {
  const [t, o, h, l, c] = bars[i];
  if (S.chartType === "line" || S.chartType === "area") return { time: loc(t), value: c };
  if (S.chartType === "ha") return ha[i];
  const pt = { time: loc(t), open: o, high: h, low: l, close: c };
  const bc = barColors.get(t);
  if (bc) {                                          // indicator barcolor() wins over chart colours
    if (S.chartType === "bars") pt.color = bc[0];
    else if (bc[1] === "chart") pt.color = bc[0];     // body only: keep the chart's own border / wick colours
    else Object.assign(pt, { color: bc[0], borderColor: bc[1] || bc[0], wickColor: bc[1] || bc[0] });
    return pt;
  }
  if (CS.colorPrev && i > 0) {                       // colour by close vs previous close (TradingView option)
    const up = c >= bars[i - 1][4];
    const body = !CS.body ? "rgba(0,0,0,0)" : S.chartType === "hollow" && up ? "rgba(0,0,0,0)" : up ? CS.upColor : CS.downColor;
    if (S.chartType === "bars") pt.color = up ? CS.upColor : CS.downColor;
    else Object.assign(pt, { color: body, borderColor: up ? CS.borderUp : CS.borderDown, wickColor: up ? CS.wickUp : CS.wickDown });
  }
  return pt;
}
function setMainData() {
  if (S.chartType === "ha") { ha = []; bars.forEach((_, i) => ha.push(haOf(i, ha[i - 1]))); }
  mainSeries.setData(bars.map((_, i) => point(i)));
}
function onVolume(m) {
  const byT = new Map(m.bars);
  for (const b of bars) if (byT.has(b[0])) b[5] = byT.get(b[0]);
  volumeSrc = m.src;
  volLoading(/^loading/.test(m.src) ? `Volume · ${m.src.replace("loading ", "")} (newest first)` : null);
  status(`${SRC_NAME[srcFor(S.symbol)]} · live · volume: ${m.src}`, "live");
}
function onBar(b) {
  const n = bars.length;
  if (n && b[0] > bars[n - 1][0]) markPriceLinesDirty();
  if (n && b[0] < bars[n - 1][0]) return;
  if (n && b[0] === bars[n - 1][0]) bars[n - 1] = b; else bars.push(b);
  const i = bars.length - 1;
  if (S.chartType === "ha") ha[i] = haOf(i, ha[i - 1]);
  mainSeries.update(point(i));
  if (!hovering) showMainLegend(i);
}

// ------------------------------------------------------------------ loading indicators
const LOADER = '<div class="ld-candles"><i></i><i></i><i></i><i></i><i></i></div>';
const SPIN = '<span class="spin"></span>';
function chartLoading(on, text = "") {
  const el = $("#chartLoader");
  el.classList.toggle("show", on);
  if (on) el.querySelector(".ld-text").textContent = text;
}
function volLoading(text) {
  const el = $("#volLoader");
  el.classList.toggle("show", !!text);
  if (text) el.querySelector(".ld-text").textContent = text;
}
function setIndPending(ind, on) {
  ind.pending = on;
  const row = ind.legendRow;
  if (row) row.classList.toggle("pending", on);
}

// ------------------------------------------------------------------ legend
let hovering = false;
let volumeSrc = null;
const fmt = (x, p = 2) => (x == null || Number.isNaN(x) ? "–" : Number(x).toLocaleString(undefined, { minimumFractionDigits: p, maximumFractionDigits: p }));
const fmtVol = (v) => v >= 1e7 ? (v / 1e7).toFixed(2) + "Cr" : v >= 1e5 ? (v / 1e5).toFixed(2) + "L" : v >= 1e3 ? (v / 1e3).toFixed(1) + "K" : fmt(v, 0);
function legendTitle() {
  const tf = TFS.find((x) => x[1] === S.tf)?.[0] || "";
  let t = esc(S.symbol);
  if (CS.titleMode !== "ticker") t += ` · ${tf}`;
  if (CS.titleMode === "ticker_tf_src") t += ` · ${SRC_NAME[srcFor(S.symbol)]}`;
  const logo = CS.logo ? `<span class="lg-logo">${esc(S.symbol.replace(/^\^/, "")[0] || "?")}</span>` : "";
  const open = nseOpen();
  const mkt = CS.marketStatus ? `<span class="lg-mkt ${open ? "on" : ""}" title="${open ? "Market open" : "Market closed"}"></span>` : "";
  const rp = RP.mode === "on" ? `<span class="lg-rp" title="Replay mode">${RP_ICON}</span>` : "";
  return logo + (CS.title ? `<b>${t}</b>` : "") + rp + mkt;
}
function nseOpen(now = Date.now() / 1000) {
  const ist = new Date((now + 19800) * 1000), m = ist.getUTCHours() * 60 + ist.getUTCMinutes(), d = ist.getUTCDay();
  return d > 0 && d < 6 && m >= 555 && m < 930;
}
function prevDayClose(i = bars.length - 1) {
  if (!bars[i]) return null;
  if (S.tf >= 86400) return i > 0 ? bars[i - 1][4] : null;
  const day = Math.floor((bars[i][0] + 19800) / 86400);
  for (let k = i; k >= 0; k--) if (Math.floor((bars[k][0] + 19800) / 86400) < day) return bars[k][4];
  return null;
}
function showMainLegend(i) {
  const head = legendTitle();
  if (i == null || !bars[i]) { $("#legendMain").innerHTML = head; return; }
  const [, o, h, l, c, v] = bars[i];
  const pc = i > 0 ? bars[i - 1][4] : o;
  const ch = c - pc, col = ch >= 0 ? css("--up") : css("--down");
  let out = head;
  if (CS.chartValues) out += `<span class="v">O <span style="color:${col}">${fmt(o)}</span></span><span class="v">H <span style="color:${col}">${fmt(h)}</span></span>` +
    `<span class="v">L <span style="color:${col}">${fmt(l)}</span></span><span class="v">C <span style="color:${col}">${fmt(c)}</span></span>`;
  if (CS.barChange) out += `<span class="v" style="color:${col}">${ch >= 0 ? "+" : ""}${fmt(ch)} (${fmt((ch / pc) * 100)}%)</span>`;
  if (CS.volume && v) out += `<span class="v">Vol <span style="color:${col}">${fmtVol(v)}</span></span>`;
  if (CS.lastDayChange) {
    const pd = prevDayClose(), last = bars[bars.length - 1][4];
    if (pd) { const d = last - pd, dc = d >= 0 ? css("--up") : css("--down"); out += `<span class="v">Day <span style="color:${dc}">${d >= 0 ? "+" : ""}${fmt(d)} (${fmt(d / pd * 100)}%)</span></span>`; }
  }
  $("#legendMain").innerHTML = out;
}
chart.subscribeCrosshairMove((p) => {
  if (!p.time || !p.point) { hovering = false; showMainLegend(bars.length - 1); updateIndLegendValues(null); return; }
  hovering = true;
  const t = p.time - TZ;
  let lo = 0, hi = bars.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (bars[m][0] <= t) lo = m; else hi = m - 1; }
  showMainLegend(lo);
  updateIndLegendValues(p.seriesData);
});
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// status-line flags: the user's Style-tab choice, else the script's indicator(show_inputs=, show_values=) default (off)
const legendOpt = (ind, k) => ind.style[k] ?? ind.meta?.[k] ?? false;
function renderIndLegend() {
  const box = $("#legendInds");
  box.innerHTML = "";
  box.classList.toggle("collapsed", !!S.legendCollapsed);
  for (const ind of inds.values()) {
    const row = document.createElement("div");
    row.className = "lg-ind" + (ind.visible ? "" : " off");
    if (CS.legendBg) row.style.background = hexA(css("--bg"), CS.legendBgA);
    const args = !legendOpt(ind, "showInputs") || !CS.indInputs ? "" : (ind.meta?.inputs || []).filter((x) => typeof x.default !== "boolean" && (typeof x.default !== "string" || x.options)).map((x) => ind.inputs[x.name] ?? x.default).join(", ");
    row.innerHTML = SPIN + `<span class="t${CS.indTitles ? "" : " hidden"}">${esc(ind.meta?.title || ind.ref || "Script")}${args ? " " + esc(args) : ""}</span>` +
      `<span class="vals"></span>${ind.error ? `<span class="err">⚠ ${esc(ind.error)}</span>` : ""}` +
      `<button data-a="vis" title="Show/hide">${ind.visible ? "👁" : "◌"}</button>` +
      `<button data-a="set" title="Settings">⚙</button><button data-a="code" title="Source code">{ }</button>` +
      `<button data-a="del" title="Remove">✕</button>`;
    row.querySelector('[data-a="vis"]').onclick = () => { ind.visible = !ind.visible; applyVisibility(ind); renderIndLegend(); save(); };
    row.querySelector('[data-a="set"]').onclick = () => openSettings(ind);
    row.querySelector('[data-a="code"]').onclick = () => openEditor({ code: ind.code, ref: ind.ref, bindId: ind.id });
    row.querySelector('[data-a="del"]').onclick = () => removeIndicator(ind.id);
    ind.legendVals = row.querySelector(".vals");
    ind.legendRow = row; row.classList.toggle("pending", !!ind.pending);
    box.appendChild(row);
  }
  if (inds.size) {                                      // TradingView-style chevron: hide / show the indicator rows
    const tg = document.createElement("button");
    tg.className = "lg-toggle";
    tg.title = S.legendCollapsed ? "Show indicator legend" : "Hide indicator legend";
    tg.innerHTML = S.legendCollapsed ? `<span class="chev">▾</span>${inds.size}` : `<span class="chev">▴</span>`;
    tg.onclick = () => { S.legendCollapsed = !S.legendCollapsed; renderIndLegend(); save(); };
    box.appendChild(tg);
  }
  updateIndLegendValues(null);
}
function updateIndLegendValues(seriesData) {
  for (const ind of inds.values()) {
    if (!ind.legendVals) continue;
    if (!legendOpt(ind, "showValues") || !CS.indValues) { ind.legendVals.innerHTML = ""; continue; }
    ind.legendVals.innerHTML = ind.series.map((s, j) => {
      if (ind.effPlots?.[j] && !ind.effPlots[j].visible) return "";
      const d = seriesData?.get(s);
      const v = seriesData ? (d && d.color !== GAP ? d.value : null) : lastValue(ind, j);
      const txt = ind.lastMsg?.scale && v != null ? fmtVol(v) : fmt(v, precisionOf(ind));
      return `<span style="color:${ind.plotColors[j]}">${txt}</span>`;
    }).join(" ");
  }
}
function lastValue(ind, j) {
  const vals = ind.lastVals?.[j];
  return vals == null ? null : vals;
}

// ------------------------------------------------------------------ indicators
let seq = Date.now();
const newId = () => "i" + (seq++).toString(36);

function addIndicator({ ref = null, code, inputs = {}, visible = true, id = newId() }) {
  const ind = { id, ref, code, inputs, visible, style: {}, series: [], plotColors: [], lines: [], markers: [], meta: null, error: null, sig: "" };
  inds.set(id, ind);
  S.indicators.push(ind);
  save();
  ind.pending = true;
  send({ op: "set_indicator", id, code, inputs });
  renderIndLegend();
  return ind;
}
function updateIndicator(ind) {
  ind.error = null;
  save();
  setIndPending(ind, true);
  send({ op: "set_indicator", id: ind.id, code: ind.code, inputs: ind.inputs });
}
function removeIndicator(id) {
  const ind = inds.get(id);
  if (!ind) return;
  clearSeries(ind);
  inds.delete(id);
  S.indicators = S.indicators.filter((x) => x.id !== id);
  if (editingId === id) bindEditor(null);
  save();
  send({ op: "remove_indicator", id });
  refreshMarkers();
  refreshBarColors();
  renderIndLegend();
}
function clearSeries(ind) {
  const panes = new Set();
  for (const s of ind.series) { const pi = s.getPane().paneIndex(); if (pi > 0) panes.add(pi); for (const x of plotExtras(s)) chart.removeSeries(x); chart.removeSeries(s); }
  ind.series = []; ind.lines = [];
  [...panes].sort((a, b) => b - a).forEach((pi) => { const p = chart.panes()[pi]; if (p && p.getSeries().length === 0) chart.removePane(pi); });
  layoutPanes();
}
// Price pane gets ~60% of the height (less as oscillator panes are added), oscillators share the rest.
function layoutPanes() {
  const ps = chart.panes();
  if (ps.length < 2) return;
  ps[0].setStretchFactor(Math.max(2, 6 - ps.length) * (ps.length - 1) / 2);
  for (let i = 1; i < ps.length; i++) ps[i].setStretchFactor(1);
}

const LINE_STYLES = { solid: LW.LineStyle.Solid, dotted: LW.LineStyle.Dotted, dashed: LW.LineStyle.Dashed, "large dashed": LW.LineStyle.LargeDashed };
function seriesFor(p, paneIndex, precision, scaleId) {
  const base = { color: p.color, priceLineVisible: false, lastValueVisible: CS.indValue, crosshairMarkerVisible: false,
    priceScaleId: scaleId || scaleSide(),
    title: p.showTitle || CS.indName ? p.title : "",
    autoscaleInfoProvider: scaleId || paneIndex > 0 ? undefined : (orig) => (CS.scaleMainOnly ? null : orig()),
    priceFormat: { type: "price", precision: precision ?? 2, minMove: Math.pow(10, -(precision ?? 2)) } };
  if (!base.autoscaleInfoProvider) delete base.autoscaleInfoProvider;
  const tag = (x) => { x._ltv = { title: p.title, showTitle: !!p.showTitle, own: !!scaleId }; return x; };
  if (p.style === "histogram") return tag(chart.addSeries(LW.HistogramSeries, base, paneIndex));
  if (p.style === "area") return tag(chart.addSeries(LW.AreaSeries, { ...base, lineColor: p.color, topColor: hexA(p.color, 0.35), bottomColor: hexA(p.color, 0), lineWidth: p.lineWidth, lineStyle: LINE_STYLES[p.lineStyle] ?? 0 }, paneIndex));
  const opts = { ...base, lineWidth: p.lineWidth, lineStyle: LINE_STYLES[p.lineStyle] ?? 0,
    lineType: p.style === "step" ? LW.LineType.WithSteps : LW.LineType.Simple };
  if (p.style === "circles") Object.assign(opts, { lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: p.lineWidth + 1 });
  return tag(chart.addSeries(LW.LineSeries, opts, paneIndex));
}
// colour helpers: any CSS colour -> #rrggbb, and #rrggbb + alpha -> rgba()
const _cx = document.createElement("canvas").getContext("2d");
function toHex(c) { _cx.fillStyle = "#000"; _cx.fillStyle = c || "#000"; const v = _cx.fillStyle; return v.startsWith("#") ? v : "#" + (v.match(/\d+/g) || [0, 0, 0]).slice(0, 3).map((x) => (+x).toString(16).padStart(2, "0")).join(""); }
function hexA(c, a) { const h = toHex(c); return `rgba(${parseInt(h.slice(1, 3), 16)},${parseInt(h.slice(3, 5), 16)},${parseInt(h.slice(5, 7), 16)},${a})`; }
const precisionOf = (ind) => ind.style.precision ?? ind.meta?.precision ?? 2;
// script defaults merged with the user's Style-tab overrides
function effPlot(ind, p) {
  const o = ind.style.plots?.[p.title] || {};
  const e = { ...p, visible: o.visible !== false, lineStyle: o.lineStyle || "solid", showTitle: !!ind.style.showTitles };
  if (o.color) { e.color = o.color; e.colors = null; }
  if (o.lineWidth) e.lineWidth = o.lineWidth;
  if (o.style) e.style = o.style;
  return e;
}
function effHline(ind, h) {
  const o = ind.style.hlines?.[h.title || String(h.price)] || {};
  return { ...h, visible: o.visible !== false, color: o.color || h.color, style: o.lineStyle || h.style, price: o.price ?? h.price };
}
// Lines connect across whitespace in lightweight-charts, so a NaN gap in a line/step plot is drawn
// as an invisible segment holding the last value (like Pine's plot.style_linebr).
const GAP = "rgba(0,0,0,0)";
function plotPoints(res, p, held = null) {
  const brk = p.style !== "histogram" && p.style !== "area" && p.style !== "circles";
  return res.time.map((t, k) => {
    const v = p.values[k];
    if (v == null) return brk && held != null ? { time: loc(t), value: held, color: GAP } : { time: loc(t) };
    held = v;
    const pt = { time: loc(t), value: v };
    if (p.colors && p.colors[k]) pt.color = p.colors[k];
    return pt;
  });
}
function setPlotData(s, p, pts) {
  if (p.style !== "circles" || !p.colors) { s._ltvSplit = null; return s.setData(pts); }
  const groups = new Map();
  for (const pt of pts) if (pt.value != null) groups.set(pt.color || p.color, true);
  s._ltvSplit = s._ltvSplit || new Map();
  for (const [col, x] of s._ltvSplit) if (!groups.has(col)) { x.setData([]); }
  let first = true;
  for (const col of groups.keys()) {
    let x = s._ltvSplit.get(col);
    if (!x) {
      if (first && ![...s._ltvSplit.values()].includes(s)) x = s;
      else { x = chart.addSeries(LW.LineSeries, { ...s.options(), color: col, lastValueVisible: false, title: "" }, s.getPane().paneIndex()); x._ltvExtra = true; }
      if (x === s) s.applyOptions({ color: col });
      s._ltvSplit.set(col, x);
    }
    first = false;
    x.setData(pts.map((pt) => pt.value != null && (pt.color || p.color) === col ? { time: pt.time, value: pt.value } : { time: pt.time }));
  }
}
function updatePlotPt(s, p, pt) {
  if (!s._ltvSplit) return s.update(pt, true);
  const col = pt.color || p.color;
  if (pt.value != null && !s._ltvSplit.has(col)) {
    const x = chart.addSeries(LW.LineSeries, { ...s.options(), color: col, lastValueVisible: false, title: "" }, s.getPane().paneIndex());
    x._ltvExtra = true; s._ltvSplit.set(col, x);
  }
  for (const [c, x] of s._ltvSplit) x.update(pt.value != null && c === col ? { time: pt.time, value: pt.value } : { time: pt.time }, true);
}
const plotExtras = (s) => s._ltvSplit ? [...s._ltvSplit.values()].filter((x) => x !== s) : [];
const lastHeld = (p) => { for (let k = p.values.length - 1; k >= 0; k--) if (p.values[k] != null) return p.values[k]; return null; };

function onIndicatorFull(msg) {
  const ind = inds.get(msg.id);
  if (!ind) return;
  ind.error = null;
  ind.meta = { title: msg.title, overlay: msg.overlay, precision: msg.precision, inputs: msg.inputs,
    showInputs: msg.showInputs === true, showValues: msg.showValues === true, help: msg.help || null,
    plots: msg.plots.map(({ title, color, style, lineWidth }) => ({ title, color, style, lineWidth })), hlines: msg.hlines, hasMarkers: msg.markers.length > 0 };
  ind.lastMsg = msg;
  const plots = msg.plots.map((p) => effPlot(ind, p));
  const hls = msg.hlines.map((h) => effHline(ind, h));
  ind.effPlots = plots;
  const prec = precisionOf(ind);
  const sig = JSON.stringify([msg.overlay, msg.scale, plots.map((p) => [p.style, p.color, p.lineWidth, p.lineStyle, p.showTitle]), hls, prec]);
  if (sig !== ind.sig || ind.series.length !== msg.plots.length) {
    const oldPane = ind.series[0]?.getPane().paneIndex();
    const pane = msg.overlay ? 0 : (oldPane > 0 ? oldPane : chart.panes().length);
    const old = ind.series;
    const scaleId = msg.scale ? "scale_" + ind.id : undefined;
    ind.series = plots.map((p) => seriesFor(p, pane, prec, scaleId));
    if (scaleId && ind.series[0]) ind.series[0].priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 }, visible: false });
    ind.plotColors = plots.map((p) => p.color);
    ind.series_old = old;
    for (const s of old) { for (const x of plotExtras(s)) chart.removeSeries(x); chart.removeSeries(s); }
    if (!msg.overlay && ind.series.length && oldPane == null) {
      const pn = ind.series[0].getPane();
      layoutPanes();
    }
    if (!ind.series.length && !msg.overlay && msg.hlines.length) {
      ind.series = [seriesFor({ style: "line", color: "rgba(0,0,0,0)", lineWidth: 1 }, pane, prec)];
      ind.plotColors = ["transparent"];
    }
    ind.lines = [];
    if (ind.series[0]) for (const h of hls) {
      if (!h.visible) continue;
      ind.lines.push(ind.series[0].createPriceLine({ price: h.price, color: h.color, lineWidth: 1,
        lineStyle: LINE_STYLES[h.style] ?? LW.LineStyle.Dashed, axisLabelVisible: ind.style.priceLabels !== false, title: h.title }));
    }
    ind.sig = sig;
  }
  plots.forEach((p, j) => ind.series[j] && setPlotData(ind.series[j], p, plotPoints(msg, p)));
  ind.held = msg.plots.map(lastHeld);
  syncLastLabels(ind, msg.plots);
  ind.lastVals = msg.plots.map((p) => p.values[p.values.length - 1]);
  ind.markers = msg.markers.map((m) => ({ ...m, time: loc(m.time) }));
  ind.barcolors = new Map();
  if (msg.barcolors) msg.time.forEach((t, k) => { if (msg.barcolors[k]) ind.barcolors.set(t, msg.barcolors[k]); });
  ind.objs = { boxes: msg.boxes || [], labels: msg.labels || [], bubbles: msg.bubbles || [], lines: msg.lines || [], tables: msg.tables || [], profiles: msg.profiles || [], vpspecs: msg.vpspecs || [] };
  ind.alertSeen = new Set((msg.alerts || []).map((x) => x.t + "|" + x.msg));
  applyVisibility(ind);
  refreshMarkers();
  renderIndLegend();
  if (editingId === ind.id) consoleMsg(`✓ ${msg.title}: ${msg.plots.length} plot(s), ${msg.markers.length} marker(s)`, "ok");
}
function onIndicatorTail(msg) {
  const ind = inds.get(msg.id);
  if (!ind || ind.series.length !== msg.plots.length || !msg.time.length) return;
  msg.plots.forEach((p, j) => {
    for (const pt of plotPoints(msg, effPlot(ind, p), ind.held?.[j])) { try { updatePlotPt(ind.series[j], effPlot(ind, p), pt); } catch { /* older than data */ } }
    const h = lastHeld(p);
    if (h != null && ind.held) ind.held[j] = h;
  });
  ind.lastVals = msg.plots.map((p) => p.values[p.values.length - 1]);
  syncLastLabels(ind, msg.plots);
  const t0 = loc(msg.time[0]);
  ind.markers = ind.markers.filter((m) => m.time < t0).concat(msg.markers.map((m) => ({ ...m, time: loc(m.time) })));
  if (msg.barcolors && ind.barcolors) {
    msg.time.forEach((t, k) => { if (msg.barcolors[k]) ind.barcolors.set(t, msg.barcolors[k]); else ind.barcolors.delete(t); });
    if (ind.visible && !hideInds) tailBarColors(msg.time);
  }
  if (msg.boxes) ind.objs = { boxes: msg.boxes, labels: msg.labels || [], bubbles: msg.bubbles || [], lines: msg.lines || [], tables: msg.tables || [], profiles: msg.profiles || [], vpspecs: msg.vpspecs || [] };
  if (msg.alerts?.length && ind.visible) fireAlerts(ind, msg.alerts, msg.time[msg.time.length - 1]);
  zones?.dirty();
  refreshMarkers();
  if (!hovering) updateIndLegendValues(null);
}
function onIndicatorError(msg) {
  const ind = inds.get(msg.id);
  if (!ind) return;
  ind.error = msg.error;
  renderIndLegend();
  if (editingId === ind.id) consoleMsg("✗ " + msg.error, "err");
}
// hide the price-axis label of a plot whose latest value is a gap (e.g. inactive Supertrend side)
function syncLastLabels(ind, plots) {
  plots.forEach((p, j) => {
    const on = CS.indValue && ind.style.priceLabels !== false && p.values[p.values.length - 1] != null;
    if (ind.series[j] && ind.series[j].options().lastValueVisible !== on) ind.series[j].applyOptions({ lastValueVisible: on });
  });
}
function applyVisibility(ind) {
  ind.series.forEach((s, j) => { const o = { visible: !hideInds && ind.visible && (ind.effPlots?.[j]?.visible ?? true) }; s.applyOptions(o); for (const x of plotExtras(s)) x.applyOptions(o); });
  refreshMarkers();
  refreshBarColors();
}
const indOn = (ind) => ind.visible && !hideInds;
// candle colours from every visible indicator that calls barcolor() (later indicators win)
function refreshBarColors() {
  const m = new Map();
  for (const ind of inds.values()) if (indOn(ind) && ind.barcolors) for (const [t, c] of ind.barcolors) m.set(t, c);
  const changed = m.size || barColors.size;
  barColors = m;
  if (changed && mainSeries && bars.length) setMainData();
  zones?.dirty();
}
function tailBarColors(times) {
  for (const t of times) {
    let c = null;
    for (const ind of inds.values()) if (indOn(ind) && ind.barcolors?.has(t)) c = ind.barcolors.get(t);
    if (c) barColors.set(t, c); else barColors.delete(t);
    let i = bars.length - 1;
    while (i >= 0 && bars[i][0] > t) i--;
    if (i >= 0 && bars[i][0] === t) try { mainSeries.update(point(i)); } catch { /* older than data */ }
  }
}
// script alert(): notify once per alert, only after its bar has closed (like Pine's once-per-bar-close)
function fireAlerts(ind, list, lastT) {
  ind.alertSeen = ind.alertSeen || new Set();
  for (const a of list) {
    const key = a.t + "|" + a.msg;
    if (a.t >= lastT || ind.alertSeen.has(key)) continue;
    ind.alertSeen.add(key);
    toast(a.msg);
    try { if (window.Notification?.permission === "granted") new Notification("TickLens", { body: a.msg }); } catch { /* */ }
  }
}
function toast(text) {
  let host = document.getElementById("toasts");
  if (!host) { host = document.createElement("div"); host.id = "toasts"; document.body.appendChild(host); }
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  el.onclick = () => el.remove();
  host.appendChild(el);
  setTimeout(() => el.remove(), 30000);
  try { if (window.Notification?.permission === "default") Notification.requestPermission(); } catch { /* */ }
}
// boxes / labels / lines / tables of visible indicators, drawn by zones.js
function indObjects() {
  const out = [];
  for (const ind of inds.values()) if (indOn(ind) && ind.objs && ind.style.objects !== false) out.push(ind.objs);
  return out;
}
function refreshMarkers() {
  if (!markersApi) return;
  const all = [];
  for (const ind of inds.values()) if (ind.visible && !hideInds && ind.style.markers !== false) all.push(...ind.markers);
  all.sort((a, b) => a.time - b.time);
  markersApi.setMarkers(all);
}

// ------------------------------------------------------------------ socket
let ws, wsRetry = 0;
const queue = [];
function send(m) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(m)); else queue.push(m); }
function status(msg, cls = "") {
  const el = $("#status");
  const busy = !cls && /loading|connect|…/i.test(msg);
  el.innerHTML = (busy ? SPIN : "") + `<span class="st-t">${esc(msg)}</span>`;
  el.title = msg;
  el.className = "status " + cls + (busy ? " busy" : "");
}
function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => {
    wsRetry = 0;
    queue.length = 0;
    loadSymbol(false);
    sendWatch();
    for (const ind of inds.values()) send({ op: "set_indicator", id: ind.id, code: ind.code, inputs: ind.inputs });
  };
  ws.onclose = () => { status("disconnected – retrying", "err"); setTimeout(connect, Math.min(1000 * 2 ** wsRetry++, 15000)); };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    switch (m.type) {
      case "history":
        if (m.symbol !== S.symbol || m.tf !== S.tf) return;
        vpCache.clear(); vpPending.clear();
        if (m.prepend) {                                     // older candles from scrolling back: keep the view where it is
          const r = chart.timeScale().getVisibleLogicalRange();
          bars = m.bars; cacheInfo = m.cache || cacheInfo; setMainData();
          if (r) chart.timeScale().setVisibleLogicalRange({ from: r.from + m.prepend, to: r.to + m.prepend });
          more.busy = false; more.end = !!m.end; markPriceLinesDirty();
          status(`${SRC_NAME[m.source] || m.source} · +${m.prepend} older bars`, "live");
          rangeStep();
          break;
        }
        more.busy = false; more.end = false;
        bars = m.bars; volumeSrc = m.volume_src; cacheInfo = m.cache || null; cacheSrc = m.source; setMainData();
        window.top.LTVSide?.cacheChanged();
        chartLoading(false);
        if (m.replay) {
          const v = RP.view; RP.view = null;
          chart.timeScale().setVisibleLogicalRange(v && v.to - v.from > 5 ? v : { from: Math.max(0, bars.length - 120), to: bars.length + 40 });
          rpOnHistory(m.replay);
          status(`Replay · ${fmtRpTime(m.replay.t)}`, "live");
          showMainLegend(bars.length - 1); markPriceLinesDirty();
          break;
        }
        if (RP.mode === "on") rpExit(false);
        chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, bars.length - 160), to: bars.length + 5 });
        fitPrices();
        showMainLegend(bars.length - 1);
        markPriceLinesDirty();
        status(`${SRC_NAME[m.source] || m.source} · live${m.volume_src ? " · volume: " + m.volume_src : ""}`, "live");
        rangeStep();
        break;
      case "bar": onBar(m.bar); break;
      case "more": more.busy = false; more.end = !!m.end; if (m.end && !rangeJob) status("No older data", "live"); rangeStep(m.n === 0); break;
      case "replay": rpOnStep(m); if (!m.end) status(`Replay · ${fmtRpTime(m.t)}`, "live"); break;
      case "quotes": onQuotes(m.items); break;
      case "volume": onVolume(m); break;
      case "ind": { const i = inds.get(m.id); if (i) setIndPending(i, false); onIndicatorFull(m); break; }
      case "ind_tail": onIndicatorTail(m); break;
      case "vprofile": onVProfile(m); break;
      case "ind_error": { const i = inds.get(m.id); if (i) setIndPending(i, false); onIndicatorError(m); break; }
      case "status": status(m.msg); if (/^volume: /.test(m.msg)) volLoading(/…$/.test(m.msg) ? m.msg.replace(/^volume: /, "Volume · ") : null); break;
      case "error": if (/Sign in to TradingView/.test(m.msg)) (window.top.LTVTvLogin || openTvLogin)(m.msg);
        if (/Breeze/.test(m.msg) && !EMBED) bzStatus();
        window.top.LTVSide?.notify(m.msg, "err");
        if (RP.busy) { RP.busy = false; rpPause(); } status(m.msg, "err"); consoleMsg("✗ " + m.msg, "err"); chartLoading(false); volLoading(null); rangeDone(); break;
    }
  };
}
// scroll-back: near the left edge ask the server for older candles (1m store, else the source)
const more = { busy: false, end: false };

// ------------------------------------------------------------------ date ranges (bottom bar): 1D 5D 1M 3M 6M YTD 1Y 5Y All, go to date
// each range picks TradingView's interval, then pages older candles in (cache first, else download) until the range is covered
const RANGES = { "1D": [1, 60, "1 day"], "5D": [5, 300, "5 days"], "1M": [30, 1800, "1 month"], "3M": [91, 3600, "3 months"], "6M": [182, 86400, "6 months"],
  YTD: ["ytd", 86400, "year to date"], "1Y": [365, 86400, "1 year"], "5Y": [1826, 604800, "5 years"], All: [null, 604800, "all data"] };
let rangeJob = null;
let rangeLoaderEl = null;
const rangeLoader = () => (rangeLoaderEl ||= ov("rangeLoader", "rloader", '<div class="ld-bars"><i></i><i></i><i></i><i></i><i></i></div><span class="ld-text"></span>'));
function rangeStart(job) {
  if (job.t != null) return job.t;
  const [days] = RANGES[job.key], last = bars[bars.length - 1][0];
  if (days === "ytd") return Date.UTC(new Date((last + TZ) * 1000).getUTCFullYear(), 0, 1) / 1000 - TZ;
  if (days == null) return -Infinity;
  if (days <= 5) {                        // trading days: the last N sessions present in the data
    const day = (t) => Math.floor((t + TZ) / 86400);
    let n = 0, prev = null;
    for (let i = bars.length - 1; i >= 0; i--) { const d = day(bars[i][0]); if (d !== prev) { if (++n > days) return bars[i + 1][0]; prev = d; } }
    return day(last) * 86400 - TZ - (days + 3) * 86400;   // not enough sessions loaded yet: ask for more
  }
  return last - days * 86400;
}
function setRange(key, t = null) {
  if (!RANGES[key] && key !== "goto") return;
  rangeJob = { key, t, tries: 0 };
  S.range = key === "goto" ? null : key;
  const tf = key === "goto" ? S.tf : RANGES[key][1];
  rangeLoading(true);
  if (S.tf !== tf) { S.tf = tf; loadSymbol(); renderTop(); } else if (bars.length) rangeStep(); else loadSymbol();
  paintRangeBar();
}
function rangeStep(empty = false) {
  if (!rangeJob || !bars.length || more.busy) return;
  const start = rangeStart(rangeJob);
  rangeJob.empties = empty ? (rangeJob.empties || 0) + 1 : 0;   // a few empty pages in a row = nothing older
  if (bars[0][0] > start && !more.end && rangeJob.tries < 60 && rangeJob.empties < 3) {
    rangeJob.tries++;
    more.busy = true; send({ op: "more" });
    const span = RANGES[rangeJob.key]?.[2] || "history";
    rangeLoading(true, `Downloading ${span} · ${S.symbol} · ${new Date((bars[0][0] + TZ) * 1000).toISOString().slice(0, 10)}`);
    return;
  }
  // covered (or nothing older exists): show exactly the range
  const ts = chart.timeScale();
  let i = bars.findIndex((b) => b[0] >= start); if (i < 0) i = 0;
  if (rangeJob.key === "goto") ts.setVisibleLogicalRange({ from: i - 60, to: i + 60 });
  else ts.setVisibleLogicalRange({ from: i - 0.5, to: bars.length - 0.5 + Math.min(5, (bars.length - i) * 0.03) });
  if (bars[0][0] > start && rangeJob.key !== "All") status(`Only data from ${new Date((bars[0][0] + TZ) * 1000).toISOString().slice(0, 10)} is available`, "live");
  rangeDone();
}
function rangeDone() { rangeJob = null; rangeLoading(false); paintRangeBar(); }
function rangeLoading(on, text = "") {
  rangeLoader().classList.toggle("show", !!on);
  rangeLoader().querySelector(".ld-text").textContent = text || (on ? "Loading…" : "");
  paintRangeBar();
}
const paintRangeBar = () => { try { (EMBED ? window.top : window).LTVRangeBar?.paint(); } catch { /* */ } };
function gotoDateDialog() {
  const d = document.createElement("dialog"), last = bars[bars.length - 1];
  const iso = (t) => new Date((t + TZ) * 1000).toISOString().slice(0, 16);
  d.innerHTML = `<form method="dialog" class="dlg"><div class="dlg-head"><b>Go to</b><button value="cancel">✕</button></div>
    <div class="tvl-body"><label class="srow">Date <input type="date" name="d" required></label>
    <label class="srow">Time <input type="time" name="tm" value="09:15" ${S.tf >= 86400 ? "disabled" : ""}></label>
    <div class="dlg-foot"><span class="spacer"></span><button value="cancel">Cancel</button><button value="ok" class="primary">Go to</button></div></div></form>`;
  document.body.appendChild(d);
  const f = d.querySelector("form");
  f.d.value = last ? iso(last[0]).slice(0, 10) : ""; f.d.max = f.d.value;
  d.onclose = () => {
    if (d.returnValue === "ok" && f.d.value) setRange("goto", Date.parse(`${f.d.value}T${S.tf >= 86400 ? "00:00" : f.tm.value || "00:00"}:00Z`) / 1000 - TZ);
    d.remove();
  };
  d.showModal();
}
chart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
  if (!r || r.from > 15 || more.busy || more.end || !bars.length || RP.mode) return;
  more.busy = true; status("Loading older bars…");
  send({ op: "more" });
  setTimeout(() => { more.busy = false; }, 30000);
});
function loadSymbol(persist = true) {
  if (persist) save();
  draw.setSymbol(S.symbol);
  bars = []; setMainData(); cacheInfo = null;
  more.busy = false; more.end = false;
  fitPrices();
  chartLoading(true, `Loading ${S.symbol} · ${TFS.find((x) => x[1] === S.tf)?.[0] || ""}`);
  volLoading(null);
  for (const ind of inds.values()) { ind.series.forEach((s) => { s.setData([]); for (const x of plotExtras(s)) x.setData([]); }); ind.markers = []; ind.barcolors = null; ind.objs = null; setIndPending(ind, true); }
  barColors = new Map();
  refreshMarkers();
  applyWatermark(); applyMainOpts();
  renderTop();
  const replay = RP.mode === "on" && RP.t ? { t: RP.t, step: Math.min(RP.step || S.tf, S.tf) } : null;
  if (replay) { rpPause(); RP.busy = true; RP.step = replay.step; }
  send({ op: "load", source: srcFor(S.symbol), symbol: S.symbol, tf: S.tf, extended: CS.session === "extended", replay });
}

// ------------------------------------------------------------------ top bar
// The top bar, watchlist and drawing toolbar act on the active chart of the layout: A() is its API.
const A = () => (!EMBED && window.LTVLayout?.api()) || LOCAL;
const each = (sync, fn) => (!EMBED && window.LTVLayout ? window.LTVLayout.each(sync, fn) : fn(LOCAL));
function renderTop() {
  if (EMBED) { window.parent?.LTVLayout?.changed(SLOT); return; }
  const a = A().S;
  $("#symText").textContent = a.symbol;
  paintChartType(a.chartType);
  setTimeout(paintTitle, 0);
  rpBtn?.classList.toggle("on", !!A().RP.mode);
  renderTfs(); renderWatchlist();
}
// browser tab title: "SYMBOL 23,894.40 ▲0.31%" from the active chart's last bar, throttled to 1/s
let titleTxt = "";
function paintTitle() {
  if (EMBED) return;
  const c = A(), sym = c.S.symbol, b = c.bars || [];
  let txt = `${sym} · TickLens`;
  if (b.length) {
    const last = b[b.length - 1][4];
    const ref = quotes.get(wkey(sym));
    let pct = ref && ref.pct != null && !ref.error ? ref.pct : null;
    if (pct == null) {                     // fallback: previous session's close from the loaded bars
      const day = (t) => Math.floor((t + 19800) / 86400), d0 = day(b[b.length - 1][0]);
      let pc = null;
      if (c.S.tf >= 86400) pc = b.length > 1 ? b[b.length - 2][4] : null;
      else for (let i = b.length - 2; i >= 0; i--) if (day(b[i][0]) !== d0) { pc = b[i][4]; break; }
      if (pc) pct = (last - pc) / pc * 100;
    }
    txt = `${sym} ${fmtQ(last)}` + (pct == null ? "" : ` ${pct >= 0 ? "▲" : "▼"}${fmtQ(Math.abs(pct))}%`);
  }
  if (txt !== titleTxt) { titleTxt = txt; document.title = txt; }
}
if (!EMBED) setInterval(paintTitle, 1000);
function renderTfs() {
  const box = $("#tfs"), tf = A().S.tf;
  box.innerHTML = "";
  for (const [label, sec] of TFS) {
    const b = document.createElement("button");
    b.textContent = label;
    b.className = sec === tf ? "active" : "";
    b.onclick = () => each("interval", (c) => c.setTf(sec));
    box.appendChild(b);
  }
}
// chart type: icon button with a menu (the hidden select keeps the value)
const CT_ICONS = {
  candles: '<path d="M7 3v4M7 17v4M17 3v6M17 15v6"/><rect x="5" y="7" width="4" height="10" rx="1" fill="currentColor"/><rect x="15" y="9" width="4" height="6" rx="1"/>',
  hollow: '<path d="M7 3v4M7 17v4M17 3v6M17 15v6"/><rect x="5" y="7" width="4" height="10" rx="1"/><rect x="15" y="9" width="4" height="6" rx="1"/>',
  bars: '<path d="M7 4v16M4 8h3M7 15h3M17 4v14M14 7h3M17 13h3"/>',
  line: '<path d="M3 17l5-6 4 3 4-7 5 5"/>',
  area: '<path d="M3 17l5-6 4 3 4-7 5 5v8H3z" fill="currentColor" fill-opacity=".25"/><path d="M3 17l5-6 4 3 4-7 5 5"/>',
  ha: '<path d="M7 3v4M7 17v4M17 3v6M17 15v6"/><rect x="5" y="7" width="4" height="10" rx="1"/><rect x="15" y="9" width="4" height="6" rx="1" fill="currentColor"/>',
};
const ctIcon = (t, size = 20) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${CT_ICONS[t] || CT_ICONS.candles}</svg>`;
function paintChartType(t) { $("#chartType").value = t; $("#chartTypeBtn").innerHTML = ctIcon(t); $("#chartTypeBtn").title = "Chart type: " + ($("#chartType").selectedOptions[0]?.text || t); }
paintChartType(S.chartType);
$("#chartTypeBtn").onclick = () => {
  const r = $("#chartTypeBtn").getBoundingClientRect(), cur = A().S.chartType;
  LTVSettings.openMenu([...$("#chartType").options].map((o) => ({ label: o.text, icon: ctIcon(o.value, 18), checked: o.value === cur,
    action: () => A().setChartType(o.value) })), r.left, r.bottom + 4);
};
$("#themeBtn").onclick = () => { const th = S.theme === "dark" ? "light" : "dark"; each("all", (c) => c.setTheme(th)); };

// symbol search
let searchTimer;
let symMode = "chart";            // "chart" = change chart symbol, "add" = add to watchlist
let symTab = "all";               // "all" | "breeze" | "yf" | "tv"
let symKind = "";                 // "" (All) | index | stock | fut | opt
const KINDS = [["", "All"], ["index", "Index"], ["stock", "Stock"], ["fut", "Futures"], ["opt", "Options"]];
function kindOf(r) {
  const sym = String(r.symbol || "").toUpperCase(), t = String(r.type || "").toUpperCase();
  const m = sym.replace(/^[A-Z_]+:/, "").match(FNO_RE);
  if (m) return m[3] ? "opt" : "fut";
  if (/OPT/.test(t)) return "opt";
  if (/FUT/.test(t) || /\d!$/.test(sym)) return "fut";
  if (/INDEX/.test(t)) return "index";
  if (/^(EQ|STOCK|EQUITY|ETF|FUND|DR)\b|\b(EQ|STOCK|EQUITY|ETF|FUND|DR)$/.test(t)) return "stock";
  return "";
}
function renderSymKinds() {
  $("#symKinds").innerHTML = KINDS.map(([k, l]) => `<button type="button" data-k="${k}" class="${k === symKind ? "on" : ""}">${l}</button>`).join("");
}
const mainSrc = () => (S.breezeOk ? "breeze" : "yf");      // NSE names search here on the "All" tab
function renderSymTabs() {
  const tabs = [["all", "All"], ...(S.breezeOk ? [["breeze", "Breeze"]] : []), ["yf", "Yahoo"], ["tv", "TV"]];
  if (!tabs.some(([k]) => k === symTab)) symTab = "all";
  $("#symTabs").innerHTML = tabs.map(([k, l]) => `<button type="button" data-k="${k}" class="${k === symTab ? "on" : ""}">${l}</button>`).join("");
  renderSymKinds();
}
$("#symKinds").onclick = (e) => {
  const b = e.target.closest("button[data-k]"); if (!b) return;
  symKind = b.dataset.k; renderSymKinds();
  $("#symInput").dispatchEvent(new Event("input")); $("#symInput").focus();
};
$("#symTabs").onclick = (e) => {
  const b = e.target.closest("button[data-k]"); if (!b) return;
  symTab = b.dataset.k; renderSymTabs();
  $("#symInput").dispatchEvent(new Event("input")); $("#symInput").focus();
};
function openSymbolDialog(mode) {
  symMode = mode;
  $("#symTitle").textContent = mode === "add" ? "Add to watchlist" : "Symbol search";
  renderSymTabs();
  $("#symInput").value = ""; $("#symResults").innerHTML = hintList();
  $("#symDlg").showModal(); $("#symInput").focus();
  tvAccount().then(() => { if (!$("#symInput").value.trim()) $("#symResults").innerHTML = hintList(); });
}
$("#symbolBtn").onclick = () => openSymbolDialog("chart");
$("#symResults").addEventListener("click", (e) => { if (e.target.closest("[data-tvlogin]")) { e.preventDefault(); $("#symDlg").close(); openTvLogin(); } });
function hintList() {
  const tv = ` TV: commodities, currency, global ("SILVER", "CRUDEOIL", "USDINR", "XAUUSD" → MCX:SILVER1!, FX_IDC:USDINR).`;
  const bz = S.breezeOk && symTab !== "yf" ? ` Breeze F&amp;O: "NIFTY FUT", "NIFTY 24000 CE", "BANKNIFTY NOV 52000 PE", "SENSEX 80000 CE" (BSE).` : "";
  const acct = symTab === "all" || symTab === "tv" ? `<div class="grp tv-acct">TradingView: ${tvUser ? `signed in as <b>${esc(tvUser)}</b>` : "guest (MCX needs an account)"} · <a href="#" data-tvlogin>${tvUser ? "Account" : "Sign in"}</a></div>` : "";
  return `<div class="grp">Type a name or symbol, Enter to use it as typed.${symTab === "tv" ? tv : symTab === "all" ? bz + tv : bz}</div>` + acct;
}
function pickSymbol(symbol, src) {
  symbol = canon(symbol);
  if (symTab === "tv" && !symbol.includes(":")) symbol = symbol in TV_INDEX ? TV_INDEX[symbol] : symbol;   // typed on the TV tab
  setSymSrc(symbol, src || (symTab === "all" || symTab === "tv" ? mainSrc() : symTab));
  $("#symDlg").close();
  if (symMode === "add") { addToWatchlist(symbol); return; }
  each("symbol", (c) => c.setSymbol(symbol));
}
const TV_INDEX = { NIFTY: "NSE:NIFTY", BANKNIFTY: "NSE:BANKNIFTY", SENSEX: "BSE:SENSEX", BANKEX: "BSE:BANKEX" };
let searchSeq = 0;
$("#symInput").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !e.target.value.trim()) return;
  e.preventDefault();
  const first = $("#symResults .it");
  // on the TV tab a bare name needs its exchange: take the top match (e.g. SILVER -> MCX:SILVER1!)
  if (symTab === "tv" && !e.target.value.includes(":") && first) first.click(); else pickSymbol(e.target.value);
});
async function searchSource(src, q) {
  try {
    const r = await fetch(`/api/search?source=${src}&kind=${symKind}&q=${encodeURIComponent(q)}`);
    if (!r.ok) return [{ symbol: canon(q), name: `search failed: HTTP ${r.status}`, type: "", src }];
    return (await r.json()).map((x) => ({ ...x, src }));
  } catch (e) { return [{ symbol: canon(q), name: `search failed: ${e.message || e}`, type: "", src }]; }
}
$("#symInput").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if (q.length < 2) { $("#symResults").innerHTML = hintList(); return; }
  searchTimer = setTimeout(async () => {
    const my = ++searchSeq;
    const srcs = symTab === "all" ? [mainSrc(), "tv"] : [symTab];
    $("#symResults").innerHTML = `<div class="searching">${SPIN}<span>Searching ${srcs.map((x) => SRC_NAME[x]).join(" + ")}…</span></div>`;
    const lists = (await Promise.all(srcs.map((x) => searchSource(x, q))))
      .map((l) => (symKind ? l.filter((r) => !r.symbol || kindOf(r) === symKind || /unavailable|failed/.test(r.name || "")) : l));
    if (my !== searchSeq) return;
    const box = $("#symResults");
    box.innerHTML = lists.some((l) => l.length) ? "" : `<div class="grp">No ${symKind ? KINDS.find(([k]) => k === symKind)[1].toLowerCase() + " " : ""}matches</div>`;
    lists.forEach((res, k) => {
      if (!res.length) return;
      if (srcs.length > 1) box.insertAdjacentHTML("beforeend", `<div class="grp">${SRC_NAME[srcs[k]]}</div>`);
      for (const r of res) {
        // a TradingView result is always stored with its exchange prefix, so it keeps the TV source
        const sym = r.src === "tv" && !String(r.symbol).includes(":") ? TV_INDEX[r.symbol] || r.symbol : r.symbol;
        const d = document.createElement("div");
        d.className = "it";
        d.innerHTML = `<span><b>${esc(sym)}</b> <small>${esc(r.name)}</small></span><span class="it-tags">${exTag(r.exchange ?? exchOf(sym))}<small class="tag">${esc(r.type || "")}</small><small class="src-badge ${r.src}">${r.src === "tv" ? "TV" : SRC_NAME[r.src]}</small></span>`;
        d.onclick = () => pickSymbol(sym, r.src);
        box.appendChild(d);
      }
    });
  }, 250);
});

// TradingView account: MCX and some other exchanges refuse guests. The server keeps the session in its cache
// folder; the password is only passed through to TradingView once.
let tvUser = null;
const tvAccount = () => fetch("/api/tv/account").then((r) => r.json()).then((d) => (tvUser = d.user)).catch(() => null);
function openTvLogin(reason = "") {
  if (document.querySelector("#tvLogin")) return;
  const d = document.createElement("dialog");
  d.id = "tvLogin";
  d.innerHTML = `<form method="dialog" class="dlg tv-login"><div class="dlg-head"><b>TradingView account</b><button value="cancel">✕</button></div>
    <div class="tvl-body"></div></form>`;
  document.body.appendChild(d);
  const body = d.querySelector(".tvl-body");
  const err = (t) => { const e = body.querySelector(".tvl-err"); if (e) e.textContent = t || ""; };
  const post = async (payload) => {
    const r = await fetch("/api/tv/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
    return j;
  };
  const done = (user) => { tvUser = user; d.close(); status(`TradingView: signed in${user ? " as " + user : ""}`, "live"); each("all", (c) => c.setSymbol(c.S.symbol)); };
  const busy = (b, on) => { b.disabled = on; b.innerHTML = on ? SPIN + " Signing in…" : b.dataset.t; };
  const view = (mode) => {
    if (mode === "user") {
      body.innerHTML = `<p>Signed in as <b>${esc(tvUser || "your account")}</b>. MCX and other exchanges load with this account.</p>
        <div class="dlg-foot"><span class="spacer"></span><button type="button" data-a="out">Sign out</button><button value="cancel" class="primary">Close</button></div>`;
      body.querySelector('[data-a="out"]').onclick = async () => { await fetch("/api/tv/logout", { method: "POST" }); tvUser = null; view("login"); };
      return;
    }
    if (mode === "2fa") {
      body.innerHTML = `<p>Enter the 6-digit code from your authenticator app.</p><input name="code" inputmode="numeric" autocomplete="one-time-code" placeholder="123456">
        <div class="tvl-err"></div><div class="dlg-foot"><span class="spacer"></span><button type="button" class="primary" data-t="Verify">Verify</button></div>`;
      const b = body.querySelector(".primary"), inp = body.querySelector("input"); inp.focus();
      b.onclick = async () => { busy(b, true); try { done((await post({ code: inp.value.trim() })).user); } catch (e) { err(e.message); } busy(b, false); };
      inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); b.click(); } };
      return;
    }
    if (mode === "session") {
      body.innerHTML = `<p class="muted">In a browser where you're signed in to tradingview.com: DevTools → Application → Cookies → copy <b>sessionid</b> and <b>sessionid_sign</b>. Kept only in the app's cache folder.</p>
        <input name="sid" placeholder="sessionid" autocomplete="off"><input name="sign" placeholder="sessionid_sign" autocomplete="off">
        <div class="tvl-err"></div><div class="dlg-foot"><button type="button" data-a="back">Back</button><span class="spacer"></span><button type="button" class="primary" data-t="Use session">Use session</button></div>`;
      const b = body.querySelector(".primary");
      body.querySelector('[data-a="back"]').onclick = () => view("login");
      b.onclick = async () => { busy(b, true); try { done((await post({ sessionid: body.querySelector('[name="sid"]').value, sessionid_sign: body.querySelector('[name="sign"]').value })).user); } catch (e) { err(e.message); } busy(b, false); };
      return;
    }
    body.innerHTML = `${reason ? `<p class="tvl-why">${esc(reason.replace(/^PermissionError: /, ""))}</p>` : ""}
      <p class="muted">Sign in once with a TradingView account (a free one works). The app keeps only the session, never your password.</p>
      <input name="u" placeholder="Email or username" autocomplete="username"><input name="p" type="password" placeholder="Password" autocomplete="current-password">
      <div class="tvl-err"></div>
      <div class="tvl-alt"><span class="muted">Signed in with Google?</span>
        <button type="button" data-a="auto" data-t="Use my browser's session">Use my browser's session</button>
        <button type="button" data-a="har">Import HAR file…</button><input type="file" accept=".har,application/json" hidden></div>
      <div class="dlg-foot"><button type="button" data-a="sess">Paste session instead</button><span class="spacer"></span><button type="button" class="primary" data-t="Sign in">Sign in</button></div>`;
    const b = body.querySelector(".primary"), u = body.querySelector('[name="u"]'), pw = body.querySelector('[name="p"]');
    body.querySelector('[data-a="sess"]').onclick = () => view("session");
    const ab = body.querySelector('[data-a="auto"]'), hb = body.querySelector('[data-a="har"]'), fi = body.querySelector('input[type="file"]');
    hb.dataset.t = hb.textContent;
    ab.onclick = async () => { busy(ab, true); try { done((await post({ auto: true })).user); } catch (e) { err(e.message); } busy(ab, false); };
    hb.onclick = () => fi.click();
    fi.onchange = async () => {
      const f = fi.files[0]; if (!f) return;
      busy(hb, true);
      try { done((await post({ har: await f.text() })).user); } catch (e) { err(e.message); }
      busy(hb, false); fi.value = "";
    };
    b.onclick = async () => {
      busy(b, true);
      try { const r = await post({ username: u.value.trim(), password: pw.value }); pw.value = ""; if (r.need_2fa) view("2fa"); else done(r.user); }
      catch (e) { err(e.message); }
      busy(b, false);
    };
    pw.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); b.click(); } };
    u.focus();
  };
  d.onclose = () => d.remove();
  d.showModal();
  tvAccount().then(() => view(tvUser ? "user" : "login"));
}
window.LTVTvLogin = openTvLogin;

// Breeze connection: the Connect button logs in again (OTP via Telegram) and stores the new session token
let bz = { connected: false };
const bzPaint = () => {
  const b = $("#bzBtn"); if (!b) return;
  b.classList.toggle("hidden", !S.breezeOk);
  const feedBad = bz.connected && bz.feed?.failed > 0;
  b.dataset.st = bz.renewing ? "wait" : feedBad ? "err" : bz.connected ? "on" : bz.error ? "err" : "off";
  b.title = bz.renewing ? "Breeze: waiting for the OTP on Telegram"
    : feedBad ? `Breeze connected, but the live tick feed is refused for ${bz.feed.failed} symbols (charts use polled 1m candles, no ticks recorded): ${bz.feed.error} · click to reconnect`
    : bz.connected ? "Breeze connected" + (bz.updated ? ` · token from ${bz.updated}` : "")
    : "Breeze not connected · click to connect";
};
const bzStatus = () => (EMBED ? Promise.resolve() : fetch("/api/breeze/status").then((r) => r.json()).then((d) => { bz = d; bzPaint(); }).catch(() => {}));
function openBreeze() {
  if (document.querySelector("#bzDlg")) return;
  const d = document.createElement("dialog");
  d.id = "bzDlg";
  d.innerHTML = `<form method="dialog" class="dlg tv-login"><div class="dlg-head"><b>Breeze (ICICI Direct)</b><button value="cancel">✕</button></div><div class="tvl-body"></div></form>`;
  document.body.appendChild(d);
  const body = d.querySelector(".tvl-body");
  const paint = (msg = "", busy = false) => {
    const st = busy || bz.renewing ? `${SPIN} Logging in… reply to the Telegram bot with the OTP ICICI sends you (90 s).`
      : bz.connected && bz.feed?.failed > 0 ? `<span class="bz-dot off"></span> Connected, but the live tick feed is refused for ${bz.feed.failed} symbols. Reconnect to restore ticks.`
      : bz.connected ? `<span class="bz-dot on"></span> Connected${bz.updated ? ` · token from ${esc(bz.updated)}` : ""}` : `<span class="bz-dot off"></span> Not connected`;
    const miss = bz.missing?.length ? `<p class="tvl-why">Add to .env first: ${bz.missing.map(esc).join(", ")}</p>` : "";
    body.innerHTML = `<p>${st}</p>${miss}<p class="muted">Connect logs in to ICICI with your .env credentials and asks for the OTP on Telegram. The new session token is saved to .env.</p>
      <div class="tvl-err">${esc(msg || bz.error || "")}</div>
      <div class="dlg-foot"><span class="spacer"></span><button value="cancel">Close</button><button type="button" class="primary" ${busy || bz.renewing || bz.missing?.length ? "disabled" : ""}>${bz.connected ? "Reconnect" : "Connect"}</button></div>`;
    body.querySelector(".primary").onclick = connect;
  };
  const connect = async () => {
    paint("", true); bz.renewing = true; bzPaint();
    try {
      const r = await fetch("/api/breeze/connect", { method: "POST" });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
      bz = j; bzPaint(); paint();
      status("Breeze connected", "live");
      quotes.clear(); sendWatch(); each("all", (c) => c.setSymbol(c.S.symbol));
    } catch (e) { await bzStatus(); paint(e.message); }
  };
  d.onclose = () => d.remove();
  d.showModal();
  paint(); bzStatus().then(() => document.querySelector("#bzDlg") && paint());
}
if (!EMBED) { $("#bzBtn").onclick = openBreeze; setInterval(bzStatus, 30000); }

// watchlist with live quotes
const quotes = new Map();          // "source:symbol" -> {last, chg, pct, error}
const wkey = (name) => `${srcFor(name)}:${name}`;
const fmtQ = (v, p = 2) => (v == null || Number.isNaN(v) ? "–" : Number(v).toLocaleString(undefined, { minimumFractionDigits: p, maximumFractionDigits: p }));
function renderWatchlist() {
  $("#wlName span").textContent = S.watchlists[S.wlActive].name;
  const box = $("#wlItems");
  box.innerHTML = "";
  S.watchlist.forEach((w, i) => {
    const d = document.createElement("div");
    d.className = "wl-row wl-item" + (w === A().S.symbol ? " cur" : "");
    d.dataset.key = wkey(w);
    const src = srcFor(w), ex = exchOf(w);
    d.title = [w, ex, SRC_NAME[src] || src].filter(Boolean).join(" · ");
    d.innerHTML = `<span class="sym"><span class="sym-n">${esc(w)}</span><span class="wl-tags">${exTag(ex)}<i class="src-tag ${src}" title="Streaming from ${SRC_NAME[src] || src}">${SRC_TAG[src] || src}</i></span></span><span class="q-last sk"></span><span class="q-chg sk"></span><span class="q-pct sk"></span>` +
      `<button title="Remove from watchlist" class="rm">✕</button>`;
    d.onclick = () => each("symbol", (c) => c.setSymbol(w));
    d.querySelector(".rm").onclick = (e) => { e.stopPropagation(); S.watchlist.splice(i, 1); save(); renderWatchlist(); sendWatch(); };
    box.appendChild(d);
    paintQuote(d, quotes.get(wkey(w)), false);
  });
}
function paintQuote(row, q, flash = true) {
  if (!row || !q) return;
  const last = row.querySelector(".q-last"), chg = row.querySelector(".q-chg"), pct = row.querySelector(".q-pct");
  for (const c of [last, chg, pct]) c.classList.remove("sk");
  if (q.error && q.last == null) { last.textContent = "n/a"; last.title = q.error; return; }
  const cls = q.chg == null ? "" : q.chg >= 0 ? "up" : "dn";
  if (flash && row._last != null && q.last !== row._last) {
    last.classList.remove("fu", "fd"); void last.offsetWidth; last.classList.add(q.last > row._last ? "fu" : "fd");
  }
  row._last = q.last;
  last.textContent = fmtQ(q.last);
  chg.textContent = q.chg == null ? "–" : (q.chg >= 0 ? "+" : "") + fmtQ(q.chg);
  pct.textContent = q.pct == null ? "–" : (q.pct >= 0 ? "+" : "") + fmtQ(q.pct) + "%";
  chg.className = "q-chg " + cls; pct.className = "q-pct " + cls;
}
function onQuotes(items) {
  for (const q of items) {
    const prev = quotes.get(q.key) || {};
    const merged = q.error ? { ...prev, error: q.error } : q;
    quotes.set(q.key, merged);
    paintQuote(document.querySelector(`.wl-item[data-key="${CSS.escape(q.key)}"]`), merged);
  }
  window.LTVSide?.onQuotes(items);
}
function addToWatchlist(symbol) {
  symbol = canon(symbol);
  if (!S.watchlist.includes(symbol)) S.watchlist.push(symbol);
  save(); renderWatchlist(); sendWatch();
}
function sendWatch() {
  if (EMBED) return;
  const syms = [...new Set([...S.watchlist, ...(window.LTVSide?.extraSymbols() || [])])];
  send({ op: "watch", items: syms.map((symbol) => ({ source: srcFor(symbol), symbol })) });
}
function setSource(src) {
  if (src === S.source) return;
  S.source = src;
  quotes.clear();
  const fno = FNO_RE.exec(S.symbol);   // F&O exists on Breeze only
  if (fno && src !== "breeze") S.symbol = fno[1];
  save(); renderWatchlist(); sendWatch(); loadSymbol();
}
$("#wlAdd").onclick = () => openSymbolDialog("add");

// named watchlists: switch / create / rename / copy / clear / delete
function useWatchlist(i) {
  S.wlActive = i; S.watchlist = S.watchlists[i].items;
  quotes.clear(); save(); renderWatchlist(); sendWatch();
}
function askName(title, value = "") {
  return new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.innerHTML = `<form method="dialog" class="dlg wl-dlg"><div class="dlg-head"><b>${esc(title)}</b><button value="cancel">✕</button></div>
      <input name="n" maxlength="40" autocomplete="off" placeholder="Name">
      <div class="dlg-foot"><span class="spacer"></span><button value="cancel">Cancel</button><button value="ok" class="primary">Save</button></div></form>`;
    document.body.appendChild(d);
    const inp = d.querySelector("input"); inp.value = value;
    d.onclose = () => { const v = inp.value.trim(); d.remove(); resolve(d.returnValue === "ok" && v ? v : null); };
    d.showModal(); inp.select();
  });
}
const uniqueName = (n, skip = -1) => { let out = n, k = 2; while (S.watchlists.some((l, i) => i !== skip && l.name === out)) out = `${n} (${k++})`; return out; };
$("#wlName").onclick = () => {
  const r = $("#wlName").getBoundingClientRect(), cur = S.watchlists[S.wlActive];
  LTVSettings.openMenu([
    ...S.watchlists.map((l, i) => ({ label: l.name, hint: String(l.items.length), checked: i === S.wlActive, action: () => useWatchlist(i) })),
    "-",
    { label: "Create new list…", icon: "＋", action: async () => { const n = await askName("Create new list"); if (n) { S.watchlists.push({ name: uniqueName(n), items: [] }); useWatchlist(S.watchlists.length - 1); } } },
    { label: "Rename…", icon: "✎", action: async () => { const n = await askName("Rename list", cur.name); if (n) { cur.name = uniqueName(n, S.wlActive); save(); renderWatchlist(); } } },
    { label: "Make a copy…", icon: "⧉", action: async () => { const n = await askName("Copy list", cur.name + " copy"); if (n) { S.watchlists.push({ name: uniqueName(n), items: [...cur.items] }); useWatchlist(S.watchlists.length - 1); } } },
    { label: "Clear list", icon: "⌫", disabled: !cur.items.length, action: async () => { if (await LTVSettings.confirm(`Remove all ${cur.items.length} symbols from "${cur.name}"?`, { title: "Clear list", ok: "Clear", danger: true })) { cur.items.length = 0; save(); renderWatchlist(); sendWatch(); } } },
    { label: "Delete list", icon: "🗑", disabled: S.watchlists.length < 2, action: async () => { if (await LTVSettings.confirm(`Delete list "${cur.name}"?`, { title: "Delete list", ok: "Delete", danger: true })) { S.watchlists.splice(S.wlActive, 1); useWatchlist(Math.max(0, S.wlActive - 1)); } } },
  ], r.left, r.bottom + 4);
};
// resizable width (drag the left edge, like TradingView's right panel)
const wlEl = $("#watchlist");
const setWlWidth = (w) => { wlEl.style.width = Math.round(Math.max(200, Math.min(window.innerWidth * 0.6, w))) + "px"; };
if (S.wlWidth) setWlWidth(S.wlWidth);
$("#wlResize").addEventListener("pointerdown", (e) => {
  e.preventDefault();
  const x0 = e.clientX, w0 = wlEl.offsetWidth, h = e.currentTarget;
  h.setPointerCapture(e.pointerId); document.body.classList.add("wl-resizing");
  const move = (ev) => setWlWidth(w0 + (x0 - ev.clientX));
  const up = () => { h.removeEventListener("pointermove", move); h.removeEventListener("pointerup", up); document.body.classList.remove("wl-resizing"); S.wlWidth = wlEl.offsetWidth; save(); };
  h.addEventListener("pointermove", move); h.addEventListener("pointerup", up);
});
$("#wlResize").ondblclick = () => { setWlWidth(320); S.wlWidth = 320; save(); };

// indicator picker
async function loadCatalogue() {
  try { scripts = await (await fetch("/api/scripts")).json(); } catch { scripts = []; }
  const sel = $("#edOpen");
  sel.innerHTML = `<option value="">Open…</option>` +
    `<optgroup label="My scripts">${scripts.filter((s) => s.kind === "user").map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("")}</optgroup>` +
    `<optgroup label="Built-in">${scripts.filter((s) => s.kind === "builtin").map((s) => `<option value="${esc(s.id)}">${esc(s.title)}</option>`).join("")}</optgroup>`;
}
function renderIndList() {
  const q = $("#indSearch").value.toLowerCase();
  const box = $("#indList");
  box.innerHTML = "";
  for (const [kind, label] of [["user", "My scripts"], ["builtin", "Built-in"]]) {
    const items = scripts.filter((s) => s.kind === kind && (s.title + s.name).toLowerCase().includes(q));
    if (!items.length) continue;
    box.insertAdjacentHTML("beforeend", `<div class="grp">${label}</div>`);
    for (const s of items) {
      const d = document.createElement("div");
      d.className = "it";
      d.innerHTML = `<span>${esc(s.title)}</span><small>${esc(s.name)}</small>`;
      d.onclick = async () => {
        const { code } = await (await fetch(`/api/scripts/${encodeURIComponent(s.id)}`)).json();
        A().addIndicator({ ref: s.id, code });
        $("#indDlg").close();
      };
      box.appendChild(d);
    }
  }
}
$("#indBtn").onclick = async () => { await loadCatalogue(); $("#indSearch").value = ""; renderIndList(); $("#indDlg").showModal(); $("#indSearch").focus(); };
$("#indSearch").oninput = renderIndList;

// settings dialog (TradingView-like: Inputs / Style tabs, live preview, Defaults / Cancel / OK)
const PLOT_TYPES = [["line", "Line"], ["step", "Step line"], ["histogram", "Histogram"], ["area", "Area"], ["circles", "Circles"]];
const STYLE_OPTS = [["solid", "────"], ["dashed", "─ ─ ─"], ["dotted", "·······"], ["large dashed", "── ──"]];
const opt = (list, v) => list.map(([k, l]) => `<option value="${k}" ${k === v ? "selected" : ""}>${l}</option>`).join("");
function restyle(ind) {
  if (!ind.lastMsg) return;
  ind.sig = "";
  onIndicatorFull(ind.lastMsg);
}
function openSettings(ind) {
  const meta = ind.meta || { inputs: [], plots: [], hlines: [] };
  const before = { style: JSON.parse(JSON.stringify(ind.style)), inputs: { ...ind.inputs } };
  const st = ind.style;
  st.plots = st.plots || {}; st.hlines = st.hlines || {};
  $("#setTitle").textContent = meta.title || "Indicator";
  const form = $("#setForm");
  form.innerHTML = `<div class="tabs"><button type="button" data-tab="in" class="on">Inputs</button><button type="button" data-tab="st">Style</button></div>
    <div class="tab" data-pane="in"></div><div class="tab hidden" data-pane="st"></div>`;
  form.querySelectorAll("[data-tab]").forEach((b) => b.onclick = () => {
    form.querySelectorAll("[data-tab]").forEach((x) => x.classList.toggle("on", x === b));
    form.querySelectorAll("[data-pane]").forEach((x) => x.classList.toggle("hidden", x.dataset.pane !== b.dataset.tab));
  });

  // Inputs tab
  const pin = form.querySelector('[data-pane="in"]');
  if (!meta.inputs.length) pin.innerHTML = `<div class="muted">No inputs.</div>`;
  if (meta.help) pin.insertAdjacentHTML("afterbegin", `<a class="in-help" href="${esc(meta.help)}" target="_blank" rel="noopener">📖 How to use this indicator</a>`);
  for (const sp of meta.inputs) {
    const val = ind.inputs[sp.name] ?? sp.default;
    const lab = document.createElement("label");
    lab.className = "srow";
    lab.innerHTML = `<span>${esc(sp.name)}${sp.tooltip ? ` <span class="in-info" title="${esc(sp.tooltip)}">ⓘ</span>` : ""}</span>`;
    lab.querySelector(".in-info")?.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); });
    let el;
    if (sp.options) {
      el = document.createElement("select");
      el.innerHTML = sp.options.map((o) => `<option ${o === val ? "selected" : ""}>${esc(o)}</option>`).join("");
    } else if (sp.type === "bool") {
      el = document.createElement("input"); el.type = "checkbox"; el.checked = !!val;
    } else if (sp.type === "str" && /^(#[0-9a-f]{3,8}|rgba?\()/i.test(String(sp.default))) {
      // colour input: picker + opacity, stored as rgba() text in a hidden field
      const m = String(val).match(/rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:[ ,/]+([\d.]+))?/i);
      const alpha0 = m ? (m[4] != null ? +m[4] : 1) : 1;
      const wrap = document.createElement("span"); wrap.className = "ctl";
      wrap.innerHTML = `<input type="color" value="${toHex(val)}"><input type="range" min="0" max="1" step="0.05" value="${alpha0}" title="Opacity">`;
      const [pick, alpha] = wrap.querySelectorAll("input");
      el = document.createElement("input"); el.type = "hidden"; el.value = val;
      const upd = () => { el.value = +alpha.value >= 1 ? pick.value : hexA(pick.value, +alpha.value); };
      pick.oninput = alpha.oninput = upd;
      wrap.appendChild(el);
      el.dataset.name = sp.name; el.dataset.type = sp.type;
      lab.appendChild(wrap);
      pin.appendChild(lab);
      continue;
    } else {
      el = document.createElement("input");
      el.type = sp.type === "int" || sp.type === "float" ? "number" : "text";
      if (sp.min != null) el.min = sp.min;
      if (sp.max != null) el.max = sp.max;
      el.step = sp.step ?? (sp.type === "float" ? "any" : 1);
      el.value = val;
    }
    el.dataset.name = sp.name; el.dataset.type = sp.type;
    lab.appendChild(el);
    pin.appendChild(lab);
  }

  // Style tab
  const pst = form.querySelector('[data-pane="st"]');
  const row = (html) => { const d = document.createElement("div"); d.className = "srow"; d.innerHTML = html; pst.appendChild(d); return d; };
  for (const p of meta.plots) {
    const o = st.plots[p.title] || {};
    const d = row(`<label class="chk"><input type="checkbox" data-k="visible" ${o.visible === false ? "" : "checked"}> ${esc(p.title)}</label>
      <span class="ctl"><input type="color" data-k="color" value="${toHex(o.color || p.color)}" title="Colour">
      <select data-k="lineWidth" title="Width">${opt([[1, "1px"], [2, "2px"], [3, "3px"], [4, "4px"]].map(([a, b]) => [String(a), b]), String(o.lineWidth || p.lineWidth))}</select>
      <select data-k="lineStyle" title="Line style">${opt(STYLE_OPTS, o.lineStyle || "solid")}</select>
      <select data-k="style" title="Plot type">${opt(PLOT_TYPES, o.style || p.style)}</select></span>`);
    d.oninput = d.onchange = () => {
      const q = d.querySelector.bind(d);
      st.plots[p.title] = { visible: q('[data-k="visible"]').checked, color: q('[data-k="color"]').value,
        lineWidth: +q('[data-k="lineWidth"]').value, lineStyle: q('[data-k="lineStyle"]').value, style: q('[data-k="style"]').value };
      if (st.plots[p.title].color === toHex(p.color)) delete st.plots[p.title].color;
      restyle(ind);
    };
  }
  for (const h of meta.hlines) {
    const key = h.title || String(h.price);
    const o = st.hlines[key] || {};
    const d = row(`<label class="chk"><input type="checkbox" data-k="visible" ${o.visible === false ? "" : "checked"}> ${esc(h.title || "Level")}</label>
      <span class="ctl"><input type="number" step="any" data-k="price" value="${o.price ?? h.price}" title="Level" style="width:80px">
      <input type="color" data-k="color" value="${toHex(o.color || h.color)}" title="Colour">
      <select data-k="lineStyle" title="Line style">${opt(STYLE_OPTS, o.lineStyle || h.style)}</select></span>`);
    d.oninput = d.onchange = () => {
      const q = d.querySelector.bind(d);
      st.hlines[key] = { visible: q('[data-k="visible"]').checked, color: q('[data-k="color"]').value,
        lineStyle: q('[data-k="lineStyle"]').value, price: parseFloat(q('[data-k="price"]').value) };
      restyle(ind);
    };
  }
  const flags = [["markers", "Signals (buy/sell markers)", meta.hasMarkers], ["priceLabels", "Labels on price scale", true],
    ["showTitles", "Plot names on price scale", true, false], ["showValues", "Values in status line", true, false], ["showInputs", "Inputs in status line", true, false]];
  pst.insertAdjacentHTML("beforeend", `<div class="sep-h"></div>`);
  for (const [k, label, show, dflt = true] of flags) {
    if (!show) continue;
    const on = k === "showInputs" || k === "showValues" ? legendOpt(ind, k) : (st[k] ?? dflt);
    const d = row(`<label class="chk"><input type="checkbox" ${on ? "checked" : ""}> ${label}</label>`);
    d.querySelector("input").onchange = (e) => { st[k] = e.target.checked; restyle(ind); applyVisibility(ind); renderIndLegend(); };
  }
  const pr = row(`<span>Precision</span><select>${opt([["", "Default"], ...[0, 1, 2, 3, 4, 5, 6].map((n) => [String(n), String(n)])], st.precision == null ? "" : String(st.precision))}</select>`);
  pr.querySelector("select").onchange = (e) => { st.precision = e.target.value === "" ? null : +e.target.value; restyle(ind); renderIndLegend(); };

  let reset = false;
  $("#setDefaults").onclick = () => { reset = true; $("#setDlg").returnValue = "ok"; $("#setDlg").close(); };
  $("#setDlg").onclose = () => {
    if ($("#setDlg").returnValue !== "ok") {          // cancel: revert live preview
      ind.style = before.style; ind.inputs = before.inputs;
      restyle(ind); applyVisibility(ind); renderIndLegend();
      return;
    }
    if (reset) { ind.style = {}; ind.inputs = {}; }
    else for (const el of form.querySelectorAll('[data-pane="in"] [data-name]')) {
      const t = el.dataset.type;
      ind.inputs[el.dataset.name] = t === "bool" ? el.checked : t === "int" ? parseInt(el.value, 10) : t === "float" ? parseFloat(el.value) : el.value;
    }
    save();
    restyle(ind);
    updateIndicator(ind);
    renderIndLegend();
  };
  $("#setDlg").returnValue = "";
  $("#setDlg").showModal();
}

// ------------------------------------------------------------------ script editor
const TEMPLATE = `indicator("My Indicator", overlay=True)
length = input("Length", 20, min=1)

basis = ema(close, length)
plot(basis, "Basis", color="#2962ff")

# Signals
plotshape(crossover(close, basis), "Cross up", position="below", shape="arrowUp", color="#26a69a")
plotshape(crossunder(close, basis), "Cross down", position="above", shape="arrowDown", color="#ef5350")
`;
const ed = $("#edCode");
function toggleEditor(show) { $("#editor").classList.toggle("hidden", !show); }
function bindEditor(id) {
  editingId = id;
  $("#edApply").textContent = id ? "Update on chart" : "Add to chart";
}
function consoleMsg(msg, cls = "") { $("#edConsole").innerHTML = `<div class="${cls}">${esc(msg)}</div>`; }
function openEditor({ code = TEMPLATE, ref = null, bindId = null } = {}) {
  toggleEditor(true);
  ed.value = code;
  const [kind, name] = (ref || "").split(":");
  $("#edName").value = kind === "user" ? name : kind === "builtin" ? "my_" + name : "";
  bindEditor(bindId);
  consoleMsg(kind === "builtin" ? "Built-in script: edit and Save under a new name, or Update on chart." : "");
  ed.focus();
}
$("#editorBtn").onclick = async () => {
  if (A() !== LOCAL) { A().toggleEditor(); return; }
  await loadCatalogue();
  if ($("#editor").classList.contains("hidden")) { if (!ed.value) openEditor(); else toggleEditor(true); } else toggleEditor(false);
};
$("#edClose").onclick = () => toggleEditor(false);
$("#edNew").onclick = () => openEditor();
$("#edOpen").onchange = async (e) => {
  const id = e.target.value;
  e.target.value = "";
  if (!id) return;
  const { code } = await (await fetch(`/api/scripts/${encodeURIComponent(id)}`)).json();
  openEditor({ code, ref: id });
};
async function saveScript() {
  const name = $("#edName").value.trim();
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(name)) { consoleMsg("✗ Name: letters, digits, _ or - only", "err"); $("#edName").focus(); return null; }
  const r = await fetch(`/api/scripts/${encodeURIComponent("user:" + name)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: ed.value }),
  });
  if (!r.ok) { consoleMsg("✗ Save failed: " + (await r.text()), "err"); return null; }
  consoleMsg(`✓ Saved as ${name}`, "ok");
  await loadCatalogue();
  return "user:" + name;
}
$("#edSave").onclick = saveScript;
$("#edDelete").onclick = async () => {
  const name = $("#edName").value.trim();
  if (!name || !(await LTVSettings.confirm(`Delete script "${name}"?`, { title: "Delete script", ok: "Delete", danger: true }))) return;
  await fetch(`/api/scripts/${encodeURIComponent("user:" + name)}`, { method: "DELETE" });
  consoleMsg(`Deleted ${name}`); await loadCatalogue();
};
function applyEditor() {
  const ind = editingId && inds.get(editingId);
  if (ind) { ind.code = ed.value; updateIndicator(ind); consoleMsg("Running…"); return; }
  const name = $("#edName").value.trim();
  const added = addIndicator({ ref: name ? "user:" + name : null, code: ed.value });
  bindEditor(added.id);
  consoleMsg("Running…");
}
$("#edApply").onclick = applyEditor;
ed.addEventListener("keydown", (e) => {
  if (e.key === "Tab") {
    e.preventDefault();
    const s = ed.selectionStart;
    ed.setRangeText("    ", s, ed.selectionEnd, "end");
  } else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); applyEditor(); }
  else if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); saveScript(); }
});

// ------------------------------------------------------------------ chart settings (TradingView "Settings" + price-scale menu)
const SCALE_MODE = { regular: 0, log: 1, percent: 2, indexed: 3 };
const CROSS_STYLE = { solid: 0, dotted: 1, dashed: 2, large: 3 };
const scaleSide = () => (CS.placement === "left" ? "left" : "right");
const themeColor = { bg: "--bg", bg2: "--bg", vGridColor: "--border", hGridColor: "--border", textColor: "--muted", lineColor: "--border" };
function csColor(k) {
  if (CS[k]) return CS[k];
  if (themeColor[k]) return toHex(css(themeColor[k]));
  return { crossColor: "#9598a1", priceLineColor: "#9598a1" }[k] || "#787b86";
}
function candleOpts() {
  const clear = "rgba(0,0,0,0)";
  return {
    upColor: !CS.body || S.chartType === "hollow" ? clear : CS.upColor, downColor: CS.body ? CS.downColor : clear,
    borderVisible: CS.borders, borderUpColor: CS.borderUp, borderDownColor: CS.borderDown,
    wickVisible: CS.wick, wickUpColor: CS.wickUp, wickDownColor: CS.wickDown,
  };
}
function mainPrecision() {
  if (CS.precision !== "default") return +CS.precision;
  const c = bars[bars.length - 1]?.[4];
  return c != null && Math.abs(c) < 1 ? 4 : 2;
}
function applyMainOpts() {
  if (!mainSeries) return;
  const p = mainPrecision();
  const o = { lastValueVisible: CS.symLabel, priceLineVisible: CS.symLine, priceLineColor: CS.priceLineColor || "",
    title: CS.symName ? S.symbol : "", priceScaleId: scaleSide(), priceFormat: { type: "price", precision: p, minMove: Math.pow(10, -p) } };
  if (S.chartType === "candles" || S.chartType === "hollow" || S.chartType === "ha") Object.assign(o, candleOpts());
  if (S.chartType === "bars") Object.assign(o, { upColor: CS.upColor, downColor: CS.downColor });
  mainSeries.applyOptions(o);
}
function applyChartSettings() {
  const side = scaleSide(), left = side === "left";
  const bg = CS.bgType === "gradient"
    ? { type: LW.ColorType.VerticalGradient, topColor: csColor("bg"), bottomColor: csColor("bg2") }
    : { type: LW.ColorType.Solid, color: csColor("bg") };
  const cross = { color: csColor("crossColor"), style: CROSS_STYLE[CS.crossStyle] ?? 2 };
  const scale = { borderVisible: true, borderColor: csColor("lineColor"), alignLabels: CS.noOverlap };
  chart.applyOptions({
    layout: { background: bg, textColor: csColor("textColor"), fontSize: +CS.fontSize || 12, panes: { separatorColor: css("--border") } },
    grid: { vertLines: { visible: CS.vGrid, color: CS.vGridColor || css("--border") + "80" }, horzLines: { visible: CS.hGrid, color: CS.hGridColor || css("--border") + "80" } },
    crosshair: { vertLine: cross, horzLine: cross },
    timeScale: { rightOffset: +CS.rightBars, borderVisible: true, borderColor: csColor("lineColor") },
    leftPriceScale: { ...scale, visible: left }, rightPriceScale: { ...scale, visible: !left },
  });
  // indicator series follow the scale side and the label options
  for (const ind of inds.values()) {
    for (const s of ind.series) {
      if (!s._ltv) continue;
      s.applyOptions({ ...(s._ltv.own ? {} : { priceScaleId: side }), title: s._ltv.showTitle || CS.indName ? s._ltv.title : "" });
    }
    if (ind.lastMsg) syncLastLabels(ind, ind.lastMsg.plots);
  }
  if (mainSeries) {
    applyMainOpts();
    const ps = chart.priceScale(side, 0);
    ps.applyOptions({ mode: SCALE_MODE[CS.mode] ?? 0, invertScale: CS.invert, autoScale: CS.autoScale,
      scaleMargins: { top: (+CS.marginTop || 0) / 100, bottom: (+CS.marginBottom || 0) / 100 } });
    setMainData();
  }
  applyWatermark();
  for (const [id, mode] of [["navBar", CS.navButtons], ["alBar", CS.scaleModes], ["curLabel", CS.currency]]) {
    const el = $("#" + id); if (!el) continue;
    el.classList.toggle("hidden", mode === "hidden"); el.classList.toggle("ov-hover", mode === "hover");
  }
  document.querySelectorAll(".pane-btns").forEach((x) => x.remove());
  paneSig = "";
  markPriceLinesDirty();
  if (typeof renderIndLegend === "function") { renderIndLegend(); showMainLegend(bars.length - 1); }
  try { draw.redraw(); } catch { /* drawings not initialised yet */ }
}
function setCS(next) {
  const reload = ("timezone" in next && next.timezone !== CS.timezone) || ("session" in next && next.session !== CS.session);
  Object.assign(CS, next);
  save();
  if (next.timezone !== undefined) TZ = tzOffset(CS.timezone);
  applyChartSettings();
  if (reload) loadSymbol(false);
}

// watermark ---------------------------------------------------------
let watermark = null;
function applyWatermark() {
  const tf = TFS.find((x) => x[1] === S.tf)?.[0] || "";
  const text = CS.watermark === "symbol" ? S.symbol : CS.watermark === "symbol_tf" ? `${S.symbol}, ${tf}` : "";
  try {
    if (!text) { if (watermark) { watermark.detach(); watermark = null; } return; }
    const opts = { horzAlign: "center", vertAlign: "center", lines: [{ text, color: hexA(csColor("watermarkColor"), 0.22), fontSize: 64, fontStyle: "bold" }] };
    if (watermark) watermark.applyOptions(opts); else watermark = LW.createTextWatermark(chart.panes()[0], opts);
  } catch (e) { console.warn("watermark", e); }
}

// price lines: previous day close, high/low of the visible range -------------------
let priceLines = {}, plDirty = true;
function markPriceLinesDirty() { plDirty = true; }
function setLine(key, price, opts) {
  const show = price != null && (opts.lineVisible || opts.axisLabelVisible);
  const cur = priceLines[key];
  if (!show) { if (cur) { mainSeries.removePriceLine(cur); delete priceLines[key]; } return; }
  const o = { price, lineWidth: 1, lineStyle: LW.LineStyle.Dashed, ...opts };
  if (cur) cur.applyOptions(o); else priceLines[key] = mainSeries.createPriceLine(o);
}
function refreshPriceLines() {
  if (!mainSeries || !bars.length) return;
  setLine("prev", prevDayClose(), { color: CS.prevColor, lineVisible: CS.prevLine, axisLabelVisible: CS.prevLabel, title: CS.prevLabel ? "Prev close" : "" });
  let hi = null, lo = null;
  const r = chart.timeScale().getVisibleLogicalRange();
  if (r) for (let i = Math.max(0, Math.floor(r.from)); i <= Math.min(bars.length - 1, Math.ceil(r.to)); i++) {
    if (hi == null || bars[i][2] > hi) hi = bars[i][2];
    if (lo == null || bars[i][3] < lo) lo = bars[i][3];
  }
  const hl = { color: CS.hlColor, lineVisible: CS.hlLine, axisLabelVisible: CS.hlLabel, lineStyle: LW.LineStyle.Dotted };
  setLine("hi", hi, { ...hl, title: CS.hlLabel ? "High" : "" });
  setLine("lo", lo, { ...hl, title: CS.hlLabel ? "Low" : "" });
}
chart.timeScale().subscribeVisibleLogicalRangeChange(() => { if (CS.hlLine || CS.hlLabel) markPriceLinesDirty(); });

// on-chart overlays: plus button, countdown, A/L, currency, gear, navigation, pane buttons ---------
const wrapEl = $("#chartWrap");
function ov(id, cls, html = "") {
  const d = document.createElement("div"); d.id = id; d.className = cls; d.innerHTML = html; wrapEl.appendChild(d); return d;
}
const plusBtn = ov("plusBtn", "ov plus hidden", "+");
const countdown = ov("countdown", "ov countdown hidden");
const xLabel = ov("xLabel", "ov xlabel hidden");   // crosshair price label, drawn above the last-price label and countdown
const alBar = ov("alBar", "ov albar", '<button data-m="auto" title="Auto (fits data to screen)">A</button><button data-m="log" title="Logarithmic (Alt + L)">L</button>');
const curLabel = ov("curLabel", "ov curlabel", "INR");
const gearBtn = ov("gearBtn", "ov gear", '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M7 4h10l5 8-5 8H7l-5-8z"/><circle cx="12" cy="12" r="3"/></svg>');
const navBar = ov("navBar", "ov navbar", ["−:Zoom out:zo", "+:Zoom in:zi", "‹:Scroll left:sl", "›:Scroll right:sr", "⟲:Reset chart view:rs"]
  .map((x) => { const [t, n, a] = x.split(":"); return `<button data-a="${a}" title="${n}">${t}</button>`; }).join(""));
gearBtn.title = "Price scale settings";
gearBtn.onclick = () => { const r = gearBtn.getBoundingClientRect(); LTVSettings.openMenu(priceMenu(), r.left - 230, r.top - 10); };
alBar.querySelector('[data-m="auto"]').onclick = () => setCS({ autoScale: !chart.priceScale(scaleSide(), 0).options().autoScale });
alBar.querySelector('[data-m="log"]').onclick = () => setCS({ mode: CS.mode === "log" ? "regular" : "log" });
navBar.onclick = (e) => {
  const a = e.target.closest("button")?.dataset.a, ts = chart.timeScale(), r = navAnim?.to || ts.getVisibleLogicalRange();
  if (!a || !r) return;
  const w = r.to - r.from, c = (r.from + r.to) / 2;
  if (a === "zo") animateRange({ from: c - w * 0.625, to: c + w * 0.625 });
  if (a === "zi") animateRange({ from: c - w * 0.4, to: c + w * 0.4 });
  if (a === "sl") animateRange({ from: r.from - w * 0.3, to: r.to - w * 0.3 });
  if (a === "sr") animateRange({ from: r.from + w * 0.3, to: r.to + w * 0.3 });
  if (a === "rs") resetChartView();
};
// navigation buttons move only this chart, with an eased glide
let navAnim = null;
function animateRange(to, ms = 320) {
  const ts = chart.timeScale(), from = ts.getVisibleLogicalRange();
  if (!from) return;
  if (navAnim) cancelAnimationFrame(navAnim.raf); else applyingSync++;
  const t0 = performance.now(), ease = (x) => 1 - Math.pow(1 - x, 3);
  navAnim = { to };
  const step = (now) => {
    const k = ease(Math.min(1, (now - t0) / ms));
    ts.setVisibleLogicalRange({ from: from.from + (to.from - from.from) * k, to: from.to + (to.to - from.to) * k });
    if (k < 1) navAnim.raf = requestAnimationFrame(step);
    else { navAnim = null; requestAnimationFrame(() => applyingSync--); }
  };
  navAnim.raf = requestAnimationFrame(step);
}
// a new symbol has its own price range: turn auto-scale back on for every pane (dragging the axis turns it off)
function fitPrices() {
  if (!CS.autoScale) setCS({ autoScale: true });
  const n = chart.panes ? chart.panes().length : 1;
  for (let i = 0; i < n; i++) for (const side of ["right", "left"]) {
    try { chart.priceScale(side, i).applyOptions({ autoScale: true }); } catch { /* no scale on that side */ }
  }
}
function resetPriceScale() { setCS({ autoScale: true }); chart.priceScale(scaleSide(), 0).applyOptions({ autoScale: true }); }
function resetChartView() {
  resetPriceScale();
  animateRange({ from: Math.max(0, bars.length - 160), to: bars.length + (+CS.rightBars || 0) });
}
// crosshair "+": TradingView-style quick menu (alerts, paper orders, horizontal line) ----------
let plusAt = null;          // { price, pane, ind } under the crosshair
function paneTop(k) { let y = 0; try { const ps = chart.panes(); for (let i = 0; i < k; i++) y += ps[i].getHeight() + 1; } catch { /* */ } return y; }
function indsOnPane(k) { return [...inds.values()].filter((i) => i.visible && i.series[0] && i.series[0].getPane().paneIndex() === k); }
function lastClose() { return bars[bars.length - 1]?.[4]; }
function plusTarget() {     // crosshair point, or the last close when the mouse is off the chart
  return plusAt && plusAt.live ? plusAt : (mainSeries && lastClose() != null ? { price: lastClose(), pane: 0 } : null);
}
const sideApi = () => window.top.LTVSide;
function plusMenuItems(t) {
  const sym = S.symbol, pr = mainPrecision(), px = fmt(t.price, pr), items = [];
  if (t.pane === 0) {
    const above = t.price >= (lastClose() ?? t.price);
    items.push({ label: `Add alert on ${sym} at ${px}`, keys: "Alt + A", icon: "⏰", action: () => sideApi()?.newAlert({ symbol: sym, price: t.price }) });
    for (const ind of indsOnPane(0)) {   // each overlay at its own scale (e.g. Volume)
      const v = ind.series[0].coordinateToPrice(t.y); if (v == null) continue;
      const vs = ind.lastMsg?.scale ? fmtVol(v) : fmt(v, precisionOf(ind));
      items.push({ label: `Add alert on ${indTitle(ind)} at ${vs}`, icon: "⏰",
        action: () => sideApi()?.newAlert({ symbol: sym, price: v, ind: { id: ind.id, title: indTitle(ind), j: 0 } }) });
    }
    items.push("-",
      { label: `${above ? "Sell" : "Buy"} 1${FNO_RE.test(sym) ? " lot" : ""} ${sym} @ ${px} limit`, keys: above ? "Alt + Shift + S" : "Alt + Shift + B", icon: "⇅", action: () => paperOrder(above ? "sell" : "buy", "limit", t.price) },
      { label: `${above ? "Buy" : "Sell"} 1${FNO_RE.test(sym) ? " lot" : ""} ${sym} @ ${px} stop`, keys: above ? "Alt + Shift + B" : "Alt + Shift + S", icon: "⇅", action: () => paperOrder(above ? "buy" : "sell", "stop", t.price) },
      { label: `Paper trade ${sym} at ${px}…`, keys: "Shift + T", icon: "＋", action: () => sideApi()?.newOrder({ symbol: sym, price: t.price }) },
      { label: `Paper trade ${sym} / its options…`, keys: "Shift + P", icon: "₹", action: () => window.top.LTVTrade?.openTicket({ symbol: sym }) },
      "-",
      { label: `Draw horizontal line at ${px}`, keys: "Alt + H", icon: "—", action: () => drawHLine(t.price) });
  } else {
    for (const ind of indsOnPane(t.pane)) {
      const v = ind.series[0].coordinateToPrice(t.y), vs = fmt(v, precisionOf(ind));
      items.push({ label: `Add alert on ${indTitle(ind)} at ${vs}`, keys: "Alt + A", icon: "⏰",
        action: () => sideApi()?.newAlert({ symbol: sym, price: v, ind: { id: ind.id, title: indTitle(ind), j: 0 } }) });
    }
    if (!items.length) items.push({ label: "No indicator in this pane", disabled: true });
  }
  return items;
}
const indTitle = (ind) => ind.meta?.shorttitle || ind.meta?.title || ind.ref || "Script";
function drawHLine(price) { draw.add("hline", [{ t: bars[bars.length - 1]?.[0] || 0, p: price }]); }
function paperOrder(sideName, type, price) { sideApi()?.addOrder({ symbol: S.symbol, side: sideName, type, qty: 1, price }); }
plusBtn.onclick = (e) => {
  e.stopPropagation();
  const t = plusAt; if (!t) return;
  const r = plusBtn.getBoundingClientRect();
  LTVSettings.openMenu(plusMenuItems(t), r.left - 330, r.top - 6);
  // keep the menu where it was opened; nudge it left of the button when it fits
  const m = document.querySelector(".cs-menu"); if (m) m.style.left = Math.max(4, r.left - m.offsetWidth - 4) + "px";
};
plusBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
chart.subscribeCrosshairMove((p) => {
  const g = geom(), k = p.paneIndex ?? 0;
  if (!p.point || !mainSeries) { xLabel.classList.add("hidden"); if (plusAt) plusAt.live = false; if (!plusBtn.matches(":hover")) plusBtn.classList.add("hidden"); return; }
  const y = p.point.y, top = paneTop(k);
  const price = k === 0 ? mainSeries.coordinateToPrice(y) : null;
  plusAt = { price, pane: k, y, live: true };
  if (k === 0 && price != null && chart.options().crosshair.horzLine.labelVisible !== false) {
    const fs = +CS.fontSize || 12, h = fs + 8;
    xLabel.textContent = mainSeries.priceFormatter().format(price);
    Object.assign(xLabel.style, { left: g.scaleX + "px", width: g.scaleW + "px", top: (y - h / 2) + "px", height: h + "px", lineHeight: h + "px",
      fontSize: fs + "px", background: chart.options().crosshair.horzLine.labelBackgroundColor || "#131722" });
    xLabel.classList.remove("hidden");
  } else xLabel.classList.add("hidden");
  if (!CS.plusButton || (k > 0 && !indsOnPane(k).length)) { plusBtn.classList.add("hidden"); return; }
  plusBtn.classList.remove("hidden");
  // inside the pane, just left of the price-scale label (right scale) or right of it (left scale)
  plusBtn.style.left = (g.side === "left" ? g.leftW + 4 : g.leftW + g.paneW - 24) + "px";
  plusBtn.style.top = (top + y - 10) + "px";
  plusBtn.title = k === 0 ? `Quick actions at ${fmt(price, mainPrecision())}` : "Quick actions";
});
plusBtn.addEventListener("mouseenter", () => plusBtn.classList.remove("hidden"));
// shortcuts use the crosshair price (or the last close)
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.querySelector("dialog[open]")) return;
  const k = e.key.toLowerCase(), t = plusTarget(); if (!t || t.price == null) return;
  const go = (fn) => { e.preventDefault(); e.stopPropagation(); fn(); };
  if (e.altKey && !e.shiftKey && k === "a") go(() => sideApi()?.newAlert({ symbol: S.symbol, price: t.price }));
  else if (e.altKey && !e.shiftKey && k === "h") go(() => drawHLine(t.price));
  else if (e.altKey && e.shiftKey && (k === "s" || e.code === "KeyS")) go(() => paperOrder("sell", t.price >= lastClose() ? "limit" : "stop", t.price));
  else if (e.altKey && e.shiftKey && (k === "b" || e.code === "KeyB")) go(() => paperOrder("buy", t.price <= lastClose() ? "limit" : "stop", t.price));
  else if (!e.altKey && e.shiftKey && k === "t") go(() => sideApi()?.newOrder({ symbol: S.symbol, price: t.price }));
}, true);
function scaleWidth(id) { try { return chart.priceScale(id).width(); } catch { return 0; } }
function geom() {
  const side = scaleSide(), ts = chart.timeScale();
  const leftW = side === "left" ? scaleWidth("left") : 0, paneW = ts.width(), scaleW = scaleWidth(side);
  let pane0 = 0; try { pane0 = chart.panes()[0].getHeight(); } catch { /* */ }
  return { side, leftW, paneW, scaleW, scaleX: side === "left" ? 0 : leftW + paneW, pane0, timeH: ts.height(), H: $("#chart").clientHeight };
}
function fmtCountdown(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60, p2 = (x) => String(x).padStart(2, "0");
  return h ? `${h}:${p2(m)}:${p2(s)}` : `${p2(m)}:${p2(s)}`;
}
let paneSig = "";
// where this chart's local candle cache starts (shown in the sidebar's Data cache panel)
let cacheInfo = null, cacheSrc = "";
function placeOverlays() {
  try { placeOverlaysOnce(); } catch (e) { if (!placeOverlays.err) console.error("overlays:", e); placeOverlays.err = 1; }
  requestAnimationFrame(placeOverlays);
}
function placeOverlaysOnce() {
  const g = geom();
  const put = (el, x, y, w, h) => { el.style.left = x + "px"; el.style.top = y + "px"; if (w != null) el.style.width = w + "px"; if (h != null) el.style.height = h + "px"; };
  put(gearBtn, g.scaleX, g.H - g.timeH, g.scaleW, g.timeH);
  put(alBar, g.scaleX, g.pane0 - 24, g.scaleW);
  put(curLabel, g.scaleX, 2, g.scaleW);
  put(navBar, g.leftW + g.paneW / 2 - 85, g.pane0 - 46);
  // countdown under the last-price label
  const last = bars[bars.length - 1];
  const showCd = RP.mode !== "on" && CS.countdown && CS.symLabel && last && S.tf < 604800 && mainSeries;
  if (showCd) {
    let end = last[0] + S.tf;
    if (S.tf >= 86400) { const d = Math.floor((Date.now() / 1000 + 19800) / 86400); end = d * 86400 - 19800 + 930 * 60; }
    const left = end - Date.now() / 1000, y = mainSeries.priceToCoordinate(last[4]);
    if (left > 0 && left < S.tf + 86400 && y != null && y < g.pane0 - 10) {
      countdown.textContent = fmtCountdown(left);
      countdown.style.background = last[4] >= last[1] ? CS.upColor : CS.downColor;
      put(countdown, g.scaleX, y + 10, g.scaleW);
      countdown.classList.remove("hidden");
    } else countdown.classList.add("hidden");
  } else countdown.classList.add("hidden");
  alBar.querySelector('[data-m="auto"]').classList.toggle("on", !!chart.priceScale(g.side, 0).options().autoScale);
  alBar.querySelector('[data-m="log"]').classList.toggle("on", CS.mode === "log");
  // pane buttons (indicator panes)
  const ps = chart.panes();
  const hs = ps.map((p) => p.getHeight());
  const sig = hs.join(",") + "|" + CS.paneButtons + "|" + g.leftW + "|" + g.paneW;
  if (sig !== paneSig) {
    paneSig = sig;
    document.querySelectorAll(".pane-btns").forEach((x) => x.remove());
    if (CS.paneButtons !== "hidden" && ps.length > 1) {
      let top = 0;
      ps.forEach((p, k) => {
        const box = ov("", "ov pane-btns" + (CS.paneButtons === "hover" ? " ov-hover" : ""));
        box.innerHTML = (k > 1 ? '<button data-a="up" title="Move pane up">↑</button>' : "") +
          (k > 0 && k < ps.length - 1 ? '<button data-a="down" title="Move pane down">↓</button>' : "") +
          `<button data-a="max" title="${maxPane === k ? "Restore pane" : "Maximize pane"}">${maxPane === k ? "⤡" : "⤢"}</button>` +
          (k > 0 ? '<button data-a="del" title="Remove pane">✕</button>' : "");
        put(box, g.leftW + g.paneW - 6 - box.children.length * 24, top + 4);
        box.onclick = (e) => paneAction(k, e.target.closest("button")?.dataset.a);
        top += hs[k] + 1;
      });
    }
  }
  if (plDirty) { plDirty = false; refreshPriceLines(); }
}
let maxPane = null;
function paneAction(k, a) {
  const ps = chart.panes();
  if (!a || !ps[k]) return;
  if (a === "up" || a === "down") { ps[k].moveTo(a === "up" ? k - 1 : k + 1); maxPane = null; layoutPanes(); }
  if (a === "max") {
    if (maxPane === k) { maxPane = null; layoutPanes(); if (ps.length < 2) ps[0].setStretchFactor(1); }
    else { maxPane = k; ps.forEach((p, j) => p.setStretchFactor(j === k ? 1000 : 1)); }
  }
  if (a === "del") for (const ind of [...inds.values()]) if (ind.series[0]?.getPane().paneIndex() === k) removeIndicator(ind.id);
  paneSig = "";
}

// price-scale menu -----------------------------------------------------
function priceMenu() {
  const ps = chart.priceScale(scaleSide(), 0).options();
  const tog = (k) => () => setCS({ [k]: !CS[k] });
  return [
    { label: "Reset price scale", keys: "Alt + R", icon: "⟲", action: resetPriceScale },
    "-",
    { label: "Auto (fits data to screen)", checked: ps.autoScale, action: () => setCS({ autoScale: !ps.autoScale }) },
    { label: "Scale price chart only", checked: CS.scaleMainOnly, action: () => { setCS({ scaleMainOnly: !CS.scaleMainOnly }); resetPriceScale(); } },
    { label: "Invert scale", keys: "Alt + I", checked: CS.invert, action: tog("invert") },
    "-",
    { label: "Regular", checked: CS.mode === "regular", action: () => setCS({ mode: "regular" }) },
    { label: "Percent", keys: "Alt + P", checked: CS.mode === "percent", action: () => setCS({ mode: CS.mode === "percent" ? "regular" : "percent" }) },
    { label: "Indexed to 100", checked: CS.mode === "indexed", action: () => setCS({ mode: CS.mode === "indexed" ? "regular" : "indexed" }) },
    { label: "Logarithmic", keys: "Alt + L", checked: CS.mode === "log", action: () => setCS({ mode: CS.mode === "log" ? "regular" : "log" }) },
    "-",
    { label: CS.placement === "left" ? "Move scale to right" : "Move scale to left", action: () => setCS({ placement: CS.placement === "left" ? "right" : "left" }) },
    "-",
    { label: "Labels", sub: [
      { label: "Symbol name label", checked: CS.symName, action: tog("symName") },
      { label: "Symbol last price label", checked: CS.symLabel, action: tog("symLabel") },
      { label: "Symbol previous day close price label", checked: CS.prevLabel, action: tog("prevLabel") },
      { label: "High and low price labels", checked: CS.hlLabel, action: tog("hlLabel") },
      { label: "Indicators and financials name labels", checked: CS.indName, action: tog("indName") },
      { label: "Indicators and financials value labels", checked: CS.indValue, action: tog("indValue") },
      { label: "Countdown to bar close", checked: CS.countdown, action: tog("countdown") },
      "-",
      { label: "No overlapping labels", checked: CS.noOverlap, action: tog("noOverlap") }] },
    { label: "Lines", sub: [
      { label: "Price line", checked: CS.symLine, action: tog("symLine") },
      { label: "Previous day close price line", checked: CS.prevLine, action: tog("prevLine") },
      { label: "High and low price lines", checked: CS.hlLine, action: tog("hlLine") }] },
    { label: "Plus button", checked: CS.plusButton, action: tog("plusButton") },
    "-",
    { label: "Session", sub: [
      { label: "Regular trading hours", checked: CS.session !== "extended", action: () => setCS({ session: "regular" }) },
      { label: "Extended trading hours", checked: CS.session === "extended", action: () => setCS({ session: "extended" }) }] },
    "-",
    { label: "More settings…", icon: "⚙", action: () => openChartSettings("scales") },
  ];
}
function openChartSettings(tab = "symbol") {
  LTVSettings.openDialog({ cs: CS, colorOf: csColor, onChange: setCS, tab });
}
$("#chart").addEventListener("contextmenu", (e) => {
  if (e.defaultPrevented) return;
  const g = geom(), b = $("#chart").getBoundingClientRect(), x = e.clientX - b.left, y = e.clientY - b.top;
  e.preventDefault();
  if (x >= g.scaleX && x <= g.scaleX + g.scaleW && y < g.pane0) LTVSettings.openMenu(priceMenu(), e.clientX, e.clientY);
  else LTVSettings.openMenu([
    { label: "Reset chart view", keys: "Alt + R", icon: "⟲", action: resetChartView },
    "-",
    { label: "Remove drawings", action: () => draw.removeAll() },
    "-",
    { label: "Settings…", icon: "⚙", action: () => openChartSettings() }], e.clientX, e.clientY);
});
document.addEventListener("keydown", (e) => {
  if (!e.altKey || e.ctrlKey || e.shiftKey || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.querySelector("dialog[open]")) return;
  const k = e.key.toLowerCase();
  if (k === "r") { e.preventDefault(); resetChartView(); }
  if (k === "i") { e.preventDefault(); setCS({ invert: !CS.invert }); }
  if (k === "p") { e.preventDefault(); setCS({ mode: CS.mode === "percent" ? "regular" : "percent" }); }
  if (k === "l") { e.preventDefault(); setCS({ mode: CS.mode === "log" ? "regular" : "log" }); }
});
$("#chartSetBtn").onclick = () => (A() === LOCAL ? openChartSettings() : LTVSettings.openDialog(A().settingsArgs()));
setInterval(() => { if (CS.marketStatus && !hovering) showMainLegend(bars.length - 1); }, 30000);

// ------------------------------------------------------------------ bar replay
const rpBtn = document.createElement("button");
rpBtn.id = "replayBtn"; rpBtn.title = "Bar replay"; rpBtn.innerHTML = RP_ICON + "<span>Replay</span>";
$("#editorBtn").after(rpBtn);
const rpSel = ov("rpSel", "rp-sel hidden", '<div class="rp-fade"></div><div class="rp-line"><span class="rp-cut">✂</span></div><div class="rp-tlabel"></div>');
const rpBar = ov("rpBar", "rp-bar hidden", `
  <button data-a="select" class="rp-select" title="Select a new starting point">${'<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M5 4v16M19 12H9m4-4-4 4 4 4"/></svg>'}<span>Select bar</span></button>
  <button data-a="selmenu" class="rp-caret" title="More ways to start">▾</button><i></i>
  <button data-a="play" title="Play (Shift + ↓)"></button>
  <button data-a="fwd" title="Forward (Shift + →)"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M6 5l9 7-9 7zM18 5v14"/></svg></button>
  <button data-a="speed" class="rp-txt" title="Replay speed"></button>
  <button data-a="step" class="rp-txt" title="Update interval"></button><i></i>
  <button data-a="live" title="Jump to real-time"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 5l8 7-8 7zM12 5l8 7-8 7zM21 5v14"/></svg></button>
  <span class="spacer"></span>
  <button data-a="close" class="rp-close" title="Exit replay mode">✕</button>`);
const PLAY_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M7 5l12 7-12 7z"/></svg>';
const PAUSE_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';
const tfLabel = (sec) => TFS.find((x) => x[1] === sec)?.[0] || `${sec / 60}m`;
function fmtRpTime(t) {
  const d = new Date((t + TZ) * 1000), p2 = (x) => String(x).padStart(2, "0");
  const day = d.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", timeZone: "UTC" }).replace(",", "");
  return `${day} '${String(d.getUTCFullYear()).slice(2)}` + (S.tf < 86400 ? `  ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}` : "");
}
function rpRender() {
  const on = RP.mode === "on", sel = RP.mode === "select";
  if (EMBED) renderTop(); else rpBtn.classList.toggle("on", !!A().RP.mode);
  rpBar.classList.toggle("hidden", !RP.mode);
  rpSel.classList.toggle("hidden", !sel);
  document.body.classList.toggle("rp-selecting", sel);
  rpBar.querySelector('[data-a="select"]').classList.toggle("on", sel);
  rpBar.querySelector('[data-a="play"]').disabled = !on || RP.end;
  rpBar.querySelector('[data-a="fwd"]').disabled = !on || RP.end || RP.playing || RP.busy;
  rpBar.querySelector('[data-a="play"]').innerHTML = RP.playing ? PAUSE_SVG : PLAY_SVG;
  rpBar.querySelector('[data-a="play"]').title = RP.playing ? "Pause (Shift + ↓)" : "Play (Shift + ↓)";
  rpBar.querySelector('[data-a="speed"]').textContent = RP.speed + "x";
  rpBar.querySelector('[data-a="step"]').textContent = tfLabel(Math.min(RP.step || S.tf, S.tf));
  if (!hovering) showMainLegend(bars.length - 1);
}
function rpSelectMode() {
  rpPause();
  RP.mode = "select";
  rpRender();
}
function rpExit(reload = true) {
  const was = RP.mode;
  rpPause();
  Object.assign(RP, { mode: null, t: null, end: false, busy: false });
  rpRender();
  if (reload && was === "on") { status("Leaving replay…"); loadSymbol(false); }
}
// start replay so that the first hidden bar is the one starting at t
function rpStart(t) {
  if (!bars.length) return;
  RP.view = chart.timeScale().getVisibleLogicalRange();
  rpPause();
  RP.mode = "on"; RP.end = false; RP.busy = true; RP.t = t;
  if (!RP.step || RP.step > S.tf) RP.step = S.tf;
  rpRender();
  chartLoading(true, "Starting replay…");
  for (const ind of inds.values()) setIndPending(ind, true);
  send({ op: "replay_start", t, step: RP.step });
}
function rpOnHistory(info) {
  Object.assign(RP, { mode: "on", t: info.t, step: info.step, end: info.end, busy: false });
  rpRender();
}
function rpForward() {
  if (RP.mode !== "on" || RP.busy || RP.end) return;
  RP.busy = true; RP.sent = performance.now();
  send({ op: "replay_step", n: 1 });
  rpRender();
}
function rpOnStep(m) {
  RP.busy = false; RP.t = m.t; RP.end = m.end;
  if (m.end) { rpPause(); status("Replay finished: no more bars. Jump to real-time to go live.", "live"); }
  if (RP.playing) {
    const wait = Math.max(0, 1000 / RP.speed - (performance.now() - RP.sent));
    RP.timer = setTimeout(() => { RP.timer = null; if (RP.playing) rpForward(); }, wait);
  }
  rpRender();
}
function rpPlay() {
  if (RP.mode !== "on" || RP.end) return;
  RP.playing = true; rpRender();
  if (!RP.busy) rpForward();
}
function rpPause() { RP.playing = false; clearTimeout(RP.timer); RP.timer = null; }
function rpMenuUp(items, btn) {
  const r = btn.getBoundingClientRect();
  LTVSettings.openMenu(items, r.left, r.top);
  const m = document.querySelector(".cs-menu");
  if (m) m.style.top = Math.max(4, r.top - m.offsetHeight - 6) + "px";
}
function rpPickDate() {
  const d = document.createElement("dialog");
  d.className = "rp-date";
  const last = bars[bars.length - 1], first = bars[0];
  const iso = (t) => new Date((t + TZ) * 1000).toISOString().slice(0, 16);
  d.innerHTML = `<form method="dialog" class="dlg"><div class="dlg-head"><b>Select date</b><button value="cancel">✕</button></div>
    <label>Start replay from <input type="${S.tf < 86400 ? "datetime-local" : "date"}" name="d"></label>
    <div class="dlg-foot"><span class="spacer"></span><button value="cancel">Cancel</button><button value="ok" class="primary">Go to</button></div></form>`;
  document.body.appendChild(d);
  const inp = d.querySelector("input");
  inp.min = S.tf < 86400 ? iso(first[0]) : iso(first[0]).slice(0, 10);
  inp.max = S.tf < 86400 ? iso(last[0]) : iso(last[0]).slice(0, 10);
  inp.value = inp.max;
  d.onclose = () => {
    if (d.returnValue === "ok" && inp.value) {
      const t = Date.parse(inp.value + (S.tf < 86400 ? ":00Z" : "T00:00:00Z")) / 1000 - TZ;
      let i = bars.findIndex((b) => b[0] >= t); if (i < 1) i = i < 0 ? bars.length - 1 : 1;
      rpStart(bars[i][0]);
    }
    d.remove();
  };
  d.showModal();
}
const rpToggle = () => (RP.mode ? rpExit() : rpSelectMode());
rpBtn.onclick = () => (A() === LOCAL ? rpToggle() : A().toggleReplay());
rpBar.onclick = (e) => {
  const b = e.target.closest("button"); if (!b || b.disabled) return;
  const a = b.dataset.a;
  if (a === "select") RP.mode === "select" ? (RP.mode = RP.t ? "on" : null, rpRender()) : rpSelectMode();
  if (a === "selmenu") rpMenuUp([
    { label: "Select bar", action: rpSelectMode },
    { label: "Select date…", action: rpPickDate },
    { label: "Select first available date", action: () => bars.length > 1 && rpStart(bars[1][0]) },
    { label: "Random bar", action: () => bars.length > 20 && rpStart(bars[10 + Math.floor(Math.random() * (bars.length - 20))][0]) }], b);
  if (a === "play") RP.playing ? rpPause() : rpPlay();
  if (a === "fwd") rpForward();
  if (a === "speed") rpMenuUp(RP_SPEEDS.map((x) => ({ label: x + "x", checked: RP.speed === x, action: () => { RP.speed = x; S.rpSpeed = x; save(); rpRender(); } })), b);
  if (a === "step") rpMenuUp(TFS.filter(([, sec]) => sec <= S.tf).map(([lab, sec]) => ({ label: lab, checked: (RP.step || S.tf) === sec,
    action: () => { RP.step = sec; rpRender(); if (RP.mode === "on" && RP.t) { rpPause(); RP.busy = true; chartLoading(true, "Updating replay…"); send({ op: "replay_start", t: RP.t, step: sec }); } } })), b);
  if (a === "live" || a === "close") rpExit();
  rpRender();
};
// select-bar mode: a blue cut line follows the mouse, bars to the right of it fade out
function rpSelX(clientX) {
  const box = $("#chart").getBoundingClientRect(), g = geom();
  const x = clientX - box.left - g.leftW;
  if (x < 0 || x > g.paneW || !bars.length) return null;
  const li = Math.round(chart.timeScale().coordinateToLogical(x));
  const i = Math.max(1, Math.min(bars.length - 1, li));
  return { i, x: chart.timeScale().logicalToCoordinate(i) + g.leftW, g };
}
function rpSelMove(e) {
  const r = rpSelX(e.clientX);
  if (!r) return;
  const { x, g } = r, h = g.H - g.timeH;
  const line = rpSel.querySelector(".rp-line"), fade = rpSel.querySelector(".rp-fade"), lab = rpSel.querySelector(".rp-tlabel");
  line.style.left = x + "px"; line.style.height = g.H + "px";
  rpSel.querySelector(".rp-cut").style.top = Math.min(h - 12, e.clientY - $("#chart").getBoundingClientRect().top) + "px";
  fade.style.left = x + "px"; fade.style.width = Math.max(0, g.leftW + g.paneW - x) + "px"; fade.style.height = h + "px";
  fade.style.background = hexA(csColor("bg"), 0.72);
  lab.textContent = "Re: " + fmtRpTime(bars[r.i][0]);
  lab.style.top = h + "px"; lab.style.height = g.timeH + "px";
  lab.style.left = Math.max(g.leftW, Math.min(x - lab.offsetWidth / 2, g.leftW + g.paneW - lab.offsetWidth)) + "px";
}
$("#chartWrap").addEventListener("pointermove", (e) => { if (RP.mode === "select") rpSelMove(e); }, true);
$("#chartWrap").addEventListener("pointerdown", (e) => {
  if (RP.mode !== "select" || e.button !== 0 || e.target.closest("#rpBar, .ov:not(#rpSel)")) return;
  const r = rpSelX(e.clientX);
  if (!r) return;
  e.preventDefault(); e.stopPropagation();
  rpStart(bars[r.i][0]);
}, true);
document.addEventListener("keydown", (e) => {
  if (!RP.mode || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.querySelector("dialog[open]")) return;
  if (e.key === "Escape" && RP.mode === "select") { RP.mode = RP.t ? "on" : null; rpRender(); }
  if (!e.shiftKey || RP.mode !== "on") return;
  if (e.key === "ArrowRight") { e.preventDefault(); e.stopPropagation(); rpForward(); }
  if (e.key === "ArrowDown") { e.preventDefault(); e.stopPropagation(); RP.playing ? rpPause() : rpPlay(); }
}, true);
RP.speed = RP_SPEEDS.includes(S.rpSpeed) ? S.rpSpeed : 1;

// ------------------------------------------------------------------ layout sync (crosshair, time, date range)
const hostL = () => (EMBED ? window.parent?.LTVLayout : window.LTVLayout);
let applyingSync = 0;
function timeAt(x) {                // logical index -> UTC time (extrapolated past both ends)
  const n = bars.length;
  if (!n) return null;
  if (x >= n - 1) return bars[n - 1][0] + (x - (n - 1)) * S.tf;
  if (x <= 0) return bars[0][0] + x * S.tf;
  const i = Math.floor(x), f = x - i;
  return bars[i][0] + f * (bars[i + 1][0] - bars[i][0]);
}
function logicalAt(t) {             // UTC time -> logical index
  const n = bars.length;
  if (!n) return null;
  if (t >= bars[n - 1][0]) return n - 1 + (t - bars[n - 1][0]) / S.tf;
  if (t <= bars[0][0]) return (t - bars[0][0]) / S.tf;
  let lo = 0, hi = n - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (bars[m][0] <= t) lo = m; else hi = m - 1; }
  return lo + (t - bars[lo][0]) / (bars[lo + 1][0] - bars[lo][0]);
}
function syncCrosshair(t, price) {
  if (!mainSeries) return;
  applyingSync++;
  try {
    if (t == null || !bars.length) chart.clearCrosshairPosition();
    else {
      const i = Math.min(bars.length - 1, Math.max(0, Math.floor(logicalAt(t) + 1e-9)));
      chart.setCrosshairPosition(price ?? bars[i][4], bars[i][0] + TZ, mainSeries);
    }
  } catch { /* outside data */ }
  applyingSync--;
}
function syncRange(from, to, both) {
  if (!bars.length) return;
  const ts = chart.timeScale(), r = ts.getVisibleLogicalRange();
  if (!r) return;
  const b = logicalAt(to), a = both ? logicalAt(from) : b - (r.to - r.from);
  if (Math.abs(a - r.from) < 0.01 && Math.abs(b - r.to) < 0.01) return;
  applyingSync++;
  ts.setVisibleLogicalRange({ from: a, to: b });
  requestAnimationFrame(() => applyingSync--);
}
chart.subscribeCrosshairMove((p) => {
  if (applyingSync || !hostL()?.sync) return;
  if (!p.point || p.time == null) { hostL().crosshair(SLOT, null); return; }
  const price = mainSeries ? mainSeries.coordinateToPrice(p.point.y) : null;
  hostL().crosshair(SLOT, p.time - TZ, price);
});
chart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
  if (applyingSync || !r || !bars.length || !hostL()?.sync) return;
  hostL().range(SLOT, timeAt(r.from), timeAt(r.to));
});

// ------------------------------------------------------------------ boot
makeMain();
applyChartSettings();
requestAnimationFrame(placeOverlays);
// Fixed range / anchored volume profiles are computed on the server (1m intrabars when available)
const vpCache = new Map(), vpPending = new Set(), vpLast = new Map();
function vpData(d) {
  if (!bars.length || d.pts.length < 2) return null;
  const v = d.style.vp || {}, lastT = bars[bars.length - 1][0];
  let t1 = Math.min(d.pts[0].t, d.pts[1].t), t2 = Math.max(d.pts[0].t, d.pts[1].t);
  const live = t2 >= lastT;
  const key = [S.symbol, S.tf, t1, t2, v.layout || "Number of Rows", v.rows || 24, v.va || 70, v.use_ib !== false, live ? lastT : 0].join("|");
  const hit = vpCache.get(key);
  if (hit !== undefined) { vpLast.set(d.id, hit); return hit; }
  if (!vpPending.has(key)) {
    vpPending.add(key);
    send({ op: "vprofile", key, t1, t2, layout: v.layout || "Number of Rows", rows: v.rows || 24, va: v.va || 70, use_ib: v.use_ib !== false });
  }
  return vpLast.get(d.id) || null;                    // previous result while the new one loads (no flicker)
}
// Visible Range VP: profile of the bars on screen, requested (debounced) when the visible range changes
let vrTimer = null, vrWant = null;
function vpRange(spec, t1, t2) {
  if (!bars.length) return null;
  const lastT = bars[bars.length - 1][0], live = t2 >= lastT;
  const o = { layout: spec.layout || "Number of Rows", rows: spec.rows || 24, va: spec.va || 70, use_ib: spec.use_ib !== false };
  const key = ["vr", S.symbol, S.tf, t1, t2, o.layout, o.rows, o.va, o.use_ib, live ? lastT : 0].join("|");
  const hit = vpCache.get(key);
  if (hit !== undefined) { vpLast.set("vr", hit); return hit; }
  if (!vpPending.has(key) && vrWant !== key) {
    vrWant = key;
    clearTimeout(vrTimer);
    vrTimer = setTimeout(() => { vpPending.add(key); send({ op: "vprofile", kind: "vrvp", key, t1, t2, ...o }); }, 250);
  }
  return vpLast.get("vr") || null;
}
function onVProfile(m) {
  vpPending.delete(m.key);
  if (vpCache.size > 300) vpCache.clear();
  vpCache.set(m.key, m.profile || null);
  draw?.redraw();
  zones?.dirty();
}
const draw = LTVDraw.init({ chart, el: $("#chart"), series: () => mainSeries, bars: () => bars, tf: () => S.tf, vpData,
  leftOffset: () => (scaleSide() === "left" ? scaleWidth("left") : 0),
  toolbar: !EMBED, onToolbar: () => EMBED && window.parent?.LTVLayout?.toolbarChanged(SLOT),
  onHideIndicators: (on) => { hideInds = on; for (const ind of inds.values()) applyVisibility(ind); },
  onRemoveIndicators: async () => { if (inds.size && await LTVSettings.confirm(`Remove all ${inds.size} indicators?`, { title: "Remove indicators", ok: "Remove", danger: true })) [...inds.keys()].forEach(removeIndicator); } });
zones = LTVZones.init({ chart, el: $("#chart"), series: () => mainSeries, bars: () => bars, tf: () => S.tf,
  leftOffset: () => (scaleSide() === "left" ? scaleWidth("left") : 0), objects: indObjects, vpRange,
  fmtTime: (t) => new Date((t + TZ) * 1000).toISOString().slice(0, 16).replace("T", " "),
  fmtPrice: (x) => (x == null ? "–" : (+x).toFixed(mainPrecision())) });
// API the layout host (top window) uses to drive this chart
const LOCAL = {
  slot: SLOT, get S() { return S; }, CS, RP, chart,
  get draw() { return draw; },
  setSymbol(sym) { S.symbol = canon(sym); loadSymbol(); },
  setTf(sec) { if (S.tf !== sec) { S.tf = sec; S.range = null; loadSymbol(); paintRangeBar(); } },
  setRange: (k) => setRange(k), gotoDate: () => gotoDateDialog(), setCS: (n) => setCS(n),
  get range() { return { key: rangeJob?.key || S.range || null, loading: !!rangeJob }; },
  get tzOffset() { return TZ; },
  setChartType(t) { S.chartType = t; save(); makeMain(); renderTop(); },
  setSource(src) { setSource(src); },
  setTheme(th) { S.theme = th; save(); applyTheme(); makeMain(); },
  addIndicator: (x) => addIndicator(x),
  toggleEditor() { $("#editorBtn").onclick(); },
  settingsArgs: (tab) => ({ cs: CS, colorOf: csColor, onChange: setCS, tab }),
  toggleReplay: () => rpToggle(),
  syncCrosshair, syncRange, renderTop,
  save: () => save(),
  get bars() { return bars; },
  get tz() { return TZ; },
  get cache() { return cacheInfo ? { ...cacheInfo, source: cacheSrc } : null; },
  paintAlertLines: () => paintAlertLines(),
  paintTradeLines: () => paintTradeLines(),
  indList: () => [...inds.values()].map((i) => ({ id: i.id, title: i.meta?.title || i.ref || "Script", visible: i.visible, error: i.error })),
  toggleInd(id) { const i = inds.get(id); if (i) { i.visible = !i.visible; applyVisibility(i); renderIndLegend(); save(); } },
  removeInd: (id) => removeIndicator(id),
  indValue(id, j = 0) { const i = inds.get(id); return i ? lastValue(i, j) : null; },
  dataRows(p) {   // Data window: values under the crosshair (last bar when the mouse is off the chart)
    if (!bars.length) return [];
    let i = bars.length - 1;
    if (p?.time) { const t = p.time - TZ; let lo = 0, hi = bars.length - 1;
      while (lo < hi) { const m = (lo + hi + 1) >> 1; if (bars[m][0] <= t) lo = m; else hi = m - 1; } i = lo; }
    const [t, o, h, l, c, v] = bars[i], pc = i > 0 ? bars[i - 1][4] : o;
    const at = new Date((t + TZ) * 1000).toISOString().replace("T", " ").slice(0, S.tf >= 86400 ? 10 : 16);
    const rows = [{ h: `${S.symbol} · ${TFS.find((x) => x[1] === S.tf)?.[0] || ""}` }, { k: "Date", v: at }, { k: "Open", v: fmt(o) }, { k: "High", v: fmt(h) },
      { k: "Low", v: fmt(l) }, { k: "Close", v: fmt(c) }, { k: "Change", v: `${c - pc >= 0 ? "+" : ""}${fmt(c - pc)} (${fmt((c - pc) / pc * 100)}%)`, c: c >= pc ? css("--up") : css("--down") },
      { k: "Volume", v: fmtVol(v) }];
    for (const ind of inds.values()) {
      if (!ind.visible) continue;
      rows.push({ h: ind.meta?.title || ind.ref || "Script" });
      ind.series.forEach((sr, j) => {
        const d = p?.seriesData?.get(sr);
        const val = p?.time ? (d && d.color !== GAP ? d.value : null) : lastValue(ind, j);
        rows.push({ k: ind.effPlots?.[j]?.title || `Plot ${j + 1}`, v: val == null ? "–" : (ind.lastMsg?.scale ? fmtVol(val) : fmt(val, precisionOf(ind))), c: ind.plotColors[j] });
      });
    }
    return rows;
  },
  csv() {   // OHLCV plus every indicator plot, in the chart's timezone
    const tf = TFS.find((x) => x[1] === S.tf)?.[0] || S.tf;
    const cols = [];
    for (const ind of inds.values()) ind.series.forEach((sr, j) => {
      const m = new Map();
      for (const d of sr.data()) if (d.value != null && d.color !== GAP) m.set(d.time, d.value);
      cols.push([`${ind.meta?.title || ind.ref || "Script"}: ${ind.effPlots?.[j]?.title || "Plot " + (j + 1)}`, m]);
    });
    const q = (x) => (/[",\n]/.test(x) ? `"${x.replace(/"/g, '""')}"` : x);
    const lines = [["time", "open", "high", "low", "close", "volume", ...cols.map((c) => c[0])].map(q).join(",")];
    for (const [t, o, h, l, c, v] of bars) {
      const at = new Date((t + TZ) * 1000).toISOString().replace("T", " ").slice(0, 19);
      lines.push([at, o, h, l, c, v, ...cols.map(([, m]) => m.get(t + TZ) ?? "")].join(","));
    }
    return { name: `${S.symbol.replace(/\W+/g, "_")}_${tf}.csv`, text: lines.join("\n") };
  },
};
window.LTVChart = LOCAL;

// ------------------------------------------------------------------ bottom bar (host): ranges, go to date, clock + timezone, RTH/ETH
if (!EMBED) {
  const bar = $("#rangeBar");
  const CAL = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M8 3v4M16 3v4M9 15h6m-2-2 2 2-2 2"/></svg>';
  bar.innerHTML = `<div class="rb-ranges">${Object.keys(RANGES).map((k) => `<button data-r="${k}" title="${RANGES[k][2]} · ${TFS.find((x) => x[1] === RANGES[k][1])?.[0]} bars">${k}</button>`).join("")}</div>
    <i class="rb-sep"></i><button data-a="goto" class="rb-ico" title="Go to date">${CAL}</button><span class="spacer"></span>
    <button data-a="tz" class="rb-clock" title="Timezone"></button><button data-a="sess" class="rb-sess" title="Trading hours"></button>`;
  const upMenu = (items, btn) => {
    const r = btn.getBoundingClientRect(); LTVSettings.openMenu(items, r.left, r.top);
    const m = document.querySelector(".cs-menu"); if (m) { m.style.top = Math.max(4, r.top - m.offsetHeight - 6) + "px"; m.style.left = Math.max(4, Math.min(r.left, innerWidth - m.offsetWidth - 4)) + "px"; }
  };
  bar.onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const c = A();
    if (b.dataset.r) return c.setRange(b.dataset.r);
    const a = b.dataset.a;
    if (a === "goto") c.gotoDate();
    if (a === "tz") upMenu(LTVSettings.TIMEZONES.map(([v, label]) => ({ label, checked: (c.CS.timezone || "exchange") === v, action: () => c.setCS({ timezone: v }) })), b);
    if (a === "sess") upMenu([
      { label: "Regular trading hours", hint: "RTH", checked: c.CS.session !== "extended", action: () => c.setCS({ session: "regular" }) },
      { label: "Extended trading hours", hint: "ETH", checked: c.CS.session === "extended", action: () => c.setCS({ session: "extended" }) }], b);
  };
  const LOAD = '<span class="ld-bars sm"><i></i><i></i><i></i><i></i></span>';
  const paint = () => {
    const c = A(); if (!c) return;
    const r = c.range || {};
    for (const b of bar.querySelectorAll("[data-r]")) {
      const on = r.key === b.dataset.r;
      b.classList.toggle("on", on); b.classList.toggle("busy", on && r.loading);
      b.innerHTML = on && r.loading ? `${LOAD}${b.dataset.r}` : b.dataset.r;
    }
    const off = c.tzOffset ?? 19800, now = new Date(Date.now() + off * 1000), m = Math.abs(off) / 60;
    bar.querySelector(".rb-clock").textContent = `${now.toISOString().slice(11, 19)} UTC${off >= 0 ? "+" : "−"}${Math.floor(m / 60)}${m % 60 ? ":" + String(m % 60).padStart(2, "0") : ""}`;
    bar.querySelector(".rb-sess").textContent = c.CS?.session === "extended" ? "ETH" : "RTH";
  };
  window.LTVRangeBar = { paint };
  paint(); setInterval(paint, 1000);
}
if (EMBED) {
  const host = () => window.parent?.LTVLayout;
  document.addEventListener("pointerdown", () => host()?.activate(SLOT), true);
  document.addEventListener("keydown", (e) => {        // fullscreen shortcuts also work while a chart frame has focus
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.querySelector("dialog[open]")) return;
    if (e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey && e.code === "KeyF") { e.preventDefault(); host()?.fullscreen("toggle"); }
    else if ((e.ctrlKey || e.metaKey) && e.code === "KeyS") { e.preventDefault(); host()?.saveLayout(); }
    else if (e.key === "Escape") host()?.fullscreen("exit");
  });
} else {
  $("#chartWrap").addEventListener("pointerdown", () => window.LTVLayout?.activate(0), true);
}
const saved = S.indicators;
S.indicators = [];
for (const it of saved) {
  const ind = { ...it, style: it.style || {}, series: [], plotColors: [], lines: [], markers: [], meta: null, error: null, sig: "", visible: it.visible !== false };
  inds.set(ind.id, ind); S.indicators.push(ind);
}
// first run only (nothing saved yet): a couple of defaults. An empty list the user made by removing
// everything is remembered as empty, so reloads never bring the defaults back.
if (!S.indInit) {
  S.indInit = true;
  save();
  if (!HAD_STATE && !saved.length) Promise.all(["builtin:ema", "builtin:rsi"].map((id) => fetch(`/api/scripts/${id}`).then((r) => r.json())))
    .then((list) => list.forEach((s) => addIndicator({ ref: s.id, code: s.code })));
}
renderIndLegend();
renderTfs();
renderWatchlist();
// default source for NSE names without a remembered one: Breeze when its keys exist, else Yahoo
fetch("/api/config").then((r) => r.json()).then((c) => {
  const was = srcFor(S.symbol);
  S.breezeOk = !!c.breeze;
  S.source = c.breeze ? "breeze" : "yf"; save(); bzStatus();
  renderWatchlist(); sendWatch();
  if (srcFor(S.symbol) !== was) loadSymbol();
}).catch(() => {});
// Volume is an indicator now: add it once for existing layouts
if (!S.volInit) {
  S.volInit = true;
  if (![...inds.values()].some((i) => i.ref === "builtin:volume"))
    fetch("/api/scripts/builtin:volume").then((r) => r.json()).then((x) => addIndicator({ ref: x.id, code: x.code })).catch(() => {});
  save();
}
loadCatalogue();
connect();
if (!EMBED) window.LTVApp = { quotes, srcFor, wkey, sendWatch, A: () => A(), each, esc, SRC_NAME, toast, addToWatchlist, canon, TFS,
  get S() { return S; }, pick: (sym) => each("symbol", (c) => c.setSymbol(sym)) };
window.__ltv = { LOCAL, RP, chart, get bars() { return bars; }, inds, draw, CS, setCS, main: () => mainSeries, TZ: () => TZ };
})();
