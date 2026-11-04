indicator("SMA", overlay=True)
length = input("Length", 20, min=1)
src = input("Source", "close", options=["open", "high", "low", "close", "hl2", "hlc3", "ohlc4"])
plot(sma(source(src), length), f"SMA {length}", color="#2962ff")
