indicator("Expected Move Bands (beta)", overlay=True, precision=2)
# FREE · BETA. Where today's 15:15 close may land, from the options market (ATM straddle), fixed at 09:20 IST.
#   S        = chart close at the anchor (first bar ending at or after 09:20 IST)
#   straddle = nearest-expiry ATM CE + PE (strike nearest S), last 1m close at or before the anchor
#   sigma    = straddle / 0.8 * sqrt(minutes left to 15:15 / trading minutes left to expiry 15:30)   (normal approx)
#   bands    = S +- z * sigma, z = 0.674 (50%), 0.994 (68%), 1.645 (90%)
# Measured, not theoretical: on 27 NIFTY days (Sep 25 - Nov 4 2026) the 15:15 close finished inside the
# 50 / 68 / 90% bands on 52 / 67 / 89% of days (scripts/research/expected_move/EM_RESULTS.md). 27 days is a
# small sample: treat as beta. The bands are about the CLOSE; price crosses the 68% band intraday on most days.
# Causal: computed once from data <= the anchor, never moved later. Not a trade signal.
ALGO = "emb-0.1.0 (straddle @09:20)"
show_50 = input("Show 50% Band", True)
show_90 = input("Show 90% Band", True)
days_back = input("History (sessions)", 5, min=1, max=60, tooltip="How many past days keep their bands (and count in this chart's own record).")
show_table = input("Show Table", True)
col = input("Band Colour", "#7e57c2")

Z = {50: 0.674, 68: 0.994, 90: 1.645}
TESTED = {50: (14, 27), 68: (18, 27), 90: (24, 27)}          # days the 15:15 close was inside / test days (NIFTY)
ANCHOR, TARGET, END = 5, 359, 375                            # minutes after 09:15: 09:20 anchor, 15:14 last counted minute, 15:30


def rgba(hx, a):
    hx = hx.lstrip("#")
    return f"rgba({int(hx[0:2], 16)},{int(hx[2:4], 16)},{int(hx[4:6], 16)},{a})"


def main():
    n = len(df)
    if n < 2 or timeframe >= 3600:
        table([["Expected Move Bands (beta)"], ["Needs an intraday chart below 1h"]], position="bottom_right")
        return
    oc = options_chain()
    sd = session_day.to_numpy()
    sm = session_minute.to_numpy()
    c = close.to_numpy(float)
    tfm = max(1, int(timeframe // 60))
    starts = np.flatnonzero(np.r_[True, sd[1:] != sd[:-1]])
    ends = np.r_[starts[1:], n]
    mt = float(syminfo.mintick or 0.01)
    fp = lambda x: f"{x:,.{max(0, min(4, -int(math.floor(math.log10(mt)))))}f}"
    if oc is not None and len(oc):
        ot = oc.time.to_numpy(np.int64) + 19800
        oc = oc.assign(day=pd.to_datetime(ot // 86400 * 86400, unit="s"), m=(ot % 86400) // 60 - 555)
    made, rec = 0, {p: [0, 0] for p in Z}
    first = max(0, len(starts) - days_back)
    for g in range(first, len(starts)):
        s, e = starts[g], ends[g]
        a_idx = [i for i in range(s, e) if sm[i] + tfm >= ANCHOR]
        if not a_idx or oc is None or not len(oc):
            continue
        a = a_idx[0]
        if a == n - 1:                                       # anchor bar still forming: wait for its close
            continue
        a_min = sm[a] + tfm - 1                              # last 1m minute inside the anchor bar
        S = c[a]
        day = pd.Timestamp(sd[s])
        od = oc[(oc.day == day) & (oc.m <= a_min) & (oc.m >= 0)]
        if not len(od):
            continue
        exps = sorted(x for x in od.expiry.unique() if str(x) >= str(day.date()))
        if not exps:
            continue
        exp = exps[0]
        od = od[od.expiry == exp]
        ks = od.strike.unique()
        k = float(ks[np.argmin(np.abs(ks - S))])
        leg = od[od.strike == k].sort_values("m").groupby("right").close.last()
        if not ("CE" in leg.index and "PE" in leg.index):
            continue
        strad = float(leg["CE"] + leg["PE"])
        days_more = int(np.busday_count(np.datetime64(day.date()) + 1, np.datetime64(str(exp)[:10]) + 1))
        T = (END - a_min) + 375 * days_more
        rem = TARGET - a_min
        if rem <= 0 or T <= 0 or strad <= 0:
            continue
        sig = strad / 0.8 * math.sqrt(rem / T)
        made += 1
        last_bar = e - 1
        done = sm[last_bar] >= TARGET                       # the session reached 15:15: score the bands
        close_t = None
        if done:
            j = [i for i in range(s, e) if sm[i] <= TARGET][-1]
            if j < n - 1:
                close_t = c[j]
        right = None if (g == len(starts) - 1 and not done) else last_bar
        for p, z in Z.items():
            if (p == 50 and not show_50) or (p == 90 and not show_90):
                continue
            up, dn = S + z * sig, S - z * sig
            held = None if close_t is None else (dn <= close_t <= up)
            if held is not None:
                rec[p][0] += 1; rec[p][1] += bool(held)
            ins, tot = TESTED[p]
            tip = {"title": f"{p}% expected-move band (beta)", "status": "CONFIRMED (fixed at the anchor)",
                   "rows": [["Band", f"{fp(dn)} – {fp(up)} (±{z * sig:,.1f})"], ["Anchor", f"{fp(S)} at the bar ending ~09:20 IST"],
                            ["ATM straddle", f"{fp(strad)} (strike {k:g}, expiry {str(exp)[:10]})"],
                            ["Minutes left today / to expiry", f"{rem} / {T}"],
                            ["Tested (NIFTY)", f"close inside on {ins} of {tot} days ({100 * ins / tot:.0f}%) - small sample, not yet reliable"]]
                           + ([["Today", "15:15 close inside" if held else "15:15 close outside"]] if held is not None else []),
                   "notes": ["Rule: straddle/0.8 x sqrt(minutes left today / minutes to expiry), normal z for the band.",
                             "About the 15:15 CLOSE: price usually crosses the inner bands during the day.",
                             "Evidence: Derived from option prices (Observed). Not a forecast of direction, not a trade signal."],
                   "version": ALGO}
            sty = "dotted" if p == 90 else "dashed"
            if p == 68:
                box(a, right, up, dn, bgcolor=rgba(col, 0.05), border_color=rgba(col, 0.75), border_style="dashed",
                    text=f"68% ±{z * sig:,.0f}", text_color=rgba(col, 0.9), extend=right is None, tip=tip)
            else:
                line(a, up, right, up, color=rgba(col, 0.6), width=1, style=sty, extend=right is None)
                line(a, dn, right, dn, color=rgba(col, 0.6), width=1, style=sty, extend=right is None)
    if show_table:
        rows_t = [[{"text": "Expected Move Bands (beta, free)", "bold": True}, {"text": ALGO}]]
        if oc is None or not len(oc):
            rows_t.append(["Bands", "no option-chain data for this chart (index options on Breeze only)"])
        elif not made:
            rows_t.append(["Bands", "no 09:20 straddle in the shown days yet"])
        for p in Z:
            ins, tot = TESTED[p]
            mine = f" · this chart {rec[p][1]}/{rec[p][0]}" if rec[p][0] else ""
            rows_t.append([f"{p}% band, close inside", f"tested {ins}/{tot} days ({100 * ins / tot:.0f}%){mine}"])
        rows_t.append(["Note", "27 test days only: not yet reliable. About the 15:15 close, not the range."])
        table(rows_t, position="bottom_right")


main()
