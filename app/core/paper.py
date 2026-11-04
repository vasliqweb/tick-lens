"""
Paper trading: simulated trades on live quotes. Nothing is ever sent to a broker.

Trades live in data/paper/trades.json. Market fills use the Breeze quote of the contract
(ask for buys, bid for sells, LTP when the book is empty); for symbols Breeze cannot quote
the browser's last price is used and the trade records which price source filled it.
SL / target / limit triggers are evaluated in the browser on streamed quotes (the app must be open).

Option picker: strikes on a fixed grid (100 by default for indices) around the underlying's
spot: ATM = round(spot / step) * step, ITM/OTM = ATM -/+ n * step for calls (reversed for puts),
then the nearest strike the exchange actually lists for that expiry.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException

from .symbols import FNO_RE, INDICES, canonical, to_source

log = logging.getLogger("paper")
ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "paper" / "trades.json"
ACCOUNT = ROOT / "data" / "paper" / "account.json"
START_CAPITAL = 500000.0
ALGO = "paper-1"
# NSE index lot sizes (fallback when the contract master has no lot column; editable in the ticket)
LOT_FALLBACK = {"NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 60, "MIDCPNIFTY": 120, "NIFTYNXT50": 25,
                "SENSEX": 20, "BANKEX": 30}
INDEX_STEP = 100                 # user preference: index strikes on the nearest hundred

router = APIRouter(prefix="/api/paper")
_lock = threading.Lock()


# ------------------------------------------------------------------ storage
def load() -> list:
    try:
        return json.loads(STORE.read_text())
    except (OSError, ValueError):
        return []


def save(trades: list) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(trades, indent=1))
    os.replace(tmp, STORE)


def load_account() -> dict:
    try:
        a = json.loads(ACCOUNT.read_text())
    except (OSError, ValueError):
        a = {}
    return {"capital": START_CAPITAL, "brokerage": 20.0, "since": 0, **a}


def account_summary(trades: Optional[list] = None, acct: Optional[dict] = None) -> dict:
    """Capital ledger since the last reset: balance = capital + booked P&L - brokerage; available = balance - blocked.
    Blocked funds = premium/value of open trades and pending limit entries (sold options block the premium too:
    a simplification, real SPAN margin is far higher)."""
    a = acct or load_account()
    trades = load() if trades is None else trades
    since, brk = a["since"], a["brokerage"]
    booked = fees = blocked = 0.0
    orders = 0
    for t in trades:
        if (t.get("createdAt") or 0) < since:
            continue
        if t["status"] == "closed":
            booked += t.get("pnl") or 0
            orders += 2
        elif t["status"] == "open":
            orders += 1
            blocked += t["entry"] * t["qty"]
        elif t["status"] == "pending":
            blocked += (t["limit"] or 0) * t["qty"]
    fees = orders * brk
    balance = a["capital"] + booked - fees
    return {**a, "booked": round(booked, 2), "fees": round(fees, 2), "orders": orders, "balance": round(balance, 2),
            "blocked": round(blocked, 2), "available": round(balance - blocked, 2)}


def _find(trades: list, tid: str) -> dict:
    for t in trades:
        if t["id"] == tid:
            return t
    raise HTTPException(404, "trade not found")


def _num(v, name: str, positive: bool = True) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{name} must be a number")
    if x != x or (positive and x <= 0):
        raise HTTPException(400, f"{name} must be > 0")
    return round(x, 4)


# ------------------------------------------------------------------ Breeze helpers
def _hub():
    from .breeze import BreezeHub
    hub = BreezeHub.get()
    return hub if hub.breeze is not None else None      # never start an OTP login from here


async def quote(symbol: str) -> Optional[dict]:
    """Breeze quote {last, bid, ask, prev} or None when Breeze is not connected / cannot quote it."""
    hub = _hub()
    if hub is None:
        return None
    try:
        info = await hub.resolve(to_source(symbol, "breeze"))
        q = await hub.quote(info["isec"], info.get("fno"))
    except Exception as e:
        log.info("paper quote %s: %s", symbol, e)
        return None
    if not q or not q.get("last"):
        return None
    return {**q, "source": "breeze", "at": time.time()}


def fill_price(q: dict, side: str) -> float:
    px = q.get("ask") if side == "buy" else q.get("bid")
    return float(px or q["last"])


_LOTS: dict = {}


def _lot_sizes() -> dict:
    """Underlying (app name) -> lot size, read from the SDK's NFO and BFO scrip masters when they have a lot column."""
    if _LOTS:
        return _LOTS
    out = dict(LOT_FALLBACK)
    try:
        import pandas as pd
        import breeze_connect.breeze_connect as sdk
        isec_to_app = {bz: n for n, (_, bz) in INDICES.items() if bz}
        names = {n.upper(): n for n in sdk.zip.namelist()}
        for fname in ("FOBSESCRIPMASTER.TXT", "FONSESCRIPMASTER.TXT"):     # NFO last: wins when both list it
            if fname not in names:
                continue
            df = pd.read_csv(sdk.zip.open(names[fname]), sep=",", dtype=str, engine="python")
            df.columns = [c.strip().strip('"') for c in df.columns]
            lot = next((c for c in df.columns if "lot" in c.lower()), None)
            under = next((c for c in ("ShortName", "Symbol", "ExchangeCode") if c in df.columns), None)
            if not (lot and under):
                continue
            cnt: dict = {}
            for u, l in zip(df[under].str.strip().str.strip('"'), df[lot].str.strip().str.strip('"')):
                try:
                    n = int(float(l))
                except (TypeError, ValueError):
                    continue
                if n > 0:
                    cnt.setdefault(isec_to_app.get(u, u), Counter())[n] += 1
            out.update({u: c.most_common(1)[0][0] for u, c in cnt.items()})
    except Exception as e:
        log.info("lot sizes from contract master unavailable (%s); using fallback table", e)
    _LOTS.update(out)
    return _LOTS


