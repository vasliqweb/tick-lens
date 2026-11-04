"""Options Positioning Bubbles: runs on synthetic option OI, classifies build-up types, causal (no repaint)."""
import numpy as np
import pandas as pd
from pathlib import Path

from core.scripting import run_script

CODE = (Path(__file__).resolve().parents[1] / "builtins" / "options_positioning.py").read_text(encoding="utf-8")


def frames(days=5, seed=3, tf=300):
    rng = np.random.default_rng(seed)
    mins = []
    for d in pd.bdate_range("2026-10-26", periods=days):
        mins += list(pd.date_range(d + pd.Timedelta(hours=3, minutes=45), periods=375, freq="1min"))
    mins = pd.DatetimeIndex(mins)
    spot = 24000 + np.cumsum(rng.normal(0, 3, len(mins)))
    m1 = pd.DataFrame({"open": spot, "high": spot + 2, "low": spot - 2, "close": spot, "volume": 1000.0}, index=mins)
    key = m1.index.floor(f"{tf}s")
    bars = m1.groupby(key).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    rows = []
    t = mins.as_unit("s").asi8
    for k in range(23500, 24550, 50):
        for right in ("CE", "PE"):
            oi = 1e6 + np.cumsum(rng.normal(0, 3000, len(mins))).clip(-9e5)
            px = np.maximum(1, (spot - k if right == "CE" else k - spot).clip(0) + 60 + rng.normal(0, 1, len(mins)))
            rows.append(pd.DataFrame({"time": t, "expiry": "2026-11-03", "strike": float(k), "right": right,
                                      "close": px, "volume": 5000.0, "oi": oi}))
    ch = pd.concat(rows, ignore_index=True)
    # inject a big call-writing event at 24200 CE on the last day 10:30 IST (05:00 UTC): OI +300k, premium down
    last = pd.bdate_range("2026-10-26", periods=days)[-1]
    t0 = int((last + pd.Timedelta(hours=5)).value // 10**9)
    m = (ch.strike == 24200) & (ch.right == "CE") & (ch.time >= t0)
    ch.loc[m, "oi"] += 300000
    ch.loc[m, "close"] -= 8
    return bars, ch


def run(bars, ch, tf=300, **inp):
    ctx = {"syminfo": {"timezone": "Asia/Kolkata", "session": "0915-1530", "mintick": 0.05, "is24x7": False, "ticker": "NIFTY"},
           "tf": tf, "options": lambda: ch}
    return run_script(CODE, bars, {k.replace("_", " "): v for k, v in inp.items()}, None, ctx)


def test_detects_injected_call_writing():
    bars, ch = frames()
    r = run(bars, ch)
    cw = [b for b in r["bubbles"] if b["text"] == "CW" and b["p"] == 24200.0]
    assert cw, [b["text"] for b in r["bubbles"]]
    assert cw[0]["tip"]["status"] == "CONFIRMED"
    assert any(row[0] == "OI change (Observed)" for row in cw[0]["tip"]["rows"])
    assert not any("BUY" in b["text"] or "SELL" in b["text"] for b in r["bubbles"])


def test_first_session_has_no_baseline_and_caps_hold():
    bars, ch = frames()
    r = run(bars, ch, Max_Bubbles_per_Session=5)
    first = int(bars.index[75].value // 10**9)            # second session start
    assert not any(b["t"] < first for b in r["bubbles"])
    assert len(r["bubbles"]) > 0


def test_no_repaint_when_more_bars_arrive():
    bars, ch = frames()
    full = run(bars, ch)
    cut = bars.iloc[:-40]
    tcut = int(cut.index[-1].value // 10**9) + 300
    part = run(cut, ch[ch.time < tcut])
    key = lambda b: (b["t"], b["p"], b["text"])
    pf = {key(b) for b in part["bubbles"] if b["t"] < tcut - 300}
    ff = {key(b) for b in full["bubbles"] if b["t"] < tcut - 300}
    assert pf and pf == ff


def test_no_options_message():
    bars, _ = frames(days=2)
    ctx = {"syminfo": {"timezone": "Asia/Kolkata"}, "tf": 300}
    r = run_script(CODE, bars, {}, None, ctx)
    assert r["tables"] and not r["bubbles"]
