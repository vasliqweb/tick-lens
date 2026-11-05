"""Money-flow research: does constituent money flow predict NIFTY 60 min ahead better than baselines?
Causal: features at bar t use data <= t close. Index cut at 15:15. Run: python3 mf_study.py <app_dir>"""
import sys, glob, os
import numpy as np, pandas as pd
APP = sys.argv[1] if len(sys.argv) > 1 else "."
sys.path.insert(0, APP)
from core.breeze import NIFTY50_FALLBACK as MEM
B = os.path.join(APP, "data", "Breeze")

def load(sym):
    out = {}
    for f in sorted(glob.glob(os.path.join(B, sym, "1m", "*.csv"))):
        d = pd.read_csv(f).drop_duplicates("time", keep="last").sort_values("time")
        t = pd.to_datetime(d.time, unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
        m = t.dt.hour * 60 + t.dt.minute
        d = d[(m >= 555) & (m < 915)].copy()
        d["m"] = m[d.index]
        if len(d) > 200:
            d = d.set_index("m"); out[os.path.basename(f)[:10]] = d[~d.index.duplicated(keep="last")]
    return out

import pickle, time as _t
CD = os.path.expanduser("~/mf_cache"); os.makedirs(CD, exist_ok=True)
nifty = load("NIFTY")
days = sorted(nifty)
T0 = _t.time()
def rd(sym, day):
    f = os.path.join(B, sym, "1m", day + ".csv")
    if not os.path.exists(f): return None
    d = pd.read_csv(f).drop_duplicates("time", keep="last").sort_values("time")
    t = pd.to_datetime(d.time, unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    m = t.dt.hour * 60 + t.dt.minute
    d = d[(m >= 555) & (m < 915)].copy(); d["m"] = m[d.index]
    d = d.set_index("m"); d = d[~d.index.duplicated(keep="last")]
    return d if len(d) > 200 else None
rows = []
for day in days:
    cf = os.path.join(CD, day + ".pkl")
    if os.path.exists(cf):
        rows += pickle.load(open(cf, "rb")); continue
    if _t.time() - T0 > 140:
        print("PARTIAL", day); sys.exit(0)
    n = nifty[day]
    flows, dr = [], []
    for s in MEM:
        d = rd(s, day)
        if d is None: continue
        rng = (d.high - d.low).replace(0, np.nan)
        clv = (((d.close - d.low) - (d.high - d.close)) / rng).fillna(0)
        tp = (d.high + d.low + d.close) / 3
        f = (clv * tp * d.volume).reindex(range(555, 915)).fillna(0)
        tr = (np.sign(d.close.diff().fillna(d.close - d.open)) * tp * d.volume).reindex(range(555, 915)).fillna(0)
        flows.append((f, tr))
    if len(flows) < 40: continue
    F = sum(f for f, _ in flows) / 1e7          # Rs crore / minute (CLV estimate)
    T = sum(t for _, t in flows) / 1e7          # tick-rule on 1m closes (estimate)
    cumF, cumT = F.cumsum(), T.cumsum()
    cb = sum((f.cumsum() > 0).astype(float) for f, _ in flows) / len(flows)   # flow breadth
    c = n.close.reindex(range(555, 915)).ffill()
    o = n.open.iloc[0]
    for m in range(600, 856, 5):                   # 10:00 .. 14:15 decision points
        if np.isnan(c[m]) or np.isnan(c.get(m + 60, np.nan)): continue
        fut = c[m + 60] - c[m]
        if fut == 0: continue
        dr.append(dict(day=day, m=m, y=np.sign(fut), op=c[m] - o, cumF=cumF[m], cumT=cumT[m],
                         f30=F.loc[m - 29:m].sum(), t30=T.loc[m - 29:m].sum(), fb=cb[m]))
    pickle.dump(dr, open(cf, "wb")); rows += dr
R = pd.DataFrame(rows)
ud = sorted(R.day.unique()); half = ud[len(ud) // 2]
print("days", len(ud), "rows", len(R), "split", half)

def acc(mask, sig, name):
    for lab, h in (("all", R.day >= ""), ("H1", R.day < half), ("H2", R.day >= half)):
        k = mask & h & (sig != 0)
        a = (np.sign(sig[k]) == R.y[k]).mean() if k.sum() else np.nan
        print(f"{name:42s} {lab} n={k.sum():5d} days={R.day[k].nunique():3d} acc={a*100:5.1f}")
one = pd.Series(True, index=R.index)
for col in ("op", "cumF", "cumT", "f30", "t30"):
    acc(one, R[col], col)
    q = R[col].abs() >= R[col].abs().quantile(.8)
    acc(q, R[col], col + " top20%")
acc(one, R.fb - .5, "flow breadth")
acc((R.fb - .5).abs() >= .2, R.fb - .5, "flow breadth >=70/<=30")
opq = R.op.abs() >= R.op.abs().quantile(.8)
agree = np.sign(R.op) == np.sign(R.cumF)
acc(opq & agree, R.op, "OP top20 & cumF agrees")
acc(opq & ~agree, R.op, "OP top20 & cumF disagrees")
agb = np.sign(R.op) == np.sign(R.fb - .5)
acc(opq & agb & ((R.fb-.5).abs()>=.2), R.op, "OP top20 & flowbreadth>=70 agrees")
# divergence: price above open but flow negative etc (contrarian)
acc(~agree & (R.op.abs()>0), -R.op, "fade OP when cumF disagrees")
