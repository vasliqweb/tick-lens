# TickLens

Browser charting app in the style of TradingView. Free/open-source only:
FastAPI + pandas + pandas-ta on the backend, TradingView **lightweight-charts v5** (Apache-2.0, vendored) on the frontend,
market data from **yfinance**, **jugaad-data** (NSE), **ccxt** (crypto) or a built-in simulator.

## Run
```
./run.sh          # macOS/Linux
run.bat           # Windows
```
Open http://127.0.0.1:8000

Opening it from another device on a private network (e.g. Tailscale): start uvicorn with `--host 0.0.0.0` and set
`LTV_ALLOWED_HOSTS=<private ip or name>` (comma-separated), otherwise the live socket rejects that origin (HTTP 403) and
no chart loads. Indicator scripts run as Python on the server, so never list a public address.

## Features
- Candles / hollow / bars / line / area / Heikin Ashi, volume, dark + light theme
- Timeframes 1m 5m 15m 30m 1h 1D 1W, live updates (Yahoo WebSocket, ccxt.pro, NSE polling; auto-fallback to polling)
- Symbol search (Yahoo), watchlist, layout saved in the browser
- 11 built-in indicators: SMA, EMA, Bollinger, VWAP, Supertrend, EMA Cross, RSI, MACD, Stochastic, ATR, ADX (pandas-ta)
- Indicator settings dialog, show/hide, separate panes for oscillators, buy/sell markers
- **Script editor**: write your own indicator in Python, Add/Update on chart, Save (Ctrl+S), run (Ctrl+Enter)

## ICICI Breeze (live NSE data)
Put these in `.env` next to `app.py` (session token changes daily):
```
BREEZE_API_KEY=...
BREEZE_API_SECRET=...
BREEZE_SESSION_TOKEN=...
```
Pick source **ICICI Breeze** in the symbol dialog and use NSE symbols (`RELIANCE`, `M&M`) or index codes
(`NIFTY`, `CNXBAN`, `NIFFIN`, `CNXIT`). Timeframes 15m/1h/1W are resampled from 5m/30m/1D.
History is cached in `cache/breeze/` (only finished days). Calls are limited to 90/min.

**Index volume:** for `NIFTY` and `CNXBAN` the volume is the sum of the constituents' volume
(list from NSE archives, built-in Nifty 50 fallback) plus live tick volume. The first load of a timeframe
takes about a minute (50 stocks); later loads use the cache.

