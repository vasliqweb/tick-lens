# Expected Move Bands calibration (NIFTY), study of 2026-11-06

**Verdict: not reliable enough to ship as a "premium" band yet.** Bands computed straight from the VIX are much too wide. Calibrating them helps on average, but the scale drifts between periods, so the stated percentages don't hold on unseen days. The ATM straddle is the most promising source: at 09:20 it was well calibrated without any fitting. But that rests on only 27 days (14 test days), too few to trust.

## Setup (`em_study.py`, all causal)
- NIFTY 1m (97 days, 2026-06-17 .. 2026-11-04, cut 09:15-15:15), India VIX 1m, nearest-expiry option chain 1m (27 days from 2026-09-25).
- Anchors 09:20, 10:15, 11:15, 12:15, 13:15, 14:15. Band = price at the anchor ± multiplier × sigma for the rest of the day (to 15:15).
  - **VIX**: VIX/100/√252 × √(minutes left / 375).
  - **STRAD**: ATM CE+PE at the anchor; sigma to expiry ≈ straddle/0.8; scaled by √(minutes left today / trading minutes to expiry).
  - Multipliers:
    - **raw**: normal z (0.674 / 0.994 / 1.645).
    - **CAL**: one factor fitted on the first half so the 68% band holds 68%.
    - **QCAL**: a separate factor per band, fitted on the first half.
    - **ROLL20**: per-band factors from the previous 20 days only, re-fitted every day.
- CLOSE = the 15:15 close lands inside the band. TOUCH-free = price never leaves the band before 15:15. Pass = every band's CLOSE rate on the second half is within ±6 points of its label.

## Key results: 09:20 anchor, second-half days (unseen), CLOSE inside the band
| Method | 50% band | 68% band | 90% band | 68% width (pts) | pass |
|---|---|---|---|---|---|
| VIX raw | 65% | 82% | 96% | 374 | no (too wide) |
| VIX CAL (k 0.42) | 29% | 49% | 65% | 157 | no (too narrow) |
| VIX QCAL | 45% | 49% | 73% | 157 | no |
| VIX ROLL20 | 45% | 61% | 82% | 210 | no |
| Straddle raw (n = 14) | 50% | 64% | 93% | 372 | yes, but only 14 days |

Across all 6 anchors × 4 versions for the VIX (24 rows, 49 test days each), only one passed: ROLL20 at 14:15 (49% / 65% / 88%). Full tables are in `em_table.md`.

## Reading
- The VIX overstates NIFTY's rest-of-day move by about 2.4× (fitted factor 0.38-0.48). Part of that is because the VIX also prices overnight gaps and event risk, which an intraday band never sees.
- The ratio isn't stable: the second half (Aug 25 - Nov 4) moved more than the first, so a factor fitted on the first half was too narrow later. Rolling 20-day calibration adapts, but still under-covers at the 68% and 90% bands at most anchors.
- Daily moves are fat-tailed: a factor that fits 68% is too narrow at 90%. So separate factors per band are needed, and even those miss on unseen days.
- These bands are about where the close lands, not the range. A calibrated 68% band is touched intraday on most days (TOUCH-free 8-27%). A "price stays inside" band would have to be much wider.
- The straddle is self-calibrating (the market prices the current regime). At 09:20 it hit 50/64/93% on the 14 test days. At later anchors, raw straddle bands get too wide, because time-to-expiry scaling over-weights the expiry-day and overnight risk.

## What would make this shippable
1. Keep recording the option chain daily. Re-run with 60+ straddle days; if the 09:20 straddle band stays within ±6 points, it's the candidate.
2. Model intraday variance with a time-of-day profile instead of uniform minutes (the open and close are more volatile), and test a straddle band with an expiry-day adjustment.
3. Label the band with its measured hit rate and the sample size, never the theoretical %.
