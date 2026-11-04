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

// ------------------------------------------------------------------ on / off
function apply() {
  const on = MQ.matches;
  if (on === isM()) return;
  if (!on) closeAll();
  document.body.classList.toggle("m", on);
  window.dispatchEvent(new Event("resize"));
}
MQ.addEventListener?.("change", apply);
apply();

window.LTVMobile = { isM, closeAll, openSide, openSheet, store, keep, I, stepperize, get cur() { return cur; } };
})();
