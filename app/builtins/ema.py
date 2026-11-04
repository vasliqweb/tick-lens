indicator("EMA", overlay=True)
length = input("Length", 50, min=1)
src = input("Source", "close", options=["open", "high", "low", "close", "hl2", "hlc3", "ohlc4"])
plot(ema(source(src), length), f"EMA {length}", color="#ff6d00")
