"""Server paper engine: index candle-close trigger, tolerance-band limit fill, trailing prev-candle SL, 2x range target."""
import asyncio
import calendar

import pytest

from core import paper, paper_engine
from core.paper_engine import Candles, Engine, Feed, bucket, valid_until

IST = 19800
S0, S1 = 9 * 3600 + 15 * 60 - IST, 15 * 3600 + 15 * 60 - IST
DAY = calendar.timegm((2026, 11, 5, 0, 0, 0))          # Thursday


def ist(h, m, s=0):
    return DAY + h * 3600 + m * 60 + s - IST


class FakeFeed(Feed):
    def __init__(self):
        self.cbs, self.q = {}, {}

    async def subscribe(self, symbol, cb):
        self.cbs[symbol] = cb

        async def off():
            self.cbs.pop(symbol, None)
        return off

    async def quote(self, symbol):
        return self.q.get(symbol)


OPT = "NIFTY 10NOV26 24400 CE"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(paper, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(paper, "ACCOUNT", tmp_path / "account.json")
    monkeypatch.setattr(paper_engine, "GAP_S", 1e9)
    clock = {"t": ist(9, 20, 5)}
    feed = FakeFeed()
    eng = Engine(feed, clock=lambda: clock["t"])
    monkeypatch.setattr(Engine, "_inst", eng)
    monkeypatch.setattr(paper.time, "time", lambda: clock["t"])
    eng.start = lambda: None
    return eng, feed, clock


def place(body):
    base = {"symbol": OPT, "side": "buy", "lots": 1, "lotSize": 65, "under": "NIFTY", "src": "breeze", "price": 100}
    return asyncio.run(paper.open_trade({**base, **body}))


def run(eng, coro_fn):
    return asyncio.run(coro_fn())


def test_bucket_and_valid_until():
    assert bucket(ist(9, 22), 300, S0, S1) == (ist(9, 20), ist(9, 25))
    assert bucket(ist(9, 10), 300, S0, S1) is None
    assert valid_until(ist(10, 0)) == ist(15, 30)
    assert valid_until(calendar.timegm((2026, 11, 6, 12, 0, 0))) == calendar.timegm((2026, 11, 9, 0, 0, 0)) + 15 * 3600 + 30 * 60 - IST


def test_seed_and_close():
    c = Candles(300, S0, S1)
    c.seed([(ist(9, 15), 1, 2, 0.5, 1.5), (ist(9, 20), 1.5, 3, 1, 2)], ist(9, 21, 30))
    assert len(c.closed) == 1 and c.cur["h"] == 3
    out = c.tick(2.5, ist(9, 25, 1))
    assert out and out[0]["c"] == 2 and c.cur["o"] == 2.5


def test_index_trigger_band_fill_trailing_sl(env):
    eng, feed, clock = env
    t = place({"entryType": "band", "cond": {"under": "NIFTY", "tf": 300, "dir": "above", "level": 24435},
               "band": {"pct": 1, "anchor": "now", "center": 100}, "rules": {"sl": {"mode": "prevLow"}, "target": {"mode": "range", "k": 2}}})
    assert t["engine"] == "server" and t["band"]["lo"] == 99 and t["band"]["hi"] == 101 and t["status"] == "pending"

    async def go():
        async def at(ts, sym=None, px=None):
            clock["t"] = ts
            if sym:
                feed.cbs[sym](px)
            await eng.step()
            await asyncio.sleep(0)
            await eng.step()
        await at(ist(9, 20, 6))                           # subscribes NIFTY + option
        assert "NIFTY" in feed.cbs and OPT in feed.cbs
        for ts, px in ((ist(9, 20, 10), 24427), (ist(9, 22), 24440), (ist(9, 23), 24420), (ist(9, 24, 50), 24438)):
            await at(ts, "NIFTY", px)
        assert paper.load()[0]["cond"]["phase"] == "armed"      # candle not closed yet: no look-ahead
        feed.q[OPT] = {"last": 103, "bid": 102.9, "ask": 103.2}  # premium jumped above the range
        await at(ist(9, 25, 2))
        x = paper.load()[0]
        assert x["cond"]["phase"] == "triggered" and x["status"] == "pending"
        assert x["idxTarget"] == 24478 and x["idxSl"] == 24420
        feed.q[OPT] = {"last": 100.4, "bid": 100.3, "ask": 100.5}
        await at(ist(9, 25, 6), OPT, 100.4)
        x = paper.load()[0]
        assert x["status"] == "open" and x["entry"] == 100.5
        for ts, px in ((ist(9, 26), 24445), (ist(9, 27), 24425), (ist(9, 29, 50), 24430)):
            await at(ts, "NIFTY", px)
        await at(ist(9, 30, 2))
        x = paper.load()[0]
        assert x["status"] == "open" and x["idxSl"] == 24425     # 24430 close held above 24420, trails to 24425
        feed.q[OPT] = {"last": 95, "bid": 94.8, "ask": 95.2}
        for ts, px in ((ist(9, 31), 24428), (ist(9, 34, 50), 24410)):
            await at(ts, "NIFTY", px)
        await at(ist(9, 35, 2))
        x = paper.load()[0]
        assert x["status"] == "closed" and x["exitReason"] == "sl" and x["exit"] == 94.8
        assert eng.msgs and any("Stop loss" in m["text"] for m in eng.msgs)
    asyncio.run(go())


def test_market_trigger_then_index_target(env):
    eng, feed, clock = env
    place({"entryType": "market", "cond": {"under": "NIFTY", "tf": 60, "dir": "below", "level": 24400},
           "symbol": "NIFTY 10NOV26 24400 PE", "rules": {"sl": {"mode": "prevLow"}, "target": {"mode": "range", "k": 2}}})
    pe = "NIFTY 10NOV26 24400 PE"

    async def go():
        async def at(ts, sym=None, px=None):
            clock["t"] = ts
            if sym:
                feed.cbs[sym](px)
            await eng.step()
            await asyncio.sleep(0)
            await eng.step()
        await at(ist(9, 20, 6))
        await at(ist(9, 20, 10), "NIFTY", 24405)
        await at(ist(9, 20, 30), "NIFTY", 24410)
        await at(ist(9, 20, 59), "NIFTY", 24395)            # close 24395 < 24400, range 15
        feed.q[pe] = {"last": 120, "bid": 119.9, "ask": 120.1}
        await at(ist(9, 21, 2))
        x = paper.load()[0]
        assert x["status"] == "open" and x["entry"] == 120.1 and x["idxTarget"] == 24365 and x["idxSl"] == 24410
        feed.q[pe] = {"last": 135, "bid": 134.9, "ask": 135.1}
        await at(ist(9, 21, 20), "NIFTY", 24364)
        x = paper.load()[0]
        assert x["status"] == "closed" and x["exitReason"] == "target" and x["exit"] == 134.9
    asyncio.run(go())


def test_cancel_when_sl_before_fill_and_expiry(env):
    eng, feed, clock = env
    place({"entryType": "band", "cond": {"under": "NIFTY", "tf": 60, "dir": "above", "level": 24435},
           "band": {"pct": 1, "anchor": "trigger"}, "rules": {"sl": {"mode": "prevLow"}, "target": {"mode": "none"}}})

    async def go():
        async def at(ts, sym=None, px=None):
            clock["t"] = ts
            if sym:
                feed.cbs[sym](px)
            await eng.step()
            await asyncio.sleep(0)
            await eng.step()
        await at(ist(9, 20, 6))
        await at(ist(9, 20, 10), "NIFTY", 24430)
        await at(ist(9, 20, 59), "NIFTY", 24440)
        feed.q[OPT] = {"last": 100, "bid": 99.9, "ask": 100}
        await at(ist(9, 21, 2))
        x = paper.load()[0]
        assert x["band"]["lo"] == 99 and x["band"]["hi"] == 101 and x["status"] == "open"   # anchored at trigger, fills at once
    asyncio.run(go())


def test_expiry(env):
    eng, feed, clock = env
    place({"entryType": "market", "cond": {"under": "NIFTY", "tf": 300, "dir": "above", "level": 30000}, "rules": {}})

    async def go():
        clock["t"] = ist(15, 30, 1)
        await eng.step()
        x = paper.load()[0]
        assert x["status"] == "cancelled" and x["exitReason"] == "expired"
    asyncio.run(go())


def test_validation(env):
    with pytest.raises(Exception):
        place({"entryType": "band", "band": {"pct": 1, "anchor": "now"}})           # no limit price
    with pytest.raises(Exception):
        place({"entryType": "market", "cond": {"under": "NIFTY", "tf": 120, "dir": "above", "level": 1}})
    t = place({"entryType": "band", "band": {"pct": 2, "center": 50}, "side": "sell"})
    assert t["limit"] == 49 and t["cond"] is None and t["engine"] == "server"
