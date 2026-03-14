# Backtester

`backtester/` is the repo's `backtrader`-based execution, analysis, optimization, and reporting package. It is designed to consume the canonical candle output from `oanda-candle-extractor/` instead of re-fetching market data itself.

If you are starting from the repo root, read [../README.md](../README.md) first. If you need the data-fetch side, use [../oanda-candle-extractor/README.md](../oanda-candle-extractor/README.md).

## Overview

This package currently provides:

- strict validation for the extractor's 14-column candle contract
- bid/ask-aware execution on top of `backtrader`
- a reusable `BaseStrategy`, signal helpers, and indicator wrappers (TA-Lib, scipy, SMC)
- a master-owned `instrument_api` exposing per-timeframe OHLCV, price bars, and built-in indicators
- same-instrument multi-timeframe context feeds via `run_backtest(..., context_data=...)`
- fixed-lot, risk-percent, Kelly, and volatility sizing modules
- performance analysis, optimization helpers, and report exporters

Phases 1-8, 11, and 12 are implemented and verified. See [Roadmap](#roadmap) for planned work.

The package does not fetch candles from OANDA directly. The extractor remains the historical data source.

## Current Scope

Hard limits for the current build:

- one strategy per run
- one instrument per run
- one primary execution timeframe per run
- optional higher-timeframe, same-instrument context feeds programmatically only
- no slippage modeling
- no commission modeling beyond configurable zero/default placeholders
- no partial fills
- no live order routing

The CLI is intentionally narrow. It runs one backtest from one CSV and requires an importable strategy module/class. There is no reporting CLI yet.

## Installation

From the repo root:

```powershell
python -m pip install -r backtester\requirements.txt
```

If you also need the extractor:

```powershell
python -m pip install -r oanda-candle-extractor\requirements.txt
```

### TA-Lib on Windows

`TA-Lib` is a real dependency of the current indicator layer. On Windows, the Python package sometimes fails if the native library is missing. If `python -m pip install -r backtester\requirements.txt` fails at `TA-Lib`, install a compatible wheel or native TA-Lib build for your Python version first, then rerun the requirements command.

## Data Contract

The backtester expects the extractor's canonical 14-column candle schema:

- `time`
- `open`, `high`, `low`, `close`
- `bid_open`, `bid_high`, `bid_low`, `bid_close`
- `ask_open`, `ask_high`, `ask_low`, `ask_close`
- `volume`

Persisted extractor CSV paths follow this pattern:

```text
oanda-candle-extractor\data\<INSTRUMENT>\candles_<INSTRUMENT>_<TIMEFRAME>.csv
```

Example:

```text
oanda-candle-extractor\data\EUR_USD\candles_EUR_USD_D.csv
```

Validation stays strict by design:

- timestamps must be UTC
- duplicate timestamps fail by default
- bid must not cross ask
- OHLC relationships must be internally valid

## Quickstart That Runs Today

Today, the only documented public strategy path that runs without adding your own module is programmatic. The repo does not yet contain a top-level `strategies/` package.

This example uses the checked-in extractor CSV at `oanda-candle-extractor\data\EUR_USD\candles_EUR_USD_D.csv`.

```powershell
@'
from pathlib import Path

import backtrader as bt

from backtester.run_backtest import run_backtest


class QuickstartStrategy(bt.Strategy):
    def next(self):
        if not self.position:
            self.buy(size=1)
        elif len(self) >= 3 and self.position:
            self.close()


result = run_backtest(
    QuickstartStrategy,
    instrument="EUR_USD",
    timeframe="D",
    csv_path=str(
        Path("oanda-candle-extractor")
        / "data"
        / "EUR_USD"
        / "candles_EUR_USD_D.csv"
    ),
)

print(result.strategy_name)
print(result.instrument, result.timeframe)
print(result.end_value)
print(result.order_ledger.tail(3)[["status_name", "executed_price"]])
print(result.trade_ledger.tail(3)[["status_name", "pnlcomm"]])
'@ | python -
```

Useful fields on `BacktestResult`:

- `result.order_ledger`
- `result.trade_ledger`
- `result.closed_trade_ledger`
- `result.equity_curve`
- `result.timeframe`
- `result.timeframes`
- `result.execution_policy`

## Instrument API

Each `run_backtest()` run creates one master-owned `InstrumentRuntime` attached as `self.instrument_api` on `BaseStrategy` subclasses. It exposes OHLCV history, price bars, built-in indicators, and batch snapshots per attached timeframe, with no-lookahead slicing and bar-local memoization.

```python
from backtester.strategy.base import BaseStrategy
from backtester.strategy.instrument_api import IndicatorRequest


class MyStrategy(BaseStrategy):
    def next(self):
        if not self.has_all_timeframes_ready():
            return

        # Single indicator
        rsi = self.instrument_api.indicator(None, "rsi", period=14)

        # Price bar (mid, bid, or ask)
        bar = self.instrument_api.price_bar(None, side="bid")

        # Batch snapshot
        snap = self.instrument_api.snapshot(None, [
            IndicatorRequest("sma", params={"period": 20}),
            IndicatorRequest("atr", params={"period": 14}),
        ])
```

Pass `None` as the timeframe to use the primary execution timeframe, or pass an explicit timeframe string (e.g., `"H4"`) for a context feed.

Built-in indicators: `sma`, `ema`, `rsi`, `macd`, `atr`, `adx`, `bollinger_bands`, `savgol_smooth`, `rolling_linreg_slope`, `rolling_zscore`, `swing_highs_lows`, `bos_choch`, `ob`, `liquidity`, `premium_discount`, `ict_fib`.

## Multi-Timeframe Support

`run_backtest()` accepts same-instrument higher-timeframe context feeds programmatically:

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

Key rules:

- Orders always execute on the primary feed; context feeds are read-only for signal and filter logic.
- Context feeds must be strictly higher timeframes for the same instrument.
- `BaseStrategy` exposes `has_all_timeframes_ready()`, `available_timeframes`, `data_for_timeframe()`, and timeframe-aware `instrument_api` methods.
- The CLI remains single-timeframe. Multi-timeframe is programmatic only.

## Fetch-to-Backtest Workflow

### Current executable path

1. Fetch candles with the extractor.
2. Point `run_backtest(...)` at the generated CSV.
3. Inspect the returned `BacktestResult`.
4. Export artifacts through `backtester.reporting`.

Example extractor command from the repo root:

```powershell
python oanda-candle-extractor\extract_candles.py --instrument XAU_USD --timeframes 1h --count 500
```

Example programmatic backtest against extracted output:

```python
from pathlib import Path

import backtrader as bt

from backtester.run_backtest import run_backtest


class MyStrategy(bt.Strategy):
    def next(self):
        pass


result = run_backtest(
    MyStrategy,
    instrument="XAU_USD",
    timeframe="H1",
    csv_path=str(
        Path("oanda-candle-extractor")
        / "data"
        / "XAU_USD"
        / "candles_XAU_USD_H1.csv"
    ),
)
```

### Future CLI path

This path depends on the Phase 10 `strategies/` library, which is not yet implemented.

```powershell
python -m backtester.run_backtest `
  --csv-path oanda-candle-extractor\data\XAU_USD\candles_XAU_USD_H1.csv `
  --instrument XAU_USD `
  --timeframe H1 `
  --strategy-module strategies.ema_rsi_trend `
  --strategy-class EmaRsiTrendStrategy
```

Treat any `strategies.<module>` example in Phase 8 docs as forward-looking only.

## Reporting

Reporting is library-only today.

Main public entry points:

- `backtester.reporting.export_backtest_artifacts`
- `backtester.reporting.export_optimization_artifacts`

Example:

```powershell
@'
from pathlib import Path

import backtrader as bt

from backtester.reporting import export_backtest_artifacts
from backtester.run_backtest import run_backtest


class ReportingDemo(bt.Strategy):
    def next(self):
        if not self.position:
            self.buy(size=1)
        elif len(self) >= 3 and self.position:
            self.close()


result = run_backtest(
    ReportingDemo,
    instrument="EUR_USD",
    timeframe="D",
    csv_path=str(
        Path("oanda-candle-extractor")
        / "data"
        / "EUR_USD"
        / "candles_EUR_USD_D.csv"
    ),
)

paths = export_backtest_artifacts(
    result,
    Path("artifacts"),
    run_label="phase8_readme_demo",
)

print(paths["artifact_dir"])
print(paths["summary_json"])
print(paths["report_html"])
'@ | python -
```

Expected outputs include:

- `summary.json`
- CSV ledgers and metrics tables
- PNG charts
- `report.html`

## Optimization

Optimization is also library-only today.

Main public entry points:

- `backtester.optimization.run_grid_search`
- `backtester.optimization.run_random_search`
- `backtester.optimization.run_scipy_optimization`

Minimal grid-search example:

```python
import backtrader as bt

from backtester.optimization import ParameterSpec, run_grid_search


class WindowStrategy(bt.Strategy):
    params = (("entry_bar", 1), ("exit_bar", 3))

    def next(self):
        if len(self) == int(self.p.entry_bar) and not self.position:
            self.buy(size=1)
        elif len(self) == int(self.p.exit_bar) and self.position:
            self.sell(size=1)


result = run_grid_search(
    WindowStrategy,
    instrument="EUR_USD",
    timeframe="D",
    csv_path="oanda-candle-extractor/data/EUR_USD/candles_EUR_USD_D.csv",
    search_space=[
        ParameterSpec("entry_bar", "int", grid_values=(1, 2)),
        ParameterSpec("exit_bar", "int", grid_values=(3, 4)),
    ],
    objective="total_return",
)

print(result.ranking().head())
```

If you need same-instrument multi-timeframe context, that remains programmatic through `context_data={"H4": <csv-path-or-dataframe>, ...}`.

## Relationship to a Future OANDA Bot

What should be reusable later:

- candle contract assumptions
- strategy signal logic
- sizing logic
- instrument metadata
- conservative execution assumptions as a baseline reference

What still needs new work later:

- live market data ingestion
- order submission and order rejection handling
- retry, latency, and connectivity policy
- account synchronization
- live risk controls and operational observability

The backtester and a future trading bot should share intent and assumptions where practical, but they are not the same runtime.

## Roadmap

### Planned phases

| Phase | Name | Status |
| ----- | ---- | ------ |
| 9 | Universe Candle Fetching and Instrument Coverage | Not started |
| 10 | Strategy Library and Samples | Not started |
| 13 | Repo Consolidation and Packaging | Not started |

**Phase 9** adds a batch fetcher for the fixed 11-instrument universe (10 FX pairs + XAU_USD) and explicit `InstrumentSpec` metadata for mixed price conventions. See [Phase 9 plan](../plans/backtester_phases/phase_9_universe_candle_fetching_and_instrument_coverage.md).

**Phase 10** adds a runnable `/strategies/` library with five sample strategies covering TA-Lib, scipy, SMC, all sizing modules, and all order types. See [Phase 10 plan](../plans/backtester_phases/phase_10_strategy_library_and_samples.md).

**Phase 13** is a repo consolidation pass covering `pyproject.toml` packaging, CI/CD, extractor import modernization, code quality tooling, and documentation consolidation. See [Phase 13 plan](../plans/backtester_phases/phase_13_repo_consolidation_and_packaging.md).

### Future work toward a live OANDA bot

Beyond the current phase set, the following capabilities are required before a live trading bot is viable. These are not yet scoped into numbered phases.

- **Multi-instrument backtesting**: run one strategy across multiple instruments in a single session.
- **Execution realism**: slippage modeling, commission modeling, partial fill simulation.
- **Live data ingestion**: real-time streaming from the OANDA API, replacing historical CSV input.
- **Live order management**: order submission, rejection handling, retry and connectivity policy, account synchronization.
- **Operational observability**: live risk controls, alerting, and monitoring dashboards.

## Verification Commands

From the repo root:

```powershell
python -m pytest tests\backtester -q
python -m backtester.run_backtest --help
python oanda-candle-extractor\extract_candles.py --help
```

See [project_checker.md](../plans/project_checker.md) for the full progress tracker.
