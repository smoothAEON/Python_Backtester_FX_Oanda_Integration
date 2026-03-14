# backtester.optimization

## Purpose

`backtester.optimization` runs parameter searches on top of `run_backtest()` and returns an `OptimizationResult` with trials, warnings, metadata, and out-of-sample ranking when evaluation data is configured.

## Main Public APIs

- `ParameterSpec`
- `run_grid_search`
- `run_random_search`
- `run_scipy_optimization`
- `OptimizationResult`

## How To Use It

Use this package when a strategy exposes tunable parameters and you want deterministic search against a named objective such as `total_return` or `calmar_ratio`.

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
    holdout_fraction=0.25,
    search_space=[
        ParameterSpec("entry_bar", "int", grid_values=(2, 3)),
        ParameterSpec("exit_bar", "int", grid_values=(5, 6)),
    ],
    objective="total_return",
)

print(result.ranking().head())
```

If you need higher-timeframe context, pass `context_data={"H4": <csv-path-or-dataframe>}` programmatically.
If you need cross-currency account conversion, pass `conversion_data={"GBP_USD": <csv-path-or-dataframe>}` programmatically.

## Ranking Rules

- `OptimizationResult.ranking()` and `best_trial()` require out-of-sample evaluation by default.
- Use `holdout_fraction=...` for a contiguous train/evaluation split on one dataset.
- Or pass `evaluation_csv_path` / `evaluation_dataframe` plus optional `evaluation_context_data` and `evaluation_conversion_data`.
- If you only need diagnostic inspection of in-sample search scores, call `ranking(allow_in_sample=True)` or `best_trial(allow_in_sample=True)`.

## Command-Line Flags

None. `backtester.optimization` is library-only.
