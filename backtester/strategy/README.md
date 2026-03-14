# backtester.strategy

## Purpose

`backtester.strategy` provides the reusable strategy layer: `BaseStrategy`, the master-owned `instrument_api`, `IndicatorRequest` snapshots, `PriceBar` helpers, and pure signal-check functions.

## Main Public APIs

- `BaseStrategy`
- `IndicatorRequest`
- `PriceBar`
- crossover, candle, and SMC-confluence signal helpers exported from `backtester.strategy`

## How To Use It

Subclass `BaseStrategy` when you want one-thesis order helpers, price-bar accessors, built-in indicator access, and optional higher-timeframe context feeds. Use the pure signal helpers when you want deterministic checks without touching broker state.

## Example

```python
from backtester.strategy import BaseStrategy, IndicatorRequest


class DemoStrategy(BaseStrategy):
    def next(self):
        if self.has_open_order():
            return

        snapshot = self.indicator_snapshot(
            None,
            [IndicatorRequest("ema", params={"period": 3}, alias="ema")],
        )
        if snapshot["ema"] is not None and self.is_flat():
            self.submit_long_market(size=1)
```

For a runnable public example, see `backtester.examples.InstrumentApiStrategy`.

## Command-Line Flags

None. Strategies are consumed by `python -m backtester.run_backtest`, but `backtester.strategy` itself has no CLI.
