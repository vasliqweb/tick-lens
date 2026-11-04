"""
Local 1-minute candle store: data/<Source>/<Symbol>/1m/YYYY-MM-DD.csv (UTC epoch seconds, OHLCV).

Intraday charts are built from these files; only days not on disk (and today's tail) are fetched
from the source. Raw candles are stored as the source sends them (session filters apply when served).

  data/
    Breeze/NIFTY/1m/2026-10-30.csv
    TV/NSE_NIFTY/1m/...            (":" is not allowed in Windows folder names)
    YAHOO/RELIANCE.NS/1m/...
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

log = logging.getLogger("ltv.store")
ROOT = Path(__file__).resolve().parent.parent / "data"
COLS = ["open", "high", "low", "close", "volume"]
FOLDER = {"breeze": "Breeze", "tv": "TV", "yf": "YAHOO", "sim": "SIM"}
# timeframes built from 1m candles, and the calendar days shown on first load / added per scroll-back
CACHED_TF = {60: 4, 180: 7, 300: 10, 900: 25}
# how far back each source can serve 1m candles (calendar days); None = no fixed limit
REACH = {"yf": 29, "tv": None, "breeze": None, "sim": 120}
from datetime import time as _dtime
SESSION_END_UTC = {"breeze": _dtime(10, 15)}   # 15:45 IST: NSE cash and F&O have closed
TODAY_TTL = 45.0          # seconds today's candles are reused before asking the source again
_EMPTY = pd.DataFrame(columns=COLS, dtype="float64", index=pd.DatetimeIndex([]))


_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def file_lock(p) -> threading.Lock:
    """One lock per day file: writes run in worker threads (off the event loop) and must not interleave."""
    k = str(p)
    with _LOCKS_GUARD:
        lk = _LOCKS.get(k)
        if lk is None:
            lk = _LOCKS[k] = threading.Lock()
        return lk


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip(". ") or "_"


def _utc_day(ts: pd.Timestamp) -> date:
    return ts.date()


class CandleStore:
    _locks: Dict[str, asyncio.Lock] = {}
    _fetched: Dict[str, float] = {}      # dir -> when today's candles were last fetched (file mtime also changes
                                         # when the index-volume keeper writes volume, so it can't be the TTL clock)

    def __init__(self, source: str, folder_name: str, fetch: Callable):
        """fetch(start: date, end: date) -> 1m DataFrame (UTC-naive index) covering those UTC days."""
        self.source = source
        self.dir = ROOT / FOLDER.get(source, source) / _safe(folder_name) / "1m"
        self.meta_file = self.dir.parent / "meta.json"
        self.fetch = fetch
        self.lock = self._locks.setdefault(str(self.dir), asyncio.Lock())
        try:
            self.meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
        except Exception:
            self.meta = {}
        self.meta.setdefault("empty", [])          # past days the source had nothing for (holidays, weekends)
        self.meta.setdefault("done", [])           # past days fetched after they ended (complete on disk)

    # ------------------------------------------------------------ disk
    def _path(self, d: date) -> Path:
        return self.dir / f"{d.isoformat()}.csv"

    def _save_meta(self):
        """Merged with what is on disk: several store instances (charts, index-volume keeper) share one meta.json."""
        try:
            disk = json.loads(self.meta_file.read_text(encoding="utf-8"))
        except Exception:
            disk = {}
        for k, v in disk.items():
            if k == "ivol":
                self.meta["ivol"] = sorted(set(v) | set(self.meta.get("ivol", [])))
            elif k not in self.meta or k == "ivol_live":     # written by the index-volume keeper only
                self.meta[k] = v
        self.meta_file.parent.mkdir(parents=True, exist_ok=True)
        self.meta_file.write_text(json.dumps(self.meta), encoding="utf-8")

    def _read_day(self, d: date) -> pd.DataFrame:
        p = self._path(d)
        if not p.exists():
            return _EMPTY
        try:
            df = pd.read_csv(p)
        except Exception:
            return _EMPTY
        df.index = pd.to_datetime(df.pop("time"), unit="s")
        return df[COLS].astype("float64")

    def _write_day(self, d: date, df: pd.DataFrame):
        with file_lock(self._path(d)):
            self._write_day_locked(d, df)

    def _write_day_locked(self, d: date, df: pd.DataFrame):
        old = self._read_day(d)
        if len(old):
            if len(df) and not (df["volume"] > 0).any() and (old["volume"] > 0).any():
                # index candles come with zero volume: keep the summed constituent volume already in the file
                df = df.assign(volume=old["volume"].reindex(df.index).fillna(0.0).to_numpy())
            df = pd.concat([old, df])
            df = df[~df.index.duplicated(keep="last")]
        df = df.sort_index()
        self.dir.mkdir(parents=True, exist_ok=True)
        out = df[COLS].copy()
        out.insert(0, "time", df.index.as_unit("s").asi8)
        tmp = self._path(d).with_suffix(".tmp")
        out.to_csv(tmp, index=False, float_format="%.6g")
        tmp.replace(self._path(d))

    def _has(self, d: date) -> bool:
        k = d.isoformat()
        return k in self.meta["done"] or k in self.meta["empty"]

    @property
    def floor(self) -> Optional[date]:
        """Oldest day the source can still give (None = unknown)."""
        f = self.meta.get("floor")
        reach = REACH.get(self.source)
        lim = (date.today() - timedelta(days=reach)) if reach else None
        f = date.fromisoformat(f) if f else None
        return max(x for x in (f, lim) if x) if (f or lim) else None

    # ------------------------------------------------------------ public
    def read(self, start: date, end: date) -> pd.DataFrame:
        parts = [self._read_day(start + timedelta(days=i)) for i in range((end - start).days + 1)]
        parts = [p for p in parts if len(p)]
        return pd.concat(parts).sort_index() if parts else _EMPTY

    async def ensure(self, start: date, end: Optional[date] = None) -> pd.DataFrame:
        """1m candles for UTC days start..end (default today), fetching only what is not on disk."""
        today = datetime.now(timezone.utc).date()
        end = min(end or today, today)
        async with self.lock:
            fl = self.floor
            if fl and start < fl:
                start = fl
            missing = [start + timedelta(days=i) for i in range((end - start).days + 1)]
            missing = [d for d in missing if d >= today or not self._has(d)]
            if end >= today and self._path(today).exists():
                mt = self._path(today).stat().st_mtime
                fetched = self._fetched.get(str(self.dir), 0.0)   # this app run; ticks/volume writes also touch the file
                closed = SESSION_END_UTC.get(self.source)   # Breeze/NSE: a file written after the close is final for the day
                after_close = closed is not None and (fetched or mt) >= datetime.combine(today, closed, tzinfo=timezone.utc).timestamp()
                if after_close or time.time() - fetched < TODAY_TTL:
                    missing = [d for d in missing if d != today]
            for a, b in _runs(missing):
                await self._fetch_range(a, b, today)
            return await asyncio.to_thread(self.read, start, end)     # disk I/O off the event loop (live ticks)

    async def _fetch_range(self, a: date, b: date, today: date):
        try:
            df = await self.fetch(a, b)
        except Exception as e:
            log.warning("1m fetch %s %s..%s failed: %s", self.dir.parent.name, a, b, e)
            raise
        df = df[df.index >= pd.Timestamp(a)] if len(df) else df
        if b >= today:
            self._fetched[str(self.dir)] = time.time()
        got = set()
        if len(df):
            def write():
                for d, part in df.groupby(df.index.date):
                    self._write_day(d, part)
                    got.add(d)
            await asyncio.to_thread(write)
        first = min(got) if got else None
        changed = False
        for d in sorted(got | {a + timedelta(days=i) for i in range((b - a).days + 1)}):
            if d >= today:
                continue                              # today is still forming
            k = d.isoformat()
            lst = self.meta["done"] if d in got else self.meta["empty"]
            if k not in lst:
                lst.append(k)
                changed = True
        # nothing at all in an old range, or data starts later than asked: the source has no older candles
        if (not got and b < today - timedelta(days=7)) or (first and first > a + timedelta(days=6)):
            fl = (first or b + timedelta(days=1)).isoformat()
            if self.meta.get("floor", "") < fl:
                self.meta["floor"] = fl
                changed = True
        if changed:
            self.meta["empty"] = sorted(set(self.meta["empty"]))[-4000:]
            self.meta["done"] = sorted(set(self.meta["done"]))
            self._save_meta()

    def oldest(self) -> Optional[date]:
        days = sorted(p.stem for p in self.dir.glob("*.csv")) if self.dir.exists() else []
        return date.fromisoformat(days[0]) if days else None


def _runs(days: List[date]) -> List[Tuple[date, date]]:
    out: List[Tuple[date, date]] = []
    for d in sorted(days):
        if out and (d - out[-1][1]).days == 1:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def to_tf(df: pd.DataFrame, tf: int) -> pd.DataFrame:
    """1m -> tf candles (bins on the UTC epoch grid, which matches 09:15 IST for 3/5/15m)."""
    if tf == 60 or df.empty:
        return df
    return df.resample(f"{tf}s", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


# ------------------------------------------------------------ per-source 1m fetchers
def _breeze_fetch(symbol: str):
    from .breeze import BreezeHub, MAX_ROWS, ROWS_PER_DAY
    hub = BreezeHub.get()
    span = max(1, int(MAX_ROWS / ROWS_PER_DAY[60] * 0.95))     # days per request

    async def fetch(a: date, b: date) -> pd.DataFrame:
        info = await hub.resolve(symbol)
        parts, d = [], a
        while d <= b:
            e = min(b, d + timedelta(days=span - 1))
            parts.append(await hub._call_hist(info["isec"], "1minute", d, e, info.get("fno")))
            d = e + timedelta(days=1)
        parts = [p for p in parts if len(p)]
        return pd.concat(parts).sort_index() if parts else _EMPTY
    return fetch


def _yf_fetch(ticker: str):
    async def fetch(a: date, b: date) -> pd.DataFrame:
        import yfinance as yf
        from .data_sources import _normalize
        parts, d = [], a
        while d <= b:                                         # Yahoo serves 1m in windows of up to 8 days
            e = min(b, d + timedelta(days=6))
            raw = await asyncio.to_thread(yf.Ticker(ticker).history, start=d.isoformat(),
                                          end=(e + timedelta(days=1)).isoformat(), interval="1m", auto_adjust=False)
            if len(raw):
                parts.append(_normalize(raw))
            d = e + timedelta(days=1)
        return pd.concat(parts).sort_index() if parts else _EMPTY
    return fetch


def _tv_fetch(ticker: str):
    async def fetch(a: date, b: date) -> pd.DataFrame:
        from .tradingview import fetch_bars
        days = (datetime.now(timezone.utc).date() - a).days + 1
        n = min(40_000, max(500, days * 1440))                # TradingView only serves the newest N bars
        return await fetch_bars(ticker, 60, n)
    return fetch


def _sim_fetch(_sym: str):
    async def fetch(a: date, b: date) -> pd.DataFrame:
        import numpy as np
        days = [a + timedelta(days=i) for i in range((b - a).days + 1)]
        idx = pd.DatetimeIndex([t for d in days if d.weekday() < 5
                                for t in pd.date_range(pd.Timestamp(d) + pd.Timedelta(hours=3, minutes=45), periods=375, freq="1min")])
        p = 100 + np.cumsum(np.random.default_rng(len(idx)).normal(0, .1, len(idx)))
        return pd.DataFrame({"open": p, "high": p + .05, "low": p - .05, "close": p, "volume": 100.0}, index=idx)
    return fetch


def folder_for(source: str, app_symbol: str, src_symbol: str) -> str:
    """Breeze folders use the app name (NIFTY, "NIFTY 27NOV26 FUT"); TV and Yahoo use their own tickers."""
    return app_symbol if source in ("breeze", "sim") else src_symbol


def store_for(source: str, app_symbol: str, src_symbol: str) -> Optional[CandleStore]:
    if source == "breeze":
        return CandleStore(source, app_symbol, _breeze_fetch(src_symbol))
    if source == "yf":
        return CandleStore(source, src_symbol, _yf_fetch(src_symbol))
    if source == "tv":
        return CandleStore(source, src_symbol, _tv_fetch(src_symbol))
    if source == "sim":
        return CandleStore(source, app_symbol, _sim_fetch(src_symbol))
    return None


# ------------------------------------------------------------ higher timeframes, cached as served
TF_NAME = {1800: "30m", 3600: "1h", 86400: "1D", 604800: "1W"}
TF_TTL = {1800: 60.0, 3600: 60.0, 86400: 300.0, 604800: 900.0}     # seconds before asking the source for new bars
TF_DAYS = {1800: 120, 3600: 240, 86400: 365 * 4, 604800: 365 * 12}  # first load depth (calendar days)


def lookback_for(source: str, tf: int, days: int) -> str:
    """Calendar days -> the lookback argument each source's history() takes."""
    days = max(2, int(days))
    if source == "tv":
        per_day = {1800: 48, 3600: 24, 86400: 1, 604800: 1 / 7}[tf]
        return str(int(min(5000, max(10, days * per_day + 5))))
    if source == "yf" and tf in (1800, 3600):
        days = min(days, 729)                                 # Yahoo keeps 30m/1h for ~2 years
    return f"{days}d"


