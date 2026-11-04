indicator("ATR", overlay=False)
length = input("Length", 14, min=1)
tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
plot(rma(tr, length), "ATR", color="#b71c1c")
