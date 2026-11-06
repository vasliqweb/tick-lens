# Money-flow divergence (NIFTY), study of 2026-11-06

**Verdict: no usable edge.** A new session high or low made while money flow did not confirm it did not reverse more often than one where flow agreed, or than an average bar.

## Setup (`mf_divergence.py`, all causal)
- Data: 97 days of local Breeze 1m bars (2026-06-17 .. 2026-11-04), NIFTY + 50 stocks. First/second half split at 2026-08-25.
- Flow: per-stock candle close-location estimate summed over the 50 stocks (the method the indicator uses for history). `cum` is the session cumulative net flow. Breadth is the share of stocks with positive session flow.
- Events on 3m and 5m bars closing 10:00-14:30: a new session-high close (or low), compared with the highest (lowest) close made at least 30 minutes earlier.
  - **DIV-A**: price higher high, flow lower high (`cum` below `cum` at that earlier high).
  - **DIV-B**: `cum` at least 20% below its session peak.
  - **DIV-BR**: breadth lower than at the earlier high.
  - **CONFIRMED**: new high without DIV-A (baseline a). **ALL BARS**: every bar (baseline b).
- Cooldown: 30 min per group and side. All rows are scored in the reversal direction (down after highs, up after lows).
- Outcomes: hit after 30/60 min; 1-ATR(14) barrier, reversal touched first within 60 min; average points at 60 min, net of 2 points cost. 90% bootstrap CI over days.

## Key results (60-minute reversal hit rate)
| | 3m highs | 3m lows | 5m highs | 5m lows |
|---|---|---|---|---|
| All bars (baseline b) | 52% | 48% | 52% | 48% |
| Confirmed (baseline a) | 56% (n 144) | 47% (n 116) | 53% (n 150) | 45% (n 122) |
| DIV-A flow lower high | 50% (n 34) | 52% (n 90) | 47% (n 36) | 45% (n 82) |
| DIV-B flow 20% off peak | 50% (n 38) | 58% (n 99) | 50% (n 44) | 44% (n 88) |
| DIV-BR breadth lower | 47% (n 59) | 51% (n 111) | 51% (n 61) | 44% (n 102) |

Full tables with CIs, halves, barrier and points are in `divergence_table.md`.

## Reading
- Bearish divergence at highs did worse than confirmed highs at both bar sizes. If anything, confirmed new highs pulled back slightly more often (56%), not less.
- Bullish divergence at lows: one row, DIV-B on 3m (58%, n 99, 65% / 51% by half), technically beats both baselines in both halves. But the same rule on 5m bars is 44%, its average points are negative (-3.6 after costs), and it is 1 of 16 rows tested. I'd treat it as chance, not an edge.
- Every 90% CI overlaps 50% or the baseline.
- Breadth divergence adds nothing.

## Limits
- History is the candle estimate. Only 4 days of real bid/ask ticks exist (3-6 Nov). Re-test with about 40 tick days.
- Index points (the index itself isn't tradable). Cost is a rough NIFTY futures assumption.