async def _contracts(under: str) -> list:
    hub = _hub()
    if hub is None:
        raise HTTPException(503, "Connect Breeze to trade options (option chain and premiums come from Breeze)")
    try:
        m = await hub.master()
    except Exception as e:
        raise HTTPException(503, f"Breeze not available: {e}"[:200])
    return [c for c in m["fno"] if c["under"] == under and c["kind"] == "OPT"]


def pick_strike(spot: float, strikes: list, right: str, money: str, n: int, step: float) -> tuple:
    """(target strike on the grid, nearest listed strike). money: ATM | ITM | OTM; n >= 1 for ITM/OTM."""
    atm = round(spot / step) * step
    k = 0 if money == "ATM" else max(1, n)
    sign = -1 if (money == "ITM") == (right == "CE") else 1   # CE ITM below spot, PE ITM above
    target = atm + sign * k * step if money != "ATM" else atm
    if not strikes:
        return atm, target, None
    return atm, target, min(strikes, key=lambda s: (abs(s - target), s))


def _grid(under: str, strikes: list) -> float:
    if under in INDICES:
        return INDEX_STEP
    gaps = sorted({round(b - a, 4) for a, b in zip(strikes, strikes[1:]) if b > a})
    return gaps[0] if gaps else 1.0


async def _spot(under: str, spot: Optional[float]) -> float:
    if spot:
        return spot
    q = await quote(under)
    if not q:
        raise HTTPException(409, f"no live price for {under}")
    return q["last"]


# ------------------------------------------------------------------ API
@router.get("/meta")
async def meta(under: str):
    """Option expiries and lot size for an underlying (NIFTY, BANKNIFTY, RELIANCE ...)."""
    under = canonical(under)
    cs = await _contracts(under)
    if not cs:
        raise HTTPException(404, f"{under} has no listed options")
    exps = sorted({c["expiry"] for c in cs if c["expiry"] >= date.today()})
    return {"under": under, "expiries": [e.isoformat() for e in exps[:10]],
            "lotSize": _lot_sizes().get(under), "step": _grid(under, sorted({c["strike"] for c in cs if c["expiry"] == exps[0]}))}


