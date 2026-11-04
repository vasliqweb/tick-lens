indicator("Intraday Move Bias", overlay=True, precision=2, help="/static/help/intraday_move_bias.html")
# Next-move BIAS (an estimate, not a signal): candle colour = where the closed bar's evidence leans for the next bars.
# Zones  = previous session's volume profile (VAH / POC / VAL / HVNs / high / low): 2 resistance + 2 support,
#          picked once per session from the session's opening price (fixed for the day, never repainted).
# Bubbles= only bars with unusual volume (time-of-day relative volume), size = how unusual.
# Every input is causal: bar i uses bars <= i only; the previous profile is CONFIRMED (closed session).
# The forming (last) bar's colour / bubble is PROVISIONAL until it closes.
ALGO = "imb-1.4.0"
rows = input("Profile Rows", 24, min=8, max=200, tooltip="How finely yesterday's volume profile is split. More rows = thinner zones and more exact levels; fewer rows = thicker zones.")
va_pct = input("Value Area %", 70, min=50, max=95, tooltip="Share of yesterday's volume inside the 'busy area' (VAH to VAL). Higher % = wider area, VAH/VAL zones move further apart.")
zone_days = input("Zone History (sessions)", 100, min=1, max=200, tooltip="How many past days get their own support/resistance zones. 1 = today only (cleanest chart).")
show_zones = input("Show Zones", True, tooltip="Show or hide the support (green) and resistance (red) zones.")
lvl_src = input("Level Sources", "Volume Profile + Pivots + Fib", options=["Volume Profile + Pivots + Fib", "Volume Profile only"], tooltip="Where zones come from. 'Volume Profile only' = yesterday's POC/VAH/VAL/HVN/high/low. '+ Pivots + Fib' also adds yesterday's floor pivots (P, R1, S1, R2, S2) and Fibonacci retracements (38.2/50/61.8% of yesterday's range); in tests on your data these held slightly better than volume-profile levels. Levels from both that sit together are joined into one zone.")
show_proj = input("Fib Extension Zones when Empty", True, tooltip="When price is beyond every level of the last 5 days (new high/low), draw Fibonacci extension zones of yesterday's range (127.2%, 161.8%, 200%, 261.8%...) so there are still 2 levels each side. Shown dotted.")
show_bub = input("Show Volume Bubbles", True, tooltip="Show or hide circles on candles with unusually high volume.")
bub_days = input("Bubble History (sessions)", 20, min=1, max=200, tooltip="How many past days show bubbles.")
rvol_min = input("Bubble Min RVOL", 1.8, min=1.2, max=20.0, step=0.1, tooltip="A bubble needs at least this many times the normal volume for that time of day. Raise it for fewer bubbles, lower it for more.")
bub_pct = input("Bubble Percentile (prior 5 sessions)", 95.0, min=50.0, max=99.9, step=0.5, tooltip="A bubble also needs to be in the top (100 - this)% of the last 5 days' bars. 95 = top 5%. Raise it for fewer, rarer bubbles.")
bub_max = input("Max Bubbles per Session", 8, min=1, max=50, tooltip="Hard limit of bubbles per day (the first important bars of the day win).")
show_colors = input("Color Bars", True, tooltip="Colour candles by the predicted next move. Off = normal candle colours.")
show_table = input("Show Bias Table", True, tooltip="Small table at top right: current bias, score, track record on this chart, and the live zones.")
rsi_len = input("RSI Length", 14, min=2, tooltip="RSI period used for the orange/blue rejection colours (RSI >= 65 at resistance, <= 35 at support).")
bb_len = input("BB Length", 20, min=5, tooltip="Bollinger Band period. Used for the yellow squeeze colour and for band rejections.")
bb_mult = input("BB Mult", 2.0, step=0.1, tooltip="Bollinger Band width in standard deviations. Bigger = wider bands, fewer band rejections.")
strong = input("Strong Bias Threshold", 0.45, min=0.1, max=0.9, step=0.05, tooltip="Score needed for dark green / red. Higher = fewer but stronger calls.")
mild = input("Mild Bias Threshold", 0.15, min=0.05, max=0.5, step=0.05, tooltip="Score needed for light green / pink. Below this = grey (neutral).")
c_up2 = input("Strong Up Color", "#089981", tooltip="Candle colour when price is more likely to go up.")
c_up1 = input("Mild Up Color", "#7ccfc0", tooltip="Candle colour when price is a little more likely to go up.")
c_neu = input("Neutral Color", "#787b86", tooltip="Candle colour when there is no clear direction.")
c_dn1 = input("Mild Down Color", "#f5a3a1", tooltip="Candle colour when price is a little more likely to go down.")
c_dn2 = input("Strong Down Color", "#f23645", tooltip="Candle colour when price is more likely to go down.")
c_sq = input("Squeeze Color (expansion likely)", "#f5c518", tooltip="Candle colour when price is quiet and squeezed; a bigger move may come soon, direction unknown.")
c_rd = input("Rejection Risk at Resistance", "#ff9800", tooltip="Candle colour when price poked into a ceiling or the upper band and closed back below with high RSI: it may fall back.")
c_ru = input("Rejection Risk at Support", "#2196f3", tooltip="Candle colour when price poked into a floor or the lower band and closed back above with low RSI: it may bounce.")

