/* Multi-chart layouts (up to 4 charts): this page's chart is cell "a"; the others are ?slot=N pages in iframes.
   The top bar, watchlist and drawing toolbar act on the active chart; symbol / interval / crosshair / time /
   date range can be synced across the layout. */
(() => {
"use strict";
if (new URLSearchParams(location.search).get("slot")) return;      // embedded charts are not layout hosts
const $ = (s) => document.querySelector(s);
const L = (id, areas) => ({ id, areas, n: new Set(areas.join(" ").split(/\s+/)).size });
const LAYOUTS = [
  [L("1", ["a"])],
  [L("2v", ["a b"]), L("2h", ["a", "b"])],
  [L("3v", ["a b c"]), L("3h", ["a", "b", "c"]), L("3l", ["a b", "a c"]), L("3r", ["a c", "b c"]), L("3b", ["a b", "c c"]), L("3t", ["a a", "b c"])],
  [L("4", ["a b", "c d"]), L("4h", ["a", "b", "c", "d"]), L("4v", ["a b c d"]), L("4l", ["a b", "a c", "a d"]), L("4r", ["a d", "b d", "c d"]),
   L("4t", ["a a a", "b c d"]), L("4b", ["a b c", "d d d"]), L("4m", ["a b d", "a c d"]), L("4ml", ["a c d", "b c d"]), L("4c", ["a a", "b c", "d d"])],
];
const ALL = LAYOUTS.flat();
const SYNC = [["symbol", "Symbol", "Change the symbol of every chart in the layout together"],
  ["interval", "Interval", "Change the interval of every chart together"],
  ["crosshair", "Crosshair", "Show the crosshair at the same time on every chart"],
  ["time", "Time", "Scroll every chart to the same time"],
  ["range", "Date range", "Show the same date range (from and to) on every chart"]];
const LETTERS = "abcd";

// every chart is independent by default; only the crosshair is shared
let st = { v: 2, id: "1", active: 0, sync: { symbol: false, interval: false, crosshair: true, time: false, range: false } };
try {
  const v = JSON.parse(localStorage.getItem("ltv.layout") || "{}");
  if (v.v !== 2) v.sync = { ...(v.sync || {}), time: false, range: false };
  st = { ...st, ...v, v: 2, sync: { ...st.sync, ...(v.sync || {}) } };
} catch { /* */ }
const save = () => { try { localStorage.setItem("ltv.layout", JSON.stringify(st)); } catch { /* */ } };
const grid = $("#grid"), cell0 = $("#chartWrap");
const frames = [null, null, null, null];          // slot -> iframe
const layout = () => ALL.find((x) => x.id === st.id) || ALL[0];

function icon(lay, size = 18) {
  const rows = lay.areas.map((r) => r.split(/\s+/)), R = rows.length, C = rows[0].length, pad = 1.5, w = size - 2 * pad;
  let out = `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.2">`;
  out += `<rect x="${pad}" y="${pad}" width="${w}" height="${w}" rx="2.5"/>`;
  for (const ch of new Set(rows.flat())) {
    let r0 = R, r1 = -1, c0 = C, c1 = -1;
    rows.forEach((row, r) => row.forEach((x, c) => { if (x === ch) { r0 = Math.min(r0, r); r1 = Math.max(r1, r); c0 = Math.min(c0, c); c1 = Math.max(c1, c); } }));
    out += `<rect x="${pad + (c0 / C) * w}" y="${pad + (r0 / R) * w}" width="${((c1 - c0 + 1) / C) * w}" height="${((r1 - r0 + 1) / R) * w}"/>`;
  }
  return out + "</svg>";
}

function api(slot = st.active) {
  if (!slot) return window.LTVChart;
  try { return frames[slot]?.contentWindow?.LTVChart || null; } catch { return null; }
}
function seed(slot) {
  // a new chart starts as a copy of the active one (symbol, interval, style, indicators)
  const key = `ltv.state.${slot}`;
  if (localStorage.getItem(key)) return;
  const src = api() || window.LTVChart, S = src.S;
  const copy = { ...S, indicators: (S.indicators || []).map(({ id, ref, code, inputs, visible, style }) => ({ id, ref, code, inputs, visible, style })) };
  try { localStorage.setItem(key, JSON.stringify(copy)); } catch { /* */ }
}
function apply() {
  const lay = layout();
  grid.style.gridTemplateAreas = lay.areas.map((r) => `"${r}"`).join(" ");
  const rows = lay.areas.length, cols = lay.areas[0].split(/\s+/).length;
  grid.style.gridTemplateRows = `repeat(${rows}, minmax(0, 1fr))`;
  grid.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
  grid.classList.toggle("multi", lay.n > 1);
  cell0.style.gridArea = "a";
  for (let k = 1; k < 4; k++) {
    if (k < lay.n) {
      if (!frames[k]) {
        seed(k);
        const f = document.createElement("iframe");
        f.className = "chart-cell"; f.src = `/?slot=${k}`; f.title = `Chart ${k + 1}`;
        grid.appendChild(f); frames[k] = f;
      }
      frames[k].style.gridArea = LETTERS[k];
    } else if (frames[k]) {
      frames[k].remove(); frames[k] = null;
      try { localStorage.removeItem(`ltv.state.${k}`); } catch { /* */ }
    }
  }
  if (st.active >= lay.n) st.active = 0;
  $("#layoutBtn").innerHTML = icon(lay, 20);
  activate(st.active, true);
  save();
}
function activate(slot, force) {
  if (slot === st.active && !force) return;
  if (slot && !api(slot)) { st.active = slot; markActive(); return; }   // still loading; changed() finishes it
  st.active = slot;
  markActive();
  const a = api();
  window.LTVChart.draw?.setTarget(slot && a?.draw ? a.draw.ctl : null);
  window.LTVChart.renderTop?.();
  save();
}
function markActive() {
  const multi = layout().n > 1;
  cell0.classList.toggle("active-cell", multi && st.active === 0);
  frames.forEach((f, k) => f && f.classList.toggle("active-cell", multi && st.active === k));
}

// ---------------------------------------------------------------- picker
function openPicker() {
  const old = $("#layoutPop");
  if (old) { old.remove(); return; }
  const pop = document.createElement("div");
  pop.id = "layoutPop";
  pop.innerHTML = LAYOUTS.map((row, i) => `<div class="lp-row"><span class="lp-n">${i + 1}</span>` +
    row.map((l) => `<button data-id="${l.id}" class="${l.id === st.id ? "on" : ""}" title="${l.n} chart${l.n > 1 ? "s" : ""}">${icon(l, 22)}</button>`).join("") + "</div>").join("") +
    `<div class="lp-h">SYNC IN LAYOUT</div>` +
    SYNC.map(([k, label, tip]) => `<label class="lp-sync" title="${tip}"><span>${label} <i title="${tip}">i</i></span>` +
      `<input type="checkbox" data-k="${k}" ${st.sync[k] ? "checked" : ""}><span class="tg"></span></label>`).join("");
  document.body.appendChild(pop);
  const r = $("#layoutBtn").getBoundingClientRect();
  pop.style.top = r.bottom + 6 + "px";
  pop.style.left = Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 8)) + "px";
  pop.onclick = (e) => {
    const b = e.target.closest("button[data-id]");
    if (!b) return;
    st.id = b.dataset.id; apply();
    pop.querySelectorAll("button[data-id]").forEach((x) => x.classList.toggle("on", x === b));
  };
  pop.onchange = (e) => {
    const k = e.target.dataset.k; if (!k) return;
    st.sync[k] = e.target.checked;
    if (k === "range" && st.sync.range) st.sync.time = true;
    save();
    // turning a sync on lines every chart up with the active one
    const a = api();
    if (a && st.sync[k] && k === "symbol") eachOther((c) => c.S.symbol !== a.S.symbol && c.setSymbol(a.S.symbol));
    if (a && st.sync[k] && k === "interval") eachOther((c) => c.S.tf !== a.S.tf && c.setTf(a.S.tf));
    pop.querySelectorAll("input[data-k]").forEach((x) => (x.checked = !!st.sync[x.dataset.k]));
  };
}
document.addEventListener("pointerdown", (e) => { if (!e.target.closest("#layoutPop, #layoutBtn")) $("#layoutPop")?.remove(); }, true);
$("#layoutBtn").onclick = openPicker;

