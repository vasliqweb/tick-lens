"""Money flow (rupee value bought vs sold) per 1-minute bar, from the local Breeze cache. mf-0.1.0

Per stock-minute, two methods (evidence level is kept per minute in `src`):
  * TICK (src=1, Observed + classified): raw L1 snapshots data/Breeze/<SYM>/ticks/<day>.csv.
    Traded qty = increase of the running max of total traded qty (ttq) between snapshots (rows repeat; a stale
    snapshot with a lower ttq is ignored, so the day's sum matches exchange volume). Side by the quote rule against the
    PREVIOUS snapshot's bid/ask (last >= ask -> buy, last <= bid -> sell), else the tick rule (up-tick buy,
    down-tick sell, unchanged -> previous side). Value = qty x last price. Snapshots are not every trade, so a
    snapshot gap can merge trades of both sides: classification is an estimate of aggressor side, not exchange-flagged.
  * CANDLE (src=0, Estimated): 1m OHLCV close-location split. clv = ((c-l)-(h-c))/(h-l);
    buy = value x (1+clv)/2, sell = value x (1-clv)/2, value = volume x (h+l+c)/3.
A minute uses TICK when that stock's tick file has trades in that minute, else CANDLE.
Only continuous trading 09:15-15:15 IST is counted (pre-open and the 15:15-15:30 closing auction have no
aggressor side; their volume is left out).

flow_1m(symbol, start, end) -> DataFrame (UTC-naive 1m bar start index):
  buy, sell, net (Rs), tick_share (0..1 of value classified from ticks), n (stocks counted),
  pos_share (index only: share of stocks whose session net flow so far is > 0; NaN for a single stock)
Index symbols (NIFTY) = sum over NIFTY 50 constituents. Causal per minute; nothing is filled forward in time."""
from __future__ import annotations
import os
import time as _time
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd

VERSION = "mf-0.1.0"
ROOT = Path(__file__).resolve().parent.parent / "data" / "Breeze"
IST = 19800
S0, S1 = 555, 915                       # 09:15 .. 15:15 IST: 15:15-15:30 is the closing auction (crossed book, no aggressor side)
_cache: Dict[Tuple[str, str], Tuple[float, Optional[pd.DataFrame]]] = {}
LIVE_TTL = 60.0                         # today: re-read growing tick files at most once a minute


def _safe(name: str) -> str:
    from .candle_store import _safe as s
    return s(name)


def members(symbol: str):
    from .breeze import NIFTY50_FALLBACK
    s = (symbol or "").upper()
    if s == "NIFTY" or (s.startswith("NIFTY ") and s.endswith(" FUT")):
        return list(NIFTY50_FALLBACK)
    return None


def _minute_ist(t: np.ndarray) -> np.ndarray:
    return ((t.astype(np.int64) + IST) % 86400) // 60


def tick_flow(path: Path) -> Optional[pd.DataFrame]:
    """Classified tick flow of one stock-day -> DataFrame(buy, sell) indexed by 1m start (epoch s)."""
    try:
        d = pd.read_csv(path, usecols=["time", "last", "ttq", "bid", "ask"])
    except Exception:
        return None
    d = d.dropna(subset=["time", "last", "ttq"])
    if len(d) < 2:
        return None
    t = d.time.to_numpy(float)
    order = np.argsort(t, kind="stable")
    t, px, q = t[order], d["last"].to_numpy(float)[order], d.ttq.to_numpy(float)[order]
    bid, ask = d.bid.to_numpy(float)[order], d.ask.to_numpy(float)[order]
    q = np.maximum.accumulate(q)          # ttq can jump back (out-of-order / stale snapshots): never count twice
    dq = np.diff(q, prepend=q[0])
    pb, pa = np.roll(bid, 1), np.roll(ask, 1)
    pb[0], pa[0] = np.nan, np.nan
    side = np.zeros(len(px))
    good = (pa > 0) & (pb > 0) & (pa > pb)      # crossed / locked book (auctions): no aggressor side
    side[good & (px >= pa)] = 1
    side[good & (px <= pb)] = -1
    # tick rule where the quote rule is undecided
    dp = np.sign(np.diff(px, prepend=px[0]))
    tr = pd.Series(np.where(dp == 0, np.nan, dp)).ffill().fillna(0).to_numpy()
    side = np.where(side == 0, tr, side)
    m = _minute_ist(t)
    ok = (dq > 0) & (m >= S0) & (m < S1)
    if not ok.any():
        return None
    val = dq[ok] * px[ok]
    key = (t[ok] // 60).astype(np.int64) * 60
    g = pd.DataFrame({"k": key, "buy": np.where(side[ok] > 0, val, 0.0),
                      "sell": np.where(side[ok] < 0, val, 0.0),
                      "unk": np.where(side[ok] == 0, val, 0.0)}).groupby("k").sum()
    unk = g.pop("unk") / 2                 # unknown side: split evenly (rare: first trades of the day)
    g["buy"] += unk
    g["sell"] += unk
    return g


def candle_flow(path: Path, day: date) -> Optional[pd.DataFrame]:
    try:
        d = pd.read_csv(path)
    except Exception:
        return None
    if d.empty:
        return None
    d = d.drop_duplicates("time", keep="last").sort_values("time")
    t = d.time.to_numpy(np.int64)
    m = _minute_ist(t)
    dd = pd.to_datetime(t + IST, unit="s").date
    k = (m >= S0) & (m < S1) & (dd == day)
    d = d[k]
    if d.empty:
        return None
    h, l, c = d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float)
    v = np.clip(np.nan_to_num(d.volume.to_numpy(float)), 0, None)
    rng = h - l
    clv = np.where(rng > 0, ((c - l) - (h - c)) / np.where(rng > 0, rng, 1), 0.0)
    val = v * (h + l + c) / 3
    return pd.DataFrame({"buy": val * (1 + clv) / 2, "sell": val * (1 - clv) / 2}, index=d.time.to_numpy(np.int64))


