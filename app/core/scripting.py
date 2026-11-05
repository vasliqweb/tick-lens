"""
Indicator script runtime.

Every indicator (built-in or user written) is a small Python script executed
against an OHLCV DataFrame. Scripts are vectorised (whole-series pandas ops),
Pine-like helpers are provided, and output is declared with plot()/hline()/plotshape().

Example:
    indicator("EMA Cross", overlay=True)
    fast = input("Fast", 9, min=1)
    slow = input("Slow", 21, min=1)
    f, s = ema(close, fast), ema(close, slow)
    plot(f, "Fast", color="#2962ff")
    plot(s, "Slow", color="#ff6d00")
    plotshape(crossover(f, s), "Buy", position="below", shape="arrowUp", color="#26a69a")

NOTE: scripts run with Python's exec on the server. Imports are limited to a
whitelist, but this is NOT a security sandbox: run the app for yourself only.
"""
from __future__ import annotations

import builtins
import hashlib
import math
import re
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

try:  # pandas-ta is optional; scripts can use `ta.<name>(...)` when installed
    import pandas_ta as _ta
except Exception:  # pragma: no cover
    _ta = None

ALLOWED_IMPORTS = {"math", "statistics", "numpy", "pandas", "pandas_ta", "talib", "datetime"}
PALETTE = ["#2962ff", "#ff6d00", "#e91e63", "#00bcd4", "#9c27b0", "#4caf50", "#ffeb3b", "#795548"]


def _safe_import(name, *a, **kw):
    if name.split(".")[0] not in ALLOWED_IMPORTS:
        raise ImportError(f"import of '{name}' not allowed in scripts")
    return builtins.__import__(name, *a, **kw)


_SAFE_BUILTINS = {k: getattr(builtins, k) for k in dir(builtins)
                  if k not in {"open", "exec", "eval", "compile", "input", "__import__",
                               "breakpoint", "exit", "quit", "help", "globals", "locals", "vars"}}
_SAFE_BUILTINS["__import__"] = _safe_import


# ---------------------------------------------------------------------------
# Pine-like helpers (all vectorised, pd.Series in / pd.Series out)
# ---------------------------------------------------------------------------
def _s(x, like: pd.Series) -> pd.Series:
    if isinstance(x, pd.Series):
        return x
    if np.isscalar(x):
        return pd.Series(float(x), index=like.index)
    return pd.Series(np.asarray(x, dtype="float64"), index=like.index)


def sma(s, n):            return s.rolling(int(n), min_periods=int(n)).mean()
def ema(s, n):            return s.ewm(span=int(n), adjust=False).mean()
def rma(s, n):            return s.ewm(alpha=1 / int(n), adjust=False).mean()
def stdev(s, n):          return s.rolling(int(n), min_periods=int(n)).std(ddof=0)
def highest(s, n):        return s.rolling(int(n), min_periods=1).max()
def lowest(s, n):         return s.rolling(int(n), min_periods=1).min()
def change(s, n=1):       return s.diff(int(n))
def nz(s, v=0.0):         return s.fillna(v)


