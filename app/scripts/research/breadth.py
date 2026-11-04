"""NIFTY 50 breadth from cached constituent 1m candles -> data/research/breadth_1m.csv (causal, per minute).
cols: time (UTC epoch of the 1m bar), n, adv_open (share of stocks above today's open), adv_pc (above prev close),
      mean_ret_open (equal-weight % move since open), above_vwap (share above own VWAP), up_vol (share of volume on up bars, cumulative)."""
import glob, os, sys, numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
D = os.path.join(ROOT, "data", "Breeze")
NIFTY50 = """ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE BAJAJFINSV BEL BHARTIARTL
CIPLA COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM HCLTECH HDFCBANK HDFCLIFE HINDALCO HINDUNILVR ICICIBANK INDIGO INFY
ITC JIOFIN JSWSTEEL KOTAKBANK LT M&M MARUTI MAXHEALTH NESTLEIND NTPC ONGC POWERGRID RELIANCE SBILIFE SBIN SHRIRAMFIN
SUNPHARMA TATACONSUM TMPV TATASTEEL TCS TECHM TITAN TRENT ULTRACEMCO WIPRO""".split()
def load(s):
    fs = sorted(glob.glob(os.path.join(D, s, "1m", "*.csv")))
    if not fs: return None
    df = pd.concat([pd.read_csv(f) for f in fs]).drop_duplicates("time").sort_values("time").set_index("time")
    ist = pd.to_datetime(df.index, unit="s", utc=True).tz_convert("Asia/Kolkata")
    m = ist.hour * 60 + ist.minute
    df = df[(m >= 555) & (m < 915)]
    return df
cols = {k: {} for k in ("c", "o", "pc", "vw", "uv", "tv")}
used = []
for s in NIFTY50:
    df = load(s)
    if df is None or len(df) < 1000: continue
    used.append(s)
    day = pd.to_datetime(df.index, unit="s", utc=True).tz_convert("Asia/Kolkata").normalize()
    g = df.groupby(day)
    o = g.open.transform("first"); last = g.close.last(); pc = pd.Series(last.shift(1).reindex(day).values, index=df.index)
    tp = (df.high + df.low + df.close) / 3; v = df.volume.clip(lower=0)
    vw = (tp * v).groupby(day).cumsum() / v.groupby(day).cumsum().replace(0, np.nan)
    upv = (v * (df.close > df.open)).groupby(day).cumsum(); tv = v.groupby(day).cumsum()
    for k, x in (("c", df.close), ("o", o), ("pc", pc), ("vw", vw), ("uv", upv), ("tv", tv)):
        cols[k][s] = x
P = {k: pd.DataFrame(v).sort_index() for k, v in cols.items()}
C = P["c"].ffill(limit=5)   # a quiet stock keeps its last price for up to 5 minutes (causal)
out = pd.DataFrame(index=C.index)
ok = C.notna()
out["n"] = ok.sum(axis=1)
out["adv_open"] = ((C > P["o"]) & ok).sum(axis=1) / out.n
out["adv_pc"] = ((C > P["pc"]) & ok).sum(axis=1) / out.n
out["mean_ret_open"] = ((C / P["o"] - 1) * 100).mean(axis=1)
out["above_vwap"] = ((C > P["vw"]) & ok).sum(axis=1) / out.n
out["up_vol"] = P["uv"].ffill(limit=5).sum(axis=1) / P["tv"].ffill(limit=5).sum(axis=1).replace(0, np.nan)
out.index.name = "time"
os.makedirs(os.path.join(ROOT, "data", "research"), exist_ok=True)
out.round(5).to_csv(os.path.join(ROOT, "data", "research", "breadth_1m.csv"))
print("stocks used:", len(used), "rows:", len(out), "days:", pd.to_datetime(out.index, unit="s").normalize().nunique())
