indicator("Breadth Trend Pro", overlay=True, precision=2)
# PREMIUM. NIFTY / NIFTY FUT on Breeze only (needs the NIFTY 50 stocks' breadth).
# Keeps only the parts of Intraday Move Bias (imb-beta-0.4) that held up in tests on 97 NIFTY days (Jun-Nov 2026):
#  * Trend colour: strong move since the open (+ opening-range position) AND >= 70% of the 50 stocks above their own
#    open (<= 30% for down). Tested: right after 60 min 61% (vs 56% without breadth), in both halves of the data.
#    Index strong but most stocks the other way -> grey "stocks disagree" (the move often fails).
#  * Break warning (5m): a zone touch with >= 3 of 5 break signs. Tested: price went 1 ATR through before 1 ATR back
#    61-67% of the time within 60 min.
#  * Zones: yesterday's volume profile + pivots + Fib, 2 above / 2 below the open, fixed at the open.
# Not shown (no tested edge): mild colours, reversal / rejection / squeeze colours, A+ filter, volume bubbles.
# Causal: bar i uses bars <= i; the forming bar is PROVISIONAL. Context, not BUY/SELL signals.
ALGO = "btp-1.0.0 (from imb-beta-0.4)"
rows = input("Profile Rows", 24, min=8, max=200, tooltip="How finely yesterday's volume profile is split into price rows (zone thickness).")
va_pct = input("Value Area %", 70, min=50, max=95, tooltip="Share of yesterday's volume inside VAH-VAL.")
zone_days = input("Zone History (sessions)", 1, min=1, max=60, tooltip="How many days show their zones. 1 = today only (clean chart).")
show_zones = input("Show Zones", True, tooltip="Support (green) and resistance (red) zones: 2 above and 2 below today's open.")
show_colors = input("Trend Colours", True, tooltip="Colour only the strong, breadth-confirmed bars. Other bars keep their normal colours.")
brd_min = input("Breadth Min", 0.70, min=0.6, max=0.9, step=0.05, tooltip="Share of NIFTY 50 stocks above their own open needed for an up colour (down: at most 1 - this). 0.70 = tested setting.")
strong = input("Trend Threshold", 0.45, min=0.3, max=0.9, step=0.05, tooltip="Score needed for a trend colour (tested: 0.45). Higher = fewer bars.")
brk_on = input("Break Warning", "5m only", options=["5m only", "All timeframes", "Off"], tooltip="Tested on 5m (61-67% broke). On 3m it was ~52% (no edge), so 5m only by default.")
show_table = input("Show Table", True, tooltip="Current state, live zones, this chart's own track record and the tested numbers.")
c_up = input("Up Colour", "#089981")
c_dn = input("Down Colour", "#f23645")
c_dis = input("Stocks Disagree Colour", "#787b86")
c_brk = input("Break Warning Colour", "#e91e63")

LIM = ["Breadth = share of the NIFTY 50 stocks above their own open (from cached 1m candles); not order flow.",
       "Trend colour is a tested lean (~61% after 60 min), not a forecast or a trade signal."]


