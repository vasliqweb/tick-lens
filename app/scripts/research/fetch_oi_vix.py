"""One-off research download (Breeze, free): India VIX 1m and NIFTY front-month FUT 1m with open interest.
Run from the app folder:  .venv\\Scripts\\python scripts\\research\\fetch_oi_vix.py   (or fetch_oi_vix.bat)
Writes data/research/vix_1m.csv and data/research/fut_oi_1m.csv. Uses your normal .env Breeze login (OTP if expired)."""
import asyncio, os, sys, calendar
from datetime import date, timedelta
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from core.breeze import BreezeHub
START = date(2026, 6, 15)
OUT = os.path.join(ROOT, "data", "research")
os.makedirs(OUT, exist_ok=True)
hub = BreezeHub.get()

async def hist(interval, s, e, **kw):
    await hub.limiter.wait()
    r = await hub.call("get_historical_data_v2", interval=interval, from_date=f"{s}T00:00:00.000Z",
                       to_date=f"{e}T23:59:59.000Z", **kw)
    rows = (r or {}).get("Success") or []
    if not rows and (r or {}).get("Error") and "No Data" not in str(r.get("Error")):
        print("  error:", str(r.get("Error"))[:150])
    return pd.DataFrame(rows)

async def series(tag, s0, e0, **kw):
    parts, s = [], s0
    while s <= e0:
        e = min(e0, s + timedelta(days=1))
        df = await hist("1minute", s, e, **kw)
        if len(df): parts.append(df)
        s = e + timedelta(days=1)
    print(f"{tag}: {sum(len(p) for p in parts)} rows")
    return pd.concat(parts) if parts else pd.DataFrame()

def tidy(df, extra=()):
    t = pd.to_datetime(df["datetime"]).dt.tz_localize("Asia/Kolkata").dt.tz_convert("UTC")
    out = pd.DataFrame({"time": ((t - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1s")).values})
    for c in ("open", "high", "low", "close", "volume") + tuple(extra):
        if c in df: out[c] = pd.to_numeric(df[c], errors="coerce").values
    return out.drop_duplicates("time").sort_values("time")

async def main():
    today = date.today()
    # ---- India VIX
    vix = pd.DataFrame()
    for code in ("INDVIX", "INDIAVIX"):
        test = await hist("1day", today - timedelta(days=10), today, stock_code=code, exchange_code="NSE", product_type="cash")
        if len(test):
            vix = await series(f"VIX ({code})", START, today, stock_code=code, exchange_code="NSE", product_type="cash"); break
        print("VIX code not found:", code)
    if len(vix):
        tidy(vix).to_csv(os.path.join(OUT, "vix_1m.csv"), index=False)
    # ---- NIFTY monthly futures: find each month's expiry (a weekday in the last 10 days), stitch front month
    fut = dict(stock_code="NIFTY", exchange_code="NFO", product_type="futures", right="others", strike_price="0")
    exps = []
    m = date(START.year, START.month, 1)
    while m <= today + timedelta(days=40):
        last = calendar.monthrange(m.year, m.month)[1]
        for d in range(last, last - 10, -1):
            x = date(m.year, m.month, d)
            if x.weekday() >= 5: continue
            probe_s = max(START, x - timedelta(days=25)); probe_e = min(today, x)
            if probe_s > probe_e: continue
            df = await hist("1day", probe_s, probe_e, expiry_date=f"{x}T06:00:00.000Z", **fut)
            if len(df):
                exps.append(x); print("FUT expiry found:", x); break
        m = (m + timedelta(days=32)).replace(day=1)
    parts, prev = [], START - timedelta(days=1)
    for x in exps:
        s, e = prev + timedelta(days=1), min(x, today)
        if s > today: break
        df = await series(f"FUT {x}", s, e, expiry_date=f"{x}T06:00:00.000Z", **fut)
        if len(df):
            t = tidy(df, ("open_interest",)); t["expiry"] = str(x); parts.append(t)
        prev = x
    if parts:
        pd.concat(parts).rename(columns={"open_interest": "oi"}).to_csv(os.path.join(OUT, "fut_oi_1m.csv"), index=False)
    print("done ->", OUT)

asyncio.run(main())