class TFStore:
    """data/<Source>/<Symbol>/<tf>.csv: one file per timeframe, refreshed from the newest bar only."""
    _locks: Dict[str, asyncio.Lock] = {}

    def __init__(self, source: str, folder_name: str, tf: int, extended: bool = False):
        self.source, self.tf = source, tf
        self.file = ROOT / FOLDER.get(source, source) / _safe(folder_name) / f"{TF_NAME[tf]}{'_ext' if extended else ''}.csv"
        self.lock = self._locks.setdefault(str(self.file), asyncio.Lock())

    def read(self) -> pd.DataFrame:
        if not self.file.exists():
            return _EMPTY
        try:
            df = pd.read_csv(self.file)
        except Exception:
            return _EMPTY
        df.index = pd.to_datetime(df.pop("time"), unit="s")
        return df[COLS].astype("float64")

    def write(self, df: pd.DataFrame):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        out = df[COLS].copy()
        out.insert(0, "time", df.index.as_unit("s").asi8)
        tmp = self.file.with_suffix(".tmp")
        out.to_csv(tmp, index=False, float_format="%.6g")
        tmp.replace(self.file)

    @staticmethod
    def merge(*parts) -> pd.DataFrame:
        parts = [p for p in parts if len(p)]
        if not parts:
            return _EMPTY
        df = pd.concat(parts)
        return df[~df.index.duplicated(keep="last")].sort_index()

    async def load(self, history: Callable) -> pd.DataFrame:
        """history(lookback) -> DataFrame from the source. Cached bars + only the missing newest ones."""
        async with self.lock:
            df = self.read()
            if df.empty:
                df = self.merge(await history(lookback_for(self.source, self.tf, TF_DAYS[self.tf])))
                if len(df):
                    self.write(df)
                return df
            if time.time() - self.file.stat().st_mtime < TF_TTL[self.tf]:
                return df
            since = (datetime.now(timezone.utc) - df.index[-1].to_pydatetime().replace(tzinfo=timezone.utc)).days + 2
            new = await history(lookback_for(self.source, self.tf, since))
            if len(new):                                      # indices: keep volume computed earlier (source sends 0)
                hit = new.index.intersection(df.index)
                zero = hit[(new.loc[hit, "volume"].to_numpy() == 0) & (df.loc[hit, "volume"].to_numpy() > 0)]
                if len(zero):
                    new = new.copy()
                    new.loc[zero, "volume"] = df.loc[zero, "volume"].to_numpy()
            df = self.merge(df.iloc[:-1], new)                # the last cached bar may have been forming
            self.write(df)
            return df

    async def older(self, history: Callable, first: pd.Timestamp) -> pd.DataFrame:
        """Bars before `first`, asking the source for twice the current depth when the file has none."""
        async with self.lock:
            df = self.read()
            old = df[df.index < first]
            if len(old):
                return old
            depth = (datetime.now(timezone.utc) - first.to_pydatetime().replace(tzinfo=timezone.utc)).days
            got = await history(lookback_for(self.source, self.tf, depth * 2 + 30))
            old = got[got.index < first] if len(got) else got
            if len(old):
                self.write(self.merge(old, df))
            return old

    def first(self) -> Optional[pd.Timestamp]:
        df = self.read()
        return df.index[0] if len(df) else None
