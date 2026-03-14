# backtester.optimization

## Purpose

`backtester.optimization` runs parameter searches on top of `run_backtest()` and returns an `OptimizationResult` with trials, ranking, warnings, and metadata.

## Main Public APIs

- `ParameterSpec`
- `run_grid_search`
- `run_random_search`
- `run_scipy_optimization`
- `OptimizationResult`

## How To Use It

Use this package when a strategy exposes tunable parameters and you want deterministic ranking against a named objective such as `total_return` or `calmar_ratio`.

## Example

```python
from pathlib import Path

from backtester.examples import WindowStrategy
from backtester.optimization import ParameterSpec, run_grid_search

csv_path = Path("oanda-candle-extractor") / "data" / "EUR_USD" / "candles_EUR_USD_D.csv"
result = run_grid_search(
    WindowStrategy,
    instrument="EUR_USD",
    timeframe="D",
    csv_path=str(csv_path),
    search_space=[
        ParameterSpec("entry_bar", "int", grid_values=(2, 3)),
        ParameterSpec("exit_bar", "int", grid_values=(5, 6)),
    ],
    objective="total_return",
)

print(result.ranking().head())
```

If you need higher-timeframe context, pass `context_data={"H4": <csv-path-or-dataframe>}` programmatically.

## Command-Line Flags

None. `backtester.optimization` is library-only.
