indicator("Savitzky Flow Bands [ChartPrime]", overlay=True)
# Port of the Pine v6 script "Savitzky Flow Bands [ChartPrime]" (logic kept as written, quirks included).
length = input("Length", 15, min=2)
color_up = input("Up", "#31ca45")
color_dn = input("Down", "#ff7112")
candles = input("CandleStick Color", True)


def _rgba(hx, a):
    hx = hx.lstrip("#")
    if len(hx) < 6:
        return hx
    r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
    return f"rgba({r},{g},{b},{a:.3f})"


# --- Pine coefficient loops, reproduced literally ----------------------------------------
coefficients = [math.nan] * 16
for i in range(-4, 5):
    coefficients[i + 4] = i
    if i == 4:
        for j in range(5, -5, -1):          # Pine "for j = 5 to -4" counts down
            for g in range(8, 16):
                coefficients[g] = j
# -> [-4..3, -4 x8]; norm_factor = sum = -36
norm_factor = sum(coefficients)

wsum = sum(coefficients[k] * close.shift(k) for k in range(16))
x = wsum / norm_factor
# Pine loop "for i = 1 to length-1: polynomial := math.sum(x, i) / i" -> last iteration wins
basis = x.rolling(length - 1, min_periods=length - 1).sum() / (length - 1)

distance = sma(high - low, 100) * 2
hb_raw = (basis + distance).to_numpy()
lb_raw = (basis - distance).to_numpy()
c = close.to_numpy()
n = len(c)
h_band = np.full(n, np.nan)
l_band = np.full(n, np.nan)
direction = np.full(n, np.nan)
count = np.zeros(n)
chg = np.zeros(n, dtype=bool)
d = math.nan
cnt = 0
for i in range(n):
    pl = 0.0 if i == 0 or math.isnan(l_band[i - 1]) else l_band[i - 1]
    pu = 0.0 if i == 0 or math.isnan(h_band[i - 1]) else h_band[i - 1]
    c1 = c[i - 1] if i > 0 else math.nan
    lv, hv = lb_raw[i], hb_raw[i]
    l_band[i] = lv if (lv > pl or c1 < pl) else pl          # NaN comparisons are False, like Pine
    h_band[i] = hv if (hv < pu or c1 > pu) else pu
    if c[i] > h_band[i]:
        d = 1
    if c[i] < l_band[i]:
        d = 0
    direction[i] = d
    prev = direction[i - 1] if i > 0 else math.nan
    chg[i] = (not math.isnan(d)) and (not math.isnan(prev)) and d != prev
    if d == d:                                               # Pine: direction == direction (False while na)
        cnt += 1
    if chg[i]:
        cnt = 0
    count[i] = cnt

up_dir = np.nan_to_num(direction, nan=-1) > 0
t_band = np.where(up_dir, l_band, h_band)
b = basis.to_numpy()
b2 = basis.shift(2).to_numpy()
t_color = np.where(b > b2, color_up, color_dn)

plot(basis, "Filter", color=list(t_color), style="circles", linewidth=1)

band = pd.Series(np.where(chg, np.nan, t_band), index=close.index)
plot(band, "Trend Band", color=color_up, linewidth=1)
alpha = np.clip(1 - (count - 10) / 90.0, 0, 1)               # color.from_gradient(count, 10, 100, up, na)
plot(band, "Trend Extinguishing", color=[_rgba(color_up, a) for a in alpha], linewidth=4)

# Diamonds at direction changes, offset = 1 bar
tf_td = pd.Timedelta(seconds=timeframe)
for i in np.flatnonzero(chg):
    if math.isnan(t_band[i]):
        continue
    xt = df.index[i + 1] if i + 1 < n else df.index[i] + tf_td
    label(xt, t_band[i], "◆", color="rgba(0,0,0,0)", textcolor=_rgba(color_up, 0.3), style="none", size="large")
    label(xt, t_band[i], "◆", color="rgba(0,0,0,0)", textcolor=color_up, style="none", size="small")

if candles:
    barcolor(list(np.where(up_dir, color_up, color_dn)), border=["chart"] * n)   # body only, chart keeps border/wick
