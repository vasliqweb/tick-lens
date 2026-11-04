indicator("Options Positioning Bubbles", overlay=True, precision=2)
# Where did option positions change? Bubbles at the STRIKE (price level) of the nearest-expiry index options
# whose open interest changed unusually in a bar, classified by OI change + premium change:
#   OI up + premium down = short build-up (writing)      OI up + premium up = long build-up (buying)
#   OI down + premium up = short covering                 OI down + premium down = long unwinding
# Clusters = a strike with repeated events in one session. Wall shifts = the max-OI call / put strike moved.
# Causal: a bar uses option minutes inside that bar and earlier only; thresholds come from PRIOR sessions.
# The forming bar is PROVISIONAL. No BUY/SELL: these are positioning facts + an interpretation, not signals.
ALGO = "opb-0.1.0"
width = input("Active Strikes Each Side", 5, min=1, max=15, tooltip="Only strikes this many steps above/below the price at that bar count (NIFTY step 50, BANKNIFTY/SENSEX 100). Near-the-money, nearest-expiry options carry most of the real activity.")
pct = input("Event Percentile (prior sessions)", 97.0, min=80.0, max=99.9, step=0.5, tooltip="A bubble needs an OI change bigger than this percentile of all active-strike OI changes in the previous sessions (same timeframe). 97 = top 3%. Raise for fewer bubbles.")
min_str = input("Min Strength", 1.0, min=0.5, max=10.0, step=0.1, tooltip="OI change divided by that threshold. 1 = just at the threshold, 2 = twice as big.")
base_days = input("Baseline Sessions", 3, min=1, max=10, tooltip="How many previous sessions set the 'normal' OI change size. The first session(s) with no stored history get no bubbles.")
bub_max = input("Max Bubbles per Session", 12, min=1, max=60, tooltip="Limit per day. After the limit only an event bigger than every earlier one that day is still shown (decided as it happens, never repainted).")
per_bar = input("Max Bubbles per Bar", 2, min=1, max=6, tooltip="Only the biggest events of a bar are drawn.")
bub_days = input("Bubble History (sessions)", 10, min=1, max=100, tooltip="How many past days show bubbles, clusters and wall shifts.")
show_buy = input("Show Buying / Unwinding", True, tooltip="Also show long build-up (option buying) and long unwinding. Off = only writing and covering (option sellers), which usually matter more for index levels.")
show_clu = input("Show Repeat-Level Clusters", True, tooltip="Thin band at a strike where events repeated in the same session (the market keeps building/closing positions there).")
clu_min = input("Cluster Min Events", 3, min=2, max=10, tooltip="Events at the same strike in one session needed to draw a cluster band.")
show_wall = input("Show Wall Shifts", True, tooltip="Small tag when the strike with the most call OI (call wall) or put OI (put wall) changes and holds for 2 bars.")
show_table = input("Show Table", True, tooltip="Top-right summary: expiry, call/put wall, PCR, today's events, data freshness.")

LIM = ["OI change shows that positions opened/closed, not who traded or why; the build-up type is inferred from the premium direction, which also moves with the index and implied volatility.",
       "Not bid/ask aggressor data: 'writing' vs 'buying' is an interpretation of 1m OI + premium.",
       "Breeze 1m OI may update in steps; only strikes downloaded for the day are seen."]
KIND = {("CE", "SB"): ("CW", "Call writing", "BEARISH", "possible resistance", "rgba(242,54,69,0.60)"),
        ("PE", "SB"): ("PW", "Put writing", "BULLISH", "possible support", "rgba(8,153,129,0.60)"),
        ("CE", "SC"): ("CC", "Call short covering", "BULLISH", "call writers exiting", "rgba(76,175,80,0.40)"),
        ("PE", "SC"): ("PC", "Put short covering", "BEARISH", "put writers exiting", "rgba(255,152,0,0.45)"),
        ("CE", "LB"): ("CB", "Call buying (long build-up)", "BULLISH", "upside bets added", "rgba(41,98,255,0.40)"),
        ("PE", "LB"): ("PB", "Put buying (long build-up)", "BEARISH", "downside bets added", "rgba(156,39,176,0.40)"),
        ("CE", "LU"): ("CU", "Call long unwinding", "BEARISH", "weak: call buyers exiting", "rgba(120,123,134,0.40)"),
        ("PE", "LU"): ("PU", "Put long unwinding", "BULLISH", "weak: put buyers exiting", "rgba(120,123,134,0.40)")}


def fmt(x):
    x = float(x)
    a = abs(x)
    s = f"{a / 1e7:.2f}Cr" if a >= 1e7 else f"{a / 1e5:.2f}L" if a >= 1e5 else f"{a:,.0f}"
    return ("-" if x < 0 else "+") + s