LIM = ["Bias is a weighted estimate from OHLCV, not a forecast guarantee and not a trade signal.",
       "Up/down volume is candle direction (close vs open), not bid/ask delta."]


def main():
    n = len(df)
    if n < 30 or timeframe >= 86400:
        table([["Intraday Move Bias"], ["Needs an intraday chart (1m-1h) with 30+ bars"]], position="top_right")
        return
    c, o, h, l = close.to_numpy(float), open.to_numpy(float), high.to_numpy(float), low.to_numpy(float)
    v = np.nan_to_num(volume.to_numpy(float))
    has_vol = v.sum() > 0
    vnote = syminfo.get("volume_note")
    sd = session_day.to_numpy()
    starts = np.flatnonzero(np.r_[True, sd[1:] != sd[:-1]])
    ends = np.r_[starts[1:], n]
    t_sec = df.index.as_unit("s").asi8
    mt = float(syminfo.mintick or 0.01)
    fp = lambda x: f"{x:,.{max(0, min(4, -int(math.floor(math.log10(mt)))))}f}"

    # ---- previous-session profiles (CONFIRMED only) ------------------------------------------------
    ib = lower_tf(60) if 60 < timeframe < 86400 else None
    # every session's profile, so the value-location factor is the same on every bar regardless of history length
    r = vp.session_profiles(df, ib, syminfo, timeframe, "Session", "Number of Rows", rows, va_pct, len(starts),
                            vol_note=vnote)
    prof = {p["l"]: p for p in r["profiles"] if p["status"] == "CONFIRMED"}
    pPOC, pVAH, pVAL = (np.full(n, np.nan) for _ in range(3))
    zones_by_s = {}
    adr_by_s = {}
    def levels(p, tag):
        """candidate levels of one profile: (name, price, priority)"""
        tot = np.add(p["up"], p["dn"])
        out = [(tag + "POC", p["pocPrice"], 0), (tag + "VAH", p["vah"], 1), (tag + "VAL", p["val"], 1)]
        # high-volume nodes: local peaks away from the POC, >= 1.3x mean row volume, top 2
        pk = [i for i in range(1, len(tot) - 1) if tot[i] >= tot[i - 1] and tot[i] >= tot[i + 1]
              and abs(i - p["poc"]) > 1 and tot[i] >= 1.3 * tot.mean()]
        out += [(tag + "HVN", p["base"] + p["step"] * (i + 0.5), 2) for i in sorted(pk, key=lambda i: -tot[i])[:2]]
        return out + [(tag + "High", p["high"], 3), (tag + "Low", p["low"], 3)]

    for g, (s, e) in enumerate(zip(starts, ends)):
        if g == 0:
            continue
        p = prof.get(int(t_sec[starts[g - 1]]))
        if not p or p.get("pocPrice") is None:
            continue
        pPOC[s:e], pVAH[s:e], pVAL[s:e] = p["pocPrice"], p["vah"], p["val"]
        step = p["step"]
        ref = o[s]                                                     # known at the session's first tick
        merged = []

        def add(cands):
            for nm, px, pr in sorted(cands, key=lambda x: x[2]):       # keep the higher-priority level when close
                if px is not None and all(abs(px - m[1]) > step for m in merged):
                    merged.append((nm, px, pr))
        add(levels(p, "p"))
        ps, pe = starts[g - 1], ends[g - 1]
        PH, PL, PC = float(h[ps:pe].max()), float(l[ps:pe].min()), float(c[pe - 1])
        PR = PH - PL
        if lvl_src != "Volume Profile only" and PR > 0:
            PP = (PH + PL + PC) / 3
            for nm_, px_ in (("Pivot P", PP), ("Pivot R1", 2 * PP - PL), ("Pivot S1", 2 * PP - PH),
                             ("Pivot R2", PP + PR), ("Pivot S2", PP - PR),
                             ("Fib 38.2%", PL + 0.382 * PR), ("Fib 50%", PL + 0.5 * PR), ("Fib 61.8%", PL + 0.618 * PR)):
                hit = [k for k, m in enumerate(merged) if abs(px_ - m[1]) <= step]
                if hit:                                                # confluence: join the name onto the VP level
                    k = hit[0]
                    if nm_ not in merged[k][0]:
                        merged[k] = (merged[k][0] + " + " + nm_, merged[k][1], merged[k][2])
                else:
                    merged.append((nm_, px_, 4 if nm_.startswith("Pivot") else 5))
        for back in range(2, 6):                                       # older closed sessions: p2 = 2 sessions back ...
            q = prof.get(int(t_sec[starts[g - back]])) if g - back >= 0 else None
            if q and q.get("pocPrice") is not None:
                add(levels(q, f"p{back}"))
        half = step / 2
        # 2 resistances above / 2 supports below the open. When one is accepted through (2 closes beyond), the next
        # level on that side is added from the following bar, so there are always up to 2 live zones each side.
        # average daily range of the previous 5 closed sessions (for projected zones)
        rngs = [float(h[starts[q]:ends[q]].max() - l[starts[q]:ends[q]].min()) for q in range(max(0, g - 5), g)]
        adr = float(np.mean(rngs)) if rngs else 0.0
        zl = []
        for d, pool in ((-1, sorted([m for m in merged if m[1] > ref], key=lambda m: m[1])),
                        (1, sorted([m for m in merged if m[1] <= ref], key=lambda m: -m[1]))):
            if show_proj and PR > 0:
                far = max([m[1] for m in pool], default=ref) if d < 0 else min([m[1] for m in pool], default=ref)
                for fx in (1.272, 1.618, 2.0, 2.618, 3.618, 4.236):
                    px = PL + fx * PR if d < 0 else PH - fx * PR     # extension of yesterday's low->high (up) / high->low (down)
                    if (px > far + step) if d < 0 else (px < far - step):
                        pool.append((f"FibExt {fx * 100:g}%", px, 9))
            live = [{"m": m, "s": s, "d": d} for m in pool[:2]]
            nxt = 2
            for zz in live:
                zz.update(zb=zz["m"][1] - half, zt=zz["m"][1] + half, tests=0, run=0, br=None)
            done = []
            for i in range(s, e):
                for zz in list(live):
                    if i < zz["s"]:
                        continue
                    if h[i] >= zz["zb"] and l[i] <= zz["zt"]:
                        zz["tests"] += 1
                    beyond = c[i] > zz["zt"] if d < 0 else c[i] < zz["zb"]
                    zz["run"] = zz["run"] + 1 if beyond else 0
                    if zz["run"] >= 2:
                        zz["br"] = i
                        live.remove(zz)
                        done.append(zz)
                        # next untouched level beyond the broken one (known at bar i's close -> starts at i + 1)
                        while nxt < len(pool) and (pool[nxt][1] <= zz["m"][1] if d < 0 else pool[nxt][1] >= zz["m"][1]):
                            nxt += 1
                        if nxt < len(pool) and i + 1 < e:
                            m2 = pool[nxt]; nxt += 1
                            live.append({"m": m2, "s": i + 1, "d": d, "zb": m2[1] - half, "zt": m2[1] + half,
                                         "tests": 0, "run": 0, "br": None})
            zl += done + live
        dd = pd.Timestamp(sd[starts[g - 1]])
        adr_by_s[g] = (PH, PL)
        zones_by_s[g] = (zl, p, f"{dd.day:02d} {'JanFebMarAprMayJunJulAugSepOctNovDec'[3 * dd.month - 3:3 * dd.month]}")

    # ---- indicators (all causal) -------------------------------------------------------------------
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = rma(tr, 14).to_numpy(float)
    atr = np.where(atr > 0, atr, np.nan)
    rs = rsi(close, rsi_len).to_numpy(float)
    mid, up_b, lo_b = (x.to_numpy(float) for x in bb(close, bb_len, bb_mult))
    pctb = (c - lo_b) / np.where(up_b - lo_b > 0, up_b - lo_b, np.nan)
    bbw = pd.Series((up_b - lo_b) / mid, index=df.index)
    bbw_lo = bbw.rolling(100, min_periods=50).min().to_numpy(float)
    w = v if has_vol else np.ones(n)
    gkey = sd
    vw = (pd.Series(hlc3.to_numpy(float) * w).groupby(gkey).cumsum() / pd.Series(w).groupby(gkey).cumsum()).to_numpy(float)
    # relative volume, causal and robust to volume-level shifts (futures roll, index constituents):
    #   shape = bar volume / that session's mean bar volume, median per minute-of-session over the PREVIOUS 10 sessions
    #   rvol  = (volume / shape) / median of that over the prior 30 bars   (~1.0 on a normal bar)
    vs = pd.Series(v, index=df.index)
    smean = vs.groupby(sd).transform("mean")
    shape = (vs / smean.where(smean > 0)).groupby(session_minute.to_numpy()).transform(
        lambda x: x.shift(1).rolling(10, min_periods=3).median())
    nv = vs / shape.where(shape > 0).fillna(1.0)
    lvl = nv.shift(1).rolling(30, min_periods=10).median()
    rvol = (nv / lvl.where(lvl > 0)).to_numpy(float) if has_vol else np.full(n, np.nan)
    base = (lvl * shape.fillna(1.0)).to_numpy(float)
    base_kind = np.where(shape.notna().to_numpy(), "30-bar level x time-of-day shape (10 sessions)", "30-bar median (no time-of-day history yet)")
    # importance: also in the top 5% (input) of the previous ~5 sessions' RVOL (adapts to how spiky the instrument is)
    rv_s = pd.Series(rvol, index=df.index)
    rv_q = rv_s.shift(1).rolling(max(60, int(5 * n / max(1, len(starts)))), min_periods=60).quantile(bub_pct / 100).to_numpy(float)
    rng = np.where(h - l > 0, h - l, np.nan)
    clv = np.nan_to_num(((c - l) - (h - c)) / rng)
    body = np.nan_to_num(np.abs(c - o) / rng)

    clip = lambda x: np.clip(np.nan_to_num(x), -1, 1)
    # move since the session open, scaled by ATR * sqrt(bars so far) (intraday momentum, Gao et al. 2018)
    k_in = np.zeros(n)
    s_open = np.zeros(n)
    for s_, e_ in zip(starts, ends):
        k_in[s_:e_] = np.arange(e_ - s_)
        s_open[s_:e_] = o[s_]
    OP = clip((c - s_open) / (atr * np.sqrt(k_in + 1)) / 1.5)
    VW = clip((c - vw) / atr)
    # opening range (first 15 minutes): +1 close above its high, -1 below its low, 0 inside / not finished yet
    ORB = np.zeros(n)
    nb_or = max(1, int(round(900 / timeframe)))
    for s_, e_ in zip(starts, ends):
        if e_ - s_ > nb_or:
            orh, orl = h[s_:s_ + nb_or].max(), l[s_:s_ + nb_or].min()
            seg = slice(s_ + nb_or - 1, e_)
            ORB[seg] = np.where(c[seg] > orh, 1.0, np.where(c[seg] < orl, -1.0, 0.0))
            ORB[s_ + nb_or - 1] = 0.0
    span = np.where(c >= pPOC, pVAH - pPOC, pPOC - pVAL)
    inside = 0.5 * clip((c - pPOC) / np.where(span > 0, span, np.nan))
    L = np.where(np.isnan(pPOC), 0.0, np.where(c > pVAH, 1.0, np.where(c < pVAL, -1.0, inside)))
    VC = np.where(np.nan_to_num(rvol) >= 1.2, clv * np.minimum(np.nan_to_num(rvol) / 2, 1), 0.0)
    # v1.4 weights (user's Breeze data: NIFTY 52d, BANKNIFTY 22d, NIFTY FUT 18d, 3/5/15m): the move since the open was
    # the strongest single factor; the opening-range position adds a little. Value-area location, VWAP, EMA, RSI/%B and
    # gap size did not improve it, so RSI/BB drive only the squeeze + rejection colours.
    raw = 0.75 * OP + 0.25 * ORB
    score = ema(pd.Series(raw, index=df.index), 3).to_numpy(float)

    # per-bar zone context + rejection risk
    rej_dn, rej_up = np.zeros(n, bool), np.zeros(n, bool)
    for g, (z, p, _) in zones_by_s.items():
        s, e = starts[g], ends[g]
        for zz in z:
            a_, b_ = zz["s"], (zz["br"] + 1 if zz["br"] is not None else e)
            if zz["d"] < 0:
                rej_dn[a_:b_] |= (h[a_:b_] >= zz["zb"]) & (c[a_:b_] < zz["zb"])
            else:
                rej_up[a_:b_] |= (l[a_:b_] <= zz["zt"]) & (c[a_:b_] > zz["zt"])
    rej_dn |= (h > up_b) & (c < up_b)
    rej_up |= (l < lo_b) & (c > lo_b)
    rej_dn &= (rs >= 65) & (clv < -0.2)
    rej_up &= (rs <= 35) & (clv > 0.2)
    squeeze = (bbw.to_numpy(float) <= bbw_lo * 1.1) & (np.abs(score) < 0.35)

    state = np.full(n, "Neutral", dtype=object)
    col = np.full(n, c_neu, dtype=object)
    for thr, nm_u, nm_d, cu, cd in ((mild, "Mild up", "Mild down", c_up1, c_dn1), (strong, "Strong up", "Strong down", c_up2, c_dn2)):
        state[score >= thr], col[score >= thr] = nm_u, cu
        state[score <= -thr], col[score <= -thr] = nm_d, cd
    state[squeeze], col[squeeze] = "Squeeze: expansion likely", c_sq
    state[rej_dn], col[rej_dn] = "Rejection risk at resistance", c_rd
    state[rej_up], col[rej_up] = "Rejection risk at support", c_ru
    col[np.isnan(atr)] = None
    if show_colors:
        barcolor(col)

    # ---- track record on this chart: strong calls vs the close 10 bars later (same session, closed bars only) ----
    HZ = 10
    hits = tot_calls = 0
    for i in range(n - 2 - HZ):
        if state[i] in ("Strong up", "Strong down") and sd[i + HZ] == sd[i]:
            tot_calls += 1
            hits += (c[i + HZ] > c[i]) if state[i] == "Strong up" else (c[i + HZ] < c[i])
    track = f"{100 * hits / tot_calls:.0f}%" if tot_calls >= 30 else None
    lt = local_time.to_numpy()
    hm = lambda i: f"{pd.Timestamp(lt[i]).hour:02d}:{pd.Timestamp(lt[i]).minute:02d}"
    DESC = {"POC": "the busiest price", "VAH": "the top of the busy area", "VAL": "the bottom of the busy area",
            "HVN": "a busy price", "High": "the highest price", "Low": "the lowest price"}

    def when(tag):
        b_ = tag.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")[1:] if tag[1:2].isdigit() else ""
        return "yesterday" if not b_ else f"{b_} days ago"

    def kind_of(tag):
        return tag.lstrip("p0123456789")

    # ---- zones (2 above / 2 below the session open) ------------------------------------------------
    if show_zones:
        for g in sorted(zones_by_s)[-zone_days:]:
            z, p, dlabel = zones_by_s[g]
            s, e = starts[g], ends[g]
            last_s = g == len(starts) - 1
            for zz in z:
                m, zb, zt, d, broke_at = zz["m"], zz["zb"], zz["zt"], zz["d"], zz["br"]
                base_nm = m[0].split(" + ")[0]
                nm = "R" if d < 0 else "S"
                stt = "ACCEPTED THROUGH" if broke_at is not None else ("TESTED" if zz["tests"] else "ACTIVE")
                kind = "Resistance" if d < 0 else "Support"
                bg = ("rgba(242,54,69,0.13)" if d < 0 else "rgba(8,153,129,0.13)") if broke_at is None else "rgba(120,123,134,0.10)"
                bd = ("rgba(242,54,69,0.55)" if d < 0 else "rgba(8,153,129,0.55)") if broke_at is None else "rgba(120,123,134,0.5)"
                known = "session open" if zz["s"] == s else "after the previous zone was accepted through"
                tip = {"title": f"{kind} zone · {m[0]}", "status": "PROVISIONAL" if last_s and broke_at is None else "CONFIRMED",
                       "rows": [["Level", fp(m[1])], ["Zone", f"{fp(zb)} – {fp(zt)}"],
                                ["Source", f"Fib extension {m[0][7:]} of previous session range {fp(adr_by_s[g][1])}–{fp(adr_by_s[g][0])}" if m[0].startswith("FibExt") else f"{m[0]} (previous session high/low/close)" if m[0].startswith(("Pivot", "Fib ")) else f"{m[0]} ({'previous session ' + dlabel if base_nm[1:2].isalpha() else base_nm[1] + ' sessions back'}, closed profile)"],
                                ["Open", fp(o[s])], ["Touches", str(zz["tests"])], ["Lifecycle", stt],
                                ["Known at", known], ["Evidence", "Estimated (Fibonacci extension)" if m[0].startswith("FibExt") else "Derived (price pivots)" if m[0].startswith(("Pivot", "Fib ")) else "Derived (volume profile)"]],
                       "notes": [f"Invalidation: 2 consecutive closes {'above' if d < 0 else 'below'} the zone = accepted through (greys out, next level appears).",
                                 f"Profile resolution: {p['res']}; {p.get('volNote') or 'exchange volume'}."] + ([f"Volume: {p['volumeMode']}"] if p.get("volumeMode") != "volume" else []),
                       "version": f"{ALGO} · {p['algorithmVersion']}"}
                is_proj = m[0].startswith("FibExt")
                kd, wd = ("", "") if is_proj else (kind_of(base_nm), when(base_nm))
                thing, side_w = ("ceiling", "above") if d < 0 else ("floor", "below")
                first_line = (f"{DESC[kd].capitalize()} {wd} was {fp(m[1])}." if kd in ("High", "Low")
                              else f"Lots of trading happened near {fp(m[1])} {wd} ({DESC.get(kd, 'a key price')} of that day).")
                if is_proj:
                    first_line = (f"Price is beyond every level of the last 5 days, so this is an ESTIMATED level: "
                                  f"a Fibonacci extension ({m[0][7:]}) of yesterday's range {fp(adr_by_s[g][1])} – {fp(adr_by_s[g][0])}.")
                elif base_nm.startswith("Pivot"):
                    first_line = f"{m[0]} = a classic floor-pivot level from yesterday's high, low and close ({fp(m[1])})."
                elif base_nm.startswith("Fib "):
                    first_line = f"{m[0]} retracement of yesterday's range ({fp(m[1])}): where many traders expect a pullback to pause."
                if " + " in m[0]:
                    first_line += f" Other levels sit here too ({m[0].split(' + ', 1)[1]}), so it is a joined zone."
                simple = [first_line,
                          f"It works like a {thing}: price often slows down or turns {'back down' if d < 0 else 'back up'} here."]
                if broke_at is not None:
                    simple.append(f"At {hm(broke_at)} two candles closed {side_w} it, so this {thing} is broken"
                                  f" and price may keep going {'up' if d < 0 else 'down'}.")
                else:
                    if zz["tests"]:
                        simple.append(f"Price touched it {zz['tests']} time{'s' if zz['tests'] > 1 else ''} and it is still holding.")
                    simple.append(f"If 2 candles close {side_w} {fp(zt if d < 0 else zb)}, the {thing} is broken.")
                tip["simple"] = simple
                live_end = last_s and broke_at is None
                box(int(zz["s"]), None if live_end else int(broke_at if broke_at is not None else e - 1), zt, zb, bgcolor=bg,
                    border_color=bd, border_style="dashed" if broke_at is not None else ("dotted" if is_proj else "solid"), text=f"{nm} {m[0]}",
                    text_color=bd, extend=live_end, tip=tip)

    # ---- volume bubbles (important bars only) -----------------------------------------------------
    if show_bub and has_vol:
        first = starts[max(0, len(starts) - bub_days)]
        per = {}
        for i in range(first, n):
            rv = rvol[i]
            if not (rv >= rvol_min) or not (np.isnan(rv_q[i]) or rv >= rv_q[i]):
                continue
            if per.get(sd[i], 0) >= bub_max:                            # causal cap: first N important bars of the day
                continue
            per[sd[i]] = per.get(sd[i], 0) + 1
            absorb = body[i] < 0.25 and rv >= 2.5
            colr = "rgba(156,39,176,0.55)" if absorb else ("rgba(8,153,129,0.50)" if c[i] >= o[i] else "rgba(242,54,69,0.50)")
            size = float(min(20, 5 + 4 * math.sqrt(max(0.0, rv - rvol_min))))
            prov = i == n - 1
            tip = {"title": "High relative volume bar" + (" · possible absorption (estimate)" if absorb else ""),
                   "status": "PROVISIONAL" if prov else "CONFIRMED",
                   "rows": [["Volume", f"{v[i]:,.0f}"], ["Baseline", f"{base[i]:,.0f} ({base_kind[i]})"],
                            ["RVOL", f"{rv:.2f}x (min {rvol_min:g}x, top {100 - bub_pct:g}% = {rv_q[i]:.2f}x)" if not np.isnan(rv_q[i]) else f"{rv:.2f}x (min {rvol_min:g}x)"], ["Candle", "up" if c[i] >= o[i] else "down"],
                            ["Body / range", f"{body[i]:.0%}"], ["Close location", f"{clv[i]:+.2f}"],
                            ["Bias at close", f"{state[i]} ({score[i]:+.2f})"]],
                   "notes": ["Evidence: volume Observed; RVOL Derived; absorption Interpreted from OHLCV (no bid/ask data)."]
                            + ([vnote] if vnote else []) + (["Forming bar: values change until it closes."] if prov else []),
                   "version": ALGO}
            rr = h[i] - l[i]
            uw = (h[i] - max(o[i], c[i])) / rr if rr > 0 else 0
            lw = (min(o[i], c[i]) - l[i]) / rr if rr > 0 else 0
            simple = [f"About {rv:.1f}× more trading than normal for this time of day."]
            if absorb:
                simple.append("Price hardly moved even with so much trading. Buyers and sellers fought hard; a big player may be quietly filling orders here.")
            elif uw > 0.5:
                simple.append("Price went up, but sellers pushed it back down before the candle closed.")
            elif lw > 0.5:
                simple.append("Price dropped, but buyers pushed it back up before the candle closed.")
            elif c[i] >= o[i] and clv[i] > 0.3:
                simple.append("Buyers won this candle and it closed near its high.")
            elif c[i] < o[i] and clv[i] < -0.3:
                simple.append("Sellers won this candle and it closed near its low.")
            else:
                simple.append("Both buyers and sellers were busy; the candle closed in the middle.")
            g_ = int(np.searchsorted(starts, i, side="right") - 1)
            for zz in (zones_by_s.get(g_, ([],))[0]):
                if zz["s"] <= i and (zz["br"] is None or zz["br"] >= i) and l[i] <= zz["zt"] and h[i] >= zz["zb"]:
                    simple.append(f"It happened right at a {'ceiling (resistance)' if zz['d'] < 0 else 'floor (support)'} "
                                  f"near {fp(zz['m'][1])}.")
                    break
            stt_i = state[i]
            nxt_txt = {"Strong up": "price is more likely to go UP in the next few candles.",
                       "Mild up": "price is a little more likely to go up.",
                       "Neutral": "no clear direction yet; it could go either way.",
                       "Mild down": "price is a little more likely to go down.",
                       "Strong down": "price is more likely to go DOWN in the next few candles.",
                       "Squeeze: expansion likely": "price is quiet and squeezed; a bigger move may come soon (up or down).",
                       "Rejection risk at resistance": "price may fall back from this ceiling.",
                       "Rejection risk at support": "price may bounce up from this floor."}.get(stt_i, "no clear direction yet.")
            up_c = c[i] >= o[i]
            if (up_c and stt_i in ("Strong down", "Mild down")) or (not up_c and stt_i in ("Strong up", "Mild up")):
                simple.append(f"But the bigger picture today still points {'down' if up_c else 'up'}.")
            simple.append("What next: " + nxt_txt)
            if stt_i in ("Strong up", "Mild up", "Rejection risk at support"):
                simple.append(f"This idea is wrong if a candle closes below {fp(l[i])}.")
            elif stt_i in ("Strong down", "Mild down", "Rejection risk at resistance"):
                simple.append(f"This idea is wrong if a candle closes above {fp(h[i])}.")
            simple.append("It is a guess, not a promise." + (f" On this chart, strong calls were right {track} of the time after {HZ} candles." if track else ""))
            if prov:
                simple.append("This candle is still forming, so this can change.")
            tip["simple"] = simple
            bubble(i, (h[i] + l[i] + c[i]) / 3, size, colr, border=colr.replace("0.50", "0.9").replace("0.55", "0.9"),
                   text=f"{rv:.1f}x" if size >= 11 else "", tip=tip)

    # ---- compact status table ---------------------------------------------------------------------
    if show_table:
        k = n - 2 if n >= 2 else n - 1                                  # last CLOSED bar
        rows_t = [[{"text": "Next-move bias (estimate)", "bold": True}, {"text": state[k], "color": col[k] or c_neu, "bold": True}],
                  ["Score (last closed bar)", f"{score[k]:+.2f}"]]
        if track:
            rows_t.append([f"Strong calls right after {HZ} bars", f"{track} ({tot_calls} calls, this chart)"])
        zz = zones_by_s.get(len(starts) - 1)
        if zz:
            live = sorted([q for q in zz[0] if q["br"] is None or q["br"] >= k], key=lambda q: -q["m"][1])
            for q in live:
                rows_t.append([f"{'R' if q['d'] < 0 else 'S'} · {q['m'][0]}", fp(q["m"][1])])
            for d_, side in ((-1, "Resistance"), (1, "Support")):
                if not any(q["d"] == d_ for q in live):
                    rows_t.append([side, "none: beyond 5 days of levels (turn on Fib Extension Zones)"])
        else:
            rows_t.append(["Zones", "no closed previous session"])
        if not has_vol:
            rows_t.append(["Volume", "none: bubbles off, VWAP time-weighted"])
        table(rows_t, position="top_right")


main()
