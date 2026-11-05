"""
TradingView data (unofficial): the same websocket the tradingview.com chart uses.

Connects as a guest ("unauthorized_user_token") or, after "Sign in to TradingView" in the app, with that account's
session (kept in cache/tradingview/session.json, never the password). Some exchanges (MCX) refuse guests.
Private API: it can change at any time.

Wire format: frames "~m~<len>~m~<payload>"; payload is JSON {"m": method, "p": [params]} or a heartbeat "~h~N"
that must be echoed back.

  history:  chart_create_session -> resolve_symbol -> create_series -> "timescale_update"(s) -> "series_completed"
  quotes:   quote_create_session -> quote_set_fields -> quote_add_symbols -> "qsd" updates (lp, ch, volume, ...)

Symbols use TradingView names: MCX:GOLD1!, MCX:CRUDEOIL1!, FX_IDC:USDINR, NSE:NIFTY, COMEX:GC1!, OANDA:XAUUSD.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import string
import time
from pathlib import Path
from typing import AsyncIterator, Callable, Dict, List, Optional

import pandas as pd

from .data_sources import DataSource, _normalize
from .engine import Tick

log = logging.getLogger("ltv.tv")
WS_URL = "wss://data.tradingview.com/socket.io/websocket?from=chart%2F&type=chart"
SEARCH_URL = "https://symbol-search.tradingview.com/symbol_search/v3/"
HEADERS = {"Origin": "https://www.tradingview.com", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
GUEST = "unauthorized_user_token"
INTERVAL = {60: "1", 180: "3", 300: "5", 900: "15", 1800: "30", 3600: "60", 86400: "1D", 604800: "1W", 2592000: "1M"}
MAX_BARS = 5000
QUOTE_FIELDS = ["lp", "ch", "chp", "volume", "prev_close_price", "lp_time", "description", "currency_code"]
# app index names -> TradingView
INDEX = {"NIFTY": "NSE:NIFTY", "BANKNIFTY": "NSE:BANKNIFTY", "FINNIFTY": "NSE:CNXFINANCE", "NIFTYIT": "NSE:CNXIT",
         "MIDCPNIFTY": "NSE:NIFTY_MID_SELECT", "SENSEX": "BSE:SENSEX", "BANKEX": "BSE:BANKEX"}
_FRAME = re.compile(r"~m~(\d+)~m~")
SESSION_FILE = Path(__file__).resolve().parent.parent / "cache" / "tradingview" / "session.json"
TOKEN_TTL = 3600


class TVAuth:
    """Signed-in TradingView session: sessionid cookies on disk, auth_token refreshed from the site."""
    def __init__(self):
        self.data: dict = {}
        self.pending = None            # requests.Session waiting for a 2FA code
        try:
            self.data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}

    def _save(self):
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(self.data), encoding="utf-8")

    @property
    def user(self) -> Optional[str]:
        if self.data.get("sessionid"):
            return self.data.get("user")
        if self._token_ok():
            return self.data.get("user") or "TradingView user"
        return None

    def _token_ok(self) -> bool:
        return bool(self.data.get("auth_token")) and self.data.get("exp", 0) > time.time() + 60

    def _http(self):
        import requests
        h = requests.Session()
        h.headers.update({**HEADERS, "Referer": "https://www.tradingview.com/"})
        return h

    def _store(self, http, user: dict):
        ck = http.cookies.get_dict()
        if not ck.get("sessionid"):
            raise ValueError("TradingView did not return a session")
        self.data = {"sessionid": ck["sessionid"], "sessionid_sign": ck.get("sessionid_sign", ""),
                     "user": user.get("username") or "", "auth_token": user.get("auth_token") or "", "token_at": time.time()}
        self._save()

    def login(self, username: str, password: str) -> dict:
        http = self._http()
        r = http.post("https://www.tradingview.com/accounts/signin/", data={"username": username, "password": password, "remember": "on"},
                      headers={"X-Requested-With": "XMLHttpRequest"}, timeout=20)
        try:
            d = r.json()
        except ValueError:
            raise ValueError(f"sign-in failed (HTTP {r.status_code})")
        code = d.get("code") or ""
        if "2fa" in code.lower() or d.get("two_factor_types"):
            self.pending = http
            return {"need_2fa": True}
        if d.get("error"):
            if "captcha" in code.lower() or "captcha" in str(d.get("error")).lower():
                raise ValueError("TradingView wants a captcha for this sign-in. Use the 'paste session' option instead.")
            raise ValueError(str(d.get("error"))[:200])
        self._store(http, d.get("user") or {})
        return {"user": self.user}

    def login_2fa(self, code: str) -> dict:
        http, self.pending = self.pending, None
        if http is None:
            raise ValueError("sign in again")
        r = http.post("https://www.tradingview.com/accounts/two-factor/signin/totp/", data={"code": code},
                      headers={"X-Requested-With": "XMLHttpRequest"}, timeout=20)
        d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if d.get("error") or not http.cookies.get("sessionid"):
            raise ValueError(str(d.get("error") or "wrong code")[:200])
        self._store(http, d.get("user") or {})
        return {"user": self.user}

    def use_session(self, sessionid: str, sessionid_sign: str = "") -> dict:
        self.data = {"sessionid": sessionid.strip(), "sessionid_sign": sessionid_sign.strip(), "user": "", "auth_token": "", "token_at": 0}
        self._refresh()
        if not self.data.get("auth_token"):
            self.data = {}
            raise ValueError("that session is not signed in")
        self._save()
        return {"user": self.user}

    def use_token(self, token: str) -> dict:
        """A bare auth_token (no cookies): works until its JWT expiry, usually ~4 hours."""
        import base64
        try:
            p = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
        except Exception:
            raise ValueError("not a TradingView auth token")
        if not claims.get("user_id") or claims.get("exp", 0) <= time.time() + 60:
            raise ValueError("that TradingView token has expired; export a fresh HAR or use the browser session")
        self.data = {"auth_token": token, "exp": claims["exp"], "user": "", "token_at": time.time()}
        self._save()
        return {"user": self.user, "expires": claims["exp"]}

    def from_har(self, har: str) -> dict:
        """Signed-in session from a HAR export: the cookies if Chrome kept them, else the socket's auth_token."""
        d = json.loads(har)
        ck, tok = {}, ""
        for e in d.get("log", {}).get("entries", []):
            if "tradingview.com" not in e.get("request", {}).get("url", ""):
                continue
            for c in e["request"].get("cookies") or []:
                if c.get("name") in ("sessionid", "sessionid_sign") and c.get("value"):
                    ck[c["name"]] = c["value"]
            for h in e["request"].get("headers") or []:
                if h.get("name", "").lower() == "cookie":
                    for part in h.get("value", "").split(";"):
                        k, _, v = part.strip().partition("=")
                        if k in ("sessionid", "sessionid_sign") and v:
                            ck[k] = v
            for m in e.get("_webSocketMessages") or []:
                if m.get("type") == "send" and "set_auth_token" in m.get("data", ""):
                    for part in unframe(m["data"]):
                        try:
                            j = json.loads(part)
                        except ValueError:
                            continue
                        if j.get("m") == "set_auth_token" and j["p"][0] != GUEST:
                            tok = j["p"][0]
        if ck.get("sessionid"):
            return self.use_session(ck["sessionid"], ck.get("sessionid_sign", ""))
        if tok:
            return self.use_token(tok)
        raise ValueError("no TradingView sign-in found in that HAR (export it while signed in, from a chart page)")

    def from_browser(self) -> dict:
        """Read the sessionid cookies straight from a local browser profile (needs the browser-cookie3 package)."""
        try:
            import browser_cookie3 as bc
        except ImportError:
            raise ValueError("install it first: pip install browser-cookie3")
        tried = []
        for name in ("firefox", "chrome", "edge", "brave", "opera", "chromium", "vivaldi"):
            fn = getattr(bc, name, None)
            if not fn:
                continue
            try:
                jar = fn(domain_name="tradingview.com")
                ck = {c.name: c.value for c in jar if c.name in ("sessionid", "sessionid_sign")}
            except Exception as e:
                tried.append(f"{name}: {type(e).__name__}")
                continue
            if ck.get("sessionid"):
                try:
                    return self.use_session(ck["sessionid"], ck.get("sessionid_sign", ""))
                except ValueError:
                    tried.append(f"{name}: signed out")
            else:
                tried.append(f"{name}: no session")
        raise ValueError("no signed-in TradingView session found in local browsers (" + ", ".join(tried) + ")")

    def logout(self):
        self.data = {}
        SESSION_FILE.unlink(missing_ok=True)

    def _refresh(self):
        http = self._http()
        http.cookies.set("sessionid", self.data["sessionid"], domain=".tradingview.com")
        if self.data.get("sessionid_sign"):
            http.cookies.set("sessionid_sign", self.data["sessionid_sign"], domain=".tradingview.com")
        html = http.get("https://www.tradingview.com/", timeout=20).text
        tok = re.search(r'"auth_token":"([^"]+)"', html)
        name = re.search(r'"username":"([^"]+)"', html)
        self.data["auth_token"] = tok.group(1) if tok else ""
        self.data["token_at"] = time.time()
        if name:
            self.data["user"] = name.group(1)

    def token(self) -> str:
        """auth_token for set_auth_token (guest token when not signed in or the session expired)."""
        if not self.data.get("sessionid"):
            return self.data["auth_token"] if self._token_ok() else GUEST
        if not self.data.get("auth_token") or time.time() - self.data.get("token_at", 0) > TOKEN_TTL:
            try:
                self._refresh()
                if not self.data.get("auth_token"):          # signed out on the site
                    log.warning("TradingView session expired; using guest access")
                    self.logout()
                    return GUEST
                self._save()
            except Exception as e:
                log.info("TradingView token refresh failed: %s", e)
        return self.data.get("auth_token") or GUEST