@router.get("/option")
async def option(under: str, right: str = "CE", money: str = "ATM", n: int = 1, expiry: str = "",
                 spot: Optional[float] = None, step: Optional[float] = None, quoted: bool = True):
    """Resolve ATM/ITM/OTM ±n to a listed contract and quote its premium."""
    under, right, money = canonical(under), right.upper(), money.upper()
    if right not in ("CE", "PE") or money not in ("ATM", "ITM", "OTM"):
        raise HTTPException(400, "right must be CE/PE, money ATM/ITM/OTM")
    cs = await _contracts(under)
    exps = sorted({c["expiry"] for c in cs if c["expiry"] >= date.today()})
    if not exps:
        raise HTTPException(404, f"{under} has no listed options")
    exp = next((e for e in exps if e.isoformat() == expiry), exps[0])
    chain = [c for c in cs if c["expiry"] == exp and c["right"] == right]
    strikes = sorted({c["strike"] for c in chain})
    s = await _spot(under, spot)
    g = step or _grid(under, strikes)
    atm, target, strike = pick_strike(s, strikes, right, money, n, g)
    if strike is None:
        raise HTTPException(404, f"no {right} strikes for {under} {exp}")
    c = next(c for c in chain if c["strike"] == strike)
    q = await quote(c["symbol"]) if quoted else None
    return {"symbol": c["symbol"], "under": under, "right": right, "strike": strike, "target": target, "atm": atm,
            "spot": s, "step": g, "expiry": exp.isoformat(), "lotSize": _lot_sizes().get(under),
            "offGrid": strike != target, "quote": q}


@router.get("/quote")
async def get_quote(symbol: str):
    q = await quote(canonical(symbol))
    if not q:
        raise HTTPException(409, "no Breeze quote")
    return q


@router.get("/account")
def get_account():
    return account_summary()


@router.put("/account")
def put_account(body: dict = Body(...)):
    """capital: new starting capital (resets the ledger to now); brokerage: per executed order."""
    a = load_account()
    if "capital" in body:
        a["capital"] = _num(body["capital"], "capital")
        a["since"] = time.time()            # fresh start: earlier trades no longer count
    if "brokerage" in body:
        a["brokerage"] = _num(body["brokerage"], "brokerage", positive=False) or 0.0
    ACCOUNT.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNT.write_text(json.dumps({k: a[k] for k in ("capital", "brokerage", "since")}))
    return account_summary(acct=a)


@router.get("/trades")
def trades():
    return load()


