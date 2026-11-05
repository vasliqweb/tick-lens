/* Paper trading: order ticket (options on index/stock underlyings, or the chart symbol itself), trades panel,
   SL / target / exit-limit triggers on streamed quotes, chart lines with live P&L.
   Simulated only: nothing is sent to a broker. Trades persist on the server (data/paper/trades.json). */
(() => {
"use strict";
if (+new URLSearchParams(location.search).get("slot") > 0) return;      // the host page owns trading
const app = window.LTVApp, side = window.LTVSide;
if (!app || !side) return;
const $ = (s, r = document) => r.querySelector(s);
const esc = app.esc;
const store = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const keep = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } };
const fmt = (v, p = 2) => (v == null || !Number.isFinite(+v) ? "–" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: p, maximumFractionDigits: p }));
const money = (v) => (v == null || !Number.isFinite(v) ? "–" : `${v >= 0 ? "+" : "−"}₹${fmt(Math.abs(v))}`);
const cls = (v) => (v > 0 ? "up" : v < 0 ? "dn" : "");
const FNO_RE = /^(\S+) (\d{2}[A-Z]{3}\d{2}) (?:FUT|(\S+) (CE|PE))$/;
const INDEX = new Set(["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYIT", "SENSEX", "BANKEX"]);
const PREF = Object.assign({ right: "CE", money: "ATM", n: 1, lots: 1, side: "buy", slMode: "pts", show: true, watch: true, tab: "opt" },
  store("ltv.paper.pref", {}));
const savePref = () => keep("ltv.paper.pref", PREF);