AUTH = TVAuth()


def tv_symbol(name: str) -> str:
    """App name -> TradingView symbol (EXCHANGE:TICKER). Names with an exchange prefix pass through."""
    s = " ".join(name.strip().upper().split())
    if ":" in s:
        return s
    if s in INDEX:
        return INDEX[s]
    if s.endswith(".NS"):
        return "NSE:" + s[:-3]
    if s.endswith(".BO"):
        return "BSE:" + s[:-3]
    return "NSE:" + s


def frame(obj) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, separators=(",", ":"))
    return f"~m~{len(s)}~m~{s}"


def unframe(raw: str) -> List[str]:
    out, pos = [], 0
    while True:
        m = _FRAME.match(raw, pos)
        if not m:
            return out
        n = int(m.group(1))
        out.append(raw[m.end(): m.end() + n])
        pos = m.end() + n


def _sid(prefix: str) -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))


class _Socket:
    """One websocket to TradingView with framing, heartbeats and a message callback."""

    def __init__(self, on_msg: Callable[[dict], None]):
        self.on_msg = on_msg
        self.ws = None
        self.reader: Optional[asyncio.Task] = None
        self.closed = asyncio.Event()

    async def open(self):
        import websockets
        kw = dict(max_size=2 ** 24, open_timeout=15, ping_interval=None)
        try:
            self.ws = await websockets.connect(WS_URL, additional_headers=HEADERS, **kw)
        except TypeError:                                             # websockets < 14
            self.ws = await websockets.connect(WS_URL, extra_headers=HEADERS, **kw)
        await self.send("set_auth_token", [await asyncio.to_thread(AUTH.token)])
        self.reader = asyncio.create_task(self._read())

    async def send(self, m: str, p: list):
        await self.ws.send(frame({"m": m, "p": p}))

    async def _read(self):
        try:
            async for raw in self.ws:
                for payload in unframe(raw):
                    if payload.startswith("~h~"):
                        await self.ws.send(frame(payload))           # heartbeat echo
                        continue
                    try:
                        msg = json.loads(payload)
                    except ValueError:
                        continue
                    if isinstance(msg, dict) and "m" in msg:
                        self.on_msg(msg)
        except Exception as e:
            log.info("tradingview socket closed: %s", e)
        finally:
            self.closed.set()

    async def close(self):
        if self.reader:
            self.reader.cancel()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass


