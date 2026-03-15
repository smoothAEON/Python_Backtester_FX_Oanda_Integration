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

Inside `run_backtest()`, strategy-visible feed time uses completed-bar semantics. Higher-timeframe context only unlocks after that bar has closed.

`instrument_api` is intentionally narrower than `backtester.indicators`: it exposes the runtime-safe indicator subset and rejects research-only helpers such as `savgol_smooth`, `swing_highs_lows`, `bos_choch`, `ob`, `liquidity`, `premium_discount`, `retracements`, and `ICTFibEngine`, which now live under `backtester.indicators.research`.

Repo-owned strategies also declare a runtime contract. `live_safe` is the default. Strategies marked `research_only` are rejected by `run_backtest()` unless the caller explicitly opts in with `allow_research_only=True` or `--allow-research-only`.

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