def wma(s, n):
    n = int(n)
    w = np.arange(1, n + 1, dtype="float64")
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def hma(s, n):
    n = int(n)
    return wma(2 * wma(s, n // 2) - wma(s, n), max(int(math.sqrt(n)), 1))


def rsi(s, n=14):
    d = s.diff()
    up, dn = rma(d.clip(lower=0), n), rma(-d.clip(upper=0), n)
    return 100 - 100 / (1 + up / dn)


def macd(s, fast=12, slow=26, signal=9):
    m = ema(s, fast) - ema(s, slow)
    sig = ema(m, signal)
    return m, sig, m - sig


def bb(s, n=20, k=2.0):
    mid = sma(s, n)
    sd = stdev(s, n)
    return mid, mid + k * sd, mid - k * sd


def crossover(a, b):
    b = _s(b, a)
    return (a > b) & (a.shift() <= b.shift())


def crossunder(a, b):
    b = _s(b, a)
    return (a < b) & (a.shift() >= b.shift())


# ---------------------------------------------------------------------------
class ScriptError(Exception):
    pass


_code_cache: Dict[str, Any] = {}


def _compile(code: str):
    key = hashlib.sha1(code.encode()).hexdigest()
    obj = _code_cache.get(key)
    if obj is None:
        try:
            obj = compile(code, "<script>", "exec")
        except SyntaxError as e:
            raise ScriptError(f"SyntaxError line {e.lineno}: {e.msg}") from None
        if len(_code_cache) > 500:
            _code_cache.clear()
        _code_cache[key] = obj
    return obj


def title_of(code: str, fallback: str) -> str:
    m = re.search(r"""indicator\(\s*["']([^"']+)""", code)
    return m.group(1) if m else fallback


class _Info(dict):
    """dict with attribute access: syminfo.type == syminfo["type"]."""
    __getattr__ = dict.get


MAX_OBJECTS = 500   # per kind (boxes / labels / lines), oldest dropped first like Pine


def _session_open_min(session: str) -> int:
    m = re.match(r"(\d{2})(\d{2})", session or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else 0


def run_script(code: str, df: pd.DataFrame, inputs: Optional[Dict[str, Any]] = None,
               tail: Optional[int] = None, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute a script on df. Returns a JSON-able result.

    tail: only serialise the last `tail` bars (live updates).
    ctx:  {"syminfo": dict, "tf": seconds, "lower_tf": fn(tf_seconds) -> DataFrame | None}
    """
    inputs = inputs or {}
    ctx = ctx or {}
    meta = {"title": "Script", "overlay": True, "precision": None, "scale": None, "showInputs": True, "showValues": True, "help": None}
    decl_inputs: List[dict] = []
    plots: List[dict] = []
    hlines: List[dict] = []
    shapes: List[tuple] = []
    bar_colors: List[tuple] = []
    boxes: List[dict] = []
    labels: List[dict] = []
    lines: List[dict] = []
    tables: List[dict] = []
    profiles: List[dict] = []
    vpspecs: List[dict] = []
    bubbles: List[dict] = []
    alerts: List[dict] = []
    o, h, l, c, v = (df[k] for k in ("open", "high", "low", "close", "volume"))
    info = _Info({"ticker": "", "source": "", "type": "stock", "timezone": "UTC", "session": "0000-2400",
                  "is24x7": True, "mintick": 0.01, "currency": "", "vix": None, **(ctx.get("syminfo") or {})})
    tf_sec = int(ctx.get("tf") or (int((df.index[1] - df.index[0]).total_seconds()) if len(df) > 1 else 60))
    try:
        lt = df.index.tz_localize("UTC").tz_convert(info.timezone).tz_localize(None)
    except Exception:
        lt = df.index
    local_time = pd.Series(lt, index=df.index)
    session_day = pd.Series(lt.normalize(), index=df.index)
    session_minute = pd.Series((lt.hour * 60 + lt.minute - _session_open_min(info.session)) % 1440, index=df.index)

    def _t(x):
        """bar index (int, negative from the end) or timestamp -> unix seconds"""
        if x is None:
            return None
        if isinstance(x, (int, np.integer)):
            return int(df.index[int(x)].value // 10**9)
        return int(pd.Timestamp(x).value // 10**9)

    def _f(x):
        x = float(x)
        return x if math.isfinite(x) else None

    def barcolor(colors, border=None):
        """Colour each candle: a Series/list of CSS colours (None/NaN = chart default). border: optional border colours."""
        bar_colors.append((_s_obj(colors, c), None if border is None else _s_obj(border, c)))

    def box(left, right, top, bottom, bgcolor="rgba(41,98,255,.2)", border_color=None, border_style="solid",
            text="", text_color=None, extend=False, tip=None):
        """Rectangle from bar `left` to bar `right` (index or time). right=None or extend=True runs to the last bar.
        tip: optional hover tooltip {"title", "rows": [[name, value]], "status", "notes": [str]}."""
        boxes.append({"l": _t(left), "r": _t(right), "top": _f(top), "bottom": _f(bottom), "bg": bgcolor,
                      "border": border_color, "bstyle": border_style, "text": str(text), "tc": text_color,
                      "extend": bool(extend or right is None), **({"tip": tip} if tip else {})})

    def bubble(x, y, size=6, color="rgba(41,98,255,.45)", border=None, text="", tip=None):
        """Circle at bar x / price y; size = radius in px (2..30). tip: hover tooltip like box()."""
        bubbles.append({"t": _t(x), "p": _f(y), "r": max(2.0, min(30.0, float(size))), "bg": color,
                        "border": border, "text": str(text), **({"tip": tip} if tip else {})})

    def label(x, y, text="", color="#2962ff", textcolor="#ffffff", style="down", size="normal", align="center"):
        """Text bubble at bar x / price y. style: down (points down, sits above y), up, left, right, none.
        align (style none only): center, or left = text starts at x."""
        labels.append({"t": _t(x), "p": _f(y), "text": str(text), "bg": color, "tc": textcolor, "style": style, "size": size,
                       "align": align})

    def line(x1, y1, x2, y2, color="#2962ff", width=1, style="solid", extend=False):
        lines.append({"t1": _t(x1), "p1": _f(y1), "t2": _t(x2), "p2": _f(y2), "color": color, "width": width,
                      "style": style, "extend": bool(extend or x2 is None)})

    def table(cells, position="top_right", title=""):
        """cells: rows of str or {"text", "bg", "color", "bold"}. position: top_right, top_left, bottom_right, bottom_left."""
        rows = [[x if isinstance(x, dict) else {"text": str(x)} for x in row] for row in cells]
        tables.append({"rows": rows, "position": position, "title": title})

    def profile(p, **style):
        """Volume profile object (from vp.session_profiles / vp.build plus l/r times) drawn as a histogram.
        style: width (% of the profile's time span), placement (Left/Right), volume (Up/Down|Total|Delta),
        up/down/va_up/va_down/poc/vah/val colours, show_poc, show_va, show_values, extend_poc."""
        if p:
            profiles.append({**p, "style": style})

    def profile_spec(kind="vrvp", **opts):
        """A profile the chart computes itself (Visible Range VP: depends on what is on screen)."""
        vpspecs.append({"kind": str(kind), **opts})

    def alert(message, bar=-1):
        """Raise an alert for bar `bar` (default: the last bar). The app notifies once the bar has closed."""
        alerts.append({"t": _t(bar), "msg": str(message)})

    def lower_tf(tf=60):
        """Intrabars of a lower timeframe (seconds) from the symbol's own source, or None if unavailable."""
        fn = ctx.get("lower_tf")
        if fn is None or int(tf) >= tf_sec:
            return None
        d = fn(int(tf))
        if d is None or d.empty:
            return None
        return d[(d.index >= df.index[0]) & (d.index < df.index[-1] + pd.Timedelta(seconds=tf_sec))]

    def request(symbol=None, tf=86400):
        """Bars of another symbol / timeframe from the data source (UTC index), or None.
        symbol=None: this chart's symbol; "VIX": its volatility index (India VIX / CBOE VIX)."""
        fn = ctx.get("request")
        if fn is None:
            return None
        d = fn(symbol, int(tf))
        return None if d is None or d.empty else d

    def breadth():
        """NIFTY 50 breadth on chart bars: DataFrame(adv_open, above_vwap, n) = value at each bar's last
        closed minute (share 0..1 of stocks above today's open / their VWAP), NaN where unknown; None if not
        available (only NIFTY / NIFTY FUT on Breeze, from cached constituent 1m candles)."""
        fn = ctx.get("breadth")
        d = fn() if fn else None
        if d is None or d.empty:
            return None
        d = d[~d.index.duplicated(keep="last")].sort_index()
        key = df.index + pd.Timedelta(seconds=tf_sec - 60)        # the bar's last 1m candle
        out = d.reindex(key, method="ffill", tolerance=pd.Timedelta("5min"))
        out.index = df.index
        return out

    def options_chain():
        """Nearest-expiry index options, 1 minute, long format: DataFrame(time [UTC epoch s of the 1m candle],
        expiry, strike, right ['CE'/'PE'], close, volume, oi [NaN = not reported]) covering the chart's bars;
        None if not available (Breeze charts of NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY / SENSEX or their FUT,
        from data/Breeze/<INDEX>/options/ - history via scripts/options_oi/fetch_options_oi.py)."""
        fn = ctx.get("options")
        d = fn() if fn else None
        if d is None or len(d) == 0:
            return None
        t0, t1 = int(df.index[0].value // 10**9), int(df.index[-1].value // 10**9) + tf_sec
        return d[(d.time >= t0) & (d.time < t1)].reset_index(drop=True)

    def security(tf, fn):
        """Higher-timeframe value without repainting: fn(htf_df) evaluated on bars resampled to tf seconds
        (86400 = trading day, 604800 = week), shifted one HTF bar and spread back onto chart bars."""
        tf = int(tf)
        key = session_day if tf == 86400 else (session_day - pd.to_timedelta(session_day.dt.dayofweek, unit="D")
                                               if tf == 604800 else session_day.dt.to_period("M").dt.start_time
                                               if tf == 2592000 else local_time.dt.floor(f"{tf}s"))
        g = df.groupby(key.values)
        htf = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                            "close": g["close"].last(), "volume": g["volume"].sum()})
        r = fn(htf)
        r = r.shift(1) if isinstance(r, (pd.Series, pd.DataFrame)) else r
        if isinstance(r, pd.DataFrame):
            return r.reindex(key.values).set_axis(df.index)
        return pd.Series(np.asarray(r.reindex(key.values)), index=df.index)

    def indicator(title="Script", overlay=True, precision=None, scale=None, show_inputs=False, show_values=False, help=None):
        """scale="own": overlay on the price pane with its own hidden scale in the bottom 20% (volume-style).
        show_inputs / show_values: default for "Inputs / Values in status line" (the user can still turn them on).
        help: URL of a "How to use" page, linked at the top of the Settings Inputs tab."""
        hp = str(help) if help else None
        if hp and not (hp.startswith("/static/") or hp.startswith("https://") or hp.startswith("http://")): hp = None
        meta.update(title=str(title), overlay=bool(overlay), precision=precision, scale=scale,
                    showInputs=bool(show_inputs), showValues=bool(show_values), help=hp)

    def input_(name, default, options=None, min=None, max=None, step=None, tooltip=None):
        """tooltip: help text shown as (i) next to the input in Settings."""
        spec = {"name": name, "default": default, "type": type(default).__name__,
                "options": options, "min": min, "max": max, "step": step}
        if tooltip:
            spec["tooltip"] = str(tooltip)
        decl_inputs.append(spec)
        val = inputs.get(name, default)
        try:
            if isinstance(default, bool):
                val = val if isinstance(val, bool) else str(val).lower() in ("1", "true", "yes")
            elif isinstance(default, int):
                val = int(float(val))
            elif isinstance(default, float):
                val = float(val)
            else:
                val = str(val)
        except (TypeError, ValueError):
            val = default
        if options and val not in options:
            val = default
        return val

    def plot(series, title=None, color=None, style="line", linewidth=2, pane=None):
        plots.append({"series": _s(series, c), "title": title or f"Plot {len(plots) + 1}",
                      "color": color if color is not None else PALETTE[len(plots) % len(PALETTE)],
                      "style": style, "lineWidth": linewidth, "pane": pane})

    def hline(price, title="", color="#787b86", style="dashed"):
        hlines.append({"price": float(price), "title": title, "color": color, "style": style})

    def plotshape(cond, title="", position="above", shape="circle", color="#2962ff", text=""):
        shapes.append((_s(cond, c).fillna(0).astype(bool), title, position, shape, color, text))

    ns = {
        "__builtins__": _SAFE_BUILTINS, "__name__": "__script__",
        "np": np, "pd": pd, "math": math, "ta": _ta, "df": df,
        "open": o, "high": h, "low": l, "close": c, "volume": v,
        "hl2": (h + l) / 2, "hlc3": (h + l + c) / 3, "ohlc4": (o + h + l + c) / 4,
        "time": pd.Series(df.index, index=df.index),
        "indicator": indicator, "input": input_, "plot": plot, "hline": hline, "plotshape": plotshape,
        "sma": sma, "ema": ema, "rma": rma, "wma": wma, "hma": hma, "stdev": stdev,
        "highest": highest, "lowest": lowest, "change": change, "nz": nz,
        "rsi": rsi, "macd": macd, "bb": bb, "crossover": crossover, "crossunder": crossunder,
        "na": math.nan,
        "syminfo": info, "timeframe": tf_sec, "local_time": local_time, "session_day": session_day,
        "session_minute": session_minute, "barcolor": barcolor, "box": box, "bubble": bubble, "label": label, "line": line,
        "table": table, "profile": profile, "profile_spec": profile_spec, "vp": _vp_ns(), "lower_tf": lower_tf, "security": security, "request": request, "breadth": breadth, "options_chain": options_chain, "alert": alert,
    }
    ns["source"] = lambda name: ns[name] if name in ("open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4") else close_err(name)
    try:
        exec(_compile(code), ns)
    except ScriptError:
        raise
    except Exception as e:
        tb = e.__traceback__
        line = None
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == "<script>":
                line = tb.tb_lineno
            tb = tb.tb_next
        raise ScriptError(f"{type(e).__name__}{f' line {line}' if line else ''}: {e}") from None

    sl = slice(-tail, None) if tail else slice(None)
    times = (df.index[sl].as_unit("s").asi8).tolist()

    def ser(s: pd.Series):
        a = pd.to_numeric(s, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)[sl]
        return [round(float(x), 6) if math.isfinite(x) else None for x in a]

    out_plots = []
    for p in plots:
        col = p["color"]
        item = {k: p[k] for k in ("title", "style", "lineWidth", "pane")}
        if isinstance(col, (pd.Series, np.ndarray, list)):
            item["color"] = PALETTE[0]
            item["colors"] = [None if x is None or x != x else str(x) for x in _s_obj(col, c)[sl]]
        else:
            item["color"] = col
        item["values"] = ser(p["series"])
        out_plots.append(item)

    markers = []
    for cond, title, pos, shape, color, text in shapes:
        idx = np.flatnonzero(cond.to_numpy()[sl])
        for i in idx:
            markers.append({"time": times[i], "position": {"above": "aboveBar", "below": "belowBar"}.get(pos, "inBar"),
                            "shape": shape, "color": color, "text": text or ""})
    markers.sort(key=lambda m: m["time"])

    out_colors = None
    if bar_colors:
        col, brd = bar_colors[-1]
        col = col[sl]
        brd = brd[sl] if brd is not None else [None] * len(col)
        ok = lambda x: None if x is None or (isinstance(x, float) and x != x) or x == "" else str(x)
        out_colors = [[ok(a), ok(b)] if ok(a) else None for a, b in zip(col, brd)]

    def keep(objs, key):
        objs = [x for x in objs if x.get(key) is not None]
        return objs[-MAX_OBJECTS:]

    return {"title": meta["title"], "overlay": meta["overlay"], "precision": meta["precision"], "scale": meta["scale"],
            "showInputs": meta["showInputs"], "showValues": meta["showValues"], "help": meta["help"],
            "inputs": decl_inputs, "time": times, "plots": out_plots, "hlines": hlines, "markers": markers,
            "barcolors": out_colors, "boxes": keep(boxes, "l"), "labels": keep(labels, "t"), "bubbles": keep(bubbles, "t"), "lines": keep(lines, "t1"),
            "tables": tables, "profiles": profiles[-MAX_OBJECTS:], "vpspecs": vpspecs, "alerts": [a for a in alerts if a["t"] >= (times[0] if times else 0)][-50:]}


def _vp_ns():
    from . import volume_profile as _v
    return _Info({"build": _v.build, "session_profiles": _v.session_profiles, "range_profile": _v.range_profile,
                  "auto_anchored": _v.auto_anchored, "anchor_index": _v.anchor_index, "period_keys": _v.period_keys,
                  "version": _v.ALGO_VERSION})


def close_err(name):
    raise ValueError(f"unknown source '{name}'")


def _s_obj(x, like):
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=object)
    return np.asarray(x, dtype=object)
