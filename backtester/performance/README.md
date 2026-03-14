# backtester.performance

## Purpose

`backtester.performance` turns one or more normalized backtest results into metrics, warnings, summaries, and comparison tables.

## Main Public APIs

- `PerformanceAnalyzer`
- `PerformanceMetrics`
- `ComparisonRun`
- `PerformanceComparison`

## How To Use It

Use `PerformanceAnalyzer` for one completed run. Use `PerformanceComparison` when you want ranked or pairwise comparisons across multiple completed runs.

## Example

```python
from pathlib import Path

from backtester.examples import QuickstartStrategy
from backtester.performance import PerformanceAnalyzer
from backtester.run_backtest import run_backtest

csv_path = Path("oanda-candle-extractor") / "data" / "EUR_USD" / "candles_EUR_USD_D.csv"
result = run_backtest(
    QuickstartStrategy,
    instrument="EUR_USD",
    timeframe="D",
    csv_path=str(csv_path),
)

analyzer = PerformanceAnalyzer(result)
print(analyzer.summary()["metrics"]["total_return"])
print(analyzer.warnings())
```

## Command-Line Flags

None. `backtester.performance` is library-only.
