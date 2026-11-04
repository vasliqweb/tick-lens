/* Phone / small-touch-screen layer. Adds body.m and rearranges the existing desktop UI:
   compact top bar, bottom tab bar (Chart · Watchlist · Indicators · Trade · More), bottom sheets,
   touch drawing helpers and a paper-trade positions strip. Desktop (no body.m) is untouched:
   every rule in style.css for this layer is scoped to body.m. */
(() => {
"use strict";
if (+new URLSearchParams(location.search).get("slot") > 0) return;      // embedded chart frames
const app = window.LTVApp, side = window.LTVSide;
if (!app || !side) return;
const $ = (s, r = document) => r.querySelector(s);
const MQ = matchMedia("(max-width: 768px), (pointer: coarse) and (max-height: 500px)");
const store = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const keep = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } };
const svg = (d, s = 24) => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const I = {
  chart: svg('<path d="M7 4v3M7 17v3M17 4v5M17 15v5"/><rect x="5" y="7" width="4" height="10" rx="1"/><rect x="15" y="9" width="4" height="6" rx="1"/>'),
  list: svg('<path d="M6 4h12v17l-6-3.5L6 21z"/><path d="M9 9h6M9 12.5h6"/>'),
  ind: svg('<path d="M3 20h18"/><path d="M4 12l5-5 4 3 7-6"/><path d="M6 17v-3M10 17v-5M14 17v-4M18 17V9"/>'),
  trade: svg('<path d="M4 17l5-5 4 4 7-8"/><path d="M15 8h5v5"/>'),
  more: svg('<circle cx="5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="19" cy="12" r="1.3" fill="currentColor"/>'),
  pencil: svg('<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M14 6l3 3"/>'),
  close: svg('<path d="M6 6l12 12M18 6L6 18"/>'),
};

// ------------------------------------------------------------------ shell: tab bar, scrim, generic sheet
const tabs = document.createElement("nav");
tabs.id = "mTabs";
tabs.innerHTML = [["chart", "Chart"], ["watchlist", "Watchlist"], ["ind", "Indicators"], ["trade", "Trade"], ["more", "More"]]
  .map(([k, t]) => `<button data-t="${k}">${I[k === "watchlist" ? "list" : k]}<span>${t}</span></button>`).join("");
document.body.appendChild(tabs);
const scrim = document.createElement("div");
scrim.id = "mScrim";
document.body.appendChild(scrim);
const sheet = document.createElement("section");
sheet.id = "mSheet";
sheet.innerHTML = '<div class="m-grab"><i></i></div><div class="m-sh-head"><b></b><span class="spacer"></span><span class="m-sh-tools"></span><button class="m-x" title="Close">' + I.close + '</button></div><div class="m-sh-body"></div>';
document.body.appendChild(sheet);
const aside = $("#watchlist");

let cur = null;                    // open tab: null (chart) | watchlist | trade | more | tf | side:<pane>
const isM = () => document.body.classList.contains("m");
function paintTabs() {
  const k = cur == null ? "chart" : cur === "trade" || cur === "side:trades" ? "trade" : cur.startsWith("side:") || cur === "more" ? (cur === "side:watchlist" ? "watchlist" : "more") : cur;
  tabs.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.t === k));
}
let restore = null;                // put moved nodes back when the generic sheet closes
function closeAll() {
  cur = null;
  aside.classList.remove("m-on");
  sheet.classList.remove("m-on");
  scrim.classList.remove("m-on");
  if (restore) { restore(); restore = null; }
  paintTabs();
  window.dispatchEvent(new Event("resize"));
}
function openSide(pane) {          // sidebar panel (watchlist, trades, alerts, news…) as a bottom sheet
  if (restore) { restore(); restore = null; }
  sheet.classList.remove("m-on");
  side.show(pane);
  aside.classList.add("m-on"); scrim.classList.add("m-on");
  cur = "side:" + pane; paintTabs();
}
function openSheet(id, title, fill, tools = "") {   // generic sheet; fill(body) may return a restore function
  if (restore) { restore(); restore = null; }
  aside.classList.remove("m-on");
  $(".m-sh-head b", sheet).textContent = title;
  $(".m-sh-tools", sheet).innerHTML = tools;
  const body = $(".m-sh-body", sheet);
  body.innerHTML = "";
  restore = fill(body) || null;
  sheet.classList.add("m-on"); scrim.classList.add("m-on");
  cur = id; paintTabs();
}
scrim.onclick = closeAll;
$(".m-x", sheet).onclick = closeAll;

