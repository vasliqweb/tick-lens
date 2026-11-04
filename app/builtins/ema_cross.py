# Example custom strategy-style indicator: EMA crossover with signals
indicator("EMA Cross", overlay=True)
fast = input("Fast", 9, min=1)
slow = input("Slow", 21, min=1)
f, s = ema(close, fast), ema(close, slow)
plot(f, "Fast", color="#2962ff")
plot(s, "Slow", color="#ff6d00")
plotshape(crossover(f, s), "Buy", position="below", shape="arrowUp", color="#26a69a", text="BUY")
plotshape(crossunder(f, s), "Sell", position="above", shape="arrowDown", color="#ef5350", text="SELL")
