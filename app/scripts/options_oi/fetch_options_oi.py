"""Download history of nearest-expiry index options (1m premium, volume, open interest) from Breeze (free).
Used by the "Options Positioning Bubbles" indicator. Run from the app folder (app NOT required to be running):

    .venv\\Scripts\\python scripts\\options_oi\\fetch_options_oi.py --index NIFTY --days 40
    (or double-click scripts\\options_oi\\fetch_options_oi.bat)

Writes data/Breeze/<INDEX>/options/YYYY-MM-DD.csv. Days already stored are skipped (safe to re-run / resume).
Cost: ~2 x (strikes) Breeze calls per day (~40-60), rate-limited to 90/min -> about 30-40 s per day.
Strikes: the day's low..high from your cached index 1m file, +-width steps (max 41 strikes)."""
import argparse, asyncio, os, sys
from datetime import date, timedelta
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from core.breeze import BreezeHub, in_session
from core import options_oi as oo


def day_range(index, d):
    f = os.path.join(ROOT, "data", "Breeze", index, "1m", f"{d}.csv")
    if not os.path.exists(f):
        return None
    x = pd.read_csv(f)
    x = x[[in_session(float(t)) for t in x.time]]
    x = x[x.close > 0]
    return (float(x.low.min()), float(x.high.max())) if len(x) else None


async def index_range(hub, index, d):
    isec, _, _, _ = oo.UNDERLYINGS[index]
    exch = "BSE" if index in ("SENSEX", "BANKEX") else "NSE"
    await hub.limiter.wait()
    r = await hub.call("get_historical_data_v2", interval="1day", from_date=f"{d}T00:00:00.000Z", to_date=f"{d}T23:59:59.000Z",
                       stock_code=isec, exchange_code=exch, product_type="cash")
    rows = (r or {}).get("Success") or []
    return (float(rows[0]["low"]), float(rows[0]["high"])) if rows else None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="NIFTY", help="NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX (comma list ok)")
    ap.add_argument("--days", type=int, default=40, help="calendar days back from yesterday")
    ap.add_argument("--width", type=int, default=8, help="extra strikes beyond the day's range, each side")
    ap.add_argument("--force", action="store_true", help="re-download days already stored")
    a = ap.parse_args()
    hub = BreezeHub.get()
    await hub.client()
    today = date.today()
    for index in [s.strip().upper() for s in a.index.split(",") if s.strip()]:
        if index not in oo.UNDERLYINGS:
            print("unknown index", index); continue
        have = set(oo.coverage(index))
        d = today - timedelta(days=a.days)
        while d < today:
            if d.weekday() >= 5 or (str(d) in have and not a.force):
                d += timedelta(days=1); continue
            rg = day_range(index, d) or await index_range(hub, index, d)
            if not rg:
                print(index, d, "holiday / no index data"); d += timedelta(days=1); continue
            try:   # past days: expiry found by probing (expired contracts are not in the master)
                df = await oo.fetch_day(hub, index, d, rg[0], rg[1], width=a.width)
            except Exception as e:
                print(index, d, "error:", e); d += timedelta(days=1); continue
            if df is None or not len(df):
                print(index, d, "no option data")
            else:
                print(index, d, f"expiry {df.expiry.iloc[0]}  strikes {df.strike.nunique()}  rows {len(df)}  OI rows {(df.oi > 0).sum()}")
            d += timedelta(days=1)
    print("done ->", os.path.join(ROOT, "data", "Breeze", "<INDEX>", "options"))

asyncio.run(main())
