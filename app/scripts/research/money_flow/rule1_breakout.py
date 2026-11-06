"""Rule 1 study: does money flow improve NIFTY level breakouts?  (research only, causal)

Levels, all known before the session opens (from the previous session's 1m bars, 09:15-15:15 IST):
  PDH / PDL  previous day high / low
  VAH / VAL  previous day 70% value area (5-point bins, volume at typical price)
Event: first 1m close beyond a level (up: close > L and previous close <= L; down mirrored), 09:45-14:15 IST,
       at most one event per level per day. Entry = that 1m close.
Flow at the event minute (data <= that minute only), same method as the indicator's history (candle estimate):
  f30   = net flow of the 50 stocks over the last 30 minutes (Rs cr)
  STRONG = |f30| >= 80th percentile of |f30| over the previous 5 sessions (no look-ahead)
  breadth = share of stocks whose session net flow so far is > 0
Groups: all breakouts (baseline) | STRONG flow in the breakout direction | + breadth >= 60% (<= 40% for down)
        | flow AGAINST the breakout.
Outcome: NIFTY move in the breakout direction after 15/30/60 min (points), hit = move > 0,
         net = move - COST points (round-trip cost/slippage assumption for a NIFTY futures trade).
Split: first half vs second half of days (out-of-sample check).
Run: python rule1_breakout.py <app_dir>
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

APP = sys.argv[1] if len(sys.argv) > 1 else "."
sys.path.insert(0, APP)
from core.breeze import NIFTY50_FALLBACK as MEM  # noqa: E402

B = os.path.join(APP, "data", "Breeze")
S0, S1 = 555, 915
COST = 2.0                   # points per round trip (brokerage + STT + slippage on NIFTY futures, rough)
HOR = (15, 30, 60)


def rd(sym, day):
    f = os.path.join(B, sym, "1m", day + ".csv")
    if not os.path.exists(f):
        return None
    d = pd.read_csv(f).drop_duplicates("time", keep="last").sort_values("time")
    t = pd.to_datetime(d.time, unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    m = t.dt.hour * 60 + t.dt.minute
    d = d[(m >= S0) & (m < S1)].copy()
    d["m"] = m[d.index]
    d = d.set_index("m")
    d = d[~d.index.duplicated(keep="last")]
    return d if len(d) > 200 else None


def value_area(d, step=5.0, pct=0.70):
    tp = ((d.high + d.low + d.close) / 3).to_numpy()
    v = d.volume.fillna(0).to_numpy()
    if v.sum() <= 0:
        v = np.ones_like(tp)
    lo = np.floor(tp.min() / step) * step
    k = ((tp - lo) // step).astype(int)
    hist = np.bincount(k, weights=v)
    poc = int(hist.argmax())
    a, b, tot = poc, poc, hist[poc]
    while tot < pct * hist.sum():
        up = hist[b + 1] if b + 1 < len(hist) else -1
        dn = hist[a - 1] if a - 1 >= 0 else -1
        if up >= dn:
            b += 1
            tot += up
        else:
            a -= 1
            tot += dn
    return lo + a * step, lo + (b + 1) * step


days = sorted(os.path.basename(f)[:10] for f in glob.glob(os.path.join(B, "NIFTY", "1m", "*.csv")))
idx_bars = {d: rd("NIFTY", d) for d in days}
days = [d for d in days if idx_bars[d] is not None]

flow = {}                                           # day -> (F per minute Rs cr, breadth per minute)
for day in days:
    fl = []
    for s in MEM:
        d = rd(s, day)
        if d is None:
            continue
        rng = (d.high - d.low).replace(0, np.nan)
        clv = (((d.close - d.low) - (d.high - d.close)) / rng).fillna(0)
        tp = (d.high + d.low + d.close) / 3
        fl.append((clv * tp * d.volume.fillna(0)).reindex(range(S0, S1)).fillna(0))
    if len(fl) >= 40:
        F = sum(fl) / 1e7
        br = sum((f.cumsum() > 0).astype(float) for f in fl) / len(fl)
        flow[day] = (F, br)

events = []
for i, day in enumerate(days):
    if i == 0 or day not in flow:
        continue
    prev = idx_bars[days[i - 1]]
    val, vah = value_area(prev)
    levels = {"PDH": prev.high.max(), "PDL": prev.low.min(), "VAH": vah, "VAL": val}
    F, br = flow[day]
    f30 = F.rolling(30, min_periods=1).sum()
    # causal STRONG threshold: |f30| over the previous 5 sessions' minutes
    past = [flow[d][0].rolling(30, min_periods=1).sum().abs() for d in days[max(0, i - 5):i] if d in flow]
    if len(past) < 5:
        continue
    thr = float(np.percentile(pd.concat(past).to_numpy(), 80))
    c = idx_bars[day].close.reindex(range(S0, S1)).ffill()
    for name, L in levels.items():
        for side in (1, -1):
            done = False
            for m in range(S0 + 30, 856):          # 09:45 .. 14:15
                if done:
                    break
                a, b = c.get(m - 1), c.get(m)
                if a != a or b != b:
                    continue
                if (side == 1 and b > L >= a) or (side == -1 and b < L <= a):
                    done = True
                    ev = dict(day=day, level=name, side=side, m=m, entry=b, f30=f30[m], thr=thr, breadth=br[m])
                    for h in HOR:
                        x = c.get(m + h)
                        ev[f"mv{h}"] = (x - b) * side if x == x else np.nan
                    events.append(ev)

E = pd.DataFrame(events)
if E.empty:
    print("no events")
    sys.exit(0)
E["strong_with"] = (E.f30.abs() >= E.thr) & (np.sign(E.f30) == E.side)
E["against"] = np.sign(E.f30) == -E.side
E["breadth_ok"] = np.where(E.side == 1, E.breadth >= 0.6, E.breadth <= 0.4)
ud = sorted(E.day.unique())
half = ud[len(ud) // 2]
print(f"days with flow: {len(flow)}  test days: {len(ud)}  ({ud[0]} .. {ud[-1]}), split at {half}")
print(f"cost assumption: {COST} points per round trip\n")


def row(name, k):
    out = [f"{name:44s}"]
    for lab, h in (("all", E.day >= ""), ("H1", E.day < half), ("H2", E.day >= half)):
        s = E[k & h]
        if lab == "all":
            out.append(f"n={len(s):4d}")
        for hz in HOR:
            mv = s[f"mv{hz}"].dropna()
            if lab == "all":
                if len(mv):
                    se = 1.96 * np.sqrt(0.25 / len(mv))
                    out.append(f"{hz}m hit {100 * (mv > 0).mean():5.1f}% (+-{100 * se:4.1f}) avg {mv.mean():+6.1f} net {mv.mean() - COST:+6.1f}")
                else:
                    out.append(f"{hz}m -")
            elif hz == 60:
                out.append(f"{lab} n={len(mv):3d} hit60 {100 * (mv > 0).mean():5.1f}% avg60 {mv.mean():+6.1f}" if len(mv) else f"{lab} -")
    print(" | ".join(out))


all_ = pd.Series(True, index=E.index)
groups = [("ALL breakouts (baseline)", all_),
          ("STRONG flow WITH breakout", E.strong_with),
          ("STRONG with + breadth >=60% (<=40% down)", E.strong_with & E.breadth_ok),
          ("flow AGAINST breakout", E.against),
          ("not strong-with", ~E.strong_with)]
for nm, k in groups:
    row(nm, k)
print()
for lv in ("PDH", "PDL", "VAH", "VAL"):
    row(f"{lv}: all", E.level == lv)
    row(f"{lv}: STRONG with + breadth", (E.level == lv) & E.strong_with & E.breadth_ok)
print()
for sd, nm in ((1, "UP"), (-1, "DOWN")):
    row(f"{nm}: all", E.side == sd)
    row(f"{nm}: STRONG with + breadth", (E.side == sd) & E.strong_with & E.breadth_ok)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rule1_events.csv")
E.to_csv(out, index=False)
print("\nevents written to", out)
