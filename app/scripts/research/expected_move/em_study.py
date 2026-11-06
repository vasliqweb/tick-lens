"""Expected Move Bands calibration study (NIFTY, research only, causal).

At an anchor minute A (09:20, 10:15, 11:15, 12:15, 13:15, 14:15 IST) using data <= A only:
  S      = NIFTY 1m close at A
  rem    = trading minutes from A to the 15:15 target (the study's session cut)
  VIX    sigma_rem = VIX/100 / sqrt(252) * sqrt(rem / 375)            (375 = 09:15-15:30 trading minutes)
  STRAD  ATM straddle (CE+PE, strike nearest S, nearest expiry) at A:  sigma_T*S ~ straddle / 0.8,
         T = trading minutes from A to 15:30 on expiry day (weekdays, 375/day); sigma_rem = sigma_T * sqrt(rem / T)
  Band z: 50% = 0.674, 68% = 0.994, 90% = 1.645.  Band = S +- z * sigma_rem * S  (times k for calibrated versions)
Calibrated (CAL): k fitted on the FIRST half of days so 68% of 15:15 closes fall inside the 68% band (09:20 anchor,
  fitted per anchor time); then tested on the second half.
Outcomes per day and anchor: CLOSE = 15:15 close inside the band; TOUCH = every 1m high/low from A to 15:15 inside.
Pass rule: on the second half, each band's CLOSE hit rate within +-6 points of its stated %.
Run: python em_study.py <app_dir>
"""
import glob
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

APP = sys.argv[1] if len(sys.argv) > 1 else "."
B = os.path.join(APP, "data", "Breeze", "NIFTY")
S0, S1, CLOSE = 555, 915, 930
Z = {50: 0.674, 68: 0.994, 90: 1.645}
ANCH = {"09:20": 560, "10:15": 615, "11:15": 675, "12:15": 735, "13:15": 795, "14:15": 855}
RNG = np.random.default_rng(11)


