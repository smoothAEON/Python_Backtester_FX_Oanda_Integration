# backtester.indicators

## Purpose

`backtester.indicators` wraps TA-Lib, scipy, and Smart Money Concepts helpers behind one import surface. TA-Lib and scipy wrappers are imported eagerly. SMC-backed helpers are loaded lazily when first used.

## Main Public APIs

- TA-Lib wrappers: `sma`, `ema`, `rsi`, `macd`, `atr`, `bollinger_bands`, `adx`
- scipy wrappers: `savgol_smooth`, `rolling_linreg_slope`, `rolling_zscore`
- SMC helpers: `swing_highs_lows`, `bos_choch`, `ob`, `liquidity`, `premium_discount`, `previous_high_low`, `sessions`, `retracements`, `ICTFibEngine`

## How To Use It

Use these helpers directly on pandas Series/DataFrames. The direct wrappers are useful for research notebooks, offline analysis, and deterministic unit tests.

`BaseStrategy.instrument_api` exposes only the runtime-safe subset. `savgol_smooth`, `swing_highs_lows`, `bos_choch`, `ob`, `liquidity`, `premium_discount`, `retracements`, and `ICTFibEngine` remain importable here for offline research, but are rejected from `instrument_api` because they repaint or depend on future confirmation. `previous_high_low` and `sessions` remain available through `instrument_api` after the runner normalizes feed time to completed bars.

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

If you call an SMC helper, `smartmoneyconcepts` will be imported at that point.

## Command-Line Flags

None. `backtester.indicators` is library-only.
