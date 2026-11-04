"""
Volume profile engine: Session, Session HD, Periodic, Visible Range, Fixed Range and Auto Anchored
volume profiles. Original implementation of the behaviour documented by TradingView
("Volume profile indicators: basic concepts"):

* Volume comes from lower-timeframe bars of the same symbol. Each (intra)bar's volume is spread over the
  price rows its high-low range covers, in proportion to the overlap (high == low -> one row).
* Up / down volume: close >= open is up volume, close < open is down volume. This is CANDLE DIRECTION,
  an estimate - not bid/ask (aggressor) delta.
* POC = row with the largest total volume (ties -> the row nearest the middle of the range, then lower).
* Value area: start at the POC; compare the next row above with the next row below and take the larger
  (equal volume -> the row closer to the POC, equal distance -> the row above); add it if it does not
  push the area past `va_pct` of total volume, otherwise stop. VAH / VAL = top / bottom of the area.
* Lower timeframe: the first of 1, 5, 15, 30, 60, 240 minutes (built from 1m) giving < 5000 bars for the
  profile's range; Periodic VP uses the chart-timeframe table instead. Never finer than the data we have.

Everything here is a deterministic function of the ordered input bars; nothing looks ahead.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ALGO_VERSION = "vp-1.1.0"
LAYOUTS = ("Number of Rows", "Ticks Per Row")
MAX_ROWS = 1000


def _grid(lo: float, hi: float, layout: str, size: float, mintick: float):
    """Row bottom + row height + row count for a price range."""
    mintick = mintick if mintick and mintick > 0 else 0.01
    if layout == "Ticks Per Row":
        step = max(1, int(size)) * mintick
        base = math.floor(lo / step + 1e-9) * step
        n = max(1, int(math.ceil((hi - base) / step - 1e-9)))
        if n > MAX_ROWS:                                      # keep it drawable
            step *= math.ceil(n / MAX_ROWS)
            base = math.floor(lo / step + 1e-9) * step
            n = max(1, int(math.ceil((hi - base) / step - 1e-9)))
        return base, step, n
    n = max(1, min(MAX_ROWS, int(size)))
    if hi <= lo:
        step = mintick
        return lo - step * (n // 2), step, n
    return lo, (hi - lo) / n, n


def bar_direction(o: np.ndarray, c: np.ndarray, prev_close: Optional[float] = None) -> np.ndarray:
    """+1 up / -1 down per bar: close >= open is up (TradingView rule). prev_close is unused (kept for API)."""
    return np.where(c >= o, 1.0, -1.0)


def distribute(h, l, v, base: float, step: float, n: int) -> np.ndarray:
    """(bars x rows) matrix of the volume each bar puts into each row (overlap-proportional)."""
    edges = base + step * np.arange(n + 1)
    lo_e, hi_e = edges[:-1][None, :], edges[1:][None, :]
    h = h[:, None]
    l = l[:, None]
    rng = h - l
    ov = np.clip(np.minimum(h, hi_e) - np.maximum(l, lo_e), 0, None)
    flat = rng[:, 0] <= 0
    w = np.divide(ov, rng, out=np.zeros_like(ov), where=rng > 0)
    if flat.any():                                            # zero-range bar: whole volume in its row
        k = np.clip(np.floor((l[flat, 0] - base) / step).astype(int), 0, n - 1)
        w[flat] = 0.0
        w[np.flatnonzero(flat), k] = 1.0
    # bars whose range touches the grid only on an edge (rounding) -> nearest row
    miss = (w.sum(axis=1) <= 0) & ~flat
    if miss.any():
        k = np.clip(np.floor(((h[miss, 0] + l[miss, 0]) / 2 - base) / step).astype(int), 0, n - 1)
        w[np.flatnonzero(miss), k] = 1.0
    s = w.sum(axis=1, keepdims=True)
    w = np.divide(w, s, out=np.zeros_like(w), where=s > 0)
    return w * v[:, None]


def value_area(tot: np.ndarray, va_pct: float):
    """(poc, lo_row, hi_row) row indices - single-row expansion from the POC (see module doc)."""
    n = len(tot)
    if n == 0 or tot.sum() <= 0:
        return None, None, None
    mx = tot.max()
    cand = np.flatnonzero(tot >= mx - 1e-12 * max(mx, 1))
    mid = (n - 1) / 2
    poc = int(min(cand, key=lambda k: (abs(k - mid), k)))
    left = tot.sum() * min(max(va_pct, 0.0), 100.0) / 100.0 - tot[poc]
    lo = hi = poc
    eps = 1e-9 * max(1.0, float(tot.sum()))
    while left > eps and (lo > 0 or hi < n - 1):
        up = tot[hi + 1] if hi < n - 1 else None
        dn = tot[lo - 1] if lo > 0 else None
        if dn is None or (up is not None and (up > dn or (up == dn and (hi + 1 - poc) <= (poc - lo + 1)))):
            v, side = up, 1
        else:
            v, side = dn, -1
        if v > left + eps:
            break
        left -= v
        if side > 0:
            hi += 1
        else:
            lo -= 1
    return poc, lo, hi


def build(bars: pd.DataFrame, rows_layout: str = "Number of Rows", row_size: float = 24, va_pct: float = 70.0,
          mintick: float = 0.01, prev_close: Optional[float] = None, use_ticks_when_flat: bool = True) -> Optional[Dict[str, Any]]:
    """Profile of `bars` (columns open/high/low/close/volume). Returns None for an empty input.

    When every bar has zero volume the profile is built from bar count (time at price) and
    flagged `volumeMode="bar-count"` so the UI can say so."""
    if bars is None or bars.empty:
        return None
    o, h, l, c = (bars[k].to_numpy(dtype="float64") for k in ("open", "high", "low", "close"))
    v = np.nan_to_num(bars["volume"].to_numpy(dtype="float64"), nan=0.0)
    ok = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)
    o, h, l, c, v = o[ok], h[ok], l[ok], c[ok], v[ok]
    if not len(o):
        return None
    vol_mode = "volume"
    if v.sum() <= 0:
        vol_mode = "bar-count"
        v = np.ones_like(v)
    lo_p, hi_p = float(l.min()), float(h.max())
    base, step, n = _grid(lo_p, hi_p, rows_layout, row_size, mintick)
    m = distribute(h, l, v, base, step, n)
    d = bar_direction(o, c, prev_close)
    up = m[d > 0].sum(axis=0)
    dn = m[d <= 0].sum(axis=0)
    tot = up + dn
    poc, vlo, vhi = value_area(tot, va_pct)
    r6 = lambda x: round(float(x), 6)
    return {"base": r6(base), "step": r6(step), "n": int(n),
            "up": [round(float(x), 3) for x in up], "dn": [round(float(x), 3) for x in dn],
            "poc": poc, "vaLo": vlo, "vaHi": vhi,
            "pocPrice": r6(base + step * (poc + 0.5)) if poc is not None else None,
            "vah": r6(base + step * (vhi + 1)) if vhi is not None else None,
            "val": r6(base + step * vlo) if vlo is not None else None,
            "high": r6(hi_p), "low": r6(lo_p),
            "total": round(float(tot.sum()), 3) if vol_mode == "volume" else 0.0,
            "upTotal": round(float(up.sum()), 3) if vol_mode == "volume" else 0.0,
            "dnTotal": round(float(dn.sum()), 3) if vol_mode == "volume" else 0.0,
            "bars": int(len(o)), "volumeMode": vol_mode, "lastClose": r6(c[-1])}


def _local(index: pd.DatetimeIndex, tz: str) -> pd.DatetimeIndex:
    try:
        return index.tz_localize("UTC").tz_convert(tz).tz_localize(None)
    except Exception:
        return index


def session_keys(index: pd.DatetimeIndex, tz: str, session: str, period: str) -> np.ndarray:
    """Group key per bar: trading day in the exchange timezone, ISO week, or month."""
    day = _local(index, tz).normalize()
    if period == "Week":
        day = day - pd.to_timedelta(day.dayofweek, unit="D")
    elif period == "Month":
        day = day.to_period("M").to_timestamp()
    return day.as_unit("s").asi8


def period_keys(index: pd.DatetimeIndex, tz: str, mult: int, unit: str) -> np.ndarray:
    """Periodic VP groups: `mult` x unit (Bar, Minute, Hour, Day, Week, Month), aligned to the start of each
    year and restarted every new year (TradingView behaviour). Day / Week count trading days / weeks with data."""
    mult = max(1, int(mult))
    lt = _local(index, tz)
    year = lt.year.to_numpy().astype("int64")
    if unit in ("Minute", "Hour"):
        m = mult * (60 if unit == "Hour" else 1)
        mins = ((lt - lt.to_period("Y").to_timestamp()).total_seconds() // 60).to_numpy().astype("int64")
        sub = mins // m
    elif unit == "Bar":
        sub = np.zeros(len(lt), dtype="int64")
        for y in np.unique(year):
            k = np.flatnonzero(year == y)
            sub[k] = np.arange(len(k)) // mult
    elif unit == "Day":
        day = lt.normalize().as_unit("s").asi8
        sub = np.zeros(len(lt), dtype="int64")
        for y in np.unique(year):
            k = np.flatnonzero(year == y)
            sub[k] = (np.unique(day[k], return_inverse=True)[1]) // mult
    elif unit == "Week":
        wk = (lt.normalize() - pd.to_timedelta(lt.dayofweek, unit="D")).as_unit("s").asi8
        sub = np.zeros(len(lt), dtype="int64")
        for y in np.unique(year):
            k = np.flatnonzero(year == y)
            sub[k] = (np.unique(wk[k], return_inverse=True)[1]) // mult
    else:                                                     # Month
        sub = (lt.month.to_numpy().astype("int64") - 1) // mult
    return year * 1_000_000 + sub


def anchor_index(df: pd.DataFrame, info: Dict[str, Any], tf_sec: int, mode: str, length: int) -> Tuple[int, str]:
    """Auto Anchored VP start bar. Auto: intraday -> Session, 1D -> Month, 2-10D -> Quarter, 11-60D -> Year,
    longer -> Decade. Highest High / Lowest Low / Highest Volume: that bar within the last `length` bars."""
    n = len(df)
    if mode == "Auto":
        d = tf_sec / 86400
        mode = "Session" if d < 1 else "Month" if d <= 1 else "Quarter" if d <= 10 else "Year" if d <= 60 else "Decade"
    if mode in ("Highest High", "Lowest Low", "Highest Volume"):
        w = df.iloc[max(0, n - int(length)):]
        col = {"Highest High": "high", "Lowest Low": "low", "Highest Volume": "volume"}[mode]
        a = w[col].to_numpy()
        k = int(np.argmin(a)) if mode == "Lowest Low" else int(np.argmax(a))   # earliest bar on ties
        return n - len(w) + k, mode
    lt = _local(df.index, info.get("timezone") or "UTC")
    if mode == "Session":
        key = lt.normalize()
    elif mode == "Week":
        key = lt.normalize() - pd.to_timedelta(lt.dayofweek, unit="D")
    elif mode == "Month":
        key = lt.to_period("M").to_timestamp()
    elif mode == "Quarter":
        key = lt.to_period("Q").to_timestamp()
    elif mode == "Year":
        key = lt.to_period("Y").to_timestamp()
    elif mode == "Decade":
        key = pd.to_datetime([f"{y // 10 * 10}-01-01" for y in lt.year])
    else:                                                     # Century
        key = pd.to_datetime([f"{y // 100 * 100}-01-01" for y in lt.year])
    key = pd.DatetimeIndex(key).as_unit("s").asi8
    return int(np.flatnonzero(key == key[-1])[0]), mode


def _is_proxy(vol_note: Optional[str]) -> bool:
    """ETF volume standing in for an index is a proxy; the sum of the index constituents' traded volume is not."""
    return bool(vol_note) and "constituent" not in vol_note


