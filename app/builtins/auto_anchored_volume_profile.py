indicator("Auto Anchored Volume Profile", overlay=True, precision=2)
# Auto Anchored Volume Profile: one developing profile from an automatically chosen anchor to the last bar.
# Auto: intraday -> Session, 1D -> Month, 2-10D -> Quarter, 11-60D -> Year, longer -> Decade.
# Highest High / Lowest Low / Highest Volume: that bar within the last <Length> bars (anchor can move).
anchor = input("Anchor Period", "Auto", options=["Auto", "Highest High", "Lowest Low", "Highest Volume", "Session", "Week", "Month", "Quarter", "Year", "Decade", "Century"])
length = input("Length", 20, min=1, max=5000)
layout = input("Row Layout", "Number of Rows", options=["Number of Rows", "Ticks Per Row"])
row_size = input("Row Size", 24, min=1, max=1000)
vol_type = input("Volume", "Up/Down", options=["Up/Down", "Total", "Delta"])
va_pct = input("Value Area Volume %", 70, min=1, max=100)
use_ib = input("Use Lower Timeframe Data", True)
width = input("Width (% of range)", 30, min=5, max=100)
placement = input("Placement", "Left", options=["Left", "Right"])
show_values = input("Show Values", False)
show_poc = input("Show POC", True)
show_va = input("Show Value Area", True)
show_vahval = input("Show VAH/VAL Lines", True)
extend_poc = input("Extend POC Right", False)
extend_vah = input("Extend VAH Right", False)
extend_val = input("Extend VAL Right", False)
dev_poc = input("Show Developing POC", False)
dev_va = input("Show Developing VA", False)
show_box = input("Show Histogram Box", False)
up_col = input("Up Volume Color", "rgba(38,166,154,0.30)")
dn_col = input("Down Volume Color", "rgba(239,83,80,0.30)")
va_up_col = input("Value Area Up Color", "rgba(38,166,154,0.70)")
va_dn_col = input("Value Area Down Color", "rgba(239,83,80,0.70)")
poc_col = input("POC Color", "#ff9800")
vah_col = input("VAH Color", "#2962ff")
val_col = input("VAL Color", "#2962ff")
box_col = input("Histogram Box Color", "rgba(41,98,255,0.06)")

ib = lower_tf(60) if use_ib and 60 < timeframe else None
r = vp.auto_anchored(df, ib, syminfo, timeframe, anchor, length, layout, row_size, va_pct,
                     dev=dev_poc or dev_va, vol_note=syminfo.volume_note)
for p in r["profiles"]:
    profile(p, width=width, placement=placement, volume=vol_type, up=up_col, down=dn_col, va_up=va_up_col,
            va_down=va_dn_col, poc=poc_col, vah=vah_col, val=val_col, show_poc=show_poc, show_va=show_va,
            show_vahval=show_vahval, show_values=show_values, extend_poc=extend_poc, extend_vah=extend_vah,
            extend_val=extend_val, show_box=show_box, box=box_col)
if dev_poc:
    plot(pd.Series(r["devPoc"], index=df.index), "Developing POC", color=poc_col, style="step", linewidth=1)
if dev_va:
    plot(pd.Series(r["devVah"], index=df.index), "Developing VAH", color=vah_col, style="step", linewidth=1)
    plot(pd.Series(r["devVal"], index=df.index), "Developing VAL", color=val_col, style="step", linewidth=1)
