# backtester.data

## Purpose

`backtester.data` validates extractor-native candles, loads CSV or DataFrame input, and adapts the normalized frame into the custom `backtrader` feed used by the runner.

## Main Public APIs

- `REQUIRED_COLUMNS`
- `validate_oanda_dataframe`
- `OANDADataLoader`
- `OANDABidAskData`

## How To Use It

Use this package when you want to validate data before a run, load candles without running a strategy, or build your own `backtrader` session around the canonical OANDA schema.

## Example

```python
from pathlib import Path

from backtester.data import OANDADataLoader, REQUIRED_COLUMNS, validate_oanda_dataframe

csv_path = Path("oanda-candle-extractor") / "data" / "EUR_USD" / "candles_EUR_USD_D.csv"
loader = OANDADataLoader()
frame = loader.load_csv(str(csv_path))
validated = validate_oanda_dataframe(frame)

print(tuple(validated.columns) == tuple(REQUIRED_COLUMNS))
print(validated.index.tz)
print(validated[["open", "bid_close", "ask_close"]].head(2))
```

`OANDABidAskData` is usually created internally by `run_backtest`, but it is available if you need to assemble a custom `backtrader` runner.

## Command-Line Flags

None. `backtester.data` is library-only.
