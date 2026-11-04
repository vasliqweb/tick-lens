"""
Records the live Breeze ticks of index constituents (already subscribed for index volume) to disk:

  data/Breeze/<STOCK>/ticks/YYYY-MM-DD.csv   every tick: time, last, ltq, ttq, bid, bid_qty, ask, ask_qty, avg, oi
  data/Breeze/<STOCK>/1m/YYYY-MM-DD.csv      live 1m candles built from those ticks (volume = traded-qty deltas)

Tick-built candles only fill minutes the source has not sent yet: candles downloaded from Breeze (gap refills,
the after-close exact fetch) always replace them. Any timeframe can later be rebuilt from the tick files.
One recorder per stock for the whole app, shared by every index (HDFCBANK is in NIFTY and BANKNIFTY).
"""
from __future__ import annotations

import logging
import asyncio
import math
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import pandas as pd

log = logging.getLogger("ltv.ticks")
TICK_COLS = ["time", "last", "ltq", "ttq", "bid", "bid_qty", "ask", "ask_qty", "avg", "oi"]
_FIELDS = {"last": ("last", "last_trade_price"), "ltq": ("ltq", "last_trade_quantity"), "ttq": ("ttq", "total_traded_volume"),
           "bid": ("bPrice", "bid_price"), "bid_qty": ("bQty", "bid_quantity"), "ask": ("sPrice", "offer_price"),
           "ask_qty": ("sQty", "offer_quantity"), "avg": ("avgPrice", "weighted_average"), "oi": ("OI", "open_interest_value")}


def _num(t: dict, keys) -> float:
    for k in keys:
        v = t.get(k)
        if v not in (None, ""):
            try:
                return float(str(v).replace(",", ""))
            except ValueError:
                pass
    return math.nan


class StockTicks:
    def __init__(self, name: str):
        from .candle_store import store_for
        self.name = name
        self.store = store_for("breeze", name, name)
        self.ticks_dir = self.store.dir.parent / "ticks"
        self.buf: List[list] = []
        self.bars: Dict[int, list] = {}               # minute -> [o, h, l, c, v]
        self.written: Set[int] = set()                # minutes this recorder put in the 1m file
        self.prev_ttq: Optional[float] = None
        self.day = datetime.now(timezone.utc).date()

    def on_tick(self, t: dict, now: float):
        from .breeze import in_session
        row = [round(now, 3)] + [_num(t, _FIELDS[k]) for k in TICK_COLS[1:]]
        self.buf.append(row)
        last, ttq = row[1], row[3]
        dv = 0.0
        if ttq == ttq:
            if self.prev_ttq is not None and ttq > self.prev_ttq:
                dv = ttq - self.prev_ttq
            self.prev_ttq = ttq
        if last != last or not in_session(now):
            return
        m = int(now // 60 * 60)
        b = self.bars.get(m)
        if b is None:
            self.bars[m] = [last, last, last, last, dv]
        else:
            b[1], b[2], b[3], b[4] = max(b[1], last), min(b[2], last), last, b[4] + dv

    def snapshot(self):
        """Taken on the event loop (cheap): hands the pending ticks and the forming candles to the writer."""
        buf, self.buf = self.buf, []
        bars = {m: list(b) for m, b in self.bars.items()}
        cur = int(time.time() // 60 * 60)
        self.bars = {m: b for m, b in self.bars.items() if m >= cur - 60}   # keep only the forming minutes in memory
        return buf, bars, self.day

    def write(self, snap, candles: bool = True):
        """Runs in a worker thread: disk I/O on the event loop stalled the live chart price."""
        buf, bars, day_ = snap
        if buf:
            day = datetime.fromtimestamp(buf[0][0], timezone.utc).date()
            f = self.ticks_dir / f"{day.isoformat()}.csv"
            try:
                self.ticks_dir.mkdir(parents=True, exist_ok=True)
                new = not f.exists()
                with f.open("a", encoding="utf-8", newline="") as fh:
                    if new:
                        fh.write(",".join(TICK_COLS) + "\n")
                    fh.write("".join(",".join("" if (isinstance(x, float) and x != x) else (f"{x:.3f}" if i == 0 else f"{x:.12g}")
                                              for i, x in enumerate(r)) + "\n" for r in buf))
            except OSError as e:
                log.warning("ticks %s: %s", self.name, e)
        if not candles or not bars:
            return
        from .candle_store import file_lock
        with file_lock(self.store._path(day_)):
            day = self.store._read_day(day_)
            have = set(day.index.as_unit("s").asi8.tolist()) if len(day) else set()
            # only minutes Breeze has not sent (or that this recorder wrote itself and may still update)
            todo = {m: b for m, b in bars.items() if m not in have or m in self.written}
            if not todo:
                return
            ts = sorted(todo)
            df = pd.DataFrame([todo[m] for m in ts], columns=["open", "high", "low", "close", "volume"],
                              index=pd.to_datetime(ts, unit="s"), dtype="float64")
            self.store._write_day_locked(day_, df)
        self.written.update(ts)


class TickRecorder:
    def __init__(self):
        self.stocks: Dict[str, StockTicks] = {}
        self.by_token: Dict[str, StockTicks] = {}
        self._lock = threading.Lock()
        self._last = 0.0

    async def add(self, hub, name: str, token: str):
        if token in self.by_token:
            return
        st = self.stocks.get(name) or StockTicks(name)
        self.stocks[name] = self.by_token[token] = st

        def cb(t, st=st):
            try:
                st.on_tick(t, time.time())
            except Exception:  # pragma: no cover
                log.exception("tick record %s", st.name)
        await hub.subscribe(token, cb)

    async def aflush(self, candles: bool = True):
        """Snapshot on the loop, write in a thread. Several index keepers call this every FLUSH seconds;
        the lock keeps one writer at a time and a call right after another is skipped."""
        now = time.time()
        if candles and now - self._last < 10:
            return
        self._last = now
        today = datetime.now(timezone.utc).date()
        snaps = []
        for st in self.stocks.values():
            if st.day != today:                     # new day: write yesterday, start fresh candles
                snaps.append((st, st.snapshot()))
                st.day, st.bars, st.written, st.prev_ttq = today, {}, set(), None
            snaps.append((st, st.snapshot()))

        def work():
            with self._lock:
                for st, snap in snaps:
                    try:
                        st.write(snap, candles)
                    except Exception as e:
                        log.warning("ticks %s: %s", st.name, e)
        await asyncio.to_thread(work)


RECORDER = TickRecorder()
