"""
Server-side paper order engine: index-triggered option entries, tolerance-band limit entries and index-based exits.
Runs inside the app (no browser needed). Simulated only: nothing is ever sent to a broker.

Trades handled here carry engine="server" (see paper.open_trade). Lifecycle of one order:

  ARMED     waiting for an index candle (cond.tf) to CLOSE above / below cond.level.
            Only closed candles count (no look-ahead): a candle closes when the clock passes its end.
            A candle with a feed gap (no index tick in the last GAP_S seconds of it) is ignored.
  TRIGGERED signal candle recorded. Market entry -> filled at once (ask for buys / bid for sells).
            Band entry -> waits until the option's executable price (ask for buys, bid for sells; LTP when the
            book is empty) is inside [lo, hi]; it then fills at that price (never outside the band).
            If the index SL or target condition happens before the fill, the order is cancelled (move invalid / missed).
  OPEN      exits: index SL on candle close, index target on index tick, option-premium SL / target on option tick.
            Exits are market orders priced from a fresh Breeze quote (bid for long, ask for short).
  Unfilled orders expire at the end of the F&O session (day orders).

Index rules (bull = long CE / short PE, bear = long PE / short CE):
  sl.mode prevLow   bull: a closed candle's close < the previous closed candle's low   (bear: close > previous high)
  sl.mode prevClose bull: close < previous candle's close                              (bear: close > previous close)
  sl.mode index     bull: close < sl.value                                             (bear: close > sl.value)
  target.mode range bull: index >= signal close + k * (signal high - signal low)       (bear: <= close - k * range)
  target.mode index bull: index >= target.value                                        (bear: <= target.value)
  premium modes use trade.sl / trade.target on the option LTP.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Callable, Dict, List, Optional

log = logging.getLogger("paper.engine")
ALGO = "paper-engine-1"
GRACE_S = 1.5          # wait after a candle's end before closing it (late ticks)
GAP_S = 30.0           # a candle whose last index tick is older than this before its end has a feed gap
CONFIRM_EVERY = 2.0    # at most one REST quote per order per this many seconds
POLL_EVERY = 8.0       # REST quote fallback for band entries when no option ticks arrive
FNO_END = 15 * 3600 + 30 * 60 - 19800   # 15:30 IST (UTC seconds of day): unfilled day orders expire


def valid_until(created: float) -> float:
    """Day order: end of the F&O session on the day it was placed (next weekday when placed after the close)."""
    day = created - created % 86400
    if created % 86400 >= FNO_END:
        day += 86400
    while time.gmtime(day).tm_wday >= 5:
        day += 86400
    return day + FNO_END


def bullish(t: dict) -> bool:
    return (t["side"] == "buy") == str(t["symbol"]).endswith("CE")


def bucket(ts: float, tf: int, s0: int, s1: int) -> Optional[tuple]:
    """(start, end) of the session-anchored candle holding ts, or None outside the session."""
    day, sod = ts - ts % 86400, ts % 86400
    if not (s0 <= sod < s1):
        return None
    start = day + s0 + int((sod - s0) // tf) * tf
    return start, min(start + tf, day + s1)


class Candles:
    """Live candles of one index at one timeframe, built from ticks (seeded from today's 1-minute history)."""

    def __init__(self, tf: int, s0: int, s1: int):
        self.tf, self.s0, self.s1 = tf, s0, s1
        self.cur: Optional[dict] = None
        self.closed: deque = deque(maxlen=50)
        self.last_px: Optional[float] = None
        self.last_at = 0.0

    def seed(self, bars: List[tuple], now: float) -> None:
        """bars: completed 1-minute (t, o, h, l, c) of today, oldest first."""
        for t, o, h, l, c in bars:
            if t + 60 > now:
                continue
            b = bucket(t, self.tf, self.s0, self.s1)
            if not b:
                continue
            if self.cur and self.cur["t"] != b[0]:
                self.closed.append({**self.cur, "seeded": True})
                self.cur = None
            if not self.cur:
                self.cur = {"t": b[0], "end": b[1], "o": o, "h": h, "l": l, "c": c, "last": t + 59, "n": 0}
            else:
                self.cur.update(h=max(self.cur["h"], h), l=min(self.cur["l"], l), c=c, last=t + 59)
        if self.cur and self.cur["end"] <= now:            # seeded bucket already finished: history only
            self.closed.append({**self.cur, "seeded": True})
            self.cur = None

    def tick(self, px: float, now: float) -> List[dict]:
        out = self.roll(now, grace=0.0)
        b = bucket(now, self.tf, self.s0, self.s1)
        self.last_px, self.last_at = px, now
        if not b:
            return out
        if self.cur and self.cur["t"] != b[0]:
            out += self.roll(now, grace=0.0, force=True)
        if not self.cur:
            self.cur = {"t": b[0], "end": b[1], "o": px, "h": px, "l": px, "c": px, "last": now, "n": 1}
        else:
            c = self.cur
            c.update(h=max(c["h"], px), l=min(c["l"], px), c=px, last=now, n=c["n"] + 1)
        return out

    def roll(self, now: float, grace: float = GRACE_S, force: bool = False) -> List[dict]:
        """Close the current candle once the clock is past its end. Returns newly closed candles."""
        c = self.cur
        if not c or (not force and now < c["end"] + grace):
            return []
        c = {**c, "gap": c["end"] - c["last"] > GAP_S, "closedAt": now}
        self.closed.append(c)
        self.cur = None
        return [c]


class Feed:
    """Market data the engine needs. The real one wraps BreezeHub; tests pass a fake."""

    async def subscribe(self, symbol: str, cb: Callable[[float], None]) -> Callable:  # returns an unsubscribe coroutine fn
        raise NotImplementedError

    async def quote(self, symbol: str) -> Optional[dict]:
        raise NotImplementedError

    async def minutes(self, symbol: str) -> List[tuple]:
        return []

    def ready(self) -> bool:
        return True


class BreezeFeed(Feed):
    def _hub(self):
        from .breeze import BreezeHub
        hub = BreezeHub.get()
        return hub if hub.breeze is not None else None

    def ready(self) -> bool:
        return self._hub() is not None

    async def subscribe(self, symbol, cb):
        from .breeze import tick_fields
        from .symbols import to_source
        hub = self._hub()
        info = await hub.resolve(to_source(symbol, "breeze"))
        if not info.get("token"):
            raise RuntimeError(f"no stream token for {symbol}")

        def on(t):
            px = tick_fields(t)["last"]
            if px == px and px > 0:
                cb(px)

        await hub.subscribe(info["token"], on)

        async def off():
            await hub.unsubscribe(info["token"], on)
        return off

    async def quote(self, symbol):
        from .paper import quote
        return await quote(symbol)

    async def minutes(self, symbol):
        from datetime import date
        from .breeze import session_only
        from .symbols import to_source
        hub = self._hub()
        info = await hub.resolve(to_source(symbol, "breeze"))
        df = session_only(await hub._call_hist(info["isec"], "1minute", date.today(), date.today(), info.get("fno")))
        ts = df.index.as_unit("s").asi8
        return [(int(t), float(r.open), float(r.high), float(r.low), float(r.close)) for t, r in zip(ts, df.itertuples())]


class Engine:
    _inst: Optional["Engine"] = None

    @classmethod
    def get(cls) -> "Engine":
        if cls._inst is None:
            cls._inst = Engine(BreezeFeed())
        return cls._inst

    def __init__(self, feed: Feed, store=None, clock=time.time):
        from . import paper
        self.feed, self.clock = feed, clock
        self.store = store or paper        # load / save / _lock
        self.candles: Dict[tuple, Candles] = {}
        self.subs: Dict[str, Callable] = {}
        self.px: Dict[str, tuple] = {}     # symbol -> (last, at)
        self.next_q: Dict[str, float] = {}
        self.rev = 0
        self.msgs: deque = deque(maxlen=200)    # (seq, text, trade id)
        self.seq = 0
        self.task: Optional[asyncio.Task] = None
        self.note = ""
        self._busy: set = set()
        self.wake = asyncio.Event()

    # ------------------------------------------------------------ storage helpers (disk I/O off the loop)
    async def trades(self) -> List[dict]:
        return await asyncio.to_thread(self.store.load)

    async def mutate(self, tid: str, fn: Callable[[dict], Optional[str]]) -> Optional[dict]:
        """Apply fn to the stored trade under the paper lock. fn returns a message (or None)."""
        def work():
            with self.store._lock:
                all_ = self.store.load()
                t = next((x for x in all_ if x["id"] == tid), None)
                if t is None:
                    return None, None
                msg = fn(t)
                self.store.save(all_)
                return t, msg
        t, msg = await asyncio.to_thread(work)
        if t is not None:
            self.changed(msg, tid)
        return t

    def changed(self, msg: Optional[str] = None, tid: Optional[str] = None) -> None:
        self.rev += 1
        if msg:
            self.seq += 1
            self.msgs.append({"seq": self.seq, "text": msg, "id": tid, "t": self.clock()})
        self.wake.set()

    def sync(self, rev: int, seq: int) -> dict:
        return {"rev": self.rev, "seq": self.seq, "msgs": [m for m in self.msgs if m["seq"] > seq], "note": self.note}

    # ------------------------------------------------------------ main loop
    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run())

    async def run(self) -> None:
        while True:
            try:
                await self.step()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("paper engine step")
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), 1.0 if self.subs or self.candles else 5.0)
            except asyncio.TimeoutError:
                pass

    def active(self, trades: List[dict]) -> List[dict]:
        return [t for t in trades if t.get("engine") == "server" and t["status"] in ("pending", "open")]

    async def step(self) -> None:
        act = self.active(await self.trades())
        if not act:
            await self._unsubscribe_all(keep=set())
            self.note = ""
            return
        if not self.feed.ready():
            self.note = "Breeze not connected: server orders are waiting"
            return
        self.note = ""
        now = self.clock()
        want = set()
        for t in act:
            want.add(t["symbol"])
            if t.get("cond"):
                want.add(t["cond"]["under"])
                await self._candles(t["cond"]["under"], int(t["cond"]["tf"]))
        await self._unsubscribe_all(keep=want)
        for s in want:
            if s not in self.subs:
                await self._subscribe(s)
        for (under, tf), cs in list(self.candles.items()):
            for c in cs.roll(now):
                await self.on_candle(under, tf, c)
        for t in self.active(await self.trades()):
            await self.check(t, now)

    async def _candles(self, under: str, tf: int) -> Candles:
        key = (under, tf)
        if key not in self.candles:
            from .breeze import _s0, _s1
            cs = self.candles[key] = Candles(tf, _s0, _s1)
            try:
                cs.seed(await self.feed.minutes(under), self.clock())
            except Exception as e:
                log.info("seed %s %ss: %s", under, tf, e)
        return self.candles[key]

    async def _subscribe(self, sym: str) -> None:
        def cb(px, sym=sym):
            now = self.clock()
            self.px[sym] = (px, now)
            for (under, tf), cs in self.candles.items():
                if under == sym:
                    for c in cs.tick(px, now):
                        asyncio.get_running_loop().create_task(self.on_candle(under, tf, c))
            self.wake.set()
        try:
            self.subs[sym] = await self.feed.subscribe(sym, cb)
        except Exception as e:
            log.info("engine subscribe %s: %s", sym, e)

    async def _unsubscribe_all(self, keep: set) -> None:
        for s in [s for s in self.subs if s not in keep]:
            off = self.subs.pop(s)
            try:
                await off()
            except Exception:
                pass
        for k in [k for k in self.candles if k[0] not in keep]:
            self.candles.pop(k)

    # ------------------------------------------------------------ candle close: entry triggers and index SL
    async def on_candle(self, under: str, tf: int, c: dict) -> None:
        for t in self.active(await self.trades()):
            cond = t.get("cond")
            if not cond or cond["under"] != under or int(cond["tf"]) != tf or (c["end"] <= (t.get("createdAt") or 0)):
                continue
            if c.get("gap"):
                await self.mutate(t["id"], lambda x: x["events"].append({"t": self.clock(), "e": "candle-gap", "candle": c["t"],
                                                                         "note": "feed gap: candle ignored"}))
                continue
            if cond.get("phase") == "armed":
                hit = c["c"] > cond["level"] if cond["dir"] == "above" else c["c"] < cond["level"]
                if hit:
                    await self.trigger(t, c)
                continue
            await self.index_sl(t, c)

    async def trigger(self, t: dict, c: dict) -> None:
        sig = {k: c[k] for k in ("t", "end", "o", "h", "l", "c")}
        bull = bullish(t)

        def fn(x):
            cond = x["cond"]
            if cond.get("phase") != "armed":
                return None
            cond.update(phase="triggered", signal=sig, triggeredAt=self.clock())
            r = x.get("rules") or {}
            sl, tg = r.get("sl") or {}, r.get("target") or {}
            if sl.get("mode") in ("prevLow", "prevClose"):
                x["idxSl"] = sig["l" if bull else "h"] if sl["mode"] == "prevLow" else sig["c"]
            elif sl.get("mode") == "index":
                x["idxSl"] = sl.get("value")
            if tg.get("mode") == "range":
                rng = sig["h"] - sig["l"]
                x["idxTarget"] = round(sig["c"] + (1 if bull else -1) * float(tg.get("k") or 2) * rng, 2) if rng > 0 else None
            elif tg.get("mode") == "index":
                x["idxTarget"] = tg.get("value")
            x["events"].append({"t": self.clock(), "e": "triggered", "candle": sig, "idxSl": x.get("idxSl"), "idxTarget": x.get("idxTarget")})
            return (f"⚡ {cond['under']} closed {cond['dir']} {cond['level']:g} at {sig['c']:g}: "
                    f"{'buying' if x['side'] == 'buy' else 'selling'} {x['symbol']}")
        t = await self.mutate(t["id"], fn)
        if t:
            await self.check(t, self.clock(), force=True)

    async def index_sl(self, t: dict, c: dict) -> None:
        mode = ((t.get("rules") or {}).get("sl") or {}).get("mode")
        if mode not in ("prevLow", "prevClose", "index") or t.get("idxSl") is None:
            return
        bull = bullish(t)
        sl = t["idxSl"]
        hit = c["c"] < sl if bull else c["c"] > sl
        live = t["status"] == "open" and c["end"] > (t.get("entryAt") or 0)
        if hit and (live or t["status"] == "pending"):
            if t["status"] == "pending":
                await self.cancel(t["id"], "invalidated", f"✖ {t['symbol']} entry cancelled: index closed {c['c']:g} beyond SL {sl:g} before the fill")
            else:
                await self.exit(t, "sl", f"index closed {c['c']:g} {'below' if bull else 'above'} {sl:g}")
            return
        if mode in ("prevLow", "prevClose"):          # trail to the candle that just closed
            nxt = (c["l"] if bull else c["h"]) if mode == "prevLow" else c["c"]
            if nxt != sl:
                await self.mutate(t["id"], lambda x: x.update(idxSl=nxt))

    # ------------------------------------------------------------ per-step checks: fills, ticks, expiry
    async def check(self, t: dict, now: float, force: bool = False) -> None:
        if t["id"] in self._busy:
            return
        self._busy.add(t["id"])
        try:
            await self._check(t, now, force)
        finally:
            self._busy.discard(t["id"])

    async def _check(self, t: dict, now: float, force: bool) -> None:
        bull = bullish(t)
        cond = t.get("cond")
        if t["status"] == "pending":
            if now >= (t.get("validUntil") or float("inf")):
                await self.cancel(t["id"], "expired", f"⌛ {t['symbol']} order expired unfilled (day order)")
                return
            if cond and cond.get("phase") == "armed":
                return
            ix = self.px.get(cond["under"]) if cond else None
            tgt = t.get("idxTarget")
            if ix and tgt is not None and (ix[0] >= tgt if bull else ix[0] <= tgt):
                await self.cancel(t["id"], "missed", f"✖ {t['symbol']} entry cancelled: index reached target {tgt:g} before the fill")
                return
            await self.try_fill(t, now, force)
            return
        # open: index target on tick, premium SL / target on option tick
        if cond:
            ix = self.px.get(cond["under"])
            tgt = t.get("idxTarget")
            if ix and tgt is not None and ix[1] > (t.get("entryAt") or 0) and (ix[0] >= tgt if bull else ix[0] <= tgt):
                await self.exit(t, "target", f"index {ix[0]:g} reached {tgt:g}")
                return
        op = self.px.get(t["symbol"])
        if op and op[1] > (t.get("entryAt") or 0):
            long = t["side"] == "buy"
            if t.get("sl") is not None and (op[0] <= t["sl"] if long else op[0] >= t["sl"]):
                await self.exit(t, "sl", f"premium {op[0]:g} crossed SL {t['sl']:g}", confirm=("sl", t["sl"]))
            elif t.get("target") is not None and (op[0] >= t["target"] if long else op[0] <= t["target"]):
                await self.exit(t, "target", f"premium {op[0]:g} reached {t['target']:g}", confirm=("target", t["target"]))

    async def try_fill(self, t: dict, now: float, force: bool) -> None:
        band = t.get("band")
        op = self.px.get(t["symbol"])
        if not force:
            # REST quotes are rate limited: confirm at most every CONFIRM_EVERY s when the streamed LTP is near the
            # band (or for market entries), else poll slowly in case option ticks are missing
            last = self.next_q.get(t["id"], 0)
            near = not band or band.get("lo") is None or (op and band["lo"] * 0.98 <= op[0] <= band["hi"] * 1.02)
            if now < last + (CONFIRM_EVERY if near else POLL_EVERY):
                return
        self.next_q[t["id"]] = now
        q = await self.feed.quote(t["symbol"])
        if not q:
            return
        long = t["side"] == "buy"
        px = float((q.get("ask") if long else q.get("bid")) or q["last"])
        if band and band.get("lo") is None:          # anchor at trigger: band is set from this first quote
            c = px
            lo, hi = round(c * (1 - band["pct"] / 100), 2), round(c * (1 + band["pct"] / 100), 2)

            def setb(x):
                x["band"].update(center=c, lo=lo, hi=hi)
                x["limit"] = hi if long else lo
                x["events"].append({"t": self.clock(), "e": "band", "center": c, "lo": lo, "hi": hi})
                return f"{t['symbol']} limit range {lo:g} – {hi:g} (±{band['pct']:g}% of {c:g})"
            t = await self.mutate(t["id"], setb)
            band = t["band"]
        if band and not (band["lo"] <= px <= band["hi"]):
            return
        q = {**q, "source": q.get("source", "breeze"), "at": self.clock()}

        def fill(x):
            if x["status"] != "pending":
                return None
            x.update(status="open", entry=round(px, 4), entryAt=self.clock(), entryQuote=q)
            x["events"].append({"t": self.clock(), "e": "filled", "price": x["entry"], "source": q.get("source"),
                                "band": [band["lo"], band["hi"]] if band else None})
            return f"✅ {'Bought' if long else 'Sold'} {x['qty']} {x['symbol']} @ {px:g}" + (f" (range {band['lo']:g} – {band['hi']:g})" if band else "")
        await self.mutate(t["id"], fill)

    async def exit(self, t: dict, reason: str, why: str, confirm: Optional[tuple] = None) -> None:
        now = self.clock()
        if now < self.next_q.get(t["id"], 0) + CONFIRM_EVERY:
            return
        self.next_q[t["id"]] = now
        q = await self.feed.quote(t["symbol"])
        if not q:
            return
        long = t["side"] == "buy"
        if confirm:                       # premium levels: a fresh quote must confirm the streamed cross
            k, lvl = confirm
            last = q["last"]
            ok = (last <= lvl if long else last >= lvl) if k == "sl" else (last >= lvl if long else last <= lvl)
            if not ok:
                return
        px = float((q.get("bid") if long else q.get("ask")) or q["last"])
        q = {**q, "at": now, "why": why}

        def fn(x):
            if x["status"] != "open":
                return None
            sign = 1 if long else -1
            x.update(status="closed", exit=round(px, 4), exitAt=self.clock(), exitReason=reason, exitQuote=q, exitLimit=None,
                     pnl=round(sign * (px - x["entry"]) * x["qty"], 2))
            x["events"].append({"t": self.clock(), "e": "closed", "price": x["exit"], "reason": reason, "why": why})
            icon = "🛑 Stop loss" if reason == "sl" else "🎯 Target"
            return f"{icon}: {x['symbol']} exited @ {px:g} ({why}) P&L ₹{x['pnl']:,.2f}"
        await self.mutate(t["id"], fn)

    async def cancel(self, tid: str, reason: str, msg: str) -> None:
        def fn(x):
            if x["status"] != "pending":
                return None
            x.update(status="cancelled", exitAt=self.clock(), exitReason=reason)
            x["events"].append({"t": self.clock(), "e": "cancelled", "reason": reason})
            return msg
        await self.mutate(tid, fn)
