"""
Free / open-source market data sources.

Each source returns:
  history(symbol, tf, lookback) -> DataFrame[open, high, low, close, volume] (UTC naive DatetimeIndex)
  stream(symbol)                -> async iterator of engine.Tick

Sources:
  yf     yfinance (Apache-2.0)      US, NSE (.NS), BSE (.BO), indices (^NSEI), FX, crypto. WebSocket live.
  nse    jugaad-data (Unlicense)    NSE India daily history + live quote polling.
  ccxt   ccxt / ccxt.pro (MIT)      100+ crypto exchanges, WebSocket trades.
  av     Alpha Vantage (free key)   history only (free tier ~25 calls/day). Set ALPHAVANTAGE_API_KEY.
  csv    local CSV                  offline / backtests.
  sim    random walk                offline testing.
"""
from __future__ import annotations

import asyncio
import os
import random
import time
from datetime import date, timedelta
from typing import AsyncIterator

import pandas as pd

from .engine import Tick

COLS = ["open", "high", "low", "close", "volume"]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.lower)[COLS].astype("float64")
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    df.index = idx
    return df.sort_index().dropna(subset=["close"])


class DataSource:
    async def history(self, symbol: str, tf: int, lookback: str) -> pd.DataFrame:
        raise NotImplementedError

    def stream(self, symbol: str) -> AsyncIterator[Tick]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
class YFinanceSource(DataSource):
    _TF = {60: "1m", 120: "2m", 300: "5m", 900: "15m", 1800: "30m", 3600: "60m", 86400: "1d", 604800: "1wk", 2592000: "1mo"}

    async def history(self, symbol, tf=60, lookback="5d"):
        import yfinance as yf

        base = 60 if tf == 180 else tf          # Yahoo has no 3m: resample 1m
        df = await asyncio.to_thread(
            yf.Ticker(symbol).history, period=lookback, interval=self._TF[base], auto_adjust=False
        )
        df = _normalize(df)
        if base != tf and not df.empty:
            df = df.resample(f"{tf}s", label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])
        return df

    async def stream(self, symbol):
        import yfinance as yf

        q: asyncio.Queue[Tick] = asyncio.Queue()
        last_vol = {"v": None}

        def on_msg(m: dict):
            if m.get("id") != symbol or "price" not in m:
                return
            dv = float(m.get("day_volume", 0) or 0)
            vol = 0.0 if last_vol["v"] is None else max(dv - last_vol["v"], 0.0)
            last_vol["v"] = dv
            ts = int(m.get("time", time.time() * 1000)) / 1000
            q.put_nowait(Tick(ts, float(m["price"]), vol))

        async def run_ws():
            async with yf.AsyncWebSocket(verbose=False) as ws:
                await ws.subscribe([symbol])
                await ws.listen(on_msg)

        task = asyncio.create_task(run_ws())
        try:
            while True:
                yield await q.get()
        finally:
            task.cancel()