def _quality(p, vol_note):
    return "no-volume" if p["volumeMode"] != "volume" else ("proxy" if _is_proxy(vol_note) else "ok")


def evidence(p: Dict[str, Any], res: str, va_pct: float, vol_note: Optional[str]) -> List[Dict[str, Any]]:
    ev = [
        {"metric": "POC", "value": p["pocPrice"], "level": "Derived", "rule": "row with max volume"},
        {"metric": "VAH", "value": p["vah"], "level": "Derived", "rule": f"{va_pct:g}% value area, single-row expansion from POC"},
        {"metric": "VAL", "value": p["val"], "level": "Derived", "rule": f"{va_pct:g}% value area, single-row expansion from POC"},
        {"metric": "Total volume", "value": p["total"], "level": "Estimated" if _is_proxy(vol_note) else ("Derived" if vol_note else "Observed"),
         "source": vol_note or "exchange-reported volume"},
        {"metric": "Up/Down split", "value": [p["upTotal"], p["dnTotal"]], "level": "Estimated",
         "rule": "candle direction of each intrabar (not bid/ask delta)"},
        {"metric": "Resolution", "value": res, "level": "Observed"},
    ]
    return ev


def limitations(p: Dict[str, Any], res: str, chart_tf: int, vol_note: Optional[str]) -> List[str]:
    out = ["Up/down volume is a candle-direction estimate, not aggressor (bid/ask) delta.",
           "Volume inside each bar is assumed uniform across its high-low range."]
    if res == "chart":
        out.append(f"Built from chart bars ({chart_tf // 60}m): lower-timeframe data unavailable for this range, so row detail is coarse.")
    if p["volumeMode"] == "bar-count":
        out.append("Instrument reports no volume: histogram shows TIME AT PRICE (bar count), not volume.")
    if _is_proxy(vol_note):
        out.append(f"Volume is a proxy: {vol_note}.")
    elif vol_note:
        out.append(f"Index volume = {vol_note}.")
    return out