async function api(path, opts = {}) {
  const r = await fetch("/api/paper" + path, { headers: { "content-type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
  return j;
}
const live = (sym) => app.quotes.get(`${app.srcFor(sym)}:${sym}`)?.last;
const chartLast = (sym) => { let v = null; app.each("all", (c) => { if (v == null && c.S?.symbol === sym) v = c.bars?.at(-1)?.[4]; }); return v; };
const ltpOf = (sym) => live(sym) ?? chartLast(sym);

// ------------------------------------------------------------------ state
let trades = [], acct = null;
const loadAcct = () => api("/account").then((a) => { acct = a; changed(); }).catch(() => {});
const busy = new Set();
const sign = (t) => (t.side === "buy" ? 1 : -1);
const pnlOf = (t, px = ltpOf(t.symbol)) => (t.status === "closed" ? t.pnl : t.status === "open" && px != null ? sign(t) * (px - t.entry) * t.qty : null);
const isToday = (ts) => ts && new Date(ts * 1000).toDateString() === new Date().toDateString();
async function reload() {
  try { trades = await api("/trades"); acct = await api("/account"); } catch (e) { app.toast(`Paper trades: ${e.message}`); }
  changed(true);
}
let paintT = 0;
function changed(now) {
  clearTimeout(paintT);
  const run = () => { app.each("all", (c) => c.paintTradeLines?.()); if (side.isOpen("trades")) render(); side.badge("trades", trades.filter((t) => t.status === "open" || t.status === "pending").length); };
  if (now) run(); else paintT = setTimeout(run, 400);
}
function replace(t) { const i = trades.findIndex((x) => x.id === t.id); if (i >= 0) trades[i] = t; else trades.unshift(t); app.sendWatch(); changed(true); loadAcct(); }

// ------------------------------------------------------------------ triggers (run on every quote batch)
function onQuotes(items) {
  let any = false;
  for (const q of items) {
    if (q.last == null || q.stale || !(q.last > 0)) continue;   // daily-close fallbacks are not live prices
    for (const t of trades) {
      if (t.engine === "server") { if (`${app.srcFor(t.symbol)}:${t.symbol}` === q.key || t.under && `${app.srcFor(t.under)}:${t.under}` === q.key) any = true; continue; }   // run by the server engine
      if (busy.has(t.id) || (cool.get(t.id) || 0) > Date.now() || `${app.srcFor(t.symbol)}:${t.symbol}` !== q.key) continue;
      any = true;
      const px = q.last, long = t.side === "buy";
      const stopEntry = t.entryType === "stop";             // buy stop fills at/above, sell stop at/below; limits the other way
      if (t.status === "pending" && t.limit != null && (long === stopEntry ? px >= t.limit : px <= t.limit))
        act(t, () => api(`/trades/${t.id}/fill`, { method: "POST", body: { price: px } }), `${stopEntry ? "Stop" : "Limit"} entry filled: ${label(t)} @ ${fmt(px)}`);
      else if (t.status === "open") {
        let reason = null;
        if (t.sl != null && (long ? px <= t.sl : px >= t.sl)) reason = "sl";
        else if (t.target != null && (long ? px >= t.target : px <= t.target)) reason = "target";
        else if (t.exitLimit != null && (long ? px >= t.exitLimit : px <= t.exitLimit)) reason = "limit";
        if (reason) act(t, () => api(`/trades/${t.id}/exit`, { method: "POST", body: { reason, price: px } }),
          `${{ sl: "🛑 Stop loss hit", target: "🎯 Target hit", limit: "Exit limit filled" }[reason]}: ${label(t)} @ ${fmt(px)} (${money(sign(t) * (px - t.entry) * t.qty)})`);
      }
    }
  }
  if (any) changed();
}
const cool = new Map();          // trade id -> no new trigger before this time (after an unconfirmed trigger)
async function act(t, fn, msg) {
  busy.add(t.id);
  try {
    const r = await fn(); replace(r);
    if (msg && r.status !== t.status) {      // message from the server's real fill price, not the streamed tick
      const real = r.status === "closed" ? `${{ sl: "🛑 Stop loss hit", target: "🎯 Target hit", limit: "Exit limit filled", market: "Exited" }[r.exitReason] || "Closed"}: ${label(r)} @ ${fmt(r.exit)} (${money(r.pnl)})`
        : r.status === "open" && t.status === "pending" ? `Entry filled: ${label(r)} @ ${fmt(r.entry)}` : msg;
      stick(real, t.id); side.notify(real, "alert"); side.beep();
    }
  } catch (e) {
    if (/not confirmed/.test(e.message)) { cool.set(t.id, Date.now() + 5000); console.info("paper trigger:", e.message); }
    else app.toast(`Paper trade: ${e.message}`);
  } finally { busy.delete(t.id); }
}
const label = (t) => `${t.side === "buy" ? "Buy" : "Sell"} ${t.qty} ${t.symbol}`;
const TFN = (v) => TFS_TRIG.find((x) => x[0] === +v)?.[1] || `${v}s`;
function pendingText(t) {
  if (t.engine !== "server") return `Limit ${fmt(t.limit)}`;
  const b = t.band, c = t.cond;
  const how = b ? (b.lo != null ? `range ${fmt(b.lo)} – ${fmt(b.hi)}` : `±${fmt(b.pct, 1)}% range at trigger`) : "market";
  if (c && c.phase === "armed") return `Waiting for ${c.under} close → ${how}`;
  if (c) return `Triggered @ ${fmt(c.signal?.c)} → ${how}`;
  return `Limit ${how}`;
}

// ------------------------------------------------------------------ server engine sync: index-triggered / range orders run on the server
let sRev = -1, sSeq = store("ltv.paper.seq", 0), engNote = "";
async function syncEngine() {
  try {
    const r = await api(`/sync?rev=${sRev}&seq=${sSeq}`);
    const fresh = r.msgs.filter((m) => m.seq > sSeq);
    if (fresh.length) { sSeq = r.seq; keep("ltv.paper.seq", sSeq); }
    if (r.seq < sSeq) { sSeq = r.seq; keep("ltv.paper.seq", sSeq); }      // server restarted
    for (const m of fresh) { stick(m.text, m.id); side.notify(m.text, "alert"); side.beep(); }
    if (engNote !== r.note) { engNote = r.note; if (side.isOpen("trades")) render(); }
    if (r.rev !== sRev) { const first = sRev === -1; sRev = r.rev; if (!first || fresh.length) { trades = await api("/trades"); loadAcct(); changed(true); app.sendWatch(); } }
  } catch { /* server unreachable: retry */ }
}
setInterval(() => { if (!document.hidden || trades.some((t) => t.engine === "server" && (t.status === "pending" || t.status === "open"))) syncEngine(); }, 2000);
const TFS_TRIG = [[60, "1m"], [180, "3m"], [300, "5m"], [900, "15m"], [1800, "30m"], [3600, "1h"]];
const bullOf = (side_, right) => (side_ === "buy") === (right === "CE");

// ------------------------------------------------------------------ order ticket
function underOf(sym) { const m = FNO_RE.exec(sym); return m ? m[1] : sym; }
function openTicket(o = {}) {
  const chartSym = o.symbol || app.A().S.symbol, under = underOf(chartSym), isOpt = /(CE|PE)$/.test(chartSym) && FNO_RE.test(chartSym);
  const d = document.createElement("dialog");
  d.className = "pt-dlg";
  d.innerHTML = `<form method="dialog" class="dlg pt"><div class="dlg-head"><b>Paper trade · <span class="pt-und">${esc(under)}</span></b><button value="cancel">✕</button></div>
  <div class="pt-body">
    <div class="tabs pt-tabs"><button type="button" data-t="opt">Option</button><button type="button" data-t="sym">${esc(chartSym)}</button></div>
    <div class="pt-opt">
      <div class="srow"><span>Type</span><span class="ctl"><span class="seg sm grow" data-k="right"><button type="button" data-v="CE">Call (CE)</button><button type="button" data-v="PE">Put (PE)</button></span></span></div>
      <div class="srow"><span>Strike</span><span class="ctl"><span class="seg sm grow" data-k="money"><button type="button" data-v="ITM">ITM</button><button type="button" data-v="ATM">ATM</button><button type="button" data-v="OTM">OTM</button></span>
        <select name="n" class="w-sm" title="Strikes away from ATM">${[1, 2, 3, 4, 5, 6, 8, 10].map((k) => `<option value="${k}">±${k}</option>`).join("")}</select></span></div>
      <div class="srow"><span>Expiry</span><span class="ctl"><select name="exp" class="grow"><option value="">loading…</option></select>
        <select name="step" class="w-sm" title="Strike grid">${[100, 50].map((k) => `<option value="${k}">${k} grid</option>`).join("")}</select></span></div>
      <div class="pt-contract muted">…</div>
      <div class="srow"><span>Entry</span><span class="ctl"><span class="seg sm grow" data-k="when" title="Enter now, or when an index candle closes beyond a level (runs on the server)"><button type="button" data-v="now">Now</button><button type="button" data-v="index">Index close</button></span></span></div>
      <div class="srow pt-idx"><span class="pt-idxlbl">When</span><span class="ctl"><span class="seg sm grow" data-k="dir"><button type="button" data-v="above">Closes above</button><button type="button" data-v="below">Closes below</button></span></span></div>
      <div class="srow pt-idx"><span>Level</span><span class="ctl"><input name="level" class="grow" type="number" step="0.05" placeholder="Index level"><select name="tf" class="w-sm" title="Candle timeframe">${TFS_TRIG.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></span></div>
    </div>
    <div class="pt-symnote muted"></div>
    <div class="srow"><span>Side</span><span class="ctl"><span class="seg sm grow pt-side" data-k="side"><button type="button" data-v="buy">Buy</button><button type="button" data-v="sell">Sell</button></span></span></div>
    <div class="srow"><span>Quantity</span><span class="ctl"><input name="lots" class="grow" type="number" min="1" step="1" title="Lots"><span class="unit">lots ×</span>
      <input name="lotSize" class="grow" type="number" min="1" step="1" title="Lot size"><span class="unit">= <b class="pt-qty">–</b></span></span></div>
    <div class="srow"><span>Order</span><span class="ctl"><span class="seg sm grow" data-k="etype"><button type="button" data-v="market">Market</button><button type="button" data-v="limit">Limit</button></span>
      <input name="limit" class="grow" type="number" step="0.05" placeholder="Limit price"></span></div>
    <div class="srow pt-band"><span>Tolerance</span><span class="ctl"><input name="tol" class="w-sm" type="number" step="0.1" min="0" max="20" title="± % around the limit price"><span class="unit">%</span>
      <select name="anchor" class="grow" title="Which option price the range is built around"><option value="now">of price now</option><option value="trigger">of price at trigger</option></select></span></div>
    <div class="pt-range muted"></div>
    <div class="srow pt-ir"><span>Stop loss</span><span class="ctl"><select name="slRule" class="grow"></select><input name="slIdx" class="w-sm" type="number" step="0.05" placeholder="Index"></span></div>
    <div class="srow pt-ir"><span>Target</span><span class="ctl"><select name="tgRule" class="grow"></select><input name="tgK" class="w-sm" type="number" step="0.5" min="0.5" title="× signal candle range (high − low)"><input name="tgIdx" class="w-sm" type="number" step="0.05" placeholder="Index"></span></div>
    <div class="srow pt-sltm"><span>SL / Target in</span><span class="ctl"><span class="seg sm grow" data-k="slMode" title="SL / target as points from entry or as prices"><button type="button" data-v="pts">Points</button><button type="button" data-v="px">Price</button></span></span></div>
    <div class="srow pt-psl"><span>Premium SL</span><span class="ctl"><input name="sl" class="grow" type="number" step="0.05" min="0" placeholder="optional"></span></div>
    <div class="srow pt-ptg"><span>Premium target</span><span class="ctl"><input name="target" class="grow" type="number" step="0.05" min="0" placeholder="optional"></span></div>
    <div class="srow"><span></span><span class="ctl pt-checks"><label class="chk"><input type="checkbox" name="show"> Show on chart</label><label class="chk pt-wl"><input type="checkbox" name="watch"> Add to watchlist</label></span></div>
    <div class="pt-sum muted"></div>
    <div class="tvl-err pt-err"></div>
    <p class="muted pt-note">Paper trade only, nothing goes to a broker. Market orders fill at the ask (buy) or bid (sell) from Breeze, or at the LTP when there is no bid/ask.
      Option limit with tolerance: the order rests on the server and fills only when the ask (buy) / bid (sell) is inside the range. Index triggers use closed candles only; unfilled orders expire at 15:30.</p>
  </div>
  <div class="dlg-foot"><span class="spacer"></span><button value="cancel">Cancel</button><button value="ok" class="primary pt-go">Place</button></div></form>`;
  document.body.appendChild(d);
  const f = d.querySelector("form"), err = (m) => { d.querySelector(".pt-err").textContent = m || ""; };
  const st = { tab: isOpt || o.price != null ? "sym" : PREF.tab, right: PREF.right, money: PREF.money, side: PREF.side, etype: o.price != null ? "limit" : "market", slMode: PREF.slMode,
    meta: null, opt: null, quote: null, optOk: false, when: PREF.when || "now", dir: "above", center: null };
  if (o.price != null) f.limit.value = (+o.price).toFixed(2);
  st.dir = bullOf(st.side, st.right) ? "above" : "below";
  f.tol.value = PREF.tol ?? 1; f.anchor.value = PREF.anchor || "now"; f.tgK.value = PREF.tgK ?? 2;
  f.tf.value = TFS_TRIG.some(([v]) => v === app.A().S.tf) ? app.A().S.tf : (PREF.tf || 300);
  { const sp = ltpOf(under); if (sp) f.level.value = (Math.round(sp / 5) * 5).toFixed(0); }
  f.n.value = PREF.n; f.lots.value = PREF.lots; f.show.checked = PREF.show; f.watch.checked = PREF.watch; f.step.value = 100; f.lotSize.value = 1;
  const segs = () => d.querySelectorAll(".seg[data-k]").forEach((s) => s.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === st[s.dataset.k])));
  const sym = () => (st.tab === "opt" ? st.opt?.symbol : chartSym);
  const price = () => (st.tab === "opt" ? (st.quote?.[st.side === "buy" ? "ask" : "bid"] || st.quote?.last) : ltpOf(chartSym));
  function paint() {
    segs();
    d.querySelectorAll(".pt-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === st.tab));
    d.querySelector(".pt-opt").classList.toggle("hidden", st.tab !== "opt");
    d.querySelector(".pt-wl").classList.toggle("hidden", st.tab !== "opt");
    f.n.disabled = st.money === "ATM";
    const idx = st.tab === "opt" && st.when === "index", tol = +f.tol.value || 0, bandOn = st.tab === "opt" && st.etype === "limit" && tol > 0;
    const trigAnchor = idx && bandOn && f.anchor.value === "trigger";
    f.limit.classList.toggle("hidden", st.etype !== "limit" || trigAnchor);
    d.querySelectorAll(".pt-idx").forEach((x) => x.classList.toggle("hidden", !idx));
    d.querySelector(".pt-band").classList.toggle("hidden", !(st.tab === "opt" && st.etype === "limit"));
    f.anchor.classList.toggle("hidden", !idx);
    const bull = bullOf(st.side, st.right), up = bull ? "below" : "above";
    const slOpts = [["prevLow", `Index closes ${up} previous candle ${bull ? "low" : "high"}`], ["prevClose", `Index closes ${up} previous candle close`],
      ["index", `Index closes ${up} level`], ["premium", "Option premium"], ["none", "None"]];
    const tgOpts = [["range", "Index: k × trigger candle range"], ["index", "Index reaches level"], ["premium", "Option premium"], ["none", "None"]];
    for (const [sel, opts, def] of [[f.slRule, slOpts, PREF.slRule || "prevLow"], [f.tgRule, tgOpts, PREF.tgRule2 || "none"]]) {
      const v = sel.value || def;
      sel.innerHTML = opts.map(([k, l]) => `<option value="${k}">${l}</option>`).join(""); sel.value = v;
    }
    d.querySelectorAll(".pt-ir").forEach((x) => x.classList.toggle("hidden", !idx));
    f.slIdx.classList.toggle("hidden", f.slRule.value !== "index"); f.tgK.classList.toggle("hidden", f.tgRule.value !== "range"); f.tgIdx.classList.toggle("hidden", f.tgRule.value !== "index");
    const psl = !idx || f.slRule.value === "premium", ptg = !idx || f.tgRule.value === "premium";
    d.querySelector(".pt-psl").classList.toggle("hidden", !psl); d.querySelector(".pt-ptg").classList.toggle("hidden", !ptg);
    d.querySelector(".pt-sltm").classList.toggle("hidden", !(psl || ptg));
    d.querySelector(".pt-idxlbl").textContent = `When ${under}`;
    const rng = d.querySelector(".pt-range"), lp = price();
    if (bandOn && !trigAnchor && +f.limit.value > 0) {
      const c = +f.limit.value, lo = c * (1 - tol / 100), hi = c * (1 + tol / 100), inside = lp != null && lp >= lo && lp <= hi;
      rng.innerHTML = `Range <b>${fmt(lo)} – ${fmt(hi)}</b> (±${fmt(tol, 1)}% of ${fmt(c)})${lp != null ? ` · now ${fmt(lp)} <span class="${inside ? "up" : "dn"}">${inside ? (idx ? "inside" : "inside: fills now") : "outside: order waits"}</span>` : ""}`;
    } else if (bandOn && trigAnchor) rng.innerHTML = `Range = ±${fmt(tol, 1)}% of the option price when ${esc(under)} triggers${lp != null ? ` (now ${fmt(lp * (1 - tol / 100))} – ${fmt(lp * (1 + tol / 100))})` : ""}`;
    else rng.textContent = st.tab === "opt" && st.etype === "limit" ? "Tolerance 0: plain limit order at this price" : "";
    rng.classList.toggle("hidden", !rng.textContent);
    d.querySelector(".pt-side").className = `seg sm grow pt-side ${st.side}`;
    const note = d.querySelector(".pt-symnote");
    note.textContent = st.tab === "sym" ? (INDEX.has(chartSym) ? `${chartSym} is an index: this paper trade tracks the index points (not a tradable instrument).` : `Trade ${chartSym} at its live price.`) : "";
    const qty = (+f.lots.value || 0) * (+f.lotSize.value || 0), px = price(), e = st.etype === "limit" ? +f.limit.value || px : px;
    d.querySelector(".pt-qty").textContent = qty || "–";
    const lv = levels(e);
    const risk = lv.sl != null && e ? Math.abs(e - lv.sl) * qty : null, rew = lv.target != null && e ? Math.abs(lv.target - e) * qty : null;
    const avail = acct?.available, short = avail != null && e && e * qty > avail;
    d.querySelector(".pt-sum").innerHTML = (avail != null ? `Available <b class="${short ? "dn" : ""}">₹${fmt(avail)}</b>${short ? " · not enough capital" : ""}<br>` : "") + (e ? `Value ₹${fmt(e * qty)}${lv.sl != null ? ` · SL ${fmt(lv.sl)} risk <span class="dn">₹${fmt(risk)}</span>` : ""}${lv.target != null ? ` · TGT ${fmt(lv.target)} reward <span class="up">₹${fmt(rew)}</span>` : ""}${risk && rew ? ` · R:R 1:${fmt(rew / risk, 1)}` : ""}` : "");
    const go = d.querySelector(".pt-go");
    go.textContent = idx ? `${st.side === "buy" ? "Buy" : "Sell"} when ${under} closes ${st.dir} ${f.level.value || "?"}`
      : `${st.side === "buy" ? "Buy" : "Sell"} ${sym() || ""}${st.etype === "market" && px ? ` @ ${fmt(px)}` : ""}`;
    go.className = `primary pt-go ${st.side}`;
    go.disabled = !sym() || (st.tab === "opt" && !st.optOk) || short;
  }
  function levels(e) {
    const sl = parseFloat(f.sl.value), tg = parseFloat(f.target.value), dir = st.side === "buy" ? 1 : -1;
    if (st.slMode === "px") return { sl: Number.isFinite(sl) ? sl : null, target: Number.isFinite(tg) ? tg : null };
    if (!e) return { sl: null, target: null };
    const r = (v) => Math.round(v * 20) / 20;
    return { sl: Number.isFinite(sl) && sl > 0 ? r(e - dir * sl) : null, target: Number.isFinite(tg) && tg > 0 ? r(e + dir * tg) : null };
  }
  let seq = 0, timer = 0;
  async function resolve(quick) {
    if (st.tab !== "opt" || !st.meta) return;
    const my = ++seq, spot = under === chartSym ? ltpOf(under) : live(under);
    const qs = new URLSearchParams({ under, right: st.right, money: st.money, n: f.n.value, expiry: f.exp.value, step: f.step.value });
    if (spot) qs.set("spot", spot);
    if (!quick) d.querySelector(".pt-contract").textContent = "Finding contract…";
    try {
      const r = await api(`/option?${qs}`);
      if (my !== seq) return;
      st.opt = r; st.quote = r.quote; st.optOk = true; err("");
      const q = r.quote;
      d.querySelector(".pt-contract").innerHTML = `<b>${esc(r.symbol)}</b> · spot ${fmt(r.spot)} · ATM ${fmt(r.atm, 0)}${r.offGrid ? ` · <span class="dn">${fmt(r.target, 0)} not listed, nearest used</span>` : ""}<br>` +
        (q ? `LTP <b>${fmt(q.last)}</b>${q.bid ? ` · bid ${fmt(q.bid)}` : ""}${q.ask ? ` · ask ${fmt(q.ask)}` : ""}` : '<span class="dn">no premium quote</span>');
      if (!q) st.optOk = false;
    } catch (e) { if (my === seq) { st.optOk = false; st.opt = null; d.querySelector(".pt-contract").textContent = ""; err(e.message); } }
    paint();
  }
  async function loadMeta() {
    try {
      st.meta = await api(`/meta?under=${encodeURIComponent(under)}`);
      f.exp.innerHTML = st.meta.expiries.map((x) => `<option value="${x}">${new Date(x + "T00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit", weekday: "short" })}</option>`).join("");
      if (st.meta.lotSize && (st.tab === "opt" || isOpt)) f.lotSize.value = st.meta.lotSize;
      if (!INDEX.has(under)) { f.step.innerHTML = `<option value="${st.meta.step}">${st.meta.step} grid</option>`; }
      resolve();
    } catch (e) {
      st.meta = null; f.exp.innerHTML = "<option>–</option>";
      d.querySelector(".pt-contract").innerHTML = `<span class="dn">Options unavailable: ${esc(e.message)}</span>`;
      if (st.tab === "opt" && !st.userTab) st.tab = "sym";
      paint();
    }
  }
  function setTab(t) {
    st.tab = t; st.userTab = true; err("");
    if (t === "sym") { const m = FNO_RE.exec(chartSym); f.lotSize.value = m ? (st.meta?.lotSize || 1) : 1; }
    else if (st.meta?.lotSize) f.lotSize.value = st.meta.lotSize;
    if (t === "opt" && !st.meta) loadMeta(); else if (t === "opt") resolve();
    paint();
  }
  d.addEventListener("click", (e) => {
    const tb = e.target.closest(".pt-tabs [data-t]"); if (tb) { setTab(tb.dataset.t); return; }
    const b = e.target.closest(".seg[data-k] button"); if (!b) return;
    const k = b.closest(".seg").dataset.k; st[k] = b.dataset.v;
    if (k === "etype" && st.etype === "limit" && !f.limit.value) { const p = price(); if (p) f.limit.value = (+p).toFixed(2); }   // locked: the range stays on this price
    if (k === "side" || k === "right") st.dir = bullOf(st.side, st.right) ? "above" : "below";
    if (k === "right" || k === "money") resolve(); else paint();
  });
  f.n.onchange = f.exp.onchange = f.step.onchange = () => resolve();
  f.addEventListener("input", (e) => { if (!["n", "exp", "step"].includes(e.target.name)) paint(); });
  f.slRule.onchange = f.tgRule.onchange = f.anchor.onchange = () => paint();
  timer = setInterval(() => { if (st.tab === "opt" && st.opt) resolve(true); else paint(); }, 3000);
  loadMeta();                                   // also gives the lot size when the chart is an option
  paint();
  f.onsubmit = async (e) => {
    if (e.submitter?.value !== "ok") return;
    e.preventDefault();
    const s = sym(); if (!s) return;
    const px = price(), entry = st.etype === "limit" ? parseFloat(f.limit.value) : px, lv = levels(entry);
    const idx = st.tab === "opt" && st.when === "index", tol = +f.tol.value || 0, band = st.tab === "opt" && st.etype === "limit" && tol > 0;
    const anchor = idx && band ? f.anchor.value : "now";
    if (st.etype === "limit" && anchor === "now" && !Number.isFinite(entry)) { err("Enter a limit price"); return; }
    if (idx && st.etype === "limit" && !band) { err("Set a tolerance above 0 % for an index-triggered limit"); return; }
    if (idx && !(+f.level.value > 0)) { err(`Enter the ${under} trigger level`); return; }
    const body = { symbol: s, side: st.side, lots: +f.lots.value || 1, lotSize: +f.lotSize.value || 1, entryType: st.etype, limit: st.etype === "limit" ? entry : null,
      price: px, sl: lv.sl, target: lv.target, show: f.show.checked, under: st.tab === "opt" ? under : (FNO_RE.exec(s)?.[1] || null),
      spot: st.tab === "opt" ? st.opt?.spot : null, src: app.srcFor(s) };
    if (band) Object.assign(body, { entryType: "band", limit: null, band: { pct: tol, anchor, center: anchor === "now" ? entry : null } });
    if (idx) {
      body.cond = { under, tf: +f.tf.value, dir: st.dir, level: +f.level.value };
      body.rules = { sl: { mode: f.slRule.value, value: +f.slIdx.value || null }, target: { mode: f.tgRule.value, k: +f.tgK.value || 2, value: +f.tgIdx.value || null } };
      if (f.slRule.value !== "premium") body.sl = null;
      if (f.tgRule.value !== "premium") body.target = null;
      if (body.rules.sl.mode === "index" && !body.rules.sl.value) { err("Enter the index SL level"); return; }
      if (body.rules.target.mode === "index" && !body.rules.target.value) { err("Enter the index target level"); return; }
    }
    const go = d.querySelector(".pt-go"); go.disabled = true; go.textContent = "Placing…";
    try {
      const t = await api("/trades", { method: "POST", body });
      Object.assign(PREF, { right: st.right, money: st.money, n: +f.n.value, lots: body.lots, side: st.side, slMode: st.slMode, show: f.show.checked, watch: f.watch.checked, tab: st.tab,
        when: st.when, tol: tol, anchor: f.anchor.value, tf: +f.tf.value, slRule: f.slRule.value, tgRule2: f.tgRule.value, tgK: +f.tgK.value || 2 });
      savePref();
      if (st.tab === "opt" && f.watch.checked) app.addToWatchlist(s);
      replace(t);
      const msg = t.status === "open" ? `Paper ${label(t)} filled @ ${fmt(t.entry)}` : `Paper ${label(t)} ${pendingText(t)} placed`;
      stick(msg, t.id); side.notify(msg);
      d.close();
      side.show("trades");
    } catch (ex) { err(ex.message); paint(); }
  };
  d.onclose = () => { clearInterval(timer); d.remove(); };
  d.showModal();
}

// ------------------------------------------------------------------ one-click orders (crosshair menu, Alt+Shift+B/S) and old-order migration
async function lotSizeFor(sym) {
  const m = FNO_RE.exec(sym); if (!m) return 1;
  try { return (await api(`/meta?under=${encodeURIComponent(m[1])}`)).lotSize || 1; } catch { return 1; }
}
async function quick({ symbol, side: sd, type = "market", price, lots = 1, fill = null, silent = false }) {
  symbol = app.canon(symbol);
  const fno = FNO_RE.exec(symbol), body = { symbol, side: sd, lots, lotSize: await lotSizeFor(symbol), entryType: type,
    limit: type === "market" ? null : +price, price: fill ?? ltpOf(symbol), imported: fill != null, src: app.srcFor(symbol), show: true, under: fno?.[1] || null };
  try {
    const t = await api("/trades", { method: "POST", body });
    replace(t);
    if (fno && /(CE|PE)$/.test(symbol)) app.addToWatchlist(symbol);
    if (!silent) {
      const msg = t.status === "open" ? `Paper ${label(t)} filled @ ${fmt(t.entry)}` : `Paper ${label(t)} ${type} ${fmt(t.limit)} placed`;
      stick(msg, t.id); side.notify(msg); side.show("trades");
    }
    return t;
  } catch (e) { app.toast(`Paper trade not placed: ${e.message}`); return null; }
}
async function migrateOldOrders() {      // orders made with the old Alerts-panel order tool become real paper trades
  let old; try { old = JSON.parse(localStorage.getItem("ltv.orders") || "[]"); } catch { old = []; }
  const todo = old.filter((o) => o.status === "working" || o.status === "filled");
  if (!todo.length) return;
  keep("ltv.orders", []); side.clearOrders?.();
  let n = 0;
  for (const o of todo) {
    const t = o.status === "filled" ? await quick({ symbol: o.symbol, side: o.side, fill: o.fill ?? o.price, silent: true })
      : await quick({ symbol: o.symbol, side: o.side, type: o.type === "stop" ? "stop" : "limit", price: o.price, silent: true });
    if (t) n++;
  }
  if (n) { const msg = `Moved ${n} order${n > 1 ? "s" : ""} from the old order list into Paper trades`; stick(msg); side.show("trades"); }
}

// ------------------------------------------------------------------ modify / exit-limit dialog
function modify(t, focus = "sl") {
  const d = document.createElement("dialog");
  const ltp = ltpOf(t.symbol);
  d.innerHTML = `<form method="dialog" class="dlg pt"><div class="dlg-head"><b>${esc(t.symbol)}</b><button value="cancel">✕</button></div><div class="pt-body">
    <p class="muted">${esc(label(t))} @ ${t.entry != null ? fmt(t.entry) : esc(pendingText(t))} · LTP ${fmt(ltp)}</p>
    <div class="srow"><span>Stop loss</span><span class="ctl"><input name="sl" class="grow" type="number" step="0.05" value="${t.sl ?? ""}" placeholder="none"></span></div>
    <div class="srow"><span>Target</span><span class="ctl"><input name="target" class="grow" type="number" step="0.05" value="${t.target ?? ""}" placeholder="none"></span></div>
    ${t.engine === "server" && t.cond ? `<div class="srow"><span>Index SL</span><span class="ctl"><input name="idxSl" class="grow" type="number" step="0.05" value="${t.idxSl ?? ""}" placeholder="${t.cond.phase === "armed" ? "set at trigger" : "none"}" ${t.cond.phase === "armed" ? "disabled" : ""}></span></div>
      <div class="srow"><span>Index target</span><span class="ctl"><input name="idxTarget" class="grow" type="number" step="0.05" value="${t.idxTarget ?? ""}" placeholder="${t.cond.phase === "armed" ? "set at trigger" : "none"}" ${t.cond.phase === "armed" ? "disabled" : ""}></span></div>
      ${t.cond.phase === "armed" ? `<div class="srow"><span>Trigger level</span><span class="ctl"><input name="level" class="grow" type="number" step="0.05" value="${t.cond.level}"></span></div>` : ""}` : ""}
    ${t.status === "open" && t.engine !== "server" ? `<div class="srow"><span>Exit limit</span><span class="ctl"><input name="exitLimit" class="grow" type="number" step="0.05" value="${t.exitLimit ?? ""}" placeholder="none"></span></div>` : ""}
    <div class="tvl-err pt-err"></div></div>
    <div class="dlg-foot"><span class="spacer"></span><button value="cancel">Cancel</button><button value="ok" class="primary">Save</button></div></form>`;
  document.body.appendChild(d);
  const f = d.querySelector("form");
  f.onsubmit = async (e) => {
    if (e.submitter?.value !== "ok") return;
    e.preventDefault();
    const body = { sl: f.sl.value || null, target: f.target.value || null };
    if (f.exitLimit) body.exitLimit = f.exitLimit.value || null;
    for (const k of ["idxSl", "idxTarget", "level"]) if (f[k] && !f[k].disabled && String(f[k].value) !== String(k === "level" ? t.cond.level : t[k] ?? "")) body[k] = f[k].value || null;
    try { replace(await api(`/trades/${t.id}`, { method: "PATCH", body })); d.close(); } catch (ex) { d.querySelector(".pt-err").textContent = ex.message; }
  };
  d.onclose = () => d.remove();
  d.showModal();
  f[focus]?.focus(); f[focus]?.select?.();
}
const setLevel = (id, k, v) => { const t = trades.find((x) => x.id === id); if (t) act(t, () => api(`/trades/${id}`, { method: "PATCH", body: { [k]: v } })); };
const exitMarket = (t) => act(t, () => api(`/trades/${t.id}/exit`, { method: "POST", body: { reason: "market", price: ltpOf(t.symbol) } }),
  t.status === "pending" ? `Cancelled ${label(t)}` : `Exited ${label(t)}`);

// ------------------------------------------------------------------ trades panel
let tab = "open";
function render() {
  const el = side.pane("trades"); if (!el) return;
  const tools = $(".sp-tools", el), body = $(".sp-body", el);
  tools.innerHTML = '<button data-a="new" title="New paper trade (Shift + P)">＋</button><button data-a="more" title="More">⋯</button>';
  tools.onclick = (e) => {
    const a = e.target.closest("[data-a]")?.dataset.a;
    if (a === "new") openTicket();
    if (a === "more") {
      const r = e.target.getBoundingClientRect();
      LTVSettings.openMenu([
        { label: "Exit all open trades", icon: "⏏", disabled: !trades.some((t) => t.status === "open" || t.status === "pending"), action: async () => { if (await LTVSettings.confirm("Exit all open paper trades at market?", { title: "Exit all", ok: "Exit all", danger: true })) trades.filter((t) => t.status === "open" || t.status === "pending").forEach(exitMarket); } },
        { label: "Clear closed trades", icon: "⌫", disabled: !trades.some((t) => t.status === "closed" || t.status === "cancelled"), action: async () => { if (await LTVSettings.confirm("Delete all closed paper trades? Their P&L stops counting in capital.", { title: "Clear closed trades", ok: "Delete", danger: true })) { await api("/trades", { method: "DELETE" }); reload(); } } },
        { label: `Set capital (now ₹${fmt(acct?.capital ?? 500000, 0)})…`, icon: "₹", action: async () => {
          const v = await LTVSettings.prompt("Saving starts a fresh ledger: earlier trades stop counting.", acct?.capital ?? 500000, { title: "Starting capital (₹)", type: "number", min: 1 });
          if (v != null && +v > 0) { try { acct = await api("/account", { method: "PUT", body: { capital: +v } }); render(); } catch (ex) { app.toast(ex.message); } } } },
        { label: `Brokerage per order: ₹${acct?.brokerage ?? 20}`, icon: "%", action: async () => {
          const v = await LTVSettings.prompt("Charged on every executed order (entry and exit).", acct?.brokerage ?? 20, { title: "Brokerage per order (₹)", type: "number", min: 0 });
          if (v != null && Number.isFinite(+v) && +v >= 0) { try { acct = await api("/account", { method: "PUT", body: { brokerage: +v } }); render(); } catch (ex) { app.toast(ex.message); } } } },
      ], r.left - 240, r.bottom + 4);
    }
  };
  const open = trades.filter((t) => t.status === "open"), pend = trades.filter((t) => t.status === "pending");
  const done = trades.filter((t) => t.status === "closed" || t.status === "cancelled");
  const unreal = open.reduce((s, t) => s + (pnlOf(t) || 0), 0);
  const today = trades.filter((t) => t.status === "closed" && isToday(t.exitAt));
  const real = today.reduce((s, t) => s + (t.pnl || 0), 0);
  const list = tab === "open" ? open : tab === "pending" ? pend : done;
  const a = acct || { capital: 0, balance: 0, available: 0, blocked: 0, booked: 0, fees: 0, orders: 0, brokerage: 0 };
  const equity = a.balance + unreal, ret = a.capital ? (equity - a.capital) / a.capital * 100 : 0;
  body.innerHTML = `<div class="pt-cap"><div><small>Equity</small><b>₹${fmt(equity)}</b><small class="${cls(ret)}">${ret >= 0 ? "+" : ""}${fmt(ret)}%</small></div>
      <div><small>Available</small><b>₹${fmt(a.available)}</b><small>blocked ₹${fmt(a.blocked)}</small></div>
      <div title="Starting capital (⋯ → Set capital)"><small>Capital</small><b>₹${fmt(a.capital, 0)}</b><small>fees ₹${fmt(a.fees)}</small></div></div>
    <div class="pt-tot"><div><small>Open P&L</small><b class="${cls(unreal)}">${money(unreal)}</b></div>
      <div><small>Booked today</small><b class="${cls(real)}">${money(real)}</b></div>
      <div title="All booked P&L since capital was set, before ₹${a.brokerage} × ${a.orders} orders brokerage"><small>Booked total</small><b class="${cls(a.booked)}">${money(a.booked)}</b></div></div>
    ${engNote ? `<p class="dn pt-engnote">⚠ ${esc(engNote)}</p>` : ""}
    <div class="tabs pt-ptabs">${[["pending", "Pending", pend], ["open", "Open", open], ["closed", "Closed", done]].map(([k, n, l]) => `<button data-tab="${k}" class="${tab === k ? "on" : ""}">${n}${l.length ? `<span class="pt-cnt pt-cnt-${k}">${l.length}</span>` : ""}</button>`).join("")}</div>
    ${list.length ? list.slice(0, 200).map(row).join("") : `<p class="muted sp-empty">${tab === "open" ? "No open paper trades. Use ＋, the Trade button, or Shift + P on a chart." : tab === "pending" ? "No pending orders." : "No closed trades."}</p>`}`;
}
const ts = (x) => (x ? new Date(x * 1000).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "");
function times(t) {     // buy and sell time stamps of every trade
  const inSide = t.side === "buy" ? "Buy" : "Sell", outSide = t.side === "buy" ? "Sell" : "Buy";
  const parts = [];
  if (t.status === "pending") parts.push(`Placed ${ts(t.createdAt)}`);
  if (t.entryAt) parts.push(`${inSide} ${ts(t.entryAt)} @ ${fmt(t.entry)}`);
  if (t.status === "closed") parts.push(`${outSide} ${ts(t.exitAt)} @ ${fmt(t.exit)}`);
  if (t.status === "cancelled") parts.push(`Cancelled ${ts(t.exitAt)}`);
  return parts.length ? `<div class="pt-ts">${parts.map((p) => `<span>${p}</span>`).join("")}</div>` : "";
}
function condLine(t) {  // "Index Close" trades: the index condition, its trigger candle and the index SL / target
  const c = t.engine === "server" && t.cond;
  if (!c) return "";
  const trig = (t.events || []).find((e) => e.e === "triggered");
  const parts = [`⚡ When ${esc(c.under)} ${TFN(c.tf)} closes ${c.dir} ${fmt(c.level)}`];
  if (c.signal) parts.push(`triggered ${ts(c.triggeredAt).split(", ").pop()} @ close ${fmt(c.signal.c)} (H ${fmt(c.signal.h)} L ${fmt(c.signal.l)})`);
  else if (t.status === "pending") parts.push("waiting for candle close");
  const r = t.rules || {}, slm = r.sl?.mode, tgm = r.target?.mode;
  const slTxt = { prevLow: "prev candle " + (bullOf(t.side, t.symbol.endsWith("CE") ? "CE" : "PE") ? "low" : "high"), prevClose: "prev candle close", index: "index level", premium: "option premium", none: "none" }[slm] || "none";
  const tgTxt = { range: `${fmt(r.target?.k, 1)}× trigger candle range`, index: "index level", premium: "option premium", none: "none" }[tgm] || "none";
  const lv = (now, first) => now != null ? (first != null && first !== now ? ` ${fmt(first)} → ${fmt(now)}` : ` ${fmt(now)}`) : "";
  parts.push(`iSL: ${slTxt}${slm === "premium" || slm === "none" ? "" : lv(t.idxSl, trig?.idxSl)} (on ${TFN(c.tf)} close)`);
  parts.push(`iTGT: ${tgTxt}${tgm === "premium" || tgm === "none" ? "" : lv(t.idxTarget, trig?.idxTarget)}`);
  return `<div class="pt-cond">${parts.map((p) => `<span>${p}</span>`).join("")}</div>`;
}
function row(t) {
  const px = ltpOf(t.symbol), p = pnlOf(t, px), base = t.entry ? t.entry * t.qty : null;
  const st = t.status === "pending" ? `${pendingText(t)} · waiting` : t.status === "cancelled" ? `Cancelled${t.exitReason && t.exitReason !== "cancelled" ? ` (${{ expired: "expired", invalidated: "SL before fill", missed: "target before fill" }[t.exitReason] || t.exitReason})` : ""}` :
    t.status === "closed" ? `${fmt(t.entry)} → ${fmt(t.exit)} · ${{ sl: "SL hit", target: "Target hit", limit: "Exit limit", market: "Exited" }[t.exitReason] || t.exitReason}` :
    `${fmt(t.entry)} → <b>${fmt(px)}</b>`;
  const ix = t.engine === "server" && (t.status === "open" || t.status === "pending") ? `<span class="pt-chips">${t.cond?.phase === "armed" ? `<i data-a="level" title="Trigger level">⚡ ${esc(t.cond.under)} ${t.cond.dir} ${fmt(t.cond.level)}</i>` : ""}${t.idxSl != null ? `<i class="dn" data-a="idxSl" title="Index SL (candle close)">iSL ${fmt(t.idxSl)}</i>` : ""}${t.idxTarget != null ? `<i class="up" data-a="idxTarget" title="Index target">iTGT ${fmt(t.idxTarget)}</i>` : ""}</span>` : "";
  const chips = t.status === "open" || t.status === "pending" ? ix + `<span class="pt-chips">${t.sl != null ? `<i class="dn" data-a="sl">SL ${fmt(t.sl)}</i>` : '<i data-a="sl">+ SL</i>'}${t.target != null ? `<i class="up" data-a="target">TGT ${fmt(t.target)}</i>` : '<i data-a="target">+ TGT</i>'}${t.exitLimit != null ? `<i data-a="exitLimit">Exit @ ${fmt(t.exitLimit)}</i>` : ""}</span>` : "";
  const acts = t.status === "open" ? `<button data-a="exitLimit" title="Exit at a limit price">Exit limit</button><button data-a="exit" class="pt-x" title="Exit now at market">Exit</button>`
    : t.status === "pending" ? '<button data-a="exit" class="pt-x" title="Cancel the limit entry">Cancel</button>' : '<button data-a="del" title="Delete">✕</button>';
  return `<div class="pt-row ${t.status}" data-id="${t.id}">
    <div class="pt-r1"><b class="${t.side === "buy" ? "up" : "dn"}">${t.side === "buy" ? "B" : "S"} ${t.qty}</b> <b class="pt-sym" data-a="pick" title="Open chart: ${esc(t.symbol)}">${esc(t.symbol)}</b>
      <button data-a="eye" class="pt-eye ${t.show ? "on" : ""}" title="${t.show ? "Hide from chart" : "Show on chart"}">${t.show ? "👁" : "◌"}</button>
      <span class="pt-pnl ${cls(p)}">${p == null ? "" : money(p)}${p != null && base ? `<small> ${fmt(p / base * 100, 1)}%</small>` : ""}</span></div>
    <div class="pt-r2 muted">${st}</div>${condLine(t)}${times(t)}${chips}<div class="pt-acts">${acts}</div></div>`;
}
function onPanelClick(e) {
  const tb = e.target.closest("[data-tab]"); if (tb) { tab = tb.dataset.tab; render(); return; }
  const r = e.target.closest(".pt-row"); if (!r) return;
  const t = trades.find((x) => x.id === r.dataset.id); const a = e.target.closest("[data-a]")?.dataset.a;
  if (!t || !a) return;
  if (a === "pick") app.pick(t.symbol);
  else if (a === "eye") act(t, () => api(`/trades/${t.id}`, { method: "PATCH", body: { show: !t.show } }));
  else if (["sl", "target", "exitLimit", "idxSl", "idxTarget", "level"].includes(a)) modify(t, a);
  else if (a === "exit") {
    if (!document.body.classList.contains("m")) exitMarket(t);       // phones: confirm first (easy to mis-tap)
    else LTVSettings.confirm(`${t.status === "pending" ? "Cancel" : "Exit"} ${label(t)}${t.status === "pending" ? "" : " at market"}?`,
      { title: t.status === "pending" ? "Cancel order" : "Exit trade", ok: t.status === "pending" ? "Cancel order" : "Exit", danger: true }).then((ok) => ok && exitMarket(t));
  }
  else if (a === "del") api(`/trades/${t.id}`, { method: "DELETE" }).then(reload).catch((ex) => app.toast(ex.message));
}

// ------------------------------------------------------------------ chart lines (read by every chart, also iframes)
function linesFor(sym) {
  const out = [];
  for (const t of trades) {
    if (!t.show || !(t.status === "open" || t.status === "pending")) continue;
    if (t.symbol === sym) {
      const px = ltpOf(t.symbol), p = pnlOf(t, px), lead = `${t.side === "buy" ? "BUY" : "SELL"} ${t.qty}`;
      if (t.status === "pending" && t.band?.lo != null) {
        out.push({ id: t.id, k: "bandHi", price: t.band.hi, color: "#2962ff", style: 2, title: `${lead} RANGE HI` }, { id: t.id, k: "bandLo", price: t.band.lo, color: "#2962ff", style: 2, title: `${lead} RANGE LO` });
      } else if (t.status === "pending" && t.limit != null) out.push({ id: t.id, k: "limit", price: t.limit, color: "#2962ff", style: 2, title: `${lead} LMT` });
      else out.push({ id: t.id, k: "entry", price: t.entry, color: p == null ? "#2962ff" : p >= 0 ? "#089981" : "#f23645", style: 0, width: 2, title: `${lead} ${p == null ? "" : money(p)}` });
      const ref = t.entry ?? t.limit, at = (v) => money(sign(t) * (v - ref) * t.qty);
      if (t.sl != null) out.push({ id: t.id, k: "sl", price: t.sl, color: "#f23645", style: 2, title: `SL ${at(t.sl)}`, drag: true });
      if (t.target != null) out.push({ id: t.id, k: "target", price: t.target, color: "#089981", style: 2, title: `TGT ${at(t.target)}`, drag: true });
      if (t.exitLimit != null) out.push({ id: t.id, k: "exitLimit", price: t.exitLimit, color: "#ff9800", style: 2, title: `EXIT LMT ${at(t.exitLimit)}`, drag: true });
    }
    if (t.engine === "server" && t.cond && t.cond.under === sym && t.symbol !== sym) {      // index trigger / index SL / index target on the underlying
      const m = FNO_RE.exec(t.symbol), nm = m ? `${m[3]} ${m[4]}` : t.symbol;
      if (t.cond.phase === "armed") out.push({ id: t.id, k: "level", price: t.cond.level, color: "#ff9800", style: 2, title: `⚡ ${t.side === "buy" ? "BUY" : "SELL"} ${nm} ${TFN(t.cond.tf)} close ${t.cond.dir}`, drag: true });
      if (t.idxSl != null) out.push({ id: t.id, k: "idxSl", price: t.idxSl, color: "#f23645", style: 2, title: `iSL ${nm} (close)`, drag: true });
      if (t.idxTarget != null) out.push({ id: t.id, k: "idxTarget", price: t.idxTarget, color: "#089981", style: 2, title: `iTGT ${nm}`, drag: true });
    }
    if (t.symbol === sym) continue;
    if (t.under === sym && t.spot && t.symbol !== sym && t.status === "open" && !(t.engine === "server" && t.cond)) {   // option trade drawn on its underlying at the entry spot
      const p = pnlOf(t), m = FNO_RE.exec(t.symbol);
      out.push({ id: t.id, k: "spot", price: t.spot, color: p == null ? "#787b86" : p >= 0 ? "#089981" : "#f23645", style: 1,
        title: `${t.side === "buy" ? "▲" : "▼"} ${m ? `${m[3]} ${m[4]}` : t.symbol} ×${t.qty} ${p == null ? "" : money(p)}` });
    }
  }
  return out;
}

// ------------------------------------------------------------------ sticky alerts: stay on screen (and across reloads) until cleared with confirmation
let sticky = store("ltv.sticky", []), stickyMin = store("ltv.stickyMin", false);
const stickBox = document.createElement("div");
stickBox.id = "stickyAlerts";
document.body.appendChild(stickBox);
function stick(text, ref) {
  sticky.unshift({ id: Date.now().toString(36) + Math.random().toString(36).slice(2, 5), t: Date.now() / 1000, text: String(text).slice(0, 300), ref });
  sticky = sticky.slice(0, 100); stickyMin = false; keep("ltv.sticky", sticky); keep("ltv.stickyMin", false); paintSticky();
}
function paintSticky() {
  stickBox.classList.toggle("hidden", !sticky.length);
  if (!sticky.length) { stickBox.innerHTML = ""; return; }
  const when = (t) => new Date(t * 1000).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  stickBox.innerHTML = `<div class="sa-head"><b>🔔 Alerts ${sticky.length}</b><span class="spacer"></span>
    <button data-a="min" title="${stickyMin ? "Expand" : "Minimise"}">${stickyMin ? "▴" : "▾"}</button><button data-a="all" title="Clear all alerts">Clear all</button></div>` +
    (stickyMin ? "" : `<div class="sa-list">${sticky.map((a) => `<div class="sa-it" data-id="${a.id}"><div><div>${esc(a.text)}</div><small>${when(a.t)}</small></div><button data-a="x" title="Clear this alert">✕</button></div>`).join("")}</div>`);
}
stickBox.onclick = (e) => {
  const a = e.target.closest("[data-a]")?.dataset.a, it = e.target.closest(".sa-it");
  if (a === "min") { stickyMin = !stickyMin; keep("ltv.stickyMin", stickyMin); paintSticky(); return; }
  if (a === "all") { LTVSettings.confirm(sticky.length > 1 ? `Clear all ${sticky.length} alerts?` : "Clear this alert?", { title: "Clear alerts", ok: "Clear all", danger: true }).then((ok) => { if (ok) { sticky = []; keep("ltv.sticky", sticky); paintSticky(); } }); return; }
  if (a === "x" && it) { const id = it.dataset.id; LTVSettings.confirm("Clear this alert?", { title: "Clear alert", ok: "Clear", danger: true }).then((ok) => { if (ok) { sticky = sticky.filter((x) => x.id !== id); keep("ltv.sticky", sticky); paintSticky(); } }); return; }
  if (it) { const ref = sticky.find((x) => x.id === it.dataset.id)?.ref, t = trades.find((x) => x.id === ref); if (t) { side.show("trades"); app.pick(t.symbol); } }
};
paintSticky();

// ------------------------------------------------------------------ entry points
const btn = document.createElement("button");
btn.id = "tradeBtn"; btn.className = "tb-txt"; btn.title = "Paper trade (Shift + P)";
btn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17l5-5 4 4 7-8"/><path d="M15 8h5v5"/></svg><span>Trade</span>';
btn.onclick = () => openTicket();
($("#replayBtn") || $("#editorBtn"))?.after(btn);
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey || !e.shiftKey || e.key.toLowerCase() !== "p") return;
  if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.querySelector("dialog[open]")) return;
  e.preventDefault(); openTicket();
}, true);
side.pane("trades")?.addEventListener("click", onPanelClick);

window.LTVTrade = {
  openTicket, linesFor, setLevel, onQuotes, render, reload, stick, quick,
  open: () => trades.filter((t) => t.status === "open" || t.status === "pending"), pnlOf, money,
  symbols: () => [...new Set(trades.filter((t) => t.status === "open" || t.status === "pending").flatMap((t) => [t.symbol, t.under].filter(Boolean)))],
};
reload().then(migrateOldOrders).then(() => app.sendWatch());
})();
