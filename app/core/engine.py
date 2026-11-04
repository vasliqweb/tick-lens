"""
TickLens - Python prototype engine.

Components:
  TimeSeries       ring-buffer backed series, Pine-style relative indexing (s[-1], s[0])
  Bar / BarSeries  OHLCV container built from TimeSeries columns
  IndicatorEngine  vectorised (Pandas) batch indicators + O(1) incremental live updates
  Script           base class for user-defined indicator scripts
  EventLoop        asyncio event loop feeding ticks -> bars -> indicators -> scripts
"""
from __future__ import annotations

import asyncio
import math
import random
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# TimeSeries
# ---------------------------------------------------------------------------
class TimeSeries:
    """Fixed-capacity ring buffer over a preallocated numpy array.

    Indexing:
        s[-1]  -> latest value
        s[-2]  -> previous value
        s[0]   -> oldest retained value
        s[-5:] -> last 5 values (numpy view/copy, oldest->newest)
    append() is O(1), no reallocation.
    """

    __slots__ = ("_buf", "_cap", "_head", "_len", "name")

    def __init__(self, capacity: int = 10_000, name: str = "", dtype=np.float64):
        self._buf = np.full(capacity, np.nan, dtype=dtype)
        self._cap = capacity
        self._head = 0  # next write position
        self._len = 0
        self.name = name

    def append(self, value: float) -> None:
        self._buf[self._head] = value
        self._head = (self._head + 1) % self._cap
        if self._len < self._cap:
            self._len += 1

    def update_last(self, value: float) -> None:
        """Overwrite the latest value (used while a bar is still forming)."""
        if self._len == 0:
            self.append(value)
            return
        self._buf[(self._head - 1) % self._cap] = value

    def _phys(self, i: int) -> int:
        if i < 0:
            i += self._len
        if not 0 <= i < self._len:
            raise IndexError(f"{self.name or 'TimeSeries'} index out of range")
        return (self._head - self._len + i) % self._cap

    def __getitem__(self, key):
        if isinstance(key, slice):
            return self.to_numpy()[key]
        return self._buf[self._phys(key)]

    def __len__(self) -> int:
        return self._len

    def get(self, i: int, default: float = math.nan) -> float:
        try:
            return self[i]
        except IndexError:
            return default

    def tail(self, n: int) -> np.ndarray:
        """Last n values (oldest->newest) without copying the whole ring (the per-tick path)."""
        n = max(0, min(int(n), self._len))
        if self._len < self._cap:
            return self._buf[self._len - n: self._len]
        return self._buf[(self._head - n + np.arange(n)) % self._cap]

    def to_numpy(self) -> np.ndarray:
        if self._len < self._cap:
            return self._buf[: self._len]  # view, zero copy
        return np.concatenate((self._buf[self._head :], self._buf[: self._head]))

    def to_pandas(self) -> pd.Series:
        return pd.Series(self.to_numpy(), name=self.name)

    def __repr__(self) -> str:
        return f"TimeSeries({self.name!r}, len={self._len}, last={self.get(-1)})"


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Tick:
    ts: float
    price: float
    volume: float = 0.0


