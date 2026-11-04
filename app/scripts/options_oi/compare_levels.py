"""Compare Options Positioning Bubbles levels with Intraday Move Bias (+Beta) zones on the user's cached data.
Run from the app folder:  python compare.py <app_dir> [INDEX] [TF_SECONDS]
Reads data/Breeze/<INDEX>/1m (index candles) and data/Breeze/<INDEX>/options (options OI). No network."""
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

APP = Path(sys.argv[1]).resolve()
INDEX = sys.argv[2] if len(sys.argv) > 2 else "NIFTY"
TF = int(sys.argv[3]) if len(sys.argv) > 3 else 300
sys.path.insert(0, str(APP))
from core.scripting import run_script
from core import options_oi as oo
from core.breeze import session_only
from core.breadth import breadth_1m
oo.ROOT = APP / "data" / "Breeze"

days = oo.coverage(INDEX)
assert days, "no options files"
files = sorted((APP / "data" / "Breeze" / INDEX / "1m").glob("*.csv"))
first = pd.Timestamp(days[0]) - pd.Timedelta(days=12)          # a few sessions before for IMB profiles / baselines
m1 = pd.concat([pd.read_csv(f) for f in files if pd.Timestamp(f.stem) >= first and f.stem <= days[-1]])
m1 = m1.drop_duplicates("time").sort_values("time")
m1.index = pd.to_datetime(m1.time, unit="s")
m1 = session_only(m1[["open", "high", "low", "close", "volume"]].astype(float))
ist = m1.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
m1 = m1[(ist.hour * 60 + ist.minute) < 915]                    # index: cut 15:15 (flat zero-volume auction bars)
key = m1.index.floor(f"{TF}s")
bars = m1.groupby(key).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
ch = oo.chain_1m(INDEX, bars.index[0], bars.index[-1] + pd.Timedelta(seconds=TF))
info = {"timezone": "Asia/Kolkata", "session": "0915-1530", "mintick": 0.05, "is24x7": False, "ticker": INDEX, "now": None}
ctx = {"syminfo": info, "tf": TF, "lower_tf": lambda tf: m1 if tf == 60 else None, "options": lambda: ch,
       "breadth": lambda: breadth_1m(INDEX, bars.index[0], bars.index[-1] + pd.Timedelta(seconds=TF))}
code = lambda n: (APP / "builtins" / n).read_text(encoding="utf-8")
opb = run_script(code("options_positioning.py"), bars, {"Bubble History (sessions)": 100, "Max Bubbles per Session": 60}, None, ctx)
imb = run_script(code("intraday_move_bias.py"), bars, {}, None, ctx)
beta = run_script(code("intraday_move_bias_beta.py"), bars, {}, None, ctx)

bt = bars.index.as_unit("s").asi8
pos = {t: i for i, t in enumerate(bt)}
c = bars.close.to_numpy()
sday = bars.index.tz_localize("UTC").tz_convert("Asia/Kolkata").normalize()
last_of_day = pd.Series(np.arange(len(bt)), index=sday).groupby(level=0).max()
opt_days = set(days)


def zones(res):
    out = []
    for b in res["boxes"]:
        if b.get("top") is None:
            continue
        l = pos.get(b["l"])
        r = len(bt) - 1 if (b["extend"] or b["r"] is None) else pos.get(b["r"], len(bt) - 1)
        if l is None:
            continue
        rows = dict(b.get("tip", {}).get("rows", []))
        out.append({"l": l, "r": r, "top": b["top"], "bot": b["bottom"], "text": b["text"], "life": rows.get("Lifecycle", "")})
    return out


Z = {"IMB": zones(imb), "Beta": zones(beta)}
step = oo.step_of(INDEX)
ev = [b for b in opb["bubbles"] if b["t"] in pos]
clu = [b for b in opb["boxes"]]
tol = step / 2


def inside(z, i, p, t=tol):
    return any(zz["l"] <= i <= zz["r"] and zz["bot"] - t <= p <= zz["top"] + t for zz in z)


rep = {"index": INDEX, "tf": TF, "option_days": len(days), "bars": len(bt), "events": {}, "zones": {}}
for name, z in Z.items():
    rows = {}
    for code_ in ("CW", "PW", "CC", "PC", "CB", "PB", "CU", "PU", "ALL"):
        es = [e for e in ev if code_ == "ALL" or e["text"] == code_]
        if not es:
            continue
        hit = np.mean([inside(z, pos[e["t"]], e["p"]) for e in es])
        # baseline: every active strike (+-5 steps) at the same bars
        base = []
        for e in es:
            i = pos[e["t"]]
            atm = round(c[i] / step) * step
            base += [inside(z, i, atm + k * step) for k in range(-5, 6)]
        rows[code_] = {"n": len(es), "in_zone": round(float(hit), 3), "random_strike": round(float(np.mean(base)), 3)}
    rep["events"][name] = rows
    # zones with option writing at them in the zone's first W bars vs without; only zones still alive after W
    # (fixes survival bias: long-lived zones collect more events). Outcome = accepted through later.
    W = 6
    conf, unconf = [], []
    for zz in z:
        if str(sday[zz["l"]].date()) not in opt_days or zz["r"] <= zz["l"] + W:
            continue
        side = "R" if zz["text"].startswith("R") else "S"
        want = "CW" if side == "R" else "PW"
        ok = any(e["text"] == want and zz["l"] <= pos[e["t"]] <= zz["l"] + W and zz["bot"] - tol <= e["p"] <= zz["top"] + tol for e in ev)
        broke = "ACCEPTED" in zz["life"].upper()
        (conf if ok else unconf).append(broke)
    rep["zones"][name] = {"with_writing_first_30min": {"n": len(conf), "accepted_through": round(float(np.mean(conf)), 3) if conf else None},
                          "without": {"n": len(unconf), "accepted_through": round(float(np.mean(unconf)), 3) if unconf else None}}

# writing levels: held to session end vs random strikes at the same distance from price
held, base = [], []
for e in ev:
    if e["text"] not in ("CW", "PW"):
        continue
    i = pos[e["t"]]
    e_ = last_of_day[sday[i]]
    if e_ <= i + 2:
        continue
    d = e["p"] - c[i]
    fut = c[i + 1:e_ + 1]
    def brk(level, up):
        x = (fut > level + tol) if up else (fut < level - tol)
        return bool(np.any(x[1:] & x[:-1]))
    up = e["text"] == "CW"
    if (e["p"] > c[i]) != up:          # ITM writing (strike already on the wrong side) is not a level test
        continue
    held.append(not brk(e["p"], up))
    atm = round(c[i] / step) * step
    for k in range(-6, 7):
        lv = atm + k * step
        if (lv - c[i] > 0) == up and lv != e["p"] and abs(abs(lv - c[i]) - abs(d)) <= step:
            base.append(not brk(lv, up))
rep["writing_levels_held"] = {"n": len(held), "held": round(float(np.mean(held)), 3) if held else None,
                              "same_distance_random_strike": round(float(np.mean(base)), 3) if base else None}
rep["clusters"] = len(clu)
from collections import Counter
rep["event_counts"] = dict(Counter(e["text"] for e in ev))
print(json.dumps(rep, indent=1))
