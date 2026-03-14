# backtester.reporting

## Purpose

`backtester.reporting` exports completed backtest or optimization runs to JSON, CSV, PNG, and HTML artifacts.

## Main Public APIs

- `export_backtest_artifacts`
- `export_optimization_artifacts`
- `BacktestCharts`
- `build_backtest_json_payload`
- `build_optimization_json_payload`

## How To Use It

Run a backtest or optimization first, then pass the normalized result object into the export helpers. Each export call creates a timestamped artifact directory under the output root you provide.

## Example

```python
from pathlib import Path

from backtester.examples import QuickstartStrategy
from backtester.reporting import export_backtest_artifacts
from backtester.run_backtest import run_backtest

csv_path = Path("oanda-candle-extractor") / "data" / "EUR_USD" / "candles_EUR_USD_D.csv"
result = run_backtest(
    QuickstartStrategy,
    instrument="EUR_USD",
    timeframe="D",
    csv_path=str(csv_path),
)

paths = export_backtest_artifacts(result, Path("artifacts"), run_label="docs_demo")

print(paths["artifact_dir"])
print(paths["summary_json"])
print(paths["report_html"])
```

## Command-Line Flags

None. `backtester.reporting` is library-only.