@router.post("/trades")
async def open_trade(body: dict = Body(...)):
    sym = canonical(str(body.get("symbol") or ""))
    if not sym:
        raise HTTPException(400, "symbol required")
    side = body.get("side")
    if side not in ("buy", "sell"):
        raise HTTPException(400, "side must be buy or sell")
    lots = int(_num(body.get("lots"), "lots") or 1)
    lot_size = int(_num(body.get("lotSize"), "lotSize") or 1)
    entry_type = body.get("entryType", "market")
    if entry_type not in ("market", "limit", "stop"):
        raise HTTPException(400, "entryType must be market, limit or stop")
    src = "breeze" if FNO_RE.match(sym) else str(body.get("src") or "breeze")   # quote from the chart's own source
    limit = _num(body.get("limit"), "limit")
    sl, target = _num(body.get("sl"), "sl"), _num(body.get("target"), "target")
    now = time.time()
    t = {"id": "t" + uuid.uuid4().hex[:10], "symbol": sym, "side": side, "lots": lots, "lotSize": lot_size,
         "qty": lots * lot_size, "under": canonical(body["under"]) if body.get("under") else None,
         "spot": _num(body.get("spot"), "spot"), "kind": ("OPT" if sym.endswith(("CE", "PE")) else "FUT") if FNO_RE.match(sym) else "CASH",
         "entryType": entry_type, "limit": limit, "sl": sl, "target": target, "exitLimit": None,
         "show": bool(body.get("show", True)), "src": src, "status": "pending", "createdAt": now, "algorithmVersion": ALGO,
         "entry": None, "entryAt": None, "entryQuote": None, "exit": None, "exitAt": None, "exitReason": None, "exitQuote": None,
         "events": [{"t": now, "e": "created", "type": entry_type, "limit": limit}]}
    if entry_type in ("limit", "stop"):
        if limit is None:
            raise HTTPException(400, f"{entry_type} price required")
    else:
        imported = body.get("imported") and body.get("price")   # migrated old order: keep its recorded fill
        q = await quote(sym) if src == "breeze" and not imported else None
        if q:
            px = fill_price(q, side)
        else:
            px = _num(body.get("price"), "price")
            if px is None:
                raise HTTPException(409, f"no live price for {sym} (connect Breeze for options)")
            q = {"last": px, "source": "imported" if imported else (body.get("src") or "chart"), "at": now}
        _fill(t, px, q, now)
    _check_levels(t)
    with _lock:
        all_ = load()
        need = (t["entry"] or t["limit"]) * t["qty"]
        acc = account_summary(all_)
        if need > acc["available"]:
            raise HTTPException(409, f"insufficient capital: needs ₹{need:,.2f}, available ₹{acc['available']:,.2f}")
        all_.insert(0, t)
        save(all_)
    return t


def _fill(t: dict, px: float, q: dict, now: float) -> None:
    t.update(status="open", entry=round(px, 4), entryAt=now, entryQuote=q)
    t["events"].append({"t": now, "e": "filled", "price": t["entry"], "source": q.get("source")})


def _check_levels(t: dict) -> None:
    ref = t["entry"] or t["limit"]
    if not ref:
        return
    long = t["side"] == "buy"
    if t["sl"] is not None and (t["sl"] >= ref if long else t["sl"] <= ref):
        raise HTTPException(400, f"SL must be {'below' if long else 'above'} entry {ref:g}")
    if t["target"] is not None and (t["target"] <= ref if long else t["target"] >= ref):
        raise HTTPException(400, f"target must be {'above' if long else 'below'} entry {ref:g}")


@router.patch("/trades/{tid}")
def update_trade(tid: str, body: dict = Body(...)):
    with _lock:
        all_ = load()
        t = _find(all_, tid)
        if "show" in body:
            t["show"] = bool(body["show"])
        if t["status"] in ("pending", "open"):
            changed = {}
            for k in ("sl", "target", "exitLimit"):
                if k in body:
                    t[k] = changed[k] = _num(body[k], k)
            if changed:
                _check_levels(t)
                t["events"].append({"t": time.time(), "e": "modified", **changed})
        save(all_)
    return t


@router.post("/trades/{tid}/fill")
async def fill_pending(tid: str, body: dict = Body(...)):
    """Browser saw the limit/stop entry price trade; Breeze trades are confirmed with a fresh quote first."""
    seen = _num(body.get("price"), "price")
    t = _find(load(), tid)
    if t["status"] != "pending":
        return t
    long, stop = t["side"] == "buy", t.get("entryType") == "stop"
    q = await quote(t["symbol"]) if t.get("src", "breeze") == "breeze" else None
    if t.get("src", "breeze") == "breeze":
        if not q:
            raise HTTPException(409, f"entry not confirmed: no fresh Breeze quote for {t['symbol']}")
        seen = q["last"]
    if seen is None:
        raise HTTPException(409, "price required")
    if not ((seen >= t["limit"]) if long == stop else (seen <= t["limit"])):
        raise HTTPException(409, f"entry not confirmed: LTP {seen:g} has not reached {t['limit']:g}")
    px = (fill_price(q, t["side"]) if q else seen) if stop else t["limit"]   # limit fills at its price, stop at market
    with _lock:
        all_ = load()
        t = _find(all_, tid)
        if t["status"] == "pending":
            _fill(t, px, {**(q or {"last": seen, "source": body.get("src") or "stream"}), "at": time.time(), "streamPrice": _num(body.get("price"), "price")}, time.time())
            save(all_)
    return t