// swipe a sheet down by its grab bar / header to close it
function swipeClose(el, handleSel) {
  let y0 = null, dy = 0;
  el.addEventListener("pointerdown", (e) => {
    if (!isM() || !e.target.closest(handleSel)) return;
    y0 = e.clientY; dy = 0; el.style.transition = "none";
  });
  window.addEventListener("pointermove", (e) => {
    if (y0 == null) return;
    dy = Math.max(0, e.clientY - y0);
    el.style.transform = `translateY(${dy}px)`;
  });
  const end = () => {
    if (y0 == null) return;
    y0 = null; el.style.transition = ""; el.style.transform = "";
    if (dy > 70) closeAll();
  };
  window.addEventListener("pointerup", end); window.addEventListener("pointercancel", end);
}
swipeClose(sheet, ".m-grab, .m-sh-head");
const grab = document.createElement("div");
grab.className = "m-grab"; grab.innerHTML = "<i></i>";
aside.prepend(grab);
swipeClose(aside, ".m-grab, .sp-head, .wl-head");

// ------------------------------------------------------------------ compact top bar: timeframe button
const tfBtn = document.createElement("button");
tfBtn.id = "mTfBtn";
$("#symbolBtn").after(tfBtn);
const tfLabel = () => (app.TFS.find(([, s]) => s === app.A().S.tf) || ["?"])[0];
const paintTf = () => { tfBtn.innerHTML = `<span>${tfLabel()}</span><small>▾</small>`; };
new MutationObserver(paintTf).observe($("#tfs"), { childList: true, subtree: true, attributes: true });
paintTf();
tfBtn.onclick = () => {
  if (cur === "tf") { closeAll(); return; }
  openSheet("tf", "Timeframe", (body) => {
    const tfs = $("#tfs"), home = tfs.parentElement, next = tfs.nextSibling;
    body.appendChild(tfs);
    tfs.onclick = (e) => { if (e.target.closest("button")) setTimeout(closeAll, 120); };
    return () => { tfs.onclick = null; home.insertBefore(tfs, next); };
  });
};

// ------------------------------------------------------------------ "More" sheet: everything the compact bar hides
const sideBtn = (p, label) => ({ label, icon: $(`#rail [data-p="${p}"]`)?.innerHTML || "", run: () => openSide(p) });
const PLUG = svg('<path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4"/>', 26);
const clickBtn = (sel, label, iconSel) => ({ label, icon: $(iconSel || sel)?.querySelector("svg")?.outerHTML || PLUG, run: () => { closeAll(); $(sel)?.click(); }, sel });
function moreItems() {
  return [
    sideBtn("alerts", "Alerts"), sideBtn("news", "News"), sideBtn("tree", "Objects"), sideBtn("tech", "Technicals"),
    sideBtn("hot", "Hotlists"), sideBtn("market", "Markets"), sideBtn("calendar", "Calendar"), sideBtn("notif", "Notifications"),
    sideBtn("cache", "Data cache"), sideBtn("help", "Help"),
    clickBtn("#chartTypeBtn", "Chart type"), clickBtn("#chartSetBtn", "Chart settings"), clickBtn("#themeBtn", "Theme"),
    clickBtn("#editorBtn", "Script editor"), clickBtn("#replayBtn", "Replay"), clickBtn("#saveMenuBtn", "Layouts", "#saveMenuBtn"),
    clickBtn("#layoutBtn", "Multi-chart"), clickBtn("#bzBtn", "Breeze"),
  ].filter((x) => !x.sel || $(x.sel));
}
function openMore() {
  if (cur === "more") { closeAll(); return; }
  openSheet("more", "More", (body) => {
    const items = moreItems();
    body.innerHTML = `<div class="m-grid">${items.map((x, i) => `<button data-i="${i}">${x.icon}<span>${x.label}</span></button>`).join("")}</div>`;
    body.onclick = (e) => { const b = e.target.closest("[data-i]"); if (b) items[+b.dataset.i].run(); };
  });
}

