"""
Watchlist quotes: last price, change and % change per symbol, pushed to the browser.

  breeze  websocket ticks (BreezeHub), initial value from REST quote
  yf      yfinance fast_info polling
  nse     jugaad-data NSELive polling
  ccxt    fetch_ticker polling
  sim     random walk
"""
from __future__ import annotations

import asyncio
import time
import logging
import random
from typing import Dict

log = logging.getLogger("ltv.quotes")
POLL = {"yf": 15.0, "nse": 10.0, "ccxt": 5.0, "sim": 1.0}
FLUSH = 0.5


def _yf_quote(sym):
    import yfinance as yf
    fi = yf.Ticker(sym).fast_info
    return float(fi["lastPrice"]), float(fi["previousClose"])


def _nse_quote(sym):
    from jugaad_data.nse import NSELive
    p = NSELive().stock_quote(sym)["priceInfo"]
    return float(p["lastPrice"]), float(p["previousClose"])


def _ccxt_quote(sym, exchange="binance"):
    import ccxt
    t = getattr(ccxt, exchange)().fetch_ticker(sym)
    last, pct = float(t["last"]), float(t.get("percentage") or 0)
    return last, last / (1 + pct / 100)


class QuoteWatcher:
    def __init__(self, send):
        self.send = send
        self.tasks: Dict[str, asyncio.Task] = {}
        self.pending: Dict[str, dict] = {}
        self.flusher = asyncio.create_task(self._flush())

    async def set(self, items):
        from .symbols import to_source
        want = {}
        for i in items:
            key = f"{i['source']}:{i['symbol']}"
            try:
                want[key] = (i["source"], to_source(i["symbol"], i["source"]))
            except ValueError as e:
                self.pending[key] = {"key": key, "error": str(e)}
        for key in list(self.tasks):
            if key not in want:
                self.tasks.pop(key).cancel()
        for key, (src, sym) in want.items():
            if key not in self.tasks:
                runner = self._breeze if src == "breeze" else self._tv if src == "tv" else self._poll
                self.tasks[key] = asyncio.create_task(self._guard(key, runner(key, src, sym)))

    async def _guard(self, key, coro):
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("quote %s failed: %s", key, e)
            self.pending[key] = {"key": key, "error": f"{type(e).__name__}: {e}"[:120]}

    def _put(self, key, last, prev, stale=False):
        if last is None or last != last or last <= 0:
            return
        chg = last - prev if prev and prev == prev else None
        self.pending[key] = {"key": key, "last": last, "prev": prev, "chg": chg,
                             "pct": (chg / prev * 100) if chg is not None and prev else None,
                             "stale": stale, "t": time.time()}

    async def _flush(self):
        while True:
            await asyncio.sleep(FLUSH)
            if self.pending:
                items, self.pending = list(self.pending.values()), {}
                try:
                    await self.send({"type": "quotes", "items": items})
                except Exception:
                    return

    async def _breeze(self, key, src, sym):
        from .breeze import BreezeHub, tick_fields
        hub = BreezeHub.get()
        info = await hub.resolve(sym)
        state = {"prev": None}
        q = None
        try:
            q = await hub.quote(info["isec"], info.get("fno"))
        except Exception as e:
            log.warning("breeze quote %s: %s", sym, e)
        stale = False
        if not q or not q.get("last") or not q.get("prev"):
            # F&O quotes often come back empty after hours. The daily bar only fills the GAP: its close is the last
            # finished session's close, not a live price, so it never replaces a live LTP and is flagged stale
            # (paper-trade SL/target checks ignore stale prices).
            d = await self._breeze_daily(hub, info, sym)
            if d and q and q.get("last"):
                q = {**q, "prev": q.get("prev") or d.get("prev") or d.get("last")}
            elif d:
                q, stale = d, True
        if q and q.get("last"):
            state["prev"] = q.get("prev") or None
            self._put(key, q["last"], state["prev"], stale)
        else:
            self.pending[key] = {"key": key, "error": "no quote from Breeze"}
        if not info.get("token"):
            return

        def cb(t):
            f = tick_fields(t)
            if f["prev"] == f["prev"] and f["prev"]:
                state["prev"] = f["prev"]
            self._put(key, f["last"], state["prev"])

        await hub.subscribe(info["token"], cb)
        try:
            await asyncio.Event().wait()
        finally:
            await hub.unsubscribe(info["token"], cb)

    @staticmethod
    async def _breeze_daily(hub, info, sym):
        """Last price and previous close from the last two daily bars."""
        from datetime import date, timedelta
        try:
            df = await hub._call_hist(info["isec"], "1day", date.today() - timedelta(days=10), date.today(), info.get("fno"))
        except Exception as e:
            log.warning("breeze daily %s: %s", sym, e)
            return None
        df = df.dropna(subset=["close"])
        if df.empty:
            return None
        return {"last": float(df["close"].iloc[-1]), "prev": float(df["close"].iloc[-2]) if len(df) > 1 else None}

    async def _tv(self, key, src, sym):
        from .tradingview import TVHub, quote_of
        hub = TVHub.get()

        def cb(st):
            q = quote_of(st)
            if q:
                self._put(key, q[0], q[1])

        await hub.subscribe(sym, cb)
        try:
            await asyncio.Event().wait()
        finally:
            await hub.unsubscribe(sym, cb)

    async def _poll(self, key, src, sym):
        if src == "sim":
            prev = last = 100.0
            while True:
                last *= 1 + random.gauss(0, 0.0008)
                self._put(key, round(last, 2), prev)
                await asyncio.sleep(POLL["sim"])
        fn = {"yf": _yf_quote, "nse": _nse_quote, "ccxt": _ccxt_quote}.get(src)
        if fn is None:
            return
        while True:
            try:
                last, prev = await asyncio.to_thread(fn, sym)
                self._put(key, last, prev)
            except Exception as e:
                self.pending[key] = {"key": key, "error": f"{type(e).__name__}"}
                log.debug("quote %s: %s", key, e)
            await asyncio.sleep(POLL[src])

    async def close(self):
        self.flusher.cancel()
        for t in self.tasks.values():
            t.cancel()
        self.tasks.clear()