def stock_day(sym: str, day: date) -> Optional[pd.DataFrame]:
    """One stock-day: DataFrame(buy, sell, src) by 1m start epoch s."""
    base = ROOT / _safe(sym)
    c = candle_flow(base / "1m" / f"{day}.csv", day) if (base / "1m" / f"{day}.csv").exists() else None
    tk = tick_flow(base / "ticks" / f"{day}.csv") if (base / "ticks" / f"{day}.csv").exists() else None
    if c is None and tk is None:
        return None
    if tk is None:
        out = c.assign(src=0.0)
    elif c is None:
        out = tk.assign(src=1.0)
    else:
        cc = c.loc[~c.index.isin(tk.index)].assign(src=0.0)
        out = pd.concat([tk.assign(src=1.0), cc]).sort_index()
    return out


def _mtime(sym: str, day: date) -> float:
    base = ROOT / _safe(sym)
    mt = 0.0
    for p in (base / "1m" / f"{day}.csv", base / "ticks" / f"{day}.csv"):
        try:
            mt = max(mt, os.path.getmtime(p))
        except OSError:
            pass
    return mt


def _day(symbol: str, day: date) -> Optional[pd.DataFrame]:
    key = (symbol.upper(), str(day))
    hit = _cache.get(key)
    finished = day < date.today()
    if hit is not None and (finished and hit[0] > 0 or _time.time() - hit[0] < LIVE_TTL and not finished):
        return hit[1]
    mem = members(symbol)
    syms = mem if mem else [symbol]
    B, S, SRC, NET = {}, {}, {}, {}
    for s in syms:
        x = stock_day(s, day)
        if x is None or x.empty:
            continue
        B[s], S[s], SRC[s] = x.buy, x.sell, x.src * (x.buy + x.sell)
    if not B or (mem and len(B) < 25):
        _cache[key] = (_time.time(), None)
        return None
    b, s_ = pd.DataFrame(B).sort_index(), pd.DataFrame(S).sort_index()
    idx = np.arange(b.index[0], b.index[-1] + 60, 60)
    b, s_ = b.reindex(idx), s_.reindex(idx)
    src = pd.DataFrame(SRC).reindex(idx).fillna(0).sum(axis=1)
    net_each = (b.fillna(0) - s_.fillna(0))
    out = pd.DataFrame({"buy": b.sum(axis=1), "sell": s_.sum(axis=1)})
    out["net"] = out.buy - out.sell
    tot = (out.buy + out.sell).replace(0, np.nan)
    out["tick_share"] = (src / tot).clip(0, 1)
    out["n"] = b.notna().sum(axis=1)
    if mem:
        cum = net_each.cumsum()
        seen = b.notna().cumsum() > 0
        out["pos_share"] = ((cum > 0) & seen).sum(axis=1) / seen.sum(axis=1).replace(0, np.nan)
    else:
        out["pos_share"] = np.nan
    out.index = pd.to_datetime(out.index, unit="s")
    _cache[key] = (_time.time(), out)
    return out


def flow_1m(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> Optional[pd.DataFrame]:
    parts, d = [], (start + pd.Timedelta(seconds=IST)).date()
    last = (end + pd.Timedelta(seconds=IST)).date()
    while d <= last:
        if d.weekday() < 5:
            x = _day(symbol, d)
            if x is not None:
                parts.append(x)
        d += timedelta(days=1)
    if not parts:
        return None
    out = pd.concat(parts)
    return out[~out.index.duplicated(keep="last")].sort_index()
