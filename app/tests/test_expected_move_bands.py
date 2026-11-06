"""Expected Move Bands (beta): straddle bands fixed at 09:20, measured hit rates shown, no repaint, no-data note."""
import numpy as np
import pandas as pd
from pathlib import Path

from core.scripting import run_script

CODE = (Path(__file__).resolve().parents[1] / "builtins" / "expected_move_bands.py").read_text()
INFO = {"timezone": "Asia/Kolkata", "session": "0915-1530", "mintick": 0.05, "is24x7": False}


def frame(days=4, seed=5):
    rng = np.random.default_rng(seed)
    idx = []
    for d in pd.bdate_range("2026-10-26", periods=days):
        idx += list(pd.date_range(d + pd.Timedelta(hours=3, minutes=45), periods=75, freq="5min"))
    idx = pd.DatetimeIndex(idx)
    c = 24000 + np.cumsum(rng.normal(0, 10, len(idx)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + 3, "low": np.minimum(o, c) - 3, "close": c,
                         "volume": 1e5}, index=idx)


def chain(df):
    """ATM-ish CE/PE 1m closes for every minute of every day, expiry = next Thursday-like weekday (+3 bdays)."""
    rows = []
    for d in sorted(set(df.index.normalize())):
        exp = (d + pd.offsets.BDay(3)).strftime("%Y-%m-%d")
        for m in range(0, 30):
            t = int((d + pd.Timedelta(hours=3, minutes=45 + m)).value // 10**9)
            for k in (23900.0, 24000.0, 24100.0):
                rows += [dict(time=t, expiry=exp, strike=k, right="CE", close=150.0, volume=1, oi=1),
                         dict(time=t, expiry=exp, strike=k, right="PE", close=140.0, volume=1, oi=1)]
    return pd.DataFrame(rows)


def run(df, oc, **inp):
    return run_script(CODE, df, inp, None, {"syminfo": INFO, "tf": 300, **({"options": (lambda: oc)} if oc is not None else {})})


def test_no_option_data_shows_note():
    r = run(frame(), None)
    txt = " ".join(c["text"] for row in r["tables"][0]["rows"] for c in row)
    assert "no option-chain data" in txt and not r["boxes"] and not r["lines"]


def test_bands_fixed_at_anchor_with_measured_rates():
    df = frame()
    r = run(df, chain(df))
    assert len(r["boxes"]) == 4                                    # one 68% box per day
    b = r["boxes"][-1]
    # anchor = the 09:15 5m bar (ends 09:20); straddle 290, 2 more weekdays... sigma > 0 and band symmetric about S
    assert b["l"] == int(df.index[-75].value // 10**9) and b["top"] > b["bottom"]
    rows = dict(b["tip"]["rows"])
    assert "of 27 days" in rows["Tested (NIFTY)"] and "not yet reliable" in rows["Tested (NIFTY)"]
    txt = " ".join(c["text"] for row in r["tables"][0]["rows"] for c in row)
    assert "tested 18/27" in txt and "this chart" in txt
    assert len(r["lines"]) == 16                                    # 50% + 90% upper/lower per day


def test_no_repaint():
    df = frame()
    oc = chain(df)
    full = run(df, oc)
    key = lambda r, tc: sorted((b["l"], b["top"], b["bottom"]) for b in r["boxes"] if b["l"] <= tc)
    for k in (80, 151, 230, 299):
        part = run(df.iloc[:k], oc)
        tc = part["time"][k - 2]
        assert key(part, tc) == key(full, tc)
