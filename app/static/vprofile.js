/* TickLens volume profile renderer, shared by the volume profile indicators (zones.js: Session, Session HD,
   Session chart, Periodic, Auto Anchored, Visible Range) and the Fixed Range / Anchored drawing tools (drawings.js).
   A profile p comes from core/volume_profile.py: {base, step, n, up[], dn[], poc, vaLo, vaHi, pocPrice, vah, val,
   total, status, res, volumeMode, ends{}, evidence[], limitations[], style{...}}. */
(function () {
"use strict";

const DEF = { width: 40, placement: "Left", volume: "Up/Down", up: "rgba(38,166,154,0.30)", down: "rgba(239,83,80,0.30)",
  va_up: "rgba(38,166,154,0.70)", va_down: "rgba(239,83,80,0.70)", poc: "#ff9800", vah: "#2962ff", val: "#2962ff",
  show_poc: true, show_va: true, show_vahval: true, show_values: false, extend_poc: false, extend_vah: false, extend_val: false,
  show_box: false, box: "rgba(41,98,255,0.06)", hd_px: 4 };

const fmtV = (v) => { const a = Math.abs(v); return a >= 1e7 ? (v / 1e7).toFixed(2) + "Cr" : a >= 1e5 ? (v / 1e5).toFixed(2) + "L" : a >= 1e3 ? (v / 1e3).toFixed(1) + "K" : String(Math.round(v)); };

/* Value area, same rule as the server: single-row expansion from the POC, larger row first (equal volume ->
   closer to POC, equal distance -> above), stop when the next row would exceed the target. */
function valueArea(tot, pct) {
  const n = tot.length, sum = tot.reduce((a, b) => a + b, 0);
  if (!n || sum <= 0) return { poc: null, lo: null, hi: null };
  const mx = Math.max(...tot), mid = (n - 1) / 2;
  let poc = -1;
  for (let k = 0; k < n; k++) if (tot[k] >= mx - 1e-12 * Math.max(mx, 1) && (poc < 0 || Math.abs(k - mid) < Math.abs(poc - mid))) poc = k;
  let left = sum * Math.min(Math.max(pct, 0), 100) / 100 - tot[poc], lo = poc, hi = poc;
  const eps = 1e-9 * Math.max(1, sum);
  while (left > eps && (lo > 0 || hi < n - 1)) {
    const up = hi < n - 1 ? tot[hi + 1] : null, dn = lo > 0 ? tot[lo - 1] : null;
    const takeUp = dn == null || (up != null && (up > dn || (up === dn && hi + 1 - poc <= poc - lo + 1)));
    const v = takeUp ? up : dn;
    if (v > left + eps) break;
    left -= v; if (takeUp) hi++; else lo--;
  }
  return { poc, lo, hi };
}

/* Session Volume Profile HD: merge the server's fine rows (1 tick, capped) so each row is about hd_px pixels tall
   at the current zoom, then recompute POC / VA on the merged rows - what is drawn is what is measured. */
function hdView(p, yOfP, px) {
  const y0 = yOfP(p.base), y1 = yOfP(p.base + p.step * p.n);
  if (y0 == null || y1 == null) return p;
  const rowPx = Math.abs(y0 - y1) / p.n, f = Math.max(1, Math.ceil(px / Math.max(rowPx, 1e-6)));
  if (f === 1) return p;
  const key = p.id + "|" + f;
  if (p._hdKey === key) return p._hd;
  const n = Math.ceil(p.n / f), up = new Array(n).fill(0), dn = new Array(n).fill(0);
  for (let k = 0; k < p.n; k++) { up[(k / f) | 0] += p.up[k]; dn[(k / f) | 0] += p.dn[k]; }
  const step = p.step * f, va = valueArea(up.map((u, k) => u + dn[k]), p.vaPct ?? 70);
  const q = { ...p, n, step, up, dn, poc: va.poc, vaLo: va.lo, vaHi: va.hi,
    pocPrice: va.poc == null ? null : p.base + step * (va.poc + 0.5),
    vah: va.hi == null ? null : Math.min(p.base + step * (va.hi + 1), p.high),
    val: va.lo == null ? null : p.base + step * va.lo, hdRows: n };
  p._hdKey = key; p._hd = q;
  return q;
}

/* g = {x1, x2, W, yOfP, xOfT}; x1..x2 = pixel span of the profile's bars. Returns the hit box {x1,x2,y1,y2,p}. */
function draw(ctx, p0, g) {
  const s = { ...DEF, ...(p0.style || {}) };
  const { yOfP, W } = g;
  const p = p0.hd ? hdView(p0, yOfP, +s.hd_px || 4) : p0;
  let { x1, x2 } = g;
  if (x1 == null || x2 == null || !p.n) return null;
  if (x2 < x1) [x1, x2] = [x2, x1];
  const span = Math.max(4, x2 - x1), wmax = span * (+s.width || 40) / 100;
  const tot = p.up.map((u, k) => u + p.dn[k]);
  const delta = s.volume === "Delta";
  const mx = Math.max(1e-12, ...(delta ? p.up.map((u, k) => Math.abs(u - p.dn[k])) : tot));
  const right = s.placement === "Right";
  const yTop = yOfP(p.base + p.step * p.n), yBot = yOfP(p.base);
  if (yTop == null || yBot == null) return null;
  const anyExt = s.extend_poc || s.extend_vah || s.extend_val;
  if (x1 > W || (x2 < 0 && !anyExt)) return null;
  ctx.save();
  if (s.show_box) { ctx.fillStyle = s.box; ctx.fillRect(x1, Math.min(yTop, yBot), x2 - x1, Math.abs(yBot - yTop)); }
  if (x2 >= 0) for (let k = 0; k < p.n; k++) {
    const ya = yOfP(p.base + p.step * (k + 1)), yb = yOfP(p.base + p.step * k);
    if (ya == null || yb == null) continue;
    let y0 = Math.min(ya, yb), h = Math.abs(yb - ya);
    if (h > 3) { y0 += 0.5; h -= 1; }
    h = Math.max(1, h);
    const inVA = s.show_va && p.vaLo != null && k >= p.vaLo && k <= p.vaHi;
    const cu = inVA ? s.va_up : s.up, cd = inVA ? s.va_down : s.down;
    const segs = [];
    if (delta) { const d = p.up[k] - p.dn[k]; segs.push([Math.abs(d) / mx * wmax, d >= 0 ? cu : cd]); }
    else if (s.volume === "Total") segs.push([tot[k] / mx * wmax, cu]);
    else segs.push([p.up[k] / mx * wmax, cu], [p.dn[k] / mx * wmax, cd]);
    let x = right ? x2 : x1;
    for (const [w, c] of segs) {
      if (w <= 0) continue;
      ctx.fillStyle = c;
      if (right) { ctx.fillRect(x - w, y0, w, h); x -= w; } else { ctx.fillRect(x, y0, w, h); x += w; }
    }
    if (s.show_values && h >= 9) {
      const v = delta ? p.up[k] - p.dn[k] : tot[k];
      if (v) {
        ctx.font = "10px -apple-system, Segoe UI, Roboto, sans-serif"; ctx.fillStyle = "#9598a1"; ctx.textBaseline = "middle";
        ctx.textAlign = right ? "right" : "left";
        ctx.fillText(fmtV(v), right ? x - 3 : x + 3, y0 + h / 2);
      }
    }
  }
  // "extend right until it crosses any bar": p.ends[level] = time of the first later bar touching it (null = none yet)
  const endX = (key, on) => {
    if (!on) return x2;
    const t = p0.ends?.[key];
    if (t == null || !g.xOfT) return W;
    const x = g.xOfT(t);
    return x == null ? W : Math.max(x2, x);
  };
  const hline = (price, color, w, dash, xe) => {
    const y = yOfP(price);
    if (y == null) return;
    ctx.strokeStyle = color; ctx.lineWidth = w; ctx.setLineDash(dash);
    ctx.beginPath(); ctx.moveTo(Math.max(x1, -2), Math.round(y) + 0.5); ctx.lineTo(xe, Math.round(y) + 0.5); ctx.stroke();
  };
  const prov = p.status === "PROVISIONAL";
  // (HD: the server's crossing bars are for its fine-row levels - close enough to the merged ones)
  if (s.show_vahval && p.vah != null) {
    hline(p.vah, s.vah, 1, [4, 3], endX("vah", s.extend_vah));
    hline(p.val, s.val, 1, [4, 3], endX("val", s.extend_val));
  }
  if (s.show_poc && p.pocPrice != null) hline(p.pocPrice, s.poc, 2, prov ? [6, 3] : [], endX("pocPrice", s.extend_poc));
  ctx.setLineDash([]);
  if (g.note !== false && (prov || p.kind === "frvp" || p.kind === "vrvp") && (p.volumeMode === "bar-count" || p.dataQuality === "proxy" || p.res === "chart")) {
    const t = p.volumeMode === "bar-count" ? "No volume · time at price" : p.dataQuality === "proxy" ? `Proxy volume${(p.volNote || "").match(/ETF (\S+)/) ? " (" + p.volNote.match(/ETF (\S+)/)[1] + ")" : ""}` : "Chart-bar resolution";
    ctx.font = "10px -apple-system, Segoe UI, Roboto, sans-serif"; ctx.fillStyle = "#f5a623";
    ctx.textAlign = right ? "right" : "left"; ctx.textBaseline = "bottom";
    ctx.fillText("⚠ " + t, right ? x2 - 2 : x1 + 2, Math.min(yTop, yBot) - 2);
  }
  ctx.restore();
  return { x1: right ? x2 - wmax : x1, x2: right ? x2 : x1 + wmax, y1: Math.min(yTop, yBot), y2: Math.max(yTop, yBot), p };
}

const NAMES = { frvp: "Fixed Range Volume Profile", vrvp: "Visible Range Volume Profile", aavp: "Auto Anchored Volume Profile",
  pvp: "Periodic Volume Profile", svphd: "Session Volume Profile HD", svpc: "Session Volume Profile (chart)" };
const esc = (x) => String(x ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function tooltip(p, fmtTime = (t) => new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC", fmtP = (x) => (+x).toFixed(2)) {
  const name = NAMES[p.kind] || `${p.period === "Week" ? "Weekly" : p.period === "Month" ? "Monthly" : "Session"} Volume Profile`;
  const st = p.status === "PROVISIONAL" ? '<b class="vp-prov">PROVISIONAL · developing</b>' : '<b class="vp-conf">CONFIRMED</b>';
  const vol = p.volumeMode === "bar-count" ? "n/a (no volume)" : fmtV(p.total);
  const rows = [
    ...(p.periodLabel && p.kind !== "svp" ? [["Period", p.periodLabel]] : []),
    ["Range", `${fmtTime(p.l)} → ${fmtTime(p.r)}`],
    ["POC <i>Derived</i>", fmtP(p.pocPrice)],
    ["VAH / VAL <i>Derived</i>", `${fmtP(p.vah)} / ${fmtP(p.val)}`],
    ["High / Low <i>Observed</i>", `${fmtP(p.high)} / ${fmtP(p.low)}`],
    [`Volume <i>${p.dataQuality === "proxy" ? "Estimated" : "Observed"}</i>`, vol],
    ...(p.volumeMode === "bar-count" ? [] : [["Up / Down <i>Estimated</i>", `${fmtV(p.upTotal)} / ${fmtV(p.dnTotal)}`]]),
    ["Rows", `${p.n} × ${fmtP(p.step)}${p.hdRows ? " (HD, zoom-adjusted)" : ""}`],
    ["Data", `${p.res === "chart" ? "chart bars" : p.res}, ${p.bars} bars`],
    ["Known at", fmtTime(p.knownAt)],
  ];
  const rule = (p.evidence || []).find((e) => e.metric === "VAH")?.rule || "";
  return `<div class="vp-tt-h">${name} ${st}</div>
    <table>${rows.map(([a, b]) => `<tr><td>${a}</td><td>${esc(b)}</td></tr>`).join("")}</table>
    <div class="vp-tt-r">Rule: volume spread over each bar's high–low; close ≥ open = up; POC = max-volume row; VA = ${esc(rule)}.</div>
    <div class="vp-tt-r">${esc(p.invalidationRule || "")}</div>
    ${(p.limitations || []).map((l) => `<div class="vp-tt-l">• ${esc(l)}</div>`).join("")}
    <div class="vp-tt-v">${esc(p.algorithmVersion || "")}</div>`;
}

window.LTVVP = { draw, tooltip, valueArea, DEF };
})();
