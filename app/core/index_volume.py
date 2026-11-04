"""
Index volume kept in the index's own 1m cache, so chart loads never re-sum the constituents.

One IndexVolumeKeeper per index (NIFTY, BANKNIFTY, SENSEX ...) runs for the whole app, not per chart:

  1. backfill  once per app run per day: today's constituents' 1m candles (one Breeze call per stock) are
               summed into data/Breeze/<INDEX>/1m/<today>.csv (only when the file does not already cover up to now)
  2. live      the constituents' ticks (cumulative traded qty deltas) are added to the current minute and flushed
               into the same file every FLUSH seconds; charts get the deltas through listeners
  3. close     after the session closes, one more fetch of the 50 stocks' final 1m candles replaces the tick-based
               numbers with exact ones and marks the day done ("ivol" in meta.json), then live subscriptions stop

The same constituent ticks are also recorded per stock (core/tick_recorder.py): raw ticks and live 1m candles.

Charts (1m-15m, built from the 1m file) therefore load with volume already in the bars. 30m and up get today's
volume pushed from the keeper's in-memory series. Volume is an estimate: the sum of constituents' NSE volume.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

import pandas as pd

log = logging.getLogger("ltv.ivol")
FLUSH = 30.0                 # seconds between writes of the live minutes into the 1m file
STALE = 180.0                # (unused: gaps in the file decide when to backfill)
CLOSE_UTC = 10 * 3600 + 15 * 60     # 15:45 IST: NSE cash closed, final 1m candles available
CONCURRENCY = 6
RECONCILE = 180.0            # no tick volume for this long in session -> refill closed minutes from constituents' 1m
TICK_SAMPLE = None           # set on first use: cache/breeze/tick_sample.json (diagnostics: what a Breeze tick carries)


def _now() -> float:
    return time.time()


class IndexVolumeKeeper:
    _all: Dict[str, "IndexVolumeKeeper"] = {}

    @classmethod
    def get(cls, app_name: str, code: str) -> "IndexVolumeKeeper":
        k = cls._all.get(app_name)
        if k is None or k.day != datetime.now(timezone.utc).date() or (k.task and k.task.done() and not k.final):
            k = cls._all[app_name] = cls(app_name, code)
        k.start()
        return k

    def __init__(self, app_name: str, code: str):
        from .candle_store import store_for
        self.name, self.code = app_name, code
        self.day = datetime.now(timezone.utc).date()
        self.store = store_for("breeze", app_name, code)
        self.minutes: Dict[int, float] = {}            # minute (epoch s, UTC) -> volume, today only
        self.ready = asyncio.Event()
        self.final = False                              # exact (after-close) numbers are in the file
        self.listeners: List[Callable[[float, float], None]] = []
        self.task: Optional[asyncio.Task] = None
        self.names: List[str] = []
        self.status = "starting"
        self._dirty = False
        self.ticks = 0                                  # ticks received / ticks that carried traded qty
        self.ticks_ttq = 0
        self.last_tick_vol = 0.0                        # time of the last tick that added volume
        self.last_refill = 0.0
        self._sampled = False

    # ------------------------------------------------------------ public
    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self._run())

    def series(self) -> pd.Series:
        """Today's per-minute volume (UTC-naive index)."""
        if not self.minutes:
            return pd.Series(dtype="float64", index=pd.DatetimeIndex([]))
        ts = sorted(self.minutes)
        return pd.Series([self.minutes[t] for t in ts], index=pd.to_datetime(ts, unit="s"), dtype="float64")

    def listen(self, cb: Callable[[float, float], None]):
        self.listeners.append(cb)

    def unlisten(self, cb):
        if cb in self.listeners:
            self.listeners.remove(cb)

    # ------------------------------------------------------------ meta (merged with disk: other store instances write it too)
    def _meta(self) -> dict:
        try:
            return json.loads(self.store.meta_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_meta(self, **upd):
        m = self._meta()
        m.update(upd)
        self.store.meta.update(upd)
        self.store.meta_file.parent.mkdir(parents=True, exist_ok=True)
        self.store.meta_file.write_text(json.dumps(m), encoding="utf-8")

    # ------------------------------------------------------------ main loop
    async def _run(self):
        from .breeze import BreezeHub
        hub = BreezeHub.get()
        try:
            self.names = await hub.constituents(self.code)
            key = self.day.isoformat()
            meta = self._meta()
            day = self.store._read_day(self.day)
            if len(day):
                self.minutes = {int(t): float(v) for t, v in zip(day.index.as_unit("s").asi8, day["volume"]) if v > 0}
            if key in meta.get("ivol", []):             # exact numbers already saved after the close
                self.final = True
                self.status = "final"
                self.ready.set()
                return
            live = meta.get("ivol_live") or {}
            if live.get("day") == key and live.get("empty"):   # holiday / no trading today (checked once)
                self.final = True
                self.status = "no trading today"
                return
            if self._after_close():
                await self._exact(hub)
                return
            await self._subscribe(hub)                  # ticks first, so nothing between backfill and live is lost
            if not self.minutes or await self._agaps():
                self.status = f"summing {len(self.names)} stocks (once today)"
                await self._backfill(hub, final=False)
            self.status = "live"
            self.last_refill = _now()
            self.ready.set()
            while not self._after_close():
                await asyncio.sleep(FLUSH)
                try:
                    await self.store.ensure(self.day, self.day)     # index OHLC rows to carry the volume (cached ~45s)
                except Exception as e:
                    log.info("ivol %s: index candles: %s", self.name, e)
                await self._aflush()
                await self._record(candles=True)
                await self._refill_if_quiet(hub)
            await self._aflush()
            await self._record(candles=False)                 # after the close only raw ticks; candles come from Breeze
            await self._exact(hub)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("index volume keeper %s: %s", self.name, e)
            self.status = f"failed: {e}"
        finally:
            self.ready.set()
            await self._unsubscribe(hub)

    async def _agaps(self) -> int:
        have = set(self.minutes)                       # snapshot on the loop; file read in a thread
        return await asyncio.to_thread(self._gaps, have)

    def _gaps(self, have=None) -> int:
        """Closed in-session minutes of today's index file that still have no volume (missed while the app was
        off, or ticks lost). Minutes older than 2 minutes only: the newest ones are still being counted."""
        from .breeze import session_only
        day = self.store._read_day(self.day)
        if not len(day):
            return 0
        day = session_only(day, False)
        old = day[day.index < pd.Timestamp(_now() - 120, unit="s")]
        have = set(self.minutes) if have is None else have
        return int(sum(1 for t, v in zip(old.index.as_unit("s").asi8, old["volume"]) if not v > 0 and int(t) not in have))

    async def _refill_if_quiet(self, hub):
        """Safety net every RECONCILE seconds: closed minutes still without volume (gap in the file, ticks not
        arriving) are refilled from the constituents' 1m candles."""
        from .breeze import in_session
        now = _now()
        if not in_session(now) or now - self.last_refill < RECONCILE:
            return
        self.last_refill = now
        gaps = await self._agaps()
        if not gaps:
            return
        log.info("ivol %s: %d minutes without volume (ticks %d, with qty %d); refilling from 1m candles",
                 self.name, gaps, self.ticks, self.ticks_ttq)
        self.status = f"refilling {gaps} minutes from 1m candles"
        await self._backfill(hub, final=False)
        self.status = "live"

    @staticmethod
    async def _record(candles: bool):
        try:
            from .tick_recorder import RECORDER
            await RECORDER.aflush(candles)
        except Exception as e:
            log.warning("tick recorder flush: %s", e)

    def _sample(self, t: dict):
        """Write the first tick seen to cache/breeze/tick_sample.json (field names only matter)."""
        if self._sampled:
            return
        self._sampled = True
        try:
            from .breeze import CACHE
            CACHE.mkdir(parents=True, exist_ok=True)
            (CACHE / "tick_sample.json").write_text(json.dumps({k: str(v)[:40] for k, v in t.items()}, indent=1))
            log.info("ivol %s: first constituent tick fields: %s", self.name, sorted(t))
        except Exception:
            pass

    def _after_close(self) -> bool:
        now = _now()
        return datetime.now(timezone.utc).date() != self.day or now % 86400 >= CLOSE_UTC

    # ------------------------------------------------------------ live ticks
    async def _subscribe(self, hub):
        from .breeze import tick_fields
        self._subs, last = [], {}
        for n in self.names:
            try:
                info = await hub.resolve(n)
            except Exception as e:
                log.info("ivol %s: constituent %s: %s", self.name, n, e)
                continue
            tok = info.get("token")
            if not tok:
                continue

            def cb(t, tok=tok):
                self.ticks += 1
                self._sample(t)
                q = tick_fields(t)["ttq"]
                if q != q:
                    return
                self.ticks_ttq += 1
                prev = last.get(tok)
                last[tok] = q
                if prev is not None and q > prev:
                    self.last_tick_vol = _now()
                    self._add(_now(), q - prev)
            await hub.subscribe(tok, cb)
            self._subs.append((tok, cb))
            try:
                from .tick_recorder import RECORDER
                await RECORDER.add(hub, n, tok)
            except Exception as e:
                log.info("tick recorder %s: %s", n, e)

    async def _unsubscribe(self, hub):
        for tok, cb in getattr(self, "_subs", []):
            try:
                await hub.unsubscribe(tok, cb)
            except Exception:
                pass
        self._subs = []

    def _add(self, ts: float, dv: float):
        from .breeze import in_session
        if not in_session(ts):
            return
        m = int(ts // 60 * 60)
        self.minutes[m] = self.minutes.get(m, 0.0) + dv
        self._dirty = True
        for cb in list(self.listeners):
            try:
                cb(ts, dv)
            except Exception:  # pragma: no cover
                log.exception("ivol listener")

    # ------------------------------------------------------------ disk
    async def _aflush(self):
        """Write the minutes into the index's 1m file (only rows the index file has; its OHLC stays as is).
        The CSV read/merge/write runs in a worker thread: done on the event loop it froze live chart ticks."""
        self._dirty = False
        ser = self.series() if self.minutes else None     # snapshot on the loop (ticks keep adding minutes)
        if ser is not None:
            await asyncio.to_thread(self._write_minutes, ser)
        self._flush_meta()

    def _write_minutes(self, ser: pd.Series):
        from .candle_store import file_lock
        with file_lock(self.store._path(self.day)):
            day = self.store._read_day(self.day)
            if not len(day):
                return
            v = ser.reindex(day.index)
            keep = v.notna().to_numpy() & (v.to_numpy() != day["volume"].to_numpy())   # new rows / changed minutes
            if keep.any():
                vol = day["volume"].to_numpy().copy()
                vol[keep] = v.to_numpy()[keep]
                self.store._write_day_locked(self.day, day.assign(volume=vol))

    def _flush_meta(self):
        self._save_meta(ivol_live={"day": self.day.isoformat(), "upto": _now()})

    async def _sum_today(self, hub) -> Optional[pd.Series]:
        from .candle_store import store_for
        sem, vols = asyncio.Semaphore(CONCURRENCY), []

        async def one(n):
            async with sem:
                try:
                    df = await store_for("breeze", n, n).ensure(self.day, self.day)
                    if len(df):
                        vols.append(df["volume"])
                except Exception as e:
                    log.info("ivol %s: %s today: %s", self.name, n, e)
        await asyncio.gather(*(one(n) for n in self.names))
        if not vols:
            return None
        return pd.concat(vols, axis=1).sum(axis=1, min_count=1).dropna().sort_index()

    async def _backfill(self, hub, final: bool):
        try:
            await self.store.ensure(self.day, self.day)
        except Exception as e:
            log.info("ivol %s: index candles: %s", self.name, e)
        tot = await self._sum_today(hub)
        if tot is None:
            if final:
                self._save_meta(ivol_live={"day": self.day.isoformat(), "upto": _now(), "empty": True})
            return
        cur = int(_now() // 60 * 60)
        for t, v in zip(tot.index.as_unit("s").asi8, tot.to_numpy()):
            t = int(t)
            if final or t < cur:                        # the forming minute keeps counting from ticks
                self.minutes[t] = float(v)
        self._dirty = True
        await self._aflush()
        for cb in list(self.listeners):                 # charts reload today's numbers from the series
            try:
                cb(None, 0.0)
            except Exception:  # pragma: no cover
                log.exception("ivol listener")

    async def _exact(self, hub):
        self.status = "final: exact after-close numbers"
        await self._backfill(hub, final=True)
        if self.minutes:
            m = self._meta()
            ivol = sorted(set(m.get("ivol", [])) | {self.day.isoformat()})
            self._save_meta(ivol=ivol)
        self.final = True
        self.ready.set()


def keep(app_name: str, code: str) -> IndexVolumeKeeper:
    return IndexVolumeKeeper.get(app_name, code)