def main():
    n = len(df)
    sym = str(syminfo.ticker or "")
    ch = options_chain()
    if ch is None or n < 5 or timeframe >= 86400:
        if show_table:
            table([["Options Positioning"], ["No options OI for this chart."],
                   ["Needs a Breeze intraday chart of NIFTY / BANKNIFTY /"], ["FINNIFTY / MIDCPNIFTY / SENSEX (or its FUT)"],
                   ["History: run scripts\\options_oi\\fetch_options_oi.bat"]], position="top_right")
        return
    tf = int(timeframe)
    bt = df.index.as_unit("s").asi8
    c = close.to_numpy()
    sd = session_day.to_numpy().astype("datetime64[D]").astype("int64")      # session = IST day number
    lt = local_time
    hhmm = [f"{x.hour:02d}:{x.minute:02d}" for x in lt]
    now = syminfo.now
    forming = now is not None and now < bt[-1] + tf

    t = ch.time.to_numpy()
    bi = np.searchsorted(bt, t, side="right") - 1
    ok = (bi >= 0) & (t < bt[np.clip(bi, 0, None)] + tf)
    ch = ch[ok].copy()
    if not len(ch):
        if show_table:
            table([["Options Positioning"], ["Options data does not cover these bars."]], position="top_right")
        return
    ch["bar"] = bi[ok]
    ks = np.unique(ch.strike.to_numpy())
    step = float(np.median(np.diff(ks))) if len(ks) > 1 else 50.0
    g = ch.groupby(["strike", "right", "bar"], sort=True)
    a = pd.DataFrame({"close": g["close"].last(), "oi": g["oi"].last(), "vol": g["volume"].sum(),
                      "exp": g["expiry"].last()}).reset_index()
    a["sess"] = sd[a.bar.to_numpy()]
    a = a.sort_values(["strike", "right", "bar"]).reset_index(drop=True)
    a["oi"] = a.groupby(["strike", "right", "sess"])["oi"].ffill()
    gp = a.groupby(["strike", "right"])
    same = (gp["sess"].shift(1) == a.sess) & (gp["exp"].shift(1) == a.exp)
    a["doi"] = np.where(same, a.oi - gp["oi"].shift(1), np.nan)
    a["dpx"] = np.where(same, a.close - gp["close"].shift(1), np.nan)
    a["poi"] = np.where(same, gp["oi"].shift(1), np.nan)
    a["spot"] = c[a.bar.to_numpy()]
    a["active"] = (a.strike - a.spot).abs() <= width * step + step / 2

    sess_list = sorted(set(sd.tolist()))
    have = sorted(set(a.sess.tolist()))
    show_from = sess_list[max(0, len(sess_list) - bub_days)]
    act = a[a.active & a.doi.notna()]
    by_sess = {s: np.abs(x.doi.to_numpy()) for s, x in act.groupby("sess")}
    thr = {}
    for j, s in enumerate(have):
        prev = [by_sess[p] for p in have[max(0, j - base_days):j] if p in by_sess]
        base = np.concatenate(prev) if prev else np.array([])
        base = base[base > 0]
        if len(base) >= 50:
            thr[s] = float(np.percentile(base, pct))

    ev = act[act.sess.isin(list(thr)) & (act.sess >= show_from)].copy()
    ev["thr"] = ev.sess.map(thr)
    ev["str"] = ev.doi.abs() / ev.thr
    ev = ev[(ev["str"] >= min_str) & (ev.dpx != 0) & ev.dpx.notna()]
    ev["typ"] = np.where(ev.doi > 0, np.where(ev.dpx < 0, "SB", "LB"), np.where(ev.dpx > 0, "SC", "LU"))
    if not show_buy:
        ev = ev[ev.typ.isin(["SB", "SC"])]
    ev = ev.sort_values(["bar", "str"], ascending=[True, False])

    # ---- causal selection: per bar top `per_bar`; per session `bub_max`, then only new records
    kept, cnt, best, nb = [], {}, {}, {}
    for r in ev.itertuples(index=False):
        s, b = r.sess, int(r.bar)
        if nb.get(b, 0) >= per_bar:
            continue
        k = cnt.get(s, 0)
        if k >= bub_max and r.str <= best.get(s, 0):
            continue
        kept.append(r)
        cnt[s] = k + 1
        nb[b] = nb.get(b, 0) + 1
        best[s] = max(best.get(s, 0), r.str)

    sess_end = {}
    for i in range(n):
        sess_end[sd[i]] = i
    today_s = sd[-1]
    clusters = {}
    for r in kept:
        b = int(r.bar)
        code, name, direc, meaning, col = KIND[(r.right, r.typ)]
        prov = forming and b == n - 1
        # lifecycle (writing only): price accepted through the strike (2 closes beyond by half a step) later that day
        life = "n/a"
        if r.typ == "SB" and ((r.strike <= r.spot) if r.right == "CE" else (r.strike >= r.spot)):
            life = "ITM at event (strike already on the other side of price): not a level"
        elif r.typ == "SB":
            e = sess_end[r.sess]
            beyond = (c[b + 1:e + 1] > r.strike + step / 2) if r.right == "CE" else (c[b + 1:e + 1] < r.strike - step / 2)
            run, at = 0, None
            for j, x in enumerate(beyond):
                run = run + 1 if x else 0
                if run >= 2:
                    at = b + 1 + j
                    break
            life = f"BROKEN: 2 closes beyond at {hhmm[at]}" if at is not None else ("HELD so far" if r.sess == today_s else "HELD to session end")
        size = max(5.0, min(16.0, 6.0 + 4.0 * math.log2(max(1.0, r.str))))
        pchg = (r.doi / r.poi * 100) if r.poi and r.poi == r.poi else float("nan")
        tip = {"title": f"{name} · {r.strike:g} {r.right} ({meaning})",
               "status": "PROVISIONAL" if prov else "CONFIRMED",
               "rows": [["OI change (Observed)", fmt(r.doi) + (f" ({pchg:+.1f}%)" if pchg == pchg else "")],
                        ["Premium change (Observed)", f"{r.dpx:+.2f} → {r.close:.2f}"],
                        ["Option volume in bar (Observed)", f"{r.vol:,.0f}"],
                        ["Strength (Derived)", f"{r.str:.1f}x the {pct:g}th pct ({fmt(r.thr)[1:]}) of prior {base_days} sessions"],
                        ["Interpretation", f"{name} → {direc.lower()} lean ({meaning})"],
                        ["Expiry / step", f"{r.exp} / {step:g}"], ["Price at bar", f"{r.spot:.2f}"],
                        ["Known at", f"close of the {hhmm[b]} bar"], ["Lifecycle", life],
                        ["Invalidation", "OI at this strike falls back below its pre-event level, or 2 closes beyond the strike" if r.typ == "SB"
                         else "a later opposite event at this strike"],
                        ["Algorithm", ALGO]],
               "notes": LIM + (["Forming bar: values change until it closes."] if prov else [])}
        bubble(b, float(r.strike), size, col, border=col.replace("0.40", "0.9").replace("0.45", "0.9").replace("0.60", "0.95"),
               text=code, tip=tip)
        lst = clusters.setdefault((r.sess, float(r.strike)), [])
        lst.append((b, code, float(r.doi)))

    # ---- repeat-level clusters: drawn from the bar the clu_min-th event happened (no back-dating)
    if show_clu:
        for (s, k), lst in clusters.items():
            if len(lst) < clu_min:
                continue
            b0 = lst[clu_min - 1][0]
            codes = [x[1] for x in lst]
            wr = sum(1 for x in codes if x in ("CW", "PW"))
            cv = sum(1 for x in codes if x in ("CC", "PC"))
            calls = sum(1 for x in codes if x[0] == "C")
            dom = "Call writing" if codes.count("CW") > len(codes) / 2 else "Put writing" if codes.count("PW") > len(codes) / 2 \
                else "Covering" if cv > len(codes) / 2 else "Mixed"
            bg = {"Call writing": "rgba(242,54,69,0.10)", "Put writing": "rgba(8,153,129,0.10)", "Covering": "rgba(255,152,0,0.10)"}.get(dom, "rgba(120,123,134,0.10)")
            bd = bg.replace("0.10", "0.55")
            live = s == today_s
            tip = {"title": f"Repeat-level cluster · {k:g} ({dom})", "status": "PROVISIONAL" if live else "CONFIRMED",
                   "rows": [["Events (Observed OI changes)", " ".join(f"{hhmm[b]} {cd}" for b, cd, _ in lst)],
                            ["Net OI change at strike", fmt(sum(x[2] for x in lst))],
                            ["Calls / puts", f"{calls} / {len(lst) - calls}"],
                            ["Known at", f"close of the {hhmm[b0]} bar ({clu_min}th event)"],
                            ["Interpretation", "positions keep being built/closed at this strike today; a level the market is working around"],
                            ["Invalidation", "session ends (clusters are per session) or 2 closes beyond the strike"],
                            ["Algorithm", ALGO]],
                   "notes": LIM[:1] + (["Session still open: more events may join."] if live else [])}
            box(b0, None if live else sess_end[s], k + step * 0.18, k - step * 0.18, bgcolor=bg, border_color=bd,
                text=f"{k:g} ×{len(lst)} {dom}", text_color=bd, tip=tip)

    # ---- wall shifts (max OI strike among all stored strikes, held 2 bars)
    walls = {}
    oi_now = a[a.oi.notna()]
    if show_wall or show_table:
        for right in ("CE", "PE"):
            x = oi_now[oi_now.right == right].pivot_table(index="bar", columns="strike", values="oi", aggfunc="last")
            x = x.reindex(range(n))
            x = x.groupby(sd).ffill()
            arr = x.to_numpy(dtype="float64") if len(x.columns) else np.full((n, 1), np.nan)
            none = np.isnan(arr).all(axis=1)                 # bars with no OI yet (pandas idxmax raises on these)
            j = np.where(np.isnan(arr), -np.inf, arr).argmax(axis=1)
            cols_ = np.asarray(x.columns, dtype="float64") if len(x.columns) else np.array([np.nan])
            wk = np.where(none, np.nan, cols_[j])
            wv = np.where(none, np.nan, arr[np.arange(n), j])
            walls[right] = (wk, wv, x)
    if show_wall:
        for right, (wk, wv, x) in walls.items():
            cur, shifts = {}, {}
            xv, cols = x.to_numpy(dtype="float64"), {k: j for j, k in enumerate(x.columns)}
            for i in range(1, n):
                s = sd[i]
                if s < show_from or wk[i] != wk[i] or sd[i - 1] != s or wk[i - 1] != wk[i]:
                    continue
                if s not in cur:
                    cur[s] = wk[i]
                    continue
                oc = cols.get(cur[s])
                old_oi = xv[i, oc] if oc is not None else float("nan")
                # hysteresis: the new wall must beat the old wall's OI by 5% (else ties flip-flop)
                if wk[i] != cur[s] and shifts.get(s, 0) < 6 and not (wv[i] < 1.05 * old_oi):
                    old = cur[s]
                    cur[s] = wk[i]
                    shifts[s] = shifts.get(s, 0) + 1
                    up = wk[i] > old
                    nm = "Call wall" if right == "CE" else "Put wall"
                    colr = "#f23645" if right == "CE" else "#089981"
                    label(i, float(wk[i]), f"{nm} {'▲' if up else '▼'} {wk[i]:g}", color=colr,
                          textcolor="#ffffff", style="left", size="small")
    # ---- table
    if show_table:
        last = a[a.sess == today_s]
        rows = [[{"text": "Options Positioning", "bold": True}, {"text": ALGO}]]
        if len(last):
            exp = str(last.exp.iloc[-1])
            rows.append(["Expiry", exp])
            for right, nm in (("CE", "Call wall"), ("PE", "Put wall")):
                wk, wv, _ = walls.get(right, (None, None, None))
                if wk is not None and wk[-1] == wk[-1]:
                    rows.append([nm, f"{wk[-1]:g} ({fmt(wv[-1])[1:]})"])
            lb = last[last.bar == last.bar.max()]
            lb = lb[lb.active]
            ce, pe = lb[lb.right == "CE"].oi.sum(), lb[lb.right == "PE"].oi.sum()
            if ce > 0:
                rows.append(["PCR (active, OI)", f"{pe / ce:.2f}"])
            tk = [r for r in kept if r.sess == today_s]
            if tk:
                cc = {}
                for r in tk:
                    cd = KIND[(r.right, r.typ)][0]
                    cc[cd] = cc.get(cd, 0) + 1
                rows.append(["Events today", " ".join(f"{k} {v}" for k, v in sorted(cc.items()))])
            if today_s not in thr:
                rows.append(["Bubbles today", "none: no prior sessions stored (baseline)"])
            t_last = int(ch.time.max())
            tl = pd.Timestamp(t_last, unit="s", tz="UTC").tz_convert(syminfo.timezone or "Asia/Kolkata")
            lm = f"{tl.hour:02d}:{tl.minute:02d}"
            stale = forming and now - (t_last + 60) > 6 * 60
            rows.append(["Options data upto", {"text": lm + " STALE", "color": "#f23645"} if stale else lm])
            rows.append(["Strikes stored", f"{last.strike.nunique()} (step {step:g})"])
        else:
            rows.append(["Today", "no options data yet"])
        rows.append(["Sessions with OI", f"{len(have)} of {len(sess_list)}"])
        table(rows, position="top_right")


main()
