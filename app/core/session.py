"""
One ChartSession per browser WebSocket.

  load        -> backfill history into a BarSeries, send bars, start live feed
  indicators  -> run indicator scripts over the bars, send full plots
  live tick   -> update forming bar (anchored to history grid), push bar,
                 throttled tail recompute of indicators
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from .data_sources import SOURCES, SimSource
from .engine import BarSeries
from .scripting import ScriptError, run_script

log = logging.getLogger("ltv")

DEFAULT_LOOKBACK = {
    "yf": {60: "7d", 120: "30d", 180: "7d", 300: "60d", 900: "60d", 1800: "60d", 3600: "730d", 86400: "10y", 604800: "max"},
    "nse": {86400: "1095d"},
    "ccxt": {},  # bar count
    "sim": {},
}
CALC_WINDOW = 5000      # bars used for live indicator recompute
TAIL = 3                # bars re-sent per live update
THROTTLE = 0.5          # seconds between live indicator recomputes
POLL_SEC = {"yf": 10.0, "nse": 5.0}
# Indices have no traded volume; borrow it from a liquid ETF tracking the index (Yahoo symbols).
VOLUME_PROXY = {"^NSEI": "NIFTYBEES.NS", "^NSEBANK": "BANKBEES.NS", "^CNXIT": "ITBEES.NS", "^BSESN": "SENSEXIETF.NS"}
PROXY_POLL = 30.0
LTF_CACHE_DAYS = 30     # days of 1m cache read for lower_tf(60) (volume profiles)
LTF_TTL = 60.0          # seconds a lower-timeframe fetch is reused by scripts
REQ_TTL = 600.0         # seconds a request() fetch (daily bars, VIX) is reused
# volatility index per syminfo["vix"]: (source, ticker) to try, the chart's own source first
VIX_TICKERS = {"INDIAVIX": [("tv", "NSE:INDIAVIX"), ("yf", "^INDIAVIX"), ("breeze", "INDVIX")],
               "^VIX": [("yf", "^VIX"), ("tv", "CBOE:VIX")]}


def make_source(name: str):
    if name == "sim":
        return SimSource(rate=0.25)
    if name == "breeze":
        from .breeze import BreezeSource
        return BreezeSource()
    if name == "tv":
        from .tradingview import TradingViewSource
        return TradingViewSource()
    if name not in SOURCES:
        raise ValueError(f"unknown source {name}")
    return SOURCES[name]()


class ChartSession:
    def __init__(self, send):
        self.send = send                      # async fn(dict)
        self.bars: Optional[BarSeries] = None
        self.src = None
        self.source = self.symbol = self.src_symbol = ""
        self.tf = 60
        self.indicators: Dict[str, dict] = {}  # id -> {code, inputs}
        self.feed_task: Optional[asyncio.Task] = None
        self.proxy_task: Optional[asyncio.Task] = None
        self.volume_src: Optional[str] = None
        self.vol_dirty = False
        self.calc_task: Optional[asyncio.Task] = None
        self.dirty = False
        self.gen = 0                          # bumps on every load to drop stale work
        self.full: Optional[pd.DataFrame] = None   # every bar loaded (replay hides the tail of it)
        self.rp: Optional[dict] = None             # bar replay state
        self.rp_lock = asyncio.Lock()
        self.ltf_cache: Dict[tuple, tuple] = {}    # (gen, tf) -> (fetched_at, intrabars) for lower_tf()
        self.store = None                          # 1m candle store when this timeframe is built from it
        self.store_start = None                    # oldest UTC day loaded from the store
        self.tfstore = None                        # per-timeframe cache file (30m and up)
        self.ivol_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ load
    async def load(self, source: str, symbol: str, tf: int, lookback: Optional[str] = None, extended: bool = False,
                   replay: Optional[dict] = None):
        await self.stop_feed()
        self.rp = None
        self.gen += 1
        gen = self.gen
        from .symbols import to_source
        self.source, self.symbol, self.tf = source, symbol, int(tf)
        self.src_symbol = to_source(symbol, source)          # app name -> this source's ticker
        sym = self.src_symbol
        self.src = make_source(source)
        self.src.extended = extended                          # include pre-open / closing-auction bars
        lb = lookback if source == "breeze" else (
            lookback or DEFAULT_LOOKBACK.get(source, {}).get(self.tf) or ("1000" if source == "ccxt" else "3000"))
        df = await self._cached_history(symbol, sym, gen) if not lookback else None
        if df is None:
            df = await self.src.history(sym, self.tf, lb)
        if gen != self.gen:
            return
        if df.empty:
            raise ValueError(f"no data for {symbol} ({source}, tf={tf})")
        self.volume_src = None
        proxy = VOLUME_PROXY.get(sym.upper()) if source == "yf" else None
        if proxy and not df["volume"].any():
            try:
                pv = await self.src.history(proxy, self.tf, lb)
                df = df.assign(volume=pv["volume"].reindex(df.index).fillna(0.0))
                self.volume_src = proxy
            except Exception as e:
                log.warning("volume proxy %s failed: %s", proxy, e)
            if gen != self.gen:
                return
        self.full = df
        if replay and replay.get("t"):
            await self.replay_start(int(replay["t"]), replay.get("step"), gen)
            return
        self._fill(df)
        await self.send({"type": "history", "source": source, "symbol": symbol, "tf": self.tf,
                         "volume_src": self.volume_src, "cache": self.cache_info(), "bars": self._bars_json()})
        for iid in list(self.indicators):
            await self.compute(iid)
        self._start_live(gen)

    # ------------------------------------------------------------ 1m candle store
    async def _cached_history(self, symbol: str, sym: str, gen: int) -> Optional[pd.DataFrame]:
        """Up to 15m: built from data/<Source>/<Symbol>/1m. 30m and up: data/<Source>/<Symbol>/<tf>.csv.
        None = use the source directly."""
        from .candle_store import CACHED_TF, TF_NAME, TFStore, folder_for, store_for
        self.store = self.tfstore = None
        if self.tf in TF_NAME and self.source in ("breeze", "yf", "tv"):
            store = TFStore(self.source, folder_for(self.source, symbol, sym), self.tf, bool(getattr(self.src, "extended", False)))
            try:
                df = await store.load(lambda lb: self.src.history(sym, self.tf, lb))
            except Exception as e:
                log.warning("%s cache for %s failed (%s); loading %s directly", store.file.name, symbol, e, self.source)
                return None
            if df.empty:
                return None
            self.tfstore = store
            return df
        if self.tf not in CACHED_TF:
            return None
        store = store_for(self.source, symbol, sym)
        if store is None:
            return None
        from datetime import datetime, timedelta, timezone
        start = datetime.now(timezone.utc).date() - timedelta(days=CACHED_TF[self.tf])
        try:
            df = await self._from_store(store, start)
            for _ in range(4):                        # holidays / weekends: reach back until the chart has some depth
                if len(df) >= 300 or gen != self.gen or (store.floor and start <= store.floor):
                    break
                start -= timedelta(days=CACHED_TF[self.tf])
                df = await self._from_store(store, start)
        except Exception as e:
            log.warning("1m store for %s failed (%s); loading %s directly", symbol, e, self.source)
            return None
        if df.empty:
            return None
        self.store, self.store_start = store, start
        return df

    async def _from_store(self, store, start, end=None) -> pd.DataFrame:
        from .candle_store import to_tf
        df = await store.ensure(start, end)
        if self.source == "breeze" and not getattr(self.src, "extended", False):
            from .breeze import session_only
            from .symbols import is_fno
            df = session_only(df, is_fno(self.symbol))
        return to_tf(df, self.tf)

    async def more(self):
        """Scrolled to the left edge: prepend older candles (from disk, else the source)."""
        from datetime import timedelta
        from .candle_store import CACHED_TF
        gen, store = self.gen, self.store
        if self.tfstore is not None and not self.rp and self.bars is not None and len(self.bars):
            first = pd.to_datetime(self.bars.time[0], unit="s")
            older = await self.tfstore.older(lambda lb: self.src.history(self.src_symbol, self.tf, lb), first)
            if gen != self.gen:
                return
            await self._prepend(older, older.empty)
            return
        if store is None or self.rp or self.bars is None or not len(self.bars):
            await self.send({"type": "more", "n": 0, "end": True})
            return
        older, start = pd.DataFrame(), self.store_start
        first = pd.to_datetime(self.bars.time[0], unit="s")
        for _ in range(6):                            # skip empty stretches (holidays) in one go
            fl = store.floor
            if fl and start <= fl:
                break
            start = start - timedelta(days=CACHED_TF[self.tf] * 2)
            older = await self._from_store(store, start, self.store_start - timedelta(days=1))
            if gen != self.gen:
                return
            older = older[older.index < first]
            if len(older):
                break
        self.store_start = start
        fl = store.floor
        await self._prepend(older, bool(fl and start <= fl))
        from .breeze import INDEX_LISTS
        if self.source == "breeze" and self.src_symbol.upper() in INDEX_LISTS and len(older):
            if self.ivol_task:
                self.ivol_task.cancel()
            self.ivol_task = asyncio.create_task(self._store_index_volume(gen, start))

    async def _prepend(self, older: pd.DataFrame, end: bool):
        if older.empty:
            await self.send({"type": "more", "n": 0, "end": end})
            return
        self.full = pd.concat([older, self.full]) if self.full is not None else older
        self._fill(pd.concat([older, self.frame()]))
        await self.send({"type": "history", "source": self.source, "symbol": self.symbol, "tf": self.tf, "prepend": len(older),
                         "end": end, "volume_src": self.volume_src, "cache": self.cache_info(), "bars": self._bars_json()})
        for iid in list(self.indicators):
            await self.compute(iid)

    def volume_note(self) -> Optional[str]:
        """Where this chart's volume comes from when it is not the instrument's own traded volume."""
        if getattr(self, "volume_src", None):
            return f"index has no volume - using ETF {self.volume_src} volume"
        if self.source == "breeze":
            from .breeze import INDEX_LISTS
            if (self.src_symbol or "").upper() in INDEX_LISTS:
                return "sum of constituents' traded volume"
        return None

    def cache_info(self) -> Optional[dict]:
        """Where this chart's local cache starts: {t: first cached bar (epoch s), kind: "1m"|"30m"|..., path}."""
        try:
            if self.tfstore is not None:
                f = self.tfstore.first()
                return {"t": int(f.timestamp()), "kind": self.tfstore.file.stem, "path": str(self.tfstore.file.parent.name)} if f is not None else None
            if self.store is not None:
                d = self.store.oldest()
                if d is None:
                    return None
                day = self.store._read_day(d)
                return {"t": int(day.index[0].timestamp()), "kind": "1m", "path": self.store.dir.parent.name} if len(day) else None
        except Exception:
            return None
        return None

    def _fill(self, df: pd.DataFrame):
        self.bars = BarSeries(self.tf, capacity=max(len(df) + 20_000, 50_000))
        ts = df.index.as_unit("s").asi8
        for t, o, h, l, c, v in zip(ts, df["open"], df["high"], df["low"], df["close"], df["volume"]):
            self._append(int(t), o, h, l, c, v)

    def _start_live(self, gen: int):
        source, sym, df = self.source, self.src_symbol, self.full
        self.feed_task = asyncio.create_task(self._feed(gen))
        self.calc_task = asyncio.create_task(self._calc_loop(gen))
        if self.volume_src:
            self.proxy_task = asyncio.create_task(self._proxy_volume(gen, self.volume_src))
        elif source == "breeze":
            from .breeze import INDEX_LISTS
            if sym.upper() in INDEX_LISTS:
                # finished days come from the cache (index files carry the summed volume); only today is summed here
                cached = self.store is not None or self._tf_volume_cached()
                self.proxy_task = asyncio.create_task(self._today_index_volume(gen) if cached else self._index_volume(gen))
                if self.store is not None and self.store_start is not None:   # older days: constituents' 1m volume, saved
                    self.ivol_task = asyncio.create_task(self._store_index_volume(gen, self.store_start))

    # ------------------------------------------------------------ bar replay
    async def replay_start(self, t: int, step: Optional[int] = None, gen: Optional[int] = None):
        """Hide every bar from time t on; replay_step then reveals them one update interval at a time."""
        async with self.rp_lock:
            if self.full is None or self.full.empty:
                raise ValueError("nothing loaded to replay")
            gen = self.gen if gen is None else gen
            await self.stop_feed()
            full = self.full
            ft = full.index.as_unit("s").asi8
            t = int(min(max(t, ft[min(1, len(ft) - 1)]), ft[-1]))
            step = int(step or self.tf)
            sub = None
            if step < self.tf:
                await self.send({"type": "status", "msg": "replay: loading update-interval data…"})
                lb = (f"{math.ceil((time.time() - t) / 86400) + 2}d" if self.source == "breeze"
                      else DEFAULT_LOOKBACK.get(self.source, {}).get(step))
                try:
                    sub = await self.src.history(self.src_symbol, step, lb)
                except Exception as e:
                    log.warning("replay interval %s failed: %s", step, e)
                if gen != self.gen:
                    return
                if sub is None or sub.empty or sub.index.as_unit("s").asi8[0] > t:
                    await self.send({"type": "status", "msg": "replay: no data that far back for that update interval, using the chart interval"})
                    sub, step = None, self.tf
            if sub is None:
                k = int(np.searchsorted(ft, t, "left"))
                self._fill(full.iloc[:max(k, 1)])
                self.rp = {"ft": ft, "k": max(k, 1), "sub": None, "step": step}
            else:
                st = sub.index.as_unit("s").asi8
                done = int(np.searchsorted(ft + self.tf, t, "right"))       # bars that closed before t
                self._fill(full.iloc[:max(done, 1)])
                self.rp = {"ft": ft, "sub": sub, "st": st, "j": int(np.searchsorted(st, t, "left")), "step": step}
                for j in range(int(np.searchsorted(st, ft[max(done, 1) - 1] + self.tf, "left")), self.rp["j"]):
                    self._merge_sub(j)               # the part of the current bar that already traded
            await self.send({"type": "history", "source": self.source, "symbol": self.symbol, "tf": self.tf,
                             "volume_src": self.volume_src, "bars": self._bars_json(), "replay": self._rp_info()})
            for iid in list(self.indicators):
                await self.compute(iid)

    def _rp_info(self) -> dict:
        rp = self.rp
        if rp["sub"] is None:
            k, ft = rp["k"], rp["ft"]
            now, end = (int(ft[k]) if k < len(ft) else int(ft[-1]) + self.tf), k >= len(ft)
        else:
            j, st = rp["j"], rp["st"]
            now, end = (int(st[j]) if j < len(st) else int(st[-1]) + rp["step"]), j >= len(st)
        return {"t": now, "step": rp["step"], "end": end}

    def _merge_sub(self, j: int):
        rp, ft = self.rp, self.rp["ft"]
        row = rp["sub"].iloc[j]
        t = int(rp["st"][j])
        i = int(np.searchsorted(ft, t, "right")) - 1
        if i < 0:
            return
        bt, b = int(ft[i]), self.bars
        o, h, l, c, v = (float(row[k]) for k in ("open", "high", "low", "close", "volume"))
        v = 0.0 if v != v else v
        if not len(b) or bt > b.time[-1]:
            self._append(bt, o, h, l, c, v)
        elif bt == b.time[-1]:
            b.high.update_last(max(b.high[-1], h))
            b.low.update_last(min(b.low[-1], l))
            b.close.update_last(c)
            b.volume.update_last(b.volume[-1] + v)

    async def replay_step(self, n: int = 1):
        async with self.rp_lock:
            rp = self.rp
            if rp is None:
                return
            for _ in range(max(1, int(n))):
                if rp["sub"] is None:
                    if rp["k"] >= len(rp["ft"]):
                        break
                    row = self.full.iloc[rp["k"]]
                    self._append(int(rp["ft"][rp["k"]]), *(row[k] for k in ("open", "high", "low", "close", "volume")))
                    rp["k"] += 1
                else:
                    if rp["j"] >= len(rp["st"]):
                        break
                    self._merge_sub(rp["j"])
                    rp["j"] += 1
                await self.send({"type": "bar", "bar": self._bars_json(1)[0]})
            for iid in list(self.indicators):
                await self.compute(iid, tail=TAIL)
            await self.send({"type": "replay", **self._rp_info()})

    async def stop_feed(self):
        for t in (self.feed_task, self.calc_task, self.proxy_task, self.ivol_task):
            if t:
                t.cancel()
        self.feed_task = self.calc_task = self.proxy_task = None

    # ------------------------------------------------------------ bar store
    def _append(self, t, o, h, l, c, v):
        b = self.bars
        b.time.append(t)
        for s, x in ((b.open, o), (b.high, h), (b.low, l), (b.close, c), (b.volume, v)):
            s.append(float(x))

    def upsert_bar(self, t, o, h, l, c, v) -> bool:
        b = self.bars
        last = b.time[-1] if len(b) else -math.inf
        if t > last:
            self._append(t, o, h, l, c, 0.0 if v != v else v)
        elif t == last:
            if v != v:  # NaN volume = keep existing (volume comes from a proxy)
                v = b.volume[-1]
            for s, x in ((b.open, o), (b.high, h), (b.low, l), (b.close, c), (b.volume, v)):
                s.update_last(float(x))
        else:
            return False
        return True

    def on_tick(self, ts: float, price: float, vol: float) -> None:
        """Aggregate a tick on the grid anchored at the last history bar (handles exchange TZ / daily bars)."""
        b = self.bars
        if not len(b):
            self._append(int(ts // self.tf) * self.tf, price, price, price, price, vol)
            return
        T = b.time[-1]
        if ts < T:
            return
        k = int((ts - T) // self.tf)
        if k == 0:
            b.high.update_last(max(b.high[-1], price))
            b.low.update_last(min(b.low[-1], price))
            b.close.update_last(price)
            b.volume.update_last(b.volume[-1] + vol)
        else:
            self._append(int(T + k * self.tf), price, price, price, price, vol)

    def _bars_json(self, last: Optional[int] = None):
        b = self.bars
        get = (lambda s: s.tail(last)) if last else (lambda s: s.to_numpy())
        cols = [get(b.time), get(b.open), get(b.high), get(b.low), get(b.close), get(b.volume)]
        return [[int(t), o, h, l, c, (0 if math.isnan(v) else v)] for t, o, h, l, c, v in zip(*cols)]

    def frame(self, window: Optional[int] = None) -> pd.DataFrame:
        b = self.bars
        sl = slice(-window, None) if window else slice(None)
        return pd.DataFrame(
            {k: getattr(b, k).to_numpy()[sl] for k in ("open", "high", "low", "close", "volume")},
            index=pd.to_datetime(b.time.to_numpy()[sl], unit="s"),
        )

    # ------------------------------------------------------------ indicators
    async def set_indicator(self, iid: str, code: str, inputs: dict):
        self.indicators[iid] = {"code": code, "inputs": inputs or {}}
        if self.bars is not None:
            await self.compute(iid)

    async def remove_indicator(self, iid: str):
        self.indicators.pop(iid, None)

    async def compute(self, iid: str, tail: Optional[int] = None):
        ind = self.indicators.get(iid)
        if ind is None or self.bars is None:
            return
        df = self.frame(CALC_WINDOW if tail else None)
        try:
            res = await asyncio.to_thread(run_script, ind["code"], df, ind["inputs"], tail, self._script_ctx())
        except ScriptError as e:
            if not tail:
                await self.send({"type": "ind_error", "id": iid, "error": str(e)})
            return
        except Exception as e:  # pragma: no cover
            log.exception("indicator failed")
            await self.send({"type": "ind_error", "id": iid, "error": f"{type(e).__name__}: {e}"})
            return
        if tail:
            res = {k: res[k] for k in ("time", "plots", "markers", "barcolors", "boxes", "labels", "bubbles", "lines", "tables", "profiles", "vpspecs", "alerts")}
        await self.send({"type": "ind_tail" if tail else "ind", "id": iid, **res})

    async def range_profile(self, key: str, t1: int, t2: int, layout: str, rows: float, va: float, use_ib: bool = True,
                            kind: str = "frvp"):
        """Fixed Range Volume Profile for bars [t1, t2] of this chart (drawing tool). Uses 1m intrabars when the
        source has them for the whole range, else the chart bars. Replies {type: vprofile, key, profile}."""
        from . import volume_profile as vp
        if self.bars is None or not len(self.bars.time):
            return
        df = self.frame()
        ctx = self._script_ctx()
        tf = self.tf
        last_bar = int(self.bars.time.to_numpy()[-1])

        def work():
            t0 = pd.Timestamp(t1, unit="s")
            te = pd.Timestamp(t2, unit="s") + pd.Timedelta(seconds=tf)
            ib = ctx["lower_tf"](60) if use_ib and 60 < tf < 86400 else None
            bars, res = vp._pick_bars(df, ib, t0, te, tf, "auto")
            if bars.empty:
                return None
            first = int(df.index[df.index >= t0][0].value // 10**9)
            lastb = int(df.index[df.index < te][-1].value // 10**9)
            info = ctx["syminfo"]
            fn = vp.visible_range if kind == "vrvp" else vp.range_profile
            return fn(bars, first, lastb, tf, last_bar, layout, rows, va, float(info.get("mintick") or 0.01), res,
                      info.get("volume_note"))

        p = await asyncio.to_thread(work)
        await self.send({"type": "vprofile", "key": key, "profile": p})

    def _script_ctx(self) -> dict:
        from .symbols import syminfo_for
        loop = asyncio.get_running_loop()
        gen = self.gen

        def lower_tf(tf: int):
            """Runs in the script thread: fetch (cached LTF_TTL s) intrabars from this symbol's source."""
            if self.source == "sim":
                return None
            key = (gen, tf)
            hit = self.ltf_cache.get(key)
            if hit is None or time.time() - hit[0] > LTF_TTL:
                try:
                    fut = asyncio.run_coroutine_threadsafe(self._fetch_ltf(tf), loop)
                    d = fut.result(timeout=60)
                except Exception as e:
                    log.warning("lower timeframe %ss for %s failed: %s", tf, self.symbol, e)
                    d = hit[1] if hit else None
                self.ltf_cache = {k: v for k, v in self.ltf_cache.items() if k[0] == gen}
                self.ltf_cache[key] = hit = (time.time(), d)
            d = hit[1]
            if d is not None and self.rp:                   # bar replay: never show the future
                d = d[d.index < pd.Timestamp(int(self.bars.time.to_numpy()[-1]) + self.tf, unit="s")]
            return d

        def request(symbol, tf: int):
            """Runs in the script thread: bars of `symbol` (None = this chart's symbol, "VIX" = the volatility
            index for it) at tf seconds, cached REQ_TTL s. Returns None when no source has it."""
            if self.source == "sim":
                return None
            key = (gen, symbol, tf)
            hit = self.ltf_cache.get(key)
            if hit is None or time.time() - hit[0] > REQ_TTL:
                if symbol is None:
                    cands = [(self.source, self.src_symbol)]
                elif symbol == "VIX":
                    v = VIX_TICKERS.get((info.get("vix") or ""), [])
                    cands = sorted(v, key=lambda x: x[0] != self.source)
                else:
                    from .symbols import to_source
                    known = next((v for k, v in VIX_TICKERS.items()
                                  if symbol.upper() == k or any(symbol.upper() == s for _, s in v)), None)
                    if known:                                   # a volatility index typed by hand (NSE:INDIAVIX, ^VIX)
                        cands = sorted(known, key=lambda x: x[0] != self.source)
                    elif ":" in symbol:                         # EXCH:TICKER names live on TradingView
                        cands = [("tv", symbol), (self.source, to_source(symbol.split(":", 1)[1], self.source))]
                    else:
                        cands = [(self.source, to_source(symbol, self.source))]
                d = None
                for src, sym in cands:
                    try:
                        fut = asyncio.run_coroutine_threadsafe(self._fetch_other(src, sym, tf), loop)
                        d = fut.result(timeout=60)
                        if d is not None and not d.empty:
                            break
                    except Exception as e:
                        log.info("request %s %s %ss failed: %s", src, sym, tf, e)
                    d = None
                self.ltf_cache[key] = hit = (time.time(), d)
            d = hit[1]
            if d is not None and self.rp:
                d = d[d.index < pd.Timestamp(int(self.bars.time.to_numpy()[-1]) + self.tf, unit="s")]
            return d

        try:
            info = syminfo_for(self.symbol, self.source)
        except Exception:
            info = {}
        info["volume_note"] = self.volume_note()
        info["now"] = None if self.rp else time.time()       # replay: never use the wall clock
        def breadth():
            """NIFTY 50 breadth (share of stocks above open / VWAP) from the local 1m cache, or None."""
            sym = (self.symbol or "").upper()
            if self.source != "breeze" or not (sym == "NIFTY" or (sym.startswith("NIFTY ") and sym.endswith(" FUT"))):
                return None
            if self.bars is None or not len(self.bars.time):
                return None
            from .breadth import breadth_1m
            t = self.bars.time.to_numpy()
            d = breadth_1m("NIFTY", pd.Timestamp(int(t[0]), unit="s"), pd.Timestamp(int(t[-1]) + self.tf, unit="s"))
            if d is not None and self.rp:                       # bar replay: never show the future
                d = d[d.index < pd.Timestamp(int(t[-1]), unit="s")]
            return d

        def options():
            """Nearest-expiry index options 1m OI (core/options_oi.py) for this chart's days, or None.
            Kicks a non-blocking refresh of today's chain (live charts only, Breeze already logged in)."""
            from .options_oi import underlying_of, chain_1m, LIVE
            und = underlying_of(self.symbol) if self.source == "breeze" else None
            if not und or self.bars is None or not len(self.bars.time):
                return None
            t = self.bars.time.to_numpy()
            if not self.rp:
                try:
                    LIVE.kick(loop, und, float(self.bars.close.to_numpy()[-1]))
                except Exception as e:
                    log.info("options live kick: %s", e)
            d = chain_1m(und, pd.Timestamp(int(t[0]), unit="s"), pd.Timestamp(int(t[-1]) + self.tf, unit="s"))
            if d is not None and self.rp:                       # bar replay: never show the future
                d = d[d.time < int(t[-1]) + self.tf]
            return d

        return {"syminfo": info, "tf": self.tf, "lower_tf": lower_tf, "request": request, "breadth": breadth,
                "options": options}

    async def _fetch_other(self, source: str, sym: str, tf: int) -> pd.DataFrame:
        src = make_source(source)
        lb = None if source in ("breeze", "tv") else DEFAULT_LOOKBACK.get(source, {}).get(tf) or "3000"
        if source == "yf" and tf >= 86400:
            lb = "2y"
        return await src.history(sym, tf, lb)

    async def _fetch_ltf(self, tf: int) -> pd.DataFrame:
        if tf == 60 and self.source in ("breeze", "yf", "tv"):
            # 1m intrabars from the local candle cache first: for NIFTY/BANKNIFTY (Breeze) those files carry the
            # constituents' summed volume for finished days, which the raw index feed does not have.
            try:
                from datetime import timedelta
                from .candle_store import store_for
                store = self.store or store_for(self.source, self.symbol, self.src_symbol)
                if store is not None and self.bars is not None and len(self.bars.time):
                    a = pd.Timestamp(int(self.bars.time.to_numpy()[0]), unit="s").date()
                    b = pd.Timestamp(int(self.bars.time.to_numpy()[-1]), unit="s").date()
                    a = max(a, b - timedelta(days=LTF_CACHE_DAYS))   # older sessions fall back to chart bars
                    d = await store.ensure(a, b + timedelta(days=1))
                    if self.source == "breeze" and not getattr(self.src, "extended", False):
                        from .breeze import session_only
                        from .symbols import is_fno
                        d = session_only(d, is_fno(self.symbol))
                    if d is not None and len(d):
                        return d
            except Exception as e:
                log.info("1m cache for %s unavailable (%s); fetching", self.symbol, e)
        src = make_source(self.source)
        src.extended = getattr(self.src, "extended", False)
        lb = None if self.source in ("breeze", "tv") else DEFAULT_LOOKBACK.get(self.source, {}).get(tf) or "5000"
        return await src.history(self.src_symbol, tf, lb)

    # ------------------------------------------------------------ live
    async def _feed(self, gen: int):
        try:
            async for t in self.src.stream(self.src_symbol):
                if gen != self.gen:
                    return
                await self._fill_gap(t.ts, gen)
                if gen != self.gen:
                    return
                self.on_tick(t.ts, t.price, t.volume)
                await self.send({"type": "bar", "bar": self._bars_json(1)[0]})
                self.dirty = True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("stream failed (%s): %s; falling back to polling", self.source, e)
            await self.send({"type": "status", "msg": f"live stream unavailable ({type(e).__name__}); polling"})
            await self._poll(gen)

    async def _fill_gap(self, ts: float, gen: int):
        """A tick that would skip whole bars (history ended early, e.g. cache/API lag at load): fetch the missing
        bars from the source first, so the live bar is not drawn after an empty slot / price jump."""
        b = self.bars
        if b is None or not len(b) or self.tf >= 86400:
            return
        T = b.time[-1]
        k = int((ts - T) // self.tf)
        if k < 2 or getattr(self, "_gap_tried", None) == (gen, T):
            return
        self._gap_tried = (gen, T)
        lb = {"breeze": "1", "yf": "1d", "nse": "10d"}.get(self.source, str(min(k + 5, 500)))
        try:
            df = await asyncio.wait_for(self.src.history(self.src_symbol, self.tf, lb), 8)
        except Exception as e:
            log.info("gap fill %s failed: %s", self.symbol, e)
            return
        if gen != self.gen or df is None or df.empty:
            return
        if self.volume_src:
            df = df.assign(volume=math.nan)
        cur = int(T + k * self.tf)                       # the bar the tick belongs to stays tick-built
        ts_ = df.index.as_unit("s").asi8
        sent = 0
        for t_, o, h, l, c, v in zip(ts_, *(df[x] for x in ("open", "high", "low", "close", "volume"))):
            t_ = int(t_)
            if t_ == T and not v:                        # keep the live/summed volume of the current last bar
                v = math.nan
            if T <= t_ < cur and self.upsert_bar(t_, o, h, l, c, v):
                await self.send({"type": "bar", "bar": self._bars_json(1)[0]})
                sent += 1
        if sent:
            self.dirty = True
            log.info("gap fill %s: %d bar(s)", self.symbol, sent)

    async def _poll(self, gen: int):
        """Fallback: re-fetch recent history periodically and upsert the last bars."""
        period = POLL_SEC.get(self.source, 15.0)
        short = {"yf": "1d" if self.tf < 86400 else "5d", "nse": "10d", "ccxt": "5"}.get(self.source, "5")
        while gen == self.gen:
            await asyncio.sleep(period)
            try:
                df = await self.src.history(self.src_symbol, self.tf, short)
            except Exception as e:
                await self.send({"type": "status", "msg": f"poll failed: {e}"})
                continue
            if self.volume_src:
                df = df.assign(volume=math.nan)
            ts = df.index.as_unit("s").asi8
            changed = 0
            for t, o, h, l, c, v in zip(ts[-TAIL:], *(df[k].iloc[-TAIL:] for k in ("open", "high", "low", "close", "volume"))):
                changed += self.upsert_bar(int(t), o, h, l, c, v)
            if changed:
                for bar in self._bars_json(TAIL):
                    await self.send({"type": "bar", "bar": bar})
                self.dirty = True

    async def _proxy_volume(self, gen: int, proxy: str):
        """Refresh the volume of recent bars from the proxy ETF (index ticks carry no volume)."""
        short = "1d" if self.tf < 86400 else "5d"
        while gen == self.gen:
            await asyncio.sleep(PROXY_POLL)
            try:
                pv = await self.src.history(proxy, self.tf, short)
            except Exception as e:
                log.warning("volume proxy poll failed: %s", e)
                continue
            b = self.bars
            n = min(len(b), 5)
            times = b.time.to_numpy()[-n:]
            vols = pv["volume"].set_axis(pv.index.as_unit("s").asi8)
            changed = False
            for k, t in enumerate(times):
                v = vols.get(int(t))
                if v is not None and v == v:
                    i = len(b) - n + k
                    if b.volume[i] != v:
                        b.volume._buf[b.volume._phys(i)] = float(v)
                        changed = True
            if changed:
                for bar in self._bars_json(n):
                    await self.send({"type": "bar", "bar": bar})

    async def _index_volume(self, gen: int):
        """Index volume = sum of constituents' volume (Breeze history + live ticks).

        The history part runs once in BreezeHub and is shared across page refreshes."""
        from .breeze import BASE_FOR_TF, BreezeHub, resample, tick_fields
        hub = BreezeHub.get()
        base = BASE_FOR_TF[self.tf]
        st = hub.index_volume(self.src_symbol, base)
        sent_ver = st["ver"]

        def as_tf(v):
            if base != self.tf and len(v):
                v = resample(pd.DataFrame({k: v for k in ("open", "high", "low", "close", "volume")}), self.tf)["volume"]
            return v

        async def send_bars(v, src):
            self._set_volumes(v)
            if self.tfstore is not None and len(v):        # keep the computed volume in the timeframe's cache file
                try:
                    async with self.tfstore.lock:
                        f = self.tfstore.read()
                        hit = f.index.intersection(v.index)
                        if len(hit):
                            f.loc[hit, "volume"] = v.reindex(hit).to_numpy()
                            self.tfstore.write(f)
                except Exception as e:
                    log.debug("persist index volume: %s", e)
            want = set(v.index.as_unit("s").asi8.tolist())
            bars = [[t, v_] for t, v_ in zip(map(int, self.bars.time.to_numpy()), self.bars.volume.to_numpy()) if t in want]
            await self.send({"type": "volume", "src": src, "bars": bars})
            for iid in list(self.indicators):
                await self.compute(iid)

        async def push():
            nonlocal sent_ver
            sent_ver = st["ver"]
            if len(st["series"]):
                await send_bars(as_tf(st["series"]), f"{len(st['infos'])}/{st['total']} constituents")

        async def stream(seg):
            """Send a completed window newest-first in day (intraday) or month (daily) slices."""
            v = as_tf(seg)
            if not len(v):
                return
            n = len(v)
            size = max(1, -(-n // 12))                      # at most ~12 slices per window
            for end in range(n, 0, -size):
                if gen != self.gen:
                    return
                await send_bars(v.iloc[max(0, end - size):end], f"loading {st['window']}/{st['windows'] or '?'} periods")
                await asyncio.sleep(0.05)

        sent, seen = 0, None
        if st["finished"]:                   # cached (memory or disk snapshot): one shot
            await push()
            sent = len(st["segments"])
        while gen == self.gen:
            segs = st["segments"]
            if sent < len(segs):
                for seg in segs[sent:]:
                    await stream(seg)
                sent = len(segs)
                continue
            if st["finished"]:
                if sent_ver == st["ver"]:
                    break
                sent_ver = st["ver"]
                await self.send({"type": "volume", "src": f"{len(st['infos'])}/{st['total']} constituents", "bars": []})
                break
            prog = (st.get("window", 0), st["done"])
            if prog != seen:
                seen = prog
                await self.send({"type": "status", "msg": f"volume: period {st.get('window', 0) + 1}/{st.get('windows') or '?'} · {st['done']}/{st['total'] or '?'} stocks…"})
            await asyncio.sleep(0.5)
        if gen != self.gen:
            return
        # live: daily cumulative traded qty deltas from each constituent's ticks
        last_ttq: Dict[str, float] = {}
        cbs = []
        for info in st["infos"]:
            tok = info.get("token")
            if not tok:
                continue

            def cb(t, tok=tok):
                q = tick_fields(t)["ttq"]
                if q != q:
                    return
                prev = last_ttq.get(tok)
                last_ttq[tok] = q
                if prev is not None and q > prev and gen == self.gen:
                    self.add_volume(time.time(), q - prev)
            await hub.subscribe(tok, cb)
            cbs.append((tok, cb))
        try:
            while gen == self.gen:
                await asyncio.sleep(1)
                if st["ver"] != sent_ver and gen == self.gen:   # snapshot was refreshed in the background
                    await push()
        finally:
            for tok, cb in cbs:
                await hub.unsubscribe(tok, cb)

    def _tf_volume_cached(self) -> bool:
        """30m and up: the timeframe file already holds index volume for the finished days."""
        if self.tfstore is None or self.full is None or not len(self.full):
            return False
        from datetime import datetime, timezone
        midnight = pd.Timestamp(datetime.now(timezone.utc).date())
        past = self.full[self.full.index < midnight]
        return len(past) > 0 and float((past["volume"] > 0).mean()) > 0.95

    async def _today_index_volume(self, gen: int):
        """Index volume for today from the app-wide keeper (core/index_volume.py): it sums the constituents once
        per day into the index's 1m file and adds live ticks, so loading a chart makes no constituent calls."""
        from datetime import datetime, timezone
        from .breeze import session_only
        from .candle_store import to_tf
        from .index_volume import keep
        k = keep(self.symbol, self.src_symbol)
        if not k.ready.is_set():
            await self.send({"type": "status", "msg": f"volume: today · {k.status}…"})
            await k.ready.wait()
        if gen != self.gen:
            return

        async def push(first: bool):
            tot = k.series()
            if not getattr(self.src, "extended", False):
                tot = session_only(tot, False)
            if self.bars is None or not len(self.bars) or not len(tot):
                return
            last_t = int(self.bars.time[-1])
            today = datetime.now(timezone.utc).date()
            if self.tf >= 86400:                         # daily / weekly: today's total on the last bar
                if pd.Timestamp(last_t, unit="s").date() < (today if self.tf == 86400 else today - pd.Timedelta(days=7)):
                    return
                v = pd.Series([float(tot.sum())], index=pd.DatetimeIndex([pd.Timestamp(last_t, unit="s")]))
            else:
                v = to_tf(pd.DataFrame({"open": tot, "high": tot, "low": tot, "close": tot, "volume": tot}), self.tf)["volume"]
            self._set_volumes(v)
            want = set(v.index.as_unit("s").asi8.tolist())
            bars = [[t, x] for t, x in zip(map(int, self.bars.time.to_numpy()), self.bars.volume.to_numpy()) if t in want]
            await self.send({"type": "volume", "src": f"{len(k.names)} constituents (cached)", "bars": bars})
            for iid in list(self.indicators):
                await self.compute(iid)

        await push(True)
        if k.final or gen != self.gen:
            return
        reload = asyncio.Event()

        def cb(ts, dv):
            if gen != self.gen:
                return
            if ts is None:                               # keeper re-summed today (backfill / after-close exact numbers)
                reload.set()
            else:
                self.add_volume(ts, dv)
        k.listen(cb)
        try:
            while gen == self.gen and not (k.task and k.task.done()):
                try:
                    await asyncio.wait_for(reload.wait(), 5)
                except asyncio.TimeoutError:
                    continue
                reload.clear()
                await push(False)
            if gen == self.gen:
                await push(False)                        # final numbers
        finally:
            k.unlisten(cb)

    async def _store_index_volume(self, gen: int, start):
        """Index candles have no volume: for each past day on the chart, sum the constituents' 1m volume
        (their own 1m files are cached too), write it into the index's 1m files and push it to the chart."""
        from datetime import datetime, timedelta, timezone
        from .breeze import BreezeHub, session_only
        from .candle_store import store_for, to_tf
        store, hub = self.store, BreezeHub.get()
        today = datetime.now(timezone.utc).date()
        done = set(store.meta.get("ivol", []))
        days = [start + timedelta(days=i) for i in range((today - start).days)]
        complete = set(store.meta.get("done", []))      # only finished days: today's file is still rewritten
        days = [d for d in days if d.isoformat() not in done and d.isoformat() in complete][::-1]   # newest first
        if not days:
            return
        try:
            names = await hub.constituents(self.src_symbol)
        except Exception as e:
            log.warning("index volume: constituents of %s: %s", self.src_symbol, e)
            return
        sem = asyncio.Semaphore(6)
        for k in range(0, len(days), 2):                  # two days per round (one Breeze request per stock)
            chunk = days[k:k + 2]
            a, b = min(chunk), max(chunk)
            vols = []

            async def one(name):
                async with sem:
                    try:
                        cs = store_for("breeze", name, name)
                        df = await cs.ensure(a, b)
                        if len(df):
                            vols.append(df["volume"])
                    except Exception as e:
                        log.info("index volume: %s %s..%s: %s", name, a, b, e)
            await self.send({"type": "status", "msg": f"volume: {a:%d %b} · summing {len(names)} stocks…"})
            await asyncio.gather(*(one(n) for n in names))
            if gen != self.gen:
                return
            if not vols:
                continue
            tot = pd.concat(vols, axis=1).sum(axis=1, min_count=1).dropna()
            for d in chunk:
                day = store._read_day(d)
                if not len(day):
                    continue
                day["volume"] = tot.reindex(day.index).fillna(0.0).to_numpy()
                store._write_day(d, day)
                done.add(d.isoformat())
            store.meta["ivol"] = sorted(done)
            store._save_meta()
            v = session_only(tot, False) if not getattr(self.src, "extended", False) else tot
            v = to_tf(pd.DataFrame({"open": v, "high": v, "low": v, "close": v, "volume": v}), self.tf)["volume"]
            if self.bars is not None and len(v):
                self._set_volumes(v)
                want = set(v.index.as_unit("s").asi8.tolist())
                bars = [[t, x] for t, x in zip(map(int, self.bars.time.to_numpy()), self.bars.volume.to_numpy()) if t in want]
                await self.send({"type": "volume", "src": f"{len(vols)}/{len(names)} constituents", "bars": bars})
                for iid in list(self.indicators):
                    await self.compute(iid)
        await self.send({"type": "status", "msg": "Breeze · older days' volume saved"})

    def _set_volumes(self, vol: pd.Series):
        """Write volumes onto bars with matching times (vol indexed by UTC-naive timestamps)."""
        b = self.bars
        by_t = dict(zip(vol.index.as_unit("s").asi8.tolist(), vol.to_numpy().tolist()))
        times = b.time.to_numpy()
        for i, t in enumerate(times):
            v = by_t.get(int(t))
            if v is not None:
                b.volume._buf[b.volume._phys(i)] = float(v)

    def add_volume(self, ts: float, dv: float):
        b = self.bars
        if b is not None and len(b) and ts >= b.time[-1]:
            b.volume.update_last(b.volume[-1] + dv)
            self.vol_dirty = True

    async def _calc_loop(self, gen: int):
        while gen == self.gen:
            await asyncio.sleep(THROTTLE)
            if self.vol_dirty:
                self.vol_dirty = False
                await self.send({"type": "bar", "bar": self._bars_json(1)[0]})
            if self.dirty and self.indicators:
                self.dirty = False
                for iid in list(self.indicators):
                    await self.compute(iid, tail=TAIL)

    async def close(self):
        self.gen += 1
        await self.stop_feed()
