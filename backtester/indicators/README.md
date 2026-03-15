# backtester.indicators

## Purpose

`backtester.indicators` is the live-safe indicator namespace. It exposes TA-Lib wrappers, safe scipy helpers, and causal SMC helpers that remain valid inside the runtime contract. Research-only helpers live in `backtester.indicators.research`.

## Main Public APIs

- Live-safe exports: `sma`, `ema`, `rsi`, `macd`, `atr`, `bollinger_bands`, `adx`, `rolling_linreg_slope`, `rolling_zscore`, `confirmed_swings`, `confirmed_structure`, `confirmed_order_blocks`, `confirmed_liquidity`, `confirmed_premium_discount`, `confirmed_retracements`, `CausalICTFibEngine`, `previous_high_low`, `sessions`
- Research-only exports from `backtester.indicators.research`: `savgol_smooth`, `swing_highs_lows`, `bos_choch`, `ob`, `liquidity`, `premium_discount`, `retracements`, `ICTFibEngine`

## How To Use It

Use `backtester.indicators` directly on pandas Series/DataFrames when you want helpers that remain inside the live-safe runtime contract. Use `backtester.indicators.research` only for offline research and quarantined tests.

`BaseStrategy.instrument_api` exposes only the runtime-safe subset. The causal helpers above remain available through that path. `savgol_smooth`, `swing_highs_lows`, `bos_choch`, `ob`, `liquidity`, `premium_discount`, `retracements`, and `ICTFibEngine` are intentionally excluded because they repaint or depend on future confirmation. `previous_high_low` and `sessions` remain available through `instrument_api` after the runner normalizes feed time to completed bars.

## Example

```python
from pathlib import Path

from backtester.data import OANDADataLoader
from backtester.indicators import ema, rolling_zscore

csv_path = Path("oanda-candle-extractor") / "data" / "EUR_USD" / "candles_EUR_USD_D.csv"
frame = OANDADataLoader().load_csv(str(csv_path))

ema_series = ema(frame["close"], period=5)
zscore_series = rolling_zscore(frame["close"], window=10)

print(ema_series.tail(3))
print(zscore_series.tail(3))
```

If you call `previous_high_low` or `sessions`, `smartmoneyconcepts` will be imported lazily at that point. The causal helpers are repo-owned and live-safe. Research-only SMC helpers still require `backtester.indicators.research`.

## Command-Line Flags

None. `backtester.indicators` is library-only.