// ---------------------------------------------------------------- sync
function charts() { const out = []; for (let k = 0; k < layout().n; k++) { const c = api(k); if (c) out.push(c); } return out; }
function eachOther(fn) { for (const c of charts()) if (c !== api()) fn(c); }
let guard = false;
// ---------------------------------------------------------------- fullscreen: only the chart(s), Esc to leave
const typing = (d = document) => /INPUT|TEXTAREA|SELECT/.test(d.activeElement?.tagName) || d.querySelector("dialog[open]");
function setFs(on) {
  document.documentElement.classList.toggle("fs", on);
  $("#fsBtn").classList.toggle("on", on);
  if (on && !document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
  if (!on && document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
  window.dispatchEvent(new Event("resize"));
}
const toggleFs = () => setFs(!document.documentElement.classList.contains("fs"));
$("#fsBtn").onclick = toggleFs;
document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && document.documentElement.classList.contains("fs")) setFs(false); });
document.addEventListener("keydown", (e) => {
  if (typing()) return;
  if (e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey && e.code === "KeyF") { e.preventDefault(); toggleFs(); }
  else if (e.key === "Escape" && document.documentElement.classList.contains("fs")) setFs(false);   // when the browser refused real fullscreen
});

window.LTVLayout = {
  fullscreen: (key) => { if (key === "toggle") toggleFs(); else if (key === "exit" && document.documentElement.classList.contains("fs")) setFs(false); },
  api: () => api() || window.LTVChart,
  get sync() { return layout().n > 1 ? st.sync : null; },
  activate: (slot) => activate(slot),
  // run fn on the active chart, or on every chart when that kind of sync is on ("all" = always every chart)
  each(kind, fn) {
    const all = kind === "all" || (layout().n > 1 && st.sync[kind]);
    if (!all) return fn(api() || window.LTVChart);
    charts().forEach((c) => fn(c));
  },
  changed(slot) { if (slot === st.active) activate(slot, true); },
  toolbarChanged(slot) { if (slot === st.active) window.LTVChart.draw?.renderToolbar(); },
  crosshair(slot, t, price) {
    if (guard || !st.sync.crosshair) return;
    guard = true;
    for (let k = 0; k < layout().n; k++) if (k !== slot) api(k)?.syncCrosshair(t, api(k).S.symbol === api(slot)?.S.symbol ? price : null);
    guard = false;
  },
  range(slot, from, to) {
    if (guard || !(st.sync.time || st.sync.range)) return;
    guard = true;
    for (let k = 0; k < layout().n; k++) if (k !== slot) api(k)?.syncRange(from, to, st.sync.range);
    guard = false;
  },
};
// ---------------------------------------------------------------- saved layouts (server: /api/layouts)
// A saved layout = the grid + sync options + every chart's state (symbol, interval, style, indicators,
// chart settings). Watchlists, theme and data source stay global.
const GLOBAL_KEYS = ["watchlist", "watchlists", "wlActive", "wlWidth", "theme", "source", "breezeOk", "breezeInit", "volInit", "rpSpeed"];
const TFN = { 60: "1", 180: "3", 300: "5", 900: "15", 1800: "30", 3600: "60", 86400: "D", 604800: "W", 2592000: "M" };
let cur = { id: null, name: "Unnamed", autosave: true };
try { cur = { ...cur, ...JSON.parse(localStorage.getItem("ltv.cur") || "{}") }; } catch { /* */ }
let recent = [];
try { recent = JSON.parse(localStorage.getItem("ltv.recent") || "[]"); } catch { /* */ }
let savedJson = null, saving = false;
const saveCur = () => { try { localStorage.setItem("ltv.cur", JSON.stringify(cur)); localStorage.setItem("ltv.recent", JSON.stringify(recent.slice(0, 6))); } catch { /* */ } };
const newLid = () => (Date.now().toString(36) + Math.random().toString(36).slice(2, 8));
function chartState(key) {
  let s = {};
  try { s = JSON.parse(localStorage.getItem(key) || "{}"); } catch { /* */ }
  for (const k of GLOBAL_KEYS) delete s[k];
  return s;
}
function snapshot() {
  for (const c of charts()) try { c.save(); } catch { /* */ }
  const n = layout().n, charts_ = [chartState("ltv.state")];
  for (let k = 1; k < n; k++) charts_.push(chartState(`ltv.state.${k}`));
  return { layout: { id: st.id, active: st.active, sync: st.sync }, charts: charts_ };
}
const summaryOf = (d) => { const c = d.charts?.[0] || {}; return c.symbol ? `${c.symbol}, ${TFN[c.tf] || c.tf}` : ""; };
function restore(data) {
  // write every chart's state and the grid, then reload so each chart starts cleanly from it
  let host = {};
  try { host = JSON.parse(localStorage.getItem("ltv.state") || "{}"); } catch { /* */ }
  const globals = Object.fromEntries(GLOBAL_KEYS.filter((k) => k in host).map((k) => [k, host[k]]));
  localStorage.setItem("ltv.state", JSON.stringify({ ...(data.charts?.[0] || {}), ...globals }));
  for (let k = 1; k < 4; k++) {
    const c = data.charts?.[k];
    if (c) localStorage.setItem(`ltv.state.${k}`, JSON.stringify(c)); else localStorage.removeItem(`ltv.state.${k}`);
  }
  localStorage.setItem("ltv.layout", JSON.stringify({ v: 2, id: data.layout?.id || "1", active: data.layout?.active || 0, sync: { ...st.sync, ...(data.layout?.sync || {}) } }));
  window.removeEventListener("beforeunload", beforeUnload);
  location.reload();
}
function touchRecent(id) { recent = [id, ...recent.filter((x) => x !== id)].slice(0, 6); saveCur(); }
async function put(id, name, data) {
  const r = await fetch(`/api/layouts/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, summary: summaryOf(data), data }) });
  if (!r.ok) throw new Error(await r.text());
}
function ask(title, value = "", ok = "Save") {
  return new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.innerHTML = `<form method="dialog" class="dlg wl-dlg"><div class="dlg-head"><b></b><button value="cancel">✕</button></div>
      <input name="n" maxlength="60" autocomplete="off" placeholder="Layout name">
      <div class="dlg-foot"><span class="spacer"></span><button value="cancel">Cancel</button><button value="ok" class="primary"></button></div></form>`;
    d.querySelector("b").textContent = title; d.querySelector(".primary").textContent = ok;
    document.body.appendChild(d);
    const inp = d.querySelector("input"); inp.value = value;
    d.onclose = () => { const v = inp.value.trim(); d.remove(); resolve(d.returnValue === "ok" && v ? v : null); };
    d.showModal(); inp.select();
  });
}
const toast = (msg) => { const t = document.createElement("div"); t.className = "ltv-toast"; t.textContent = msg; document.body.appendChild(t); setTimeout(() => t.remove(), 1800); };
async function saveLayout(quiet = false) {
  if (saving) return;
  if (!cur.id) {
    const name = await ask("Save new chart layout", cur.name === "Unnamed" ? "" : cur.name);
    if (!name) return;
    cur.id = newLid(); cur.name = name;
  }
  saving = true;
  try {
    const data = snapshot(), j = JSON.stringify(data);
    await put(cur.id, cur.name, data);
    savedJson = j; touchRecent(cur.id); saveCur();
    if (!quiet) toast(`Layout "${cur.name}" saved`);
  } catch (e) { toast("Save failed: " + (e.message || e)); }
  saving = false;
  paintSave();
}
const dirty = () => !cur.id || JSON.stringify(snapshot()) !== savedJson;
function paintSave() {
  const d = cur.id && savedJson != null && JSON.stringify(snapshot()) !== savedJson;
  $("#saveBtn span").textContent = cur.name;
  $("#saveBtn").classList.toggle("dirty", !!(d && !cur.autosave) || !cur.id);
  $("#saveBtn").title = !cur.id ? "Save layout (Ctrl + S)" : d && !cur.autosave ? "Unsaved changes: save layout (Ctrl + S)" : "Layout saved";
}
async function confirmLeave() {
  if (!cur.id || cur.autosave || !dirty()) return true;
  if (await LTVSettings.confirm(`Save changes to "${cur.name}" first?`, { title: "Unsaved layout", ok: "Save", cancel: "Don't save" })) await saveLayout(true);
  return true;
}
async function openSaved(id) {
  const r = await fetch(`/api/layouts/${id}`);
  if (!r.ok) { toast("Layout not found"); recent = recent.filter((x) => x !== id); saveCur(); return; }
  const doc = await r.json();
  await confirmLeave();
  cur = { ...cur, id, name: doc.name }; touchRecent(id); saveCur();
  restore(doc.data || {});
}
async function listSaved() { try { return await (await fetch("/api/layouts")).json(); } catch { return []; } }
function download() {
  const c = api() || window.LTVChart, { name, text } = c.csv();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" })); a.download = name;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
async function openSaveMenu() {
  const old = $("#savePop");
  if (old) { old.remove(); return; }
  const all = await listSaved(), byId = new Map(all.map((x) => [x.id, x]));
  const rec = recent.map((id) => byId.get(id)).filter(Boolean).slice(0, 5);
  const pop = document.createElement("div");
  pop.id = "savePop"; pop.className = "sp-pop";
  const I = (d) => `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  pop.innerHTML = `
    <div class="sp-it${cur.id && !dirty() ? " dis" : ""}" data-a="save"><span>Save layout</span><kbd>Ctrl + S</kbd></div>
    <label class="lp-sync sp-tg"><span>Autosave</span><input type="checkbox" data-k="autosave" ${cur.autosave ? "checked" : ""}><span class="tg"></span></label>
    <div class="sp-it" data-a="copy">${I('<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M4 16V6a2 2 0 0 1 2-2h10"/>')}<span>Make a copy…</span></div>
    <div class="sp-it" data-a="rename">${I('<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13 7l4 4"/>')}<span>Rename…</span></div>
    <div class="sp-it" data-a="csv">${I('<path d="M12 4v11M7 10l5 5 5-5M4 19h16"/>')}<span>Download chart data…</span></div>
    <div class="sp-sep"></div>
    <div class="sp-it" data-a="new">${I('<path d="M12 5v14M5 12h14"/>')}<span>Create new layout…</span></div>
    ${rec.length ? `<div class="sp-sep"></div><div class="lp-h">RECENTLY USED</div>` + rec.map((x) => `<div class="sp-rec${x.id === cur.id ? " on" : ""}" data-id="${x.id}"><b></b><small></small></div>`).join("") : ""}
    <div class="sp-sep"></div>
    <div class="sp-it" data-a="open">${I('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>')}<span>Open layout…</span><kbd>.</kbd></div>`;
  pop.querySelectorAll(".sp-rec").forEach((el, i) => { el.querySelector("b").textContent = rec[i].name; el.querySelector("small").textContent = rec[i].summary; });
  document.body.appendChild(pop);
  const r = $("#saveGrp").getBoundingClientRect();
  pop.style.top = r.bottom + 6 + "px";
  pop.style.left = Math.max(8, Math.min(r.right - pop.offsetWidth, innerWidth - pop.offsetWidth - 8)) + "px";
  pop.onchange = (e) => { if (e.target.dataset.k === "autosave") { cur.autosave = e.target.checked; saveCur(); paintSave(); if (cur.autosave && cur.id) saveLayout(true); } };
  pop.onclick = async (e) => {
    const rc = e.target.closest(".sp-rec");
    if (rc) { pop.remove(); if (rc.dataset.id !== cur.id) openSaved(rc.dataset.id); return; }
    const it = e.target.closest(".sp-it");
    if (!it || it.classList.contains("dis")) return;
    pop.remove();
    const a = it.dataset.a;
    if (a === "save") saveLayout();
    if (a === "csv") download();
    if (a === "open") openLayoutDialog();
    if (a === "rename") {
      const n = await ask("Rename chart layout", cur.name, "Rename");
      if (n) { cur.name = n; saveCur(); if (cur.id) await saveLayout(true); paintSave(); }
    }
    if (a === "copy") {
      const n = await ask("Copy chart layout", cur.name + " copy");
      if (n) { cur = { ...cur, id: newLid(), name: n }; await saveLayout(true); toast(`Copied to "${n}"`); }
    }
    if (a === "new") {
      const n = await ask("Create new chart layout", "", "Create");
      if (!n) return;
      await confirmLeave();
      const data = { layout: { id: "1", active: 0, sync: st.sync }, charts: [{ ...snapshot().charts[st.active] }] };
      const id = newLid();
      try { await put(id, n, data); } catch (err) { toast("Create failed: " + (err.message || err)); return; }
      cur = { ...cur, id, name: n }; touchRecent(id); saveCur();
      restore(data);
    }
  };
}
async function openLayoutDialog() {
  const d = document.createElement("dialog");
  d.innerHTML = `<form method="dialog" class="dlg sp-open"><div class="dlg-head"><b>Open layout</b><button value="cancel">✕</button></div>
    <input class="sp-q" placeholder="Search" autocomplete="off"><div class="list sp-list"></div></form>`;
  document.body.appendChild(d);
  let all = await listSaved();
  const box = d.querySelector(".sp-list"), q = d.querySelector(".sp-q");
  const render = () => {
    const f = q.value.toLowerCase();
    const items = all.filter((x) => (x.name + " " + x.summary).toLowerCase().includes(f));
    box.innerHTML = items.length ? "" : `<div class="grp">${all.length ? "No matches" : "No saved layouts yet"}</div>`;
    for (const x of items) {
      const row = document.createElement("div");
      row.className = "it" + (x.id === cur.id ? " cur" : "");
      row.innerHTML = `<span><b></b> <small></small></span><span class="sp-meta"><small></small><button type="button" title="Delete layout">✕</button></span>`;
      row.querySelector("b").textContent = x.name;
      row.querySelector("span small").textContent = x.summary;
      row.querySelector(".sp-meta small").textContent = new Date(x.updated).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
      const del = row.querySelector("button");
      del.disabled = x.id === cur.id; if (del.disabled) del.title = "This layout is open";
      del.onclick = async (e) => {
        e.stopPropagation();
        if (!(await LTVSettings.confirm(`Delete layout "${x.name}"?`, { title: "Delete layout", ok: "Delete", danger: true }))) return;
        await fetch(`/api/layouts/${x.id}`, { method: "DELETE" });
        recent = recent.filter((r) => r !== x.id); saveCur();
        all = all.filter((r) => r.id !== x.id); render();
      };
      row.onclick = () => { d.close(); if (x.id !== cur.id) openSaved(x.id); };
      box.appendChild(row);
    }
  };
  q.oninput = render; render();
  d.onclose = () => d.remove();
  d.showModal(); q.focus();
}
function beforeUnload() {
  if (cur.id && cur.autosave && dirty()) {
    const data = snapshot();
    fetch(`/api/layouts/${cur.id}`, { method: "PUT", keepalive: true, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: cur.name, summary: summaryOf(data), data }) });
  }
}
window.addEventListener("beforeunload", beforeUnload);
$("#saveBtn").onclick = () => saveLayout();
$("#saveMenuBtn").onclick = openSaveMenu;
document.addEventListener("pointerdown", (e) => { if (!e.target.closest("#savePop, #saveMenuBtn")) $("#savePop")?.remove(); }, true);
document.addEventListener("keydown", (e) => {
  if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.querySelector("dialog[open]")) return;
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.code === "KeyS") { e.preventDefault(); saveLayout(); }
  else if (e.key === "." && !e.ctrlKey && !e.altKey && !e.metaKey) { e.preventDefault(); openLayoutDialog(); }
});
// baseline for "unsaved changes" once the saved layout's charts have loaded; autosave every few seconds
(async () => {
  if (cur.id) {
    const ok = (await fetch(`/api/layouts/${cur.id}`)).ok;
    if (!ok) { cur.id = null; saveCur(); }
  }
  setTimeout(() => { if (cur.id) savedJson = JSON.stringify(snapshot()); paintSave(); }, 2500);
  setInterval(() => {
    if (savedJson == null && cur.id) return;
    if (cur.id && cur.autosave && dirty()) saveLayout(true); else paintSave();
  }, 4000);
})();
paintSave();
window.LTVLayout.saveLayout = () => saveLayout();

apply();
})();