def ist_minutes(t):
    tt = pd.to_datetime(t, unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    return tt.dt.strftime("%Y-%m-%d"), tt.dt.hour * 60 + tt.dt.minute


def load_nifty():
    out = {}
    for f in sorted(glob.glob(os.path.join(B, "1m", "*.csv"))):
        d = pd.read_csv(f).drop_duplicates("time", keep="last").sort_values("time")
        _, m = ist_minutes(d.time)
        d = d.assign(m=m.to_numpy())
        d = d[(d.m >= S0) & (d.m < S1)].set_index("m")
        d = d[~d.index.duplicated(keep="last")]
        if len(d) > 300:
            out[os.path.basename(f)[:10]] = d
    return out


nifty = load_nifty()
vx = pd.read_csv(os.path.join(APP, "data", "research", "vix_1m.csv"))
vd, vm = ist_minutes(vx.time)
vx = vx.assign(day=vd.to_numpy(), m=vm.to_numpy())
vix = {k: g.set_index("m").close.sort_index() for k, g in vx.groupby("day")}


def tmins_to_expiry(day: str, a: int, expiry: str) -> float:
    d0, d1 = date.fromisoformat(day), date.fromisoformat(expiry)
    t = CLOSE - a
    d = d0 + timedelta(days=1)
    while d <= d1:
        if d.weekday() < 5:
            t += 375
        d += timedelta(days=1)
    return float(t)


def straddle(day: str, a: int, S: float):
    f = os.path.join(B, "options", day + ".csv")
    if not os.path.exists(f):
        return None
    o = pd.read_csv(f)
    _, m = ist_minutes(o.time)
    o = o.assign(m=m.to_numpy())
    o = o[(o.m <= a) & (o.m >= S0)]
    if o.empty:
        return None
    exp = sorted(o.expiry.unique())[0]
    o = o[o.expiry == exp]
    k = o.strike.unique()
    k = k[np.argmin(np.abs(k - S))]
    leg = o[o.strike == k].sort_values("m").groupby("right").close.last()
    if not {"CE", "PE"} <= set(leg.index):
        return None
    return float(leg.CE + leg.PE), exp


rows = []
for day, d in nifty.items():
    if not (S1 - 1) in d.index:
        continue
    c1515 = float(d.close.loc[S1 - 1])
    for an, a in ANCH.items():
        if a not in d.index:
            continue
        S = float(d.close.loc[a])
        rem = S1 - 1 - a
        fut = d.loc[a + 1:S1 - 1]
        hi, lo = float(fut.high.max()), float(fut.low.min())
        r = dict(day=day, anchor=an, S=S, ret=c1515 - S, up=hi - S, dn=S - lo)
        v = vix.get(day)
        if v is not None and len(v.loc[:a]):
            r["sig_VIX"] = float(v.loc[:a].iloc[-1]) / 100 / np.sqrt(252) * np.sqrt(rem / 375) * S
        st = straddle(day, a, S)
        if st:
            T = tmins_to_expiry(day, a, st[1])
            r["sig_STRAD"] = st[0] / 0.8 * np.sqrt(rem / T)
        rows.append(r)
R = pd.DataFrame(rows)
days = sorted(R.day.unique())


def evaluate(meth, sub, k=1.0):
    """k: float (one multiplier on z), dict {band: multiplier replacing z} (QCAL), or "ROLL" (per-day multipliers
    in columns roll_<band>: quantile of |ret|/sigma over the previous 20 days, causal)."""
    out = {}
    s = sub.dropna(subset=[f"sig_{meth}"])
    if isinstance(k, str):
        s = s.dropna(subset=[f"roll{meth}_{p}" for p in Z])
    for p, z in Z.items():
        mult = (k[p] if isinstance(k, dict) else s[f"roll{meth}_{p}"] if isinstance(k, str) else z * k)
        w = mult * s[f"sig_{meth}"]
        out[p] = pd.DataFrame({"day": s.day, "close": (s.ret.abs() <= w).astype(float),
                               "touch": ((s.up <= w) & (s.dn <= w)).astype(float), "width": 2 * w})
    return out


def bci(df, col):
    if df.empty:
        return np.nan, np.nan
    g = df.groupby("day")[col].mean()
    v = [g.sample(len(g), replace=True, random_state=RNG.integers(1e9)).mean() for _ in range(800)]
    return 100 * np.percentile(v, 5), 100 * np.percentile(v, 95)


lines = []
summary = []
for meth in ("VIX", "STRAD"):
    have = sorted(R.dropna(subset=[f"sig_{meth}"]).day.unique())
    if len(have) < 10:
        lines.append(f"{meth}: only {len(have)} days, skipped")
        continue
    half = have[len(have) // 2]
    lines.append(f"\n## {meth}: {len(have)} days ({have[0]} .. {have[-1]}), split at {half}")
    lines.append("| anchor | version | k | band | n H1/H2 | CLOSE in: all (90% CI) | H1 | H2 | TOUCH-free H2 | avg width pts | pass (H2 close within 6) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for an in ANCH:
        sub = R[(R.anchor == an)].dropna(subset=[f"sig_{meth}"])
        h1, h2 = sub[sub.day < half], sub[sub.day >= half]
        x = (h1.ret.abs() / h1[f"sig_{meth}"]).dropna()
        k = float(np.quantile(x, 0.68) / Z[68]) if len(x) >= 10 else np.nan
        q = {p: float(np.quantile(x, p / 100)) for p in Z} if len(x) >= 10 else None
        # rolling, causal: multiplier per band from the previous 20 days at this anchor (all days, then scored on H2)
        ss = sub.sort_values("day").copy()
        ratio = (ss.ret.abs() / ss[f"sig_{meth}"]).reset_index(drop=True)
        for p in Z:
            vals = [np.quantile(ratio[max(0, i - 20):i], p / 100) if i >= 20 else np.nan for i in range(len(ratio))]
            ss[f"roll{meth}_{p}"] = vals
        R.loc[ss.index, [f"roll{meth}_{p}" for p in Z]] = ss[[f"roll{meth}_{p}" for p in Z]].to_numpy()
        sub = R.loc[ss.index]
        h1, h2 = sub[sub.day < half], sub[sub.day >= half]
        for ver, kk in (("raw", 1.0), ("CAL", k), ("QCAL", q), ("ROLL20", "ROLL")):
            if kk is None or (isinstance(kk, float) and kk != kk):
                continue
            e_all, e1, e2 = evaluate(meth, sub, kk), evaluate(meth, h1, kk), evaluate(meth, h2, kk)
            oks = []
            for p in Z:
                a_, b_, c_ = e_all[p], e1[p], e2[p]
                lo, hi = bci(a_, "close")
                ok = abs(100 * c_.close.mean() - p) <= 6
                oks.append(ok)
                lines.append(f"| {an} | {ver} | {kk if isinstance(kk, str) else ('/'.join('%.2f' % v for v in kk.values()) if isinstance(kk, dict) else '%.2f' % kk)} | {p}% | {len(b_)}/{len(c_)} | {100 * a_.close.mean():.0f}% ({lo:.0f}-{hi:.0f}) "
                             f"| {100 * b_.close.mean():.0f}% | {100 * c_.close.mean():.0f}% | {100 * c_.touch.mean():.0f}% "
                             f"| {a_.width.mean():.0f} | {'yes' if ok else 'no'} |")
            summary.append((meth, an, ver, all(oks), len(c_)))
txt = "\n".join(lines)
print(txt)
print("\nSUMMARY (method, anchor, version, k, all three bands pass on H2, n H2):")
for s in summary:
    print(s)
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "em_table.md"), "w", encoding="utf-8").write(txt)
