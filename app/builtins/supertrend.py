indicator("Supertrend", overlay=True)
length = input("ATR Length", 10, min=1)
mult = input("Factor", 3.0, step=0.1)
tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
atr = rma(tr, length)
up_b = (hl2 - mult * atr).to_numpy()
dn_b = (hl2 + mult * atr).to_numpy()
c = close.to_numpy()
n = len(c)
up, dn, trend = up_b.copy(), dn_b.copy(), np.ones(n)
for i in range(1, n):
    up[i] = max(up_b[i], up[i - 1]) if c[i - 1] > up[i - 1] else up_b[i]
    dn[i] = min(dn_b[i], dn[i - 1]) if c[i - 1] < dn[i - 1] else dn_b[i]
    trend[i] = 1 if c[i] > dn[i - 1] else -1 if c[i] < up[i - 1] else trend[i - 1]
st = pd.Series(np.where(trend > 0, up, dn), index=close.index)
plot(st.where(trend > 0), "Up", color="#26a69a")
plot(st.where(trend < 0), "Down", color="#ef5350")
t = pd.Series(trend, index=close.index)
plotshape((t > 0) & (t.shift() < 0), "Buy", position="below", shape="arrowUp", color="#26a69a", text="BUY")
plotshape((t < 0) & (t.shift() > 0), "Sell", position="above", shape="arrowDown", color="#ef5350", text="SELL")
