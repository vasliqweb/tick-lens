"""Money flow engine (core/money_flow.py) + Money Flow Suite builtin: classification, volume, no repaint."""
from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd
from core import money_flow as mf
from core.scripting import run_script

DAY = date(2026, 11, 4)
T0 = int(pd.Timestamp("2026-11-04 09:20", tz="Asia/Kolkata").timestamp())


def _ticks(tmp: Path):
    # (sec offset, last, ttq, bid, ask): buy at ask, sell at bid, mid -> tick rule, stale lower ttq, crossed book
    rows = [(0, 100.0, 1000, 99.9, 100.0),
            (1, 100.0, 1100, 99.9, 100.0),      # +100 at prev ask 100.0 -> buy 10,000
            (1, 100.0, 1100, 99.9, 100.0),      # duplicate row -> 0
            (2, 99.9, 1150, 99.8, 100.0),       # +50 at prev bid 99.9 -> sell 4,995
            (3, 99.95, 1050, 99.8, 100.0),      # stale snapshot (ttq back) -> 0, never re-counted
            (4, 99.95, 1170, 99.9, 100.0),      # +20 inside spread, down-tick vs 99.9? up-tick -> buy 1,999
            (65, 100.0, 1270, 100.1, 100.0)]    # crossed book, +100 -> tick rule up -> buy
    p = tmp / "TEST" / "ticks"
    p.mkdir(parents=True)
    pd.DataFrame([dict(time=T0 + s, last=l, ltq=1, ttq=q, bid=b, bid_qty=1, ask=a, ask_qty=1, avg=l, oi="")
                  for s, l, q, b, a in rows]).to_csv(p / f"{DAY}.csv", index=False)
    return p / f"{DAY}.csv"


def test_tick_classification(tmp_path):
    g = mf.tick_flow(_ticks(tmp_path))
    m0 = T0 // 60 * 60
    assert np.isclose(g.loc[m0, "buy"], 100 * 100.0 + 20 * 99.95)
    assert np.isclose(g.loc[m0, "sell"], 50 * 99.9)
    total = (g.buy + g.sell).sum()
    assert np.isclose(total, 100 * 100 + 50 * 99.9 + 20 * 99.95 + 100 * 100)     # = ttq increase x price, no double count


def test_auction_cut(tmp_path):
    p = tmp_path / "X" / "ticks"
    p.mkdir(parents=True)
    t = int(pd.Timestamp("2026-11-04 15:20", tz="Asia/Kolkata").timestamp())
    pd.DataFrame([dict(time=t, last=1, ttq=10, bid=1, ask=1), dict(time=t + 1, last=1, ttq=10**6, bid=2, ask=1)]
                 ).to_csv(p / f"{DAY}.csv", index=False)
    assert mf.tick_flow(p / f"{DAY}.csv") is None                                  # closing auction not counted


def _bars(n=400, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-10-20 03:45", periods=n * 8, freq="5min")
    ist = idx + pd.Timedelta(hours=5, minutes=30)
    m = ist.hour * 60 + ist.minute
    idx = idx[(m >= 555) & (m < 915) & (ist.dayofweek < 5)][:n]
    c = 100 + rng.normal(0, .3, len(idx)).cumsum()
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + .1, "low": np.minimum(o, c) - .1, "close": c,
                         "volume": rng.integers(1000, 5000, len(idx)).astype(float)}, index=idx)


def test_suite_no_repaint():
    code = (Path(__file__).resolve().parent.parent / "builtins" / "money_flow_suite.py").read_text()
    df = _bars()
    full = run_script(code, df, {}, None, {"syminfo": {}, "tf": 300})
    v = full["plots"][0]["values"]
    for cut in (120, 250, 333):
        part = run_script(code, df.iloc[:cut], {}, None, {"syminfo": {}, "tf": 300})
        pv = part["plots"][0]["values"]
        assert pv[:-1] == v[:cut - 1]
        assert part["plots"][0]["colors"][:-1] == full["plots"][0]["colors"][:cut - 1]
    rows = [[c["text"] for c in r] for r in full["tables"][0]["rows"]]
    assert any(r[0] == "Evidence" and r[1] == "Estimated" for r in rows)            # candle estimate is labelled