# ---------------------------------------------------------------------------
class NSESource(DataSource):
    """jugaad-data: daily history only (tf must be 86400); live via quote polling."""

    def __init__(self, poll_sec: float = 1.5):
        self.poll = poll_sec

    async def history(self, symbol, tf=86400, lookback="365d"):
        from jugaad_data.nse import stock_df

        days = int(lookback.rstrip("d"))
        df = await asyncio.to_thread(
            stock_df, symbol=symbol, from_date=date.today() - timedelta(days=days),
            to_date=date.today(), series="EQ",
        )
        df = df.set_index("DATE")[["OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]]
        return _normalize(df)

    async def stream(self, symbol):
        from jugaad_data.nse import NSELive

        nse, last_vol = NSELive(), None
        while True:
            q = await asyncio.to_thread(nse.stock_quote, symbol)
            px = float(q["priceInfo"]["lastPrice"])
            tv = float(q.get("preOpenMarket", {}).get("totalTradedVolume", 0) or 0)
            vol = 0.0 if last_vol is None else max(tv - last_vol, 0.0)
            last_vol = tv
            yield Tick(time.time(), px, vol)
            await asyncio.sleep(self.poll)


# ---------------------------------------------------------------------------
class CCXTSource(DataSource):
    _TF = {60: "1m", 300: "5m", 900: "15m", 1800: "30m", 3600: "1h", 14400: "4h", 86400: "1d"}

    def __init__(self, exchange: str = "binance"):
        self.exchange = exchange

    async def history(self, symbol, tf=60, lookback="1000"):
        import ccxt.pro as ccxtpro

        ex = getattr(ccxtpro, self.exchange)()
        try:
            rows = await ex.fetch_ohlcv(symbol, self._TF[tf], limit=int(lookback))
        finally:
            await ex.close()
        df = pd.DataFrame(rows, columns=["ts", *COLS])
        df.index = pd.to_datetime(df.pop("ts"), unit="ms")
        return _normalize(df)

    async def stream(self, symbol):
        import ccxt.pro as ccxtpro

        ex = getattr(ccxtpro, self.exchange)()
        try:
            while True:
                for tr in await ex.watch_trades(symbol):
                    yield Tick(tr["timestamp"] / 1000, float(tr["price"]), float(tr["amount"]))
        finally:
            await ex.close()


# ---------------------------------------------------------------------------
class AlphaVantageSource(DataSource):
    _TF = {60: "1min", 300: "5min", 900: "15min", 1800: "30min", 3600: "60min"}

    def __init__(self, api_key: str | None = None):
        self.key = api_key or os.environ.get("ALPHAVANTAGE_API_KEY", "demo")

    async def history(self, symbol, tf=300, lookback="compact"):
        import requests

        params = {"symbol": symbol, "apikey": self.key, "outputsize": lookback}
        if tf == 86400:
            params["function"] = "TIME_SERIES_DAILY"
        else:
            params |= {"function": "TIME_SERIES_INTRADAY", "interval": self._TF[tf]}
        r = await asyncio.to_thread(
            requests.get, "https://www.alphavantage.co/query", params=params, timeout=15
        )
        data = r.json()
        key = next((k for k in data if k.startswith("Time Series")), None)
        if key is None:
            raise RuntimeError(data.get("Note") or data.get("Information") or data)
        df = pd.DataFrame.from_dict(data[key], orient="index")
        df.columns = [c.split(". ")[1] for c in df.columns]
        return _normalize(df)

    def stream(self, symbol):
        raise NotImplementedError("Alpha Vantage free tier is too rate-limited for live ticks")


# ---------------------------------------------------------------------------
class CSVSource(DataSource):
    """CSV with columns: time,open,high,low,close,volume. Stream replays closes as ticks."""

    def __init__(self, path: str, speed: float = 0.0):
        self.path, self.speed = path, speed

    async def history(self, symbol, tf=60, lookback=""):
        return _normalize(pd.read_csv(self.path, index_col=0, parse_dates=True))

    async def stream(self, symbol):
        df = await self.history(symbol)
        for ts, row in df.iterrows():
            yield Tick(ts.timestamp(), row["close"], row["volume"])
            if self.speed:
                await asyncio.sleep(self.speed)


class SimSource(DataSource):
    def __init__(self, price: float = 100.0, n: int | None = None, rate: float = 0.0):
        self.price, self.n, self.rate = price, n, rate

    async def history(self, symbol, tf=60, lookback="500"):
        n, rows, p = int(lookback) if str(lookback).isdigit() else 2000, [], self.price
        start = (int(time.time()) // tf - n) * tf
        for i in range(n):
            o = p
            c = p = p * (1 + random.gauss(0, 0.002))
            rows.append((o, max(o, c) * 1.001, min(o, c) * 0.999, c, random.randint(100, 5000)))
        self.price = p
        return pd.DataFrame(rows, columns=COLS, index=pd.to_datetime([start + i * tf for i in range(n)], unit="s"))

    async def stream(self, symbol):
        i, ts, p = 0, time.time(), self.price
        while self.n is None or i < self.n:
            ts = time.time() if self.rate else ts + random.uniform(0.05, 1.5)
            p *= 1 + random.gauss(0, 0.0005)
            yield Tick(ts, round(p, 2), random.randint(1, 500))
            i += 1
            if self.rate:
                await asyncio.sleep(self.rate)


SOURCES = {
    "yf": YFinanceSource, "nse": NSESource, "ccxt": CCXTSource,
    "av": AlphaVantageSource, "csv": CSVSource, "sim": SimSource,
}
