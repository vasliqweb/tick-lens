indicator("Session Volume Profile Chart", overlay=True, precision=2)
# Session volume profile chart: each session drawn as a full-width volume histogram in its own column,
# candles hidden (turn "Hide Candles" off to see both). Same calculation as Session Volume Profile.
#
layout = input("Row Layout", "Number of Rows", options=["Number of Rows", "Ticks Per Row"])
row_size = input("Row Size", 24, min=1, max=1000)
vol_type = input("Volume", "Up/Down", options=["Up/Down", "Total", "Delta"])
va_pct = input("Value Area Volume %", 70, min=1, max=100)
use_ib = input("Use Lower Timeframe Data", True)
max_prof = input("Max Profiles", 60, min=1, max=500)
width = input("Width (% of session)", 95, min=5, max=100)
hide = input("Hide Candles", True)
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
show_box = input("Show Histogram Box", True)
up_col = input("Up Volume Color", "rgba(38,166,154,0.30)")
dn_col = input("Down Volume Color", "rgba(239,83,80,0.30)")
va_up_col = input("Value Area Up Color", "rgba(38,166,154,0.70)")
va_dn_col = input("Value Area Down Color", "rgba(239,83,80,0.70)")
poc_col = input("POC Color", "#ff9800")
vah_col = input("VAH Color", "#2962ff")
val_col = input("VAL Color", "#2962ff")
box_col = input("Histogram Box Color", "rgba(41,98,255,0.06)")

ib = lower_tf(60) if use_ib and 60 < timeframe < 86400 else None
r = vp.session_profiles(df, ib, syminfo, timeframe, "Session", layout, row_size, va_pct, max_prof,
                        dev=dev_poc or dev_va, vol_note=syminfo.volume_note, kind="svpc")
for p in r["profiles"]:
    profile(p, width=width, placement=placement, volume=vol_type, up=up_col, down=dn_col, va_up=va_up_col,
            va_down=va_dn_col, poc=poc_col, vah=vah_col, val=val_col, show_poc=show_poc, show_va=show_va,
            show_vahval=show_vahval, show_values=show_values, extend_poc=extend_poc, extend_vah=extend_vah,
            extend_val=extend_val, show_box=show_box, box=box_col)
if hide:
    barcolor(["rgba(0,0,0,0)"] * len(df), ["rgba(0,0,0,0)"] * len(df))
if dev_poc:
    plot(pd.Series(r["devPoc"], index=df.index), "Developing POC", color=poc_col, style="step", linewidth=1)
if dev_va:
    plot(pd.Series(r["devVah"], index=df.index), "Developing VAH", color=vah_col, style="step", linewidth=1)
    plot(pd.Series(r["devVal"], index=df.index), "Developing VAL", color=val_col, style="step", linewidth=1)