async def fetch_bars(symbol: str, tf: int, n_bars: int = MAX_BARS, timeout: float = 25.0) -> pd.DataFrame:
    """Candles for a TradingView symbol (newest n_bars), UTC-naive index."""
    if tf not in INTERVAL:
        raise ValueError(f"timeframe {tf}s not supported by TradingView")
    rows: Dict[int, list] = {}
    done = asyncio.Event()
    err: List[str] = []

    def on_msg(msg):
        m, p = msg["m"], msg.get("p") or []
        if m in ("timescale_update", "du") and len(p) > 1 and isinstance(p[1], dict):
            for bar in (p[1].get("sds_1") or {}).get("s") or []:
                v = bar.get("v") or []
                if len(v) >= 5:
                    rows[int(v[0])] = [float(x) for x in v[1:5]] + [float(v[5]) if len(v) > 5 and v[5] is not None else 0.0]
        elif m == "series_completed":
            done.set()
        elif m in ("symbol_error", "series_error", "critical_error", "protocol_error"):
            err.append(f"{m}: {p[2] if len(p) > 2 else p}")
            done.set()

    sock = _Socket(on_msg)
    await sock.open()
    try:
        cs = _sid("cs_")
        await sock.send("chart_create_session", [cs, ""])
        await sock.send("resolve_symbol", [cs, "sds_sym_1", "=" + json.dumps({"symbol": symbol, "adjustment": "splits", "session": "regular"})])
        await sock.send("create_series", [cs, "sds_1", "s1", "sds_sym_1", INTERVAL[tf], max(10, min(int(n_bars), MAX_BARS)), ""])
        try:
            await asyncio.wait_for(done.wait(), timeout)
        except asyncio.TimeoutError:
            if not rows:
                raise TimeoutError(f"TradingView did not answer for {symbol}")
        while n_bars > MAX_BARS and not err and rows and len(rows) < n_bars:   # older bars, page by page
            have = len(rows)
            done.clear()
            await sock.send("request_more_data", [cs, "sds_1", min(MAX_BARS, int(n_bars) - have)])
            try:
                await asyncio.wait_for(done.wait(), timeout)
            except asyncio.TimeoutError:
                break
            if len(rows) <= have:
                break
    finally:
        await sock.close()
    if err and not rows:
        if "permission denied" in err[0] and not AUTH.user:
            raise PermissionError(f"TradingView: {symbol} needs a TradingView account (guests are refused). Sign in to TradingView.")
        raise ValueError(f"TradingView: {symbol}: {err[0]}"[:200])
    if not rows:
        raise ValueError(f"TradingView: no data for {symbol}")
    ts = sorted(rows)
    df = pd.DataFrame([rows[t] for t in ts], columns=["open", "high", "low", "close", "volume"],
                      index=pd.to_datetime(ts, unit="s"))
    return _normalize(df)


