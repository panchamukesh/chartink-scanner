# MarketScan Pro

A self-contained Chartink-style stock scanning workspace for NSE-style equities.

## Features

- Market dashboard with breadth, movers, and summary stats
- Visual scan builder with configurable conditions
- Formula scan mode with `and` / `or`, numeric comparisons, text `contains`, and field-to-field comparisons
- Saved scans with local browser storage
- Alert monitor based on saved scans, including optional browser notifications
- Watchlist
- Price chart and stock snapshot
- CSV import and scan-result export
- Simulated price refresh for testing alert behavior
- Pine Script upload, conversion into scanner filters, and recommendation ranking

## Run

Open `index.html` in a browser. No build or install step is required.

## CSV Fields

The importer accepts columns such as:

`symbol,name,sector,open,close,high,low,changePct,volume,avgVolume,rsi,ema20,ema50,delivery,pe,resistance`

## Pine Script Import

Upload `.pine`, `.pinescript`, or `.txt` scripts from the Import Pine button. The converter handles common scanner-friendly Pine logic such as RSI, EMA/SMA 20/50, volume average checks, `crossover`, `crossunder`, `and`, `or`, and simple price comparisons.

TradingView-only behavior such as `strategy.entry`, `request.security`, drawing objects, loops, arrays, and bar-by-bar state cannot be perfectly converted into a stock screener filter, so the app shows conversion confidence and notes.
