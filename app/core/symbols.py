"""
One symbol name for every source.

The app uses NSE-style names everywhere (RELIANCE, M&M, NIFTY, BANKNIFTY) and translates
them to each source's own ticker only when talking to that source:

    name        Yahoo           Breeze
    RELIANCE    RELIANCE.NS     RELIANCE (resolved to RELIND by BreezeHub)
    NIFTY       ^NSEI           NIFTY
    BANKNIFTY   ^NSEBANK        CNXBAN
    SENSEX      ^BSESN          BSESEN (exchange BSE; options on BFO: "SENSEX 13NOV26 80000 CE")

Names that already carry a Yahoo suffix/prefix (TCS.BO, ^GSPC, BTC-USD, EURINR=X) pass through to Yahoo.
"""
from __future__ import annotations

import re

INDICES = {
    # name:        (yahoo,                  breeze)
    "NIFTY":       ("^NSEI",                "NIFTY"),
    "BANKNIFTY":   ("^NSEBANK",             "CNXBAN"),
    "FINNIFTY":    ("NIFTY_FIN_SERVICE.NS", "NIFFIN"),
    "NIFTYIT":     ("^CNXIT",               "CNXIT"),
    "MIDCPNIFTY":  ("NIFTY_MID_SELECT.NS",  "NIFMID"),
    "SENSEX":      ("^BSESN",               "BSESEN"),
    "BANKEX":      ("BSE-BANK.BO",          "BANKEX"),
}
# BSE-listed indices (Breeze: exchange BSE, derivatives on BFO); everything else above is NSE / NFO
BSE_INDICES = {"SENSEX", "BANKEX"}
# F&O contracts (Breeze only): "NIFTY 27NOV26 FUT", "BANKNIFTY 25NOV26 52000 CE", "RELIANCE 27NOV26 1400 PE"
FNO_RE = re.compile(r"^(?P<under>[A-Z0-9&\-]+) (?P<exp>\d{2}[A-Z]{3}\d{2}) (?:(?P<fut>FUT)|(?P<strike>\d+(?:\.\d+)?) (?P<right>CE|PE))$")


def is_fno(sym: str) -> bool:
    return bool(FNO_RE.match(sym.strip().upper()))


_FROM_YF = {yf: name for name, (yf, _) in INDICES.items()}
_FROM_BREEZE = {bz: name for name, (_, bz) in INDICES.items() if bz}


def canonical(sym: str) -> str:
    """Any spelling (RELIANCE.NS, ^NSEI, CNXBAN, nifty) -> app name (RELIANCE, NIFTY, BANKNIFTY)."""
    s = " ".join(sym.strip().upper().split())
    if is_fno(s):
        return s
    if s in _FROM_YF:
        return _FROM_YF[s]
    if s in _FROM_BREEZE:
        return _FROM_BREEZE[s]
    if s.endswith(".NS"):
        return s[:-3]
    return s


def exchange_of(sym: str) -> str:
    """Listing exchange label for an app name: NSE, BSE, MCX, or "" for non-Indian instruments."""
    s = canonical(sym)
    if ":" in s:
        ex = s.split(":", 1)[0]
        return ex if ex in ("NSE", "BSE", "MCX") else ""
    m = FNO_RE.match(s)
    base = m.group("under") if m else s
    if base in BSE_INDICES or s.endswith(".BO"):
        return "BSE"
    return "NSE" if is_nse(s) else ""


def is_nse(sym: str) -> bool:
    s = canonical(sym)
    return s in INDICES or not any(c in s for c in ".^=/ ") and not s.endswith("-USD")


def to_source(sym: str, source: str) -> str:
    s = canonical(sym)
    if source == "tv":
        from .tradingview import tv_symbol
        if is_fno(s):
            raise ValueError("NSE F&O contracts: use Breeze (TradingView names look like NSE:NIFTY1!)")
        return tv_symbol(s)
    if is_fno(s):
        if source != "breeze":
            raise ValueError("futures & options are available on Breeze only")
        return s
    if source == "yf":
        if s in INDICES:
            return INDICES[s][0]
        return s if not is_nse(s) else f"{s}.NS"
    if source == "breeze":
        if s in INDICES:
            if not INDICES[s][1]:
                raise ValueError(f"{s} is not available on Breeze")
            return INDICES[s][1]
        if not is_nse(s):
            raise ValueError(f"{s} is not an NSE symbol (Breeze covers NSE stocks, NSE/BSE indices and NFO/BFO F&O)")
        return s
    return s


