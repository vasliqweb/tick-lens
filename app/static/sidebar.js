/* Right sidebar (TradingView style): an icon rail that opens one panel at a time next to the chart.
   Watchlist · Alerts · Object tree & Data window · Technicals · Hotlists · Markets · Calendar · News · Notifications · Help */
(() => {
"use strict";
if (+new URLSearchParams(location.search).get("slot") > 0) return;      // embedded charts have no sidebar
const app = window.LTVApp;
if (!app) return;
const $ = (s, r = document) => r.querySelector(s);
const esc = app.esc;
const store = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const keep = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } };
const fmt = (v, p = 2) => (v == null || Number.isNaN(v) ? "–" : Number(v).toLocaleString(undefined, { minimumFractionDigits: p, maximumFractionDigits: p }));
const ago = (t) => { const s = Date.now() / 1000 - t; return s < 60 ? "now" : s < 3600 ? `${Math.floor(s / 60)}m` : s < 86400 ? `${Math.floor(s / 3600)}h` : `${Math.floor(s / 86400)}d`; };
const svg = (d) => `<svg viewBox="0 0 28 28" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const ICONS = {
  watchlist: svg('<path d="M7 5h14v19l-7-4-7 4z"/><path d="M10.5 10h7M10.5 14h7"/>'),
  trades: svg('<path d="M5 22V6M5 22h18"/><path d="M8 17l4-5 3 3 6-7"/><path d="M17 8h4v4"/>'),
  alerts: svg('<circle cx="14" cy="15.5" r="7.5"/><path d="M14 11v5h3.5M5.5 7.5l3-2.5M22.5 7.5l-3-2.5"/>'),
  tree: svg('<path d="M14 5l9 5-9 5-9-5z"/><path d="M5 15l9 5 9-5"/>'),
  cache: svg('<ellipse cx="14" cy="7.5" rx="8" ry="3"/><path d="M6 7.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13"/><path d="M6 14c0 1.7 3.6 3 8 3s8-1.3 8-3"/>'),
  tech: svg('<path d="M14 4.5c.8 5 3.7 8.6 9.5 9.5-5.8.9-8.7 4.5-9.5 9.5-.8-5-3.7-8.6-9.5-9.5 5.8-.9 8.7-4.5 9.5-9.5z"/>'),
  hot: svg('<circle cx="14" cy="14" r="9"/><circle cx="14" cy="14" r="5"/><path d="M14 14l6.5-6.5"/><circle cx="14" cy="14" r="1.2" fill="currentColor"/>'),
  market: svg('<path d="M4 22l7-11 4 5 3-4 6 10z"/><path d="M8 7l3 4 2-2.5"/>'),
  calendar: svg('<rect x="5" y="7" width="18" height="16" rx="2"/><path d="M5 12h18M10 5v4M18 5v4"/>'),
  news: svg('<path d="M6 21.5a.5.5 0 1 0 0 .01M6 15a7 7 0 0 1 7 7M6 9a13 13 0 0 1 13 13"/>'),
  notif: svg('<path d="M8 18v-5a6 6 0 0 1 12 0v5l2 2H6z"/><path d="M12 22a2 2 0 0 0 4 0"/>'),
  help: svg('<circle cx="14" cy="14" r="9"/><path d="M11.5 11.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.7M14 19v.2"/>'),
};
const PANELS = [
  ["watchlist", "Watchlist and details"], ["trades", "Paper trades"], ["alerts", "Alerts"], ["tree", "Object tree and data window"], ["cache", "Data cache"],
  ["tech", "Technicals"], ["hot", "Hotlists"], ["market", "Markets overview"], ["calendar", "Calendar"],
  ["news", "News"], ["notif", "Notifications"], ["help", "Help and shortcuts"],
];
const SHORT = { trades: "Paper trades", tree: "Objects", cache: "Data cache", market: "Markets" };
const TOP = 5;                              // first three sit at the top of the rail, the rest at the bottom

// ------------------------------------------------------------------ rail + panel host
const aside = $("#watchlist");
const wlPane = document.createElement("div");
wlPane.className = "sp-pane"; wlPane.dataset.p = "watchlist";
[...aside.children].filter((c) => c.id !== "wlResize").forEach((c) => wlPane.appendChild(c));
aside.appendChild(wlPane);
const panes = { watchlist: wlPane };
for (const [id, title] of PANELS.slice(1)) {
  const d = document.createElement("div");
  d.className = "sp-pane hidden"; d.dataset.p = id;
  d.innerHTML = `<div class="sp-head"><b>${SHORT[id] || title}</b><span class="sp-tools"></span></div><div class="sp-body"></div>`;
  aside.appendChild(d); panes[id] = d;
}
const rail = document.createElement("nav");
rail.id = "rail";
rail.innerHTML = PANELS.map(([id, title], k) => (k === TOP ? '<div class="rail-gap"></div>' : "") +
  `<button data-p="${id}" title="${title}">${ICONS[id]}<i class="badge hidden"></i></button>`).join("");
aside.after(rail);
const badge = (id, n) => { const b = $(`[data-p="${id}"] .badge`, rail); b.textContent = n > 99 ? "99+" : n; b.classList.toggle("hidden", !n); };

let open = store("ltv.side", { open: "watchlist" }).open;
function show(id) {
  open = id;
  keep("ltv.side", { open });
  aside.classList.toggle("collapsed", !id);
  for (const [k, el] of Object.entries(panes)) el.classList.toggle("hidden", k !== id);
  rail.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.p === id));
  if (typeof paintCacheIcon === "function") try { paintCacheIcon(); } catch { /* chart not ready */ }
  if (id && PANES[id]?.open) PANES[id].open(panes[id]);
  app.sendWatch();                      // panels may need quotes for extra symbols
  window.dispatchEvent(new Event("resize"));
}
rail.onclick = (e) => { const b = e.target.closest("button[data-p]"); if (b) show(open === b.dataset.p ? null : b.dataset.p); };
const body = (id) => $(".sp-body", panes[id]);
const tools = (id) => $(".sp-tools", panes[id]);
const quoteOf = (sym) => app.quotes.get(`${app.srcFor(sym)}:${sym}`);
const activeSym = () => app.A().S.symbol;

// ------------------------------------------------------------------ notifications
let notes = store("ltv.notes", []), unseen = 0;
function notify(text, kind = "info") {
  notes.unshift({ t: Date.now() / 1000, text: String(text).slice(0, 300), kind });
  notes = notes.slice(0, 200); keep("ltv.notes", notes);
  if (open !== "notif") unseen++;
  badge("notif", unseen);
  if (open === "notif") PANES.notif.open(panes.notif);
}

// ------------------------------------------------------------------ alerts
let alerts = store("ltv.alerts", []);
const lastPx = new Map();
const saveAlerts = () => { keep("ltv.alerts", alerts); app.each("all", (c) => c.paintAlertLines?.()); app.sendWatch(); badge("alerts", alerts.filter((a) => a.active).length); };
let audio;
function beep() {
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    const o = audio.createOscillator(), g = audio.createGain();
    o.frequency.value = 880; g.gain.value = 0.08; o.connect(g); g.connect(audio.destination);
    o.start(); o.stop(audio.currentTime + 0.25);
  } catch { /* no audio */ }
}
function checkAlerts(items) {
  for (const q of items) {
    if (q.last == null) continue;
    fillOrders(q);
    for (const a of alerts) {
      if (!a.active || a.ind || `${app.srcFor(a.symbol)}:${a.symbol}` !== q.key) continue;
      testAlert(a, q.last);
    }
  }
}
function testAlert(a, v) {
  {
    {
      const prev = lastPx.get(a.id);
      lastPx.set(a.id, v);
      const hit = a.cond === "above" ? v >= a.price : a.cond === "below" ? v <= a.price
        : prev != null && ((prev < a.price && v >= a.price) || (prev > a.price && v <= a.price));
      if (!hit) return;
      const what = a.ind ? `${a.symbol} ${a.ind.title}` : a.symbol;
      const msg = a.msg || `${what} ${a.cond === "cross" ? "crossed" : a.cond === "above" ? "is above" : "is below"} ${fmt(a.price)} (now ${fmt(v)})`;
      a.triggered = Date.now() / 1000; a.hits = (a.hits || 0) + 1;
      if (a.once) a.active = false;
      if (window.LTVTrade?.stick) window.LTVTrade.stick(`⏰ ${msg}`); else app.toast(`⏰ ${msg}`);
      beep(); notify(`⏰ ${msg}`, "alert");
      try { if (window.Notification?.permission === "granted") new Notification("Alert", { body: msg }); } catch { /* */ }
      saveAlerts();
      if (open === "alerts") PANES.alerts.open(panes.alerts);
    }
  }
}
// indicator alerts: read the indicator's latest value from any chart showing that symbol
setInterval(() => {
  for (const a of alerts) {
    if (!a.active || !a.ind) continue;
    let v = null;
    app.each("all", (c) => { if (v == null && c.S?.symbol === a.symbol) v = c.indValue?.(a.ind.id, a.ind.j || 0); });
    if (v != null && Number.isFinite(v)) testAlert(a, v);
  }
}, 2000);

// ------------------------------------------------------------------ paper orders (no broker is connected: orders are simulated on live quotes)
let orders = store("ltv.orders", []);
const saveOrders = () => { keep("ltv.orders", orders); app.each("all", (c) => c.paintAlertLines?.()); app.sendWatch(); if (open === "alerts") PANES.alerts.open(panes.alerts); };
function addOrder(o) {        // old order tool now places a real paper trade (Trades panel)
  if (window.LTVTrade) return window.LTVTrade.quick({ symbol: o.symbol, side: o.side, type: o.type, price: o.price });
  const ord = { id: "o" + Date.now().toString(36), symbol: app.canon(o.symbol), side: o.side, type: o.type, qty: o.qty || 1,
    price: +(+o.price).toFixed(4), status: "working", created: Date.now() / 1000 };
  if (ord.type === "market") { const last = quoteOf(ord.symbol)?.last ?? app.A().bars?.at(-1)?.[4]; ord.status = "filled"; ord.fill = last; ord.filled = ord.created; }
  orders.unshift(ord); saveOrders();
  const txt = `${ord.side === "buy" ? "Buy" : "Sell"} ${ord.qty} ${ord.symbol} @ ${fmt(ord.price)} ${ord.type}`;
  notify(ord.status === "filled" ? `Paper order filled: ${ord.side} ${ord.qty} ${ord.symbol} @ ${fmt(ord.fill)}` : `Paper order placed: ${txt}`); app.toast(`Paper order · ${txt}`);
}
function fillOrders(q) {
  let changed = false;
  for (const o of orders) {
    if (o.status !== "working" || `${app.srcFor(o.symbol)}:${o.symbol}` !== q.key) continue;
    const up = (o.side === "buy") === (o.type === "stop");     // buy stop / sell limit fill at or above the price
    if (up ? q.last >= o.price : q.last <= o.price) {
      o.status = "filled"; o.fill = q.last; o.filled = Date.now() / 1000; changed = true;
      const msg = `Paper order filled: ${o.side} ${o.qty} ${o.symbol} @ ${fmt(q.last)} (${o.type} ${fmt(o.price)})`;
      if (window.LTVTrade?.stick) window.LTVTrade.stick(`✅ ${msg}`); else app.toast(`✅ ${msg}`);
      beep(); notify(msg, "alert");
    }
  }
  if (changed) saveOrders();
}
function newOrder(o = {}) {
  if (window.LTVTrade) return window.LTVTrade.openTicket(o);
  const sym = o.symbol || activeSym(), last = quoteOf(sym)?.last ?? app.A().bars?.at(-1)?.[4], px = o.price ?? last;
  const d = document.createElement("dialog");
  d.innerHTML = `<form method="dialog" class="dlg tv-login"><div class="dlg-head"><b>Order · ${esc(sym)}</b><button value="cancel">✕</button></div>
    <div class="tvl-body"><p class="muted">Paper trading: orders are simulated on live quotes, nothing is sent to a broker.</p>
    <label class="srow">Side <span class="seg sm ord-side"><button type="button" data-s="buy" class="on">Buy</button><button type="button" data-s="sell">Sell</button></span></label>
    <label class="srow">Type <select name="type"><option value="limit">Limit</option><option value="stop">Stop</option><option value="market">Market</option></select></label>
    <label class="srow">Price <input name="price" type="number" step="any" value="${px != null ? +(+px).toFixed(2) : ""}"></label>
    <label class="srow">Quantity <input name="qty" type="number" min="1" step="1" value="1"></label>
    <div class="dlg-foot"><span class="spacer"></span><button value="cancel">Cancel</button><button value="ok" class="primary">Place order</button></div></div></form>`;
  document.body.appendChild(d);
  const f = d.querySelector("form");
  let sd = px != null && last != null && px > last ? "sell" : "buy";
  const paint = () => d.querySelectorAll(".ord-side button").forEach((b) => b.classList.toggle("on", b.dataset.s === sd));
  d.querySelector(".ord-side").onclick = (e) => { const b = e.target.closest("[data-s]"); if (b) { sd = b.dataset.s; paint(); } };
  paint();
  d.onclose = () => {
    if (d.returnValue === "ok") {
      const price = parseFloat(f.price.value), qty = Math.max(1, parseInt(f.qty.value, 10) || 1);
      if (Number.isFinite(price) || f.type.value === "market") addOrder({ symbol: sym, side: sd, type: f.type.value, qty, price: Number.isFinite(price) ? price : last });
    }
    d.remove();
  };
  d.showModal();
}

// ------------------------------------------------------------------ technicals (computed from the active chart's bars)
const sma = (c, n, i = c.length - 1) => { if (i + 1 < n) return null; let s = 0; for (let k = i - n + 1; k <= i; k++) s += c[k]; return s / n; };
function ema(c, n) { if (c.length < n) return null; const k = 2 / (n + 1); let e = sma(c, n, n - 1); for (let i = n; i < c.length; i++) e = c[i] * k + e * (1 - k); return e; }
function emaSeries(c, n) { const out = []; const k = 2 / (n + 1); let e = null; c.forEach((x, i) => { if (i === n - 1) e = sma(c, n, i); else if (i >= n) e = x * k + e * (1 - k); out.push(e); }); return out; }
function rsi(c, n = 14) {
  if (c.length <= n) return null;
  let g = 0, l = 0;
  for (let i = 1; i <= n; i++) { const d = c[i] - c[i - 1]; if (d > 0) g += d; else l -= d; }
  g /= n; l /= n;
  for (let i = n + 1; i < c.length; i++) { const d = c[i] - c[i - 1]; g = (g * (n - 1) + Math.max(d, 0)) / n; l = (l * (n - 1) + Math.max(-d, 0)) / n; }
  return l === 0 ? 100 : 100 - 100 / (1 + g / l);
}
function technicals(bars) {
  const c = bars.map((b) => b[4]), h = bars.map((b) => b[2]), l = bars.map((b) => b[3]), last = c[c.length - 1];
  const sig = (v) => (v > 0 ? 1 : v < 0 ? -1 : 0);
  const osc = [], mas = [];
  const r = rsi(c); if (r != null) osc.push(["RSI (14)", r, r < 30 ? 1 : r > 70 ? -1 : 0]);
  const hh = Math.max(...h.slice(-14)), ll = Math.min(...l.slice(-14));
  if (c.length >= 14 && hh > ll) { const k = (last - ll) / (hh - ll) * 100; osc.push(["Stochastic %K (14)", k, k < 20 ? 1 : k > 80 ? -1 : 0]);
    const w = -100 * (hh - last) / (hh - ll); osc.push(["Williams %R (14)", w, w < -80 ? 1 : w > -20 ? -1 : 0]); }
  if (c.length >= 20) { const tp = bars.slice(-20).map((b) => (b[2] + b[3] + b[4]) / 3), m = tp.reduce((a, b) => a + b) / 20,
    md = tp.reduce((a, b) => a + Math.abs(b - m), 0) / 20, cci = md ? (tp[19] - m) / (0.015 * md) : 0; osc.push(["CCI (20)", cci, cci < -100 ? 1 : cci > 100 ? -1 : 0]); }
  if (c.length >= 35) { const e12 = emaSeries(c, 12), e26 = emaSeries(c, 26), macd = e12.map((x, i) => (x != null && e26[i] != null ? x - e26[i] : null)).filter((x) => x != null);
    const sigl = ema(macd, 9), m = macd[macd.length - 1]; if (sigl != null) osc.push(["MACD (12, 26)", m, sig(m - sigl)]); }
  if (c.length > 10) { const mo = last - c[c.length - 11]; osc.push(["Momentum (10)", mo, sig(mo)]); }
  for (const n of [10, 20, 30, 50, 100, 200]) {
    const s = sma(c, n), e = ema(c, n);
    if (e != null) mas.push([`EMA (${n})`, e, sig(last - e)]);
    if (s != null) mas.push([`SMA (${n})`, s, sig(last - s)]);
  }
  const score = (rows) => (rows.length ? rows.reduce((a, r) => a + r[2], 0) / rows.length : 0);
  return { osc, mas, all: score([...osc, ...mas]), o: score(osc), m: score(mas) };
}
const verdict = (s) => (s > 0.5 ? ["Strong buy", "up"] : s > 0.1 ? ["Buy", "up"] : s < -0.5 ? ["Strong sell", "dn"] : s < -0.1 ? ["Sell", "dn"] : ["Neutral", ""]);
const gauge = (s, label) => { const [v, cls] = verdict(s), deg = s * 90;
  return `<div class="gauge"><svg viewBox="0 0 120 70" width="120" height="70"><path d="M10 60a50 50 0 0 1 100 0" stroke="var(--border)" stroke-width="8" fill="none"/>
  <path d="M10 60a50 50 0 0 1 25-43" stroke="var(--down)" stroke-width="8" fill="none"/><path d="M85 17a50 50 0 0 1 25 43" stroke="var(--up)" stroke-width="8" fill="none"/>
  <line x1="60" y1="60" x2="60" y2="18" stroke="var(--text)" stroke-width="2.5" transform="rotate(${deg} 60 60)"/></svg><small>${label}</small><b class="${cls}">${v}</b></div>`; };

// ------------------------------------------------------------------ panels
const MARKETS = [["NIFTY", "Nifty 50"], ["BANKNIFTY", "Bank Nifty"], ["FINNIFTY", "Fin Nifty"], ["SENSEX", "Sensex"], ["NSE:INDIAVIX", "India VIX"],
  ["FX_IDC:USDINR", "USD/INR"], ["MCX:GOLD1!", "Gold (MCX)"], ["MCX:SILVER1!", "Silver (MCX)"], ["MCX:CRUDEOIL1!", "Crude oil (MCX)"],
  ["SP:SPX", "S&P 500"], ["DJ:DJI", "Dow Jones"], ["NASDAQ:NDX", "Nasdaq 100"], ["TVC:NI225", "Nikkei 225"], ["BITSTAMP:BTCUSD", "Bitcoin"]];
let hotTab = "gain", treeTab = "tree", newsCache = { q: "", items: [], at: 0 }, newsSeen = store("ltv.newsSeen", 0);
const quoteRow = (sym, label = sym) => {
  const q = quoteOf(sym) || {};
  const cls = q.chg == null ? "" : q.chg >= 0 ? "up" : "dn";
  return `<div class="sp-row q" data-sym="${esc(sym)}" title="${esc(sym)}"><span class="nm">${esc(label)}</span><span>${fmt(q.last)}</span>` +
    `<span class="${cls}">${q.pct == null ? "–" : (q.pct >= 0 ? "+" : "") + fmt(q.pct) + "%"}</span></div>`;
};
const clickRows = (el) => { el.onclick = (e) => { const r = e.target.closest("[data-sym]"); if (r) app.pick(r.dataset.sym); }; };

const PANES = {
  trades: { open() { window.LTVTrade?.render(); } },
  alerts: {
    open(p) {
      tools("alerts").innerHTML = '<button data-a="new" title="Create alert">＋</button>';
      tools("alerts").onclick = () => newAlert();
      const b = body("alerts");
      b.innerHTML = alerts.length ? alerts.map((a) => `<div class="sp-alert ${a.active ? "" : "off"}" data-id="${a.id}">
        <div><b>${esc(a.symbol)}</b> ${a.ind ? `<small>${esc(a.ind.title)}</small> ` : ""}<small>${a.cond === "cross" ? "Crossing" : a.cond === "above" ? "Greater than" : "Less than"} ${fmt(a.price)}</small>
        <div class="muted">${a.active ? "Active" : a.triggered ? `Triggered ${ago(a.triggered)} ago` : "Stopped"}${a.once ? " · once" : " · every time"}${a.msg ? " · " + esc(a.msg) : ""}</div></div>
        <span class="sp-acts"><button data-a="tog" title="${a.active ? "Stop" : "Restart"}">${a.active ? "⏸" : "▶"}</button><button data-a="del" title="Delete">✕</button></span></div>`).join("")
        : '<p class="muted sp-empty">No alerts. Use ＋ (or the chart\'s crosshair ＋) to set an alert.</p>';
      if (orders.length) b.innerHTML += '<div class="sp-sec">Paper orders</div>' + orders.slice(0, 50).map((o) => `<div class="sp-alert ${o.status === "working" ? "" : "off"}" data-oid="${o.id}">
        <div><b class="${o.side === "buy" ? "up" : "dn"}">${o.side === "buy" ? "Buy" : "Sell"} ${o.qty}</b> <b>${esc(o.symbol)}</b> <small>${o.type} ${fmt(o.price)}</small>
        <div class="muted">${o.status === "filled" ? `Filled @ ${fmt(o.fill)} · ${ago(o.filled)} ago` : o.status === "cancelled" ? "Cancelled" : "Working"}</div></div>
        <span class="sp-acts"><button data-a="del" title="${o.status === "working" ? "Cancel" : "Remove"}">✕</button></span></div>`).join("");
      b.onclick = (e) => {
        const orow = e.target.closest("[data-oid]");
        if (orow) {
          const o = orders.find((x) => x.id === orow.dataset.oid);
          if (e.target.closest('[data-a="del"]')) { if (o.status === "working") o.status = "cancelled"; else orders = orders.filter((x) => x !== o); saveOrders(); }
          else app.pick(o.symbol);
          return;
        }
        const row = e.target.closest("[data-id]"); if (!row) return;
        const a = alerts.find((x) => x.id === row.dataset.id); const act = e.target.closest("[data-a]")?.dataset.a;
        if (act === "del") alerts = alerts.filter((x) => x !== a);
        else if (act === "tog") { a.active = !a.active; lastPx.delete(a.id); }
        else { app.pick(a.symbol); return; }
        saveAlerts(); this.open(p);
      };
    },
  },
  tree: {
    open(p) {
      tools("tree").innerHTML = `<span class="seg sm"><button data-t="tree" class="${treeTab === "tree" ? "on" : ""}">Object tree</button><button data-t="data" class="${treeTab === "data" ? "on" : ""}">Data window</button></span>`;
      tools("tree").onclick = (e) => { const t = e.target.closest("[data-t]"); if (t) { treeTab = t.dataset.t; this.open(p); } };
      treeTab === "tree" ? this.tree() : this.data();
    },
    tree() {
      const c = app.A(), b = body("tree"), items = c.draw?.items || [];
      b.innerHTML = `<div class="sp-sec">${esc(c.S.symbol)} · chart</div>` +
        c.indList().map((i) => `<div class="sp-row obj" data-id="${i.id}"><span class="nm">${esc(i.title)}${i.error ? ' <small class="dn">error</small>' : ""}</span>
          <span class="sp-acts"><button data-a="vis" title="${i.visible ? "Hide" : "Show"}">${i.visible ? "👁" : "◌"}</button><button data-a="del" title="Remove">✕</button></span></div>`).join("") +
        `<div class="sp-sec">Drawings (${items.length})</div>` +
        items.slice(0, 200).map((d) => `<div class="sp-row obj"><span class="nm">${esc(String(d.type).replace(/([a-z])([A-Z])/g, "$1 $2"))}</span></div>`).join("") +
        `<div class="sp-foot"><button data-a="drawtree">Manage drawings…</button></div>`;
      b.onclick = (e) => {
        const a = e.target.closest("[data-a]")?.dataset.a, id = e.target.closest("[data-id]")?.dataset.id;
        if (a === "vis") c.toggleInd(id); else if (a === "del") c.removeInd(id); else if (a === "drawtree") c.draw?.ctl?.openTree?.();
        if (a) setTimeout(() => this.tree(), 50);
      };
    },
    data() {
      const paint = (pp) => {
        if (open !== "tree" || treeTab !== "data") return;
        body("tree").innerHTML = app.A().dataRows(pp).map((r) => r.h ? `<div class="sp-sec">${esc(r.h)}</div>`
          : `<div class="sp-row dw"><span class="muted">${esc(r.k)}</span><span style="${r.c ? `color:${r.c}` : ""}">${esc(r.v)}</span></div>`).join("");
      };
      const c = app.A();
      if (this.sub !== c) {
        this.sub?.chart.unsubscribeCrosshairMove(this.fn);
        this.fn = (pp) => paint(pp.time ? pp : null);
        c.chart.subscribeCrosshairMove(this.fn); this.sub = c;
      }
      paint(null);
    },
  },
  tech: {
    open() {
      const c = app.A(), bars = c.bars || [];
      if (bars.length < 30) { body("tech").innerHTML = '<p class="muted sp-empty">Not enough bars on the chart yet.</p>'; return; }
      const t = technicals(bars), tf = app.TFS.find((x) => x[1] === c.S.tf)?.[0] || "";
      const rows = (list) => list.map(([n, v, s]) => `<div class="sp-row dw"><span>${esc(n)}</span><span>${fmt(v)}</span><span class="${s > 0 ? "up" : s < 0 ? "dn" : "muted"}">${s > 0 ? "Buy" : s < 0 ? "Sell" : "Neutral"}</span></div>`).join("");
      body("tech").innerHTML = `<div class="sp-sec">${esc(c.S.symbol)} · ${tf} · from the chart's bars</div>
        <div class="gauges">${gauge(t.o, "Oscillators")}${gauge(t.all, "Summary")}${gauge(t.m, "Moving averages")}</div>
        <div class="sp-sec">Oscillators</div>${rows(t.osc)}<div class="sp-sec">Moving averages</div>${rows(t.mas)}`;
    },
  },
  hot: {
    syms: () => [...new Set(app.S.watchlists.flatMap((l) => l.items))],
    open() {
      tools("hot").innerHTML = `<span class="seg sm">${[["gain", "Gainers"], ["lose", "Losers"], ["move", "Movers"]].map(([k, l]) => `<button data-t="${k}" class="${hotTab === k ? "on" : ""}">${l}</button>`).join("")}</span>`;
      tools("hot").onclick = (e) => { const t = e.target.closest("[data-t]"); if (t) { hotTab = t.dataset.t; this.open(); } };
      const list = this.syms().map((s) => [s, quoteOf(s)]).filter(([, q]) => q?.pct != null);
      list.sort((a, b) => (hotTab === "gain" ? b[1].pct - a[1].pct : hotTab === "lose" ? a[1].pct - b[1].pct : Math.abs(b[1].pct) - Math.abs(a[1].pct)));
      const b = body("hot");
      b.innerHTML = '<div class="sp-sec">From all your watchlists</div>' + (list.length ? list.slice(0, 25).map(([s]) => quoteRow(s)).join("") : '<p class="muted sp-empty">Waiting for quotes…</p>');
      clickRows(b);
    },
  },
  market: {
    open() {
      const b = body("market");
      b.innerHTML = MARKETS.map(([s, l]) => quoteRow(s, l)).join("");
      clickRows(b);
    },
  },
  calendar: {
    async open() {
      const b = body("calendar"), now = new Date(), ist = new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60000);
      const mins = ist.getHours() * 60 + ist.getMinutes(), wd = ist.getDay();
      const st = wd === 0 || wd === 6 ? "Closed (weekend)" : mins < 540 ? "Pre-market" : mins < 555 ? "Pre-open session" : mins < 930 ? "Open" : "Closed";
      const head = `<div class="sp-row dw"><span>NSE today</span><b class="${st === "Open" ? "up" : ""}">${st}</b></div><div class="sp-row dw"><span class="muted">Session</span><span>09:15 – 15:30 IST · F&amp;O till 15:40</span></div>`;
      b.innerHTML = head + '<div class="sp-sec">F&amp;O expiries</div><p class="muted sp-empty">Loading…</p>';
      const roots = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"], root = activeSym().split(" ")[0].replace(/^.*:/, "");
      if (!roots.includes(root)) roots.push(root);
      try {
        const r = await fetch(`/api/expiries?roots=${encodeURIComponent(roots.join(","))}`);
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || r.status);
        const days = (s) => Math.round((Date.parse(s) - Date.parse(ist.toISOString().slice(0, 10))) / 86400000);
        b.innerHTML = head + Object.entries(d).filter(([, l]) => l.length).map(([k, l]) => `<div class="sp-sec">${esc(k)} expiries</div>` + l.map((e) =>
          `<div class="sp-row dw"><span>${new Date(e.date).toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short", year: "numeric" })}</span>
          <span class="muted">${[e.fut && "FUT", e.opt && "OPT"].filter(Boolean).join(" · ")}</span><span class="${days(e.date) <= 1 ? "dn" : ""}">${days(e.date) === 0 ? "today" : days(e.date) + "d"}</span></div>`).join("")).join("");
      } catch (e) { b.innerHTML = head + `<div class="sp-sec">F&amp;O expiries</div><p class="muted sp-empty">${esc(e.message)}</p>`; }
    },
  },
  news: {
    async open(force) {
      const b = body("news"), sym = activeSym(), q = /^(NIFTY|BANKNIFTY|FINNIFTY|SENSEX|BANKEX)$/.test(sym) ? `${sym} index` : `${sym.replace(/^.*:/, "").replace(/\d+!$/, "")} stock`;
      tools("news").innerHTML = '<button data-a="r" title="Refresh">⟳</button>';
      tools("news").onclick = () => this.open(true);
      if (force || newsCache.q !== q || Date.now() - newsCache.at > 600000) {
        b.innerHTML = '<p class="muted sp-empty">Loading headlines…</p>';
        try { const r = await fetch(`/api/news?q=${encodeURIComponent(q)}`); const d = await r.json(); if (!r.ok) throw new Error(d.detail || r.status); newsCache = { q, items: d, at: Date.now() }; }
        catch (e) { b.innerHTML = `<p class="muted sp-empty">News unavailable (${esc(e.message)})</p>`; return; }
      }
      if (open === "news") { newsSeen = Date.now() / 1000; keep("ltv.newsSeen", newsSeen); badge("news", 0); }
      b.innerHTML = `<div class="sp-sec">${esc(q)} · Google News</div>` + (newsCache.items.length ? newsCache.items.map((n) =>
        `<a class="sp-news" href="${esc(n.link)}" target="_blank" rel="noopener noreferrer"><span>${esc(n.title)}</span><small class="muted">${esc(n.source)} · ${ago(n.t)}</small></a>`).join("")
        : '<p class="muted sp-empty">No recent headlines.</p>');
    },
  },
  notif: {
    open() {
      unseen = 0; badge("notif", 0);
      tools("notif").innerHTML = '<button data-a="clr" title="Clear all">Clear</button>';
      tools("notif").onclick = () => { notes = []; keep("ltv.notes", notes); this.open(); };
      body("notif").innerHTML = notes.length ? notes.map((n) => `<div class="sp-note ${n.kind}"><span>${esc(n.text)}</span><small class="muted">${ago(n.t)}</small></div>`).join("")
        : '<p class="muted sp-empty">Alerts, connection and data errors show up here.</p>';
    },
  },
  cache: {
    async open() {
      const c = app.A(), info = c.cache, S = c.S, src = info?.source || app.srcFor(S.symbol);
      const tf = app.TFS.find((x) => x[1] === S.tf)?.[0] || "";
      const when = (t) => new Date(t * 1000).toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
      const b = body("cache");
      const head = `<div class="sp-sec">${esc(S.symbol)} · ${tf}</div>
        <div class="sp-row dw"><span class="muted">Source</span><span><i class="src-tag ${src}">${app.SRC_NAME[src] || src}</i></span></div>
        <div class="sp-row dw"><span class="muted">Cached data starts</span><b>${info ? when(info.t) : "not cached"}</b></div>
        ${info ? `<div class="sp-row dw"><span class="muted">Built from</span><span>${info.kind === "1m" ? "1m candles" : esc(info.kind) + " file"}</span></div>` : ""}`;
      b.innerHTML = head + '<p class="muted sp-empty">Reading cache…</p>';
      try {
        const r = await fetch(`/api/cache?source=${src}&symbol=${encodeURIComponent(S.symbol)}`), d = await r.json();
        if (!r.ok) throw new Error(d.detail || r.status);
        const kb = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
        const day = (x) => (typeof x === "number" ? when(x) : new Date(x).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }));
        b.innerHTML = head + `<div class="sp-sec">On disk · ${esc(d.path)}</div>` + (d.files.length ? d.files.map((f) =>
          `<div class="sp-row cf"><b>${esc(f.tf)}</b><span>${day(f.first)} → ${day(f.last)}</span><span class="muted">${f.rows.toLocaleString()} bars${f.days ? ` · ${f.days} days` : ""} · ${kb(f.bytes)}</span></div>`).join("")
          : '<p class="muted sp-empty">Nothing cached yet for this symbol.</p>');
      } catch (e) { b.innerHTML = head + `<p class="muted sp-empty">${esc(e.message)}</p>`; }
      b.insertAdjacentHTML("beforeend", `<div class="sp-sec">Index constituents (Breeze)</div>
        <p class="muted sp-empty">Downloads every stock's 1m candles with volume into data/Breeze, then sums them into the index's volume.
        Charts of those stocks load from disk too. The first run takes a while (about 50 requests per 2 days).</p>
        <div class="pf-ctl"><select data-pf="days">${[[30, "30 days"], [90, "90 days"], [180, "180 days"], [365, "1 year"]].map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
        <button data-pf="NIFTY">NIFTY 50</button><button data-pf="BANKNIFTY">Bank Nifty</button><button data-pf="SENSEX">Sensex</button></div><div class="pf-jobs"></div>`);
      b.querySelectorAll("button[data-pf]").forEach((x) => x.onclick = async () => {
        const r = await fetch("/api/prefetch", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ index: x.dataset.pf, days: +b.querySelector('[data-pf="days"]').value }) });
        if (!r.ok) notify((await r.json().catch(() => ({}))).detail || "download failed", "err");
        pollPrefetch();
      });
      pollPrefetch();
    },
  },
  help: {
    open() {
      const K = [["Symbol search", "type on the chart / click symbol"], ["Fullscreen", "Shift + F"], ["Exit fullscreen / close", "Esc"], ["Save layout", "Ctrl + S"],
        ["Log scale", "Alt + L"], ["Percent scale", "Alt + P"], ["Invert scale", "Alt + I"], ["Replay: step forward", "Shift + →"], ["Replay: play / pause", "Shift + ↓"],
        ["Reset chart view", "⟲ on the chart"], ["Load older bars", "scroll the chart to the left edge"]];
      body("help").innerHTML = '<div class="sp-sec">Keyboard shortcuts</div>' + K.map(([a, k]) => `<div class="sp-row dw"><span>${a}</span><kbd>${k}</kbd></div>`).join("") +
        `<div class="sp-sec">Data</div><p class="muted sp-empty">Candles are cached under <b>data/&lt;Source&gt;/&lt;Symbol&gt;</b>: 1m files per day (1m–15m charts) and one file per timeframe (30m and up).
        The database icon in this bar (coloured by source) shows where the active chart's cached candles start.</p>`;
    },
  },
};