class TVHub:
    """One shared guest quote socket for live prices (chart stream + watchlist). Reconnects on its own."""
    _inst: Optional["TVHub"] = None

    @classmethod
    def get(cls) -> "TVHub":
        if cls._inst is None:
            cls._inst = TVHub()
        return cls._inst

    def __init__(self):
        self.subs: Dict[str, List[Callable[[dict], None]]] = {}
        self.state: Dict[str, dict] = {}         # last known fields per symbol (qsd sends only changes)
        self.sock: Optional[_Socket] = None
        self.qs = ""
        self.task: Optional[asyncio.Task] = None
        self.ready = asyncio.Event()

    def _on_msg(self, msg):
        if msg["m"] != "qsd":
            return
        p = msg.get("p") or []
        if len(p) < 2 or not isinstance(p[1], dict):
            return
        d = p[1]
        sym = d.get("n")
        if d.get("s") != "ok" or not sym:
            return
        st = self.state.setdefault(sym, {})
        st.update(d.get("v") or {})
        for cb in list(self.subs.get(sym, [])):
            try:
                cb(st)
            except Exception:
                log.exception("tv quote callback")

    async def _run(self):
        delay = 1.0
        while True:
            try:
                self.sock = _Socket(self._on_msg)
                await self.sock.open()
                self.qs = _sid("qs_")
                await self.sock.send("quote_create_session", [self.qs])
                await self.sock.send("quote_set_fields", [self.qs, *QUOTE_FIELDS])
                if self.subs:
                    await self.sock.send("quote_add_symbols", [self.qs, *self.subs])
                self.ready.set()
                delay = 1.0
                await self.sock.closed.wait()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("tradingview quotes: %s", e)
            self.ready.clear()
            if self.sock:
                await self.sock.close()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)

    async def restart(self):
        """Reconnect (e.g. after signing in) so the quote socket uses the new account."""
        if self.sock:
            await self.sock.close()

    async def subscribe(self, sym: str, cb: Callable[[dict], None]):
        new = sym not in self.subs
        self.subs.setdefault(sym, []).append(cb)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run())
        elif new and self.ready.is_set():
            try:
                await self.sock.send("quote_add_symbols", [self.qs, sym])
            except Exception:
                pass
        if sym in self.state:
            cb(self.state[sym])

    async def unsubscribe(self, sym: str, cb):
        lst = self.subs.get(sym, [])
        if cb in lst:
            lst.remove(cb)
        if not lst and sym in self.subs:
            del self.subs[sym]
            self.state.pop(sym, None)
            if self.ready.is_set():
                try:
                    await self.sock.send("quote_remove_symbols", [self.qs, sym])
                except Exception:
                    pass


