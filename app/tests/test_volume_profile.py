"""Volume profile engine: math, value area, determinism, no look-ahead, provisional/confirmed."""
import numpy as np
import pandas as pd

from core import volume_profile as vp
from core.scripting import run_script


def bars(rows, start="2026-10-26 03:45", freq="1min"):
    idx = pd.date_range(start, periods=len(rows), freq=freq)
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def test_overlap_distribution_and_totals():
    b = bars([[10, 12, 10, 12, 100], [12, 12, 11, 11, 50]])
    p = vp.build(b, "Number of Rows", 2, 70, 0.01)
    assert p["n"] == 2 and p["base"] == 10 and p["step"] == 1
    assert np.allclose(p["up"], [50, 50]) and np.allclose(p["dn"], [0, 50])
    assert abs(p["total"] - 150) < 1e-6
    assert p["poc"] == 1 and abs(p["pocPrice"] - 11.5) < 1e-9


def test_value_area_tradingview_rule():
    # POC 50 of 100; target 70 -> 20 left. Next above 10 vs below 30: below is larger but would exceed -> stop.
    tot = np.array([1, 2, 30, 50, 10, 1, 6], float)
    assert vp.value_area(tot, 70) == (3, 3, 3)
    # smooth profile: single-row steps, larger side first
    tot = np.array([2, 5, 8, 12, 20, 11, 9, 4, 3], float)   # total 74, target 51.8, POC 20 -> 31.8 left
    poc, lo, hi = vp.value_area(tot, 70)
    assert poc == 4 and (lo, hi) == (3, 5)                     # 12 below, 11 above, then 9 > 8.8 left -> stop
    # equal volumes -> row closer to POC; equal distance -> above
    assert vp.value_area(np.array([5, 10, 40, 10, 5], float), 80) == (2, 2, 3)


def test_up_down_doji_is_up():
    b = bars([[10, 11, 9, 10, 100]])
    p = vp.build(b, "Number of Rows", 2, 70, 0.01)
    assert sum(p["up"]) == 100 and sum(p["dn"]) == 0


def test_ticks_per_row_grid():
    b = bars([[100.0, 100.5, 99.5, 100.2, 10]])
    p = vp.build(b, "Ticks Per Row", 10, 70, 0.05)
    assert abs(p["step"] - 0.5) < 1e-9 and p["base"] == 99.5 and p["n"] == 2


def test_zero_volume_is_bar_count_not_fabricated():
    b = bars([[10, 11, 10, 11, 0], [11, 12, 11, 12, 0]])
    p = vp.build(b, "Number of Rows", 4, 70, 0.01)
    assert p["volumeMode"] == "bar-count" and p["total"] == 0
    assert any("TIME AT PRICE" in x for x in vp.limitations(p, "chart", 60, None))


def _sim(days=3, per=60, seed=1):
    rng = np.random.default_rng(seed)
    idx = []
    for d in range(days):
        idx += list(pd.date_range(f"2026-10-{26 + d} 03:45", periods=per, freq="5min"))
    c = 100 + np.cumsum(rng.normal(0, 0.3, len(idx)))
    o = np.r_[100, c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.1, "low": np.minimum(o, c) - 0.1, "close": c,
                         "volume": rng.integers(100, 1000, len(idx)).astype(float)}, index=pd.DatetimeIndex(idx))


INFO = {"timezone": "Asia/Kolkata", "session": "0915-1515", "mintick": 0.05}


def test_sessions_status_and_non_repainting():
    df = _sim()
    full = vp.session_profiles(df, None, INFO, 300)["profiles"]
    assert [p["status"] for p in full] == ["CONFIRMED", "CONFIRMED", "PROVISIONAL"]
    # replay: cut in the middle of day 3 - confirmed days must be identical, day 3 provisional
    cut = vp.session_profiles(df.iloc[:150], None, INFO, 300)["profiles"]
    for a, b in zip(full[:2], cut[:2]):
        assert {k: a[k] for k in ("up", "dn", "poc", "vah", "val", "knownAt")} == {k: b[k] for k in ("up", "dn", "poc", "vah", "val", "knownAt")}
    assert cut[2]["status"] == "PROVISIONAL"
    # determinism
    again = vp.session_profiles(df, None, INFO, 300)["profiles"]
    assert again == full


def test_developing_poc_is_causal():
    df = _sim()
    r = vp.session_profiles(df, None, INFO, 300, dev=True)
    r2 = vp.session_profiles(df.iloc[:100], None, INFO, 300, dev=True)
    assert np.allclose(r["devPoc"][:100], r2["devPoc"], equal_nan=True)
    # last developing value of a closed session equals its final POC
    assert abs(r["devPoc"][59] - r["profiles"][0]["pocPrice"]) < 1e-9