// ------------------------------------------------------------------ hooks for app.js
window.LTVSide = {
  alertsFor: (sym) => alerts.filter((a) => a.symbol === sym && !a.ind),
  ordersFor: (sym) => orders.filter((o) => o.symbol === sym && o.status === "working"),
  newAlert, newOrder, addOrder, notify, beep, badge, show,
  isOpen: (id) => open === id,
  clearOrders() { orders = []; saveOrders(); },
  pane: (id) => panes[id],
  extraSymbols() {
    const s = [...alerts.filter((a) => a.active && !a.ind).map((a) => a.symbol), ...orders.filter((o) => o.status === "working").map((o) => o.symbol)];
    s.push(...(window.LTVTrade?.symbols() || []));
    if (open === "market") s.push(...MARKETS.map((m) => m[0]));
    if (open === "hot") s.push(...PANES.hot.syms());
    return s;
  },
  onQuotes(items) {
    checkAlerts(items);
    window.LTVTrade?.onQuotes(items);
    if (open === "market" || open === "hot") { clearTimeout(this.qt); this.qt = setTimeout(() => PANES[open]?.open(panes[open]), 400); }
  },
  notify,
  show,
  cacheChanged() { paintCacheIcon(); if (open === "cache") PANES.cache.open(); },
};
// constituent download progress (Data cache panel)
let pfTimer = null;
async function pollPrefetch() {
  clearTimeout(pfTimer);
  let jobs = {};
  try { jobs = await (await fetch("/api/prefetch")).json(); } catch { return; }
  const box = $(".pf-jobs", panes.cache);
  const running = Object.values(jobs).some((j) => !j.finished);
  if (box) box.innerHTML = Object.values(jobs).map((j) => {
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    const label = j.stage === "done" ? `done · index volume for ${j.summed} days` : j.stage === "failed" ? "failed" : j.stage === "volume" ? "summing volume…"
      : j.stage === "stocks" ? `${j.done}/${j.total} stocks · ${esc(j.current || "")}` : "downloading index…";
    return `<div class="pf-job"><div class="sp-row dw"><b>${esc(j.index)}</b><span class="muted">${j.days} days</span><span>${label}</span></div>
      <div class="pf-bar"><i style="width:${j.stage === "done" ? 100 : pct}%"></i></div>${(j.errors || []).map((e) => `<small class="dn">${esc(e)}</small>`).join("<br>")}</div>`;
  }).join("");
  for (const j of Object.values(jobs)) {
    if (j.finished && !pollPrefetch.seen?.[j.index + j.finished]) {
      (pollPrefetch.seen ||= {})[j.index + j.finished] = 1;
      if (pollPrefetch.armed) notify(`${j.index} constituents ${j.stage === "done" ? `downloaded · volume for ${j.summed} days` : "download failed"}`, j.stage === "done" ? "info" : "err");
    }
  }
  pollPrefetch.armed = true;
  if (running) pfTimer = setTimeout(pollPrefetch, 2000);
}

