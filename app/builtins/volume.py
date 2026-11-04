indicator("Volume", overlay=True, scale="own", precision=0)
show_ma = input("Show MA", False)
ma_len = input("MA Length", 20, min=1)
plot(volume, "Volume", style="histogram", color=np.where(close >= open, "rgba(38,166,154,0.5)", "rgba(239,83,80,0.5)"))
if show_ma:
    plot(sma(volume, ma_len), "Volume MA", color="#2962ff", linewidth=1)