## One source at a time, one name for every symbol
The **Yahoo | Breeze** switch in the top bar sets the source for the chart and the whole watchlist.
Symbols use NSE names everywhere: `RELIANCE`, `M&M`, `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `NIFTYIT`.
The server translates them per source (`core/symbols.py`): `RELIANCE` → `RELIANCE.NS` (Yahoo) / `RELIND` (Breeze),
`NIFTY` → `^NSEI` / `NIFTY`, `BANKNIFTY` → `^NSEBANK` / `CNXBAN`. Old names (`RELIANCE.NS`, `^NSEI`, `CNXBAN`) are converted.

**Futures & options (Breeze only):** search `NIFTY FUT`, `NIFTY 24000 CE`, `BANKNIFTY NOV 52000 PE`.
Contract names look like `NIFTY 27NOV26 24000 CE` / `NIFTY 27NOV26 FUT`.

**Volume** is an indicator (ƒx → Volume) with an optional moving average.

## Volume profiles (engine vp-1.1.0, `core/volume_profile.py`, tests `tests/test_volume_profile.py`)
ƒx indicators: **Session Volume Profile**, **Session Volume Profile HD** (rows adapt to zoom), **Session Volume Profile Chart**
(full-width session histograms, candles hidden), **Periodic Volume Profile** (N × Bar/Minute/Hour/Day/Week/Month, restarts each year),
**Auto Anchored Volume Profile** (Auto / Highest High / Lowest Low / Highest Volume / Session…Century), **Visible Range Volume Profile**
(bars on screen, right edge). Drawing tools: **Fixed Range** and **Anchored** volume profile (⚙ for settings).
- Calculation (TradingView rules): close ≥ open = up volume; VA grows one row at a time from the POC, larger side first
  (tie → closer, then above), stops when the next row would exceed the target %. Lower timeframe = first of 1/5/15/30/60/240m with
  < 5000 bars (Periodic: chart-TF table), built from the 1m cache; else chart bars (labelled).
- Settings: rows layout/size, Up/Down · Total · Delta, VA %, width, placement, values, POC/VA/VAH/VAL, extend POC/VAH/VAL right
  (until a later bar crosses), developing POC/VA, histogram box, colours.
- Current session / developing range is **PROVISIONAL** (dashed POC); closed sessions are fixed. Hover a histogram for the evidence trail.
- Index volume: Breeze NIFTY/BANKNIFTY = sum of constituents (real); Yahoo ^NSEI = ETF proxy (labelled). No volume → time-at-price (labelled).
- Up/Down volume is candle direction, **not** bid/ask delta.

## Intraday Move Bias (ƒx, `builtins/intraday_move_bias.py`, imb-1.4.0, tests `tests/test_intraday_move_bias.py`)

How-to page (simple English, real chart examples): `static/help/intraday_move_bias.html`, opened from ⚙ Settings → Inputs → "How to use this indicator" (any script can set it with `indicator(..., help="/static/help/<page>.html")`).
Next-move **bias estimate** shown by candle colour. No BUY/SELL markers.
- **Zones**: previous session's volume profile (POC, VAH, VAL, 2 HVNs, high, low). 2 resistance (R1, R2) above and 2 support (S1, S2)
  below the session **open**. Levels from 2–5 sessions back (`p2VAH`, `p3POC`...) fill gaps. Two closes beyond a zone = accepted through:
  it greys out at that bar and the next level on that side appears from the next bar. Hover a zone for source, touches, lifecycle, invalidation.
- **Candle colours**: strong/mild up (greens), neutral (grey), mild/strong down (reds), yellow = BB squeeze (expansion likely, direction unknown),
  orange = rejection risk at resistance, blue = rejection risk at support.
  Score (v1.4) = 0.75 move since session open (÷ ATR·√bars, intraday momentum) + 0.25 opening-range (first 15 min) position, EMA(3) smoothed. RSI / BB drive squeeze + rejection colours (EMA, RSI/%B added nothing for direction in tests).
- Zones are drawn for every past session (Zone History, default 100). Level Sources (default) also adds yesterday's floor pivots (P/R1/S1/R2/S2) and Fib retracements (38.2/50/61.8%); levels within one row are joined ("pVAL + Fib 50%"). When price is beyond every level of the last 5 days, dotted **FibExt** zones (127.2/161.8/200/261.8%… of yesterday's range, estimate) keep 2 levels each side.
- Every input has an ⓘ in Settings (script `input(..., tooltip=...)`).
- Hover text starts with a plain-English box: what happened, what may come next, when the idea is wrong.
- Table shows this chart's own track record: % of strong calls right 10 bars later (closed bars only).
- **Bubbles**: RVOL ≥ 2.5 **and** in the top 5% of the previous ~5 sessions, max 8 per session. RVOL = volume ÷ (30-bar level × time-of-day
  shape from the previous 10 sessions), so futures roll / rising volume doesn't flood the chart. Size grows with RVOL.
  Green/red = candle direction, purple = high volume with small body (possible absorption, estimate). Hover for the numbers.
- Causal: closed bars never change (replay test); forming bar is PROVISIONAL. No volume (Yahoo ^NSEI) → bubbles off, VWAP time-weighted.
- Backtest v1.2 (user's Breeze cache, no costs), strong calls right 10 bars later: NIFTY 52 days 56–63% (base ~50%),
  NIFTY FUT 18 days 51–61%, BANKNIFTY 22 days ~50% (no edge). Small sample: context, not a forecast.

## Mobile (`static/mobile.js`)
On phones (width ≤ 768 px, or a touch screen ≤ 500 px tall in landscape) the page switches to a touch layout. Desktop is unchanged: every rule is scoped to `body.m`.
- **Bottom tabs:** Chart · Watchlist · Indicators · Trade · More. Panels open as bottom sheets; tap outside or swipe the handle down to close. The top bar keeps the symbol, a timeframe button and the Breeze dot; everything else is under **More**.
- **Indicators:** ☆ favourites and a Recent group at the top of the list. Tap an indicator's name in the legend to open its settings, which have − / + steppers.
- **Drawing:** the ✎ button opens the tool bar. Tap the points (or drag) to place a drawing. A magnifier shows what is under your finger, and the weak magnet is on by default. Tap a drawing to get colour, lock, clone and delete at the bottom. Long-press the chart for the crosshair.
- **Paper trading:** big Sell / Buy buttons in the Trade sheet, − / + steppers in the ticket, and SL / target lines you can drag on the chart. A positions strip above the tabs shows live P&L. Swipe a trade left to exit; exits ask you to confirm. Simulated only.
- **Install as an app (PWA):** `manifest.webmanifest`, icons and `sw.js` (network-first for the page and `/static`, never `/api` or `/ws`). Browsers allow installing only over https or on localhost. With Tailscale, run on the server: `sudo tailscale serve --bg 8000` (once), then open `https://<machine>.<tailnet>.ts.net` and choose *Add to Home screen* / *Install app*. Add that host to `LTV_ALLOWED_HOSTS`.
- Screenshots: `docs/mobile/` (Pixel 7 and iPhone 13, portrait and landscape, dark and light).