// the Data cache icon takes the colour of the active chart's source
let cacheSig = "";
function paintCacheIcon() {
  const c = app.A(), src = c.cache?.source || app.srcFor(c.S.symbol), btn = $('[data-p="cache"]', rail);
  btn.className = `${open === "cache" ? "on " : ""}src-${src}${c.cache ? " has" : ""}`;
  btn.title = c.cache ? `Data cache · ${app.SRC_NAME[src]} · cached from ${new Date(c.cache.t * 1000).toLocaleDateString()}` : `Data cache · ${app.SRC_NAME[src] || src} · not cached`;
  const sig = `${c.S.symbol}|${c.S.tf}|${c.cache?.t}`;
  if (sig !== cacheSig) { cacheSig = sig; if (open === "cache") PANES.cache.open(); }
}
setInterval(paintCacheIcon, 1500);
function newAlert(o = {}) {
  const sym = o.symbol || activeSym(), last = o.price ?? quoteOf(sym)?.last ?? app.A().bars?.at(-1)?.[4], ind = o.ind;
  const d = document.createElement("dialog");
  d.innerHTML = `<form method="dialog" class="dlg tv-login"><div class="dlg-head"><b>Create alert${ind ? " on " + esc(ind.title) : ""}</b><button value="cancel">✕</button></div>
    <div class="tvl-body"><label class="srow">Symbol <input name="sym" value="${esc(sym)}" ${ind ? "readonly" : ""}></label>
    <label class="srow">Condition <select name="cond"><option value="cross">Crossing</option><option value="above">Greater than</option><option value="below">Less than</option></select></label>
    <label class="srow">Price <input name="price" type="number" step="any" value="${last != null ? +(+last).toFixed(ind ? 4 : 2) : ""}"></label>
    <label class="srow">Message <input name="msg" placeholder="optional"></label>
    <label class="srow"><span></span><span class="chk"><input name="once" type="checkbox" checked> Only once</span></label>
    <div class="dlg-foot"><span class="spacer"></span><button value="cancel">Cancel</button><button value="ok" class="primary">Create</button></div></div></form>`;
  document.body.appendChild(d);
  d.onclose = () => {
    if (d.returnValue === "ok") {
      const f = d.querySelector("form"), price = parseFloat(f.price.value);
      if (Number.isFinite(price)) {
        alerts.unshift({ id: "a" + Date.now().toString(36), symbol: app.canon(f.sym.value || sym), cond: f.cond.value, price, msg: f.msg.value.trim(),
          once: f.once.checked, active: true, created: Date.now() / 1000, ...(ind ? { ind } : {}) });
        saveAlerts(); notify(`Alert created: ${f.sym.value}${ind ? " · " + ind.title : ""} ${f.cond.value} ${fmt(price)}`);
        try { if (window.Notification?.permission === "default") Notification.requestPermission(); } catch { /* */ }
        show("alerts");
      }
    }
    d.remove();
  };
  d.showModal();
}