# exchange prefix (TradingView) -> (timezone, regular session, currency); Yahoo suffixes map onto these
EXCHANGES = {
    "NASDAQ": ("America/New_York", "0930-1600", "USD"), "NYSE": ("America/New_York", "0930-1600", "USD"),
    "AMEX": ("America/New_York", "0930-1600", "USD"), "CME": ("America/Chicago", "1700-1600", "USD"),
    "CME_MINI": ("America/Chicago", "1700-1600", "USD"), "COMEX": ("America/New_York", "1800-1700", "USD"),
    "NYMEX": ("America/New_York", "1800-1700", "USD"), "TSX": ("America/Toronto", "0930-1600", "CAD"),
    "LSE": ("Europe/London", "0800-1630", "GBP"), "XETR": ("Europe/Berlin", "0900-1730", "EUR"),
    "EURONEXT": ("Europe/Paris", "0900-1730", "EUR"), "SIX": ("Europe/Zurich", "0900-1730", "CHF"),
    "TSE": ("Asia/Tokyo", "0900-1530", "JPY"), "HKEX": ("Asia/Hong_Kong", "0930-1600", "HKD"),
    "SSE": ("Asia/Shanghai", "0930-1500", "CNY"), "SZSE": ("Asia/Shanghai", "0930-1500", "CNY"),
    "SGX": ("Asia/Singapore", "0900-1700", "SGD"), "ASX": ("Australia/Sydney", "1000-1600", "AUD"),
    "KRX": ("Asia/Seoul", "0900-1530", "KRW"), "TWSE": ("Asia/Taipei", "0900-1330", "TWD"),
    "BMFBOVESPA": ("America/Sao_Paulo", "1000-1700", "BRL"), "TADAWUL": ("Asia/Riyadh", "1000-1500", "SAR"),
}
SUFFIX_EX = {"L": "LSE", "DE": "XETR", "PA": "EURONEXT", "AS": "EURONEXT", "SW": "SIX", "T": "TSE", "HK": "HKEX",
             "SS": "SSE", "SZ": "SZSE", "SI": "SGX", "AX": "ASX", "KS": "KRX", "TW": "TWSE", "SA": "BMFBOVESPA",
             "TO": "TSX", "SR": "TADAWUL"}


def syminfo_for(sym: str, source: str) -> dict:
    """Instrument facts for indicator scripts (Pine's syminfo.*): type, timezone, session, 24x7, mintick."""
    s = canonical(sym)
    u = s.upper()
    if source == "ccxt" or u.startswith(("BINANCE:", "BYBIT:", "COINBASE:", "BITSTAMP:", "KRAKEN:")) or u.endswith(("-USD", "USDT", "/USDT")):
        return {"ticker": s, "source": source, "type": "crypto", "timezone": "UTC", "session": "0000-2400",
                "is24x7": True, "mintick": 0.01, "currency": "USD"}
    if u.startswith("MCX:"):
        return {"ticker": s, "source": source, "type": "commodity", "timezone": "Asia/Kolkata", "session": "0900-2330",
                "is24x7": False, "mintick": 1.0, "currency": "INR"}
    if source == "sim":
        return {"ticker": s, "source": source, "type": "stock", "timezone": "UTC", "session": "0000-2400",
                "is24x7": True, "mintick": 0.01, "currency": "USD"}
    bare = u.split(":", 1)[1] if ":" in u else u
    nse = u.startswith(("NSE:", "BSE:")) if ":" in u else (is_fno(s) or is_nse(s) or u.endswith(".BO"))
    if nse:
        if is_fno(s):
            typ = "future" if FNO_RE.match(s).group("fut") else "option"
        elif bare.endswith("1!") or bare.endswith("2!"):
            typ = "future"
        elif bare in INDICES or bare in ("CNXNIFTY", "BANKNIFTY", "NIFTY"):
            typ = "index"
        else:
            typ = "stock"
        fno = typ in ("future", "option")
        return {"ticker": s, "source": source, "type": typ, "timezone": "Asia/Kolkata",
                "session": "0915-1540" if fno else "0915-1515", "is24x7": False, "mintick": 0.05, "currency": "INR",
                "vix": "INDIAVIX" if (typ == "index" or fno) and ("NIFTY" in bare) else None,
                "exchange": exchange_of(s) or ("BSE" if u.startswith("BSE:") else "NSE")}
    ex = u.split(":", 1)[0] if ":" in u else ""
    suffix = u.rsplit(".", 1)[1] if "." in u and ":" not in u else ""
    tz = EXCHANGES.get(ex) or EXCHANGES.get(SUFFIX_EX.get(suffix, ""))
    if tz:
        zone, sess, cur = tz
        return {"ticker": s, "source": source, "type": "future" if bare.endswith(("1!", "2!")) else "stock",
                "timezone": zone, "session": sess, "is24x7": False, "mintick": 0.01, "currency": cur, "vix": None}
    return {"ticker": s, "source": source, "type": "index" if u.startswith("^") else "stock", "timezone": "America/New_York",
            "session": "0930-1600", "is24x7": False, "mintick": 0.01, "currency": "USD", "vix": "^VIX" if u.startswith("^") else None}
