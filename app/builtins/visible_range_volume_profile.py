indicator("Visible Range Volume Profile", overlay=True, precision=2)
# Visible Range Volume Profile: one profile of the bars currently on screen, drawn on the right edge;
# recalculated (by the server, debounced) whenever you scroll or zoom. Lower timeframe: first of
# 1/5/15/30/60/240m with < 5000 bars for the range, else chart bars. Developing while the forming bar is visible.
layout = input("Row Layout", "Number of Rows", options=["Number of Rows", "Ticks Per Row"])
row_size = input("Row Size", 24, min=1, max=1000)
vol_type = input("Volume", "Up/Down", options=["Up/Down", "Total", "Delta"])
va_pct = input("Value Area Volume %", 70, min=1, max=100)
use_ib = input("Use Lower Timeframe Data", True)
width = input("Width (% of visible range)", 30, min=5, max=100)
placement = input("Placement", "Right", options=["Left", "Right"])
show_values = input("Show Values", False)
show_poc = input("Show POC", True)
show_va = input("Show Value Area", True)
show_vahval = input("Show VAH/VAL Lines", True)
up_col = input("Up Volume Color", "rgba(38,166,154,0.30)")
dn_col = input("Down Volume Color", "rgba(239,83,80,0.30)")
va_up_col = input("Value Area Up Color", "rgba(38,166,154,0.70)")
va_dn_col = input("Value Area Down Color", "rgba(239,83,80,0.70)")
poc_col = input("POC Color", "#ff9800")
vah_col = input("VAH Color", "#2962ff")
val_col = input("VAL Color", "#2962ff")
profile_spec("vrvp", layout=layout, rows=row_size, va=va_pct, use_ib=use_ib,
             style={"width": width, "placement": placement, "volume": vol_type, "up": up_col, "down": dn_col,
                    "va_up": va_up_col, "va_down": va_dn_col, "poc": poc_col, "vah": vah_col, "val": val_col,
                    "show_poc": show_poc, "show_va": show_va, "show_vahval": show_vahval, "show_values": show_values})