// news badge: fresh headlines for the active symbol since the panel was last opened
async function pollNews() {
  if (open !== "news") {
    try { await PANES.news.open.call(PANES.news, false); } catch { /* */ }
    badge("news", newsCache.items.filter((n) => n.t > newsSeen).length);
  }
}
const _open = PANES.news.open;
PANES.news.open = async function (force) { if (open !== "news") { // fetch only, no painting of a hidden panel
  const sym = activeSym(), q = /^(NIFTY|BANKNIFTY|FINNIFTY|SENSEX|BANKEX)$/.test(sym) ? `${sym} index` : `${sym.replace(/^.*:/, "").replace(/\d+!$/, "")} stock`;
  if (newsCache.q === q && Date.now() - newsCache.at < 600000) return;
  try { const r = await fetch(`/api/news?q=${encodeURIComponent(q)}`); if (r.ok) newsCache = { q, items: await r.json(), at: Date.now() }; } catch { /* */ }
  return; } return _open.call(this, force); };
setTimeout(pollNews, 4000); setInterval(pollNews, 600000);
// live panels refresh while open
setInterval(() => { if (open === "tech" || (open === "tree" && treeTab === "tree")) PANES[open].open(panes[open]); }, 5000);

badge("alerts", alerts.filter((a) => a.active).length);
show(open === undefined ? "watchlist" : open);
app.each("all", (c) => c.paintAlertLines?.());
})();
