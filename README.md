# OANDA Backtester

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![OANDA](https://img.shields.io/badge/OANDA-v20%20API-1A1A2E?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iMTAiIGZpbGw9IiMwMEE2NUUiLz48L3N2Zz4=)
![backtrader](https://img.shields.io/badge/backtrader-engine-blue)
![pandas](https://img.shields.io/badge/pandas-data-150458?logo=pandas&logoColor=white)
![TA-Lib](https://img.shields.io/badge/TA--Lib-indicators-orange)
![scipy](https://img.shields.io/badge/scipy-math-8CAAE6?logo=scipy&logoColor=white)
![matplotlib](https://img.shields.io/badge/matplotlib-charts-11557C)
![License](https://img.shields.io/badge/license-private-lightgrey)

A deterministic, bid/ask-aware backtesting system built on **backtrader** for OANDA forex and commodity instruments. Fetch historical candles via the OANDA v20 API, validate them against a strict 14-column schema, and run strategy backtests with optimization, sizing, and reporting.

> **Long-term goal:** build the backtester first, then reuse its data model, strategy logic, and execution assumptions for a future live OANDA trading bot.

## Features

- **Bid/ask-aware execution**: buys fill on ask candles, sells fill on bid candles.
- **14-column candle contract**: strict validation for mid, bid, and ask OHLCV data.
- **Multi-timeframe support**: same-instrument higher-timeframe context feeds for signal and filter logic.
- **Indicator library**: live-safe TA-Lib/scipy/time-aware helpers in `backtester.indicators`, including causal SMC helpers such as `confirmed_swings` and `CausalICTFibEngine`, plus quarantined research-only helpers in `backtester.indicators.research`.
- **Position sizing**: fixed-lot, risk-percent, Kelly criterion, and volatility-based sizing.
- **Optimization**: grid search, random search, and scipy-based optimization with explicit out-of-sample ranking support.
- **Walk-forward audit CLI**: repo-owned `backtester.walk_forward` runner for the Phase 10 H4 matrix with 960/480/160/160/160 expanding windows, widened grids, sizing validation, and execution anomaly reporting.
- **Reporting**: JSON, CSV, HTML reports with matplotlib charts.
- **Rate-limited extraction**: single-instrument and fixed-universe batch CLIs with gap-only date-range fetching, transient retry hardening, and atomic CSV caching.

## Project Structure

```text
oanda-candle-extractor/     # Fetches and persists OANDA candles
backtester/                 # backtrader-based backtesting engine
  core/                     #   Cerebro builder, broker, result normalization
  data/                     #   Schema validation, CSV/DataFrame loader, feed
  strategy/                 #   BaseStrategy, signal helpers, instrument API
  indicators/               #   Live-safe indicators plus causal/research SMC helper layers
  sizing/                   #   Pluggable position sizing modules
  performance/              #   Metrics, analysis, and run comparison
  optimization/             #   Grid, random, and scipy optimizers
  reporting/                #   JSON, CSV, HTML, and chart exporters
  examples/                 #   Public example strategies used by the docs
strategies/                 # Canonical runnable live-safe strategy library
tests/                      # pytest suites for backtester and extractor
plans/                      # Phase plans and progress tracker
```

## Quick Start

### Install

```bash
python -m pip install -r backtester/requirements.txt
python -m pip install -r oanda-candle-extractor/requirements.txt
```

### Fetch candles

```bash
python oanda-candle-extractor/extract_candles.py --instrument XAU_USD --timeframes 1h --count 500
python oanda-candle-extractor/fetch_universe.py
```

Requires `OANDA_API_KEY` and `OANDA_ACCOUNT_ID` in the environment or in `oanda-candle-extractor/.env`.

### Run a backtest

```python
from strategies import EmaRsiTrendStrategy
from backtester.run_backtest import run_backtest

result = run_backtest(
    EmaRsiTrendStrategy,
    instrument="EUR_USD",
    timeframe="D",
    csv_path="oanda-candle-extractor/data/EUR_USD/candles_EUR_USD_D.csv",
)

print(f"{result.strategy_name}: {result.end_value:.2f}")
print(result.closed_trade_ledger[["direction", "net_pnl"]].tail())
```

### Run via CLI

```bash
python -m backtester.run_backtest \
  --csv-path oanda-candle-extractor/data/EUR_USD/candles_EUR_USD_D.csv \
  --instrument EUR_USD \
  --timeframe D \
  --strategy-module strategies.ema_rsi_trend \
  --strategy-class EmaRsiTrendStrategy
```

### Run the Phase 10 walk-forward audit

```bash
python -m backtester.walk_forward --repo-root .
```

This runner uses local extractor CSVs only. By default it evaluates only the `live_safe` Phase 10 strategies on `H4` using the last `960` completed bars per instrument, expanding `480/160/160/160` folds, `20000` USD starting cash, and leverage `30`. Legacy research variants remain available under `strategies.research` for offline comparison only. `EmaRsiTrendStrategy` keeps `fixed_units=None` instrument-aware here: `1000.0` on the covered FX pairs and `1.0` on `XAU_USD`.

### Run tests

```bash
python -m pytest tests/backtester -q
python -m pytest tests/extractor -q
```

## Multi-Timeframe

Add same-instrument higher-timeframe context feeds for signal and filter logic:

```python
result = run_backtest(
    MyStrategy,
    instrument="EUR_USD",
    timeframe="H1",
    csv_path="oanda-candle-extractor/data/EUR_USD/candles_EUR_USD_H1.csv",
    context_data={
        "H4": "oanda-candle-extractor/data/EUR_USD/candles_EUR_USD_H4.csv",
    },
)
```

Orders always execute on the primary feed. Context feeds are read-only, and higher-timeframe rows only become visible after their completed bar time inside `run_backtest()`.

## Optimization

```python
from backtester.optimization import ParameterSpec, run_grid_search

result = run_grid_search(
    MyStrategy,
    instrument="EUR_USD",
    timeframe="D",
    csv_path="oanda-candle-extractor/data/EUR_USD/candles_EUR_USD_D.csv",
    holdout_fraction=0.25,
    search_space=[
        ParameterSpec("entry_bar", "int", grid_values=(1, 2, 3)),
        ParameterSpec("exit_bar", "int", grid_values=(4, 5, 6)),
    ],
    objective="total_return",
)

print(result.ranking().head())
```

`OptimizationResult.ranking()` and `best_trial()` require an out-of-sample score by default. Use `holdout_fraction` or explicit `evaluation_*` inputs for deployable rankings, or pass `allow_in_sample=True` only for diagnostic inspection.

For the built-in Phase 10 expanding-window matrix, use `python -m backtester.walk_forward` instead of an ad hoc temp script.

## Reporting

```python
from pathlib import Path

from backtester.reporting import export_backtest_artifacts
from backtester.run_backtest import run_backtest
from strategies import EmaRsiTrendStrategy

result = run_backtest(
    EmaRsiTrendStrategy,
    instrument="EUR_USD",
    timeframe="D",
    csv_path="oanda-candle-extractor/data/EUR_USD/candles_EUR_USD_D.csv",
)
paths = export_backtest_artifacts(result, Path("artifacts"), run_label="my_run")
```

## Data Contract

The backtester expects the extractor's canonical 14-column CSV:

| Column | Description |
| ------ | ----------- |
| `time` | Raw extractor/OANDA UTC bar-start timestamp |
| `open`, `high`, `low`, `close` | Mid-price OHLC |
| `bid_open`, `bid_high`, `bid_low`, `bid_close` | Bid-price OHLC |
| `ask_open`, `ask_high`, `ask_low`, `ask_close` | Ask-price OHLC |
| `volume` | Tick volume |

CSV path convention: `oanda-candle-extractor/data/<INSTRUMENT>/candles_<INSTRUMENT>_<TIMEFRAME>.csv`

`run_backtest()` keeps extractor files unchanged and normalizes these raw bar-start timestamps to completed-bar time internally before building feeds, so backtest ledgers, higher-timeframe visibility, and equity curves are timestamped at bar completion.

## Roadmap

| Phase | Name | Status |
| ----- | ---- | ------ |
| 1-8 | Foundation through documentation | Done |
| 9 | Universe candle fetching | Done |
| 10 | Strategy library and samples | Done |
| 11 | Multi-timeframe backtesting | Done |
| 12 | Master-owned instrument API | Done |
| 13 | Repo consolidation and packaging | Planned |

See [plans/](plans/) for detailed phase docs and [plans/project_checker.md](plans/project_checker.md) for the progress tracker.

## Documentation

| Document | Purpose |
| -------- | ------- |
| [Backtester README](backtester/README.md) | Workflow guide, CLI flags, config notes, and component links |
| [Backtester API Index](backtester/API_INDEX.md) | Public class/function import paths |
| [Strategy Library README](strategies/README.md) | Canonical runnable sample strategies and real report-export example |
| [fixbug.md](fixbug.md) | Current integrity memo superseding stale live-safety conclusions in the old audit |
| [Extractor README](oanda-candle-extractor/README.md) | Extraction usage, rate limiting, and configuration |
| [Master Plan](plans/backtester_plan.md) | Architecture and dependency plan |
| [Phase Breakdown](plans/backtester_phases/) | Detailed phase specifications |
| [Repo Audit](plans/phase8_repo_audit.md) | Phase 8 verification baseline |
