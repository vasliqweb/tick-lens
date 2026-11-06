"""Breadth Trend Pro: NIFTY-only, breadth-gated colours, 2+2 zones, break warnings with tips, no repaint."""
import numpy as np
import pandas as pd
from pathlib import Path

from core.scripting import run_script

CODE = (Path(__file__).resolve().parents[1] / "builtins" / "breadth_trend_pro.py").read_text()
INFO = {"timezone": "Asia/Kolkata", "session": "0915-1530", "mintick": 0.05, "is24x7": False}


def frame(days=6, seed=7):
    rng = np.random.default_rng(seed)
    idx = []
    for d in pd.bdate_range("2026-10-26", periods=days):
        idx += list(pd.date_range(d + pd.Timedelta(hours=3, minutes=45), periods=75, freq="5min"))
    idx = pd.DatetimeIndex(idx)
    drift = np.repeat(rng.choice([-3.0, 3.0], days), 75)                    # trending days -> strong scores
    c = 24000 + np.cumsum(rng.normal(0, 8, len(idx)) + drift)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0, 6, len(idx))
    l = np.minimum(o, c) - rng.uniform(0, 6, len(idx))
    v = rng.lognormal(10, 0.5, len(idx))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def breadth_of(df, seed=3):
    """1m breadth: share of stocks above open, leaning with the index's move since the open (plus noise)."""
    rng = np.random.default_rng(seed)
    m = pd.date_range(df.index[0], df.index[-1] + pd.Timedelta(minutes=4), freq="1min")
    c = df.close.reindex(m, method="ffill")
    day = m.normalize()
    op = df.open.groupby(df.index.normalize()).transform("first").reindex(m, method="ffill")
    adv = np.clip(0.5 + (c - op).to_numpy() / 120 + rng.normal(0, 0.08, len(m)), 0, 1)
    return pd.DataFrame({"adv_open": adv, "above_vwap": adv, "n": 50.0}, index=m).loc[pd.Series(day, index=m).index]


def ctx(df, with_breadth=True, tf=300):
    b = breadth_of(df)
    return {"syminfo": INFO, "tf": tf, **({"breadth": (lambda: b)} if with_breadth else {})}


def test_needs_nifty_breadth():
    df = frame()
    r = run_script(CODE, df, {}, None, ctx(df, with_breadth=False))
    txt = " ".join(c["text"] for row in r["tables"][0]["rows"] for c in row)
    assert "NIFTY" in txt and not r["boxes"] and not r["barcolors"]


def test_colours_zones_tips_no_signals():
    df = frame()
    r = run_script(CODE, df, {"Zone History (sessions)": 10}, None, ctx(df))
    cols = set(x[0] for x in r["barcolors"] if x)
    assert cols and cols <= {"#089981", "#f23645", "#787b86", "#e91e63"}            # strong / disagree / break only
    t0 = r["time"][-75]
    assert len(set(b["l"] for b in r["boxes"])) > 1                                 # zone history shows earlier days
    today = [b for b in r["boxes"] if b["l"] >= t0]
    assert sorted(b["text"].split()[0] for b in today if b["l"] == t0) == ["R", "R", "S", "S"]
    assert all(b["tip"]["notes"] and dict(b["tip"]["rows"])["Lifecycle"] for b in today)
    assert r["bubbles"] and all("Invalidation" in " ".join(b["tip"]["notes"]) for b in r["bubbles"])
    assert not any("BUY" in m.get("text", "") or "SELL" in m.get("text", "") for m in r["markers"])
    rows = {row[0]["text"]: row[1]["text"] for row in r["tables"][0]["rows"] if len(row) > 1}
    assert "Tested (97 NIFTY days)" in rows


def test_no_repaint_closed_bars():
    df = frame()
    C = ctx(df)
    H = {"Zone History (sessions)": 10}
    full = run_script(CODE, df, H, None, C)
    for k in (200, 301, 377, 420):
        part = run_script(CODE, df.iloc[:k], H, None, C)
        assert part["barcolors"][: k - 1] == full["barcolors"][: k - 1]
        tc = part["time"][k - 2]
        bp = sorted((b["t"], b["p"]) for b in part["bubbles"] if b["t"] <= tc)
        bf = sorted((b["t"], b["p"]) for b in full["bubbles"] if b["t"] <= tc)
        assert bp == bf
        zp = sorted((b["l"], b["text"], b["top"], b["bottom"]) for b in part["boxes"] if b["l"] <= tc)
        zf = sorted((b["l"], b["text"], b["top"], b["bottom"]) for b in full["boxes"] if b["l"] <= tc)
        assert zp == zf


def test_deterministic():
    df = frame()
    assert run_script(CODE, df, {}, None, ctx(df)) == run_script(CODE, df, {}, None, ctx(df))