## Watchlist
Live last price, change and % change (Breeze websocket; others polled). ＋ adds any symbol from any source, ✕ removes it.

## Indicator settings
⚙ on an indicator opens **Inputs** and **Style** tabs: per plot visibility, colour, width, line style, plot type
(line / step / histogram / area / circles); levels (value, colour, style); markers, price-scale labels,
plot names, status-line values/inputs, precision. **Defaults** resets everything.

## Symbols
| Source | Examples |
|---|---|
| ICICI Breeze `breeze` | `RELIANCE`, `TCS`, `NIFTY`, `CNXBAN` |
| Yahoo `yf` | `RELIANCE.NS`, `TCS.BO`, `^NSEI`, `^NSEBANK`, `AAPL`, `BTC-USD`, `INR=X` |
| NSE `nse` | `RELIANCE` (daily only) |
| Crypto `ccxt` | `BTC/USDT` (Binance) |
| Simulated `sim` | anything (offline testing) |

Yahoo intraday history limits: 1m = 7 days, 5m–30m = 60 days, 1h = 730 days.

## Custom indicator script
```python
indicator("EMA Cross", overlay=True)          # overlay=False -> own pane
fast = input("Fast", 9, min=1)                # shows up in Settings
slow = input("Slow", 21, min=1)
f, s = ema(close, fast), ema(close, slow)
plot(f, "Fast", color="#2962ff")
plot(s, "Slow", color="#ff6d00")              # style: line | step | area | histogram
plotshape(crossover(f, s), "Buy", position="below", shape="arrowUp", color="#26a69a", text="BUY")
hline(0, "Zero")
```
Available: `open high low close volume hl2 hlc3 ohlc4 df`, `sma ema rma wma hma stdev rsi macd bb highest lowest change nz crossover crossunder`,
`np pd math ta` (pandas-ta, 150+ indicators). Saved scripts live in `scripts/`, built-ins in `builtins/`.

## Layout
```
app.py              FastAPI: static UI, /api/scripts, /api/search, /ws (live chart socket)
core/session.py     per-chart session: history backfill, tick→bar aggregation, throttled indicator recompute
core/scripting.py   Python indicator runtime (Pine-like helpers)
core/data_sources.py yfinance / jugaad-data / ccxt / Alpha Vantage / CSV / sim
core/engine.py      prototype ring-buffer TimeSeries, BarSeries, incremental indicators
static/             index.html, app.js, style.css, vendor/lightweight-charts
```

## Security
Scripts are Python run on your machine. The server binds to 127.0.0.1 and the WebSocket rejects other web origins.
Imports are whitelisted, but it is not a sandbox: don't expose the app on a network.

## Paper trading (simulated, no broker orders)
**Trade** button / Shift + P / crosshair ＋ opens the ticket. **Option** tab (index or F&O stock): CE/PE, ATM/ITM/OTM ±N strikes on a 100 grid, expiry, lots × lot size; live premium from Breeze, market fills at ask (buy) / bid (sell). **Symbol** tab trades the chart symbol at its live price. Optional SL / target (points or price), limit entry, "Show on chart", auto-add option to watchlist.
Right rail **Paper trades** panel: capital (₹5,00,000 default, ⋯ → Set capital), equity, available, blocked, open/booked P&L, brokerage per order; Exit (market), Exit limit, SL/TGT edit, show/hide. Chart lines show entry/SL/target with live ₹ P&L (drag SL/target to move); option trades also show on the index at the entry spot.
Fills, SL/target hits and price alerts stay on screen until cleared (with confirmation). Triggers run while the app is open. Data: `data/paper/trades.json`, `data/paper/account.json`.
