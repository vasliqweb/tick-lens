/* TickLens chart settings: TradingView-style settings dialog + price-scale menu (UI only).
   app.js owns the settings object and applies it to the chart via onChange(cs). */
(() => {
"use strict";

const DEFAULTS = {
  // Symbol
  colorPrev: false, body: true, upColor: "#26a69a", downColor: "#ef5350", borders: true, borderUp: "#26a69a", borderDown: "#ef5350",
  wick: true, wickUp: "#26a69a", wickDown: "#ef5350", session: "regular", precision: "default", timezone: "exchange",
  // Status line
  logo: true, title: true, titleMode: "ticker_tf", marketStatus: true, chartValues: true, barChange: true, volume: false,
  lastDayChange: false, indTitles: true, indInputs: true, indValues: true, legendBg: false, legendBgA: 0.5,
  // Scales and lines
  currency: "always", scaleModes: "hover", placement: "right", noOverlap: true, plusButton: true, countdown: true,
  symName: false, symLabel: true, symLine: true, priceLineColor: "",
  prevLabel: false, prevLine: false, prevColor: "#ff9800", hlLabel: false, hlLine: false, hlColor: "#787b86",
  indName: false, indValue: true,
  // price-scale menu
  autoScale: true, scaleMainOnly: false, invert: false, mode: "regular",
  // Canvas
  bgType: "solid", bg: "", bg2: "", vGrid: true, vGridColor: "", hGrid: true, hGridColor: "", crossColor: "", crossStyle: "dashed",
  watermark: "hidden", watermarkColor: "#787b86", textColor: "", fontSize: 12, lineColor: "",
  navButtons: "hover", paneButtons: "hover", marginTop: 10, marginBottom: 8, rightBars: 10,
};
const TIMEZONES = [
  ["exchange", "Exchange (UTC+5:30 Kolkata)"], ["local", "Local (browser)"], ["UTC", "UTC"], ["Asia/Kolkata", "(UTC+5:30) Kolkata"],
  ["Asia/Dubai", "(UTC+4) Dubai"], ["Asia/Singapore", "(UTC+8) Singapore"], ["Asia/Hong_Kong", "(UTC+8) Hong Kong"], ["Asia/Tokyo", "(UTC+9) Tokyo"],
  ["Australia/Sydney", "(UTC+10/11) Sydney"], ["Europe/London", "(UTC+0/1) London"], ["Europe/Berlin", "(UTC+1/2) Berlin"],
  ["America/New_York", "(UTC-5/4) New York"], ["America/Chicago", "(UTC-6/5) Chicago"], ["America/Los_Angeles", "(UTC-8/7) Los Angeles"],
];
const VIS = [["always", "Always visible"], ["hover", "Visible on mouse over"], ["hidden", "Hidden"]];
const LV = [["value_line", "Value, line"], ["value", "Value"], ["line", "Line"], ["hidden", "Hidden"]];
const PRECISION = [["default", "Default"], ["0", "1"], ["1", "1/10"], ["2", "1/100"], ["3", "1/1000"], ["4", "1/10000"], ["5", "1/100000"]];

// label/line pairs edited as one "Value, line" select in the dialog
const PAIRS = { symLV: ["symLabel", "symLine"], prevLV: ["prevLabel", "prevLine"], hlLV: ["hlLabel", "hlLine"], indLV: ["indValue", "indName"] };

const ICON = {
  symbol: '<path d="M7 3v18M5 7h4v9H5zM16 4v16M14 8h4v7h-4z"/>',
  status: '<path d="M4 6h16M4 10h12M4 14h16M4 18h10"/>',
  scales: '<path d="M6 3v15h15M6 3L4 5M6 3l2 2M21 18l-2-2M21 18l-2 2"/><circle cx="6" cy="20" r="1.5"/>',
  canvas: '<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M14 6l3 3"/>',
};
const svg = (k) => `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">${ICON[k]}</svg>`;

const TABS = [
  { id: "symbol", name: "Symbol", rows: [
    ["#", "Candles"],
    ["check", "colorPrev", "Color bars based on previous close"],
    ["checkcolors", "body", "Body", ["upColor", "downColor"]],
    ["checkcolors", "borders", "Borders", ["borderUp", "borderDown"]],
    ["checkcolors", "wick", "Wick", ["wickUp", "wickDown"]],
    ["#", "Data modification"],
    ["select", "session", "Session", [["regular", "Regular trading hours"], ["extended", "Extended trading hours"]]],
    ["select", "precision", "Precision", PRECISION],
    ["select", "timezone", "Timezone", TIMEZONES]] },
  { id: "status", name: "Status line", rows: [
    ["#", "Instrument"],
    ["check", "logo", "Logo"],
    ["checkselect", "title", "Title", "titleMode", [["ticker", "Ticker"], ["ticker_tf", "Ticker and timeframe"], ["ticker_tf_src", "Ticker, timeframe and source"]]],
    ["check", "marketStatus", "Open market status"],
    ["check", "chartValues", "Chart values"],
    ["check", "barChange", "Bar change values"],
    ["check", "volume", "Volume"],
    ["check", "lastDayChange", "Last day change values"],
    ["#", "Indicators"],
    ["check", "indTitles", "Titles"],
    ["check", "indInputs", "Inputs", { indent: true, needs: "indTitles" }],
    ["check", "indValues", "Values"],
    ["checkrange", "legendBg", "Background", "legendBgA"]] },
  { id: "scales", name: "Scales and lines", rows: [
    ["#", "Price scale"],
    ["select", "currency", "Currency and Unit", VIS],
    ["select", "scaleModes", "Scale modes (A and L)", VIS],
    ["select", "placement", "Scales placement", [["auto", "Auto"], ["right", "Right"], ["left", "Left"]]],
    ["#", "Price labels & lines"],
    ["check", "noOverlap", "No overlapping labels"],
    ["check", "plusButton", "Plus button", { help: "Click + on the price scale to add a horizontal line at that price" }],
    ["check", "countdown", "Countdown to bar close"],
    ["check", "symName", "Symbol name label"],
    ["pair", "symLV", "Symbol", LV, "priceLineColor"],
    ["pair", "prevLV", "Previous day close", LV, "prevColor"],
    ["pair", "hlLV", "High and low", LV, "hlColor"],
    ["pair", "indLV", "Indicators and financials", [["value", "Value"], ["value_line", "Value, name"], ["line", "Name"], ["hidden", "Hidden"]]]] },
  { id: "canvas", name: "Canvas", rows: [
    ["#", "Chart basic styles"],
    ["bg", "bgType", "Background"],
    ["checkcolor", "vGrid", "Vertical grid lines", "vGridColor"],
    ["checkcolor", "hGrid", "Horizontal grid lines", "hGridColor"],
    ["crosshair", "crossColor", "Crosshair"],
    ["selectcolor", "watermark", "Watermark", [["hidden", "Hidden"], ["symbol", "Symbol"], ["symbol_tf", "Symbol and timeframe"]], "watermarkColor"],
    ["#", "Scales"],
    ["colorsize", "textColor", "Text", "fontSize"],
    ["color", "lineColor", "Lines"],
    ["#", "Buttons"],
    ["select", "navButtons", "Navigation", VIS],
    ["select", "paneButtons", "Pane", VIS],
    ["#", "Margins"],
    ["number", "marginTop", "Top", "%", 0, 45],
    ["number", "marginBottom", "Bottom", "%", 0, 45],
    ["number", "rightBars", "Right", "bars", 0, 200]] },
];

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const opts = (list, v) => list.map(([k, n]) => `<option value="${k}"${String(v) === String(k) ? " selected" : ""}>${esc(n)}</option>`).join("");
function pairValue(cs, key) {
  const [a, b] = PAIRS[key];
  return cs[a] && cs[b] ? "value_line" : cs[a] ? "value" : cs[b] ? "line" : "hidden";
}
function setPair(cs, key, v) { const [a, b] = PAIRS[key]; cs[a] = v === "value" || v === "value_line"; cs[b] = v === "line" || v === "value_line"; }

// ------------------------------------------------------------------ settings dialog
let dlg;
function openDialog({ cs, defaults = DEFAULTS, colorOf, onChange, tab = "symbol" }) {
  if (!dlg) { dlg = document.createElement("dialog"); dlg.id = "csDlg"; document.body.appendChild(dlg); }
  const orig = JSON.parse(JSON.stringify(cs));
  const draft = JSON.parse(JSON.stringify(cs));
  let cur = tab;
  const col = (k) => draft[k] || colorOf(k);
  dlg.innerHTML = `<form method="dialog" class="cs">
    <div class="cs-head"><b>Settings</b><button value="cancel" class="x">✕</button></div>
    <div class="cs-body"><nav class="cs-nav"></nav><div class="cs-pane"></div></div>
    <div class="cs-foot"><div class="cs-tmpl"><button type="button" class="cs-tbtn">Template ▾</button><div class="cs-tmenu hidden"></div></div>
      <span class="spacer"></span><button value="cancel">Cancel</button><button value="ok" class="primary">Ok</button></div></form>`;
  const nav = dlg.querySelector(".cs-nav"), pane = dlg.querySelector(".cs-pane");
  const changed = () => onChange(JSON.parse(JSON.stringify(draft)));
  function row(r) {
    const [type, key, label, a, b, c] = r;
    const o = typeof a === "object" && !Array.isArray(a) ? a : (typeof b === "object" && !Array.isArray(b) ? b : {});
    if (type === "#") return `<div class="cs-h">${esc(key)}</div>`;
    const chk = (k, l, extra = "") => `<label class="cs-chk${o.indent ? " ind" : ""}"><input type="checkbox" data-k="${k}" ${draft[k] ? "checked" : ""}${o.needs && !draft[o.needs] ? " disabled" : ""}>${esc(l)}${o.help ? ` <span class="cs-help" title="${esc(o.help)}">?</span>` : ""}</label>${extra}`;
    const color = (k) => `<input type="color" data-k="${k}" value="${col(k)}">`;
    const ctl = (lab, inner) => `<div class="cs-row"><span class="cs-l">${lab}</span><span class="cs-c">${inner}</span></div>`;
    switch (type) {
      case "check": return `<div class="cs-row">${chk(key, label)}</div>`;
      case "checkcolors": return `<div class="cs-row">${chk(key, label)}<span class="cs-c">${a.map(color).join("")}</span></div>`;
      case "checkcolor": return `<div class="cs-row">${chk(key, label)}<span class="cs-c">${color(a)}</span></div>`;
      case "checkselect": return `<div class="cs-row">${chk(key, label)}<span class="cs-c"><select data-k="${a}">${opts(b, draft[a])}</select></span></div>`;
      case "checkrange": return `<div class="cs-row">${chk(key, label)}<span class="cs-c"><input type="range" min="0" max="1" step="0.05" data-k="${a}" value="${draft[a]}"></span></div>`;
      case "select": return ctl(esc(label), `<select data-k="${key}">${opts(a, draft[key])}</select>`);
      case "selectcolor": return ctl(esc(label), `<select data-k="${key}">${opts(a, draft[key])}</select>${color(b)}`);
      case "pair": return ctl(esc(label), `<select data-pair="${key}">${opts(a, pairValue(draft, key))}</select>${b ? color(b) : ""}`);
      case "color": return ctl(esc(label), color(key));
      case "colorsize": return ctl(esc(label), `${color(key)}<select data-k="${a}" data-num="1">${opts([10, 11, 12, 13, 14, 16].map((x) => [x, x]), draft[a])}</select>`);
      case "number": return ctl(esc(label), `<input type="number" data-k="${key}" data-num="1" min="${b}" max="${c}" value="${draft[key]}"><span class="cs-u">${esc(a)}</span>`);
      case "bg": return ctl(esc(label), `<select data-k="bgType">${opts([["solid", "Solid"], ["gradient", "Gradient"]], draft.bgType)}</select>${color("bg")}${draft.bgType === "gradient" ? color("bg2") : ""}`);
      case "crosshair": return ctl(esc(label), `${color("crossColor")}<select data-k="crossStyle">${opts([["solid", "Solid"], ["dashed", "Dashed"], ["dotted", "Dotted"], ["large", "Large dashed"]], draft.crossStyle)}</select>`);
    }
    return "";
  }
  function render() {
    nav.innerHTML = TABS.map((t) => `<button type="button" data-tab="${t.id}" class="${t.id === cur ? "on" : ""}">${svg(t.id)}<span>${t.name}</span></button>`).join("");
    pane.innerHTML = TABS.find((t) => t.id === cur).rows.map(row).join("");
    nav.querySelectorAll("[data-tab]").forEach((b) => b.onclick = () => { cur = b.dataset.tab; render(); });
    pane.querySelectorAll("[data-k]").forEach((el) => {
      const ev = el.type === "color" || el.type === "range" || el.type === "number" ? "input" : "change";
      el.addEventListener(ev, () => {
        const k = el.dataset.k;
        draft[k] = el.type === "checkbox" ? el.checked : el.dataset.num || el.type === "range" ? +el.value : el.value;
        changed();
        if (el.type === "checkbox" || k === "bgType") render();
      });
    });
    pane.querySelectorAll("[data-pair]").forEach((el) => el.onchange = () => { setPair(draft, el.dataset.pair, el.value); changed(); });
  }
  // Template menu: defaults / save / apply saved
  const tbtn = dlg.querySelector(".cs-tbtn"), tmenu = dlg.querySelector(".cs-tmenu");
  tbtn.onclick = () => {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem("ltv.chart.template") || "null"); } catch { /* */ }
    tmenu.innerHTML = `<div data-t="defaults">Apply defaults</div><div data-t="save">Save as my default</div>${saved ? '<div data-t="mine">Apply my default</div>' : ""}`;
    tmenu.classList.toggle("hidden");
    tmenu.querySelectorAll("[data-t]").forEach((d) => d.onclick = () => {
      const t = d.dataset.t;
      if (t === "save") { try { localStorage.setItem("ltv.chart.template", JSON.stringify(draft)); } catch { /* */ } }
      else Object.assign(draft, JSON.parse(JSON.stringify(t === "defaults" ? defaults : saved)));
      tmenu.classList.add("hidden"); changed(); render();
    });
  };
  render();
  dlg.onclose = () => { if (dlg.returnValue !== "ok") onChange(orig); };
  dlg.returnValue = "";
  dlg.showModal();
}

