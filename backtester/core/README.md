# backtester.core

## Purpose

`backtester.core` contains the low-level execution pieces behind a run: the `Cerebro` builder, the bid/ask-aware broker, the execution model, and the normalized `BacktestResult`.

## Main Public APIs

- `build_cerebro`
- `BidAskBroker`
- `ExecutionModel`
- `BacktestResult`

## How To Use It

Most callers should enter through `backtester.run_backtest`. Use `backtester.core` directly when you need custom runner wiring, broker-level inspection, or direct access to normalized result data.

## Example

```python
from pathlib import Path

from backtester.core import BacktestResult
from backtester.examples import QuickstartStrategy
from backtester.run_backtest import run_backtest

csv_path = Path("oanda-candle-extractor") / "data" / "EUR_USD" / "candles_EUR_USD_D.csv"
result = run_backtest(
    QuickstartStrategy,
    instrument="EUR_USD",
    timeframe="D",
    csv_path=str(csv_path),
)

assert isinstance(result, BacktestResult)
print(result.execution_policy["same_bar_policy"])
print(result.order_ledger.tail(2)[["status_name", "executed_price"]])
```

## Command-Line Flags

None. `backtester.core` has no CLI. Use `python -m backtester.run_backtest` for command-line runs.
