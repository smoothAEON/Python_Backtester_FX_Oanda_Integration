# Backtester

`backtester/` is the repo's `backtrader`-based execution, analysis, optimization, and reporting package. It consumes extractor-native CSV or DataFrame input and keeps execution assumptions centralized and deterministic.

If you are starting from the repo root, read [../README.md](../README.md) first. For the data-fetch side, use [../oanda-candle-extractor/README.md](../oanda-candle-extractor/README.md).

## What Is Here

- one importable runner: `backtester.run_backtest.run_backtest()`
- one CLI: `python -m backtester.run_backtest`
- strict loader and validation support for the extractor's 14-column candle contract
- bid/ask-aware execution on top of `backtrader`
- USD-account FX valuation with explicit `point_value` metadata and leverage-aware margin usage
- reusable strategy helpers, built-in indicators, position sizers, performance analysis, optimization, and reporting
- a small public [`examples/`](examples/README.md) package for runnable documentation examples

The package does not fetch candles from OANDA directly. Use the extractor first, then point the backtester at the resulting CSV.

## Package Map

- [API_INDEX.md](API_INDEX.md): public classes, functions, and module paths
- [core/README.md](core/README.md): broker, execution model, result normalization
- [data/README.md](data/README.md): schema validation, CSV/DataFrame loading, feed adapter
- [strategy/README.md](strategy/README.md): `BaseStrategy`, `instrument_api`, signal helpers
- [indicators/README.md](indicators/README.md): TA-Lib, scipy, and SMC wrappers
- [sizing/README.md](sizing/README.md): fixed-lot, risk-percent, Kelly, volatility sizing
- [performance/README.md](performance/README.md): metrics, summaries, run comparison
- [optimization/README.md](optimization/README.md): grid, random, and scipy search
- [reporting/README.md](reporting/README.md): JSON, CSV, chart, and HTML artifact export
- [examples/README.md](examples/README.md): importable strategies used by the docs

## Install

From the repo root:

```powershell
python -m pip install -r backtester\requirements.txt
```

If you also need candle extraction:

```powershell
python -m pip install -r oanda-candle-extractor\requirements.txt
```

### TA-Lib on Windows

`TA-Lib` is a real dependency of the current indicator layer. If installation fails on Windows, install a compatible native build or wheel for your Python version first, then rerun the requirements command.

## Common Example Dataset

All README examples use the checked-in extractor CSV:

```text
oanda-candle-extractor/data/EUR_USD/candles_EUR_USD_D.csv
```

That file already matches the required 14-column schema:

- `time`
- `open`, `high`, `low`, `close`
- `bid_open`, `bid_high`, `bid_low`, `bid_close`
- `ask_open`, `ask_high`, `ask_low`, `ask_close`
- `volume`

Validation stays strict by design: UTC timestamps only, duplicate timestamps fail by default, bid must not cross ask, and OHLC relationships must remain internally valid.

## Quickstart

Programmatic run:

```powershell
@'
from pathlib import Path

from backtester.examples import QuickstartStrategy
from backtester.run_backtest import run_backtest

csv_path = Path("oanda-candle-extractor") / "data" / "EUR_USD" / "candles_EUR_USD_D.csv"

result = run_backtest(
    QuickstartStrategy,
    instrument="EUR_USD",
    timeframe="D",
    csv_path=str(csv_path),
)

print(result.strategy_name)
print(result.instrument, result.timeframe)
print(result.end_value)
print(result.order_ledger.tail(3)[["status_name", "executed_price"]])
'@ | python -
```

Useful result surfaces:

- `result.order_ledger`
- `result.trade_ledger`
- `result.closed_trade_ledger`
- `result.equity_curve`
- `result.timeframe`
- `result.timeframes`
- `result.execution_policy`

## CLI Usage

The only backtester CLI today is:

```powershell
python -m backtester.run_backtest --help
```

Runnable example using the public docs package:

```powershell
python -m backtester.run_backtest `
  --csv-path oanda-candle-extractor\data\EUR_USD\candles_EUR_USD_D.csv `
  --instrument EUR_USD `
  --timeframe D `
  --strategy-module backtester.examples `
  --strategy-class QuickstartStrategy
```

Available CLI flags:

| Flag | Required | Description |
| ---- | -------- | ----------- |
| `--csv-path` | yes | Path to an extractor-native CSV file |
| `--instrument` | yes | Instrument name such as `EUR_USD` or `XAU_USD` |
| `--timeframe` | yes | Timeframe label such as `H1`, `H4`, or `D` |
| `--strategy-module` | yes | Import path for the strategy module or package |
| `--strategy-class` | yes | Strategy class name inside that module |
| `--cash` | no | Starting account value. Default: `10000.0` |
| `--strategy-param` | no | Repeatable `key=value` strategy parameter override |

Notes:

- only `backtester.run_backtest` has CLI flags today
- optimization, reporting, indicators, performance, sizing, and data helpers are library-only
- multi-timeframe support remains programmatic only

## Configuration Surfaces

`config.py` is documented here instead of getting its own README because it is a single-module support surface.

Main types:

- `BacktestConfig`: top-level settings for a run
- `ExecutionConfig`: execution assumptions such as `same_bar_policy` and `leverage`
- `InstrumentSpec`: per-instrument sizing and valuation metadata, including `point_value`
- `resolve_instrument_spec()`: conservative FX defaults plus explicit 16-instrument Phase 9 overrides with `pip_size`, `display_precision`, `price_step`, and `point_value`

Current valuation assumes a USD account. Non-USD account conversion is out of scope.

Minimal example:

```python
from backtester.config import BacktestConfig, ExecutionConfig, resolve_instrument_spec

config = BacktestConfig(
    cash=25_000.0,
    execution=ExecutionConfig(
        same_bar_policy="worst_case_first",
        leverage=20.0,
    ),
)
spec = resolve_instrument_spec("EUR_USD")

print(config.cash)
print(config.execution.leverage)
print(spec.instrument, spec.pip_size, spec.display_precision, spec.price_step, spec.point_value)
```

## Multi-Timeframe Support

`run_backtest()` accepts same-instrument higher-timeframe context feeds programmatically:

```python
from backtester.examples import InstrumentApiStrategy
from backtester.run_backtest import run_backtest

result = run_backtest(
    InstrumentApiStrategy,
    instrument="EUR_USD",
    timeframe="H1",
    csv_path="oanda-candle-extractor/data/EUR_USD/candles_EUR_USD_H1.csv",
    context_data={
        "H4": "oanda-candle-extractor/data/EUR_USD/candles_EUR_USD_H4.csv",
    },
)
```

Key rules:

- orders execute only on the primary feed
- context feeds are read-only and must be strictly higher timeframes
- the CLI does not expose `context_data`

## Examples Package

The public docs package lives in [`backtester/examples/`](examples/README.md).

It currently provides:

- `QuickstartStrategy`: minimal runner and CLI example
- `WindowStrategy`: parameterized strategy for optimization examples
- `InstrumentApiStrategy`: `BaseStrategy` example using `instrument_api`

This package exists to make the docs runnable. It is not a replacement for the planned Phase 10 strategy library.

## Verification

From the repo root:

```powershell
python -m pytest tests\backtester -q
python -m backtester.run_backtest --help
```