LTF_SEQ = (1, 5, 15, 30, 60, 240)          # minutes, tried in order until the range has < LTF_MAX_BARS bars
LTF_MAX_BARS = 5000
# Periodic VP: chart timeframe (minutes, upper bound) -> lower timeframe (minutes)
PERIODIC_LTF = ((4, 1), (15, 1), (30, 5), (60, 10), (120, 15), (240, 30), (10**9, 60))


def resample(bars: pd.DataFrame, minutes: int, origin: pd.Timestamp) -> pd.DataFrame:
    if minutes <= 1 or bars.empty:
        return bars
    r = bars.resample(f"{int(minutes)}min", origin=origin, label="left", closed="left")
    out = pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(), "low": r["low"].min(),
                        "close": r["close"].last(), "volume": r["volume"].sum()})
    return out.dropna(subset=["open"])


def _pick_bars(chart: pd.DataFrame, ib: Optional[pd.DataFrame], t0: pd.Timestamp, t1: pd.Timestamp,
               chart_tf: int = 0, rule: str = "auto"):
    """Bars for the profile over [t0, t1): 1m intrabars (resampled to the TradingView-style lower timeframe)
    when they cover the whole range and carry volume like the chart; else the chart bars.
    rule: "auto" = first of LTF_SEQ with < 5000 bars, "periodic" = PERIODIC_LTF table, "fine" = 1m as is.
    Returns (frame, resolution label)."""
    cb = chart[(chart.index >= t0) & (chart.index < t1)]
    if ib is not None and len(ib) and len(cb):
        sub = ib[(ib.index >= t0) & (ib.index < t1)]
        covers = len(sub) > 0 and ib.index[0] <= cb.index[0]
        vol_ok = sub["volume"].sum() > 0 or cb["volume"].sum() <= 0
        if covers and vol_ok:
            base = int((sub.index[1] - sub.index[0]).total_seconds() // 60) if len(sub) > 1 else 1
            base = max(1, min(base, int(np.median(np.diff(sub.index.asi8)) // 60 // 10**9) if len(sub) > 2 else base))
            if rule == "periodic":
                ltf = next(m for lim, m in PERIODIC_LTF if chart_tf // 60 <= lim)
            elif rule == "fine":
                ltf = base
            else:
                ltf = next((m for m in LTF_SEQ if len(sub) * base / m < LTF_MAX_BARS), LTF_SEQ[-1])
            ltf = max(ltf, base)
            if chart_tf and ltf * 60 >= chart_tf:
                return cb, "chart"
            return resample(sub, ltf, t0) if ltf > base else sub, f"{ltf}m intrabars"
    return cb, "chart"


def extend_ends(df: pd.DataFrame, p: Dict[str, Any], keys=("pocPrice", "vah", "val")) -> Dict[str, Optional[int]]:
    """For each level: time of the first chart bar after the profile whose high-low range crosses it
    ("extend right until it crosses any bar"); None = not crossed yet (runs to the last bar)."""
    out = {}
    after = df[df.index > pd.Timestamp(p["r"], unit="s")]
    hi, lo = after["high"].to_numpy(), after["low"].to_numpy()
    for k in keys:
        x = p.get(k)
        if x is None or not len(after):
            out[k] = None
            continue
        hit = np.flatnonzero((lo <= x) & (hi >= x))
        out[k] = int(after.index[hit[0]].value // 10**9) if len(hit) else None
    return out


_DEV_CACHE: "OrderedDict[str, tuple]" = OrderedDict()


def _developing(bars: pd.DataFrame, cut: np.ndarray, rows_layout, row_size, va_pct, mintick, prev_close):
    """Developing POC/VAH/VAL at each cut (number of intrabars closed by the end of each chart bar).
    Memoised on the exact input, so closed sessions are computed once and live updates only redo today."""
    h = hashlib.sha1()
    h.update(bars.index.asi8.tobytes())
    h.update(bars[["open", "high", "low", "close", "volume"]].to_numpy(dtype="float64").tobytes())
    h.update(np.asarray(cut, dtype="int64").tobytes())
    h.update(repr((rows_layout, row_size, va_pct, mintick, prev_close)).encode())
    key = h.hexdigest()
    hit = _DEV_CACHE.get(key)
    if hit is not None:
        _DEV_CACHE.move_to_end(key)
        return hit
    m = len(cut)
    poc, vah, val = np.full(m, np.nan), np.full(m, np.nan), np.full(m, np.nan)
    memo = {}
    for k in range(m):
        c = int(cut[k])
        if not c:
            continue
        if c not in memo:
            memo[c] = build(bars.iloc[:c], rows_layout, row_size, va_pct, mintick, prev_close)
        q = memo[c]
        if q and q["poc"] is not None:
            poc[k], vah[k], val[k] = q["pocPrice"], q["vah"], q["val"]
    res = (poc, vah, val)
    _DEV_CACHE[key] = res
    if len(_DEV_CACHE) > 400:
        _DEV_CACHE.popitem(last=False)
    return res


def _session_closed(first: pd.Timestamp, last_bar: pd.Timestamp, tf_sec: int, info: Dict[str, Any], period: str) -> bool:
    """True once the trading session of the last group is over: its last bar closed at/after the session end,
    or (live, not replay) the wall clock `info["now"]` is past the session end. 24x7 / week / month: never."""
    m = re.match(r"(\d{2})(\d{2})-(\d{2})(\d{2})", str(info.get("session") or ""))
    if period != "Session" or info.get("is24x7") or not m:
        return False
    tz = info.get("timezone") or "UTC"
    try:
        day = first.tz_localize("UTC").tz_convert(tz).normalize()
        end = day + pd.Timedelta(hours=int(m.group(3)), minutes=int(m.group(4)))
        if int(m.group(3)) * 60 + int(m.group(4)) <= int(m.group(1)) * 60 + int(m.group(2)):
            end += pd.Timedelta(days=1)                       # overnight session (MCX 0900-2330 is same-day)
        end_utc = end.tz_convert("UTC").tz_localize(None)
    except Exception:
        return False
    if last_bar + pd.Timedelta(seconds=tf_sec) >= end_utc:
        return True
    now = info.get("now")
    return now is not None and pd.Timestamp(float(now), unit="s") >= end_utc


def session_profiles(df: pd.DataFrame, ib: Optional[pd.DataFrame], info: Dict[str, Any], tf_sec: int,
                     period: str = "Session", rows_layout: str = "Number of Rows", row_size: float = 24,
                     va_pct: float = 70.0, max_profiles: int = 60, dev: bool = False,
                     vol_note: Optional[str] = None, mult: int = 1, unit: str = "Day", hd: bool = False,
                     kind: str = "svp") -> Dict[str, Any]:
    """One profile per session / week / month of `df` (chart bars, UTC index).

    The last group is PROVISIONAL (still developing); earlier groups are CONFIRMED and never change
    because each is a pure function of its own bars. With dev=True also returns causal developing
    POC/VAH/VAL per chart bar (bar i only sees intrabars that closed by the end of bar i)."""
    n = len(df)
    out = {"profiles": [], "devPoc": np.full(n, np.nan), "devVah": np.full(n, np.nan), "devVal": np.full(n, np.nan)}
    if n == 0:
        return out
    mintick = float(info.get("mintick") or 0.01)
    tz = info.get("timezone") or "UTC"
    keys = period_keys(df.index, tz, mult, unit) if period == "Periodic" else session_keys(df.index, tz, info.get("session") or "", period)
    rule = "periodic" if period == "Periodic" else "auto"
    if hd:                                                    # HD: finest rows; the chart merges them to fit the zoom
        rows_layout, row_size = "Ticks Per Row", 1
    starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    ends = np.r_[starts[1:], n]
    first = max(0, len(starts) - int(max_profiles))
    bar_td = pd.Timedelta(seconds=tf_sec)
    prev_close = None
    for g, (s, e) in enumerate(zip(starts, ends)):
        if g < first:
            prev_close = float(df["close"].iloc[e - 1])
            continue
        t0, t1 = df.index[s], df.index[e - 1] + bar_td
        bars, res = _pick_bars(df, ib, t0, t1, tf_sec, rule)
        p = build(bars, rows_layout, row_size, va_pct, mintick, prev_close)
        last = g == len(starts) - 1 and not _session_closed(df.index[s], df.index[e - 1], tf_sec, info,
                                                            "Session" if period == "Session" or (period == "Periodic" and unit == "Day" and mult == 1) else period)
        if p:
            known = int(df.index[e - 1].value // 10**9) + (0 if last else tf_sec)
            p.update({
                "id": f"{kind}-{period[0]}-{int(t0.value // 10**9)}", "kind": kind, "period": period, "hd": hd,
                "periodLabel": f"{mult} {unit}" if period == "Periodic" else period,
                "l": int(t0.value // 10**9), "r": int(df.index[e - 1].value // 10**9),
                "eventTime": int(t0.value // 10**9), "knownAt": known,
                "status": "PROVISIONAL" if last else "CONFIRMED", "res": res,
                "evidence": evidence(p, res, va_pct, vol_note), "limitations": limitations(p, res, tf_sec, vol_note),
                "invalidationRule": "None for history (fixed once the session closes). Developing profile changes until then.",
                "algorithmVersion": ALGO_VERSION, "volNote": vol_note,
                "dataQuality": _quality(p, vol_note),
            })
            p["ends"] = extend_ends(df, p)
            p["vaPct"] = va_pct
            out["profiles"].append(p)
        if dev:
            cut = np.searchsorted(bars.index.asi8, (df.index[s:e] + bar_td).asi8, side="left")
            dl, ds = ("Number of Rows", 100) if hd else (rows_layout, row_size)   # HD: 100-row developing (speed)
            dv = _developing(bars, cut, dl, ds, va_pct, mintick, prev_close)
            out["devPoc"][s:e], out["devVah"][s:e], out["devVal"][s:e] = dv
        prev_close = float(df["close"].iloc[e - 1])
    return out


def range_profile(bars: pd.DataFrame, t_from: int, t_to: int, tf_sec: int, last_bar: int, rows_layout: str,
                  row_size: float, va_pct: float, mintick: float, res: str, vol_note: Optional[str]) -> Optional[Dict[str, Any]]:
    """Fixed range profile over [t_from, t_to + tf) - `bars` already sliced to that range."""
    p = build(bars, rows_layout, row_size, va_pct, mintick)
    if not p:
        return None
    developing_ = t_to >= last_bar
    p.update({"kind": "frvp", "l": int(t_from), "r": int(t_to), "eventTime": int(t_from),
              "knownAt": int(min(t_to, last_bar)) + (0 if developing_ else tf_sec),
              "status": "PROVISIONAL" if developing_ else "CONFIRMED", "res": res,
              "evidence": evidence(p, res, va_pct, vol_note), "limitations": limitations(p, res, tf_sec, vol_note),
              "invalidationRule": "Fixed once the range end bar has closed; a range that includes the forming bar is developing.",
              "algorithmVersion": ALGO_VERSION, "volNote": vol_note,
              "dataQuality": _quality(p, vol_note)})
    return p


def visible_range(bars: pd.DataFrame, t_from: int, t_to: int, tf_sec: int, last_bar: int, rows_layout: str,
                  row_size: float, va_pct: float, mintick: float, res: str, vol_note: Optional[str]):
    p = range_profile(bars, t_from, t_to, tf_sec, last_bar, rows_layout, row_size, va_pct, mintick, res, vol_note)
    if p:
        p["kind"] = "vrvp"
        p["invalidationRule"] = "Recalculated whenever the visible range changes; developing while the forming bar is visible."
    return p


def auto_anchored(df: pd.DataFrame, ib: Optional[pd.DataFrame], info: Dict[str, Any], tf_sec: int,
                  mode: str = "Auto", length: int = 20, rows_layout: str = "Number of Rows", row_size: float = 24,
                  va_pct: float = 70.0, dev: bool = False, vol_note: Optional[str] = None) -> Dict[str, Any]:
    """Auto Anchored VP: one profile from the anchor bar to the last bar (always PROVISIONAL: it grows with
    every bar, and length-based anchors can move to a newer bar)."""
    n = len(df)
    out = {"profiles": [], "devPoc": np.full(n, np.nan), "devVah": np.full(n, np.nan), "devVal": np.full(n, np.nan)}
    if n == 0:
        return out
    a, used = anchor_index(df, info, tf_sec, mode, length)
    mintick = float(info.get("mintick") or 0.01)
    t0, t1 = df.index[a], df.index[-1] + pd.Timedelta(seconds=tf_sec)
    bars, res = _pick_bars(df, ib, t0, t1, tf_sec, "auto")
    p = build(bars, rows_layout, row_size, va_pct, mintick)
    if p:
        p.update({"id": f"aavp-{int(t0.value // 10**9)}", "kind": "aavp", "period": used, "anchorMode": mode,
                  "periodLabel": f"Anchor: {used}" + (f" ({int(length)} bars)" if used in ("Highest High", "Lowest Low", "Highest Volume") else ""),
                  "l": int(t0.value // 10**9), "r": int(df.index[-1].value // 10**9), "eventTime": int(t0.value // 10**9),
                  "knownAt": int(df.index[-1].value // 10**9), "status": "PROVISIONAL", "res": res,
                  "evidence": evidence(p, res, va_pct, vol_note), "limitations": limitations(p, res, tf_sec, vol_note) +
                  (["Length-based anchor: the start bar moves when a new extreme appears in the window."]
                   if used in ("Highest High", "Lowest Low", "Highest Volume") else []),
                  "invalidationRule": "Developing: recalculated on every bar from the current anchor.",
                  "algorithmVersion": ALGO_VERSION, "volNote": vol_note, "dataQuality": _quality(p, vol_note)})
        out["profiles"].append(p)
        if dev:
            cut = np.searchsorted(bars.index.asi8, (df.index[a:] + pd.Timedelta(seconds=tf_sec)).asi8, side="left")
            dv = _developing(bars, cut, rows_layout, row_size, va_pct, mintick, None)
            out["devPoc"][a:], out["devVah"][a:], out["devVal"][a:] = dv
    return out
