/* TickLens indicator objects: boxes, labels and lines (Pine's box.new / label.new / line.new)
   drawn on a canvas under the drawing tools, and tables as HTML panels over the chart.
   Objects come from indicator scripts as {boxes, labels, lines, tables} with UTC-second times. */
(function () {
"use strict";

function init({ chart, el, series, bars, tf, leftOffset = () => 0, objects = () => [], fmtTime, fmtPrice, vpRange = () => null }) {
  const wrap = el.parentElement;
  const cv = document.createElement("canvas");
  cv.className = "zones-canvas";
  wrap.appendChild(cv);
  const ctx = cv.getContext("2d");
  const tblHost = document.createElement("div");
  tblHost.className = "ind-tables";
  wrap.appendChild(tblHost);
  const dpr = () => window.devicePixelRatio || 1;
  const tip = document.createElement("div");
  tip.className = "vp-tooltip hidden";
  wrap.appendChild(tip);
  let vpHits = [], tipHits = [];

  const B = () => bars() || [];
  function logicalOfT(t) {
    const b = B(), n = b.length, step = tf();
    if (!n) return null;
    if (t <= b[0][0]) return (t - b[0][0]) / step;
    if (t >= b[n - 1][0]) return n - 1 + (t - b[n - 1][0]) / step;
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (b[m][0] <= t) lo = m; else hi = m; }
    return lo + (t - b[lo][0]) / (b[hi][0] - b[lo][0]);
  }
  const xOfT = (t) => { const L = logicalOfT(t); return L == null ? null : chart.timeScale().logicalToCoordinate(L); };
  const yOfP = (p) => { const s = series(); return s && p != null ? s.priceToCoordinate(p) : null; };
  const paneW = () => chart.timeScale().width();
  const paneH = () => { try { return chart.panes()[0].getHeight(); } catch { return el.clientHeight; } };

  let dirty = true, lastSig = "", tblSig = "";
  function viewSig() {
    const ts = chart.timeScale(), s = series(), r = ts.getVisibleLogicalRange();
    return [cv.width, cv.height, r && r.from, r && r.to, s && s.priceToCoordinate(1000), s && s.priceToCoordinate(2000), B().length].join("|");
  }
  function resize() {
    const w = paneW(), h = paneH(), r = dpr(), off = leftOffset() + "px";
    if (cv.style.left !== off) { cv.style.left = off; dirty = true; }
    if (cv.width !== Math.round(w * r) || cv.height !== Math.round(h * r)) {
      cv.width = Math.round(w * r); cv.height = Math.round(h * r); cv.style.width = w + "px"; cv.style.height = h + "px";
      dirty = true;
    }
  }
  const DASH = { solid: [], dashed: [6, 4], dotted: [2, 3] };

  function drawBox(b, W) {
    const x1 = xOfT(b.l), y1 = yOfP(b.top), y2 = yOfP(b.bottom);
    if (x1 == null || y1 == null || y2 == null) return;
    const x2 = b.extend || b.r == null ? W : xOfT(b.r);
    if (x2 == null || x2 < 0 || x1 > W) return;
    const top = Math.min(y1, y2), h = Math.max(1, Math.abs(y2 - y1));
    ctx.fillStyle = b.bg;
    ctx.fillRect(x1, top, x2 - x1, h);
    if (b.tip) tipHits.push([{ x1, x2, y1: top, y2: top + h, box: 1 }, b.tip]);
    if (b.border) {
      ctx.strokeStyle = b.border; ctx.lineWidth = 1; ctx.setLineDash(DASH[b.bstyle] || []);
      ctx.strokeRect(Math.round(x1) + 0.5, Math.round(top) + 0.5, x2 - x1, h);
      ctx.setLineDash([]);
    }
    if (b.text && h >= 9) {
      ctx.font = "11px -apple-system, Segoe UI, Roboto, sans-serif";
      ctx.fillStyle = b.tc || b.border || "#d1d4dc";
      ctx.textAlign = "right"; ctx.textBaseline = "middle";
      ctx.fillText(b.text, Math.min(x2, W) - 6, top + h / 2);
    }
  }
  function drawLine(l, W) {
    const x1 = xOfT(l.t1), y1 = yOfP(l.p1), y2 = yOfP(l.p2);
    const x2 = l.extend || l.t2 == null ? W : xOfT(l.t2);
    if (x1 == null || x2 == null || y1 == null || y2 == null) return;
    ctx.strokeStyle = l.color; ctx.lineWidth = l.width || 1; ctx.setLineDash(DASH[l.style] || []);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    ctx.setLineDash([]);
  }
  function drawBubble(bb, W) {
    const x = xOfT(bb.t), y = yOfP(bb.p);
    if (x == null || y == null || x < -bb.r || x > W + bb.r) return;
    ctx.beginPath(); ctx.arc(x, y, bb.r, 0, Math.PI * 2);
    ctx.fillStyle = bb.bg; ctx.fill();
    if (bb.border) { ctx.strokeStyle = bb.border; ctx.lineWidth = 1; ctx.stroke(); }
    if (bb.text && bb.r >= 9) {
      ctx.font = "600 10px -apple-system, Segoe UI, Roboto, sans-serif";
      ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(bb.text, x, y + 0.5);
    }
    if (bb.tip) tipHits.push([{ x1: x - bb.r, x2: x + bb.r, y1: y - bb.r, y2: y + bb.r }, bb.tip]);
  }
  function tipHtml(t) {
    const rows = (t.rows || []).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
    const st = t.status ? `<div class="${t.status === "PROVISIONAL" ? "vp-prov" : "vp-conf"}">${esc(t.status)}</div>` : "";
    const notes = (t.notes || []).map((n) => `<div class="vp-tt-l">${esc(n)}</div>`).join("");
    const simple = (t.simple || []).length
      ? `<div style="margin:4px 0 6px;padding:6px 8px;border-radius:4px;background:rgba(41,98,255,.12);font-size:12px;line-height:1.45">${t.simple.map(esc).join("<br>")}</div>` : "";
    return `<div class="vp-tt-h">${esc(t.title || "")}</div>${st}${simple}<table>${rows}</table>${notes}${t.version ? `<div class="vp-tt-v">${esc(t.version)}</div>` : ""}`;
  }
  function drawLabel(lb) {
    const x = xOfT(lb.t), y = yOfP(lb.p);
    if (x == null || y == null || !lb.text) return;
    const fs = lb.size === "small" ? 10 : lb.size === "large" ? 13 : 11;
    ctx.font = `600 ${fs}px -apple-system, Segoe UI, Roboto, sans-serif`;
    const tw = ctx.measureText(lb.text).width, w = tw + 10, h = fs + 8, tip = lb.style === "none" ? 0 : 5;
    let bx = x - w / 2, by;
    if (lb.style === "up") by = y + tip;
    else if (lb.style === "left") { bx = x + tip; by = y - h / 2; }
    else if (lb.style === "right") { bx = x - w - tip; by = y - h / 2; }
    else if (lb.style === "none") { by = y - h / 2; if (lb.align === "left") bx = x; }
    else by = y - h - tip;
    ctx.fillStyle = lb.bg;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(bx, by, w, h, 3); else ctx.rect(bx, by, w, h);
    if (tip) {
      if (lb.style === "up") { ctx.moveTo(x - 4, by); ctx.lineTo(x, y); ctx.lineTo(x + 4, by); }
      else if (lb.style === "left") { ctx.moveTo(bx, y - 4); ctx.lineTo(x, y); ctx.lineTo(bx, y + 4); }
      else if (lb.style === "right") { ctx.moveTo(bx + w, y - 4); ctx.lineTo(x, y); ctx.lineTo(bx + w, y + 4); }
      else { ctx.moveTo(x - 4, by + h); ctx.lineTo(x, y); ctx.lineTo(x + 4, by + h); }
    }
    ctx.fill();
    ctx.fillStyle = lb.tc || "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(lb.text, bx + w / 2, by + h / 2 + 0.5);
  }

  function render() {
    const r = dpr(), W = paneW();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.setTransform(r, 0, 0, r, 0, 0);
    if (!series()) return;
    const all = objects();
    vpHits = []; tipHits = [];
    if (window.LTVVP) {
      const half = (chart.timeScale().options().barSpacing || 6) / 2;
      for (const o of all) for (const p of o.profiles || []) {
        const xa = xOfT(p.l), xb = xOfT(p.r);
        if (xa == null || xb == null) continue;
        const hit = LTVVP.draw(ctx, p, { x1: xa - half, x2: xb + half, W, yOfP, xOfT });
        if (hit) vpHits.push([hit, hit.p || p]);
      }
      // Visible Range VP: bars on screen, histogram on the right edge of the pane
      const vr = chart.timeScale().getVisibleLogicalRange(), b = B();
      if (vr && b.length) for (const o of all) for (const sp of o.vpspecs || []) {
        const i1 = Math.max(0, Math.ceil(vr.from)), i2 = Math.min(b.length - 1, Math.floor(vr.to));
        if (i2 < i1) continue;
        const p = vpRange(sp, b[i1][0], b[i2][0]);
        if (!p) continue;
        const xa = Math.max(0, chart.timeScale().logicalToCoordinate(i1) - half);
        const hit = LTVVP.draw(ctx, { ...p, style: sp.style || {} }, { x1: xa, x2: W, W, yOfP, xOfT, note: true });
        if (hit) vpHits.push([hit, hit.p]);
      }
    }
    for (const o of all) for (const b of o.boxes || []) drawBox(b, W);
    for (const o of all) for (const l of o.lines || []) drawLine(l, W);
    for (const o of all) for (const bb of o.bubbles || []) drawBubble(bb, W);
    for (const o of all) for (const lb of o.labels || []) drawLabel(lb);
    renderTables(all);
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function renderTables(all) {
    const tbls = all.flatMap((o) => o.tables || []);
    const sig = JSON.stringify(tbls);
    if (sig === tblSig) return;
    tblSig = sig;
    tblHost.innerHTML = tbls.map((t) => {
      const rows = t.rows.map((row) => `<tr>${row.map((c) =>
        `<td style="${c.bg ? `background:${esc(c.bg)};` : ""}${c.color ? `color:${esc(c.color)};` : ""}${c.bold ? "font-weight:600;" : ""}">${esc(c.text)}</td>`).join("")}</tr>`).join("");
      return `<div class="ind-table pos-${esc(t.position || "top_right")}">${t.title ? `<div class="it-title">${esc(t.title)}</div>` : ""}<table>${rows}</table></div>`;
    }).join("");
  }
  function placeTables() {
    const off = leftOffset();
    tblHost.style.left = off + "px";
    tblHost.style.width = paneW() + "px";
    tblHost.style.height = paneH() + "px";
  }

  // profile tooltip (evidence trail): hover the histogram of a session / range profile
  wrap.addEventListener("mousemove", (e) => {
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const inside = ([b]) => x >= b.x1 && x <= b.x2 && y >= b.y1 && y <= b.y2;
    let h = null, gen = false;
    for (let k = tipHits.length - 1; k >= 0; k--) if (!tipHits[k][0].box && inside(tipHits[k])) { h = tipHits[k]; gen = true; break; }
    if (!h) h = vpHits.find(inside);
    if (!h) { for (let k = tipHits.length - 1; k >= 0; k--) if (inside(tipHits[k])) { h = tipHits[k]; gen = true; break; } }
    if (!h || e.buttons) { tip.classList.add("hidden"); tip._p = null; return; }
    if (tip._p !== h[1]) { tip._p = h[1]; tip.innerHTML = gen ? tipHtml(h[1]) : LTVVP.tooltip(h[1], fmtTime, fmtPrice); }
    tip.classList.remove("hidden");
    const wr = wrap.getBoundingClientRect();
    let lx = e.clientX - wr.left + 14, ly = e.clientY - wr.top + 14;
    if (lx + tip.offsetWidth > wr.width) lx = e.clientX - wr.left - tip.offsetWidth - 14;
    if (ly + tip.offsetHeight > wr.height) ly = Math.max(0, wr.height - tip.offsetHeight - 4);
    tip.style.left = lx + "px"; tip.style.top = ly + "px";
  }, true);
  wrap.addEventListener("mouseleave", () => tip.classList.add("hidden"));

  function frame() {
    try {
      resize();
      placeTables();
      const sig = viewSig();
      if (dirty || sig !== lastSig) { lastSig = sig; dirty = false; render(); }
    } catch (e) { if (!frame.err) console.error("zones:", e); frame.err = 1; }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  return { dirty() { dirty = true; } };
}

window.LTVZones = { init };
})();
