indicator("GTI Pro", overlay=True, show_inputs=False, show_values=False)
# GTI Pro - institutional Supply | Demand | Trap zones.
# Phase 1: volume engine, GTI bar colours, POC / value area.  Phase 2: V (expected-move) and P (volume-profile) zones.
rvol_mode = input("RVOL mode", "Auto", options=["Auto", "Time-of-day", "SMA 20"])
tod_n = input("Time-of-day sessions", 10, min=3, max=50)
rvol_th = input("Institutional RVOL", 1.2, min=0.5, step=0.1)
climax_th = input("Climax RVOL", 2.5, min=1.0, step=0.1)
absorb_body = input("Absorption body/range", 0.35, min=0.05, max=1.0, step=0.05)
absorb_delta = input("Absorption delta against %", 15.0, min=0.0, max=100.0, step=1.0)
absorb_rvol = input("Absorption min RVOL (small body)", 1.8, min=1.0, step=0.1)
delta_src = input("Delta source", "Auto", options=["Auto", "Lower TF", "Chart bar"])
ltf_min = input("Lower TF minutes", 1, options=[1, 3, 5, 15])
palette = input("Palette", "GTI", options=["GTI", "Classic"])
black_border = input("White border on black bars", True)
poc_mode = input("POC", "Developing", options=["Developing", "Previous period"])
show_dpoc = input("Daily POC / VA", True)
show_pdpoc = input("Previous day POC", True)
show_wpoc = input("Weekly POC / VA", True)
va_pct = input("Value area %", 70.0, min=50.0, max=95.0, step=5.0)
bin_pct = input("Profile bin %", 0.03, min=0.01, max=1.0, step=0.01)
show_v = input("V zones (expected move)", True)
show_inner = input("V inner zones", True)
TF_OPTS = ["Auto", "4H", "Daily", "Weekly", "Monthly", "Quarterly", "Half-yearly", "None"]
v_period = input("TF1", "Auto", options=TF_OPTS)
hist1 = input("History TF1", False)
tf2 = input("TF2", "None", options=TF_OPTS[1:])
hist2 = input("History TF2", False)
tf3 = input("TF3", "None", options=TF_OPTS[1:])
hist3 = input("History TF3", True)
show_zlabels = input("Show zone labels", True)
show_poc_lines = input("Show POC lines", True)
show_wkhl = input("Show week Hi & Lo lines", False)
show_range = input("Show weekly range table", False)
range_pos = input("Range table position", "top_right", options=["top_right", "top_left", "middle_right", "middle_left", "bottom_right", "bottom_left"])
show_vwap = input("VWAP", False)
mvwap_len = input("MVWAP length", 50, min=2, max=500)
vix_sym = input("VIX symbol", "Auto")
v_base = input("V base", "Prev close", options=["Prev close", "Period open"])
vol_src = input("Volatility source", "Auto", options=["Auto", "VIX", "HV20", "ATR"])
scale_vix = input("Scale (VIX)", 1.107, min=0.1, step=0.001)
scale_hv = input("Scale (HV / ATR)", 1.0, min=0.1, step=0.01)
show_p = input("P zones (VAH / VAL)", False)
min_score = input("Min zone score", 50, min=0, max=100)
n_periods = input("Periods to show", 5, min=1, max=60)
show_f = input("F zones (footprint)", True)
f_htf = input("F zones from higher TF", True)
f_htf_mult = input("Higher TF = chart TF ×", 4, min=2, max=16)
f_base_atr = input("F base: max range × ATR", 0.6, min=0.1, step=0.05)
f_dep_atr = input("F departure: min range × ATR", 1.5, min=0.5, step=0.1)
f_dep_rvol = input("F departure: min RVOL", 1.5, min=1.0, step=0.1)
f_body = input("F demand zone top", "Base high", options=["Base high", "Highest body"])
f_max = input("Max F zones per side", 6, min=1, max=30)
show_t = input("Trap zones", True)
trap_bars = input("Trap: bars to reclaim level", 3, min=1, max=10)
show_broken = input("Keep broken zones (grey)", False)
sig_rev = input("Signal: reversal at zone (B / S)", True)
sig_cont = input("Signal: continuation (B+ / S+)", True)
sig_trap = input("Signal: trap reversal (T)", True)
sig_score = input("Signal min zone score", 70, min=0, max=100)
cont_trend = input("Continuation trend filter", True)
trade_mode = input("Mode", "Auto", options=["Auto", "Intraday", "Swing", "Positional"])
skip_min = input("Skip first N minutes", 5, min=0)
sq_min = input("Intraday square-off: minutes before close", 15, min=0)
min_rr = input("Min reward : risk", 1.0, min=0.1, step=0.1)
rr_tp = input("Fallback target R:R", 2.0, min=0.5, step=0.5)
sl_buf = input("SL buffer × ATR", 0.05, min=0.0, step=0.05)
opp_exit = input("Exit on opposite GTI bar in profit", True)
trail = input("Trail SL behind new F zones", False)
capital = input("Capital", 500000.0, min=0.0, step=10000.0)
risk_pct = input("Risk % per trade", 1.0, min=0.1, step=0.1)
lot = input("Lot size", 1, min=1)
max_pos_pct = input("Max position value % of capital", 100.0, min=1.0, step=5.0)
min_turnover = input("Min daily turnover (millions, 0 = auto)", 0.0, min=0.0, step=10.0)
keep_lv = input("Keep last N trade levels", 3, min=0, max=20)
show_volt = input("Volume table", True)
vol_rows = input("Volume table rows", 7, min=3, max=20)
vol_pos = input("Volume table position", "bottom_left", options=["top_right", "top_left", "middle_right", "middle_left", "bottom_right", "bottom_left"])
show_dash = input("Dashboard", True)
dash_pos = input("Dashboard position", "bottom_right", options=["top_right", "top_left", "bottom_right", "bottom_left"])

opt_mode = input("Option chart mode", "Auto", options=["Auto", "On", "Off"])
is_option = opt_mode == "On" or (opt_mode == "Auto" and syminfo.type == "option")
if is_option:      # option premiums: no expected-move zones or trade signals, only GTI bars, POC and trapped buyers / sellers
    show_v = show_p = show_f = show_t = sig_rev = sig_cont = sig_trap = show_range = False
    tf2 = tf3 = "None"
intraday = timeframe < 86400
vol = volume.astype(float).fillna(0.0)
has_volume = bool((vol.tail(50) > 0).sum() >= 10)
rng = (high - low)

# ---- volume baseline: time-of-day RVOL (same slot over the last N sessions), SMA20 fallback
mode = rvol_mode
if mode == "Auto":
    mode = "Time-of-day" if intraday and not syminfo.is24x7 else "SMA 20"
# circuit / zero-range bars and bars with no volume yet (index volume still loading) stay out of the averages
base_vol = vol.where((rng > 0) & (vol > 0))
if mode == "Time-of-day":
    slot = session_minute // max(1, timeframe // 60)
    avg = base_vol.groupby(slot.values).transform(lambda s: s.shift(1).rolling(tod_n, min_periods=3).mean())
    # sessions without 3 earlier days of the same slot stay uncoloured (an SMA fallback would flag every open)
else:
    avg = base_vol.shift(1).rolling(20, min_periods=5).mean()
rvol = (vol / avg.replace(0, np.nan)).fillna(0.0)

# ---- delta: close-location of lower-TF intrabars, summed per chart bar (fallback: the chart bar itself)
def clv(h, l, c):
    r = (h - l)
    return (2 * (c - l) / r.replace(0, np.nan) - 1).fillna(0.0)