// ------------------------------------------------------------------ tab actions
tabs.onclick = (e) => {
  const b = e.target.closest("button[data-t]"); if (!b) return;
  const t = b.dataset.t;
  if (t === "chart") closeAll();
  else if (t === "watchlist") cur === "side:watchlist" ? closeAll() : openSide("watchlist");
  else if (t === "ind") { closeAll(); $("#indBtn").click(); }
  else if (t === "trade") cur === "side:trades" ? closeAll() : openSide("trades");
  else if (t === "more") openMore();
};
// picking a symbol in the watchlist sheet goes straight back to the chart
aside.addEventListener("click", (e) => {
  if (!isM() || cur !== "side:watchlist") return;
  if (e.target.closest(".wl-item") && !e.target.closest("button")) setTimeout(closeAll, 80);
});

// ------------------------------------------------------------------ steppers: − / + around number inputs (indicator settings, trade ticket)
function stepperize(root) {
  if (!isM()) return;
  root.querySelectorAll('input[type="number"]:not([data-mstep])').forEach((inp) => {
    inp.dataset.mstep = "1";
    const wrap = document.createElement("span");
    wrap.className = "m-step";
    inp.replaceWith(wrap);
    const mk = (t, k) => { const b = document.createElement("button"); b.type = "button"; b.textContent = t; b.dataset.k = k; return b; };
    wrap.append(mk("−", -1), inp, mk("+", 1));
    wrap.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-k]"); if (!b || inp.disabled) return;
      e.preventDefault();
      const step = +inp.step > 0 ? +inp.step : 1, dec = (String(inp.step).split(".")[1] || "").length;
      let v = (+inp.value || 0) + step * +b.dataset.k;
      if (inp.min !== "" && v < +inp.min) v = +inp.min;
      if (inp.max !== "" && v > +inp.max) v = +inp.max;
      inp.value = dec ? v.toFixed(dec) : String(Math.round(v));
      inp.dispatchEvent(new Event("input", { bubbles: true })); inp.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
}

// ------------------------------------------------------------------ indicators: favourites + recent at the top of the list, legend name -> settings
const IND_FAV = "ltv.m.indFav", IND_REC = "ltv.m.indRecent";
const indKey = (it) => it.querySelector("small")?.textContent || it.textContent;
let indObs = null;
function decorateIndList() {
  const box = $("#indList");
  if (!isM() || !box) return;
  try {
    box.querySelectorAll(".m-indgrp, .m-indgrp-it").forEach((x) => x.remove());
    const fav = store(IND_FAV, []), rec = store(IND_REC, []);
    const items = [...box.querySelectorAll(".it")];
    const byKey = new Map(items.map((it) => [indKey(it), it]));
    for (const it of items) {
      if (!it.querySelector(".m-star")) it.insertAdjacentHTML("afterbegin", '<button type="button" class="m-star" title="Favourite">☆</button>');
      const on = fav.includes(indKey(it)), st = it.querySelector(".m-star");
      st.textContent = on ? "★" : "☆"; st.classList.toggle("on", on);
    }
    const group = (title, keys) => {
      const its = keys.map((k) => byKey.get(k)).filter(Boolean);
      if (!its.length) return "";
      return `<div class="grp m-indgrp">${title}</div>` + its.map((it) => `<div class="it m-indgrp-it" data-src="${app.esc(indKey(it))}">${it.innerHTML}</div>`).join("");
    };
    box.insertAdjacentHTML("afterbegin", group("Favourites", fav) + group("Recent", rec.filter((k) => !fav.includes(k)).slice(0, 5)));
  } finally { indObs?.takeRecords(); }      // our own edits must not re-trigger the observer
}
{
  const box = $("#indList");
  indObs = new MutationObserver(() => decorateIndList());
  indObs.observe(box, { childList: true });
  box.addEventListener("click", (e) => {
    if (!isM()) return;
    const star = e.target.closest(".m-star");
    const it = e.target.closest(".it"); if (!it) return;
    const key = it.dataset.src || indKey(it);
    if (star) {
      e.stopPropagation(); e.preventDefault();
      const fav = store(IND_FAV, []);
      keep(IND_FAV, fav.includes(key) ? fav.filter((k) => k !== key) : [key, ...fav]);
      decorateIndList(); return;
    }
    keep(IND_REC, [key, ...store(IND_REC, []).filter((k) => k !== key)].slice(0, 8));
    if (it.dataset.src) {        // a copy in Favourites / Recent: run the real row's handler
      e.stopPropagation();
      [...box.querySelectorAll(".it:not(.m-indgrp-it)")].find((x) => indKey(x) === key)?.click();
    }
  }, true);
}
// phones: don't pop the keyboard over the list when the dialog opens (tap the search box to type)
new MutationObserver(() => { if (isM() && $("#indDlg").open && document.activeElement === $("#indSearch")) $("#indSearch").blur(); })
  .observe($("#indDlg"), { attributes: true, attributeFilter: ["open"] });
// tap an indicator name in the chart legend: open its settings
$("#legendInds").addEventListener("click", (e) => {
  if (!isM()) return;
  const t = e.target.closest(".lg-ind .t"); if (!t) return;
  t.closest(".lg-ind").querySelector('[data-a="set"]')?.click();
});
// settings dialog: steppers on number inputs
{
  const f = $("#setForm"), ob = new MutationObserver(() => { stepperize(f); ob.takeRecords(); });
  ob.observe(f, { childList: true, subtree: true });
}

// ------------------------------------------------------------------ drawing: pencil button, tool picker overlay, hint chip, magnifier loupe
const D = () => window.__ltv?.draw, TOOLS = window.LTVDraw?.TOOLS || {};
const drawing = () => { const t = D()?.state?.tool; return !!t && (TOOLS[t] ? TOOLS[t].group !== "cursor" : t === "measure" || t === "zoom"); };
const fab = document.createElement("button");
fab.id = "mDrawFab"; fab.title = "Drawing tools"; fab.innerHTML = I.pencil;
const hint = document.createElement("div");
hint.id = "mDrawHint";
const chartWrap = $("#chartWrap");
chartWrap.append(fab, hint);
const drawBar = $("#drawBar");
function setDrawOpen(on) {
  document.body.classList.toggle("m-draw", on);
  fab.classList.toggle("open", on);
}
function paintDraw() {
  const st = D()?.state; if (!st) return;
  const on = drawing(), t = TOOLS[st.tool];
  fab.classList.toggle("on", on);
  hint.classList.toggle("hidden", !on);
  if (on) {
    const n = t?.n, what = st.tool === "measure" ? "Tap start, then end" : n === 0 ? "Drag to draw" : n === 1 ? "Tap to place" : n === -1 ? "Tap points, double-tap to finish" : `Tap ${n} points or drag`;
    hint.innerHTML = `<b>${app.esc(t?.name || st.tool)}</b><span>${what}</span><button data-a="x" title="Cancel">✕</button>`;
  }
}
fab.onclick = (e) => { e.stopPropagation(); setDrawOpen(!document.body.classList.contains("m-draw")); };
fab.addEventListener("pointerdown", (e) => e.stopPropagation(), true);
hint.addEventListener("pointerdown", (e) => e.stopPropagation(), true);
hint.onclick = (e) => { if (e.target.closest('[data-a="x"]')) { const st = D()?.state; D()?.setTool(st?.cursor || "cross"); paintDraw(); } };
// picking a tool closes the picker so the whole chart is free for the finger
let toolBefore = null;
const pickStart = () => { toolBefore = D()?.state?.tool; };
const pickEnd = () => setTimeout(() => { if (isM() && D()?.state?.tool !== toolBefore && drawing()) setDrawOpen(false); paintDraw(); }, 30);
drawBar?.addEventListener("pointerdown", pickStart, true); drawBar?.addEventListener("click", pickEnd);
$("#drawFly")?.addEventListener("pointerdown", pickStart, true); $("#drawFly")?.addEventListener("click", pickEnd);
setInterval(() => { if (isM()) paintDraw(); }, 400);       // tool resets to the cursor after a drawing is placed
// tapping the chart while the picker is open closes it
chartWrap.addEventListener("pointerdown", (e) => { if (isM() && document.body.classList.contains("m-draw") && !e.target.closest("#mDrawFab")) setDrawOpen(false); }, true);

// magnifier: shows what is under the finger while placing or dragging a drawing / trade line
const loupe = document.createElement("canvas");
loupe.id = "mLoupe";
document.body.appendChild(loupe);
const LS = 120, ZOOM = 2;
let lp = null;
function paintLoupe(x, y) {
  const r = window.devicePixelRatio || 1, g = loupe.getContext("2d");
  if (loupe.width !== LS * r) { loupe.width = loupe.height = LS * r; }
  const half = LS / ZOOM / 2;
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.fillStyle = getComputedStyle(document.body).getPropertyValue("--bg") || "#131722";
  g.fillRect(0, 0, loupe.width, loupe.height);
  for (const c of chartWrap.querySelectorAll("canvas")) {
    const b = c.getBoundingClientRect();
    if (!b.width || !c.width || b.right < x - half || b.left > x + half || b.bottom < y - half || b.top > y + half) continue;
    const kx = c.width / b.width, ky = c.height / b.height;
    try { g.drawImage(c, (x - half - b.left) * kx, (y - half - b.top) * ky, 2 * half * kx, 2 * half * ky, 0, 0, loupe.width, loupe.height); } catch { /* tainted / empty */ }
  }
  g.strokeStyle = "#ff9800"; g.lineWidth = r;
  g.beginPath(); g.moveTo(loupe.width / 2, loupe.height / 2 - 10 * r); g.lineTo(loupe.width / 2, loupe.height / 2 + 10 * r);
  g.moveTo(loupe.width / 2 - 10 * r, loupe.height / 2); g.lineTo(loupe.width / 2 + 10 * r, loupe.height / 2); g.stroke();
  const top = y - LS - 40 < 50 ? y + 40 : y - LS - 40;
  loupe.style.left = Math.max(6, Math.min(innerWidth - LS - 6, x - LS / 2)) + "px";
  loupe.style.top = top + "px";
}
const wantLoupe = () => drawing() || window.__ltv?.chart?.options?.().handleScroll === false;   // drawing tool, or a drawing / trade line is being dragged
chartWrap.addEventListener("pointerdown", (e) => { if (isM() && e.pointerType !== "mouse") lp = { id: e.pointerId }; }, true);
window.addEventListener("pointermove", (e) => {
  if (!lp || e.pointerId !== lp.id) return;
  if (!wantLoupe()) { loupe.classList.remove("on"); return; }
  loupe.classList.add("on");
  cancelAnimationFrame(lp.raf); const { clientX: x, clientY: y } = e;
  lp.raf = requestAnimationFrame(() => paintLoupe(x, y));
}, true);
const loupeOff = () => { lp = null; loupe.classList.remove("on"); };
window.addEventListener("pointerup", loupeOff, true); window.addEventListener("pointercancel", loupeOff, true);

// ------------------------------------------------------------------ paper trading: positions strip, Buy / Sell bar, ticket steppers, swipe to exit
const TR = () => window.LTVTrade;
const strip = document.createElement("div");
strip.id = "mPos"; strip.className = "hidden";
$("#layout").after(strip);
function paintStrip() {
  if (!isM() || !TR()?.open) return;
  const open = TR().open(), money = TR().money;
  strip.classList.toggle("hidden", !open.length);
  if (!open.length) { strip.innerHTML = ""; window.dispatchEvent(new Event("resize")); return; }
  const tot = open.reduce((s, t) => s + (TR().pnlOf(t) || 0), 0), c = (v) => (v > 0 ? "up" : v < 0 ? "dn" : "");
  const chips = open.slice(0, 6).map((t) => { const p = TR().pnlOf(t);
    return `<span class="m-pc" data-sym="${app.esc(t.symbol)}"><b class="${t.side === "buy" ? "up" : "dn"}">${t.side === "buy" ? "B" : "S"}</b> ${app.esc(t.symbol)} <i class="${c(p)}">${p == null ? (t.status === "pending" ? "LMT" : "–") : money(p)}</i></span>`; }).join("");
  const was = strip.dataset.n;
  strip.innerHTML = `<button class="m-pos-sum" title="Open paper trades"><small>${open.length} open</small><b class="${c(tot)}">${money(tot)}</b></button><div class="m-pos-list">${chips}</div>`;
  if (was !== String(open.length)) { strip.dataset.n = open.length; window.dispatchEvent(new Event("resize")); }
}
setInterval(paintStrip, 1000);
strip.onclick = (e) => {
  const chip = e.target.closest(".m-pc");
  if (chip && chip.dataset.sym !== app.A().S.symbol) { app.pick(chip.dataset.sym); return; }
  openSide("trades");
};
// Buy / Sell bar at the bottom of the trades sheet
{
  const pane = side.pane("trades");
  if (pane) {
    const bar = document.createElement("div");
    bar.className = "m-tradebar";
    bar.innerHTML = '<button data-s="sell" class="m-sell">Sell</button><button data-s="buy" class="m-buy">Buy</button>';
    pane.appendChild(bar);
    bar.onclick = (e) => {
      const b = e.target.closest("[data-s]"); if (!b) return;
      closeAll(); TR()?.openTicket();
      requestAnimationFrame(() => $(`dialog.pt-dlg[open] .pt-side [data-v="${b.dataset.s}"]`)?.click());
    };
    // swipe a trade row left to exit / cancel it (asks to confirm)
    let sw = null;
    pane.addEventListener("pointerdown", (e) => { const r = e.target.closest(".pt-row.open, .pt-row.pending"); if (isM() && r) sw = { r, x: e.clientX, y: e.clientY, dx: 0 }; });
    pane.addEventListener("pointermove", (e) => {
      if (!sw) return;
      sw.dx = Math.min(0, e.clientX - sw.x);
      if (Math.abs(e.clientY - sw.y) > 30 && sw.dx > -20) { sw.r.style.transform = ""; sw = null; return; }
      sw.r.style.transform = `translateX(${sw.dx}px)`; sw.r.classList.toggle("m-swipe", sw.dx < -80);
    });
    const end = () => {
      if (!sw) return;
      const { r, dx } = sw; sw = null;
      r.style.transform = ""; r.classList.remove("m-swipe");
      if (dx < -80) r.querySelector('[data-a="exit"]')?.click();
    };
    pane.addEventListener("pointerup", end); pane.addEventListener("pointercancel", end);
  }
}
// ticket / modify dialogs: steppers on lots, SL, target, limit
new MutationObserver((ms) => {
  for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1 && n.matches?.("dialog.pt-dlg, dialog")) stepperize(n);
}).observe(document.body, { childList: true });

// ------------------------------------------------------------------ on / off
function apply() {
  const on = MQ.matches;
  if (on === isM()) return;
  if (!on) { closeAll(); setDrawOpen(false); }
  document.body.classList.toggle("m", on);
  if (on && D()?.state && !D().state.magnet) { D().state.magnet = 1; D().renderToolbar?.(); }  // weak magnet by default on phones (not persisted, like desktop)
  window.dispatchEvent(new Event("resize"));
}
MQ.addEventListener?.("change", apply);
apply();

// installable app: the service worker only registers on https or localhost (browsers require a secure origin)
if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});

window.LTVMobile = { isM, closeAll, openSide, openSheet, store, keep, I, stepperize, get cur() { return cur; } };
})();
