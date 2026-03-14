# strategies

## Purpose

`strategies/` is the canonical runnable sample-strategy library for this repo. These strategies are showcase and coverage vehicles for the backtester surface. They are meant to demonstrate the execution, indicator, sizing, optimization, and reporting layers together rather than act as profit-seeking defaults.

## Available Strategies

- `EmaRsiTrendStrategy`
- `MacdAtrBreakoutStrategy`
- `BollingerZscoreReversionStrategy`
- `SmcPullbackStrategy`
- `IctOteSniperStrategy`
- `HybridRegimeStrategy`

## CLI Example

```powershell
python -m backtester.run_backtest `
  --csv-path oanda-candle-extractor\data\EUR_USD\candles_EUR_USD_H1.csv `
  --instrument EUR_USD `
  --timeframe H1 `
  --strategy-module strategies.ema_rsi_trend `
  --strategy-class EmaRsiTrendStrategy
```

## Real Report Example

```python
from pathlib import Path

from backtester.reporting import export_backtest_artifacts
from backtester.run_backtest import run_backtest
from strategies import EmaRsiTrendStrategy

csv_path = Path("oanda-candle-extractor") / "data" / "EUR_USD" / "candles_EUR_USD_H1.csv"
result = run_backtest(
    EmaRsiTrendStrategy,
    instrument="EUR_USD",
    timeframe="H1",
    csv_path=str(csv_path),
)
paths = export_backtest_artifacts(result, Path("artifacts"), run_label="phase10_demo")

print(paths["artifact_dir"])
print(paths["summary_json"])
print(paths["report_html"])
```