delta = vol * clv(high, low, close)
delta_from = "chart bar"
ib_by_bar = {}   # chart bar position -> (lows, highs, volumes) of its intrabars, volume scaled to the chart bar
if delta_src != "Chart bar" and intraday:
    ib = lower_tf(ltf_min * 60)
    if ib is not None and len(ib) and ib["volume"].sum() > 0:
        pos = df.index.searchsorted(ib.index, side="right") - 1
        ok = pos >= 0
        ibd = (ib["volume"] * clv(ib["high"], ib["low"], ib["close"]))[ok]
        sums = pd.Series(ibd.to_numpy(), index=pos[ok]).groupby(level=0).sum()
        cover = pd.Series(np.nan, index=range(len(df)))
        cover.loc[sums.index] = sums.to_numpy()
        # intrabar volume is from the source; scale it to the chart bar's volume so units match
        ib_vol = pd.Series(ib["volume"][ok].to_numpy(), index=pos[ok]).groupby(level=0).sum()
        scale = pd.Series(np.nan, index=range(len(df)))
        scale.loc[ib_vol.index] = ib_vol.to_numpy()
        ratio = (cover / scale.replace(0, np.nan)).to_numpy()
        ltf_delta = pd.Series(ratio, index=df.index) * vol
        delta = ltf_delta.where(ltf_delta.notna(), delta)
        # intrabars per chart bar for the volume profile (finer POC, like request.security_lower_tf in v4)
        p_ok = pos[ok]
        il, ih, iv = ib["low"].to_numpy()[ok], ib["high"].to_numpy()[ok], ib["volume"].to_numpy()[ok]
        sc_arr = scale.to_numpy()
        cuts = np.flatnonzero(np.diff(p_ok)) + 1
        for seg in np.split(np.arange(len(p_ok)), cuts):
            if len(seg):
                bi = int(p_ok[seg[0]])
                tot_ib = sc_arr[bi]
                if tot_ib and tot_ib > 0:
                    ib_by_bar[bi] = (il[seg], ih[seg], iv[seg] * (vol.iloc[bi] / tot_ib))
        delta_from = f"{ltf_min}m intrabars"
    elif delta_src == "Lower TF":
        delta_from = "chart bar (no lower-TF data)"
dratio = (delta / vol.replace(0, np.nan)).fillna(0.0)

# ---- GTI bar colours
body = (close - open).abs() / rng.replace(0, np.nan)
against = ((close > open) & (dratio < -absorb_delta / 100)) | ((close < open) & (dratio > absorb_delta / 100))
inst = (rvol >= rvol_th) & (vol > 0)
# absorption: high volume that fails to move price - delta against the candle, or a small body on strong volume
absorption = inst & (against | ((body.fillna(1.0) <= absorb_body) & (rvol >= absorb_rvol)))
yellow = (rvol >= climax_th) | absorption
blue = inst & ~yellow & (delta >= 0)
black = inst & ~yellow & (delta < 0)
if palette == "GTI":
    c_buy, c_sell, c_unusual = "#2962FF", "#000000", "#FFD600"
    c_up, c_dn = None, None
else:
    c_buy, c_sell, c_unusual = "#00E676", "#FF1744", "#FFD600"
    c_up, c_dn = "#1B8F5A", "#B71C1C"
if has_volume:
    colors = pd.Series(None, index=close.index, dtype=object)
    if c_up:
        colors[close >= open] = c_up
        colors[close < open] = c_dn
    colors[blue] = c_buy
    colors[black] = c_sell
    colors[yellow] = c_unusual
    border = colors.copy()
    if black_border and palette == "GTI":
        border[black] = "#FFFFFF"
    barcolor(colors, border)

# ---- volume profile: POC / VAH / VAL of the previous day / week, drawn on the current one
tick = float(syminfo.mintick or 0.01)

def profile(h, l, v, ref):
    step = max(ref * bin_pct / 100, tick)
    lo0 = float(l.min())
    li = np.floor((l.to_numpy() - lo0) / step).astype(int)
    hi = np.floor((h.to_numpy() - lo0) / step).astype(int)
    n = int(hi.max()) + 1
    hist = np.zeros(n)
    vv = v.to_numpy()
    for a, b, x in zip(li, hi, vv):          # spread each bar's volume evenly over the bins it traded in
        if x > 0:
            hist[a:b + 1] += x / (b - a + 1)
    if hist.sum() <= 0:
        return np.nan, np.nan, np.nan
    poc = int(hist.argmax())
    lo_i = hi_i = poc
    tot, need = hist[poc], hist.sum() * va_pct / 100
    while tot < need and (lo_i > 0 or hi_i < n - 1):
        up = hist[hi_i + 1] if hi_i < n - 1 else -1
        dn = hist[lo_i - 1] if lo_i > 0 else -1
        if up >= dn:
            hi_i += 1; tot += hist[hi_i]
        else:
            lo_i -= 1; tot += hist[lo_i]
    mid = lambda i: lo0 + (i + 0.5) * step
    return mid(poc), mid(hi_i) + step / 2, mid(lo_i) - step / 2

def period_levels(key):
    out = {}
    for k, g in df.assign(k=key.values).groupby("k"):
        out[k] = profile(g["high"], g["low"], g["volume"].astype(float), float(g["close"].iloc[-1]))
    keys = sorted(out)
    prev = {keys[i]: out[keys[i - 1]] for i in range(1, len(keys))}
    lv = [prev.get(k, (np.nan, np.nan, np.nan)) for k in key.values]
    a = np.array(lv, dtype=float).reshape(-1, 3)
    return (pd.Series(a[:, j], index=df.index) for j in range(3))

def developing(key, with_va=True):
    """POC (and VAH / VAL) of the period so far at every bar: the session's own profile, built bar by bar."""
    n = len(df)
    out = np.full((n, 3), np.nan)
    hv, lv, vv, ov = high.to_numpy(), low.to_numpy(), vol.to_numpy(), open.to_numpy()
    for _, pos in pd.Series(np.arange(n)).groupby(key.values):
        pos = pos.to_numpy()
        step = max(ov[pos[0]] * bin_pct / 100, tick)
        org = math.floor(lv[pos].min() / step)                 # absolute grid: bins never move as bars arrive
        hist = np.zeros(int(math.floor(hv[pos].max() / step)) - org + 1)
        for i in pos:
            parts = ib_by_bar.get(int(i)) or ([lv[i]], [hv[i]], [vv[i]])
            for l_, h_, v_ in zip(*parts):
                if v_ > 0:
                    a, b = int(math.floor(l_ / step)) - org, int(math.floor(h_ / step)) - org
                    a, b = max(a, 0), min(b, len(hist) - 1)
                    hist[a:b + 1] += v_ / (b - a + 1)
            tot_all = hist.sum()
            if tot_all <= 0:
                continue
            p = int(hist.argmax())
            out[i, 0] = (org + p + 0.5) * step
            if with_va:
                lo_i = hi_i = p
                tot, need, nb = hist[p], tot_all * va_pct / 100, len(hist)
                while tot < need and (lo_i > 0 or hi_i < nb - 1):
                    up = hist[hi_i + 1] if hi_i < nb - 1 else -1
                    dn = hist[lo_i - 1] if lo_i > 0 else -1
                    if up >= dn:
                        hi_i += 1; tot += hist[hi_i]
                    else:
                        lo_i -= 1; tot += hist[lo_i]
                out[i, 1] = (org + hi_i + 1) * step
                out[i, 2] = (org + lo_i) * step
    return (pd.Series(out[:, j], index=df.index) for j in range(3))

