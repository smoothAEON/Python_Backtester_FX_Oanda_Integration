# backtester.examples

## Purpose

`backtester.examples` provides a small set of importable strategies used by the documentation and tests. These classes are public and runnable today, but they are intentionally minimal.

## Available Example Strategies

- `QuickstartStrategy`: minimal runner and CLI example
- `WindowStrategy`: parameterized example for optimization docs
- `InstrumentApiStrategy`: `BaseStrategy` example using `indicator_snapshot()` and `price_bar()`

## How To Use It

Use these strategies directly in `run_backtest()` or point the CLI at the package.

## Example

```powershell
python -m backtester.run_backtest `
  --csv-path oanda-candle-extractor\data\EUR_USD\candles_EUR_USD_D.csv `
  --instrument EUR_USD `
  --timeframe D `
  --strategy-module backtester.examples `
  --strategy-class QuickstartStrategy
```

Programmatic import:

```python
from backtester.examples import InstrumentApiStrategy, QuickstartStrategy, WindowStrategy
```

This package exists to support runnable docs. It is not the future Phase 10 strategy library.

## Command-Line Flags

None. `backtester.examples` has no standalone CLI; it is consumed through `python -m backtester.run_backtest`.
