/* TickLens cross-device sync: chart state (indicators, symbol, TF, styles), drawings, watchlists, alerts and the
   other "ltv.*" settings live on the server too, so the PC and the phone open the same charts.
   Runs before every other script: pulls the server copy into localStorage (synchronous, so the app reads the
   synced values on boot), then mirrors every later localStorage write of a synced key back to the server.
   Per-key last write wins. Device-only keys (multi-chart grid, open side panel, sync bookkeeping) stay local. */
(() => {
"use strict";
const LS = window.localStorage;
if (!LS) return;
const EMBED = +new URLSearchParams(location.search).get("slot") > 0;    // multi-chart frames: the host page pulled already
const LOCAL_ONLY = /^ltv\.(sync\.|layout$|side$|paper\.seq$)/;
const synced = (k) => typeof k === "string" && k.startsWith("ltv.") && !LOCAL_ONLY.test(k);
const DEVICE_FIELDS = { "ltv.state": ["wlWidth"] };                     // per-device fields inside a synced value
const P = Storage.prototype, rawSet = P.setItem, rawDel = P.removeItem;
const get = (k) => P.getItem.call(LS, k);
const meta = (k, d) => { try { return JSON.parse(get(k)) ?? d; } catch { return d; } };
const setMeta = (k, v) => { try { rawSet.call(LS, k, JSON.stringify(v)); } catch { /* full */ } };
let rev = meta("ltv.sync.rev", 0);
const pending = new Set(meta("ltv.sync.pending", []));                  // written here, not yet on the server
const savePending = () => setMeta("ltv.sync.pending", [...pending]);

function keepDeviceFields(k, incoming) {
  const f = DEVICE_FIELDS[k];
  if (!f || incoming == null) return incoming;
  try {
    const mine = JSON.parse(get(k) || "{}"), v = JSON.parse(incoming);
    for (const x of f) if (x in mine) v[x] = mine[x]; else delete v[x];
    return JSON.stringify(v);
  } catch { return incoming; }
}
// apply server values that differ from this device; returns how many changed
function apply(keys) {
  let n = 0;
  for (const [k, v] of Object.entries(keys || {})) {
    if (!synced(k) || pending.has(k)) continue;
    const val = v == null ? null : keepDeviceFields(k, v);
    if (val === get(k)) continue;
    try { if (val == null) rawDel.call(LS, k); else rawSet.call(LS, k, val); n++; } catch { /* full */ }
  }
  return n;
}
function pull(since) {
  try {
    const x = new XMLHttpRequest();
    x.open("GET", `/api/state?since=${since}`, false);                 // sync on purpose: must land before the app boots
    x.send();
    return x.status === 200 ? JSON.parse(x.responseText) : null;
  } catch { return null; }
}

// ---- push
let timer = null;
function body() {
  const keys = {};
  for (const k of pending) keys[k] = get(k);
  return JSON.stringify({ keys });
}
async function push(beacon) {
  clearTimeout(timer); timer = null;
  if (!pending.size) return;
  const sent = [...pending], payload = body();
  try {
    const r = await fetch("/api/state", { method: "PUT", headers: { "Content-Type": "application/json" }, body: payload, keepalive: beacon && payload.length < 60000 });
    if (!r.ok) return;
    const j = await r.json();
    rev = Math.max(rev, j.rev || 0); setMeta("ltv.sync.rev", rev);
    for (const k of sent) pending.delete(k);
    savePending();
  } catch { /* offline: pending stays and goes up on the next load */ }
}
const schedule = () => { if (!timer) timer = setTimeout(push, 1500); };
function mark(k) { pending.add(k); savePending(); schedule(); }
P.setItem = function (k, v) { rawSet.call(this, k, v); if (this === LS && synced(k)) mark(k); };
P.removeItem = function (k) { rawDel.call(this, k); if (this === LS && synced(k)) mark(k); };

// ---- boot: server copy first (host page only)
if (!EMBED) {
  const s = pull(0);
  if (s) {
    apply(s.keys);
    rev = s.rev || 0; setMeta("ltv.sync.rev", rev);
    // first sync from this device: put up what it has that the server lacks
    for (let i = 0; i < LS.length; i++) { const k = LS.key(i); if (synced(k) && !(k in (s.keys || {}))) pending.add(k); }
    savePending();
  }
  if (pending.size) schedule();
  // coming back to the app (phone PWA resumed, PC tab refocused): reload if another device changed something
  let checking = false;
  const check = async () => {
    if (document.visibilityState !== "visible" || checking) return;
    checking = true;
    try {
      await push();
      const r = await fetch(`/api/state?since=${rev}`);
      if (r.ok) {
        const j = await r.json();
        const n = apply(j.keys);
        rev = Math.max(rev, j.rev || 0); setMeta("ltv.sync.rev", rev);
        if (n) location.reload();
      }
    } catch { /* offline */ }
    checking = false;
  };
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") push(true); else check(); });
  window.addEventListener("focus", check);
  window.addEventListener("pagehide", () => push(true));
} else {
  window.addEventListener("pagehide", () => push(true));
}
window.LTVSync = { push, pending: () => [...pending] };
})();