week_key = session_day - pd.to_timedelta(session_day.dt.dayofweek, unit="D")
dpoc = dvah = dval = wpoc = None
if has_volume and intraday and show_dpoc and show_poc_lines:
    dpoc, dvah, dval = developing(session_day) if poc_mode == "Developing" else period_levels(session_day)
    plot(dpoc, "Daily POC", color="#2962FF", style="step", linewidth=2)
    plot(dvah, "VAH", color="rgba(41,98,255,0.6)", style="step", linewidth=1)
    plot(dval, "VAL", color="rgba(41,98,255,0.6)", style="step", linewidth=1)
    if show_pdpoc:
        last_poc = dpoc.groupby(session_day.values).last()
        prev_poc = pd.Series(last_poc.shift(1).reindex(session_day.values).to_numpy(), index=df.index)
        plot(prev_poc, "Prev Day POC", color="rgba(126,87,194,0.6)", style="step", linewidth=1)
if has_volume and show_wpoc and show_poc_lines and timeframe < 604800:
    wpoc = next(developing(week_key, with_va=False)) if poc_mode == "Developing" else next(period_levels(week_key))
    plot(wpoc, "Weekly POC", color="#FF9800", style="step", linewidth=2)
if show_wkhl and timeframe < 604800:                     # previous week's high / low
    wk_hl = df.groupby(week_key.values).agg(h=("high", "max"), l=("low", "min")).shift(1)
    plot(pd.Series(wk_hl["h"].reindex(week_key.values).to_numpy(), index=df.index), "Prev Week High", color="#00897B", style="step", linewidth=1)
    plot(pd.Series(wk_hl["l"].reindex(week_key.values).to_numpy(), index=df.index), "Prev Week Low", color="#E53935", style="step", linewidth=1)
if show_vwap and has_volume:
    tp_v = (high + low + close) / 3 * vol
    if intraday:
        plot(tp_v.groupby(session_day.values).cumsum() / vol.groupby(session_day.values).cumsum().replace(0, np.nan),
             "VWAP", color="#AB47BC", linewidth=1)
    plot(tp_v.rolling(mvwap_len).sum() / vol.rolling(mvwap_len).sum().replace(0, np.nan), "MVWAP", color="#8D6E63", linewidth=1)

# ---- zones: V (volatility expected move) and P (previous-period volume profile), scored and merged
PERIOD_DAYS = {"4H": (0.64, 1 / 6), "Daily": (1, 1), "Weekly": (5, 7), "Monthly": (21, 30), "Quarterly": (63, 91), "Half-yearly": (126, 182)}
TF_TAG = {"4H": "4H", "Daily": "D", "Weekly": "W", "Monthly": "M", "Quarterly": "Q", "Half-yearly": "H"}
try:
    _s = str(syminfo.session or "0915-1530").split("-")
    sess_hours = ((int(_s[1][:2]) * 60 + int(_s[1][2:])) - (int(_s[0][:2]) * 60 + int(_s[0][2:]))) / 60 or 24.0
except Exception:
    sess_hours = 6.25
# markets open longer than ~6h (24x7, commodities, most non-Indian exchanges) move more in a day: one period up
long_mkt = bool(syminfo.is24x7) or sess_hours > 6.5 or (syminfo.currency or "INR") != "INR"

def resolve(name):
    if name != "Auto":
        return name
    if timeframe <= 900:
        return "Weekly" if long_mkt else "Daily"
    return "Weekly" if timeframe <= 3600 else "Monthly" if timeframe < 86400 else "Quarterly" if timeframe < 604800 else "Half-yearly"