// ------------------------------------------------------------------ context menus (with submenus)
let menuEl = null;
function closeMenu() { if (menuEl) { menuEl.remove(); menuEl = null; } document.querySelectorAll(".cs-menu").forEach((m) => m.remove()); }
function buildMenu(items, x, y, level = 0, parentLeft = 0) {
  const m = document.createElement("div");
  m.className = "cs-menu";
  for (const it of items) {
    if (it === "-") { m.appendChild(Object.assign(document.createElement("div"), { className: "cs-msep" })); continue; }
    const d = document.createElement("div");
    d.className = "cs-mi" + (it.disabled ? " dis" : "") + (it.checked && it.icon ? " sel" : "");
    d.innerHTML = `<span class="cs-mk">${it.icon || (it.checked ? "✓" : "")}</span><span class="cs-mn">${esc(it.label)}</span>` +
      `<span class="cs-mkeys">${it.keys ? esc(it.keys) : it.sub ? "›" : it.hint ? esc(it.hint) : ""}</span>`;
    if (it.sub) {
      d.onmouseenter = () => {
        m.querySelectorAll(".cs-mi.open").forEach((x) => x.classList.remove("open"));
        document.querySelectorAll(`.cs-menu[data-level="${level + 1}"]`).forEach((x) => x.remove());
        d.classList.add("open");
        const r = d.getBoundingClientRect();
        buildMenu(it.sub, r.right - 4, r.top - 6, level + 1, r.left);
      };
    } else {
      d.onmouseenter = () => document.querySelectorAll(`.cs-menu[data-level="${level + 1}"]`).forEach((x) => x.remove());
      d.onclick = () => { if (it.disabled) return; closeMenu(); it.action && it.action(); };
    }
    m.appendChild(d);
  }
  m.dataset.level = level;
  document.body.appendChild(m);
  const w = m.offsetWidth, h = m.offsetHeight;
  if (level > 0 && x + w > window.innerWidth) x = parentLeft - w + 4;
  m.style.left = Math.max(4, Math.min(x, window.innerWidth - w - 4)) + "px";
  m.style.top = Math.max(4, Math.min(y, window.innerHeight - h - 4)) + "px";
  if (!level) menuEl = m;
  return m;
}
function openMenu(items, x, y) { closeMenu(); buildMenu(items, x, y); }
document.addEventListener("pointerdown", (e) => { if (!e.target.closest(".cs-menu")) closeMenu(); }, true);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
window.addEventListener("resize", closeMenu);

