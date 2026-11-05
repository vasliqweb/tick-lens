"""
ICICI Direct Breeze integration (breeze-connect SDK, MIT).

  BreezeHub     one logged-in BreezeConnect client + one websocket shared by the whole app.
                Symbol resolution (NSE symbol -> ISEC code/token), rate-limited & disk-cached
                historical candles, tick fan-out to asyncio subscribers, REST quotes.
  BreezeSource  DataSource for charts (source id "breeze").

Credentials come from .env next to app.py:
  BREEZE_API_KEY, BREEZE_API_SECRET, BREEZE_SESSION_TOKEN (daily)
Symbols: NSE trading symbols (RELIANCE, TCS, M&M) or Breeze index codes (NIFTY, CNXBAN, NIFFIN, BSESEN).
BSE indices (SENSEX = BSESEN, BANKEX) use exchange BSE; their derivatives come from the BFO contract master.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import math
import os
import threading
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from .data_sources import COLS, DataSource
from .engine import Tick

log = logging.getLogger("ltv.breeze")
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache" / "breeze"
IST = "Asia/Kolkata"

# Breeze native candle intervals; other timeframes are resampled from the largest divisor.
NATIVE = {60: "1minute", 300: "5minute", 1800: "30minute", 86400: "1day"}
MONTH = 2592000                              # "1M" timeframe id: calendar months (IST), not a fixed 30 days
BASE_FOR_TF = {60: 60, 180: 60, 300: 300, 900: 300, 1800: 1800, 3600: 1800, 86400: 86400, 604800: 86400, MONTH: 86400}
ROWS_PER_DAY = {60: 375, 300: 75, 1800: 13, 86400: 1}
MAX_ROWS = 1000                              # Breeze returns at most 1000 candles per call
DEFAULT_DAYS = {60: 5, 180: 10, 300: 30, 900: 60, 1800: 120, 3600: 240, 86400: 365 * 4, 604800: 365 * 12, MONTH: 365 * 20}
# NSE continuous session in IST. 09:00-09:15 is pre-open and 15:15-15:30 the closing auction:
# Breeze returns flat/zero-volume/spiky candles there, so (like TradingView) they are dropped.
SESSION = os.environ.get("NSE_SESSION", "09:15-15:15")
FNO_SESSION = os.environ.get("NSE_FNO_SESSION", "09:15-15:40")   # futures & options run till 15:40


def _span(spec):
    return tuple(int(h) * 3600 + int(m) * 60 - 19800 for h, m in (x.split(":") for x in spec.split("-")))


_s0, _s1 = _span(SESSION)
_f0, _f1 = _span(FNO_SESSION)
_c1 = _span("09:15-15:30")[1]                # official cash close (end of the closing auction)
LIVE_CHUNK_TTL = 300                         # seconds to reuse today's (still changing) candles
IVOL_CONCURRENCY = 6                                                # parallel constituent fetches (rate limiter still applies)
CONSTITUENT_DAYS = {60: 3, 300: 12, 1800: 60, 86400: 1500}   # index-volume history depth per base interval
CALLS_PER_MIN = int(os.environ.get("BREEZE_CALLS_PER_MIN", "90"))  # Breeze limit is 100/min

# Index -> NSE constituents list (volume = sum of constituents' volume)
INDEX_LISTS = {
    "NIFTY": "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "CNXBAN": "https://archives.nseindia.com/content/indices/ind_niftybanklist.csv",
    # BSE has no stable free CSV: built-in lists below. Volume = NSE volume of the same stocks (Breeze is NSE-only
    # for equities), so for SENSEX/BANKEX it is an estimate of activity, not BSE-reported volume.
    "BSESEN": None,
    "BANKEX": None,
}
# Breeze stream tokens for indices (not in the equity scrip master)
INDEX_TOKENS = {"NIFTY": "4.1!NIFTY 50", "CNXBAN": "4.1!NIFTY BANK", "NIFFIN": "4.1!NIFTY FIN SERVICE",
                "CNXIT": "4.1!NIFTY IT", "NIFMID": "4.1!NIFTY MIDCAP 50"}
# BSE indices: ISEC code -> stream token. The BSE scrip master token is used when it lists the index;
# otherwise this fallback (override with BREEZE_TOKEN_BSESEN / BREEZE_TOKEN_BANKEX in .env).
BSE_INDEX_TOKENS = {"BSESEN": "1.1!1", "BANKEX": "1.1!12"}
BSE_CASH = set(BSE_INDEX_TOKENS)


def cash_exchange(isec: str) -> str:
    return "BSE" if isec in BSE_CASH else "NSE"


SENSEX_FALLBACK = """ADANIPORTS ASIANPAINT AXISBANK BAJAJFINSV BAJFINANCE BEL BHARTIARTL ETERNAL HCLTECH HDFCBANK
HINDUNILVR ICICIBANK INFY ITC KOTAKBANK LT M&M MARUTI NTPC POWERGRID RELIANCE SBIN SUNPHARMA TMPV TATASTEEL TCS TECHM
TITAN TRENT ULTRACEMCO""".split()
BANKEX_FALLBACK = "AUBANK AXISBANK BANKBARODA FEDERALBNK HDFCBANK ICICIBANK IDFCFIRSTB INDUSINDBK KOTAKBANK SBIN".split()
BANKNIFTY_FALLBACK = "AUBANK AXISBANK BANKBARODA CANBK FEDERALBNK HDFCBANK ICICIBANK IDFCFIRSTB INDUSINDBK KOTAKBANK PNB SBIN".split()
NIFTY50_FALLBACK = """ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE BAJAJFINSV BEL BHARTIARTL
CIPLA COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM HCLTECH HDFCBANK HDFCLIFE HINDALCO HINDUNILVR ICICIBANK INDIGO INFY
ITC JIOFIN JSWSTEEL KOTAKBANK LT M&M MARUTI MAXHEALTH NESTLEIND NTPC ONGC POWERGRID RELIANCE SBILIFE SBIN SHRIRAMFIN
SUNPHARMA TATACONSUM TMPV TATASTEEL TCS TECHM TITAN TRENT ULTRACEMCO WIPRO""".split()


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader (KEY=VALUE, # comments); does not override real env vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _token_stamp() -> str:
    from .breeze_login import SESSION_STAMP
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith(SESSION_STAMP):
                return line[len(SESSION_STAMP):].strip()
    except OSError:
        pass
    return ""


RENEW_COOLDOWN = 300          # after a failed auto-login, wait before asking for another OTP


_AUTH_ERRORS = ("session", "user details", "invalid user", "unauthor", "not authori", "login", "logged",
                "api key", "apikey", "appkey", "checksum", "token", "credential", "customer details")


def _expired(err) -> bool:
    """Breeze errors that mean the login is gone ("Session key is expired", "Invalid User Details", ...)."""
    t = str(err or "").lower()
    return any(k in t for k in _AUTH_ERRORS)


class RateLimiter:
    def __init__(self, per_min: int):
        self.gap = 60.0 / per_min
        self.next = 0.0
        self.lock = asyncio.Lock()

    async def wait(self):
        async with self.lock:
            now = time.monotonic()
            if self.next > now:
                await asyncio.sleep(self.next - now)
            self.next = max(now, self.next) + self.gap


class BreezeHub:
    _inst: Optional["BreezeHub"] = None

    @classmethod
    def get(cls) -> "BreezeHub":
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def __init__(self):
        self.breeze = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._login_lock = asyncio.Lock()
        self._renew_failed_at = 0.0
        self.renewing, self.last_error = False, ""
        self._ws_lock = threading.Lock()
        self.ws_ok = False
        self.limiter = RateLimiter(CALLS_PER_MIN)
        self.names_file = CACHE / "names.json"                # symbol -> {isec, token, name}
        try:
            self.names: Dict[str, dict] = json.loads(self.names_file.read_text())
        except Exception:
            self.names = {}
        for v in self.names.values():
            v["token"] = _first_token(v.get("token"))
        self._live_chunks: Dict[tuple, tuple] = {}            # (isec, interval, start) -> (fetched_at, df)
        self._warming: set = set()
        self._ivol: Dict[tuple, dict] = {}                    # (index, base_tf) -> shared progress state
        self.subs: Dict[str, List[Callable[[dict], None]]] = defaultdict(list)  # token -> callbacks
        self._master = None
        self._master_lock = threading.Lock()

    # ------------------------------------------------------------ session
    async def client(self):
        if self.breeze is not None:
            return self.breeze
        async with self._login_lock:
            if self.breeze is None:
                self.loop = asyncio.get_running_loop()
                try:
                    b = await asyncio.to_thread(self._login)
                except Exception as e:
                    if not _expired(e):
                        raise
                    await self._renew()
                    b = await asyncio.to_thread(self._login)
                self.breeze = b
                if not getattr(self, "_master_task", None):
                    self._master_task = asyncio.create_task(asyncio.to_thread(self._build_master))  # warm F&O list
                if self.subs:                                  # live feeds from before a renewal
                    self.ws_ok = False
                    for tok in list(self.subs):
                        try:
                            await asyncio.to_thread(self._ws_join, b, tok)
                        except Exception as e:
                            log.warning("resubscribe %s: %s", tok, e)
        return self.breeze

    async def _renew(self, manual: bool = False):
        """Expired session key: log in again through Playwright + Telegram OTP (one attempt at a time)."""
        from .breeze_login import renew
        if not manual and time.time() - self._renew_failed_at < RENEW_COOLDOWN:
            raise RuntimeError("Breeze session expired; auto-login failed recently, retrying in a few minutes")
        log.warning("Breeze: %s (OTP via Telegram)", "connecting" if manual else "session expired, renewing")
        self.renewing, self.last_error = True, ""
        try:
            await renew(ROOT / ".env", CACHE / "login")
        except Exception as e:
            self._renew_failed_at = time.time()
            self.last_error = str(e)[:300]
            raise RuntimeError(f"Breeze auto-login failed: {e}") from None
        finally:
            self.renewing = False

    async def reconnect(self):
        """Connect button: fresh login + OTP even if the current key still works, then a new client."""
        if self.renewing:
            raise RuntimeError("a Breeze login is already waiting for the OTP")
        async with self._login_lock:
            await self._renew(manual=True)
            self.breeze, self.ws_ok = None, False
        await self.client()

    def status(self) -> dict:
        from .breeze_login import missing_config
        return {"connected": self.breeze is not None, "renewing": self.renewing, "error": self.last_error,
                "missing": missing_config(ROOT / ".env"), "updated": _token_stamp()}

    async def call(self, fn: str, **kw):
        """Breeze REST call; an expired session is renewed once and the call retried."""
        for attempt in (0, 1):
            b = await self.client()
            try:
                r = await asyncio.to_thread(getattr(b, fn), **kw)
            except Exception as e:
                if attempt or not _expired(e):
                    raise
                r = {"Error": str(e)}
            if attempt or not _expired((r or {}).get("Error") if isinstance(r, dict) else None):
                return r
            async with self._login_lock:
                if self.breeze is b:
                    self.breeze, self.ws_ok = None, False
                    await self._renew()

    @staticmethod
    def _login():
        load_env()
        key, secret, token = (os.environ.get(k) for k in ("BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_SESSION_TOKEN"))
        if not (key and secret and token):
            raise RuntimeError("Breeze credentials missing: set BREEZE_API_KEY, BREEZE_API_SECRET, BREEZE_SESSION_TOKEN in .env")
        from breeze_connect import BreezeConnect
        b = BreezeConnect(api_key=key)
        b.generate_session(api_secret=secret, session_token=token)
        log.info("Breeze session ready")
        return b

    # ------------------------------------------------------------ symbols
    async def resolve(self, symbol: str) -> dict:
        symbol = symbol.upper().strip()
        if symbol in self.names:
            return self.names[symbol]
        b = await self.client()
        from .symbols import FNO_RE
        m = FNO_RE.match(" ".join(symbol.split()))
        if m:
            return await self._resolve_fno(m)
        if symbol in INDEX_TOKENS:
            self.names[symbol] = {"isec": symbol, "token": INDEX_TOKENS[symbol], "name": INDEX_TOKENS[symbol][4:]}
            return self.names[symbol]
        if symbol in BSE_INDEX_TOKENS:
            tok = (b.stock_script_dict_list[0].get(symbol) if len(b.stock_script_dict_list or []) > 0 else None)
            token = os.environ.get(f"BREEZE_TOKEN_{symbol}") or (f"1.1!{tok}" if tok else BSE_INDEX_TOKENS[symbol])
            log.info("BSE index %s stream token %s", symbol, token)
            return {"isec": symbol, "token": token, "name": "SENSEX" if symbol == "BSESEN" else symbol, "exch": "BSE"}
        r = await self.call("get_names", exchange_code="NSE", stock_code=symbol)
        if isinstance(r, dict) and r.get("isec_stock_code"):
            info = {"isec": r["isec_stock_code"].strip('"').split()[0], "token": _first_token(r["isec_token_level1"]),
                    "name": str(r.get("company name", "")).strip('"')}
        else:  # already an ISEC code / index code
            tok = b.stock_script_dict_list[1].get(symbol)
            info = {"isec": symbol, "token": f"4.1!{tok}" if tok else None, "name": symbol}
        if not info["token"]:
            return info
        self.names[symbol] = info
        try:
            self.names_file.parent.mkdir(parents=True, exist_ok=True)
            self.names_file.write_text(json.dumps(self.names))
        except OSError:
            pass
        return info

    # ------------------------------------------------------------ search + F&O contracts
    def _build_master(self):
        """Equities (NSE symbol, ISEC code, company) and NFO contracts from the SDK's security master."""
        with self._master_lock:                     # one build, concurrent searches wait for it
            if self._master is not None:
                return self._master
            return self._build_master_locked()

    def _build_master_locked(self):
        import re
        from datetime import datetime
        from .symbols import INDICES
        t0 = time.time()
        b = self.breeze
        eq, isec_to_nse = [], {}
        try:
            import breeze_connect.breeze_connect as sdk
            try:
                df = pd.read_csv(sdk.zip.open("NSEScripMaster.txt"), sep=",", dtype=str)
            except Exception:
                df = pd.read_csv(sdk.zip.open("NSEScripMaster.txt"), sep=",", engine="python", dtype=str)
            df.columns = [c.strip().strip('"') for c in df.columns]
            df = df[[c for c in ("Token", "ShortName", "Series", "CompanyName", "ExchangeCode") if c in df.columns]]
            df = df.apply(lambda c: c.str.strip().str.strip('"'))
            if "Series" in df.columns:
                df = df[df["Series"] == "EQ"]
            names = df["CompanyName"] if "CompanyName" in df.columns else df["ShortName"]
            for sym, isec, nm, tok in zip(df["ExchangeCode"], df["ShortName"], names, df["Token"]):
                eq.append({"symbol": sym, "isec": isec, "name": nm if isinstance(nm, str) else "", "token": tok})
                isec_to_nse[isec] = sym
        except Exception as e:
            log.warning("equity master unavailable: %s", e)
        for app_name, (_, bz) in INDICES.items():
            if bz:
                isec_to_nse[bz] = app_name
        pat = re.compile(r"^(FUT|OPT)-([^-]+)-(\d{1,2}-[A-Za-z]{3}-\d{4})(?:-([\d.]+)-(CE|PE))?$")
        today, dates, fno, seen = date.today(), {}, [], set()
        lists = b.stock_script_dict_list
        # (exchange, contracts, stream prefix): NFO first so an underlying listed on both keeps its NSE contract
        books = [("NFO", lists[4], "4.1!")] + ([("BFO", lists[5], "8.1!")] if len(lists) > 5 else [])
        for exch, cname, tok, prefix in ((x, c, t, p) for x, book, p in books for c, t in book.items()):
            m = pat.match(cname)
            if not m:
                continue                            # also skips the header row
            kind, under, exp, strike, right = m.groups()
            d = dates.get(exp)
            if d is None:
                try:
                    d = datetime.strptime(exp, "%d-%b-%Y").date()
                except ValueError:
                    d = date.min
                dates[exp] = d
            if d < today:
                continue
            app_under = isec_to_nse.get(under, under)
            k = float(strike) if strike else None
            label = f"{app_under} {d.strftime('%d%b%y').upper()} " + ("FUT" if kind == "FUT" else f"{k:g} {right}")
            if label in seen:
                continue
            seen.add(label)
            fno.append({"symbol": label, "isec": under, "kind": kind, "expiry": d, "strike": k,
                        "right": right, "token": f"{prefix}{tok}", "under": app_under, "exch": exch})
        fno.sort(key=lambda c: (c["under"], c["expiry"], c["kind"] != "FUT", c["strike"] or 0, c["right"] or ""))
        self._master = {"eq": eq, "fno": fno, "by_name": {c["symbol"]: c for c in fno}}
        log.info("Breeze master: %d equities, %d F&O contracts (%d BFO) in %.1fs", len(eq), len(fno),
                 sum(c["exch"] == "BFO" for c in fno), time.time() - t0)
        return self._master

    async def master(self):
        await self.client()
        if self._master is not None:
            return self._master
        return await asyncio.to_thread(self._build_master)

    async def search(self, q: str, limit: int = 40, kind: str = "") -> List[dict]:
        """kind: "" (all) | index | stock | fut | opt. Every result carries its exchange (NSE/BSE)."""
        from .symbols import BSE_INDICES, INDICES
        m = await self.master()
        words = q.upper().split()
        if not words:
            return []
        kind = (kind or "").lower()
        first, rest = words[0], words[1:]
        out = []
        if kind in ("", "index") and not rest:
            out += [{"symbol": n, "name": f"{n} index", "type": "INDEX", "exchange": "BSE" if n in BSE_INDICES else "NSE"}
                    for n in INDICES if n.startswith(first) and INDICES[n][1]]
        if kind in ("", "stock") and not rest:
            eqs = [e for e in m["eq"] if e["symbol"].startswith(first) or first in e["name"].upper()]
            eqs.sort(key=lambda e: (not e["symbol"].startswith(first), len(e["symbol"])))
            out += [{"symbol": e["symbol"], "name": e["name"], "type": "EQ", "exchange": "NSE"} for e in eqs[:limit if kind else 15]]
        if kind in ("", "fut", "opt"):
            fno = [c for c in m["fno"] if c["under"].startswith(first) and all(w in c["symbol"] for w in rest)
                   and (not kind or c["kind"] == kind.upper())]
            if not rest and kind != "opt":   # bare underlying: options would flood the list; show futures
                fno = [c for c in fno if c["kind"] == "FUT"]
            elif not rest:                   # bare + Options filter: nearest expiry, strikes around the middle of the chain
                near = {}
                for c in fno:
                    near[c["under"]] = min(near.get(c["under"], c["expiry"]), c["expiry"])
                fno = [c for c in fno if c["expiry"] == near[c["under"]]]
                mid = sorted(c["strike"] for c in fno)[len(fno) // 2] if fno else 0
                fno.sort(key=lambda c: (c["under"] != first, abs(c["strike"] - mid), c["strike"], c["right"]))
            out += [{"symbol": c["symbol"], "name": ("Future" if c["kind"] == "FUT" else "Option") + f" · {c['exch']}",
                     "type": c["kind"], "exchange": "BSE" if c.get("exch") == "BFO" else "NSE"} for c in fno[:limit]]
        return out[:limit]

    async def _resolve_fno(self, m) -> dict:
        name = " ".join(m.group(0).split())
        c = (await self.master())["by_name"].get(name)
        if not c:
            raise ValueError(f"contract not found: {name}")
        info = {"isec": c["isec"], "token": c["token"], "name": name,
                "fno": {"product": "futures" if c["kind"] == "FUT" else "options", "exch": c.get("exch", "NFO"),
                        "expiry": c["expiry"].isoformat(), "strike": "" if c["strike"] is None else f"{c['strike']:g}",
                        "right": "others" if c["kind"] == "FUT" else ("call" if c["right"] == "CE" else "put")}}
        return info

    # ------------------------------------------------------------ history
    async def _call_hist(self, isec: str, interval: str, start: date, end: date, fno: Optional[dict] = None) -> pd.DataFrame:
        b = await self.client()
        await self.limiter.wait()
        extra = {"exchange_code": cash_exchange(isec), "product_type": "cash"}
        if fno:
            extra = {"exchange_code": fno.get("exch", "NFO"), "product_type": fno["product"], "right": fno["right"],
                     "strike_price": fno["strike"], "expiry_date": f"{fno['expiry']}T06:00:00.000Z"}
        r = await self.call(
            "get_historical_data_v2", interval=interval,
            from_date=f"{start.isoformat()}T00:00:00.000Z", to_date=f"{end.isoformat()}T23:59:59.000Z",
            stock_code=isec, **extra)
        rows = (r or {}).get("Success") or []
        if not rows:
            err = (r or {}).get("Error")
            if err and "No Data" not in str(err):
                raise RuntimeError(f"Breeze history {isec}: {err}")
            return pd.DataFrame(columns=COLS, dtype="float64", index=pd.DatetimeIndex([]))
        df = pd.DataFrame(rows)
        idx = pd.to_datetime(df["datetime"]).dt.tz_localize(IST).dt.tz_convert("UTC").dt.tz_localize(None)
        out = df[COLS].apply(pd.to_numeric, errors="coerce").astype("float64")
        out.index = pd.DatetimeIndex(idx)
        return out.sort_index()

    @staticmethod
    def chunk_ranges(base_tf: int, days: int) -> List[tuple]:
        """Epoch-aligned (start, end) request windows covering the last `days` days, oldest first."""
        span = max(1, int(MAX_ROWS / ROWS_PER_DAY[base_tf] * 0.95))   # calendar days per call
        today, epoch = date.today(), date(2000, 1, 1)
        first = today - timedelta(days=days)
        k0, k1 = (first - epoch).days // span, (today - epoch).days // span
        return [(max(first, epoch + timedelta(days=k * span)), epoch + timedelta(days=k * span), epoch + timedelta(days=(k + 1) * span - 1))
                for k in range(k0, k1 + 1)]

    async def candle_chunk(self, isec: str, base_tf: int, s: date, e: date, fno: Optional[dict] = None, key: Optional[str] = None) -> pd.DataFrame:
        """One request window: disk cache for finished windows, short memo for today's."""
        interval, today = NATIVE[base_tf], date.today()
        ck = (key or isec).replace("/", "_").replace(" ", "_")
        cache = CACHE / interval / ck / f"{s}_{e}.pkl"
        if e < today and cache.exists():
            return pd.read_pickle(cache)
        memo = self._live_chunks.get((ck, interval, s))
        if e >= today and memo and time.time() - memo[0] < LIVE_CHUNK_TTL:
            return memo[1]
        df = await self._call_hist(isec, interval, s, min(e, today), fno)
        if e >= today:
            self._live_chunks[(ck, interval, s)] = (time.time(), df)
        else:
            cache.parent.mkdir(parents=True, exist_ok=True)
            df.to_pickle(cache)
        return df

    async def candles(self, isec: str, base_tf: int, days: int, fno: Optional[dict] = None, key: Optional[str] = None) -> pd.DataFrame:
        """Candles at a native interval for the last `days` calendar days, chunked + disk-cached."""
        rng = self.chunk_ranges(base_tf, days)
        parts = [await self.candle_chunk(isec, base_tf, s, e, fno, key) for _, s, e in rng]
        df = pd.concat([p for p in parts if len(p)]) if any(len(p) for p in parts) else pd.DataFrame(columns=COLS, dtype="float64", index=pd.DatetimeIndex([]))
        df = df[~df.index.duplicated(keep="last")].sort_index()
        return df[df.index >= pd.Timestamp(rng[0][0])]

    # ------------------------------------------------------------ index volume
    def index_volume(self, index: str, base_tf: int) -> dict:
        """Shared, page-refresh-proof computation of sum(constituent volume) at base_tf.

        Returns a state dict {done, total, series, finished, infos, ver}. Computed once per
        (index, interval) per day, snapshotted to disk (instant after a server restart), and the
        other intervals are prefetched in the background so timeframe switches are instant."""
        key = (index.upper(), base_tf)
        st = self._ivol.get(key)
        if st and (not st["finished"] or date.fromtimestamp(st["at"]) == date.today()):
            return st                     # kept current by live ticks below, so reuse all day
        st = {"done": 0, "total": 0, "series": pd.Series(dtype="float64"), "finished": False,
              "infos": [], "at": time.time(), "ver": 0, "segments": [], "window": 0, "windows": 0}
        snap = CACHE / "ivol" / f"{index.upper()}_{base_tf}_{date.today()}.pkl"
        stale = True
        try:
            saved = pd.read_pickle(snap)
            st.update(series=saved["series"], infos=saved["infos"], total=saved["total"], done=saved["total"], finished=True,
                      segments=[saved["series"]])
            stale = _market_moved_since(saved["at"])
        except Exception:
            pass
        self._ivol[key] = st

        def save():
            try:
                snap.parent.mkdir(parents=True, exist_ok=True)
                pd.to_pickle({"series": st["series"], "infos": st["infos"], "total": st["total"], "at": time.time()}, snap)
            except Exception as e:  # pragma: no cover
                log.debug("ivol snapshot: %s", e)

        async def compute(publish):
            """Fetch window by window, newest first; publish(segment) once a window is complete."""
            syms = await self.constituents(index)
            st["total"] = len(syms)
            infos = {}
            for sym in syms:
                try:
                    infos[sym] = await self.resolve(sym)
                except Exception as e:
                    log.warning("constituent %s: %s", sym, e)
            sem = asyncio.Semaphore(IVOL_CONCURRENCY)
            wins = self.chunk_ranges(base_tf, CONSTITUENT_DAYS[base_tf])[::-1]
            st["windows"] = len(wins)
            for w, (first, s0, e0) in enumerate(wins):
                vols = []
                st["done"] = 0

                async def one(info):
                    async with sem:
                        try:
                            vols.append((await self.candle_chunk(info["isec"], base_tf, s0, e0))["volume"])
                        except Exception as e:
                            log.warning("constituent %s volume failed: %s", info["isec"], e)
                        st["done"] += 1
                await asyncio.gather(*(one(i) for i in infos.values()))
                vols = [v for v in vols if len(v) and isinstance(v.index, pd.DatetimeIndex)]
                seg = pd.concat(vols, axis=1).sum(axis=1, min_count=1).dropna().sort_index() if vols \
                    else pd.Series(dtype="float64", index=pd.DatetimeIndex([]))
                seg = seg[seg.index >= pd.Timestamp(first)]
                st["window"] = w + 1
                publish(seg)
            return list(infos.values())

        async def run():
            if stale:
                fresh = []

                def publish(seg):
                    fresh.append(seg)
                    if not st["finished"]:            # first load: stream segments to the chart as they complete
                        st["segments"].append(seg)
                        st["series"] = pd.concat([seg, st["series"]]).sort_index()
                try:
                    infos = await compute(publish)
                    if st["finished"]:                # background refresh of a snapshot: swap in one go
                        st["series"] = pd.concat(fresh).sort_index() if fresh else st["series"]
                        st["segments"] = [st["series"]]
                    st["infos"] = infos
                    st["ver"] += 1
                finally:
                    st["finished"] = True
                    st["at"] = time.time()
                save()
            # keep the shared series current: add each constituent's traded-qty delta to its base-tf bucket
            last_ttq: Dict[str, float] = {}

            def cb(t, tok):
                q = tick_fields(t)["ttq"]
                if q != q:
                    return
                prev = last_ttq.get(tok)
                last_ttq[tok] = q
                if prev is None or q <= prev or not in_session(time.time()):
                    return
                now = time.time()
                if base_tf >= 86400:
                    b = (now + 19800) // 86400 * 86400 - 19800          # IST midnight, as UTC
                else:
                    b = (now - 13500) // base_tf * base_tf + 13500        # NSE grid anchored at 09:15 IST
                ts = pd.Timestamp(int(b), unit="s")
                ser = st["series"]
                ser.loc[ts] = (ser.get(ts, 0.0) or 0.0) + (q - prev)
                if ser.index[-1] != ts or len(ser) > 1 and ser.index[-2] > ts:
                    st["series"] = ser.sort_index()
            for info in st["infos"]:
                if info.get("token"):
                    await self.subscribe(info["token"], lambda t, tok=info["token"]: cb(t, tok))
            self._prefetch(index)
            while True:                   # snapshot the live-updated series now and then
                await asyncio.sleep(120)
                if in_session(time.time()):
                    save()

        asyncio.get_running_loop().create_task(run())
        return st

    def _prefetch(self, index: str):
        """Warm the other intervals in the background, one at a time, so later timeframe switches are instant."""
        k = (index.upper(), date.today())
        if k in self._warming:
            return
        self._warming.add(k)

        async def warm():
            for base in (300, 60, 1800, 86400):
                st = self.index_volume(index, base)
                while not st["finished"]:
                    await asyncio.sleep(1)
        asyncio.get_running_loop().create_task(warm())

    # ------------------------------------------------------------ quotes
    async def quote(self, isec: str, fno: Optional[dict] = None) -> Optional[dict]:
        b = await self.client()
        await self.limiter.wait()
        exch = cash_exchange(isec)
        args = {"exchange_code": exch, "expiry_date": "", "product_type": "cash", "right": "", "strike_price": ""}
        if fno:
            exch = fno.get("exch", "NFO")
            args = {"exchange_code": exch, "expiry_date": f"{fno['expiry']}T06:00:00.000Z", "product_type": fno["product"],
                    "right": fno["right"], "strike_price": fno["strike"]}
        r = await self.call("get_quotes", stock_code=isec, **args)
        rows = (r or {}).get("Success") or []
        if not rows:
            return None
        q = next((x for x in rows if str(x.get("exchange_code", "")).upper() == exch), rows[0])
        last, prev = float(q.get("ltp") or 0), float(q.get("previous_close") or 0)
        def num(*keys):
            for k in keys:
                try:
                    v = float(q.get(k) or 0)
                except (TypeError, ValueError):
                    v = 0.0
                if v > 0:
                    return v
            return None
        return {"last": last, "prev": prev, "volume": float(q.get("total_quantity_traded") or 0),
                "bid": num("best_bid_price"), "ask": num("best_offer_price"),
                "open": num("open"), "high": num("high"), "low": num("low")}

    # ------------------------------------------------------------ websocket
    async def subscribe(self, token: str, cb: Callable[[dict], None]) -> None:
        """cb runs on the asyncio loop with the parsed tick dict."""
        b = await self.client()
        first = not self.subs[token]
        self.subs[token].append(cb)
        if first:
            await asyncio.to_thread(self._ws_join, b, token)

    async def unsubscribe(self, token: str, cb) -> None:
        lst = self.subs.get(token, [])
        if cb in lst:
            lst.remove(cb)
        if not lst and self.breeze is not None and self.ws_ok:
            self.subs.pop(token, None)
            try:
                await asyncio.to_thread(self.breeze.unsubscribe_feeds, stock_token=token)
            except Exception as e:  # pragma: no cover
                log.debug("unsubscribe %s: %s", token, e)

    def _ws_join(self, b, token: str):
        with self._ws_lock:
            if not self.ws_ok:
                b.ws_connect()
                b.on_ticks = self._on_tick
                self.ws_ok = True
            res = b.subscribe_feeds(stock_token=token)
            log.info("subscribe %s -> %s", token, res)

    def _on_tick(self, t: dict):  # runs on the socketio thread
        tok = t.get("symbol") or (f"4.1!{t['stock_code']}" if t.get("stock_code") else None)
        if tok and self.loop and tok in self.subs:
            self.loop.call_soon_threadsafe(self._dispatch, tok, t)

    def _dispatch(self, tok: str, t: dict):
        for cb in list(self.subs.get(tok, [])):
            try:
                cb(t)
            except Exception:  # pragma: no cover
                log.exception("tick callback")

    # ------------------------------------------------------------ index constituents
    async def constituents(self, index: str) -> List[str]:
        index = index.upper()
        if index not in INDEX_LISTS:
            return []
        url = INDEX_LISTS[index]
        cache = CACHE / "lists" / f"{index}_{date.today()}.txt"
        if cache.exists():
            return cache.read_text().split()
        syms: List[str] = []
        try:
            if url:
                import requests
                r = await asyncio.to_thread(requests.get, url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                r.raise_for_status()
                syms = [row["Symbol"].strip() for row in csv.DictReader(io.StringIO(r.text)) if row.get("Symbol")]
        except Exception as e:
            log.warning("index list %s download failed (%s); using built-in list", index, e)
        if not syms:
            syms = {"NIFTY": NIFTY50_FALLBACK, "CNXBAN": BANKNIFTY_FALLBACK, "BSESEN": SENSEX_FALLBACK,
                    "BANKEX": BANKEX_FALLBACK}.get(index, [])
        if syms:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(" ".join(syms))
        return syms


def _market_moved_since(ts: float) -> bool:
    """True if NSE traded between `ts` and now (so a saved snapshot is out of date)."""
    now = time.time()
    if now - ts < 60:
        return False
    day = lambda x: int((x + 19800) // 86400)                                   # IST day number
    if day(ts) != day(now):
        return True
    sod = lambda x: (x + 19800) % 86400                                         # IST seconds of day
    open_, close = 9 * 3600 + 15 * 60, 15 * 3600 + 30 * 60
    weekday = date.fromtimestamp(now).weekday() < 5
    return weekday and sod(ts) < close and sod(now) > open_


def _first_token(tok: Optional[str]) -> Optional[str]:
    """'4.1!1333 1462 17320' (several scrip-master rows matched) -> '4.1!1333'."""
    if not tok:
        return tok
    tok = tok.replace('"', "")
    pre, _, rest = tok.partition("!")
    return f"{pre}!{rest.split()[0]}" if rest and pre.replace(".", "").isdigit() and rest.split()[0].isdigit() else tok


def tick_fields(t: dict) -> dict:
    """Normalise a Breeze tick: last price, previous close, cumulative traded qty."""
    def f(*keys):
        for k in keys:
            v = t.get(k)
            if v not in (None, ""):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return math.nan
    return {"last": f("last", "last_trade_price"), "prev": f("close", "previous_close"),
            "ttq": f("ttq", "total_traded_volume")}


def in_session(ts: float, fno: bool = False) -> bool:
    """True if a UTC epoch time falls in the NSE continuous session (F&O session if fno)."""
    a, b = (_f0, _f1) if fno else (_s0, _s1)
    return a <= ts % 86400 < b


def in_daily_session(ts: float, fno: bool = False) -> bool:
    """Daily bars track the official close: like in_session, but cash ticks count until 15:30 IST (closing auction)."""
    return in_session(ts, fno) or (not fno and _s0 <= ts % 86400 < _c1)


def session_only(df: pd.DataFrame, fno: bool = False) -> pd.DataFrame:
    """Keep intraday candles that start inside the session (daily+ candles pass through)."""
    if df.empty or len(df.index) < 2 or (df.index[1:] - df.index[:-1]).min() >= pd.Timedelta(days=1):
        return df
    a, b = (_f0, _f1) if fno else (_s0, _s1)
    sod = df.index.as_unit("s").asi8 % 86400
    return df[(sod >= a) & (sod < b)]


def period_start(t: pd.Timestamp, tf: int) -> pd.Timestamp:
    """Naive-UTC start of the daily / weekly (Monday) / monthly bar holding naive-UTC time t, in IST."""
    ist = pd.Timestamp(t).tz_localize("UTC").tz_convert(IST).normalize()
    if tf == 604800:
        ist -= pd.Timedelta(days=ist.dayofweek)
    elif tf == MONTH:
        ist = ist.replace(day=1)
    return ist.tz_convert("UTC").tz_localize(None)


def resample(df: pd.DataFrame, tf: int) -> pd.DataFrame:
    if df.empty:
        return df
    if tf in (604800, MONTH):
        ist = df.tz_localize("UTC").tz_convert(IST)
        out = ist.resample("W-MON" if tf == 604800 else "MS", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        out.index = out.index.tz_convert("UTC").tz_localize(None)
        return out.dropna(subset=["close"])
    # intraday: NSE session starts 09:15 IST = 03:45 UTC; anchor bins there
    out = df.resample(f"{tf}s", origin=pd.Timestamp("2000-01-03 03:45"), label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return out.dropna(subset=["close"])


class BreezeSource(DataSource):
    def __init__(self):
        self.hub = BreezeHub.get()

    async def history(self, symbol, tf=300, lookback=None):
        info = await self.hub.resolve(symbol)
        base = BASE_FOR_TF.get(int(tf))
        if base is None:
            raise ValueError(f"timeframe {tf}s not supported by Breeze")
        days = int(str(lookback).rstrip("d")) if lookback and str(lookback).rstrip("d").isdigit() else DEFAULT_DAYS[int(tf)]
        df = await self.hub.candles(info["isec"], base, days, info.get("fno"), info["name"] if info.get("fno") else None)
        if base < 86400 and not getattr(self, "extended", False):
            df = session_only(df, bool(info.get("fno")))
        return resample(df, int(tf)) if base != int(tf) else df

    async def stream(self, symbol):
        info = await self.hub.resolve(symbol)
        if not info.get("token"):
            raise RuntimeError(f"no Breeze stream token for {symbol}")
        q: asyncio.Queue = asyncio.Queue()
        last_ttq = {"v": None}

        def cb(t):
            f = tick_fields(t)
            ok = in_daily_session if getattr(self, "daily", False) else in_session
            if f["last"] != f["last"] or not (getattr(self, "extended", False) or ok(time.time(), bool(info.get("fno")))):
                return
            vol = 0.0
            if f["ttq"] == f["ttq"]:
                if last_ttq["v"] is not None:
                    vol = max(f["ttq"] - last_ttq["v"], 0.0)
                last_ttq["v"] = f["ttq"]
            q.put_nowait(Tick(time.time(), f["last"], vol))

        await self.hub.subscribe(info["token"], cb)
        try:
            while True:
                yield await q.get()
        finally:
            await self.hub.unsubscribe(info["token"], cb)
