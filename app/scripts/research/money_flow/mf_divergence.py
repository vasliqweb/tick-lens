"""Money-flow divergence study (NIFTY, research only, causal).

Flow: per-stock candle close-location estimate (same as mf_study.py / the indicator's history), summed over the
NIFTY 50 stocks; cum = session cumulative net flow (Rs cr) at bar close; breadth = share of stocks whose session
net flow is > 0. Features use 09:15-15:15 data up to the bar close only. Outcomes use NIFTY 1m closes up to 15:29.

Events on NIFTY 3m and 5m bars whose close is 10:00-14:30 IST:
  NEW HIGH  bar close > every earlier close today.   (NEW LOW mirrored)
  ref bar   the highest close made >= 30 min earlier (lowest for lows)
  DIV-A     cum < cum at the ref bar          (price higher high, flow lower high)
  DIV-B     cum <= session max cum - 20% of |max cum|  (lows: cum >= min + 20% of |min|)
  DIV-BR    breadth < breadth at the ref bar  (lows: >)
  CONFIRMED new high without DIV-A (baseline a);  ALL BARS (baseline b, unconditional)
Cooldown: one event per group per side per 30 minutes.
Prediction: divergence at a high -> down, at a low -> up. All groups are scored in the REVERSAL direction, so the
CONFIRMED rows read "how often a confirmed extreme reversed" (100 - that = continued).
Outcomes: sign of the move after 30 / 60 min; barrier = 1 ATR(14 bars) in the reversal direction touched before
1 ATR the other way within 60 min (1m high/low; same-minute or no touch = unresolved, excluded);
avg points at 60 min in the reversal direction, net of COST.
Stats: hit %, 90% bootstrap CI over days, first-half / second-half days.
Run: python mf_divergence.py <app_dir>
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
S0, S1, OUT_END = 555, 915, 930
COST = 2.0
COOL = 30
RNG = np.random.default_rng(7)


def rd(sym, day, end=S1):
    f = os.path.join(B, sym, "1m", day + ".csv")
    if not os.path.exists(f):
        return None
    d = pd.read_csv(f).drop_duplicates("time", keep="last").sort_values("time")
    t = pd.to_datetime(d.time, unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    m = t.dt.hour * 60 + t.dt.minute
    d = d[(m >= S0) & (m < end)].copy()
    d["m"] = m[d.index]
    d = d.set_index("m")
    d = d[~d.index.duplicated(keep="last")]
    return d if len(d) > 200 else None


days = sorted(os.path.basename(f)[:10] for f in glob.glob(os.path.join(B, "NIFTY", "1m", "*.csv")))
data = {}
for day in days:
    nx = rd("NIFTY", day, OUT_END)
    if nx is None:
        continue
    fl = []
    for s in MEM:
        d = rd(s, day)
        if d is None:
            continue
        rng = (d.high - d.low).replace(0, np.nan)
        clv = (((d.close - d.low) - (d.high - d.close)) / rng).fillna(0)
        tp = (d.high + d.low + d.close) / 3
        fl.append((clv * tp * d.volume.fillna(0)).reindex(range(S0, S1)).fillna(0))
    if len(fl) < 40:
        continue
    cumF = (sum(fl) / 1e7).cumsum()
    br = sum((f.cumsum() > 0).astype(float) for f in fl) / len(fl)
    data[day] = (nx.reindex(range(S0, OUT_END)).ffill(), cumF, br)
days = sorted(data)
half = days[len(days) // 2]


def study(tf):
    rows, all_rows = [], []
    prev_bars = None                                  # ATR carries over from the previous day
    for day in days:
        nx, cumF, br = data[day]
        sess = nx.loc[S0:S1 - 1]
        g = (sess.index - S0) // tf
        bars = pd.DataFrame({"high": sess.high.groupby(g).max(), "low": sess.low.groupby(g).min(),
                             "close": sess.close.groupby(g).last()})
        bars["end"] = S0 + (bars.index + 1) * tf        # bar close time (exclusive minute)
        bars = bars[bars.end <= S1]
        pc = bars.close.shift(1)
        tr = pd.concat([bars.high - bars.low, (bars.high - pc).abs(), (bars.low - pc).abs()], axis=1).max(axis=1)
        if prev_bars is not None:
            tr_all = pd.concat([prev_bars, tr.reset_index(drop=True)], ignore_index=True)
            atr = tr_all.rolling(14, min_periods=5).mean().iloc[len(prev_bars):].to_numpy()
        else:
            atr = tr.rolling(14, min_periods=5).mean().to_numpy()
        prev_bars = tr.reset_index(drop=True).iloc[-14:]
        cl = bars.close.to_numpy()
        ends = bars.end.to_numpy()
        cum = np.array([cumF[e - 1] for e in ends])
        bra = np.array([br[e - 1] for e in ends])
        last = {}
        for k in range(1, len(bars)):
            e = ends[k]
            if e < 600 or e > 870:
                continue
            entry = cl[k]
            path = nx.loc[e:min(e + 59, OUT_END - 1)]
            out = {}
            for h in (30, 60):
                x = nx.close.get(e - 1 + h, np.nan)
                out[h] = x - entry
            base = dict(day=day, e=e, entry=entry, atr=atr[k], up30=out[30], up60=out[60], path=path)
            all_rows.append(base)
            for side in (1, -1):                       # 1 = new high, -1 = new low
                prior = cl[:k]
                if not ((side == 1 and entry > prior.max()) or (side == -1 and entry < prior.min())):
                    continue
                old = ends[:k] <= e - 30
                if not old.any():
                    continue
                ref = np.flatnonzero(old)[np.argmax(prior[old] * side)]
                mx = cum[:k + 1].max() if side == 1 else cum[:k + 1].min()
                flags = {
                    "DIV-A": (cum[k] - cum[ref]) * side < 0,
                    "DIV-B": (side == 1 and cum[k] <= mx - 0.2 * abs(mx)) or (side == -1 and cum[k] >= mx + 0.2 * abs(mx)),
                    "DIV-BR": (bra[k] - bra[ref]) * side < 0,
                }
                flags["CONFIRMED"] = not flags["DIV-A"]
                for grp, on in flags.items():
                    if not on or e - last.get((grp, side), -999) < COOL:
                        continue
                    last[(grp, side)] = e
                    rows.append(dict(base, grp=grp, side=side))
    return pd.DataFrame(rows), pd.DataFrame(all_rows)


def score(df, rev):
    """rev = +1 for 'price goes down' scoring at highs (reversal), -1 at lows. Returns per-event metrics."""
    m30 = -df.up30 * rev
    m60 = -df.up60 * rev
    bar = []
    for _, r in df.iterrows():
        a = r.atr
        if not a == a or a <= 0:
            bar.append(np.nan)
            continue
        res = np.nan
        for _, p in r.path.iterrows():
            dn = p.low <= r.entry - a
            upx = p.high >= r.entry + a
            good, bad = (dn, upx) if rev == 1 else (upx, dn)
            if good and bad:
                break
            if good:
                res = 1.0
                break
            if bad:
                res = 0.0
                break
        bar.append(res)
    return pd.DataFrame({"day": df.day.to_numpy(), "h30": (m30 > 0).astype(float).where(m30 != 0),
                         "h60": (m60 > 0).astype(float).where(m60 != 0), "pts60": m60.to_numpy(), "bar": bar})


def ci(s, col):
    s = s.dropna(subset=[col])
    if s.empty:
        return np.nan, np.nan
    dd = s.groupby("day")[col].agg(["sum", "count"])
    u = dd.index.to_numpy()
    vals = []
    for _ in range(1000):
        pick = dd.loc[RNG.choice(u, len(u))]
        vals.append(pick["sum"].sum() / pick["count"].sum())
    return np.percentile(vals, 5) * 100, np.percentile(vals, 95) * 100


def line(name, s):
    if s.empty:
        return f"| {name} | 0 | | | | | | |"
    h1, h2 = s[s.day < half], s[s.day >= half]
    lo, hi = ci(s, "h60")
    return (f"| {name} | {len(s)} | {s.day.nunique()} | {100 * s.h30.mean():.0f}% | {100 * s.h60.mean():.0f}% ({lo:.0f}-{hi:.0f}) "
            f"| {100 * h1.h60.mean():.0f}% / {100 * h2.h60.mean():.0f}% (n {len(h1)}/{len(h2)}) "
            f"| {100 * s.bar.mean():.0f}% (n {s.bar.notna().sum()}) | {s.pts60.mean() - COST:+.1f} |")


out = [f"Days: {len(days)} ({days[0]} .. {days[-1]}), split at {half}. Cost {COST} pts. "
       "Hit = move in the REVERSAL direction (down after a high, up after a low).", ""]
head = ("| Group | n | days | 30m hit | 60m hit (90% CI) | 60m hit H1 / H2 | 1-ATR barrier reversal first | avg 60m pts net |\n"
        "|---|---|---|---|---|---|---|---|")
for tf in (3, 5):
    ev, allb = study(tf * 1)
    for side, nm, rev in ((1, "HIGHS (bearish divergence -> down)", 1), (-1, "LOWS (bullish divergence -> up)", -1)):
        out += [f"### {tf}m bars, {nm}", head]
        out.append(line("ALL BARS (baseline b)", score(allb, rev)))
        for grp in ("CONFIRMED", "DIV-A", "DIV-B", "DIV-BR"):
            sub = ev[(ev.grp == grp) & (ev.side == side)] if not ev.empty else ev
            out.append(line(grp + (" (baseline a)" if grp == "CONFIRMED" else ""), score(sub, rev) if len(sub) else pd.DataFrame()))
        out.append("")
txt = "\n".join(out)
print(txt)
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "divergence_table.md"), "w", encoding="utf-8").write(txt)