class BarSeries:
    """OHLCV columns as TimeSeries, aggregated from ticks by time frame (seconds)."""

    def __init__(self, timeframe: int = 60, capacity: int = 10_000):
        self.tf = timeframe
        self.time = TimeSeries(capacity, "time")
        self.open = TimeSeries(capacity, "open")
        self.high = TimeSeries(capacity, "high")
        self.low = TimeSeries(capacity, "low")
        self.close = TimeSeries(capacity, "close")
        self.volume = TimeSeries(capacity, "volume")
        self._bucket: Optional[int] = None

    def append_bar(self, ts: float, o: float, h: float, l: float, c: float, v: float) -> None:
        """Append a completed historical bar (backfill)."""
        self._bucket = int(ts // self.tf)
        self.time.append(self._bucket * self.tf)
        self.open.append(o)
        self.high.append(h)
        self.low.append(l)
        self.close.append(c)
        self.volume.append(v)

    def on_tick(self, t: Tick) -> bool:
        """Returns True when a new bar is opened (previous bar closed)."""
        bucket = int(t.ts // self.tf)
        if bucket != self._bucket:
            self._bucket = bucket
            self.time.append(bucket * self.tf)
            for s in (self.open, self.high, self.low, self.close):
                s.append(t.price)
            self.volume.append(t.volume)
            return True
        self.high.update_last(max(self.high[-1], t.price))
        self.low.update_last(min(self.low[-1], t.price))
        self.close.update_last(t.price)
        self.volume.update_last(self.volume[-1] + t.volume)
        return False

    def __len__(self) -> int:
        return len(self.close)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": self.open.to_numpy(),
                "high": self.high.to_numpy(),
                "low": self.low.to_numpy(),
                "close": self.close.to_numpy(),
                "volume": self.volume.to_numpy(),
            },
            index=pd.to_datetime(self.time.to_numpy(), unit="s"),
        )