@router.post("/trades/{tid}/exit")
async def exit_trade(tid: str, body: dict = Body(...)):
    """reason: market | limit | sl | target. Breeze trades are always priced/confirmed with a fresh server quote."""
    reason = body.get("reason", "market")
    t = _find(load(), tid)
    if t["status"] == "pending":                       # an unfilled limit entry is simply cancelled
        return _close(tid, None, "cancelled", None)
    if t["status"] != "open":
        return t
    long = t["side"] == "buy"
    breeze = t.get("src", "breeze") == "breeze"
    q = await quote(t["symbol"]) if breeze else None
    if reason == "market":
        if q:
            px = fill_price(q, "sell" if long else "buy")
        else:
            px = _num(body.get("price"), "price")
            if px is None:
                raise HTTPException(409, f"no live price for {t['symbol']}")
            q = {"last": px, "source": body.get("src") or "stream", "at": time.time()}
    else:
        # SL / target / exit-limit: the browser saw a streamed price cross the level. Confirm it with a fresh
        # quote before closing (a stale or wrong tick must never close a trade), then fill like real orders:
        # target / exit limit = resting limit order -> the level itself; SL = stop-market -> the confirmed bid/ask.
        level = {"sl": t.get("sl"), "target": t.get("target"), "limit": t.get("exitLimit")}.get(reason)
        if level is None:
            raise HTTPException(400, f"no {reason} level on this trade")
        seen = _num(body.get("price"), "price")
        if breeze:
            if not q:
                raise HTTPException(409, f"{reason} not confirmed: no fresh Breeze quote for {t['symbol']}")
            seen = q["last"]
        elif seen is None:
            raise HTTPException(409, "price required")
        hit = (seen <= level if long else seen >= level) if reason == "sl" else (seen >= level if long else seen <= level)
        if not hit:
            raise HTTPException(409, f"{reason} not confirmed: LTP {seen:g} has not crossed {level:g}")
        if reason == "sl":
            px = fill_price(q, "sell" if long else "buy") if q else seen
        else:
            px = level
        if not q:
            q = {"last": seen, "source": body.get("src") or "stream", "at": time.time()}
        q = {**q, "streamPrice": _num(body.get("price"), "price")}
    return _close(tid, px, reason, q)


def _close(tid: str, px: Optional[float], reason: str, q: Optional[dict]) -> dict:
    with _lock:
        all_ = load()
        t = _find(all_, tid)
        now = time.time()
        if reason == "cancelled":
            t.update(status="cancelled", exitAt=now, exitReason="cancelled")
        elif t["status"] == "open":
            sign = 1 if t["side"] == "buy" else -1
            t.update(status="closed", exit=round(px, 4), exitAt=now, exitReason=reason, exitQuote=q, exitLimit=None,
                     pnl=round(sign * (px - t["entry"]) * t["qty"], 2))
        t["events"].append({"t": now, "e": t["status"], "price": t.get("exit"), "reason": reason})
        save(all_)
    return t


@router.delete("/trades/{tid}")
def delete_trade(tid: str):
    with _lock:
        all_ = load()
        t = _find(all_, tid)
        if t["status"] in ("open", "pending"):
            raise HTTPException(409, "exit the trade first")
        save([x for x in all_ if x["id"] != tid])
    return {"ok": True}


@router.delete("/trades")
def clear_closed():
    with _lock:
        save([x for x in load() if x["status"] in ("open", "pending")])
    return {"ok": True}
