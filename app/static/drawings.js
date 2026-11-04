/* TickLens drawing tools: a canvas overlay on the main pane of a lightweight-charts chart.
   Points are stored as {t: UTC seconds, p: price} so drawings survive timeframe changes.
   Usage: const D = LTVDraw.init({chart, el, series: () => mainSeries, bars: () => bars, tf: () => S.tf}); D.setSymbol(sym) */
(() => {
"use strict";

// ------------------------------------------------------------------ catalogue
const FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.618, 2.618, 3.618, 4.236];
const FIB_COL = ["#787b86", "#f23645", "#ff9800", "#4caf50", "#089981", "#00bcd4", "#787b86", "#2962ff", "#f23645", "#9c27b0", "#e91e63"];
const FIB_TIME = [0, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89];
const GANN = [[1, 8], [1, 4], [1, 3], [1, 2], [1, 1], [2, 1], [3, 1], [4, 1], [8, 1]];
const EMOJI = ["😀", "😂", "😍", "😎", "🤔", "😱", "😡", "👍", "👎", "🙏", "👀", "🔥", "🚀", "💰", "💎", "📈", "📉", "⚠️", "✅", "❌", "⭐", "🎯", "🐂", "🐻"];

// n: points (0 = freehand, -1 = click until double-click/Enter). "#Title" rows are menu section headers.
const GROUPS = [
  { id: "cursor", tools: [
    ["cross", "Cross", 0], ["dot", "Dot", 0], ["arrowcur", "Arrow", 0], ["eraser", "Eraser", 0]] },
  { id: "lines", title: "Lines", tools: [
    ["#Lines"],
    ["trend", "Trendline", 2, "Alt + T"], ["ray", "Ray", 2], ["info", "Info line", 2], ["extended", "Extended line", 2],
    ["angle", "Trend angle", 2], ["hline", "Horizontal line", 1, "Alt + H"], ["hray", "Horizontal ray", 1, "Alt + J"],
    ["vline", "Vertical line", 1, "Alt + V"], ["cross_line", "Crossline", 1, "Alt + C"],
    ["#Channels"],
    ["channel", "Parallel channel", 3], ["regression", "Regression trend", 2], ["flattop", "Flat top/bottom", 3], ["disjoint", "Disjoint channel", 3],
    ["#Pitchforks"],
    ["pitchfork", "Pitchfork", 3], ["schiff", "Schiff pitchfork", 3], ["mschiff", "Modified Schiff pitchfork", 3], ["inside_pf", "Inside pitchfork", 3]] },
  { id: "fib", title: "Fibonacci", tools: [
    ["#Fibonacci"],
    ["fib", "Fib retracement", 2, "Alt + F"], ["fibext", "Trend-based fib extension", 3], ["fibchannel", "Fib channel", 3],
    ["fibtime", "Fib time zone", 2], ["fibfan", "Fib speed resistance fan", 2], ["fibtimetrend", "Trend-based fib time", 3],
    ["fibcircle", "Fib circles", 2], ["fibspiral", "Fib spiral", 2], ["fibarc", "Fib speed resistance arcs", 2],
    ["fibwedge", "Fib wedge", 3], ["pitchfan", "Pitchfan", 3],
    ["#Gann"],
    ["gannbox", "Gann box", 2], ["gannsq", "Gann square fixed", 2], ["gannsquare", "Gann square", 2], ["gannfan", "Gann fan", 2]] },
  { id: "patterns", title: "Patterns", tools: [
    ["#Chart patterns"],
    ["xabcd", "XABCD pattern", 5], ["cypher", "Cypher pattern", 5], ["hs", "Head and shoulders", 7], ["abcd", "ABCD pattern", 4],
    ["tripattern", "Triangle pattern", 4], ["threedrives", "Three drives pattern", 7],
    ["#Elliott waves"],
    ["ew_impulse", "Elliott impulse wave (1·2·3·4·5)", 6], ["ew_corr", "Elliott correction wave (A·B·C)", 4],
    ["ew_tri", "Elliott triangle wave (A·B·C·D·E)", 6], ["ew_dbl", "Elliott double combo wave (W·X·Y)", 4],
    ["ew_tpl", "Elliott triple combo wave (W·X·Y·X·Z)", 6],
    ["#Cycles"],
    ["cyclic", "Cyclic lines", 2], ["timecycles", "Time cycles", 2], ["sine", "Sine line", 2]] },
  { id: "forecast", title: "Forecasting and measurement", tools: [
    ["#Forecasting"],
    ["long", "Long position", 2], ["short", "Short position", 2], ["forecast", "Position forecast", 2],
    ["barspattern", "Bars pattern", 3], ["ghost", "Ghost feed", -1], ["sector", "Sector", 3],
    ["#Volume-based"],
    ["avwap", "Anchored VWAP", 1], ["vprofile", "Fixed range volume profile", 2], ["avprofile", "Anchored volume profile", 1],
    ["#Measurers"],
    ["prange", "Price range", 2], ["drange", "Date range", 2], ["dprange", "Date and price range", 2]] },
  { id: "shapes", title: "Brushes, arrows and shapes", tools: [
    ["#Brushes"],
    ["brush", "Brush", 0], ["highlighter", "Highlighter", 0],
    ["#Arrows"],
    ["arrowmarker", "Arrow marker", 2], ["arrowline", "Arrow", 2], ["arrowup", "Arrow mark up", 1], ["arrowdown", "Arrow mark down", 1],
    ["arrowleft", "Arrow mark left", 1], ["arrowright", "Arrow mark right", 1],
    ["#Shapes"],
    ["rect", "Rectangle", 2, "Alt + Shift + R"], ["rotrect", "Rotated rectangle", 3], ["path", "Path", -1], ["circle", "Circle", 2],
    ["ellipse", "Ellipse", 2], ["polyline", "Polyline", -1], ["triangle", "Triangle", 3], ["arc", "Arc", 3],
    ["curve", "Curve", 3], ["dcurve", "Double curve", 3]] },
  { id: "text", title: "Text and notes", tools: [
    ["#Text and notes"],
    ["text", "Text", 1], ["anchored", "Anchored text", 1], ["note", "Note", 1], ["pricenote", "Price note", 2], ["pin", "Pin", 1],
    ["callout", "Callout", 2], ["comment", "Comment", 1], ["pricelabel", "Price label", 1], ["signpost", "Signpost", 1],
    ["flag", "Flag mark", 1]] },
  { id: "icons", title: "Emojis", tools: EMOJI.map((e, i) => ["emoji" + i, e, 1]) },
];
const TOOLS = {};
for (const g of GROUPS) for (const [id, name, n, keys] of g.tools) if (!id.startsWith("#")) TOOLS[id] = { id, name, n, keys, group: g.id };
for (let i = 0; i < EMOJI.length; i++) TOOLS["emoji" + i].emoji = EMOJI[i];
TOOLS.projection = { id: "projection", name: "Projection", n: 3, group: "forecast", hidden: true };   // kept for older saved drawings
const TEXT_TOOLS = new Set(["text", "anchored", "note", "pin", "pricenote", "callout", "comment", "signpost", "flag", "info"]);
const FILL_TOOLS = new Set(["rect", "rotrect", "circle", "ellipse", "triangle", "polyline", "channel", "flattop", "disjoint",
  "arc", "gannbox", "gannsquare", "sector", "callout", "comment", "note", "text", "anchored", "pricelabel", "arrowmarker"]);
const LABELS = {
  xabcd: "XABCD", cypher: "XABCD", hs: ["", "LS", "", "H", "", "RS", ""], abcd: "ABCD", tripattern: "ABCD",
  threedrives: ["", "1", "", "2", "", "3", ""], ew_impulse: "012345", ew_corr: "0ABC", ew_tri: "0ABCDE",
  ew_dbl: "0WXY", ew_tpl: "0WXYXZ",
};

// ------------------------------------------------------------------ icons (24px stroke SVG, one per tool)
const o = (x, y) => `<circle cx="${x}" cy="${y}" r="1.7"/>`;
const SVG = {
  cross: '<path d="M12 3v7M12 14v7M3 12h7M14 12h7"/>',
  dot: '<circle cx="12" cy="12" r="2.5" fill="currentColor"/>',
  arrowcur: '<path d="M6 3l12 9-5.5 1 3 6-2 1-3-6L6 18z"/>',
  eraser: '<path d="M4 15l9-9 7 7-6 6H8z"/><path d="M8 19h12M9 10l7 7"/>',
  trend: o(5, 19) + o(19, 5) + '<path d="M6.3 17.7L17.7 6.3"/>',
  ray: o(5, 19) + o(11, 13) + '<path d="M6.3 17.7l3.4-3.4M12.3 11.7L21 3"/>',
  info: o(5, 19) + o(17, 5) + '<path d="M6.3 17.7L15.7 6.3"/><rect x="13" y="15" width="8" height="5" rx="1.5"/>',
  extended: o(9, 15) + o(15, 9) + '<path d="M3 21l4.8-4.8M10.2 13.8l3.6-3.6M16.2 7.8L21 3"/>',
  angle: o(5, 19) + o(18, 6) + '<path d="M6.3 17.7L16.7 7.3M7 19h14M12 19a6 6 0 00-2-4.5"/>',
  hline: o(12, 12) + '<path d="M3 12h7.3M13.7 12H21"/>',
  hray: o(5, 12) + '<path d="M6.7 12H21"/>',
  vline: o(12, 12) + '<path d="M12 3v7.3M12 13.7V21"/>',
  cross_line: o(12, 12) + '<path d="M3 12h7.3M13.7 12H21M12 3v7.3M12 13.7V21"/>',
  channel: o(5, 13) + o(17, 4) + o(7, 20) + '<path d="M6.4 12L15.6 5M8.4 19L20 10"/>',
  regression: o(5, 16) + o(19, 8) + '<path d="M3 13l18-9v6L3 19z"/>',
  flattop: o(5, 9) + o(17, 4) + o(5, 18) + '<path d="M6.6 8.3l8.8-3.6M6.7 18H20"/>',
  disjoint: o(5, 6) + o(18, 4) + o(5, 14) + '<path d="M6.7 5.7l9.6-1.4M6.7 14.6L19 20"/>',
  pitchfork: o(5, 19) + o(10, 7) + o(17, 15) + '<path d="M6.3 17.7L20 4M11 6l9 0M17 15l4-4M10.8 8.4l2.7 3"/>',
  schiff: o(4, 19) + o(10, 7) + o(17, 15) + '<path d="M7 13L20 4M11 6l9 0M17 15l4-4M5.6 19H15.3"/>',
  mschiff: o(4, 19) + o(10, 7) + o(17, 15) + '<path d="M8 12L20 4M11 6l9 0M17 15l4-4M5 17.5l4-9"/>',
  inside_pf: o(4, 19) + o(9, 8) + o(16, 17) + '<path d="M6 13l6-9M10 9l7-6M16 15l5-9M5.3 18l3-8.4"/>',
  fib: o(4, 20) + o(20, 4) + '<path d="M3 4h15.3M3 9h18M3 14h18M5.7 20H21"/>',
  fibext: o(4, 9) + o(12, 4) + '<path d="M5.6 8L10.4 5M3 13h18M3 17h18M3 21h18"/>',
  fibchannel: o(5, 13) + o(18, 4) + '<path d="M6.5 12L16.6 5M4 19L20 8M5 23L21 12"/>',
  fibtime: o(4, 4) + o(9, 13) + '<path d="M4 6v15M9 15v6M13 3v18M17 3v18M21 3v18M5 6l3 5" stroke-dasharray="0"/>',
  fibfan: o(4, 20) + o(18, 6) + '<path d="M5.5 18.5L21 10M5.5 18.5L21 14M5.5 18.5L12 3M5.5 18.5L16 3M4 18V4M6 20h15"/>',
  fibtimetrend: o(4, 5) + o(8, 19) + o(13, 19) + '<path d="M4.7 6.6L7.3 17.4M9.7 19h1.6M17 3v18M21 3v18"/>',
  fibcircle: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5.5"/><circle cx="12" cy="12" r="2.5"/>' + o(19, 5),
  fibspiral: '<path d="M12 12a2 2 0 012 2 4 4 0 01-4 4 6 6 0 01-6-6 8 8 0 018-8"/>' + o(12, 12) + o(17, 7) + '<path d="M13 11l3-3"/>',
  fibarc: '<path d="M3 18a9 9 0 0118 0M6 18a6 6 0 0112 0M9 18a3 3 0 016 0"/>' + o(12, 18),
  fibwedge: o(5, 4) + o(5, 20) + o(20, 20) + '<path d="M5 5.7v12.6M6.7 20h11.6M5 9a11 11 0 0111 11M5 13a7 7 0 017 7"/>',
  pitchfan: o(4, 20) + o(9, 6) + o(17, 15) + '<path d="M5 18.5L9 7.5M5.5 19L20 13M5.5 19L20 7M5.5 19L16 4M10 7.5l6 6"/>',
  gannbox: '<rect x="4" y="4" width="16" height="16"/><path d="M4 9.3h16M4 14.6h16M9.3 4v16M14.6 4v16"/>' + o(4, 20) + o(20, 4),
  gannsq: '<rect x="4" y="4" width="16" height="16"/><path d="M4 12h16M12 4v16M4 20L20 4M4 20l16-8M4 20l8-16"/>' + o(4, 20),
  gannsquare: '<rect x="4" y="4" width="16" height="16"/><path d="M4 12h16M12 4v16M4 20L20 4M4 20l16-8M4 20l8-16"/>' + o(4, 20) + o(20, 4),
  gannfan: o(4, 20) + o(15, 9) + '<path d="M5.5 18.5L21 10M5.5 18.5L21 15M5.5 18.5L12 3M5.5 18.5L17 3M5.5 18.5L13.6 10.4"/>',
  xabcd: o(4, 19) + o(8, 5) + o(12, 14) + o(16, 6) + o(20, 18) + '<path d="M4.6 17.3L7.4 6.7M9 6.5l2 6M12.7 12.5l2.6-5M16.6 7.6l2.8 8.8M8 5l8 1M4 19l8-5" />',
  cypher: o(4, 19) + o(8, 5) + o(12, 13) + o(16, 6) + o(20, 18) + '<path d="M4.6 17.3L7.4 6.7M9 6.5l2 5M12.7 11.5l2.6-4M16.6 7.6l2.8 8.8"/><text x="10" y="23" font-size="6" fill="currentColor" stroke="none">C</text>',
  hs: o(3, 18) + o(7, 10) + o(10, 15) + o(12, 5) + o(14, 15) + o(17, 10) + o(21, 18) + '<path d="M3 18l4-8 3 5 2-10 2 10 3-5 4 8M2 15h20"/>',
  abcd: o(4, 18) + o(9, 5) + o(15, 13) + o(20, 3) + '<path d="M4 18l5-13 6 8 5-10M4 18l11-5M9 5l11-2"/>',
  tripattern: o(3, 20) + o(8, 4) + o(12, 15) + o(16, 8) + '<path d="M3 20L8 4l4 11 4-7M8 4l13 8M3 20l18-8"/>',
  threedrives: o(3, 16) + o(6, 8) + o(9, 18) + o(12, 6) + o(15, 19) + o(18, 4) + '<path d="M3 16l3-8 3 10 3-12 3 13 3-15 3-1"/>',
  ew_impulse: o(3, 18) + o(8, 12) + o(11, 15) + o(16, 8) + o(21, 13) + '<path d="M3 18l5-6 3 3 5-7 5 5"/><text x="6" y="7" font-size="6" fill="currentColor" stroke="none">1</text><text x="17" y="5" font-size="6" fill="currentColor" stroke="none">5</text>',
  ew_corr: o(3, 18) + o(8, 12) + o(13, 16) + o(20, 9) + '<path d="M3 18l5-6 5 4 7-7"/><text x="6" y="8" font-size="6" fill="currentColor" stroke="none">A</text><text x="17" y="6" font-size="6" fill="currentColor" stroke="none">C</text>',
  ew_tri: o(3, 18) + o(7, 11) + o(11, 16) + o(15, 12) + o(19, 15) + '<path d="M3 18l4-7 4 5 4-4 4 3"/><text x="5" y="7" font-size="6" fill="currentColor" stroke="none">A</text><text x="17" y="9" font-size="6" fill="currentColor" stroke="none">E</text>',
  ew_dbl: o(3, 18) + o(9, 12) + o(14, 16) + o(20, 9) + '<path d="M3 18l6-6 5 4 6-7"/><text x="6" y="8" font-size="6" fill="currentColor" stroke="none">W</text><text x="17" y="6" font-size="6" fill="currentColor" stroke="none">Y</text>',
  ew_tpl: o(3, 18) + o(8, 12) + o(12, 16) + o(16, 11) + o(20, 14) + '<path d="M3 18l5-6 4 4 4-5 4 3"/><text x="5" y="8" font-size="6" fill="currentColor" stroke="none">W</text><text x="17" y="8" font-size="6" fill="currentColor" stroke="none">Z</text>',
  cyclic: '<path d="M4 3v18M9 3v18M14 3v18M19 3v18"/>' + o(4, 12) + o(9, 12),
  timecycles: '<path d="M2 14a4 4 0 018 0M10 14a4 4 0 018 0M18 14a2.5 2.5 0 015 0"/>' + o(2, 14) + o(10, 14),
  sine: '<path d="M2 14c2-12 5-12 7 0s5 12 7 0 4-8 6-4"/>' + o(5.5, 5) + o(12.5, 23),
  long: o(4, 4) + o(4, 20) + '<path d="M5.7 4H20M4 12h16M5.7 20H20"/><text x="10" y="11" font-size="7" fill="currentColor" stroke="none">L</text>',
  short: o(4, 4) + o(4, 20) + '<path d="M5.7 4H20M4 12h16M5.7 20H20"/><text x="10" y="19" font-size="7" fill="currentColor" stroke="none">S</text>',
  forecast: '<path d="M5 4v16M10 6v12M3 8h4v8H3zM8 9h4v6H8z"/><path d="M16 6v6M14 10l2 2 2-2"/><circle cx="16" cy="16" r="1.5" fill="currentColor"/>',
  barspattern: '<path d="M5 5v14M10 3v16M15 6v13M19 4v14M3 8h4v7H3zM8 6h4v8H8zM13 9h4v6h-4zM17 7h4v7h-4z"/>',
  ghost: o(3, 16) + '<path d="M4.5 15.2L20 6M8 10v8M12 8v8M16 6v8M7 12h2v4H7zM11 10h2v4h-2zM15 8h2v4h-2z"/>' + o(21, 5),
  sector: o(5, 5) + o(5, 19) + o(19, 19) + '<path d="M5 6.7v10.6M6.7 19h10.6M5 5a14 14 0 0114 14"/>',
  avwap: '<path d="M7 4v16M13 6v12M5 8h4v8H5zM11 9h4v6h-4z"/>' + o(3, 16) + '<path d="M4.5 15L21 6"/>',
  vprofile: o(4, 20) + o(20, 4) + '<path d="M4 4v14.3M20 5.7V20M4 7h6v3H4zM4 10h9v3H4zM4 13h5v3H4z"/>',
  avprofile: o(3, 12) + '<path d="M4.7 12H9M9 5v14M9 6h7v3H9zM9 9h11v3H9zM9 12h9v3H9zM9 15h5v3H9z"/>',
  prange: o(5, 4) + o(5, 20) + '<path d="M6.7 4H20M6.7 20H20M13 18V6M10 9l3-3 3 3"/>',
  drange: o(4, 4) + o(20, 20) + '<path d="M4 5.7V20M20 4v14.3M6 12h12M15 9l3 3-3 3"/>',
  dprange: o(4, 20) + o(20, 4) + '<path d="M5.7 20H20V5.7M4 18.3V4h14.3M12 7v10M7 12h10M10 9l2-2 2 2M15 10l2 2-2 2"/>',
  brush: '<path d="M14 4l6 6-8 8-6-6z"/><path d="M6 12l-3 8 8-3"/>',
  highlighter: '<path d="M15 3l6 6-9 9-6-6z"/><path d="M6 12l-2 6 2 2 6-2M3 21h6"/>',
  arrowmarker: '<path d="M4 17l9-9-2-2h8v8l-2-2-9 9z"/>',
  arrowline: o(4, 20) + '<path d="M5.3 18.7L20 4M13 4h7v7"/>',
  arrowup: '<path d="M12 4l7 7h-4v9H9v-9H5z"/>',
  arrowdown: '<path d="M12 20l7-7h-4V4H9v9H5z"/>',
  arrowleft: '<path d="M4 12l7-7v4h9v6h-9v4z"/>',
  arrowright: '<path d="M20 12l-7-7v4H4v6h9v4z"/>',
  rect: '<rect x="4" y="6" width="16" height="12"/>' + o(4, 6) + o(20, 18),
  rotrect: '<path d="M3 13L13 3l8 8-10 10z"/>' + o(3, 13) + o(13, 3) + o(21, 11),
  path: o(3, 18) + o(9, 8) + o(15, 15) + '<path d="M4 16.5l4-7M10.5 9.3l3 4.4M16.5 14L21 6M17 6h4v4"/>',
  circle: '<circle cx="12" cy="12" r="8"/>' + o(12, 12) + o(20, 12),
  ellipse: '<ellipse cx="12" cy="12" rx="9" ry="6"/>' + o(3, 6) + o(21, 18),
  polyline: '<path d="M3 17l5-12 6 6 7-4-3 13z"/>' + o(3, 17) + o(8, 5) + o(14, 11) + o(21, 7),
  triangle: '<path d="M12 4l9 16H3z"/>' + o(12, 4) + o(21, 20) + o(3, 20),
  arc: '<path d="M3 18a10 10 0 0118 0"/>' + o(3, 18) + o(21, 18) + o(12, 8),
  curve: '<path d="M3 19C6 5 17 5 21 12"/>' + o(3, 19) + o(21, 12),
  dcurve: '<path d="M3 15c3-12 6-12 9-3s6 9 9-3"/>' + o(3, 15) + o(21, 9),
  text: '<path d="M5 5h14M12 5v15M9 20h6"/>',
  anchored: '<path d="M7 5h10M12 5v11M10 16h4"/><path d="M5 20h14"/>' + o(5, 20),
  note: '<rect x="4" y="4" width="16" height="13" rx="2"/><path d="M8 17l-2 4 6-4M8 9h8M8 12h5"/>',
  pricenote: o(4, 20) + '<path d="M5.3 18.7L12 12"/><rect x="11" y="6" width="10" height="7" rx="1.5"/>',
  pin: '<path d="M12 21v-6M7 15h10l-2-4V5h1V3H8v2h1v6z"/>',
  callout: '<rect x="3" y="3" width="18" height="11" rx="2"/><path d="M8 14l-3 7 8-7"/>',
  comment: '<path d="M4 4h16v12H10l-6 5z"/>',
  pricelabel: '<path d="M3 12l5-6h13v12H8z"/>' + o(8, 12),
  signpost: '<path d="M12 21V8M5 3h12l3 3-3 3H5z"/>',
  flag: '<path d="M6 21V4M6 4h12l-3 4 3 4H6"/>',
  ruler: '<path d="M3 17L17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/>',
  zoom: '<circle cx="10" cy="10" r="6.5"/><path d="M15 15l6 6M10 7v6M7 10h6"/>',
  magnet: '<path d="M6 3v9a6 6 0 0012 0V3h-4v9a2 2 0 01-4 0V3z"/><path d="M6 7h4M14 7h4"/>',
  stay: '<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M14 6l3 3"/><rect x="14" y="15" width="7" height="6" rx="1"/><path d="M15.5 15v-2a2 2 0 014 0"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 018 0v4"/>',
  unlock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 017.5-2"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeoff: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/><path d="M3 3l18 18"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14"/>',
  tree: '<path d="M4 5h6M8 12h12M8 19h12M5 5v14h3M5 12h3"/>',
  star: '<path d="M12 3l2.8 5.8 6.2.9-4.5 4.4 1 6.2L12 17.4 6.5 20.3l1-6.2L3 9.7l6.2-.9z"/>',
  starfill: '<path fill="currentColor" d="M12 3l2.8 5.8 6.2.9-4.5 4.4 1 6.2L12 17.4 6.5 20.3l1-6.2L3 9.7l6.2-.9z"/>',
  emoji: '<circle cx="12" cy="12" r="9"/><circle cx="9" cy="10" r=".8" fill="currentColor"/><circle cx="15" cy="10" r=".8" fill="currentColor"/><path d="M8 14.5c2 2.5 6 2.5 8 0"/>',
};
SVG.projection = SVG.sector;
const svg = (k, size = 22) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">${SVG[k] || ""}</svg>`;

// ------------------------------------------------------------------ geometry helpers
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const lerp = (a, b, k) => ({ x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k });
const add = (a, b) => ({ x: a.x + b.x, y: a.y + b.y });
const sub = (a, b) => ({ x: a.x - b.x, y: a.y - b.y });
const mid = (a, b) => lerp(a, b, 0.5);
function extendPt(a, b, far = 1e5) { const d = dist(a, b) || 1; return { x: b.x + (b.x - a.x) / d * far, y: b.y + (b.y - a.y) / d * far }; }
const fmtP = (p) => (Math.abs(p) >= 1000 ? p.toFixed(2) : Math.abs(p) >= 1 ? p.toFixed(2) : p.toPrecision(4));
const fmtN = (x) => x.toLocaleString(undefined, { maximumFractionDigits: 2 });
function fmtSpan(sec) {
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.round((sec % 3600) / 60);
  return [d && `${d}d`, h && `${h}h`, m && `${m}m`].filter(Boolean).join(" ") || "0m";
}
function hexA(c, a) {
  const m = /^#?([\da-f]{2})([\da-f]{2})([\da-f]{2})/i.exec(c || "");
  return m ? `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},${a})` : c;
}

// ------------------------------------------------------------------ main
function init({ chart, el, series, bars, tf, onChange = () => {}, onHideIndicators = () => {}, onRemoveIndicators = () => {}, leftOffset = () => 0,
  toolbar = true, onToolbar = () => {}, vpData = () => null }) {
  const wrap = el.parentElement;
  const cv = document.createElement("canvas");
  cv.className = "draw-canvas";
  wrap.appendChild(cv);
  const ctx = cv.getContext("2d");
  const dpr = () => window.devicePixelRatio || 1;

  const st = {
    symbol: null, items: [], sel: null, tool: "cross", cursor: "cross", magnet: 0, stay: false, lockAll: false, hideAll: false,
    hideInd: false, hidePos: false, draft: null, drag: null, hover: null, undo: [], redo: [], measure: null, zoom: null, last: {},
  };
  try { Object.assign(st.last, JSON.parse(localStorage.getItem("ltv.draw.prefs") || "{}")); } catch { /* ignore */ }
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

  // ---------------------------------------------------------------- coordinates
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
  function tOfLogical(L) {
    const b = B(), n = b.length, step = tf();
    if (!n) return 0;
    if (L <= 0) return b[0][0] + L * step;
    if (L >= n - 1) return b[n - 1][0] + (L - (n - 1)) * step;
    const i = Math.floor(L);
    return b[i][0] + (L - i) * (b[i + 1][0] - b[i][0]);
  }
  const xOfT = (t) => { const L = logicalOfT(t); return L == null ? null : chart.timeScale().logicalToCoordinate(L); };
  const yOfP = (p) => series().priceToCoordinate(p);
  const toXY = (pt) => ({ x: xOfT(pt.t), y: yOfP(pt.p) });
  function fromXY(x, y, snap = true) {
    let L = chart.timeScale().coordinateToLogical(x);
    if (L == null) return null;
    if (snap) L = Math.round(L);
    let p = series().coordinateToPrice(y);
    if (p == null) return null;
    if (st.magnet && snap) {
      const bar = B()[L];
      if (bar) {
        let best = null;
        for (const v of bar.slice(1, 5)) { const d = Math.abs(yOfP(v) - y); if (!best || d < best.d) best = { v, d }; }
        if (st.magnet === 2 || best.d < 30) p = best.v;
      }
    }
    return { t: tOfLogical(L), p };
  }
  const paneH = () => { try { return chart.panes()[0].getHeight(); } catch { return el.clientHeight; } };
  const paneW = () => chart.timeScale().width();
  const barIdx = (t) => { const L = logicalOfT(t); return L == null ? null : Math.round(L); };

  // ---------------------------------------------------------------- persistence + history
  const key = () => `ltv.draw.${st.symbol}`;
  const strip = (d) => ({ id: d.id, type: d.type, pts: d.pts, style: d.style, text: d.text, locked: d.locked, hidden: d.hidden });
  function persist() { try { localStorage.setItem(key(), JSON.stringify(st.items.map(strip))); } catch { /* full */ } onChange(); }
  function snapshot() { st.undo.push(JSON.stringify(st.items.map(strip))); if (st.undo.length > 100) st.undo.shift(); st.redo = []; }
  function restore(json) { st.items = JSON.parse(json); st.sel = null; persist(); renderFloat(); }
  function setSymbol(sym) {
    st.symbol = sym; st.sel = null; st.draft = null; st.undo = []; st.redo = [];
    try { st.items = JSON.parse(localStorage.getItem(key()) || "[]"); } catch { st.items = []; }
    renderFloat(); onChange();
  }
  const newId = () => Math.random().toString(36).slice(2, 10);
  function defaultStyle(type) {
    const base = { color: "#2962ff", width: 2, dash: "solid", fill: "#2962ff", fillA: 0.15, font: 14, extL: false, extR: false, labels: true };
    if (type === "highlighter") Object.assign(base, { color: "#ffeb3b", width: 16 });
    if (type === "brush") Object.assign(base, { color: "#f23645" });
    if (["fib", "fibext", "fibchannel", "fibtime", "fibfan", "fibcircle", "fibarc", "fibwedge", "gannbox", "gannsq", "gannfan", "pitchfan"].includes(type)) base.width = 1;
    if (type === "text" || type === "anchored") Object.assign(base, { color: css("--text") || "#d1d4dc", fillA: 0 });
    if (["arrowup", "long"].includes(type)) base.color = "#089981";
    if (["arrowdown", "short"].includes(type)) base.color = "#f23645";
    if (type === "avwap") base.color = "#ff9800";
    if (type === "vprofile" || type === "avprofile") Object.assign(base, { color: "#2962ff", fill: "#2962ff", vp: { ...(st.last[type + ".vp"] || {}) } });
    return Object.assign(base, st.last[type] || {});
  }

  // ---------------------------------------------------------------- render primitives (also record hit paths)
  let hits = null;
  const dashOf = (s) => (s.dash === "dashed" ? [6, 4] : s.dash === "dotted" ? [2, 3] : []);
  function stroke(path, s, w) {
    ctx.strokeStyle = s.color; ctx.lineWidth = w ?? s.width; ctx.setLineDash(dashOf(s)); ctx.stroke(path);
    hits && hits.push({ path, stroke: true });
  }
  function fillP(path, color, a) { ctx.fillStyle = hexA(color, a); ctx.fill(path); hits && hits.push({ path, stroke: false }); }
  function seg(a, b, s, w) { const p = new Path2D(); p.moveTo(a.x, a.y); p.lineTo(b.x, b.y); stroke(p, s, w); return p; }
  function polyPath(P, close) { const p = new Path2D(); P.forEach((q, i) => (i ? p.lineTo(q.x, q.y) : p.moveTo(q.x, q.y))); if (close) p.closePath(); return p; }
  function poly(P, s, close = false, fill = false) {
    const p = polyPath(P, close);
    if (fill) fillP(p, s.fill, s.fillA);
    stroke(p, s);
    return p;
  }
  function label(x, y, str, { color = "#fff", bg = null, align = "center", base = "middle", font = 12, pad = 4, bold = false, border = null } = {}) {
    if (str == null || str === "") return;
    ctx.font = `${bold ? "600 " : ""}${font}px -apple-system, "Trebuchet MS", Roboto, sans-serif`;
    const lines = String(str).split("\n");
    const w = Math.max(...lines.map((l) => ctx.measureText(l).width)), lh = font * 1.25, h = lh * lines.length;
    let bx = align === "center" ? x - w / 2 : align === "right" ? x - w : x;
    let by = base === "middle" ? y - h / 2 : base === "bottom" ? y - h : y;
    const box = new Path2D(); box.rect(bx - pad, by - pad / 2, w + pad * 2, h + pad);
    if (bg) { ctx.fillStyle = bg; ctx.fill(box); }
    if (border) { ctx.strokeStyle = border; ctx.lineWidth = 1; ctx.setLineDash([]); ctx.stroke(box); }
    hits && hits.push({ path: box, stroke: false });
    ctx.fillStyle = color; ctx.textAlign = "left"; ctx.textBaseline = "top";
    lines.forEach((l, i) => ctx.fillText(l, bx, by + i * lh + (lh - font) / 2));
    return { x: bx - pad, y: by - pad / 2, w: w + pad * 2, h: h + pad };
  }
  function arrowHead(a, b, s, size = 10) {
    const ang = Math.atan2(b.y - a.y, b.x - a.x);
    const p = new Path2D();
    p.moveTo(b.x, b.y);
    p.lineTo(b.x - size * Math.cos(ang - 0.45), b.y - size * Math.sin(ang - 0.45));
    p.lineTo(b.x - size * Math.cos(ang + 0.45), b.y - size * Math.sin(ang + 0.45));
    p.closePath();
    ctx.fillStyle = s.color; ctx.fill(p); hits && hits.push({ path: p, stroke: false });
  }
  function hlineAt(y, s, x0 = 0, x1 = paneW()) { return seg({ x: x0, y }, { x: x1, y }, s); }
  const priceTag = (y, p, color) => label(paneW() - 2, y, fmtP(p), { bg: color, align: "right", font: 11 });
  const W = () => paneW(), H = () => paneH();

  // levels between two points (fib-like): k=0 at b, k=1 at a (TradingView retracement convention)
  function levelLines(a, b, pa, pb, s, levels, cols, { ext = false } = {}) {
    const x0 = Math.min(a.x, b.x), x1 = s.extR || ext ? W() : Math.max(a.x, b.x), xl = s.extL ? 0 : x0;
    let prevY = null;
    levels.forEach((k, i) => {
      const y = b.y + (a.y - b.y) * k, price = pb + (pa - pb) * k, c = cols[i % cols.length];
      if (prevY != null && s.fillA > 0) {
        const r = new Path2D(); r.rect(xl, Math.min(prevY, y), x1 - xl, Math.abs(y - prevY)); ctx.fillStyle = hexA(c, s.fillA * 0.8); ctx.fill(r);
      }
      seg({ x: xl, y }, { x: x1, y }, { ...s, color: c });
      if (s.labels) label(xl + 2, y - 2, `${k} (${fmtP(price)})`, { color: c, align: "left", base: "bottom", font: 11 });
      prevY = y;
    });
  }

  // ---------------------------------------------------------------- per-tool renderers
  // P = screen points, d = drawing, s = style
  const R = {
    trend(P, d, s) { line2(P, s); },
    ray(P, d, s) { seg(P[0], extendPt(P[0], P[1]), s); },
    extended(P, d, s) { seg(extendPt(P[1], P[0]), extendPt(P[0], P[1]), s); },
    info(P, d, s) {
      line2(P, s);
      const [a, b] = d.pts, dp = b.p - a.p, bi = (barIdx(b.t) ?? 0) - (barIdx(a.t) ?? 0);
      const ang = Math.atan2(P[0].y - P[1].y, P[1].x - P[0].x) * 180 / Math.PI;
      label(P[1].x + 8, P[1].y, `${dp >= 0 ? "+" : ""}${fmtP(dp)} (${fmtN(dp / a.p * 100)}%)\n${bi} bars, ${fmtSpan(Math.abs(b.t - a.t))}\n${ang.toFixed(1)}°${d.text ? "\n" + d.text : ""}`,
        { bg: hexA(s.color, 0.85), align: "left", font: 11 });
    },
    angle(P, d, s) {
      line2(P, s);
      const ang = Math.atan2(P[0].y - P[1].y, P[1].x - P[0].x);
      seg(P[0], { x: P[0].x + 60, y: P[0].y }, { ...s, dash: "dotted", width: 1 });
      const p = new Path2D(); p.arc(P[0].x, P[0].y, 30, 0, -ang, ang > 0); stroke(p, { ...s, width: 1 });
      label(P[0].x + 40, P[0].y - 10 * Math.sign(ang || 1), `${(ang * 180 / Math.PI).toFixed(1)}°`, { color: s.color, align: "left" });
    },
    hline(P, d, s) { hlineAt(P[0].y, s); priceTag(P[0].y, d.pts[0].p, s.color); if (d.text) label(8, P[0].y - 4, d.text, { color: s.color, align: "left", base: "bottom" }); },
    hray(P, d, s) { hlineAt(P[0].y, s, P[0].x); priceTag(P[0].y, d.pts[0].p, s.color); },
    vline(P, d, s) { seg({ x: P[0].x, y: 0 }, { x: P[0].x, y: H() }, s); },
    cross_line(P, d, s) { hlineAt(P[0].y, s); seg({ x: P[0].x, y: 0 }, { x: P[0].x, y: H() }, s); priceTag(P[0].y, d.pts[0].p, s.color); },
    channel(P, d, s) {
      if (P.length < 3) return line2(P, s);
      const off = sub(P[2], P[0]);
      const a2 = add(P[0], { x: 0, y: off.y }), b2 = add(P[1], { x: 0, y: off.y });
      const ex = (a, b) => [s.extL ? extendPt(b, a) : a, s.extR ? extendPt(a, b) : b];
      const [A, Bp] = ex(P[0], P[1]), [C, D] = ex(a2, b2);
      fillP(polyPath([A, Bp, D, C], true), s.fill, s.fillA);
      seg(A, Bp, s); seg(C, D, s);
      const [m1, m2] = ex(mid(P[0], a2), mid(P[1], b2)); seg(m1, m2, { ...s, dash: "dashed", width: 1 });
    },
    flattop(P, d, s) {
      if (P.length < 3) return line2(P, s);
      const y = P[2].y;
      fillP(polyPath([P[0], P[1], { x: P[1].x, y }, { x: P[0].x, y }], true), s.fill, s.fillA);
      seg(P[0], P[1], s); seg({ x: P[0].x, y }, { x: P[1].x, y }, s);
    },
    disjoint(P, d, s) {
      if (P.length < 3) return line2(P, s);
      const dy = P[2].y - P[1].y, c = { x: P[0].x, y: P[0].y + dy + (P[1].y - P[0].y) * 2 }, e = { x: P[1].x, y: P[2].y };
      // mirror line: from (x0, y2 + (y1-y0)) to (x1, y2)
      const c0 = { x: P[0].x, y: P[2].y + (P[1].y - P[0].y) };
      fillP(polyPath([P[0], P[1], e, c0], true), s.fill, s.fillA);
      seg(P[0], P[1], s); seg(c0, e, s); void c;
    },
    pitchfork(P, d, s, variant = "std") {
      if (P.length < 3) return line2(P, s);
      let o = P[0];
      if (variant === "schiff") o = { x: P[0].x, y: (P[0].y + P[1].y) / 2 };
      if (variant === "mschiff") o = mid(P[0], P[1]);
      const m = mid(P[1], P[2]);
      seg(P[1], P[2], { ...s, width: 1 });
      if (variant === "inside") {
        const m0 = mid(P[0], P[1]);
        seg(m0, extendPt(m0, add(m0, sub(m, P[0]))), s);
        seg(P[0], extendPt(P[0], m), { ...s, dash: "dashed", width: 1 });
      } else seg(o, extendPt(o, m), s);
      const dir = sub(m, o);
      for (const q of [P[1], P[2]]) seg(q, extendPt(q, add(q, dir)), s);
      fillP(polyPath([P[1], extendPt(P[1], add(P[1], dir), 3000), extendPt(P[2], add(P[2], dir), 3000), P[2]], true), s.fill, s.fillA * 0.6);
      if (variant === "std") seg(P[0], P[1], { ...s, dash: "dashed", width: 1 });
    },
    schiff(P, d, s) { R.pitchfork(P, d, s, "schiff"); },
    mschiff(P, d, s) { R.pitchfork(P, d, s, "mschiff"); },
    inside_pf(P, d, s) { R.pitchfork(P, d, s, "inside"); },
    regression(P, d, s) {
      const b = B(), i0 = Math.max(0, Math.min(barIdx(d.pts[0].t), barIdx(d.pts[1].t))), i1 = Math.min(b.length - 1, Math.max(barIdx(d.pts[0].t), barIdx(d.pts[1].t)));
      if (i1 - i0 < 1) return line2(P, s);
      let n = 0, sx = 0, sy = 0, sxy = 0, sxx = 0;
      for (let i = i0; i <= i1; i++) { const y = b[i][4]; n++; sx += i; sy += y; sxy += i * y; sxx += i * i; }
      const k = (n * sxy - sx * sy) / (n * sxx - sx * sx || 1), c = (sy - k * sx) / n;
      let sd = 0; for (let i = i0; i <= i1; i++) sd += (b[i][4] - (k * i + c)) ** 2;
      sd = Math.sqrt(sd / n);
      const X = (i) => chart.timeScale().logicalToCoordinate(i);
      const pt = (i, off) => ({ x: X(i), y: yOfP(k * i + c + off) });
      fillP(polyPath([pt(i0, 2 * sd), pt(i1, 2 * sd), pt(i1, -2 * sd), pt(i0, -2 * sd)], true), s.fill, s.fillA * 0.6);
      seg(pt(i0, 0), pt(i1, 0), s); seg(pt(i0, 2 * sd), pt(i1, 2 * sd), { ...s, width: 1 }); seg(pt(i0, -2 * sd), pt(i1, -2 * sd), { ...s, width: 1 });
    },
    fib(P, d, s) { if (P.length < 2) return line2(P, s); levelLines(P[0], P[1], d.pts[0].p, d.pts[1].p, s, FIB, FIB_COL); seg(P[0], P[1], { ...s, dash: "dashed", color: "#787b86", width: 1 }); },
    fibext(P, d, s) {
      if (P.length < 3) return line2(P, s);
      const dy = P[1].y - P[0].y, dp = d.pts[1].p - d.pts[0].p;
      const x0 = Math.min(P[2].x, P[1].x), x1 = s.extR ? W() : Math.max(P[2].x, P[1].x) + 80;
      poly(P, { ...s, dash: "dashed", color: "#787b86", width: 1 });
      [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.272, 1.618, 2, 2.618].forEach((k, i) => {
        const y = P[2].y + dy * k, c = FIB_COL[i % FIB_COL.length];
        seg({ x: x0, y }, { x: x1, y }, { ...s, color: c });
        if (s.labels) label(x0 + 2, y - 2, `${k} (${fmtP(d.pts[2].p + dp * k)})`, { color: c, align: "left", base: "bottom", font: 11 });
      });
    },
    fibchannel(P, d, s) {
      if (P.length < 3) return line2(P, s);
      const off = P[2].y - P[0].y;
      FIB.slice(0, 8).forEach((k, i) => {
        const a = { x: P[0].x, y: P[0].y + off * k }, b = { x: P[1].x, y: P[1].y + off * k };
        seg(s.extL ? extendPt(b, a) : a, s.extR ? extendPt(a, b) : b, { ...s, color: FIB_COL[i] });
        if (s.labels) label(a.x - 4, a.y, String(k), { color: FIB_COL[i], align: "right", font: 11 });
      });
    },
    fibtime(P, d, s) {
      if (P.length < 2) return line2(P, s);
      const dx = P[1].x - P[0].x;
      FIB_TIME.forEach((k, i) => { const x = P[0].x + dx * k; seg({ x, y: 0 }, { x, y: H() }, { ...s, color: FIB_COL[i % FIB_COL.length] }); if (s.labels) label(x + 3, 12, String(k), { color: FIB_COL[i % FIB_COL.length], align: "left", font: 11 }); });
      seg(P[0], P[1], { ...s, dash: "dashed", width: 1, color: "#787b86" });
    },
    fibfan(P, d, s) {
      if (P.length < 2) return line2(P, s);
      const dx = P[1].x - P[0].x, dy = P[1].y - P[0].y;
      [0, 0.25, 0.382, 0.5, 0.618, 0.75, 1].forEach((k, i) => {
        const c = FIB_COL[i];
        seg(P[0], extendPt(P[0], { x: P[1].x, y: P[0].y + dy * k }), { ...s, color: c });
        seg(P[0], extendPt(P[0], { x: P[0].x + dx * k, y: P[1].y }), { ...s, color: c, dash: "dotted" });
      });
      const r = new Path2D(); r.rect(P[0].x, P[0].y, dx, dy); stroke(r, { ...s, color: "#787b86", width: 1 });
    },
    fibcircle(P, d, s) {
      if (P.length < 2) return line2(P, s);
      const c = mid(P[0], P[1]), r0 = dist(P[0], P[1]) / 2;
      [0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.618, 2.618].forEach((k, i) => { const p = new Path2D(); p.arc(c.x, c.y, r0 * k, 0, 2 * Math.PI); stroke(p, { ...s, color: FIB_COL[i + 1] }); });
      seg(P[0], P[1], { ...s, dash: "dashed", width: 1, color: "#787b86" });
    },
    fibarc(P, d, s) {
      if (P.length < 2) return line2(P, s);
      const r0 = dist(P[0], P[1]), up = P[1].y < P[0].y;
      [0.236, 0.382, 0.5, 0.618, 0.786, 1].forEach((k, i) => { const p = new Path2D(); p.arc(P[1].x, P[1].y, r0 * k, up ? 0 : Math.PI, up ? Math.PI : 2 * Math.PI); stroke(p, { ...s, color: FIB_COL[i + 1] }); });
      seg(P[0], P[1], { ...s, dash: "dashed", width: 1, color: "#787b86" });
    },
    fibwedge(P, d, s) {
      if (P.length < 3) return line2(P, s);
      const r = dist(P[0], P[1]), a1 = Math.atan2(P[1].y - P[0].y, P[1].x - P[0].x), a2 = Math.atan2(P[2].y - P[0].y, P[2].x - P[0].x);
      seg(P[0], P[1], s); seg(P[0], { x: P[0].x + r * Math.cos(a2), y: P[0].y + r * Math.sin(a2) }, s);
      [0.236, 0.382, 0.5, 0.618, 0.786, 1].forEach((k, i) => { const p = new Path2D(); p.arc(P[0].x, P[0].y, r * k, a1, a2, a2 < a1); stroke(p, { ...s, color: FIB_COL[i + 1] }); });
    },
    pitchfan(P, d, s) {
      if (P.length < 3) return line2(P, s);
      seg(P[1], P[2], { ...s, width: 1 });
      [0, 0.25, 0.382, 0.5, 0.618, 0.75, 1].forEach((k, i) => seg(P[0], extendPt(P[0], lerp(P[1], P[2], k)), { ...s, color: FIB_COL[i] }));
    },
    gannbox(P, d, s) {
      if (P.length < 2) return line2(P, s);
      const ks = [0, 0.25, 0.382, 0.5, 0.618, 0.75, 1], dx = P[1].x - P[0].x, dy = P[1].y - P[0].y;
      fillP(polyPath([P[0], { x: P[1].x, y: P[0].y }, P[1], { x: P[0].x, y: P[1].y }], true), s.fill, s.fillA * 0.5);
      ks.forEach((k, i) => {
        seg({ x: P[0].x + dx * k, y: P[0].y }, { x: P[0].x + dx * k, y: P[1].y }, { ...s, color: FIB_COL[i] });
        seg({ x: P[0].x, y: P[0].y + dy * k }, { x: P[1].x, y: P[0].y + dy * k }, { ...s, color: FIB_COL[i] });
        if (s.labels) { label(P[0].x + dx * k, P[0].y - 8 * Math.sign(dy || 1), String(k), { color: FIB_COL[i], font: 10 }); }
      });
      seg(P[0], P[1], { ...s, dash: "dashed", width: 1 }); seg({ x: P[0].x, y: P[1].y }, { x: P[1].x, y: P[0].y }, { ...s, dash: "dashed", width: 1 });
    },
    gannsq(P, d, s) {
      if (P.length < 2) return line2(P, s);
      const side = Math.max(Math.abs(P[1].x - P[0].x), Math.abs(P[1].y - P[0].y));
      const q = { x: P[0].x + side * Math.sign(P[1].x - P[0].x || 1), y: P[0].y + side * Math.sign(P[1].y - P[0].y || 1) };
      R.gannbox([P[0], q], d, s);
      for (const [a, b] of GANN) seg(P[0], { x: P[0].x + (q.x - P[0].x) * Math.min(1, a / b), y: P[0].y + (q.y - P[0].y) * Math.min(1, b / a) }, { ...s, width: 1, color: "#787b86" });
    },
    gannfan(P, d, s) {
      if (P.length < 2) return line2(P, s);
      const dx = P[1].x - P[0].x, dy = P[1].y - P[0].y;
      GANN.forEach(([a, b], i) => {
        const e = { x: P[0].x + dx * (a / b > 1 ? 1 : a / b) * (b > a ? 1 : 1), y: P[0].y + dy * (b / a > 1 ? 1 : b / a) };
        const q = a >= b ? { x: P[0].x + dx / a * b, y: P[1].y } : { x: P[1].x, y: P[0].y + dy * a / b };
        void e;
        seg(P[0], extendPt(P[0], q), { ...s, color: FIB_COL[(i + 1) % FIB_COL.length] });
        if (s.labels) label(q.x, q.y, `${a}/${b}`, { color: FIB_COL[(i + 1) % FIB_COL.length], font: 10 });
      });
    },
    pattern(P, d, s) {
      const L = LABELS[d.type], lab = (i) => (Array.isArray(L) ? L[i] : L[i]) || "";
      const pts = d.pts;
      if (["xabcd", "cypher"].includes(d.type)) {
        if (P.length >= 3) fillP(polyPath(P.slice(0, 3), true), s.fill, s.fillA);
        if (P.length >= 5) fillP(polyPath(P.slice(2, 5), true), s.fill, s.fillA);
        const ratio = (i, j, k) => Math.abs((pts[k].p - pts[j].p) / ((pts[j].p - pts[i].p) || 1)).toFixed(3);
        const dl = { ...s, dash: "dashed", width: 1 };
        if (P.length >= 3) { seg(P[0], P[2], dl); label(mid(P[0], P[2]).x, mid(P[0], P[2]).y, ratio(0, 1, 2), { bg: hexA(s.color, 0.8), font: 10 }); }
        if (P.length >= 4) { seg(P[1], P[3], dl); label(mid(P[1], P[3]).x, mid(P[1], P[3]).y, ratio(1, 2, 3), { bg: hexA(s.color, 0.8), font: 10 }); }
        if (P.length >= 5) {
          seg(P[2], P[4], dl); label(mid(P[2], P[4]).x, mid(P[2], P[4]).y, ratio(2, 3, 4), { bg: hexA(s.color, 0.8), font: 10 });
          seg(P[0], P[4], dl); label(mid(P[0], P[4]).x, mid(P[0], P[4]).y, Math.abs((pts[4].p - pts[3].p) / ((pts[1].p - pts[0].p) || 1)).toFixed(3), { bg: hexA(s.color, 0.8), font: 10 });
        }
      }
      if (d.type === "abcd" && P.length === 4) {
        const dl = { ...s, dash: "dashed", width: 1 };
        seg(P[0], P[2], dl); seg(P[1], P[3], dl);
        label(mid(P[0], P[2]).x, mid(P[0], P[2]).y, Math.abs((pts[2].p - pts[1].p) / ((pts[1].p - pts[0].p) || 1)).toFixed(3), { bg: hexA(s.color, 0.8), font: 10 });
        label(mid(P[1], P[3]).x, mid(P[1], P[3]).y, Math.abs((pts[3].p - pts[2].p) / ((pts[2].p - pts[1].p) || 1)).toFixed(3), { bg: hexA(s.color, 0.8), font: 10 });
      }
      if (d.type === "hs" && P.length >= 5) { seg(extendPt(P[4], P[2]), extendPt(P[2], P[4]), { ...s, dash: "dashed" }); if (P.length === 7) fillP(polyPath(P.slice(2, 5), true), s.fill, s.fillA); }
      if (d.type === "tripattern" && P.length === 4) { seg(P[0], extendPt(P[0], P[2]), { ...s, dash: "dashed" }); seg(P[1], extendPt(P[1], P[3]), { ...s, dash: "dashed" }); fillP(polyPath(P, true), s.fill, s.fillA); }
      poly(P, s);
      P.forEach((q, i) => {
        const up = i > 0 ? q.y < P[i - 1].y : P[1] ? q.y < P[1].y : true;
        const t = lab(i);
        if (t) label(q.x, q.y + (up ? -14 : 14), t, { bg: hexA(s.color, 0.9), font: 11, bold: true });
      });
    },
    fibtimetrend(P, d, s) {
      if (P.length < 3) return line2(P, s);
      poly(P, { ...s, dash: "dashed", width: 1, color: "#787b86" });
      const dx = P[1].x - P[0].x;
      [0, 0.382, 0.5, 0.618, 1, 1.382, 1.618, 2, 2.618, 4.236].forEach((k, i) => {
        const x = P[2].x + dx * k, c = FIB_COL[i % FIB_COL.length];
        seg({ x, y: 0 }, { x, y: H() }, { ...s, color: c });
        if (s.labels) label(x + 3, 12, String(k), { color: c, align: "left", font: 11 });
      });
    },
    fibspiral(P, d, s) {
      if (P.length < 2) return line2(P, s);
      const r0 = dist(P[0], P[1]) || 1, a0 = Math.atan2(P[1].y - P[0].y, P[1].x - P[0].x), phi = 1.618034;
      const p = new Path2D();
      for (let th = -4 * Math.PI, first = true; th <= 2.5 * Math.PI; th += 0.05) {
        const r = r0 * Math.pow(phi, th / (Math.PI / 2));
        const x = P[0].x + r * Math.cos(a0 - th), y = P[0].y + r * Math.sin(a0 - th);
        if (first) { p.moveTo(x, y); first = false; } else p.lineTo(x, y);
      }
      stroke(p, s);
      seg(P[0], P[1], { ...s, dash: "dashed", width: 1, color: "#787b86" });
    },
    gannsquare(P, d, s) {
      if (P.length < 2) return line2(P, s);
      R.gannbox(P, d, s);
      for (const [a, b] of GANN) seg(P[0], { x: P[0].x + (P[1].x - P[0].x) * Math.min(1, a / b), y: P[0].y + (P[1].y - P[0].y) * Math.min(1, b / a) }, { ...s, width: 1, color: "#787b86" });
    },
    candles(list, s, alpha = 0.55) {
      // list: [{L, o, h, l, c}] drawn as translucent candles
      const ts = chart.timeScale(), bw = Math.max(1, ((ts.logicalToCoordinate(1) ?? 0) - (ts.logicalToCoordinate(0) ?? 0)) * 0.6);
      for (const k of list) {
        const x = ts.logicalToCoordinate(k.L); if (x == null) continue;
        const col = k.c >= k.o ? "#089981" : "#f23645";
        seg({ x, y: yOfP(k.h) }, { x, y: yOfP(k.l) }, { color: hexA(col, alpha), width: 1, dash: "solid" });
        const y0 = yOfP(Math.max(k.o, k.c)), y1 = yOfP(Math.min(k.o, k.c));
        const r = new Path2D(); r.rect(x - bw / 2, y0, bw, Math.max(1, y1 - y0)); fillP(r, col, alpha);
      }
    },
    barspattern(P, d, s) {
      if (P.length < 2) return;
      const b = B(), ia = barIdx(d.pts[0].t), ib = barIdx(d.pts[1].t), i0 = Math.max(0, Math.min(ia, ib)), i1 = Math.min(b.length - 1, Math.max(ia, ib));
      const r = new Path2D(); r.rect(Math.min(P[0].x, P[1].x), 0, Math.abs(P[1].x - P[0].x), H()); fillP(r, s.fill, 0.06);
      if (P.length < 3 || i1 < i0) return;
      const L2 = logicalOfT(d.pts[2].t), off = d.pts[2].p - b[i0][1], list = [];
      for (let i = i0; i <= i1; i++) list.push({ L: Math.round(L2) + i - i0, o: b[i][1] + off, h: b[i][2] + off, l: b[i][3] + off, c: b[i][4] + off });
      R.candles(list, s);
    },
    ghost(P, d, s) {
      if (st.sel === d || st.draft === d) poly(P, { ...s, dash: "dashed", width: 1 });
      const Ls = d.pts.map((q) => logicalOfT(q.t)), list = [];
      let prev = d.pts[0].p;
      for (let k = 1; k < d.pts.length; k++) {
        const a = Math.round(Ls[k - 1]), z = Math.round(Ls[k]);
        for (let L = a + 1; L <= z; L++) {
          const c = d.pts[k - 1].p + (d.pts[k].p - d.pts[k - 1].p) * (L - a) / ((z - a) || 1), w = Math.abs(c - prev) * 0.4 + Math.abs(c) * 0.0004;
          list.push({ L, o: prev, c, h: Math.max(prev, c) + w, l: Math.min(prev, c) - w }); prev = c;
        }
      }
      R.candles(list, s, 0.5);
      if (!list.length) poly(P, s);
    },
    sector(P, d, s) {
      if (P.length < 3) return line2(P, s);
      const r = dist(P[0], P[1]), a1 = Math.atan2(P[1].y - P[0].y, P[1].x - P[0].x), a2 = Math.atan2(P[2].y - P[0].y, P[2].x - P[0].x);
      const p = new Path2D(); p.moveTo(P[0].x, P[0].y); p.arc(P[0].x, P[0].y, r, a1, a2, a2 < a1); p.closePath();
      fillP(p, s.fill, s.fillA); stroke(p, s);
    },
    avprofile(P, d, s) {
      const b = B(); if (!b.length) return;
      const end = { t: b[b.length - 1][0], p: d.pts[0].p };
      R.vprofile([P[0], toXY(end)], { ...d, pts: [d.pts[0], end] }, s);
      const c = new Path2D(); c.arc(P[0].x, P[0].y, 4, 0, 7); fillP(c, s.color, 1);
    },
    pin(P, d, s) {
      const { x, y } = P[0];
      const head = new Path2D(); head.arc(x, y - 18, 7, 0, 7); fillP(head, s.color, 1);
      seg({ x, y: y - 11 }, { x, y }, { ...s, width: 2 });
      if (st.sel === d || st.hover === d) label(x + 10, y - 26, d.text || "Pin", { bg: hexA(s.fill, 0.92), color: "#fff", align: "left", base: "bottom", font: s.font });
    },
    cyclic(P, d, s) {
      if (P.length < 2) return line2(P, s);
      const dx = Math.abs(P[1].x - P[0].x) || 10;
      for (let x = P[0].x, i = 0; x < W() && i < 400; x += dx, i++) seg({ x, y: 0 }, { x, y: H() }, { ...s, width: 1 });
    },
    timecycles(P, d, s) {
      if (P.length < 2) return line2(P, s);
      const dx = Math.abs(P[1].x - P[0].x) || 10, y = P[0].y;
      for (let x = P[0].x, i = 0; x < W() && i < 200; x += dx, i++) { const p = new Path2D(); p.ellipse(x + dx / 2, y, dx / 2, dx / 2, 0, Math.PI, 2 * Math.PI); stroke(p, s); }
    },
    sine(P, d, s) {
      if (P.length < 2) return line2(P, s);
      const half = Math.abs(P[1].x - P[0].x) || 10, amp = (P[1].y - P[0].y) / 2, cy = (P[0].y + P[1].y) / 2;
      const p = new Path2D();
      for (let x = Math.min(P[0].x, 0) - half * 2, first = true; x < W(); x += 2) {
        const y = cy - amp * Math.cos(Math.PI * (x - P[0].x) / half);
        if (first) { p.moveTo(x, y); first = false; } else p.lineTo(x, y);
      }
      stroke(p, s);
    },
    position(P, d, s, long) {
      if (P.length < 2) return;
      const [e] = d.pts, tgt = d.pts[1].p, stp = d.pts[2] ? d.pts[2].p : e.p - (tgt - e.p);
      const x0 = P[0].x, x1 = Math.max(P[1].x, x0 + 20), ye = P[0].y, yt = yOfP(tgt), ys = yOfP(stp);
      const g = "#089981", r = "#f23645";
      fillP(polyPath([{ x: x0, y: ye }, { x: x1, y: ye }, { x: x1, y: yt }, { x: x0, y: yt }], true), g, 0.2);
      fillP(polyPath([{ x: x0, y: ye }, { x: x1, y: ye }, { x: x1, y: ys }, { x: x0, y: ys }], true), r, 0.2);
      seg({ x: x0, y: ye }, { x: x1, y: ye }, { color: "#787b86", width: 1, dash: "solid" });
      const pct = (p) => `${fmtP(Math.abs(p - e.p))} (${fmtN(Math.abs(p - e.p) / e.p * 100)}%)`;
      const rr = Math.abs(tgt - e.p) / (Math.abs(stp - e.p) || 1);
      const xm = (x0 + x1) / 2;
      label(xm, yt + (yt < ye ? -10 : 10), `Target: ${fmtP(tgt)} · ${pct(tgt)}`, { bg: g, font: 11 });
      label(xm, ys + (ys < ye ? -10 : 10), `Stop: ${fmtP(stp)} · ${pct(stp)}`, { bg: r, font: 11 });
      label(xm, ye, `${long ? "Long" : "Short"} ${fmtP(e.p)} · R:R ${rr.toFixed(2)}`, { bg: hexA("#363a45", 0.9), font: 11 });
    },
    long(P, d, s) { R.position(P, d, s, true); },
    short(P, d, s) { R.position(P, d, s, false); },
    forecast(P, d, s) {
      seg(P[0], P[1] || P[0], { ...s, dash: "dashed" });
      if (P.length < 2) return;
      const dp = d.pts[1].p - d.pts[0].p;
      for (const q of P) { const c = new Path2D(); c.arc(q.x, q.y, 4, 0, 7); fillP(c, s.color, 1); }
      label(P[1].x, P[1].y + (dp >= 0 ? -16 : 16), `${dp >= 0 ? "+" : ""}${fmtP(dp)} (${fmtN(dp / d.pts[0].p * 100)}%)\n${fmtSpan(Math.abs(d.pts[1].t - d.pts[0].t))}`, { bg: hexA(dp >= 0 ? "#089981" : "#f23645", 0.9), font: 11 });
    },
    projection(P, d, s) {
      if (P.length < 3) return line2(P, s);
      poly(P, s);
      const r = dist(P[0], P[1]), a1 = Math.atan2(P[1].y - P[0].y, P[1].x - P[0].x), a2 = Math.atan2(P[2].y - P[0].y, P[2].x - P[0].x);
      const p = new Path2D(); p.moveTo(P[0].x, P[0].y); p.arc(P[0].x, P[0].y, r, a1, a2, a2 < a1); p.closePath();
      fillP(p, s.fill, s.fillA); stroke(p, { ...s, width: 1 });
      const k = Math.abs((d.pts[2].p - d.pts[1].p) / ((d.pts[1].p - d.pts[0].p) || 1));
      label(P[2].x, P[2].y - 14, k.toFixed(3), { bg: hexA(s.color, 0.85), font: 11 });
    },
    avwap(P, d, s) {
      const b = B(), i0 = Math.max(0, barIdx(d.pts[0].t));
      const pts = []; let pv = 0, vv = 0;
      const anyVol = b.slice(i0).some((x) => x[5] > 0);
      for (let i = i0; i < b.length; i++) {
        const tp = (b[i][2] + b[i][3] + b[i][4]) / 3, v = anyVol ? (b[i][5] || 0) : 1;
        pv += tp * v; vv += v;
        if (vv > 0) pts.push({ x: chart.timeScale().logicalToCoordinate(i), y: yOfP(pv / vv) });
      }
      if (pts.length) { poly(pts, s); priceTag(pts[pts.length - 1].y, pv / vv, s.color); }
      const c = new Path2D(); c.arc(P[0].x, P[0].y, 4, 0, 7); fillP(c, s.color, 1);
    },
    vprofile(P, d, s) {
      if (P.length < 2) return line2(P, s);
      const xa = Math.min(P[0].x, P[1].x), xb = Math.max(P[0].x, P[1].x);
      const p = st.draft === d ? null : vpData(d);
      const half = (chart.timeScale().options().barSpacing || 6) / 2;
      if (!p || !window.LTVVP) {                               // waiting for the server (1m intrabars)
        const r = new Path2D(); r.rect(xa, Math.min(P[0].y, P[1].y), xb - xa, Math.abs(P[1].y - P[0].y) || 1);
        stroke(r, { ...s, width: 1, dash: "dashed" });
        if (st.draft !== d) label(xa + 4, Math.min(P[0].y, P[1].y) + 10, "Volume profile…", { color: "#9598a1", align: "left", font: 10 });
        return;
      }
      const vs = { ...(d.style.vp || {}) };
      const g = LTVVP.draw(ctx, { ...p, style: vs }, { x1: xa - half, x2: xb + half, W: cv.width / dpr(), yOfP });
      const y1 = yOfP(p.base + p.step * p.n), y2 = yOfP(p.base);
      if (y1 == null || y2 == null) return;
      // range box (hit area + selection) and anchor guides
      const r = new Path2D(); r.rect(xa - half, Math.min(y1, y2), xb - xa + 2 * half, Math.abs(y2 - y1));
      fillP(r, s.fill, st.sel === d || st.hover === d ? 0.06 : 0.02);
      if (st.sel === d || st.hover === d) stroke(r, { ...s, width: 1, dash: "dashed" });
      if (g && (st.sel === d || st.hover === d) && s.labels !== false) {
        const fp = (x) => fmtP(x);
        label(xb + half + 4, yOfP(p.pocPrice), `POC ${fp(p.pocPrice)}`, { bg: hexA(vs.poc || "#ff9800", 0.9), align: "left", font: 10 });
        label(xb + half + 4, yOfP(p.vah), `VAH ${fp(p.vah)}`, { bg: hexA(vs.vah || "#2962ff", 0.9), align: "left", font: 10 });
        label(xb + half + 4, yOfP(p.val), `VAL ${fp(p.val)}`, { bg: hexA(vs.val || "#2962ff", 0.9), align: "left", font: 10 });
      }
      if (st.sel === d) {
        const tag = p.status === "PROVISIONAL" ? "developing" : "fixed";
        label(xa - half + 2, Math.max(y1, y2) + 10, `${tag} · ${p.res === "chart" ? "chart bars" : p.res}${p.volumeMode === "bar-count" ? " · no volume" : p.dataQuality === "proxy" ? " · proxy volume" : ""}`,
          { color: "#9598a1", align: "left", font: 10 });
      }
    },
    range(P, d, s, mode) {
      if (P.length < 2) return line2(P, s);
      const [a, b] = d.pts, dp = b.p - a.p, bi = (barIdx(b.t) ?? 0) - (barIdx(a.t) ?? 0);
      const col = mode === "d" ? s.color : dp >= 0 ? "#2962ff" : "#f23645";
      const x0 = mode === "p" ? Math.min(P[0].x, P[1].x) : P[0].x, x1 = mode === "p" ? Math.max(P[0].x, P[1].x) : P[1].x;
      const y0 = mode === "d" ? Math.min(P[0].y, P[1].y) : P[0].y, y1 = mode === "d" ? Math.max(P[0].y, P[1].y) : P[1].y;
      fillP(polyPath([{ x: x0, y: y0 }, { x: x1, y: y0 }, { x: x1, y: y1 }, { x: x0, y: y1 }], true), col, 0.2);
      if (mode !== "d") { const xm = (x0 + x1) / 2; seg({ x: xm, y: y0 }, { x: xm, y: y1 }, { color: col, width: 1, dash: "solid" }); arrowHead({ x: xm, y: y0 }, { x: xm, y: y1 }, { color: col }, 8); }
      if (mode !== "p") { const ym = (y0 + y1) / 2; seg({ x: x0, y: ym }, { x: x1, y: ym }, { color: col, width: 1, dash: "solid" }); arrowHead({ x: x0, y: ym }, { x: x1, y: ym }, { color: col }, 8); }
      const parts = [];
      if (mode !== "d") parts.push(`${dp >= 0 ? "+" : ""}${fmtP(dp)} (${fmtN(dp / a.p * 100)}%)`);
      if (mode !== "p") parts.push(`${bi} bars, ${fmtSpan(Math.abs(b.t - a.t))}`);
      if (mode === "dp") {
        const b0 = B(), i0 = Math.max(0, Math.min(barIdx(a.t), barIdx(b.t))), i1 = Math.min(b0.length - 1, Math.max(barIdx(a.t), barIdx(b.t)));
        let v = 0; for (let i = i0; i <= i1; i++) v += b0[i]?.[5] || 0;
        if (v) parts.push(`Vol ${fmtN(v)}`);
      }
      const below = y1 >= y0;
      label((x0 + x1) / 2, (below ? Math.max(y0, y1) + 8 : Math.min(y0, y1) - 8), parts.join("\n"), { bg: col, base: below ? "top" : "bottom", font: 11 });
    },
    prange(P, d, s) { R.range(P, d, s, "p"); },
    drange(P, d, s) { R.range(P, d, s, "d"); },
    dprange(P, d, s) { R.range(P, d, s, "dp"); },
    freehand(P, d, s) {
      if (d.type === "highlighter") { ctx.globalAlpha = 0.4; poly(P, s); ctx.globalAlpha = 1; } else poly(P, s);
    },
    arrowline(P, d, s) { line2(P, s); if (P[1]) arrowHead(P[0], P[1], s, 8 + s.width * 2); },
    arrowmarker(P, d, s) {
      if (P.length < 2) return;
      const [a, b] = P, L = dist(a, b), ang = Math.atan2(b.y - a.y, b.x - a.x), w = Math.max(6, L * 0.12), hl = Math.min(L * 0.4, w * 2.5);
      const rot = (x, y) => ({ x: a.x + x * Math.cos(ang) - y * Math.sin(ang), y: a.y + x * Math.sin(ang) + y * Math.cos(ang) });
      const shape = [rot(0, -w / 2), rot(L - hl, -w / 2), rot(L - hl, -w * 1.4), rot(L, 0), rot(L - hl, w * 1.4), rot(L - hl, w / 2), rot(0, w / 2)];
      const p = polyPath(shape, true); fillP(p, s.color, 0.85);
      if (d.text) label(a.x, a.y + 14, d.text, { color: s.color, font: s.font });
    },
    rect(P, d, s) {
      if (P.length < 2) return;
      const x0 = s.extL ? 0 : Math.min(P[0].x, P[1].x), x1 = s.extR ? W() : Math.max(P[0].x, P[1].x);
      poly([{ x: x0, y: P[0].y }, { x: x1, y: P[0].y }, { x: x1, y: P[1].y }, { x: x0, y: P[1].y }], s, true, true);
      if (d.text) label((x0 + x1) / 2, (P[0].y + P[1].y) / 2, d.text, { color: s.color, font: s.font });
    },
    rotrect(P, d, s) {
      if (P.length < 3) return line2(P, s);
      const v = sub(P[1], P[0]), L = Math.hypot(v.x, v.y) || 1, n = { x: -v.y / L, y: v.x / L };
      const h = (P[2].x - P[0].x) * n.x + (P[2].y - P[0].y) * n.y, o = { x: n.x * h, y: n.y * h };
      poly([P[0], P[1], add(P[1], o), add(P[0], o)], s, true, true);
    },
    circle(P, d, s) { if (P.length < 2) return; const p = new Path2D(); p.arc(P[0].x, P[0].y, dist(P[0], P[1]), 0, 2 * Math.PI); fillP(p, s.fill, s.fillA); stroke(p, s); },
    ellipse(P, d, s) {
      if (P.length < 2) return;
      const p = new Path2D(); p.ellipse((P[0].x + P[1].x) / 2, (P[0].y + P[1].y) / 2, Math.abs(P[1].x - P[0].x) / 2, Math.abs(P[1].y - P[0].y) / 2, 0, 0, 2 * Math.PI);
      fillP(p, s.fill, s.fillA); stroke(p, s);
    },
    triangle(P, d, s) { poly(P, s, P.length === 3, P.length === 3); },
    path(P, d, s) { poly(P, s); if (P.length > 1) arrowHead(P[P.length - 2], P[P.length - 1], s, 8 + s.width * 2); },
    polyline(P, d, s) { poly(P, s, d.done, d.done); },
    arc(P, d, s) {
      if (P.length < 3) return line2(P, s);
      const c = { x: 2 * P[2].x - (P[0].x + P[1].x) / 2, y: 2 * P[2].y - (P[0].y + P[1].y) / 2 };
      const p = new Path2D(); p.moveTo(P[0].x, P[0].y); p.quadraticCurveTo(c.x, c.y, P[1].x, P[1].y);
      fillP(p, s.fill, s.fillA); stroke(p, s);
    },
    curve(P, d, s) {
      if (P.length < 3) return line2(P, s);
      const c = { x: 2 * P[2].x - (P[0].x + P[1].x) / 2, y: 2 * P[2].y - (P[0].y + P[1].y) / 2 };
      const p = new Path2D(); p.moveTo(P[0].x, P[0].y); p.quadraticCurveTo(c.x, c.y, P[1].x, P[1].y); stroke(p, s);
    },
    dcurve(P, d, s) {
      if (P.length < 3) return line2(P, s);
      const m = mid(P[0], P[1]), off = sub(P[2], lerp(P[0], m, 0.5));
      const c1 = add(lerp(P[0], m, 0.5), { x: off.x * 2, y: off.y * 2 }), c2 = sub(lerp(m, P[1], 0.5), { x: off.x * 2, y: off.y * 2 });
      const p = new Path2D(); p.moveTo(P[0].x, P[0].y); p.quadraticCurveTo(c1.x, c1.y, m.x, m.y); p.quadraticCurveTo(c2.x, c2.y, P[1].x, P[1].y); stroke(p, s);
    },
    text(P, d, s) { label(P[0].x, P[0].y, d.text || "Text", { color: s.color, font: s.font, align: "left", bg: s.fillA ? hexA(s.fill, s.fillA) : null, bold: s.bold }); },
    anchored(P, d, s) { R.text(P, d, s); },
    note(P, d, s) {
      const pin = new Path2D(); pin.arc(P[0].x, P[0].y, 6, 0, 7); fillP(pin, s.color, 1);
      if (st.sel === d || st.hover === d || d.style.open) label(P[0].x + 10, P[0].y - 10, d.text || "Note", { bg: hexA(s.fill, Math.max(0.9, s.fillA)), color: "#fff", align: "left", base: "bottom", font: s.font });
    },
    pricenote(P, d, s) {
      line2(P, s);
      if (P[1]) label(P[1].x + 6, P[1].y, `${fmtP(d.pts[0].p)}${d.text ? "  " + d.text : ""}`, { bg: s.color, align: "left", font: s.font - 2 });
      const c = new Path2D(); c.arc(P[0].x, P[0].y, 3, 0, 7); fillP(c, s.color, 1);
    },
    callout(P, d, s) {
      if (P.length < 2) return;
      const box = label(P[1].x, P[1].y, d.text || "Callout", { bg: hexA(s.fill, Math.max(0.85, s.fillA)), color: "#fff", font: s.font, pad: 8 });
      if (box) { const p = new Path2D(); p.moveTo(P[0].x, P[0].y); p.lineTo(box.x + box.w / 2 - 8, box.y + box.h / 2); p.lineTo(box.x + box.w / 2 + 8, box.y + box.h / 2); p.closePath(); fillP(p, s.fill, Math.max(0.85, s.fillA)); }
    },
    comment(P, d, s) {
      const box = label(P[0].x, P[0].y - 14, d.text || "Comment", { bg: hexA(s.fill, Math.max(0.9, s.fillA)), color: "#fff", font: s.font, pad: 8, base: "bottom", align: "left" });
      if (box) { const p = polyPath([{ x: P[0].x, y: P[0].y }, { x: P[0].x, y: box.y + box.h }, { x: P[0].x + 12, y: box.y + box.h }], true); fillP(p, s.fill, Math.max(0.9, s.fillA)); }
    },
    pricelabel(P, d, s) {
      const box = label(P[0].x + 10, P[0].y - 18, fmtP(d.pts[0].p), { bg: s.color, align: "left", base: "bottom", font: s.font - 1 });
      if (box) seg(P[0], { x: box.x + 6, y: box.y + box.h }, { ...s, width: 1 });
    },
    signpost(P, d, s) {
      const b = B()[barIdx(d.pts[0].t)], top = b ? yOfP(b[2]) : P[0].y, y = Math.min(top - 50, P[0].y);
      seg({ x: P[0].x, y: top - 4 }, { x: P[0].x, y }, { ...s, width: 1 });
      label(P[0].x, y, d.text || "Signpost", { bg: s.color, base: "bottom", font: s.font - 1, pad: 6 });
    },
    flag(P, d, s) {
      seg({ x: P[0].x, y: P[0].y }, { x: P[0].x, y: P[0].y - 24 }, { ...s, width: 2 });
      fillP(polyPath([{ x: P[0].x, y: P[0].y - 24 }, { x: P[0].x + 16, y: P[0].y - 19 }, { x: P[0].x, y: P[0].y - 14 }], true), s.color, 1);
      if (d.text) label(P[0].x + 18, P[0].y - 19, d.text, { color: s.color, align: "left", font: s.font - 2 });
    },
    arrowmark(P, d, s, dir) {
      const { x, y } = P[0], k = 14, sh = {
        up: [[0, 0], [k, k], [k / 2.5, k], [k / 2.5, 2 * k], [-k / 2.5, 2 * k], [-k / 2.5, k], [-k, k]],
        down: [[0, 0], [k, -k], [k / 2.5, -k], [k / 2.5, -2 * k], [-k / 2.5, -2 * k], [-k / 2.5, -k], [-k, -k]],
        left: [[0, 0], [k, -k], [k, -k / 2.5], [2 * k, -k / 2.5], [2 * k, k / 2.5], [k, k / 2.5], [k, k]],
        right: [[0, 0], [-k, -k], [-k, -k / 2.5], [-2 * k, -k / 2.5], [-2 * k, k / 2.5], [-k, k / 2.5], [-k, k]],
      }[dir];
      fillP(polyPath(sh.map(([a, b]) => ({ x: x + a, y: y + b })), true), s.color, 1);
      if (d.text) label(x, dir === "up" ? y + 2 * k + 10 : dir === "down" ? y - 2 * k - 10 : y + k + 8, d.text, { color: s.color, font: s.font - 2 });
    },
    arrowup(P, d, s) { R.arrowmark(P, d, s, "up"); },
    arrowdown(P, d, s) { R.arrowmark(P, d, s, "down"); },
    arrowleft(P, d, s) { R.arrowmark(P, d, s, "left"); },
    arrowright(P, d, s) { R.arrowmark(P, d, s, "right"); },
    emoji(P, d, s) {
      const size = s.font * 2;
      ctx.font = `${size}px "Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillStyle = "#000";
      ctx.fillText(TOOLS[d.type].emoji, P[0].x, P[0].y);
      const box = new Path2D(); box.rect(P[0].x - size / 2, P[0].y - size / 2, size, size); hits && hits.push({ path: box, stroke: false });
    },
  };
  function line2(P, s) {
    if (P.length < 2) return;
    const a = s.extL ? extendPt(P[1], P[0]) : P[0], b = s.extR ? extendPt(P[0], P[1]) : P[1];
    seg(a, b, s);
    if (s.arrow) arrowHead(P[0], P[1], s, 8 + s.width * 2);
  }
  const PATTERN = new Set(["xabcd", "cypher", "hs", "abcd", "tripattern", "threedrives", "ew_impulse", "ew_corr", "ew_tri", "ew_dbl", "ew_tpl"]);
  function rendererOf(type) {
    if (PATTERN.has(type)) return R.pattern;
    if (type === "brush" || type === "highlighter") return R.freehand;
    if (type.startsWith("emoji")) return R.emoji;
    return R[type] || R.trend;
  }

  // ---------------------------------------------------------------- render loop
  let lastSig = "";
  function viewSig() {
    const ts = chart.timeScale(), s = series(), r = ts.getVisibleLogicalRange();
    return [cv.width, cv.height, r && r.from, r && r.to, s && s.priceToCoordinate(1000), s && s.priceToCoordinate(2000), B().length, B()[B().length - 1]?.[4]].join("|");
  }
  let dirty = true;
  const markDirty = () => { dirty = true; };
  function resize() {
    const w = paneW(), h = paneH(), r = dpr(), off = leftOffset() + "px";
    if (cv.style.left !== off) { cv.style.left = off; dirty = true; }
    if (cv.width !== Math.round(w * r) || cv.height !== Math.round(h * r)) {
      cv.width = Math.round(w * r); cv.height = Math.round(h * r); cv.style.width = w + "px"; cv.style.height = h + "px";
      dirty = true;
    }
  }
  function frame() {
    resize();
    const sig = viewSig();
    if (dirty || sig !== lastSig) { lastSig = sig; dirty = false; render(); }
    requestAnimationFrame(frame);
  }
  function screenPts(d) { return d.pts.map(toXY); }
  function drawOne(d) {
    const P = screenPts(d);
    if (P.some((q) => q.x == null || q.y == null)) return;
    d._hits = []; hits = d._hits;
    ctx.save();
    try { rendererOf(d.type)(P, d, d.style); } catch (e) { console.warn("draw", d.type, e); }
    ctx.restore();
    hits = null;
    d._P = P;
  }
  const isPosT = (t) => t === "long" || t === "short" || t === "forecast";
  function render() {
    const r = dpr();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.setTransform(r, 0, 0, r, 0, 0);
    if (!B().length || !series()) return;
    for (const d of st.items) { d._hits = null; d._P = null; }
    for (const d of st.items) if (!d.hidden && !(isPosT(d.type) ? st.hidePos : st.hideAll)) drawOne(d);
    if (st.draft) drawOne(st.draft);
    if (st.measure) drawOne(st.measure);
    if (st.zoom) { const z = st.zoom; ctx.fillStyle = "rgba(41,98,255,.12)"; ctx.fillRect(Math.min(z.x0, z.x1), 0, Math.abs(z.x1 - z.x0), paneH()); }
    const sel = st.sel;
    if (sel && sel._P) for (const q of sel._P) {
      ctx.beginPath(); ctx.arc(q.x, q.y, 5, 0, 7);
      ctx.fillStyle = css("--bg") || "#131722"; ctx.fill(); ctx.lineWidth = 1.5; ctx.strokeStyle = sel.style.color; ctx.setLineDash([]); ctx.stroke();
    }
  }

  // ---------------------------------------------------------------- hit testing
  function hitTest(x, y) {
    const r = dpr();
    if (st.sel && st.sel._P) {
      const i = st.sel._P.findIndex((q) => Math.hypot(q.x - x, q.y - y) < 8);
      if (i >= 0) return { d: st.sel, handle: i };
    }
    ctx.save(); ctx.setTransform(r, 0, 0, r, 0, 0); ctx.lineWidth = 8;
    try {
      for (let k = st.items.length - 1; k >= 0; k--) {
        const d = st.items[k];
        if (d.hidden || !d._hits) continue;
        for (const h of d._hits) {
          if (h.stroke ? ctx.isPointInStroke(h.path, x * r, y * r) : ctx.isPointInPath(h.path, x * r, y * r)) return { d, handle: -1 };
        }
        if (d._P) { const i = d._P.findIndex((q) => Math.hypot(q.x - x, q.y - y) < 6); if (i >= 0) return { d, handle: i }; }
      }
    } finally { ctx.restore(); }
    return null;
  }

  // ---------------------------------------------------------------- interaction
  const rel = (e) => { const b = el.getBoundingClientRect(); return { x: e.clientX - b.left - leftOffset(), y: e.clientY - b.top }; };
  const inPane = ({ x, y }) => x >= 0 && y >= 0 && x <= paneW() && y <= paneH();
  let chartLocked = false;
  function lockChart(on) {
    if (on === chartLocked) return;
    chartLocked = on;
    chart.applyOptions({ handleScroll: !on, handleScale: !on });
  }
  const isDrawTool = (t) => TOOLS[t] && TOOLS[t].group !== "cursor" || t === "measure" || t === "zoom";
  function setTool(t) {
    if (st.draft && !isMulti(st.draft)) st.draft = null;
    finishMulti();
    st.tool = t;
    if (TOOLS[t] && TOOLS[t].group === "cursor" && t !== "eraser") {
      st.cursor = t;
      const vis = t === "cross";
      chart.applyOptions({ crosshair: { mode: t === "arrowcur" ? LW().CrosshairMode.Hidden ?? 2 : LW().CrosshairMode.Normal, vertLine: { visible: vis }, horzLine: { visible: vis } } });
    }
    el.style.cursor = t === "arrowcur" ? "default" : t === "dot" ? "crosshair" : t === "eraser" ? "not-allowed" : "";
    lockChart(isDrawTool(t));
    st.measure = null; markDirty(); renderToolbar();
  }
  const LW = () => window.LightweightCharts;
  function backToCursor() { if (!st.stay) setTool(st.cursor); else renderToolbar(); }

  function commit(d) {
    snapshot();
    delete d.done; d.done = true;
    st.items.push(d); st.sel = d; st.draft = null;
    st.last[d.type] = st.last[d.type] || {};
    persist(); markDirty(); renderFloat();
    if (TEXT_TOOLS.has(d.type) && !d.text) openSettings(d, true);
    backToCursor();
  }
  function isMulti(d) { return TOOLS[d?.type]?.n === -1; }
  function finishMulti() {
    const d = st.draft;
    if (!d || !isMulti(d)) return;
    d.pts.pop();   // remove floating preview point
    if (d.pts.length >= 2) commit(d); else st.draft = null;
  }

  let down = null;
  const onChart = (e) => el.contains(e.target);     // ignore clicks on the floating bar, legend, etc.
  function onDown(e) {
    if (e.button === 2 || !onChart(e)) return;
    const q = rel(e);
    if (!inPane(q)) return;
    const t = st.tool;
    if (t === "zoom") { st.zoom = { x0: q.x, x1: q.x }; consume(e); return; }
    if (t === "measure") {
      const p = fromXY(q.x, q.y, false);
      if (!p) return;
      if (st.measure && st.measure._fixed) { st.measure = null; setTool(st.cursor); consume(e); return; }
      if (!st.measure) st.measure = { type: "dprange", pts: [p, { ...p }], style: defaultStyle("dprange") };
      else { st.measure._fixed = true; }
      consume(e); markDirty(); return;
    }
    if (isDrawTool(t)) {
      consume(e);
      const p = fromXY(q.x, q.y);
      if (!p) return;
      const tool = TOOLS[t];
      if (tool.n === 0) { st.draft = { id: newId(), type: t, pts: [p], style: defaultStyle(t) }; down = { free: true }; return; }
      if (tool.n === 1) { commit({ id: newId(), type: t, pts: [p], style: defaultStyle(t) }); return; }
      if (!st.draft) {
        st.draft = { id: newId(), type: t, pts: [p, { ...p }], style: defaultStyle(t) };
        down = { x: q.x, y: q.y, started: true };
      } else {
        st.draft.pts[cursorIdx(st.draft)] = p;
        if (isPos(st.draft)) { commit(st.draft); markDirty(); return; }
        if (tool.n > 0 && st.draft.pts.length >= tool.n) commit(st.draft);
        else st.draft.pts.push({ ...p });
      }
      markDirty();
      return;
    }
    // cursor / eraser: select & drag
    const h = hitTest(q.x, q.y);
    if (t === "eraser") { if (h) { remove(h.d); consume(e); } return; }
    if (!h) { if (st.sel) { st.sel = null; renderFloat(); markDirty(); } return; }
    consume(e);
    st.sel = h.d; renderFloat(); markDirty();
    if (h.d.locked || st.lockAll) return;
    down = { drag: true, x: q.x, y: q.y, handle: h.handle, d: h.d, orig: JSON.parse(JSON.stringify(h.d.pts)), moved: false };
    lockChart(true);
  }
  const isPos = (d) => d.type === "long" || d.type === "short";
  const cursorIdx = (d) => (isPos(d) ? 1 : d.pts.length - 1);
  function onMove(e) {
    const q = rel(e);
    if (st.zoom) { st.zoom.x1 = q.x; markDirty(); return; }
    if (st.measure && !st.measure._fixed) { const p = fromXY(q.x, q.y, false); if (p) { st.measure.pts[1] = p; markDirty(); } return; }
    if (down && down.free && st.draft) { const p = fromXY(q.x, q.y, false); if (p) { st.draft.pts.push(p); markDirty(); } return; }
    if (st.draft) {
      const p = fromXY(q.x, q.y); if (!p) return;
      st.draft.pts[cursorIdx(st.draft)] = p;
      if (isPos(st.draft)) {
        const e0 = st.draft.pts[0]; st.draft.pts[2] = { t: p.t, p: e0.p - (p.p - e0.p) };
      }
      markDirty(); return;
    }
    if (down && down.drag) {
      if (!down.moved && Math.hypot(q.x - down.x, q.y - down.y) < 3) return;
      if (!down.moved) { snapshot(); down.moved = true; }
      const d = down.d;
      if (down.handle >= 0) {
        const p = fromXY(q.x, q.y); if (!p) return;
        d.pts[down.handle] = p;
        if ((d.type === "long" || d.type === "short") && d.pts[2]) {
          if (down.handle === 1) d.pts[2].t = p.t;
          if (down.handle === 2) d.pts[1].t = p.t;
        }
      } else {
        // translate in logical/price space so the shape keeps its bar spacing
        const ts = chart.timeScale(), s = series();
        const dL = Math.round(ts.coordinateToLogical(q.x) - ts.coordinateToLogical(down.x));
        const dP = s.coordinateToPrice(q.y) - s.coordinateToPrice(down.y);
        d.pts = down.orig.map((o) => ({ t: tOfLogical(logicalOfT(o.t) + dL), p: o.p + dP }));
      }
      markDirty(); renderFloat(); return;
    }
    if (!isDrawTool(st.tool)) {
      const h = inPane(q) ? hitTest(q.x, q.y) : null;
      const hv = h ? h.d : null;
      if (hv !== st.hover) { st.hover = hv; markDirty(); }
      el.style.cursor = h ? (h.handle >= 0 ? "pointer" : "move") : st.tool === "arrowcur" ? "default" : st.tool === "eraser" ? "not-allowed" : "";
    }
  }
  function onUp(e) {
    const q = rel(e);
    if (st.zoom) {
      const ts = chart.timeScale(), a = ts.coordinateToLogical(Math.min(st.zoom.x0, q.x)), b = ts.coordinateToLogical(Math.max(st.zoom.x0, q.x));
      st.zoom = null;
      if (b - a > 2) ts.setVisibleLogicalRange({ from: a, to: b });
      setTool(st.cursor); return;
    }
    if (down && down.free && st.draft) { if (st.draft.pts.length > 1) commit(st.draft); else st.draft = null; down = null; return; }
    if (down && down.started && st.draft) {
      // press-drag-release creates a 2-point drawing in one gesture
      if (Math.hypot(q.x - down.x, q.y - down.y) > 6 && TOOLS[st.draft.type].n === 2) commit(st.draft);
      down = null; return;
    }
    if (down && down.drag) { if (down.moved) persist(); down = null; lockChart(isDrawTool(st.tool)); return; }
    down = null;
  }
  function consume(e) { e.preventDefault(); e.stopPropagation(); }
  // capture phase: run before the chart's own handlers
  wrap.addEventListener("pointerdown", onDown, true);
  window.addEventListener("pointermove", onMove, true);
  window.addEventListener("pointerup", onUp, true);
  wrap.addEventListener("mousedown", (e) => { if (chartLocked) e.stopPropagation(); }, true);
  wrap.addEventListener("dblclick", (e) => {
    if (!onChart(e)) return;
    if (st.draft && isMulti(st.draft)) { st.draft.pts.pop(); finishMulti(); consume(e); return; }
    const h = hitTest(...Object.values(rel(e)));
    if (h) { consume(e); openSettings(h.d); }
  }, true);
  wrap.addEventListener("contextmenu", (e) => {
    if (!onChart(e)) return;
    const h = hitTest(...Object.values(rel(e)));
    if (h) { e.preventDefault(); st.sel = h.d; renderFloat(); markDirty(); }
  });
  document.addEventListener("keydown", (e) => {
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.querySelector("dialog[open]")) return;
    if (e.key === "Escape") { if (st.draft && isMulti(st.draft)) finishMulti(); st.draft = null; st.measure = null; setTool(st.cursor); }
    else if (e.key === "Enter" && st.draft) finishMulti();
    else if ((e.key === "Delete" || e.key === "Backspace") && st.sel) { remove(st.sel); e.preventDefault(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undo(e.shiftKey); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); undo(true); }
    else if (e.altKey && !e.ctrlKey) {
      const map = { t: "trend", h: "hline", v: "vline", f: "fib", c: "cross_line", j: "hray" };
      const t = e.shiftKey && e.key.toLowerCase() === "r" ? "rect" : map[e.key.toLowerCase()];
      if (t) { e.preventDefault(); pick(t); }
    } else if (e.shiftKey && !e.ctrlKey && !e.metaKey && st.tool !== "measure" && e.key === "Shift") { /* shift+click = measure */ }
    markDirty();
  });
  // Shift + click on chart = quick measure (TradingView behaviour)
  wrap.addEventListener("pointerdown", (e) => { if (e.shiftKey && onChart(e) && !isDrawTool(st.tool) && inPane(rel(e))) { setTool("measure"); onDown(e); } }, true);

  function remove(d) {
    snapshot();
    st.items = st.items.filter((x) => x !== d);
    if (st.sel === d) st.sel = null;
    persist(); markDirty(); renderFloat();
  }
  function undo(isRedo) {
    const from = isRedo ? st.redo : st.undo, to = isRedo ? st.undo : st.redo;
    if (!from.length) return;
    to.push(JSON.stringify(st.items.map(strip)));
    restore(from.pop());
  }

  // ---------------------------------------------------------------- left toolbar
  const bar = document.createElement("div");
  bar.id = "drawBar";
  const host = document.getElementById("gridCol") || document.getElementById("grid") || wrap;
  if (toolbar) host.parentElement.insertBefore(bar, host);
  const fly = document.createElement("div");
  fly.id = "drawFly"; fly.className = "hidden";
  document.body.appendChild(fly);
  const favBar = document.createElement("div");
  favBar.id = "drawFav"; favBar.className = "hidden";
  wrap.appendChild(favBar);
  const groupSel = {};
  let favs = [], showFav = false;
  try { Object.assign(groupSel, JSON.parse(localStorage.getItem("ltv.draw.groups") || "{}")); } catch { /* ignore */ }
  try { favs = JSON.parse(localStorage.getItem("ltv.draw.favs") || "[]"); showFav = localStorage.getItem("ltv.draw.showFav") === "1"; } catch { /* ignore */ }
  const saveUi = () => { try {
    localStorage.setItem("ltv.draw.groups", JSON.stringify(groupSel)); localStorage.setItem("ltv.draw.favs", JSON.stringify(favs));
    localStorage.setItem("ltv.draw.showFav", showFav ? "1" : "0");
  } catch { /* */ } };
  function pick(t) {
    const g = TOOLS[t]?.group;
    if (g) { groupSel[g] = t; saveUi(); }
    closeFly();
    C.setTool(t);
  }
  const toolIcon = (t, size = 22) => (TOOLS[t]?.emoji ? `<span class="emo">${TOOLS[t].emoji}</span>` : svg(t, size));
  const sep = () => bar.appendChild(Object.assign(document.createElement("div"), { className: "db-sep" }));
  function groupButton(g) {
    const cur = groupSel[g.id] || g.tools.find((x) => !x[0].startsWith("#"))[0];
    const b = document.createElement("div");
    b.className = "db-btn" + (TOOLS[C.st.tool]?.group === g.id ? " on" : "");
    b.title = TOOLS[cur].name + (TOOLS[cur].keys ? ` (${TOOLS[cur].keys})` : "");
    b.innerHTML = toolIcon(cur) + `<span class="db-more">‹</span>`;
    b.onclick = (e) => { if (e.target.closest(".db-more")) openFly(g, b); else pick(cur); };
    b.oncontextmenu = (e) => { e.preventDefault(); openFly(g, b); };
    bar.appendChild(b);
  }
  function plainButton(icon, title, on, fn, more) {
    const b = document.createElement("div");
    b.className = "db-btn" + (on ? " on" : ""); b.title = title;
    b.innerHTML = svg(icon) + (more ? `<span class="db-more">‹</span>` : "");
    b.onclick = (e) => { if (more && e.target.closest(".db-more")) more(b); else fn(b); };
    if (more) b.oncontextmenu = (e) => { e.preventDefault(); more(b); };
    bar.appendChild(b); return b;
  }
  function renderToolbar() {
    bar.innerHTML = "";
    GROUPS.forEach((g, i) => { groupButton(g); if (i === 0) sep(); });
    sep();
    plainButton("ruler", "Measure (Shift + click)", C.st.tool === "measure", () => C.setTool(C.st.tool === "measure" ? C.st.cursor : "measure"));
    plainButton("zoom", "Zoom in (drag a range)", C.st.tool === "zoom", () => C.setTool(C.st.tool === "zoom" ? C.st.cursor : "zoom"));
    sep();
    const mg = plainButton("magnet", ["Magnet mode: off", "Weak magnet", "Strong magnet"][C.st.magnet], C.st.magnet > 0,
      () => { C.st.magnet = C.st.magnet ? 0 : 1; renderToolbar(); },
      (b) => menu(b, [["Weak magnet", C.st.magnet === 1, () => { C.st.magnet = C.st.magnet === 1 ? 0 : 1; }], ["Strong magnet", C.st.magnet === 2, () => { C.st.magnet = C.st.magnet === 2 ? 0 : 2; }]]));
    if (C.st.magnet === 2) mg.classList.add("strong");
    plainButton("stay", "Stay in drawing mode", C.st.stay, () => { C.st.stay = !C.st.stay; renderToolbar(); });
    plainButton(C.st.lockAll ? "lock" : "unlock", C.st.lockAll ? "Unlock all drawings" : "Lock all drawings", C.st.lockAll, () => { C.st.lockAll = !C.st.lockAll; if (C.st.lockAll) { C.st.sel = null; C.renderFloat(); } renderToolbar(); });
    const anyHidden = C.st.hideAll || C.st.hideInd || C.st.hidePos;
    plainButton(anyHidden ? "eyeoff" : "eye", "Hide drawings", anyHidden,
      () => { C.setHide(!(C.st.hideAll || C.st.hideInd || C.st.hidePos) ? "draw" : "none"); },
      (b) => menu(b, [
        ["Hide drawings", C.st.hideAll, () => C.setHide(C.st.hideAll ? "-draw" : "draw")],
        ["Hide indicators", C.st.hideInd, () => C.setHide(C.st.hideInd ? "-ind" : "ind")],
        ["Hide positions and orders", C.st.hidePos, () => C.setHide(C.st.hidePos ? "-pos" : "pos")],
        ["Hide all", C.st.hideAll && C.st.hideInd && C.st.hidePos, () => C.setHide(C.st.hideAll && C.st.hideInd && C.st.hidePos ? "none" : "all")]]));
    plainButton("tree", "Object tree", false, C.openTree);
    sep();
    plainButton("trash", "Remove drawings", false, C.removeAll,
      (b) => menu(b, [["Remove drawings", false, C.removeAll], ["Remove indicators", false, () => C.onRemoveIndicators()], ["Remove drawings & indicators", false, () => { C.removeAll(); C.onRemoveIndicators(); }]]));
    const sp = document.createElement("div"); sp.style.flex = "1"; bar.appendChild(sp);
    const fb = plainButton(showFav ? "starfill" : "star", "Favorites toolbar", showFav, () => { showFav = !showFav; saveUi(); renderFav(); renderToolbar(); });
    fb.classList.add("fav");
    renderFav();
    if (C === ctl) onToolbar();
  }
  function setHide(what) {
    if (what === "none") { st.hideAll = st.hideInd = st.hidePos = false; }
    else if (what === "all") { st.hideAll = st.hideInd = st.hidePos = true; }
    else { const on = !what.startsWith("-"), k = what.replace("-", ""); st[{ draw: "hideAll", ind: "hideInd", pos: "hidePos" }[k]] = on; }
    onHideIndicators(st.hideInd);
    st.sel = null; renderFloat(); markDirty(); renderToolbar();
  }
  async function removeAll() {
    if (!st.items.length) return;
    if (!(await LTVSettings.confirm(`Remove all ${st.items.length} drawings on ${st.symbol}?`, { title: "Remove drawings", ok: "Remove", danger: true }))) return;
    snapshot(); st.items = []; st.sel = null; persist(); markDirty(); renderFloat();
  }
  function closeFly() { fly.classList.add("hidden"); document.querySelectorAll(".db-btn.open").forEach((x) => x.classList.remove("open")); }
  function place(anchor) {
    const r = anchor.getBoundingClientRect();
    anchor.classList.add("open");
    fly.classList.remove("hidden");
    fly.style.left = r.right + 6 + "px";
    fly.style.top = Math.max(4, Math.min(r.top - 6, window.innerHeight - fly.offsetHeight - 8)) + "px";
  }
  function menu(anchor, items) {
    closeFly();
    fly.innerHTML = "";
    const list = document.createElement("div"); list.className = "fly-list";
    for (const [name, on, fn] of items) {
      const it = document.createElement("div");
      it.className = "fly-it" + (on ? " on" : "");
      it.innerHTML = `<span class="fly-chk">${on ? "✓" : ""}</span><span class="fly-name">${name}</span>`;
      it.onclick = () => { fn(); closeFly(); renderToolbar(); };
      list.appendChild(it);
    }
    fly.appendChild(list); place(anchor);
  }
  function openFly(g, anchor) {
    closeFly();
    fly.innerHTML = "";
    const list = document.createElement("div");
    list.className = g.id === "icons" ? "fly-emo" : "fly-list";
    for (const [id, name] of g.tools) {
      if (id.startsWith("#")) {
        if (list.children.length) list.appendChild(Object.assign(document.createElement("div"), { className: "fly-sep" }));
        list.appendChild(Object.assign(document.createElement("div"), { className: "fly-h", textContent: id.slice(1) }));
        continue;
      }
      const t = TOOLS[id], it = document.createElement("div");
      it.className = "fly-it" + (C.st.tool === id ? " on" : "");
      it.title = name;
      if (g.id === "icons") it.textContent = name;
      else it.innerHTML = `${toolIcon(id, 24)}<span class="fly-name">${name}</span><span class="fly-keys">${t.keys || ""}</span>` +
        `<span class="fly-star${favs.includes(id) ? " on" : ""}" title="Add to favorites">${svg(favs.includes(id) ? "starfill" : "star", 16)}</span>`;
      it.onclick = (e) => {
        if (e.target.closest(".fly-star")) {
          favs = favs.includes(id) ? favs.filter((x) => x !== id) : [...favs, id];
          if (favs.length && !showFav) showFav = true;
          saveUi(); renderFav(); openFly(g, anchor); return;
        }
        pick(id);
      };
      list.appendChild(it);
    }
    fly.appendChild(list); place(anchor);
  }
  function renderFav() {
    favBar.innerHTML = "";
    favBar.classList.toggle("hidden", !showFav || !favs.length);
    for (const id of favs) {
      if (!TOOLS[id]) continue;
      const b = document.createElement("div");
      b.className = "db-btn" + (C.st.tool === id ? " on" : ""); b.title = TOOLS[id].name;
      b.innerHTML = toolIcon(id, 20);
      b.onclick = () => pick(id);
      favBar.appendChild(b);
    }
  }
  favBar.addEventListener("pointerdown", (e) => e.stopPropagation());
  // the toolbar can drive another chart's drawings (multi-chart layouts): C is the controller it acts on
  const ctl = { get st() { return st; }, setTool, setHide, removeAll, openTree, renderFloat, onRemoveIndicators };
  let C = ctl;
  document.addEventListener("pointerdown", (e) => { if (!fly.contains(e.target) && !bar.contains(e.target)) closeFly(); }, true);
  window.addEventListener("resize", closeFly);
  // ---------------------------------------------------------------- floating toolbar for the selection
  const ft = document.createElement("div");
  ft.id = "drawFloat"; ft.className = "hidden";
  wrap.appendChild(ft);
  function renderFloat() {
    const d = st.sel;
    if (!d) { ft.classList.add("hidden"); return; }
    const s = d.style;
    ft.classList.remove("hidden");
    ft.innerHTML = `
      <span class="ft-name">${TOOLS[d.type]?.name || d.type}</span>
      <input type="color" data-k="color" value="${toHex(s.color)}" title="Line colour">
      ${FILL_TOOLS.has(d.type) ? `<input type="color" data-k="fill" value="${toHex(s.fill)}" title="Fill colour">` : ""}
      <select data-k="width" title="Width">${[1, 2, 3, 4].map((w) => `<option ${+s.width === w ? "selected" : ""}>${w}</option>`).join("")}</select>
      <select data-k="dash" title="Style">${["solid", "dashed", "dotted"].map((v) => `<option ${s.dash === v ? "selected" : ""}>${v}</option>`).join("")}</select>
      <button data-a="settings" title="Settings">⚙</button>
      <button data-a="lock" title="${d.locked ? "Unlock" : "Lock"}">${d.locked ? "🔒" : "🔓"}</button>
      <button data-a="clone" title="Clone">⧉</button>
      <button data-a="delete" title="Remove">🗑</button>`;
    ft.querySelectorAll("[data-k]").forEach((inp) => inp.oninput = () => {
      snapshot();
      s[inp.dataset.k] = inp.dataset.k === "width" ? +inp.value : inp.value;
      st.last[d.type] = { ...(st.last[d.type] || {}), [inp.dataset.k]: s[inp.dataset.k] };
      savePrefs(); persist(); markDirty();
    });
    ft.querySelector('[data-a="settings"]').onclick = () => openSettings(d);
    ft.querySelector('[data-a="lock"]').onclick = () => { d.locked = !d.locked; persist(); renderFloat(); };
    ft.querySelector('[data-a="clone"]').onclick = () => {
      snapshot();
      const c = JSON.parse(JSON.stringify(strip(d))); c.id = newId();
      c.pts = c.pts.map((p) => ({ t: tOfLogical(logicalOfT(p.t) + 5), p: p.p }));
      st.items.push(c); st.sel = c; persist(); markDirty(); renderFloat();
    };
    ft.querySelector('[data-a="delete"]').onclick = () => remove(d);
  }
  ft.addEventListener("pointerdown", (e) => e.stopPropagation());
  const savePrefs = () => { try { localStorage.setItem("ltv.draw.prefs", JSON.stringify(st.last)); } catch { /* */ } };
  const _c = document.createElement("canvas").getContext("2d");
  function toHex(c) { _c.fillStyle = "#000"; _c.fillStyle = c || "#000"; const v = _c.fillStyle; return v.startsWith("#") ? v : "#" + (v.match(/\d+/g) || [0, 0, 0]).slice(0, 3).map((x) => (+x).toString(16).padStart(2, "0")).join(""); }

  // ---------------------------------------------------------------- volume profile settings (FRVP / anchored VP)
  const VP_DEF = { layout: "Number of Rows", rows: 24, volume: "Up/Down", va: 70, width: 30, placement: "Left", extend_poc: false,
    show_poc: true, show_va: true, show_vahval: true, show_values: false, use_ib: true,
    up: "rgba(38,166,154,0.30)", down: "rgba(239,83,80,0.30)", va_up: "rgba(38,166,154,0.70)", va_down: "rgba(239,83,80,0.70)",
    poc: "#ff9800", vah: "#2962ff", val: "#2962ff" };
  const alphaOf = (c) => { const m = String(c).match(/rgba?\([^)]*,\s*([\d.]+)\s*\)/); return m && String(c).startsWith("rgba") ? +m[1] : 1; };
  function vpForm(v0) {
    const v = { ...VP_DEF, ...v0 };
    const sel = (n, opts) => `<select name="vp_${n}">${opts.map((o) => `<option ${v[n] === o ? "selected" : ""}>${o}</option>`).join("")}</select>`;
    const num = (n, min, max) => `<input type="number" name="vp_${n}" min="${min}" max="${max}" value="${v[n]}" style="width:70px">`;
    const chk = (n, t) => `<label class="chk"><input type="checkbox" name="vp_${n}" ${v[n] ? "checked" : ""}>${t}</label>`;
    const col = (n) => `<input type="color" name="vp_${n}" value="${toHex(v[n])}"><input type="range" name="vp_${n}_a" min="0" max="1" step="0.05" value="${alphaOf(v[n])}" style="width:60px">`;
    return `<div class="sep-h"></div><div class="muted">Volume profile</div>
      <label class="srow"><span>Row layout</span><span class="ctl">${sel("layout", ["Number of Rows", "Ticks Per Row"])} ${num("rows", 1, 1000)}</span></label>
      <label class="srow"><span>Volume</span><span class="ctl">${sel("volume", ["Up/Down", "Total", "Delta"])}</span></label>
      <label class="srow"><span>Value area %</span><span class="ctl">${num("va", 1, 100)}</span></label>
      <label class="srow"><span>Width % / placement</span><span class="ctl">${num("width", 5, 100)} ${sel("placement", ["Left", "Right"])}</span></label>
      <label class="srow"><span>Show</span><span class="ctl">${chk("show_poc", "POC")}${chk("show_va", "Value area")}${chk("show_vahval", "VAH/VAL")}${chk("show_values", "Values")}${chk("extend_poc", "Extend POC")}</span></label>
      <label class="srow"><span>Data</span><span class="ctl">${chk("use_ib", "Use 1m intrabars")}</span></label>
      <label class="srow"><span>Up / Down</span><span class="ctl">${col("up")} ${col("down")}</span></label>
      <label class="srow"><span>VA up / down</span><span class="ctl">${col("va_up")} ${col("va_down")}</span></label>
      <label class="srow"><span>POC / VAH / VAL</span><span class="ctl">${col("poc")} ${col("vah")} ${col("val")}</span></label>`;
  }
  function readVpForm(f) {
    const v = {}, g = (n) => f["vp_" + n];
    for (const n of ["layout", "volume", "placement"]) v[n] = g(n).value;
    for (const n of ["rows", "va", "width"]) v[n] = +g(n).value || VP_DEF[n];
    for (const n of ["show_poc", "show_va", "show_vahval", "show_values", "extend_poc", "use_ib"]) v[n] = g(n).checked;
    for (const n of ["up", "down", "va_up", "va_down", "poc", "vah", "val"]) { const a = +g(n + "_a").value; v[n] = a >= 1 ? g(n).value : hexA(g(n).value, a); }
    return v;
  }

  // ---------------------------------------------------------------- settings dialog
  const dlg = document.createElement("dialog");
  dlg.id = "drawDlg";
  document.body.appendChild(dlg);
  function openSettings(d, focusText = false) {
    const s = d.style, isVP = d.type === "vprofile" || d.type === "avprofile", isLine = TOOLS[d.type]?.n >= 2 && !isVP;
    const pts = d.pts.map((p, i) => `<label class="srow"><span>Point ${i + 1}</span><span class="ctl"><input type="number" step="any" data-pt="${i}" value="${+p.p.toFixed(4)}"></span></label>`).join("");
    dlg.innerHTML = `<form method="dialog" class="dlg">
      <div class="dlg-head"><b>${TOOLS[d.type]?.name || d.type}</b><button value="cancel">✕</button></div>
      <div id="drawForm">
        <label class="srow"><span>Line</span><span class="ctl"><input type="color" name="color" value="${toHex(s.color)}">
          <select name="width">${[1, 2, 3, 4, 6, 8].map((w) => `<option ${+s.width === w ? "selected" : ""}>${w}</option>`).join("")}</select>
          <select name="dash">${["solid", "dashed", "dotted"].map((v) => `<option ${s.dash === v ? "selected" : ""}>${v}</option>`).join("")}</select></span></label>
        <label class="srow"><span>Background</span><span class="ctl"><input type="color" name="fill" value="${toHex(s.fill)}">
          <input type="range" name="fillA" min="0" max="1" step="0.05" value="${s.fillA}"></span></label>
        <label class="srow"><span>Text</span><span class="ctl"><textarea name="text" rows="2" placeholder="Text">${(d.text || "").replace(/</g, "&lt;")}</textarea></span></label>
        <label class="srow"><span>Font size</span><span class="ctl"><select name="font">${[10, 11, 12, 14, 16, 20, 24, 28, 32, 40].map((f) => `<option ${+s.font === f ? "selected" : ""}>${f}</option>`).join("")}</select>
          <label class="chk"><input type="checkbox" name="bold" ${s.bold ? "checked" : ""}>Bold</label></span></label>
        ${isLine ? `<label class="srow"><span>Extend</span><span class="ctl"><label class="chk"><input type="checkbox" name="extL" ${s.extL ? "checked" : ""}>Left</label>
          <label class="chk"><input type="checkbox" name="extR" ${s.extR ? "checked" : ""}>Right</label>
          <label class="chk"><input type="checkbox" name="arrow" ${s.arrow ? "checked" : ""}>Arrow</label></span></label>` : ""}
        <label class="srow"><span>Labels</span><span class="ctl"><label class="chk"><input type="checkbox" name="labels" ${s.labels !== false ? "checked" : ""}>Show</label></span></label>
        ${isVP ? vpForm(d.style.vp || {}) : ""}
        <div class="sep-h"></div><div class="muted">Coordinates (price)</div>${pts}
      </div>
      <div class="dlg-foot"><span class="spacer"></span><button value="cancel">Cancel</button><button value="ok" class="primary">OK</button></div></form>`;
    dlg.showModal();
    if (focusText) dlg.querySelector('[name="text"]').focus();
    dlg.onclose = () => {
      if (dlg.returnValue !== "ok") return;
      snapshot();
      const f = dlg.querySelector("form");
      for (const k of ["color", "fill", "dash"]) s[k] = f[k].value;
      for (const k of ["width", "fillA", "font"]) s[k] = +f[k].value;
      for (const k of ["extL", "extR", "arrow", "labels", "bold"]) if (f[k]) s[k] = f[k].checked;
      d.text = f.text.value;
      if (isVP) { s.vp = readVpForm(f); st.last[d.type + ".vp"] = s.vp; }
      f.querySelectorAll("[data-pt]").forEach((inp) => { const v = parseFloat(inp.value); if (Number.isFinite(v)) d.pts[+inp.dataset.pt].p = v; });
      st.last[d.type] = { color: s.color, width: s.width, dash: s.dash, fill: s.fill, fillA: s.fillA, font: s.font, extL: s.extL, extR: s.extR };
      savePrefs(); persist(); markDirty(); renderFloat();
    };
    dlg.querySelector('[name="text"]').addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); dlg.returnValue = "ok"; dlg.close("ok"); } });
  }

  // ---------------------------------------------------------------- object tree
  function openTree() {
    dlg.innerHTML = `<form method="dialog" class="dlg"><div class="dlg-head"><b>Object Tree · ${st.symbol}</b><button value="cancel">✕</button></div>
      <div class="list" id="treeList"></div></form>`;
    const box = dlg.querySelector("#treeList");
    const draw = () => {
      box.innerHTML = st.items.length ? "" : '<div class="muted" style="padding:8px">No drawings</div>';
      st.items.slice().reverse().forEach((d) => {
        const row = document.createElement("div");
        row.className = "it";
        row.innerHTML = `<span>${TOOLS[d.type]?.emoji || ""} ${TOOLS[d.type]?.name || d.type}${d.text ? ` <small>${d.text.slice(0, 24).replace(/</g, "&lt;")}</small>` : ""}</span>
          <span><button type="button" data-a="h">${d.hidden ? "🙈" : "👁"}</button><button type="button" data-a="l">${d.locked ? "🔒" : "🔓"}</button><button type="button" data-a="x">🗑</button></span>`;
        row.querySelector('[data-a="h"]').onclick = (e) => { e.stopPropagation(); d.hidden = !d.hidden; persist(); markDirty(); draw(); };
        row.querySelector('[data-a="l"]').onclick = (e) => { e.stopPropagation(); d.locked = !d.locked; persist(); draw(); };
        row.querySelector('[data-a="x"]').onclick = (e) => { e.stopPropagation(); remove(d); draw(); };
        row.onclick = () => {
          st.sel = d; renderFloat(); markDirty();
          const L = logicalOfT(d.pts[0].t), r = chart.timeScale().getVisibleLogicalRange();
          if (r && L != null && (L < r.from || L > r.to)) { const w = r.to - r.from; chart.timeScale().setVisibleLogicalRange({ from: L - w / 2, to: L + w / 2 }); }
        };
        box.appendChild(row);
      });
    };
    draw();
    dlg.showModal();
    dlg.onclose = null;
  }

  renderToolbar();
  requestAnimationFrame(frame);
  return {
    setSymbol, redraw: markDirty, setTool, removeAll, ctl, renderToolbar,
    setTarget(c) { C = c || ctl; closeFly(); renderToolbar(); },
    add(type, pts) { const d = { id: newId(), type, pts, style: defaultStyle(type) }; snapshot(); st.items.push(d); st.sel = d; persist(); markDirty(); renderFloat(); return d; },
    get items() { return st.items; },
    get state() { return st; },
  };
}

window.LTVDraw = { init, GROUPS, TOOLS };
})();