def period_key(name):
    sd_ = session_day
    if name == "4H":
        return sd_ + pd.to_timedelta((session_minute // 240) * 240, unit="m")
    if name == "Daily":
        return sd_
    if name == "Weekly":
        return week_key
    if name == "Monthly":
        return sd_.dt.to_period("M").dt.start_time
    if name == "Quarterly":
        return sd_.dt.to_period("Q").dt.start_time
    return pd.Series(pd.to_datetime(sd_.dt.year.astype(str) + np.where(sd_.dt.month <= 6, "-01-01", "-07-01")), index=df.index)

v_on = show_v and v_period != "None"
period = resolve("Auto" if v_period == "None" else v_period)    # TF1 drives signals; with TF1 = None only P / F / trap zones
sd = session_day
pkey = period_key(period)

def by_local_date(d):
    """daily bars from request() -> Series of closes indexed by local trading date"""
    try:
        idx = d.index.tz_localize("UTC").tz_convert(syminfo.timezone).tz_localize(None).normalize()
    except Exception:
        idx = d.index.normalize()
    return pd.Series(d["close"].to_numpy(), index=idx).groupby(level=0).last()

daily = request(None, 86400) if timeframe < 86400 else None
dclose = by_local_date(daily) if daily is not None else close.groupby(sd.values).last()
dclose.index = pd.DatetimeIndex(dclose.index)
hv20 = (np.log(dclose).diff().rolling(20, min_periods=10).std() * math.sqrt(365 if syminfo.is24x7 else 252))
dtr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
atr14 = rma(dtr, 14)
vix = None
src_used = vol_src
if vol_src in ("Auto", "VIX") and (syminfo.vix or vix_sym != "Auto"):
    vd = request("VIX" if vix_sym == "Auto" else vix_sym, 86400)
    if vd is not None:
        vix = by_local_date(vd)
        vix.index = pd.DatetimeIndex(vix.index)
if src_used == "Auto":
    src_used = "VIX" if vix is not None else "HV20"
if src_used == "VIX" and vix is None:
    src_used = "HV20"
d_atr = (dclose.diff().abs().rolling(14, min_periods=5).mean() / dclose)          # daily ATR-ish as fraction of price

def asof(s, when):
    """last value of a date-indexed series strictly before `when` (non-repainting)"""
    if s is None or not len(s):
        return np.nan
    k = s.index.searchsorted(when, side="left") - 1
    return float(s.iloc[k]) if k >= 0 else np.nan

def build_zones(name, key, primary):
    """V (and for TF1 also P) zones of every period of `name`; TF1 fills vouter for runaway detection"""
    global last_m, last_sigma
    out = []
    grp = list(pd.Series(np.arange(len(df))).groupby(key.values))
    akeys = sorted(set(key.values))
    plv = {}
    if primary and show_p and has_volume:
        for k, g in df.assign(k=key.values).groupby("k"):
            plv[k] = profile(g["high"], g["low"], g["volume"].astype(float), float(g["close"].iloc[-1]))
    for gi, (k, pos) in enumerate(grp):
        pos = pos.to_numpy()
        first, lastb = int(pos[0]), int(pos[-1])
        is_cur = lastb == len(df) - 1
        start_day = pd.Timestamp(sd.iloc[first])
        ki = akeys.index(k)
        if show_v and (v_on or not primary):
            if v_base == "Period open":
                base = float(open.iloc[first])
            else:
                base = float(close.iloc[first - 1]) if first > 0 else np.nan
            if src_used == "VIX":
                sigma, scale = asof(vix, start_day) / 100, scale_vix
            elif src_used == "ATR":
                sigma, scale = asof(d_atr, start_day) * math.sqrt(252) / 1.25, scale_hv
            else:
                sigma, scale = asof(hv20, start_day), scale_hv
            days = PERIOD_DAYS[name][1 if syminfo.is24x7 else 0]
            m = scale * base * sigma * math.sqrt(days / (365 if syminfo.is24x7 else 252))
            if m == m and m > 0:
                if primary:
                    last_m, last_sigma = m, sigma
                for side in (1, -1):
                    if show_inner:
                        a, b = base + side * 0.245 * m, base + side * 0.385 * m
                        out.append(dict(side=side, kind="inner", top=max(a, b), bottom=min(a, b), score=50, src=["V"],
                                        left=first, right=lastb, extend=is_cur, imp=0.7, tf=name))
                    if primary:
                        vouter.setdefault(first, [np.nan, np.nan])[0 if side > 0 else 1] = base + side * 1.0 * m
                    a, b = base + side * 0.777 * m, base + side * 1.0 * m
                    out.append(dict(side=side, kind="outer", top=max(a, b), bottom=min(a, b), score=70, src=["V"],
                                    left=first, right=lastb, extend=is_cur, imp=1.0, tf=name))
        if primary and show_p and ki > 0 and akeys[ki - 1] in plv:
            poc_p, vah_p, val_p = plv[akeys[ki - 1]]
            a = float(atr14.iloc[first]) if atr14.iloc[first] == atr14.iloc[first] else 0.0
            if vah_p == vah_p:
                out.append(dict(side=1, kind="vp", top=vah_p + 0.1 * a, bottom=vah_p - 0.1 * a, score=60, src=["P"],
                                left=first, right=lastb, extend=is_cur, imp=0.7, tf=name))
                out.append(dict(side=-1, kind="vp", top=val_p + 0.1 * a, bottom=val_p - 0.1 * a, score=60, src=["P"],
                                left=first, right=lastb, extend=is_cur, imp=0.7, tf=name))
    return out, grp

def first_drawn(grp, hist):
    """bar where drawing starts: the current period only, or the last n_periods with history on"""
    k = n_periods if hist else 1
    return int(grp[-k][1].iloc[0]) if len(grp) > k else 0

vouter = {}   # TF1 period start bar -> [supply-target top, demand-target bottom] for runaway detection
last_m, last_sigma = np.nan, np.nan
zones, groups = build_zones(period, pkey, True)     # dicts: side (1 supply / -1 demand), kind (inner/outer/vp), top, bottom, score, src, left, right, extend
draw_from = first_drawn(groups, hist1)               # older periods: signals only

def merge(zs):
    """overlapping same-side zones of one period -> one zone: union of range, max score +10 per extra source"""
    out = []
    for z in sorted(zs, key=lambda z: (z["left"], z["side"], z["bottom"])):
        hit = next((o for o in out if o["side"] == z["side"] and o["left"] == z["left"]
                    and z["bottom"] <= o["top"] and z["top"] >= o["bottom"]), None)
        if hit is None:
            out.append(dict(z, src=list(z["src"]), n=1))
            continue
        hit["top"], hit["bottom"] = max(hit["top"], z["top"]), min(hit["bottom"], z["bottom"])
        if z["score"] > hit["score"] or (z["kind"] == "outer"):
            hit["kind"] = z["kind"] if z["kind"] == "outer" or hit["kind"] != "outer" else hit["kind"]
        hit["score"] = max(hit["score"], z["score"])
        hit["n"] += 1
        for s in z["src"]:
            if s not in hit["src"]:
                hit["src"].append(s)
    for o in out:
        o["score"] = min(100, o["score"] + 10 * (o["n"] - 1))
    return out

zones = [z for z in merge(zones) if z["score"] >= min_score]       # V / P zones, one merged list per period
extra = []                                                         # TF2 / TF3: drawn (and listed on the dashboard), no signals
for _tf, _h in ((tf2, hist2), (tf3, hist3)):
    if _tf != "None" and not (v_on and _tf == period) and show_v:
        _z, _g = build_zones(_tf, period_key(_tf), False)
        _from = first_drawn(_g, _h)
        extra += [z for z in _z if z["left"] >= _from]

# ---- Phase 3-5: one pass over the bars (zone life cycle, traps, signals, trade management)
n = len(df)
H, L, O, C = high.to_numpy(), low.to_numpy(), open.to_numpy(), close.to_numpy()
RV, DL, VOL = rvol.to_numpy(), delta.to_numpy(), vol.to_numpy()
BLUE, BLACK, YEL, INST = (x.to_numpy() for x in (blue, black, yellow, inst))
ATR = atr14.bfill().fillna(0.0).to_numpy()
DAY, PK = sd.to_numpy(), pkey.to_numpy()
SMIN = session_minute.to_numpy()
RNG = H - L
tf_min = max(1, timeframe // 60)
mtick = float(syminfo.mintick or 0.01)
tf_str = f"{tf_min}m" if timeframe < 3600 else f"{timeframe // 3600}h" if timeframe < 86400 else "D" if timeframe < 604800 else "W"
_s = (syminfo.session or "0000-2400").split("-")
sess_len = ((int(_s[1][:2]) * 60 + int(_s[1][2:])) - (int(_s[0][:2]) * 60 + int(_s[0][2:]))) % 1440 or 1440
mode_t = trade_mode if trade_mode != "Auto" else ("Intraday" if intraday else "Swing")
day_trading = mode_t == "Intraday" and intraday and not syminfo.is24x7
ema50 = ema(close, 50).to_numpy()
WPOC = wpoc.to_numpy() if wpoc is not None else None
DPOC = dpoc.to_numpy() if dpoc is not None else None
rnd = lambda x: round(x / mtick) * mtick

# liquidity: average daily turnover of the previous 20 sessions
AUTO_TURN = {"INR": 500, "USD": 20, "EUR": 10, "GBP": 10, "JPY": 2000, "HKD": 100, "CAD": 10, "AUD": 10}
turn_min = (min_turnover or AUTO_TURN.get(syminfo.currency, 0)) * 1e6
day_turn = (close * vol).groupby(sd.values).sum()
avg_turn = day_turn.shift(1).rolling(20, min_periods=3).mean()
TURN = avg_turn.reindex(sd.values).to_numpy()
liquid_ok = lambda i: syminfo.type in ("index", "crypto") or turn_min <= 0 or not (TURN[i] == TURN[i]) or TURN[i] >= turn_min

# -- F zones: base (1-4 small bars) + departure bar (big range, high RVOL, delta in the move direction)
def f_detect(h, l, o, c, rv, dl, atr_prev):
    rng_ = h - l
    small = rng_ <= f_base_atr * atr_prev
    run = np.zeros(len(h), int)
    for i in range(1, len(h)):
        run[i] = min(run[i - 1] + 1, 4) if small[i] else 0
    if len(h):
        run[0] = 1 if small[0] else 0
    up = (rng_ >= f_dep_atr * atr_prev) & (rv >= f_dep_rvol) & (c > o) & (dl > 0)
    dn = (rng_ >= f_dep_atr * atr_prev) & (rv >= f_dep_rvol) & (c < o) & (dl < 0)
    out = []
    for i in np.flatnonzero(up | dn):
        if i < 1 or run[i - 1] < 1:
            continue
        b0 = i - run[i - 1]
        side = -1 if up[i] else 1
        bh, bl = h[b0:i].max(), l[b0:i].min()
        if f_body == "Highest body":
            bodies_hi, bodies_lo = np.maximum(o[b0:i], c[b0:i]).max(), np.minimum(o[b0:i], c[b0:i]).min()
            top, bot = (bodies_hi, bl) if side < 0 else (bh, bodies_lo)
        else:
            top, bot = bh, bl
        size = rng_[i] / atr_prev[i] if atr_prev[i] > 0 else 0
        score = 40 * min(rv[i] / 3, 1) + 30 * min(size / 3, 1) + 30
        out.append((i, b0, side, top, bot, round(score)))
    return out

f_new = {}       # bar from which the zone is live -> [zone]
if show_f and has_volume:
    for i, b0, side, top, bot, sc in f_detect(H, L, O, C, RV, DL, np.r_[np.nan, ATR[:-1]]):
        f_new.setdefault(i + 1, []).append(dict(side=side, top=top, bottom=bot, base=sc, tests=0, left=b0, src=["F"],
                                                kind="f", flip=False, made=i))
    if f_htf:
        htf_min = tf_min * f_htf_mult
        if intraday:
            hk = sd + pd.to_timedelta((session_minute // htf_min) * htf_min, unit="m")
        elif timeframe < 604800:
            hk = week_key
        else:
            hk = sd.dt.to_period("M").dt.start_time
        g = pd.DataFrame({"o": O, "h": H, "l": L, "c": C, "v": VOL, "d": DL, "p": np.arange(n)}).groupby(hk.values)
        hb = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(),
                           "v": g["v"].sum(), "d": g["d"].sum(), "p0": g["p"].min(), "p1": g["p"].max()})
        if len(hb) > 25:
            if hb["p1"].iloc[-1] == n - 1:
                hb = hb.iloc[:-1]                    # the forming higher-TF bar is not confirmed yet
            htr = pd.concat([hb["h"] - hb["l"], (hb["h"] - hb["c"].shift()).abs(), (hb["l"] - hb["c"].shift()).abs()], axis=1).max(axis=1)
            hatr = rma(htr, 14).to_numpy()
            hv = hb["v"].where(hb["v"] > 0)
            hrv = (hb["v"] / hv.shift(1).rolling(20, min_periods=5).mean()).fillna(0).to_numpy()
            for j, j0, side, top, bot, sc in f_detect(hb["h"].to_numpy(), hb["l"].to_numpy(), hb["o"].to_numpy(),
                                                      hb["c"].to_numpy(), hrv, hb["d"].to_numpy(), np.r_[np.nan, hatr[:-1]]):
                act = int(hb["p1"].iloc[j]) + 1
                if act < n:
                    f_new.setdefault(act, []).append(dict(side=side, top=top, bottom=bot, base=sc, tests=0,
                                                          left=int(hb["p0"].iloc[j0]), src=["H"], kind="f", flip=False, made=act - 1))

period_zones = {}
for z in zones:
    period_zones.setdefault(z["left"], []).append(z)

# -- state
fz, tz, broken = [], [], []            # live F zones, live trap zones, broken zones (for grey history)
cur_vp, vout = [], (np.nan, np.nan)
run_up = run_dn = False
prev_hi = prev_lo = np.nan
p_hi = p_lo = np.nan
or_hi = or_lo = np.nan
pend = []                              # trap candidates: dict(dir, lvl, imp, bar, ext, rv)
pend_t = []                            # formed trap zones waiting for the confirming bar
pos = None                             # open trade
trades, sig_labels, run_marks = [], [], []
alerts_n = 0

def fscore(z, i):
    s = z["base"] - 15 * z["tests"]
    for v in cur_vp:
        if v["side"] == z["side"] and v["bottom"] <= z["top"] and v["top"] >= z["bottom"]:
            s += 10
    return min(100, max(0, round(s)))

def tag_of(z):
    if z["kind"] == "trap":
        return "TRAP▼" if z["side"] > 0 else "TRAP▲"
    if z.get("flip"):
        return "S↺" if z["side"] > 0 else "D↺"
    if z["kind"] == "outer":
        return "ST" if z["side"] > 0 else "DT"
    return "S" if z["side"] > 0 else "D"

def target_for(side, entry, i):
    """next opposite zone edge in the trade direction, else daily POC, else R:R"""
    cands = []
    for z in cur_vp + fz + tz:
        if side > 0 and z["side"] > 0 and z["bottom"] > entry:
            cands.append(z["bottom"])
        if side < 0 and z["side"] < 0 and z["top"] < entry:
            cands.append(z["top"])
    if cands:
        return (min(cands) if side > 0 else max(cands)), "zone"
    if DPOC is not None and DPOC[i] == DPOC[i] and (DPOC[i] - entry) * side > 0:
        return DPOC[i], "POC"
    return None, "R:R"

def can_enter(i):
    if pos is not None or not has_volume or not liquid_ok(i):
        return False
    if day_trading and (SMIN[i] < skip_min or SMIN[i] + tf_min > sess_len - sq_min):
        return False
    return True

def enter(i, side, kind, sl, why):
    global pos, alerts_n
    entry = C[i]
    risk = (entry - sl) * side
    if risk <= 0:
        return False
    tp, how = target_for(side, entry, i)
    if tp is None or (tp - entry) * side < min_rr * risk:
        if how == "R:R" or tp is None:
            tp = entry + side * rr_tp * risk
        else:
            return False
    qty = math.floor(capital * risk_pct / 100 / risk / lot) * lot
    qty = min(qty, math.floor(capital * max_pos_pct / 100 / entry / lot) * lot)
    if qty < lot:
        return False
    rr = (tp - entry) * side / risk
    pos = dict(side=side, i=i, entry=entry, sl=sl, sl0=sl, tp=tp, kind=kind, qty=qty, why=why, rr=rr)
    sig_labels.append((i, side, kind))
    msg = (f"GTI Pro {kind} {syminfo.ticker} {tf_str} | {why} | Entry {rnd(entry):,.2f} | SL {rnd(sl):,.2f} | "
           f"TP {rnd(tp):,.2f} | Qty {qty} | Risk {syminfo.currency} {risk * qty:,.0f} | R:R 1:{rr:.1f}")
    alert(msg, bar=i)
    alerts_n += 1
    return True

def close_pos(i, px, reason):
    global pos
    r = (px - pos["entry"]) * pos["side"] / abs(pos["entry"] - pos["sl0"])
    trades.append(dict(pos, x=i, px=px, reason=reason, r=r))
    pos = None

for i in range(n):
    new_day = i == 0 or DAY[i] != DAY[i - 1]
    new_per = i == 0 or PK[i] != PK[i - 1]
    a_i = ATR[i] if ATR[i] > 0 else RNG[i]
    buf = sl_buf * a_i

    # ---------- session / period boundaries
    if new_per:
        prev_hi, prev_lo = p_hi, p_lo
        p_hi, p_lo = H[i], L[i]
        cur_vp = [dict(z, state=0) for z in period_zones.get(i, [])]
        vout = tuple(vouter.get(i, (np.nan, np.nan)))
        run_up = run_dn = False
        for z in cur_vp:                                  # gap through a zone: no signal on its first touch
            if (z["side"] > 0 and O[i] > z["top"]) or (z["side"] < 0 and O[i] < z["bottom"]):
                z["state"] = 2
    else:
        p_hi, p_lo = max(p_hi, H[i]), min(p_lo, L[i])
    if new_day:
        or_hi = or_lo = np.nan
        if intraday:
            tz = [z for z in tz if False]                 # intraday trap zones end with the session
            pend, pend_t = [], []
        if pos is not None and day_trading and i > 0:     # missed square-off (data gap): exit at last close
            close_pos(i - 1, C[i - 1], "session end")
    if intraday and SMIN[i] < 15:
        or_hi = H[i] if or_hi != or_hi else max(or_hi, H[i])
        or_lo = L[i] if or_lo != or_lo else min(or_lo, L[i])
    or_done = intraday and SMIN[i] >= 15

    # ---------- manage the open trade (bar i after entry)
    if pos is not None and i > pos["i"]:
        s = pos["side"]
        if (s > 0 and L[i] <= pos["sl"]) or (s < 0 and H[i] >= pos["sl"]):
            close_pos(i, pos["sl"], "SL")
        elif (s > 0 and H[i] >= pos["tp"]) or (s < 0 and L[i] <= pos["tp"]):
            close_pos(i, pos["tp"], "TP")
        elif opp_exit and ((s > 0 and BLACK[i]) or (s < 0 and BLUE[i])) and (C[i] - pos["entry"]) * s > 0:
            close_pos(i, C[i], "opposite bar")
        elif day_trading and SMIN[i] + tf_min >= sess_len - sq_min:
            close_pos(i, C[i], "square-off")

    # ---------- runaway: close beyond a V target zone = trend day
    if vout[0] == vout[0] and not run_up and C[i] > vout[0]:
        run_up = True
        run_marks.append((i, 1))
        st = next((z for z in cur_vp if z["side"] > 0 and z["kind"] == "outer"), None)
        if st is not None:       # broken supply target -> demand (institutions changed side)
            fz.append(dict(side=-1, top=st["top"], bottom=st["bottom"], base=st["score"], tests=0, left=i,
                           src=["V"], kind="f", flip=True, made=i))
    if vout[1] == vout[1] and not run_dn and C[i] < vout[1]:
        run_dn = True
        run_marks.append((i, -1))
        dt = next((z for z in cur_vp if z["side"] < 0 and z["kind"] == "outer"), None)
        if dt is not None:
            fz.append(dict(side=1, top=dt["top"], bottom=dt["bottom"], base=dt["score"], tests=0, left=i,
                           src=["V"], kind="f", flip=True, made=i))

    # ---------- F zones: breaks, flips, tests
    keep = []
    for z in fz:
        if z["made"] >= i:
            keep.append(z)
            continue
        s = z["side"]
        through = (s < 0 and C[i] < z["bottom"]) or (s > 0 and C[i] > z["top"])
        if through:
            if (s > 0 and BLUE[i]) or (s < 0 and BLACK[i]):
                keep.append(dict(z, side=-s, tests=0, flip=True, made=i, left=i))   # zone flips side
            broken.append(dict(z, right=i))
            continue
        touch = (s < 0 and L[i] <= z["top"]) or (s > 0 and H[i] >= z["bottom"])
        was_out = (s < 0 and L[i - 1] > z["top"]) or (s > 0 and H[i - 1] < z["bottom"])
        z["touch"] = touch
        z["first"] = touch and was_out and z["tests"] == 0
        if touch and was_out:
            z["tests"] += 1
        keep.append(z)
    fz = keep

    # ---------- V / P zone visits (first visit only)
    for z in cur_vp:
        s = z["side"]
        touch = (s < 0 and L[i] <= z["top"]) or (s > 0 and H[i] >= z["bottom"])
        if z["state"] == 0 and touch:
            z["state"] = 1

    # ---------- trap zones: validity, new traps from watched levels
    tz = [z for z in tz if not ((z["side"] > 0 and C[i] > z["top"]) or (z["side"] < 0 and C[i] < z["bottom"]))]
    if show_t and i > 0 and has_volume:
        ups = [(z["top"], 1.0 if z["kind"] == "outer" else 0.7) for z in cur_vp if z["side"] > 0]
        ups += [(z["top"], 0.8) for z in fz if z["side"] > 0]
        dns = [(z["bottom"], 1.0 if z["kind"] == "outer" else 0.7) for z in cur_vp if z["side"] < 0]
        dns += [(z["bottom"], 0.8) for z in fz if z["side"] < 0]
        if prev_hi == prev_hi:
            ups.append((prev_hi, 0.9)); dns.append((prev_lo, 0.9))
        if or_done and or_hi == or_hi:
            ups.append((or_hi, 0.6)); dns.append((or_lo, 0.6))
        if WPOC is not None and WPOC[i] == WPOC[i]:
            ups.append((WPOC[i], 0.7)); dns.append((WPOC[i], 0.7))
        # resolve pending breaks
        still = []
        for p_ in pend:
            p_["ext"] = max(p_["ext"], H[i]) if p_["dir"] > 0 else min(p_["ext"], L[i])
            back = (p_["dir"] > 0 and C[i] < p_["lvl"]) or (p_["dir"] < 0 and C[i] > p_["lvl"])
            if i > p_["bar"] and back and i - p_["bar"] <= trap_bars:
                depth = abs(p_["ext"] - p_["lvl"]) / a_i if a_i > 0 else 0
                sc = round(40 * min(p_["rv"] / 3, 1) + 30 * min(depth / 1.5, 1) + 30 * p_["imp"])
                top, bot = (p_["ext"], p_["lvl"]) if p_["dir"] > 0 else (p_["lvl"], p_["ext"])
                z = dict(side=p_["dir"], top=top, bottom=bot, base=sc, score=sc, tests=0, left=p_["bar"], src=["T"],
                         kind="trap", made=i, imp=p_["imp"])
                tz.append(z)
                tz = tz[-10:]
                if sc >= sig_score and p_["imp"] >= 0.8:
                    pend_t.append(z)
            elif i - p_["bar"] < trap_bars:
                still.append(p_)
        pend = still
        brk_up = (BLUE[i] or YEL[i]) and RV[i] >= rvol_th
        brk_dn = (BLACK[i] or YEL[i]) and RV[i] >= rvol_th
        for lvl, imp in (ups if brk_up else []):
            if C[i] > lvl >= C[i - 1] and not any(abs(p_["lvl"] - lvl) < mtick for p_ in pend):
                pend.append(dict(dir=1, lvl=lvl, imp=imp, bar=i, ext=H[i], rv=RV[i]))
        for lvl, imp in (dns if brk_dn else []):
            if C[i] < lvl <= C[i - 1] and not any(abs(p_["lvl"] - lvl) < mtick for p_ in pend):
                pend.append(dict(dir=-1, lvl=lvl, imp=imp, bar=i, ext=L[i], rv=RV[i]))

    # ---------- signals (bar close)
    if can_enter(i):
        done = False
        # trap reversal: confirmed by the bar after the trap forms
        if sig_trap:
            for z in list(pend_t):
                if z["made"] < i:
                    pend_t.remove(z)
                    if not done and ((z["side"] > 0 and C[i] < O[i]) or (z["side"] < 0 and C[i] > O[i])):
                        sl = z["top"] + buf if z["side"] > 0 else z["bottom"] - buf
                        done = enter(i, -z["side"], "T", sl, f"{tag_of(z)} {z['score']}")
        # continuation: first pullback into a fresh F zone in the trend direction
        if sig_cont and not done:
            for z in fz:
                if not (z.get("touch") and z["tests"] == 1) or z["made"] >= i:      # still inside the first pullback
                    continue
                s = -z["side"]                                   # demand zone -> long
                trend = ((C[i] > WPOC[i]) if WPOC is not None and WPOC[i] == WPOC[i] else ema50[i] > ema50[max(i - 5, 0)]) \
                    if s > 0 else ((C[i] < WPOC[i]) if WPOC is not None and WPOC[i] == WPOC[i] else ema50[i] < ema50[max(i - 5, 0)])
                if cont_trend and not trend and not z.get("flip"):
                    continue
                reject = (s > 0 and C[i] > z["bottom"] and (BLUE[i] or (C[i] > z["top"] and C[i] > O[i]))) or \
                         (s < 0 and C[i] < z["top"] and (BLACK[i] or (C[i] < z["bottom"] and C[i] < O[i])))
                if reject and fscore(z, i) >= min(sig_score, 60):
                    sl = z["bottom"] - buf if s > 0 else z["top"] + buf
                    done = enter(i, s, "B+" if s > 0 else "S+", sl, f"{tag_of(z)} {fscore(z, i)} [{'+'.join(z['src'])}]")
                    if done:
                        break
        # reversal at a zone: first visit, GTI bar inside, close back out
        if sig_rev and not done:
            cands = [(z, z["score"]) for z in cur_vp if z["state"] == 1] + [(z, fscore(z, i)) for z in fz if z.get("touch") and z["tests"] <= 1]
            for z, sc in sorted(cands, key=lambda x: -x[1]):
                if sc < sig_score or not INST[i]:
                    continue
                if z["side"] < 0 and not run_dn and L[i] <= z["top"] and C[i] > z["top"] and C[i] > O[i]:
                    done = enter(i, 1, "B", z["bottom"] - buf, f"{tag_of(z)} {sc} [{'+'.join(z['src'])}]")
                elif z["side"] > 0 and not run_up and H[i] >= z["bottom"] and C[i] < z["bottom"] and C[i] < O[i]:
                    done = enter(i, -1, "S", z["top"] + buf, f"{tag_of(z)} {sc} [{'+'.join(z['src'])}]")
                if done:
                    if z in cur_vp:
                        z["state"] = 2
                    break

    # ---------- end of visits, zone retirement
    for z in cur_vp:
        s = z["side"]
        if z["state"] == 1 and ((s < 0 and (L[i] > z["top"] or C[i] < z["bottom"])) or
                                (s > 0 and (H[i] < z["bottom"] or C[i] > z["top"]))):
            z["state"] = 2
    fz = [z for z in fz if z["tests"] < 3 or z.get("touch")]
    for z in f_new.get(i + 1, []):                          # confirmed at this bar's close, live from the next
        fz.append(dict(z))
        if trail and pos is not None and pos["side"] == -z["side"]:
            nsl = z["bottom"] - buf if pos["side"] > 0 else z["top"] + buf
            if (nsl - pos["sl"]) * pos["side"] > 0 and (C[i] - nsl) * pos["side"] > 0:
                pos["sl"] = nsl
    for side in (1, -1):                                    # keep the newest f_max zones per side
        same = [z for z in fz if z["side"] == side]
        if len(same) > f_max:
            drop = same[:len(same) - f_max]
            fz = [z for z in fz if not any(z is d for d in drop)]

# ---- draw: V / P zones (recent periods), live F and trap zones, signals, trade levels
SUP, DEM = (239, 83, 80), (0, 188, 212)
VSUP, VDEM = (244, 143, 120), (77, 222, 235)          # V zones: salmon / aqua blocks, no border
rgba = lambda rgb, a: f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{a})"
ZNAME = {("outer", 1): "Supply Target Zone", ("inner", 1): "Supply Zone", ("inner", -1): "Demand Zone",
         ("outer", -1): "Demand Target Zone", ("vp", 1): "VAH Zone", ("vp", -1): "VAL Zone"}
for z in [z for z in zones if z["left"] >= draw_from] + extra:
    rgb = (VSUP if z["side"] > 0 else VDEM) if z["kind"] != "vp" else (SUP if z["side"] > 0 else DEM)
    outer = z["kind"] == "outer"
    hi_tf = z["tf"] != period or not v_on
    name = f"{TF_TAG.get(z['tf'], '')}  {ZNAME[(z['kind'], z['side'])]}"
    box(z["left"], z["right"], z["top"], z["bottom"],
        bgcolor=rgba(rgb, (0.28 if outer else 0.45) * (0.55 if hi_tf else 1.0)),
        border_color=rgba(rgb, 0.9) if hi_tf or z["kind"] == "vp" else None, border_style="dashed" if hi_tf else "solid",
        text=(name if z["extend"] else "") if show_zlabels else f"{tag_of(z)} {z['score']}",
        text_color=rgba(SUP if z["side"] > 0 else DEM, 1))
for z in fz:
    sc = fscore(z, n - 1)
    if sc < min_score:
        continue
    rgb = SUP if z["side"] > 0 else DEM
    srcs = list(z["src"]) + [v_ for v in cur_vp if v["side"] == z["side"] and v["bottom"] <= z["top"] and v["top"] >= z["bottom"] for v_ in v["src"]]
    srcs = list(dict.fromkeys(srcs))
    box(z["left"], None, z["top"], z["bottom"], bgcolor=rgba(rgb, 0.30), border_color=rgba(rgb, 1.0),
        border_style="dashed" if z.get("flip") else "solid",
        text=f"{tag_of(z)} {sc} [{'+'.join(srcs)}]" + (f" T{z['tests']}" if z["tests"] else ""), extend=True)
for z in tz:
    if z["score"] < min_score:
        continue
    col = (170, 0, 255) if z["side"] > 0 else (124, 77, 255)
    box(z["left"], None, z["top"], z["bottom"], bgcolor=rgba(col, 0.30), border_color=rgba(col, 1.0),
        text=f"{tag_of(z)} {z['score']}", extend=True)
if show_broken:
    for z in broken[-20:]:
        box(z["left"], z["right"], z["top"], z["bottom"], bgcolor="rgba(158,158,158,0.15)", border_color="rgba(158,158,158,0.5)")
if is_option:      # GTI selling bar at the session low that price reclaims = trapped sellers (and the mirror for buyers)
    lo_d = pd.Series(L).groupby(DAY).cummin().to_numpy()
    hi_d = pd.Series(H).groupby(DAY).cummax().to_numpy()
    for i in range(n):
        side = -1 if BLACK[i] and L[i] <= lo_d[i] else 1 if BLUE[i] and H[i] >= hi_d[i] else 0
        if not side:
            continue
        for j in range(i + 1, min(i + 1 + trap_bars, n)):
            if DAY[j] != DAY[i]:
                break
            if (side < 0 and C[j] > H[i]) or (side > 0 and C[j] < L[i]):
                label(j, L[j] if side < 0 else H[j], "Trapped sellers" if side < 0 else "Trapped buyers",
                      color="#00C853" if side < 0 else "#D50000", style="up" if side < 0 else "down", size="small")
                alert(f"{syminfo.ticker}: {'trapped sellers' if side < 0 else 'trapped buyers'} at {C[j]:,.2f}", bar=j)
                break
COL = {"B": "#00C853", "B+": "#00C853", "S": "#D50000", "S+": "#D50000", "T": "#AA00FF"}
for i, side, kind in sig_labels[-300:]:
    label(i, L[i] if side > 0 else H[i], kind, color=COL[kind], style="up" if side > 0 else "down", size="small")
for i, d in run_marks[-50:]:
    label(i, H[i] if d > 0 else L[i], "RUN▲" if d > 0 else "RUN▼", color="#00C853" if d > 0 else "#D50000",
          style="down" if d > 0 else "up", size="small")
shown = trades[-keep_lv:] if keep_lv else []
if pos is not None and keep_lv:
    shown = shown[-(keep_lv - 1):] if keep_lv > 1 else []
    shown = shown + [dict(pos, x=None, px=None, reason="open", r=None)]
for tr in shown:
    x2 = tr["x"]
    line(tr["i"], tr["entry"], x2, tr["entry"], color="rgba(158,158,158,0.8)", style="dotted")
    line(tr["i"], tr["sl0"], x2, tr["sl0"], color="#D50000")
    line(tr["i"], tr["tp"], x2, tr["tp"], color="#00C853")
    lx = x2 if x2 is not None else n - 1
    label(lx, tr["tp"], f"TP {rnd(tr['tp']):,.2f} (1:{tr['rr']:.1f}) Qty {tr['qty']}", color="rgba(0,200,83,0.85)", style="left", size="small")
    label(lx, tr["sl0"], f"SL {rnd(tr['sl0']):,.2f} ({abs(tr['entry'] - tr['sl0']):,.1f} pts)", color="rgba(213,0,0,0.85)", style="left", size="small")

# ---- volume table: last N bars
if show_volt:
    hdr = {"bg": "#3F51B5", "color": "#fff", "bold": True}
    rows_v = [[dict(hdr, text="Time"), dict(hdr, text="Side"), dict(hdr, text="Last"), dict(hdr, text="Volume")]]
    lt_ = local_time.dt.strftime("%H:%M" if intraday else "%d %b").to_numpy()
    for i in range(n - 1, max(n - 1 - vol_rows, -1), -1):
        up = DL[i] >= 0 if VOL[i] > 0 else C[i] >= O[i]
        bg = ("#00E5FF" if INST[i] else "#B2EBF2") if up else ("#FFD600" if INST[i] else "#FFF59D")
        vv = VOL[i]
        vs = f"{vv/1e7:.2f}Cr" if vv >= 1e7 else f"{vv/1e5:.2f}L" if vv >= 1e5 else f"{vv:,.0f}"
        rows_v.append([{"text": lt_[i], "bg": bg, "color": "#131722"},
                       {"text": "▲" if up else "▼", "bg": bg, "color": "#00796B" if up else "#C62828"},
                       {"text": f"{C[i]:,.2f}", "bg": bg, "color": "#131722"},
                       {"text": vs, "bg": bg, "color": "#131722"}])
    table(rows_v, position=vol_pos)

# ---- weekly range table: expected move from the volatility index (or HV20) around the last price
if show_range:
    sig_now = (float(vix.iloc[-1]) / 100 if src_used == "VIX" and vix is not None and len(vix)
               else float(hv20.dropna().iloc[-1]) if hv20.notna().any() else np.nan)
    px = float(close.iloc[-1])
    yr = 365 if syminfo.is24x7 else 252
    H_, G_, R_, LG = {"bg": "#3D2FAE", "color": "#fff", "bold": True}, {"bg": "#22A845", "color": "#fff", "bold": True}, \
        {"bg": "#E53935", "color": "#fff", "bold": True}, {"bg": "#76E04C", "color": "#0B3D0B"}
    C_ = {"bg": "#D6EEF8", "color": "#1E4FA8"}
    ref = (vix_sym if vix_sym != "Auto" else syminfo.vix or "VIX").split(":")[-1].lstrip("^") if src_used == "VIX" else "HV20"
    rows_r = [[dict(H_, text="Reference Symbol"), dict(H_, text="Current Value"), dict(H_, text="Benchmark Index"), dict(H_, text="Current Value")],
              [dict(G_, text=ref), dict(R_, text="-" if sig_now != sig_now else f"{sig_now * 100:.2f} %"),
               dict(G_, text=str(syminfo.ticker)), dict(LG, text=f"{int(px)}" if px >= 1000 else f"{px:,.2f}")],
              [dict(H_, text="Forecast Period"), dict(H_, text="Forecast Volatility"), dict(H_, text="Min Range"), dict(H_, text="Max Range")]]
    for nm, k in (("Weekly", 5 if not syminfo.is24x7 else 7), ("Daily", 1), ("Hourly", 1 / (24 if syminfo.is24x7 else 6.25 if syminfo.currency == "INR" and not long_mkt else sess_hours))):
        pct = sig_now * math.sqrt(k / yr) if sig_now == sig_now else np.nan
        f = (lambda x: f"{int(x)}") if px >= 1000 else (lambda x: f"{x:,.2f}")
        rows_r.append([dict(G_, text=nm), dict(C_, text="-" if pct != pct else f"+/- {pct * 100:.2f} %"),
                       dict(C_, text="-" if pct != pct else f(px * (1 - pct))), dict(C_, text="-" if pct != pct else f(px * (1 + pct)))])
    table(rows_r, position=range_pos)

# ---- dashboard
if show_dash:
    last = len(df) - 1
    day_delta = delta.groupby(session_day.values).cumsum()
    fmtv = lambda x: "-" if x is None or x != x else (f"{x/1e7:.2f} Cr" if abs(x) >= 1e7 else f"{x/1e5:.2f} L" if abs(x) >= 1e5 else f"{x:,.0f}")
    fmtp = lambda s: "-" if s is None or s.iloc[-1] != s.iloc[-1] else f"{s.iloc[-1]:,.2f}"
    side = "Unusual" if yellow.iloc[-1] else "Buying" if blue.iloc[-1] else "Selling" if black.iloc[-1] else "None"
    side_bg = {"Unusual": "#FFD600", "Buying": "#2962FF", "Selling": "#000000"}.get(side)
    rows = [
        ["Instrument", f"{syminfo.type} · {syminfo.currency}"],
        ["RVOL", f"{rvol.iloc[last]:.2f}× ({mode})"],
        [{"text": "Footprint"}, {"text": side, "bg": side_bg, "color": "#000" if side == "Unusual" else "#fff" if side_bg else None}],
        ["Bar delta", fmtv(delta.iloc[last])],
        ["Day delta", fmtv(day_delta.iloc[last])],
    ]
    if dpoc is not None:
        rows += [["Daily POC", fmtp(dpoc)], ["VAH / VAL", f"{fmtp(dvah)} / {fmtp(dval)}"]]
    if wpoc is not None:
        rows += [["Weekly POC", fmtp(wpoc)]]
    if show_v:
        rows += [["V period", f"{period if v_on else 'off'}" + "".join(f" + {t}" for t in (tf2, tf3) if t != "None" and not (v_on and t == period)) + f" · σ {src_used}" + (f" {last_sigma*100:.1f}%" if last_sigma == last_sigma else "")],
                 ["Expected move", "-" if last_m != last_m else f"±{last_m:,.2f}"]]
    tr_on = len(trades)
    if tr_on:
        wins = [x["r"] for x in trades if x["r"] > 0]
        loss = [-x["r"] for x in trades if x["r"] <= 0]
        pf = (sum(wins) / sum(loss)) if loss and sum(loss) > 0 else float("inf")
        rows += [["Signals", f"{tr_on} · win {len(wins) / tr_on * 100:.0f}% · PF(R) {pf:.2f} · {sum(x['r'] for x in trades):+.1f}R"]]
    if pos is not None:
        rows += [[{"text": "Open trade"}, {"text": f"{pos['kind']} @ {pos['entry']:,.2f} SL {pos['sl']:,.2f} TP {pos['tp']:,.2f}",
                                           "bg": "#00C853" if pos["side"] > 0 else "#D50000", "color": "#fff"}]]
    rows += [["Mode", f"{mode_t}" + (" · runaway ▲" if run_up else " · runaway ▼" if run_dn else "")]]
    if not liquid_ok(n - 1):
        rows += [[{"text": "Liquidity"}, {"text": f"low turnover ({TURN[n-1]/1e6:,.0f}M < {turn_min/1e6:,.0f}M): signals off", "bg": "#B71C1C", "color": "#fff"}]]
    px = float(close.iloc[-1])
    cur = [z for z in zones + extra if z["extend"]] + [dict(z, score=fscore(z, n - 1)) for z in fz] + list(tz)
    for side, name in ((1, "Nearest supply"), (-1, "Nearest demand")):
        cand = [z for z in cur if z["side"] == side and (z["bottom"] >= px if side > 0 else z["top"] <= px)]
        if cand:
            z = min(cand, key=lambda z: abs((z["bottom"] if side > 0 else z["top"]) - px))
            edge = z["bottom"] if side > 0 else z["top"]
            rows += [[name, f"{edge:,.2f} ({(edge - px) / px * 100:+.2f}%) · {z['score']}"]]
    rows += [["Delta from", delta_from]]
    if not has_volume:
        rows += [[{"text": "Data", "bold": True}, {"text": "No volume: use futures / ETF symbol", "bg": "#B71C1C", "color": "#fff"}]]
    table(rows, position=dash_pos, title="GTI Pro")