def main():
    n = len(df)
    B = breadth()
    if n < 30 or timeframe >= 86400 or B is None:
        why = ("needs an intraday chart (1m-1h) with 30+ bars" if (n < 30 or timeframe >= 86400)
               else "needs NIFTY 50 breadth: open Breeze NIFTY or NIFTY FUT")
        table([[{"text": "Breadth Trend Pro", "bold": True}], [why]], position="top_right")
        return
    adv = B["adv_open"].to_numpy(float)
    c, o, h, l = close.to_numpy(float), open.to_numpy(float), high.to_numpy(float), low.to_numpy(float)
    v = np.nan_to_num(volume.to_numpy(float))
    has_vol = v.sum() > 0
    sd = session_day.to_numpy()
    starts = np.flatnonzero(np.r_[True, sd[1:] != sd[:-1]])
    ends = np.r_[starts[1:], n]
    t_sec = df.index.as_unit("s").asi8
    mt = float(syminfo.mintick or 0.01)
    fp = lambda x: f"{x:,.{max(0, min(4, -int(math.floor(math.log10(mt)))))}f}"
    lt = local_time.to_numpy()
    hm = lambda i: f"{pd.Timestamp(lt[i]).hour:02d}:{pd.Timestamp(lt[i]).minute:02d}"

    # ---- zones: previous CONFIRMED session profile + pivots + Fib, 2 above / 2 below the open --------------------
    ib = lower_tf(60) if 60 < timeframe < 86400 else None
    r = vp.session_profiles(df, ib, syminfo, timeframe, "Session", "Number of Rows", rows, va_pct, len(starts),
                            vol_note=syminfo.get("volume_note"))
    prof = {p["l"]: p for p in r["profiles"] if p["status"] == "CONFIRMED"}
    zones_by_s, rng_by_s = {}, {}

    def levels(p, tag):
        tot = np.add(p["up"], p["dn"])
        out = [(tag + "POC", p["pocPrice"], 0), (tag + "VAH", p["vah"], 1), (tag + "VAL", p["val"], 1)]
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
        step, ref, merged = p["step"], o[s], []

        def add(cands):
            for nm, px, pr in sorted(cands, key=lambda x: x[2]):
                if px is not None and all(abs(px - m[1]) > step for m in merged):
                    merged.append((nm, px, pr))
        add(levels(p, "p"))
        ps, pe = starts[g - 1], ends[g - 1]
        PH, PL, PC = float(h[ps:pe].max()), float(l[ps:pe].min()), float(c[pe - 1])
        PR = PH - PL
        if PR > 0:
            PP = (PH + PL + PC) / 3
            for nm_, px_ in (("Pivot P", PP), ("Pivot R1", 2 * PP - PL), ("Pivot S1", 2 * PP - PH), ("Pivot R2", PP + PR),
                             ("Pivot S2", PP - PR), ("Fib 38.2%", PL + 0.382 * PR), ("Fib 50%", PL + 0.5 * PR),
                             ("Fib 61.8%", PL + 0.618 * PR)):
                hit = [k for k, m in enumerate(merged) if abs(px_ - m[1]) <= step]
                if hit:
                    k = hit[0]
                    if nm_ not in merged[k][0]:
                        merged[k] = (merged[k][0] + " + " + nm_, merged[k][1], merged[k][2])
                else:
                    merged.append((nm_, px_, 4 if nm_.startswith("Pivot") else 5))
        for back in range(2, 6):
            q = prof.get(int(t_sec[starts[g - back]])) if g - back >= 0 else None
            if q and q.get("pocPrice") is not None:
                add(levels(q, f"p{back}"))
        half = step / 2
        zl = []
        for d, pool in ((-1, sorted([m for m in merged if m[1] > ref], key=lambda m: m[1])),
                        (1, sorted([m for m in merged if m[1] <= ref], key=lambda m: -m[1]))):
            if PR > 0:
                far = max([m[1] for m in pool], default=ref) if d < 0 else min([m[1] for m in pool], default=ref)
                for fx in (1.272, 1.618, 2.0, 2.618, 3.618, 4.236):
                    px = PL + fx * PR if d < 0 else PH - fx * PR
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
                    if zz["run"] >= 2:                                   # accepted through: next level from bar i + 1
                        zz["br"] = i
                        live.remove(zz)
                        done.append(zz)
                        while nxt < len(pool) and (pool[nxt][1] <= zz["m"][1] if d < 0 else pool[nxt][1] >= zz["m"][1]):
                            nxt += 1
                        if nxt < len(pool) and i + 1 < e:
                            m2 = pool[nxt]; nxt += 1
                            live.append({"m": m2, "s": i + 1, "d": d, "zb": m2[1] - half, "zt": m2[1] + half,
                                         "tests": 0, "run": 0, "br": None})
            zl += done + live
        rng_by_s[g] = (PH, PL)
        zones_by_s[g] = (zl, p)

    # ---- trend score (tested weights) + breadth gate -------------------------------------------------------------
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = rma(tr, 14).to_numpy(float)
    atr = np.where(atr > 0, atr, np.nan)
    clip = lambda x: np.clip(np.nan_to_num(x), -1, 1)
    k_in, s_open = np.zeros(n), np.zeros(n)
    for s_, e_ in zip(starts, ends):
        k_in[s_:e_] = np.arange(e_ - s_)
        s_open[s_:e_] = o[s_]
    OP = clip((c - s_open) / (atr * np.sqrt(k_in + 1)) / 1.5)
    ORB = np.zeros(n)
    nb_or = max(1, int(round(900 / timeframe)))
    for s_, e_ in zip(starts, ends):
        if e_ - s_ > nb_or:
            orh, orl = h[s_:s_ + nb_or].max(), l[s_:s_ + nb_or].min()
            seg = slice(s_ + nb_or - 1, e_)
            ORB[seg] = np.where(c[seg] > orh, 1.0, np.where(c[seg] < orl, -1.0, 0.0))
            ORB[s_ + nb_or - 1] = 0.0
    score = ema(pd.Series(0.75 * OP + 0.25 * ORB, index=df.index), 3).to_numpy(float)

    state = np.full(n, "", dtype=object)
    col = np.full(n, None, dtype=object)
    have = ~np.isnan(adv)
    for dr, nm, cc in ((1, "Up trend (breadth confirmed)", c_up), (-1, "Down trend (breadth confirmed)", c_dn)):
        isS = dr * score >= strong
        agree = isS & have & (dr * (adv - 0.5) >= brd_min - 0.5)
        dis = isS & have & (dr * (adv - 0.5) < 0)
        state[agree], col[agree] = nm, cc
        state[dis], col[dis] = "Stocks disagree", c_dis

    # ---- break-likely warning at fresh zone touches (>= 3 of 5 signs) --------------------------------------------
    brk, brk_dir, brk_info = np.zeros(n, bool), np.zeros(n), {}
    if brk_on == "All timeframes" or (brk_on == "5m only" and timeframe == 300):
        rv_s = (pd.Series(v) / pd.Series(v).rolling(30).median()).to_numpy(float) if has_vol else np.full(n, np.nan)
        opx = np.nan_to_num(OP) * 1.5
        for g, (z, p) in zones_by_s.items():
            for zz in z:
                a_ = max(zz["s"], 1)
                b_ = zz["br"] if zz["br"] is not None else ends[g] - 1
                dz, nm_ = zz["d"], zz["m"][0]
                is_fib = ("Fib" in nm_) and ("FibExt" not in nm_)
                for i in range(a_, min(b_, n - 1) + 1):
                    if sd[i] != sd[i - 1]:
                        continue
                    fresh = (h[i] >= zz["zb"] and h[i - 1] < zz["zb"]) if dz < 0 else (l[i] <= zz["zt"] and l[i - 1] > zz["zt"])
                    if not fresh:
                        continue
                    why = []
                    if is_fib: why.append("Fib zone")
                    if -dz * opx[i] >= 1.0: why.append("strong move since the open towards it")
                    if not np.isnan(adv[i]) and -dz * (adv[i] - 0.5) >= 0.2: why.append(f"{100 * adv[i]:.0f}% of stocks above open")
                    if not np.isnan(rv_s[i]) and rv_s[i] >= 1.5: why.append(f"high volume ({rv_s[i]:.1f}x 30-bar median)")
                    if (c[i] > zz["zt"]) if dz < 0 else (c[i] < zz["zb"]): why.append("closed beyond the zone")
                    if len(why) >= 3:
                        brk[i], brk_dir[i], brk_info[i] = True, -dz, (zz, why)
        state[brk], col[brk] = "Break likely through zone", c_brk
    col[np.isnan(atr)] = None
    if show_colors:
        barcolor(col)

    # ---- this chart's own track record (closed bars only) --------------------------------------------------------
    H60 = max(1, int(round(3600 / timeframe)))
    s_last = np.zeros(n, int)
    for s_, e_ in zip(starts, ends):
        s_last[s_:e_] = e_ - 1
    t60 = [0, 0]
    for i in range(n - 1):
        if state[i].startswith(("Up trend", "Down trend")) and i + H60 <= min(s_last[i], n - 2):
            dr = 1 if state[i].startswith("Up") else -1
            t60[0] += 1; t60[1] += (c[i + H60] - c[i]) * dr > 0
    bk, res_by = [0, 0], {}
    for i in np.flatnonzero(brk):
        if np.isnan(atr[i]) or i >= n - 2:
            continue
        dr = brk_dir[i]; tp_, sl_ = c[i] + dr * atr[i], c[i] - dr * atr[i]; res_ = 0
        for j in range(i + 1, min(i + H60, s_last[i], n - 2) + 1):
            if (l[j] <= sl_) if dr > 0 else (h[j] >= sl_):
                res_ = -1; break
            if (h[j] >= tp_) if dr > 0 else (l[j] <= tp_):
                res_ = 1; break
        res_by[i] = res_
        if res_:
            bk[0] += 1; bk[1] += res_ > 0

    # break-warning marks with hover tips (the candle colour alone has no tooltip)
    first_t = starts[max(0, len(starts) - zone_days)]
    for i, (zz, why) in brk_info.items():
        if i < first_t:
            continue
        prov = i == n - 1
        dr = brk_dir[i]
        res_ = res_by.get(i)
        out_txt = ("pending (needs 1 ATR either way within 60 min)" if res_ in (None, 0) and not prov else
                   "broke through (1 ATR beyond first)" if res_ == 1 else "held (1 ATR back first)" if res_ == -1 else "forming")
        tip = {"title": "Break likely through " + ("resistance" if zz["d"] < 0 else "support") + f" · {zz['m'][0]}",
               "status": "PROVISIONAL" if prov else "CONFIRMED",
               "rows": [["Zone", f"{fp(zz['zb'])} – {fp(zz['zt'])}"], ["Break signs", f"{len(why)} of 5 (needs 3)"]]
                       + [["•", w] for w in why]
                       + [["Known at", f"close of the {hm(i)} bar"], ["Outcome", out_txt]],
               "notes": [f"Rule: first touch of a live zone with >= 3 break signs. Tested on 97 NIFTY days (5m): 61-67% went 1 ATR through before 1 ATR back within 60 min.",
                         f"Invalidation: price closes back {'below' if dr > 0 else 'above'} {fp(zz['zb'] if dr > 0 else zz['zt'])} (inside/behind the zone).",
                         "Evidence: Derived (price, volume, breadth); interpretation, not a trade signal."] + LIM[:1],
               "version": ALGO,
               "simple": [f"Price reached the {'ceiling' if zz['d'] < 0 else 'floor'} near {fp(zz['m'][1])} with {len(why)} signs of breaking it.",
                          f"In tests, zones touched like this broke about 2 times in 3 on 5m charts.",
                          f"Wrong if price closes back {'below' if dr > 0 else 'above'} {fp(zz['zb'] if dr > 0 else zz['zt'])}."]}
        y = h[i] + 0.15 * (atr[i] if atr[i] == atr[i] else 0) if dr > 0 else l[i] - 0.15 * (atr[i] if atr[i] == atr[i] else 0)
        bubble(i, y, 5, "rgba(233,30,99,0.85)", border="#ffffff", tip=tip)

    # ---- zones ---------------------------------------------------------------------------------------------------
    if show_zones:
        for g in sorted(zones_by_s)[-zone_days:]:
            z, p = zones_by_s[g]
            s, e = starts[g], ends[g]
            last_s = g == len(starts) - 1
            for zz in z:
                m, zb, zt, d, broke_at = zz["m"], zz["zb"], zz["zt"], zz["d"], zz["br"]
                kind = "Resistance" if d < 0 else "Support"
                stt = "ACCEPTED THROUGH" if broke_at is not None else ("TESTED" if zz["tests"] else "ACTIVE")
                bg = ("rgba(242,54,69,0.12)" if d < 0 else "rgba(8,153,129,0.12)") if broke_at is None else "rgba(120,123,134,0.08)"
                bd = ("rgba(242,54,69,0.55)" if d < 0 else "rgba(8,153,129,0.55)") if broke_at is None else "rgba(120,123,134,0.45)"
                src = ("Fib extension of the previous session's range" if m[0].startswith("FibExt") else
                       "previous session high/low/close" if m[0].startswith(("Pivot", "Fib ")) else "closed volume profile")
                tip = {"title": f"{kind} zone · {m[0]}", "status": "PROVISIONAL" if last_s and broke_at is None else "CONFIRMED",
                       "rows": [["Level", fp(m[1])], ["Zone", f"{fp(zb)} – {fp(zt)}"], ["Source", src],
                                ["Touches", str(zz["tests"])], ["Lifecycle", stt],
                                ["Known at", "session open" if zz["s"] == s else f"after the previous zone was accepted through ({hm(zz['s'])})"]]
                               + ([["Accepted through", hm(broke_at)]] if broke_at is not None else []),
                       "notes": [f"Invalidation: 2 consecutive closes {'above' if d < 0 else 'below'} the zone = accepted through (greys out; the next level appears).",
                                 "Levels are fixed at the open from closed sessions: they never move during the day."],
                       "version": f"{ALGO} · {p['algorithmVersion']}"}
                live_end = last_s and broke_at is None
                box(int(zz["s"]), None if live_end else int(broke_at if broke_at is not None else e - 1), zt, zb, bgcolor=bg,
                    border_color=bd, border_style="dashed" if broke_at is not None else ("dotted" if m[0].startswith("FibExt") else "solid"),
                    text=f"{'R' if d < 0 else 'S'} {m[0]}", text_color=bd, extend=live_end, tip=tip)

    # ---- table ---------------------------------------------------------------------------------------------------
    if show_table:
        k = n - 2 if n >= 2 else n - 1
        st = state[k] or "No trend colour (no confirmed lean)"
        vk = np.flatnonzero(have[:k + 1])
        a_k = adv[vk[-1]] if len(vk) and sd[vk[-1]] == sd[k] else np.nan
        rows_t = [[{"text": "Breadth Trend Pro", "bold": True}, {"text": ALGO}],
                  ["Last closed bar", {"text": st, "color": col[k] or None, "bold": True}],
                  ["NIFTY 50 stocks above open", "no data yet" if np.isnan(a_k) else f"{100 * a_k:.0f}%"],
                  ["This chart: trend right after 60 min", f"{100 * t60[1] / t60[0]:.0f}% of {t60[0]} bars" if t60[0] >= 30 else f"{t60[0]} bars so far (needs 30)"]]
        if brk_on != "Off":
            rows_t.append(["This chart: break warnings that broke",
                           f"{100 * bk[1] / bk[0]:.0f}% of {bk[0]} decided" if bk[0] >= 10 else
                           (f"{bk[0]} decided so far (needs 10)" if (brk_on == "All timeframes" or timeframe == 300) else "5m charts only (setting)")])
        rows_t.append(["Tested (97 NIFTY days)", "trend 61% right after 60 min; 5m break warnings 61-67% broke"])
        zz = zones_by_s.get(len(starts) - 1)
        if zz:
            for q in sorted([q for q in zz[0] if q["br"] is None or q["br"] >= k], key=lambda q: -q["m"][1]):
                rows_t.append([f"{'R' if q['d'] < 0 else 'S'} · {q['m'][0]}", fp(q["m"][1])])
        rows_t.append(["Status", "last bar PROVISIONAL; closed bars never change"])
        table(rows_t, position="top_right")


main()
