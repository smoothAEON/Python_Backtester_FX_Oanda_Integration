# strategies

## Purpose

`strategies/` is the canonical runnable sample-strategy library for this repo. These strategies are showcase and coverage vehicles for the backtester surface, and this package now exports only the public `live_safe` variants.

## Available Strategies

`live_safe`:

- `BollingerZscoreReversionStrategy`
- `EmaRsiTrendStrategy`
- `HybridRegimeStrategy`
- `IctOteSniperStrategy`
- `MacdAtrBreakoutStrategy`
- `SmcPullbackStrategy`

`research_only`:

- `strategies.research.BollingerZscoreReversionStrategy`
- `strategies.research.SmcPullbackStrategy`
- `strategies.research.IctOteSniperStrategy`
- `strategies.research.HybridRegimeStrategy`

The default `python -m backtester.walk_forward` audit matrix includes only the `live_safe` strategies. `run_backtest()` rejects `research_only` strategies unless you pass `--allow-research-only` or `allow_research_only=True`. Use `strategies.research` only for offline comparison against the preserved pre-rewrite implementations.

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
