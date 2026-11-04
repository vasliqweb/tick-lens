"""Intraday Move Bias: runs, 2+2 zones from the previous session, causal (no repaint of closed bars)."""
import numpy as np
import pandas as pd
from pathlib import Path

from core.scripting import run_script

CODE = (Path(__file__).resolve().parents[1] / "builtins" / "intraday_move_bias.py").read_text()
CTX = {"syminfo": {"timezone": "Asia/Kolkata", "session": "0915-1530", "mintick": 0.05, "is24x7": False}, "tf": 300}


def frame(days=6, seed=7):
    rng = np.random.default_rng(seed)
    idx = []
    for d in pd.bdate_range("2026-10-26", periods=days):
        idx += list(pd.date_range(d + pd.Timedelta(hours=3, minutes=45), periods=75, freq="5min"))
    idx = pd.DatetimeIndex(idx)
    c = 24000 + np.cumsum(rng.normal(0, 8, len(idx)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0, 6, len(idx))
    l = np.minimum(o, c) - rng.uniform(0, 6, len(idx))
    v = rng.lognormal(10, 0.5, len(idx))
    v[rng.integers(0, len(idx), 25)] *= 5
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def last_open(df):
    loc = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata").normalize()
    return int(df.index[loc == loc[-1]][0].value // 10**9)


def open_zones(r, df):
    t0 = last_open(df)
    return sorted(b["text"].split()[0] for b in r["boxes"] if b["l"] == t0)


def run(df, **inp):
    return run_script(CODE, df, {k.replace("_", " "): v for k, v in inp.items()}, None, CTX)


def test_zones_two_each_side_and_tooltips():
    df = frame()
    r = run(df)
    today = [b for b in r["boxes"] if b["l"] >= last_open(df)]
    assert open_zones(r, df) == ["R", "R", "S", "S"]
    # a zone accepted through ends at its break bar and the next level on that side starts after it
    for b in today:
        if dict(b["tip"]["rows"])["Lifecycle"] == "ACCEPTED THROUGH":
            assert b["r"] is not None and not b["extend"]
    assert all("tip" in b and b["tip"]["rows"] for b in today)
    assert not any("BUY" in m["text"] or "SELL" in m["text"] for m in r["markers"])


def test_bubbles_only_on_important_bars():
    df = frame()
    r = run(df)
    assert 0 < len(r["bubbles"]) < len(df) * 0.2
    assert all(b["tip"]["rows"][2][1].endswith("x)") for b in r["bubbles"])
    days = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata").normalize()
    per = pd.Series([days[df.index.as_unit("s").asi8.tolist().index(b["t"])] for b in r["bubbles"]]).value_counts()
    assert per.max() <= 8


def test_no_repaint_closed_bars():
    df = frame()
    H = {"Bubble History (sessions)": 60, "Zone History (sessions)": 20}
    full = run_script(CODE, df, H, None, CTX)
    for k in (200, 301, 377, 420):
        part = run_script(CODE, df.iloc[:k], H, None, CTX)
        # bar colours of closed bars (all but the forming one) are identical
        assert part["barcolors"][: k - 1] == full["barcolors"][: k - 1]
        # bubbles on closed bars are identical
        tb = {b["t"]: (b["r"], b["p"]) for b in part["bubbles"] if b["t"] < part["time"][k - 1]}
        tf = {b["t"]: (b["r"], b["p"]) for b in full["bubbles"] if b["t"] < part["time"][k - 1]}
        assert tb == tf
        # zone levels for the session in progress were fixed at its open
        # zones that were known by the cut (start <= last closed bar) have the same levels
        tc = part["time"][k - 2]
        zp = sorted((b["l"], b["text"], b["top"], b["bottom"]) for b in part["boxes"] if b["l"] <= tc)
        zf = sorted((b["l"], b["text"], b["top"], b["bottom"]) for b in full["boxes"] if b["l"] <= tc)
        assert zp == zf


def test_two_levels_each_side_even_after_gap():
    ok = 0
    for seed in range(12):
        df = frame(days=8, seed=seed)
        names = open_zones(run(df), df)
        ok += names == ["R", "R", "S", "S"]
        assert names.count("R") <= 2 and names.count("S") <= 2
    assert ok == 12          # projected zones fill a side when price is beyond 5 sessions of levels


def test_deterministic_and_no_volume():
    df = frame()
    assert run(df) == run(df)
    df["volume"] = 0.0
    r = run(df)
    assert r["bubbles"] == [] and r["boxes"]
