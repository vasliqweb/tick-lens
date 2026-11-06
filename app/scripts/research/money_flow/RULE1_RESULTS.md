# Rule 1: level breakout confirmed by money flow (NIFTY), study of 2026-11-06

**Verdict: no edge.** Breakouts that came with STRONG money flow in the same direction did not follow through more often than other breakouts.

## Setup (`rule1_breakout.py`, all causal)
- Data: local Breeze 1m bars, NIFTY + 50 stocks, 97 days (2026-06-17 .. 2026-11-04). 63 days had at least one breakout.
- Levels from the previous session: high (PDH), low (PDL), and the 70% value-area high and low (VAH/VAL).
- Event: first 1m close through a level, 09:45-14:15 IST, at most one per level per side per day. 230 events.
- Flow: candle estimate (close-location), the same method the indicator uses for history. STRONG means the last 30 minutes are in the top 20% of the previous 5 sessions. Breadth means at least 60% of stocks have net inflow (at most 40% for a down break).
- Outcome: points moved in the breakout direction after 15/30/60 min. Cost is 2 points per trade. The ± figure is the 95% range from sample size.

## Key results
| Group | n | 30 min hit | 60 min hit | avg 60 min (pts) | 60 min hit, 1st half / 2nd half |
|---|---|---|---|---|---|
| All breakouts (baseline) | 230 | 54% ±6 | 51% ±6 | +2.5 | 47% / 56% |
| STRONG flow with breakout | 64 | 56% ±12 | **45%** ±12 | -1.7 | 52% / 39% |
| STRONG + breadth | 28 | 61% ±18 | **43%** ±18 | +8.0 | 33% / 50% |
| Flow against breakout | 95 | 53% ±10 | 57% ±10 | +10.1 | 48% / 68% |

## Reading
- Breakouts of yesterday's levels are a coin flip on their own: 51% at 60 minutes, about +0.5 points after costs.
- Adding STRONG flow in the breakout direction did not help. It was slightly worse at 60 minutes and not consistent between the two halves. The 30-minute numbers are a little higher, but well inside the noise (±12 to ±18 points of hit rate).
- Breakouts against the flow did slightly better at 60 minutes, but only in the second half. It's probably noise, and it doesn't pass the "both halves, n ≥ 40" bar.
- Per level and per direction, the samples are tiny (6 to 9 events). Ignore them.

## Limits
- History is the candle estimate, not real bid/ask ticks; only 4 tick days exist (3-6 Nov). Tick-based flow might behave differently. Re-run once there are about 40 tick days.
- The NIFTY index isn't tradable. Points are index points, and the cost is a rough futures assumption.
- One breakout definition (the first 1m close). Retest entries or holding above the level for N minutes were not tested.
