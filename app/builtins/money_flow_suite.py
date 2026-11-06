indicator("Money Flow Suite", overlay=False, precision=1)
# PREMIUM (beta). Rupee money flow: value bought minus value sold, in Rs crore.
#  - Breeze NIFTY / NIFTY FUT: sum of the NIFTY 50 stocks' flow. Breeze stock: its own flow.
#  - Minutes with raw ticks: side from bid/ask (quote rule, then tick rule) = Observed + classified.
#  - Other minutes / other sources: candle close-location estimate (CMF-style) = Estimated.
# Causal: a bar sums only its own minutes; thresholds use prior sessions only. The forming bar is PROVISIONAL.
# Context, not a signal: no BUY/SELL. Tested result is shown in the table.
ALGO = "mfs-0.1.0 (flow mf-0.1.0)"
display = input("Display", "Session cumulative", options=["Session cumulative", "Per bar"], tooltip="Session cumulative: each column is the total net flow since today's open; its colour is this bar's own flow (green in, red out). Per bar: each column is only this bar's net flow.")
win_min = input("Strong Flow Window (min)", 30, min=5, max=120, tooltip="Minutes summed for the 'strong flow' check (default 30).")
pct = input("Strong Flow Percentile", 80.0, min=50.0, max=99.0, step=1.0, tooltip="The last-N-minute flow is 'strong' when it is bigger than this percentile of the previous 5 sessions' values (80 = top 20%). Tested on 97 NIFTY days: strong 30-min flow was right about the next 60 minutes ~55% of the time in both halves of the data (small edge).")
show_table = input("Show Table", True, tooltip="Source, session net flow, last-window flow, stocks with inflow, tested result.")
c_in = input("Inflow Color", "#089981")
c_out = input("Outflow Color", "#f23645")

CR = 1e7


def rgba(hx, a):
    hx = hx.lstrip("#")
    return f"rgba({int(hx[0:2], 16)},{int(hx[2:4], 16)},{int(hx[4:6], 16)},{a})"


def main():
    n = len(df)
    if n < 2:
        return
    mf = money_flow()
    est_only = mf is None or mf.buy.notna().sum() == 0
    if est_only:                                    # any source: candle estimate from the chart's own bars
        h, l, c = high, low, close
        rng = (h - l).replace(0, np.nan)
        clv = (((c - l) - (h - c)) / rng).fillna(0)
        val = volume.fillna(0).clip(lower=0) * (h + l + c) / 3
        buy, sell = val * (1 + clv) / 2, val * (1 - clv) / 2
        tick = pd.Series(0.0, index=df.index)
        pos = pd.Series(np.nan, index=df.index)
        if float(volume.fillna(0).sum()) <= 0:
            table([["Money Flow Suite"], ["No volume on this chart: money flow needs traded volume."],
                   ["Tip: use Breeze NIFTY (sum of the 50 stocks) or a stock."]], position="top_left")
            return
    else:
        buy, sell = mf.buy, mf.sell
        tick, pos = mf.tick_share.fillna(0), mf.pos_share
    net = (buy - sell) / CR
    sd = session_day
    cum = net.fillna(0).groupby(sd.values).cumsum()
    cum[net.isna()] = np.nan
    has = net.notna()
    # strong window flow: threshold from the previous 5 sessions only (causal)
    k = max(1, int(round(win_min * 60 / max(timeframe, 60)))) if timeframe < 86400 else 1
    fw = net.fillna(0).groupby(sd.values).transform(lambda x: x.rolling(k, min_periods=1).sum())
    fw[~has] = np.nan
    days = pd.Series(sd.values).drop_duplicates().tolist()
    thr = pd.Series(np.nan, index=df.index)
    absf = fw.abs()
    for i, d in enumerate(days):
        if i < 5:
            continue
        prev = absf[(sd >= days[i - 5]) & (sd < d)].dropna()
        if len(prev) >= 20:
            thr[sd == d] = float(np.percentile(prev, pct))
    strong = (absf >= thr) & thr.notna()
    # colours: solid = mostly tick-classified (Observed), faded = estimated; brighter when strong window flow
    a = np.where(tick >= 0.5, 0.85, 0.45) + np.where(strong, 0.15, 0.0)
    col = [None if not hz else rgba(c_in if x >= 0 else c_out, round(min(ai, 1.0), 2))
           for x, ai, hz in zip(net.fillna(0), a, has)]
    if display == "Per bar":
        plot(net, "Net Flow (Rs cr)", style="histogram", color=col)
    else:
        plot(cum, "Session Net Flow (Rs cr)", style="histogram", color=col)
    hline(0, "", "#787b86", "dotted")
    if not show_table:
        return
    j = int(np.flatnonzero(has.to_numpy())[-1]) if has.any() else n - 1
    today = sd == sd.iloc[j]
    b_t, s_t = float(buy[today].sum()) / CR, float(sell[today].sum()) / CR
    ts = float(tick[today].mul((buy + sell)[today]).sum() / max((buy + sell)[today].sum(), 1))
    if ts > 0:
        tk_today = np.flatnonzero((today & (tick > 0)).to_numpy())
        mi = (int(df.index[tk_today[0]].value // 60_000_000_000) + 330) % 1440 if len(tk_today) else 0   # IST minute of day
        since = "%02d:%02d" % (mi // 60, mi % 60)
        pct_t = ("%.1f" % (ts * 100)) if ts < 0.1 else ("%d" % round(ts * 100))
        pct_c = ("%.1f" % (100 - ts * 100)) if ts < 0.1 else ("%d" % (100 - round(ts * 100)))
        src = "Ticks bid/ask %s%% (from %s IST) | candle estimate %s%%" % (pct_t, since, pct_c)
    else:
        src = "Candle estimate (no ticks)"
    lvl = "Observed (classified)" if ts >= 0.5 else "Estimated"
    fwj = fw.iloc[j]
    st = "STRONG " + ("INFLOW" if fwj > 0 else "OUTFLOW") if bool(strong.iloc[j]) else "normal"
    def sg(x):
        return ("+" if x >= 0 else "-") + ("%.1f" % abs(x))
    rows = [[{"text": "Money Flow Suite", "bold": True}, {"text": ALGO}],
            ["Source", src], ["Evidence", lvl],
            ["Session net (Rs cr)", {"text": sg(b_t - s_t), "color": c_in if b_t >= s_t else c_out, "bold": True}],
            ["Bought / sold (Rs cr)", "%.0f / %.0f" % (b_t, s_t)],
            ["Last %d min (Rs cr)" % win_min, {"text": "%s  %s" % (sg(fwj) if fwj == fwj else "-", st),
                                                "color": (c_in if fwj > 0 else c_out) if bool(strong.iloc[j]) else None}]]
    pj = pos.iloc[j] if len(pos) else np.nan
    if pj == pj:
        rows.append(["Stocks with net inflow", "%d%%" % round(pj * 100)])
    rows.append(["Tested (NIFTY 97d)", "strong 30-min flow: ~55% right 60 min later; session flow alone ~51%"])
    rows.append(["Status", "last bar PROVISIONAL" if j == n - 1 else "closed bars"])
    table(rows, position="top_left")


main()