# ---------------------------------------------------------------------------
# Indicator engine
# ---------------------------------------------------------------------------
class IndicatorEngine:
    """Batch indicators via Pandas (history/backfill) + O(1) incremental state for live ticks."""

    # ---- batch (vectorised) ----
    @staticmethod
    def sma(s: pd.Series, n: int) -> pd.Series:
        return s.rolling(n, min_periods=n).mean()

    @staticmethod
    def ema(s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=n, adjust=False).mean()

    @staticmethod
    def rsi(s: pd.Series, n: int = 14) -> pd.Series:
        d = s.diff()
        up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
        dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
        return 100 - 100 / (1 + up / dn)

    @staticmethod
    def macd(s: pd.Series, fast=12, slow=26, signal=9) -> pd.DataFrame:
        m = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
        sig = m.ewm(span=signal, adjust=False).mean()
        return pd.DataFrame({"macd": m, "signal": sig, "hist": m - sig})

    @staticmethod
    def bollinger(s: pd.Series, n=20, k=2.0) -> pd.DataFrame:
        mid = s.rolling(n).mean()
        sd = s.rolling(n).std(ddof=0)
        return pd.DataFrame({"mid": mid, "upper": mid + k * sd, "lower": mid - k * sd})

    @staticmethod
    def atr(df: pd.DataFrame, n=14) -> pd.Series:
        pc = df["close"].shift()
        tr = pd.concat(
            [df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1
        ).max(axis=1)
        return tr.ewm(alpha=1 / n, adjust=False).mean()

    @staticmethod
    def vwap(df: pd.DataFrame) -> pd.Series:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        day = df.index.normalize()
        pv = (tp * df["volume"]).groupby(day).cumsum()
        return pv / df["volume"].groupby(day).cumsum()

    @staticmethod
    def ta(df: pd.DataFrame, kind: str, **kw):
        """Any of 150+ pandas-ta indicators, e.g. ta(df, "supertrend", length=10, multiplier=3)."""
        import pandas_ta  # noqa: F401  (registers df.ta accessor)
        return getattr(df.ta, kind)(**kw)

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        c = df["close"]
        out["sma20"] = self.sma(c, 20)
        out["ema50"] = self.ema(c, 50)
        out["rsi14"] = self.rsi(c)
        out = out.join(self.macd(c)).join(self.bollinger(c))
        out["atr14"] = self.atr(df)
        out["vwap"] = self.vwap(df)
        return out


class IncEMA:
    """O(1) streaming EMA, seeds from batch value. Supports forming-bar recompute."""

    __slots__ = ("a", "prev", "value")

    def __init__(self, n: int, seed: float = math.nan):
        self.a = 2 / (n + 1)
        self.prev = seed   # EMA of last closed bar
        self.value = seed

    def update(self, x: float, new_bar: bool) -> float:
        if new_bar:
            self.prev = self.value
        self.value = x if math.isnan(self.prev) else self.prev + self.a * (x - self.prev)
        return self.value


class IncSMA:
    """O(1) streaming SMA over a window; forming bar handled by replacing last element."""

    __slots__ = ("n", "win", "total")

    def __init__(self, n: int):
        self.n, self.win, self.total = n, deque(), 0.0

    def update(self, x: float, new_bar: bool) -> float:
        if new_bar or not self.win:
            self.win.append(x)
            self.total += x
            if len(self.win) > self.n:
                self.total -= self.win.popleft()
        else:
            self.total += x - self.win[-1]
            self.win[-1] = x
        return self.total / self.n if len(self.win) == self.n else math.nan


class IncRSI:
    """O(1) streaming Wilder RSI."""

    __slots__ = ("n", "pc", "au", "ad", "_pc", "_au", "_ad", "value", "last")

    def __init__(self, n: int = 14):
        self.n = n
        self.pc = self.au = self.ad = math.nan       # committed state (closed bars)
        self._pc = self._au = self._ad = math.nan    # forming-bar state
        self.value = math.nan
        self.last = math.nan

    def update(self, x: float, new_bar: bool) -> float:
        if new_bar:
            self.pc, self.au, self.ad = self._pc, self._au, self._ad
            self._pc = self.last if not math.isnan(self.last) else self.pc
        self.last = x
        if math.isnan(self._pc):
            return math.nan
        d = x - self._pc
        u, dn = max(d, 0.0), max(-d, 0.0)
        a = 1 / self.n
        au = u if math.isnan(self.au) else self.au + a * (u - self.au)
        ad = dn if math.isnan(self.ad) else self.ad + a * (dn - self.ad)
        self._au, self._ad = au, ad
        self.value = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
        return self.value


# ---------------------------------------------------------------------------
# User scripts
# ---------------------------------------------------------------------------
class Script:
    """Base class for custom indicator/strategy scripts (Pine-like on_bar model).

    Override on_bar(). Access series via self.bars.close[-1], self.bars.close[-2], ...
    Use self.plot(name, value) to output series.
    """

    def __init__(self, bars: BarSeries):
        self.bars = bars
        self.plots: Dict[str, TimeSeries] = {}

    def plot(self, name: str, value: float, new_bar: bool) -> None:
        ts = self.plots.setdefault(name, TimeSeries(self.bars.close._cap, name))
        (ts.append if new_bar or len(ts) == 0 else ts.update_last)(value)

    def on_bar(self, new_bar: bool) -> None:  # pragma: no cover
        raise NotImplementedError


class EmaCrossScript(Script):
    """Example custom script: fast/slow EMA cross signal."""

    def __init__(self, bars: BarSeries, fast=9, slow=21):
        super().__init__(bars)
        self.f, self.s = IncEMA(fast), IncEMA(slow)
        self.signal: Optional[str] = None

    def on_bar(self, new_bar: bool) -> None:
        c = self.bars.close[-1]
        f, s = self.f.update(c, new_bar), self.s.update(c, new_bar)
        self.plot("ema_fast", f, new_bar)
        self.plot("ema_slow", s, new_bar)
        pf, ps = self.plots["ema_fast"].get(-2), self.plots["ema_slow"].get(-2)
        if new_bar and not math.isnan(pf):
            if pf <= ps and f > s:
                self.signal = "BUY"
            elif pf >= ps and f < s:
                self.signal = "SELL"


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------
class EventLoop:
    """asyncio pipeline: feed -> Queue -> BarSeries -> indicators -> scripts -> listeners."""

    def __init__(self, bars: BarSeries, queue_size: int = 100_000):
        self.bars = bars
        self.q: asyncio.Queue[Optional[Tick]] = asyncio.Queue(queue_size)
        self.scripts: List[Script] = []
        self.indicators: Dict[str, object] = {}
        self.listeners: List[Callable[[Tick, bool, Dict[str, float]], None]] = []
        self.latencies: List[float] = []

    def add_indicator(self, name: str, ind) -> None:
        self.indicators[name] = ind

    def add_script(self, s: Script) -> None:
        self.scripts.append(s)

    def on_update(self, fn) -> None:
        self.listeners.append(fn)

    def backfill(self, df: pd.DataFrame) -> None:
        """Warm up bars, incremental indicators and scripts from historical OHLCV."""
        bars, inds, scripts = self.bars, self.indicators.values(), self.scripts
        ts = df.index.as_unit("s").asi8
        for t, o, h, l, c, v in zip(ts, df["open"], df["high"], df["low"], df["close"], df["volume"]):
            bars.append_bar(t, o, h, l, c, v)
            for ind in inds:
                ind.update(c, True)
            for s in scripts:
                s.on_bar(True)

    async def consume(self, ticks) -> None:
        """Pump an async iterator of Ticks (from a DataSource) into the loop."""
        async for t in ticks:
            await self.q.put(t)
        await self.q.put(None)

    async def publish(self, t: Optional[Tick]) -> None:
        await self.q.put(t)

    async def run(self) -> None:
        bars, inds, scripts, listeners = self.bars, self.indicators, self.scripts, self.listeners
        lat = self.latencies
        perf = time.perf_counter
        while True:
            t = await self.q.get()
            if t is None:
                break
            t0 = perf()
            new_bar = bars.on_tick(t)
            c = t.price
            vals = {k: ind.update(c, new_bar) for k, ind in inds.items()}
            for s in scripts:
                s.on_bar(new_bar)
            for fn in listeners:
                fn(t, new_bar, vals)
            lat.append(perf() - t0)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
async def simulated_feed(loop: EventLoop, n: int, start_ts: float, price: float = 100.0):
    ts = start_ts
    for _ in range(n):
        ts += random.uniform(0.05, 1.5)
        price *= 1 + random.gauss(0, 0.0005)
        await loop.publish(Tick(ts, round(price, 2), random.randint(1, 500)))
    await loop.publish(None)


async def main(n_ticks: int = 200_000):
    bars = BarSeries(timeframe=60)
    loop = EventLoop(bars)
    loop.add_indicator("sma20", IncSMA(20))
    loop.add_indicator("ema50", IncEMA(50))
    loop.add_indicator("rsi14", IncRSI(14))
    script = EmaCrossScript(bars)
    loop.add_script(script)

    signals = []
    loop.on_update(lambda t, nb, v: script.signal and nb and signals.append((t.ts, script.signal)))

    t0 = time.perf_counter()
    await asyncio.gather(loop.run(), simulated_feed(loop, n_ticks, time.time()))
    wall = time.perf_counter() - t0

    lat = np.array(loop.latencies) * 1e6
    print(f"ticks={n_ticks} bars={len(bars)} wall={wall:.2f}s ({n_ticks / wall:,.0f} ticks/s)")
    print(f"per-tick latency us: p50={np.percentile(lat, 50):.1f} p99={np.percentile(lat, 99):.1f}")
    print(f"close[-1]={bars.close[-1]} close[-2]={bars.close[-2]} last signal={script.signal}")

    # Cross-check incremental vs Pandas batch
    df = IndicatorEngine().compute_all(bars.to_frame())
    print(df[["close", "sma20", "ema50", "rsi14", "macd", "upper", "lower", "atr14", "vwap"]].tail(3))
    inc = {k: ind.value if hasattr(ind, "value") else ind.total / ind.n for k, ind in loop.indicators.items()}
    for k in ("sma20", "ema50", "rsi14"):
        print(f"{k}: incremental={inc[k]:.4f} pandas={df[k].iloc[-1]:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