def quote_of(st: dict):
    """(last, prev_close) from accumulated qsd fields."""
    lp = st.get("lp")
    if lp is None:
        return None
    prev = st.get("prev_close_price")
    if prev is None and st.get("ch") is not None:
        prev = lp - st["ch"]
    return float(lp), (float(prev) if prev is not None else None)


def _clean(x) -> str:
    return str(x or "").replace("<em>", "").replace("</em>", "")


async def search(q: str, limit: int = 25) -> list:
    """TradingView symbol search. Futures are expanded into continuous (SILVER1!, SILVER2!) and dated contracts.
    "MCX:SILVER1!" style queries search SILVER on MCX."""
    import requests

    q = q.strip().upper()
    exchange, text = ("", q)
    if ":" in q:
        exchange, text = q.split(":", 1)
    root = re.sub(r"\d+!$", "", text) or text                     # SILVER1! -> SILVER

    def get(search_type=""):
        r = requests.get(SEARCH_URL, params={"text": root, "hl": 0, "exchange": exchange, "lang": "en", "search_type": search_type,
                                             "domain": "production", "sort_by_country": "IN"}, headers=HEADERS, timeout=10)
        r.raise_for_status()
        d = r.json()
        return d.get("symbols", []) if isinstance(d, dict) else d or []

    items = await asyncio.to_thread(get)
    if not any(str(it.get("type", "")).startswith("futures") for it in items):
        try:
            items = await asyncio.to_thread(get, "futures") + items       # make sure futures show up
        except Exception:
            pass
    out, seen = [], set()

    def add(full, name, typ):
        full = full.upper()
        if full not in seen:
            seen.add(full)
            out.append({"symbol": full, "name": name, "type": typ})

    if ":" in q:
        add(q, "as typed", "")
    for it in items:
        sym, ex = _clean(it.get("symbol")), it.get("prefix") or it.get("source_id") or it.get("exchange") or ""
        if not sym:
            continue
        pre = f"{ex}:" if ex else ""
        desc, typ = _clean(it.get("description")), f"{it.get('exchange', '')} {it.get('type', '')}".strip()
        if str(it.get("type", "")).startswith("futures"):
            contracts = it.get("contracts") or []
            conts = [c for c in contracts if str(c.get("symbol", "")).endswith("!")]
            if not conts and not sym.endswith("!"):
                add(f"{pre}{sym}1!", f"{desc} · continuous: current contract", typ)
                add(f"{pre}{sym}2!", f"{desc} · continuous: next contract", typ)
            for c in conts:
                add(pre + _clean(c.get("symbol")), f"{_clean(c.get('description')) or desc} · continuous", typ)
            for c in contracts:
                cs = _clean(c.get("symbol"))
                if cs and not cs.endswith("!"):
                    add(pre + cs, _clean(c.get("description")) or desc, typ)
            if sym.endswith("!"):
                add(pre + sym, desc, typ)
        else:
            add(pre + sym, desc, typ)
    # put the instruments whose root matches the query first (SILVER before MCXSILVDEX)
    def rank(x):
        t = x["symbol"].split(":", 1)[-1]
        return (0 if x["name"] == "as typed" else 1 if re.sub(r"\d+!$", "", t) == root else 2 if t.startswith(root) else 3)
    out.sort(key=rank)
    return out[:limit]


class TradingViewSource(DataSource):
    async def history(self, symbol, tf=300, lookback=None):
        n = int(lookback) if lookback and str(lookback).isdigit() else MAX_BARS
        return await fetch_bars(symbol, int(tf), n)

    async def stream(self, symbol) -> AsyncIterator[Tick]:
        hub = TVHub.get()
        q: asyncio.Queue = asyncio.Queue()
        last = {"vol": None, "lp": None}

        def cb(st):
            lp = st.get("lp")
            if lp is None:
                return
            vol, dv = st.get("volume"), 0.0
            if vol is not None:
                if last["vol"] is not None and vol >= last["vol"]:
                    dv = vol - last["vol"]
                last["vol"] = vol
            if lp == last["lp"] and not dv:
                return
            last["lp"] = lp
            q.put_nowait(Tick(float(st.get("lp_time") or time.time()), float(lp), float(dv)))

        await hub.subscribe(symbol, cb)
        try:
            while True:
                yield await q.get()
        finally:
            await hub.unsubscribe(symbol, cb)
