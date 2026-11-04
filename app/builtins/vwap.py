indicator("VWAP", overlay=True)
day = df.index.normalize()
pv = (hlc3 * volume).groupby(day).cumsum()
plot(pv / volume.groupby(day).cumsum(), "VWAP", color="#e91e63")