// in-app replacements for window.confirm / window.prompt (modal, themed, keyboard: Enter = OK, Esc = cancel)
function modal({ title = "Confirm", message = "", ok = "OK", cancel = "Cancel", danger = false, input = null }) {
  return new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.className = "ltv-modal";
    const esc = (x) => String(x).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    d.innerHTML = `<form method="dialog" class="dlg"><div class="dlg-head"><b>${esc(title)}</b><button value="cancel" title="Close">✕</button></div>
      <div class="lm-body">${message ? `<p>${esc(message)}</p>` : ""}${input ? `<input name="v" type="${input.type || "text"}" step="any" value="${esc(input.value ?? "")}" ${input.min != null ? `min="${input.min}"` : ""}>` : ""}</div>
      <div class="dlg-foot"><span class="spacer"></span><button value="cancel">${esc(cancel)}</button><button value="ok" class="primary ${danger ? "danger" : ""}">${esc(ok)}</button></div></form>`;
    document.body.appendChild(d);
    d.onclose = () => { const v = d.returnValue === "ok"; const val = d.querySelector('[name="v"]')?.value; d.remove(); resolve(input ? (v ? val : null) : v); };
    d.showModal();
    const f = d.querySelector(input ? '[name="v"]' : "button.primary"); f.focus(); if (input) f.select();
  });
}
const confirmModal = (message, o = {}) => modal({ title: o.title || "Please confirm", message, ok: o.ok || "OK", danger: o.danger, cancel: o.cancel });
const promptModal = (message, value, o = {}) => modal({ title: o.title || "Enter a value", message, ok: o.ok || "Save", input: { value, type: o.type, min: o.min } });

window.LTVSettings = { DEFAULTS, TIMEZONES, openDialog, openMenu, closeMenu, pairValue, setPair, confirm: confirmModal, prompt: promptModal };
})();
