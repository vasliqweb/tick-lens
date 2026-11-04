"""Index options open interest, 1 minute, for the nearest expiry ("active options": strikes around the money).

Files (one per trading day, long format):
  data/Breeze/<INDEX>/options/YYYY-MM-DD.csv   time,expiry,strike,right,close,volume,oi
  data/Breeze/<INDEX>/options/expiries.json    expiry probes {"yes": [...], "no": [...]} (never repeated)

time = 1m candle start, UTC epoch seconds (same as the app's candle files). oi = exchange open interest at the end of
that minute as Breeze reports it (0 = not reported -> treated as missing). Observed data only, nothing is filled in.

History is downloaded by scripts/options_oi/fetch_options_oi.py (run on your PC, Breeze login). Today's file is
kept fresh by LIVE (core app, every REFRESH s while a chart that uses options_chain() is open).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger("ltv.options")
ROOT = Path(__file__).resolve().parent.parent / "data" / "Breeze"
COLS = ["time", "expiry", "strike", "right", "close", "volume", "oi"]
IST = "Asia/Kolkata"
REFRESH = float(os.environ.get("OPTIONS_OI_REFRESH", "120"))   # seconds between live refreshes of today's chain
LIVE_WIDTH = int(os.environ.get("OPTIONS_OI_LIVE_WIDTH", "7"))  # strikes each side of spot refreshed live
# underlying: Breeze stock code, derivative exchange, strike step, weekly expiries?
UNDERLYINGS = {
    "NIFTY": ("NIFTY", "NFO", 50, True),
    "BANKNIFTY": ("CNXBAN", "NFO", 100, False),
    "FINNIFTY": ("NIFFIN", "NFO", 50, False),
    "MIDCPNIFTY": ("NIFMID", "NFO", 25, False),
    "SENSEX": ("BSESEN", "BFO", 100, True),
}


def underlying_of(symbol: str) -> Optional[str]:
    """'NIFTY' / 'NIFTY 23NOV26 FUT' -> 'NIFTY'; anything else (stocks, option contracts) -> None."""
    s = (symbol or "").upper().strip()
    if s in UNDERLYINGS:
        return s
    p = s.split()
    if len(p) == 3 and p[0] in UNDERLYINGS and p[2] == "FUT":
        return p[0]
    return None


def step_of(und: str) -> int:
    return UNDERLYINGS[und][2]


def opt_dir(und: str) -> Path:
    return ROOT / und / "options"


def _ist_today() -> date:
    return pd.Timestamp.now(tz=IST).date()


# ---------------------------------------------------------------- reading (script thread, no network)
_day_cache: Dict[Tuple[str, str], Tuple[float, Optional[pd.DataFrame]]] = {}
_live_mem: Dict[str, pd.DataFrame] = {}          # und -> today's rows held in memory by LIVE


def read_day(und: str, day: date) -> Optional[pd.DataFrame]:
    f = opt_dir(und) / f"{day}.csv"
    if not f.exists():
        return None
    mt = os.path.getmtime(f)
    hit = _day_cache.get((und, str(day)))
    if hit and hit[0] >= mt:
        return hit[1]
    try:
        d = pd.read_csv(f)
    except Exception as e:
        log.warning("options file %s: %s", f, e)
        d = None
    if d is not None and not d.empty:
        d = d[COLS].drop_duplicates(["time", "strike", "right"], keep="last")
        d["oi"] = pd.to_numeric(d["oi"], errors="coerce").replace(0, np.nan)
    _day_cache[(und, str(day))] = (mt, d)
    return d


def chain_1m(und: str, start: pd.Timestamp, end: pd.Timestamp) -> Optional[pd.DataFrame]:
    """Long frame of every stored option minute in [start, end] (UTC-naive), sorted by time; None if nothing."""
    parts, d = [], start.date()
    today = _ist_today()
    while d <= end.date():
        if d.weekday() < 5:
            x = _live_mem.get(und) if d == today and und in _live_mem else read_day(und, d)
            if x is not None and len(x):
                parts.append(x)
        d += timedelta(days=1)
    if not parts:
        return None
    out = pd.concat(parts, ignore_index=True)
    t0, t1 = int(start.value // 10**9), int(end.value // 10**9)
    out = out[(out.time >= t0) & (out.time <= t1)]
    return out.sort_values(["time", "strike", "right"]).reset_index(drop=True) if len(out) else None


def coverage(und: str) -> List[str]:
    """Days with a stored options file (for the fetch script / table)."""
    d = opt_dir(und)
    return sorted(p.stem for p in d.glob("????-??-??.csv")) if d.exists() else []


# ---------------------------------------------------------------- Breeze download (event loop)
def _probes(und: str) -> dict:
    f = opt_dir(und) / "expiries.json"
    try:
        return json.loads(f.read_text())
    except Exception:
        return {"yes": [], "no": []}


def _save_probes(und: str, p: dict):
    f = opt_dir(und) / "expiries.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"yes": sorted(set(p["yes"])), "no": sorted(set(p["no"]))}))


async def _hist(hub, und: str, interval: str, s: date, e: date, expiry: date, strike: float, right: str) -> pd.DataFrame:
    isec, exch, _, _ = UNDERLYINGS[und]
    await hub.limiter.wait()
    r = await hub.call("get_historical_data_v2", interval=interval, from_date=f"{s}T00:00:00.000Z",
                       to_date=f"{e}T23:59:59.000Z", stock_code=isec, exchange_code=exch, product_type="options",
                       right=right, strike_price=f"{strike:g}", expiry_date=f"{expiry}T06:00:00.000Z")
    rows = (r or {}).get("Success") or []
    if not rows:
        err = (r or {}).get("Error")
        if err and "No Data" not in str(err):
            log.info("options %s %s %g %s: %s", und, expiry, strike, right, str(err)[:120])
        return pd.DataFrame()
    return pd.DataFrame(rows)


async def find_expiry(hub, und: str, day: date, spot: float, master_expiries: Optional[List[date]] = None) -> Optional[date]:
    """Nearest expiry on or after `day` (expiry day itself counts). Probes are cached in expiries.json."""
    if master_expiries:
        fut = sorted(e for e in master_expiries if e >= day)
        if fut:
            return fut[0]
    weekly = UNDERLYINGS[und][3]
    p = _probes(und)
    yes, no = set(p["yes"]), set(p["no"])
    k = round(spot / (2 * step_of(und))) * 2 * step_of(und)
    for i in range(0, 45):
        d = day + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        if not weekly and (nxt - d).days > 10:            # monthly contracts expire in the month's last days
            continue
        ds = str(d)
        if ds in yes:
            return d
        if ds in no:
            continue
        probe_to = min(d, _ist_today())
        df = await _hist(hub, und, "1day", day, probe_to, d, k, "call")
        (yes if len(df) else no).add(ds)
        _save_probes(und, {"yes": list(yes), "no": list(no)})
        if len(df):
            return d
    return None


def _tidy(raw: pd.DataFrame, expiry: date, strike: float, right: str) -> pd.DataFrame:
    t = pd.to_datetime(raw["datetime"]).dt.tz_localize(IST).dt.tz_convert("UTC")
    out = pd.DataFrame({"time": ((t - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1s")).values})
    out["expiry"] = str(expiry)
    out["strike"] = float(strike)
    out["right"] = "CE" if right == "call" else "PE"
    out["close"] = pd.to_numeric(raw.get("close"), errors="coerce").values
    out["volume"] = pd.to_numeric(raw.get("volume"), errors="coerce").values
    out["oi"] = pd.to_numeric(raw.get("open_interest"), errors="coerce").values
    return out


async def fetch_day(hub, und: str, day: date, lo: float, hi: float, width: int = 10, max_strikes: int = 41,
                    expiry: Optional[date] = None, master_expiries: Optional[List[date]] = None,
                    strikes: Optional[List[float]] = None, save: bool = True) -> Optional[pd.DataFrame]:
    """Download 1m CE+PE of the nearest expiry for strikes covering [lo, hi] +- width steps. Writes the day file."""
    st = step_of(und)
    if expiry is None:
        expiry = await find_expiry(hub, und, day, (lo + hi) / 2, master_expiries)
    if expiry is None:
        log.warning("options %s %s: no expiry found", und, day)
        return None
    if strikes is None:
        a = int(np.floor(lo / st)) - width
        b = int(np.ceil(hi / st)) + width
        mid = int(round((lo + hi) / 2 / st))
        ks = sorted(range(a, b + 1), key=lambda k: abs(k - mid))[:max_strikes]
        strikes = sorted(k * st for k in ks)
    parts = []
    for k in strikes:
        for right in ("call", "put"):
            raw = await _hist(hub, und, "1minute", day, day, expiry, k, right)
            if len(raw):
                parts.append(_tidy(raw, expiry, k, right))
    if not parts:
        return None
    df = pd.concat(parts, ignore_index=True)
    from .breeze import in_session
    df = df[[in_session(float(x), fno=True) for x in df.time]]
    df = df.sort_values(["time", "strike", "right"])[COLS]
    if save:
        _write_day(und, day, df)
    return df


def _write_day(und: str, day: date, df: pd.DataFrame, merge: bool = True):
    f = opt_dir(und) / f"{day}.csv"
    f.parent.mkdir(parents=True, exist_ok=True)
    if merge and f.exists():
        try:
            old = pd.read_csv(f)[COLS]
            df = pd.concat([old, df]).drop_duplicates(["time", "strike", "right"], keep="last")
        except Exception:
            pass
    tmp = f.with_suffix(".tmp")
    df.sort_values(["time", "strike", "right"]).to_csv(tmp, index=False)
    os.replace(tmp, f)


# ---------------------------------------------------------------- live (today) refresher
class LiveChain:
    """Keeps today's chain fresh for an underlying: every REFRESH s, re-downloads today's 1m for the strikes
    LIVE_WIDTH steps around the latest spot (~30 Breeze calls, ~20 s of the 90/min budget). Non-blocking: charts
    read whatever is in memory / on disk."""

    def __init__(self):
        self.last: Dict[str, float] = {}
        self.busy: Dict[str, bool] = {}
        self.status: Dict[str, dict] = {}

    def kick(self, loop, und: str, spot: float):
        if not und or spot != spot:
            return
        now = time.time()
        if self.busy.get(und) or now - self.last.get(und, 0) < REFRESH:
            return
        from .breeze import in_session
        today = _ist_today()
        if not in_session(now, fno=True) and str(today) in coverage(und) and now - self.last.get(und, 0) < 3600:
            return
        if today.weekday() >= 5:
            return
        self.busy[und] = True
        asyncio.run_coroutine_threadsafe(self._run(und, spot, today), loop)

    async def _run(self, und: str, spot: float, today: date):
        try:
            from .breeze import BreezeHub
            hub = BreezeHub.get()
            if hub.breeze is None:                      # never trigger a login from a chart overlay
                self.status[und] = {"ok": False, "msg": "Breeze not logged in"}
                return
            exps = None
            try:
                m = await hub.master()
                exps = sorted({c["expiry"] for c in m["fno"] if c["under"] == und and c["kind"] == "OPT"})
            except Exception:
                pass
            df = await fetch_day(hub, und, today, spot, spot, width=LIVE_WIDTH, master_expiries=exps, save=False)
            if df is not None and len(df):
                old = _live_mem.get(und)
                if old is None:
                    old = await asyncio.to_thread(read_day, und, today)    # no disk I/O on the event loop
                if old is not None and len(old):
                    df = pd.concat([old[COLS], df]).drop_duplicates(["time", "strike", "right"], keep="last")
                df = df.sort_values(["time", "strike", "right"]).reset_index(drop=True)
                df["oi"] = pd.to_numeric(df["oi"], errors="coerce").replace(0, np.nan)
                _live_mem[und] = df
                await asyncio.to_thread(_write_day, und, today, df.fillna({"oi": 0}), False)
                self.status[und] = {"ok": True, "upto": int(df.time.max()), "at": time.time()}
        except Exception as e:
            log.warning("options live %s: %s", und, e)
            self.status[und] = {"ok": False, "msg": str(e)[:120]}
        finally:
            self.last[und] = time.time()
            self.busy[und] = False


LIVE = LiveChain()
