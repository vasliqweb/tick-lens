"""NIFTY 50 market breadth from the local Breeze 1m candle cache (no extra API calls).

breadth_1m(index, start, end) -> DataFrame (UTC-naive 1m bar start index) with
  adv_open   : share of constituents trading above today's open (0..1)
  above_vwap : share above their own session VWAP (0..1)
  n          : stocks counted
Causal per minute: each stock contributes its latest close <= that minute (held up to 5 minutes).
Only cached days are used: data/Breeze/<STOCK>/1m/YYYY-MM-DD.csv (kept live by the index-volume keeper / tick recorder)."""
from __future__ import annotations
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent / "data" / "Breeze"
_cache: Dict[Tuple[str, str], Tuple[float, Optional[pd.DataFrame]]] = {}      # (index, day) -> (max mtime, frame)


def _members(index: str):
    from .breeze import NIFTY50_FALLBACK
    return {"NIFTY": NIFTY50_FALLBACK}.get(index.upper())


def _safe(name: str) -> str:
    from .candle_store import _safe as s
    return s(name)


def _day(index: str, day: date) -> Optional[pd.DataFrame]:
    hit = _cache.get((index, str(day)))
    if hit is not None and day < date.today() - timedelta(days=1):     # finished sessions never change: no disk checks
        return hit[1]
    files = [ROOT / _safe(s) / "1m" / f"{day}.csv" for s in _members(index)]
    files = [f for f in files if f.exists()]
    if len(files) < 25:
        _cache[(index, str(day))] = (0.0, None)
        return None
    mt = max(os.path.getmtime(f) for f in files)
    if hit and hit[0] >= mt:
        return hit[1]
    C, O, VW = {}, {}, {}
    for f in files:
        try:
            d = pd.read_csv(f)
        except Exception:
            continue
        if d.empty:
            continue
        d = d.drop_duplicates("time", keep="last").sort_values("time").set_index("time")
        ist = pd.DatetimeIndex(pd.to_datetime(d.index, unit="s", utc=True)).tz_convert("Asia/Kolkata")
        m = ist.hour * 60 + ist.minute
        d = d[(m >= 555) & (m < 915) & (ist.date == day)]            # only this file's own session
        if d.empty:
            continue
        tp = (d.high + d.low + d.close) / 3
        v = d.volume.clip(lower=0)
        C[f.parent.parent.name] = d.close
        O[f.parent.parent.name] = pd.Series(d.open.iloc[0], index=d.index)
        VW[f.parent.parent.name] = (tp * v).cumsum() / v.cumsum().replace(0, np.nan)
    if len(C) < 25:
        _cache[(index, str(day))] = (mt, None)
        return None
    c = pd.DataFrame(C).sort_index()
    idx = np.arange(c.index[0], c.index[-1] + 60, 60)
    c = c.reindex(idx).ffill(limit=5)
    o = pd.DataFrame(O).reindex(idx).ffill().bfill()
    vw = pd.DataFrame(VW).reindex(idx).ffill(limit=5)
    ok = c.notna()
    n = ok.sum(axis=1).replace(0, np.nan)
    out = pd.DataFrame({"adv_open": ((c > o) & ok).sum(axis=1) / n,
                        "above_vwap": ((c > vw) & ok).sum(axis=1) / n, "n": n})
    out.index = pd.to_datetime(out.index, unit="s")
    out = out[out.n >= 25]
    _cache[(index, str(day))] = (mt, out)
    return out


def breadth_1m(index: str, start: pd.Timestamp, end: pd.Timestamp) -> Optional[pd.DataFrame]:
    if not _members(index):
        return None
    parts, d = [], start.date()
    while d <= end.date():
        if d.weekday() < 5:
            x = _day(index, d)
            if x is not None:
                parts.append(x)
        d += timedelta(days=1)
    if not parts:
        return None
    out = pd.concat(parts)
    return out[~out.index.duplicated(keep="last")].sort_index()