def test_intrabars_used_and_labelled():
    df = _sim(days=1, per=12)
    ib = df.resample("1min").ffill().iloc[:-1]                     # fake 1m intrabars covering the session
    ib = ib.assign(volume=ib["volume"] / 5)
    p = vp.session_profiles(df, ib, INFO, 300)["profiles"][0]
    assert p["res"] == "1m intrabars"
    p2 = vp.session_profiles(df, None, INFO, 300)["profiles"][0]
    assert p2["res"] == "chart" and any("chart bars" in x for x in p2["limitations"])


def test_builtin_script_runs():
    code = open("builtins/session_volume_profile.py").read()
    df = _sim()
    res = run_script(code, df, {"Show Developing POC": True}, ctx={"syminfo": INFO, "tf": 300})
    assert len(res["profiles"]) == 3 and res["profiles"][0]["style"]["placement"] == "Left"
    assert res["plots"][0]["title"] == "Developing POC"


def test_range_profile_status():
    df = _sim(days=1)
    last = int(df.index[-1].value // 10**9)
    a = vp.range_profile(df.iloc[:10], int(df.index[0].value // 10**9), int(df.index[9].value // 10**9), 300, last,
                         "Number of Rows", 24, 70, 0.05, "chart", None)
    b = vp.range_profile(df, int(df.index[0].value // 10**9), last, 300, last, "Number of Rows", 24, 70, 0.05, "chart", None)
    assert a["status"] == "CONFIRMED" and b["status"] == "PROVISIONAL"


def test_finished_session_is_confirmed():
    df = _sim()                                              # 03:45..08:40 UTC = 09:15..14:10 IST
    info = {**INFO, "is24x7": False}
    p = vp.session_profiles(df, None, info, 300)["profiles"]
    assert p[-1]["status"] == "PROVISIONAL"                  # last bar before 15:15 IST, no clock
    end = pd.Timestamp("2026-10-28 09:45").value // 10**9    # 15:15 IST on the last day
    p = vp.session_profiles(df, None, {**info, "now": end + 1}, 300)["profiles"]
    assert p[-1]["status"] == "CONFIRMED"


def test_lower_timeframe_choice():
    df = _sim(days=1, per=12)                                       # 5m chart, 1 session
    ib = df.resample("1min").ffill().iloc[:-1]
    _, res = vp._pick_bars(df, ib, df.index[0], df.index[-1] + pd.Timedelta(minutes=5), 300, "auto")
    assert res == "1m intrabars"
    # 6000 x 1m bars in range -> 5m (first with < 5000 bars) == chart tf -> chart bars
    idx = pd.date_range("2026-10-01", periods=6000, freq="1min")
    big = pd.DataFrame({"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1.0}, index=idx)
    chart15 = vp.resample(big, 15, idx[0])
    _, res = vp._pick_bars(chart15, big, idx[0], idx[-1], 900, "auto")
    assert res == "5m intrabars"
    _, res = vp._pick_bars(chart15, big, idx[0], idx[-1], 900, "periodic")
    assert res == "1m intrabars"


def test_periodic_keys_and_year_restart():
    idx = pd.DatetimeIndex(pd.to_datetime(["2025-12-30 04:00", "2025-12-31 04:00", "2026-01-01 04:00", "2026-01-02 04:00", "2026-01-05 04:00"]))
    k = vp.period_keys(idx, "Asia/Kolkata", 2, "Day")
    assert k[0] == k[1] and k[1] != k[2] and k[2] == k[3] and k[3] != k[4]


def test_auto_anchor_rules():
    df = _sim(days=3)
    i, used = vp.anchor_index(df, INFO, 300, "Auto", 20)
    assert used == "Session" and i == 120
    i, used = vp.anchor_index(df, INFO, 300, "Highest High", 20)
    assert i >= len(df) - 20 and df["high"].iloc[i] == df["high"].iloc[-20:].max()
    r = vp.auto_anchored(df, None, INFO, 300, "Auto", 20, dev=True)
    assert len(r["profiles"]) == 1 and r["profiles"][0]["status"] == "PROVISIONAL"
    assert np.isnan(r["devPoc"][119]) and not np.isnan(r["devPoc"][-1])


def test_extend_ends_first_crossing_bar():
    df = _sim(days=2)
    p = vp.session_profiles(df, None, INFO, 300)["profiles"][0]
    t = p["ends"]["pocPrice"]
    if t is not None:
        row = df.loc[pd.Timestamp(t, unit="s")]
        assert row["low"] <= p["pocPrice"] <= row["high"] and t > p["r"]


def test_hd_fine_rows():
    df = _sim(days=1)
    p = vp.session_profiles(df, None, INFO, 300, hd=True, kind="svphd")["profiles"][0]
    assert abs(p["step"] - 0.05) < 1e-9 or p["n"] == vp.MAX_ROWS


def test_all_volume_profile_builtins_run():
    import glob
    df = _sim()
    for f in glob.glob("builtins/*volume_profile*.py"):
        res = run_script(open(f).read(), df, {"Show Developing POC": True}, ctx={"syminfo": INFO, "tf": 300})
        assert res["profiles"] or res["vpspecs"], f
