# Backtester API Index

This index maps the current public backtester surfaces to their module paths.

## Root Package

`run_backtest()` keeps extractor-native inputs unchanged on disk, but normalizes feed and result timestamps to completed-bar time during a run. Entry rows in `BacktestResult.order_ledger` also retain sizing metadata, including `sizing_entry_price`, for audit and FX-rate recomputation.

| Symbol | Import Path |
| ------ | ----------- |
| `BaseStrategy` | `backtester.BaseStrategy` |
| `BacktestConfig` | `backtester.BacktestConfig` |
| `BacktestResult` | `backtester.BacktestResult` |
| `ExecutionConfig` | `backtester.ExecutionConfig` |
| `run_backtest` | `backtester.run_backtest.run_backtest` |

## Config

Relevant current fields: `ExecutionConfig.leverage` controls leveraged notional-margin simulation. `InstrumentSpec.point_value` is only constant when the quote currency already matches the USD account; otherwise runtime conversion is dynamic.

| Symbol | Import Path |
| ------ | ----------- |
| `BacktestConfig` | `backtester.config.BacktestConfig` |
| `ExecutionConfig` | `backtester.config.ExecutionConfig` |
| `InstrumentSpec` | `backtester.config.InstrumentSpec` |
| `resolve_instrument_spec` | `backtester.config.resolve_instrument_spec` |

## Core

| Symbol | Import Path |
| ------ | ----------- |
| `BacktestResult` | `backtester.core.BacktestResult` |
| `BidAskBroker` | `backtester.core.BidAskBroker` |
| `ExecutionModel` | `backtester.core.ExecutionModel` |
| `build_cerebro` | `backtester.core.build_cerebro` |

## Data

| Symbol | Import Path |
| ------ | ----------- |
| `OANDADataLoader` | `backtester.data.OANDADataLoader` |
| `OANDABidAskData` | `backtester.data.OANDABidAskData` |
| `REQUIRED_COLUMNS` | `backtester.data.REQUIRED_COLUMNS` |
| `validate_oanda_dataframe` | `backtester.data.validate_oanda_dataframe` |

## Strategy

| Symbol | Import Path |
| ------ | ----------- |
| `BaseStrategy` | `backtester.strategy.BaseStrategy` |
| `IndicatorRequest` | `backtester.strategy.IndicatorRequest` |
| `PriceBar` | `backtester.strategy.PriceBar` |
| `crossed_above` | `backtester.strategy.crossed_above` |
| `crossed_below` | `backtester.strategy.crossed_below` |
| `candle_closes_above_level` | `backtester.strategy.candle_closes_above_level` |
| `candle_closes_below_level` | `backtester.strategy.candle_closes_below_level` |
| `is_bullish_candle` | `backtester.strategy.is_bullish_candle` |
| `is_bearish_candle` | `backtester.strategy.is_bearish_candle` |
| `structure_bias` | `backtester.strategy.structure_bias` |
| `is_discount` | `backtester.strategy.is_discount` |
| `is_equilibrium` | `backtester.strategy.is_equilibrium` |
| `is_premium` | `backtester.strategy.is_premium` |
| `smc_bullish_confluence` | `backtester.strategy.smc_bullish_confluence` |
| `smc_bearish_confluence` | `backtester.strategy.smc_bearish_confluence` |

## Indicators

`backtester.indicators` is the live-safe indicator surface. Research-only helpers live under `backtester.indicators.research` and are outside the default runtime contract.

| Symbol | Import Path |
| ------ | ----------- |
| `sma` | `backtester.indicators.sma` |
| `ema` | `backtester.indicators.ema` |
| `rsi` | `backtester.indicators.rsi` |
| `macd` | `backtester.indicators.macd` |
| `atr` | `backtester.indicators.atr` |
| `adx` | `backtester.indicators.adx` |
| `bollinger_bands` | `backtester.indicators.bollinger_bands` |
| `rolling_linreg_slope` | `backtester.indicators.rolling_linreg_slope` |
| `rolling_zscore` | `backtester.indicators.rolling_zscore` |
| `confirmed_swings` | `backtester.indicators.confirmed_swings` |
| `confirmed_structure` | `backtester.indicators.confirmed_structure` |
| `confirmed_order_blocks` | `backtester.indicators.confirmed_order_blocks` |
| `confirmed_liquidity` | `backtester.indicators.confirmed_liquidity` |
| `confirmed_premium_discount` | `backtester.indicators.confirmed_premium_discount` |
| `confirmed_retracements` | `backtester.indicators.confirmed_retracements` |
| `CausalICTFibEngine` | `backtester.indicators.CausalICTFibEngine` |
| `previous_high_low` | `backtester.indicators.previous_high_low` |
| `sessions` | `backtester.indicators.sessions` |

## Research Indicators

These helpers are available for offline research only. Repo-owned strategies that depend on them must be marked `research_only`, and `run_backtest()` rejects them unless `allow_research_only=True`. Preserved research strategies live under `strategies.research`.

| Symbol | Import Path |
| ------ | ----------- |
| `savgol_smooth` | `backtester.indicators.research.savgol_smooth` |
| `swing_highs_lows` | `backtester.indicators.research.swing_highs_lows` |
| `bos_choch` | `backtester.indicators.research.bos_choch` |
| `ob` | `backtester.indicators.research.ob` |
| `liquidity` | `backtester.indicators.research.liquidity` |
| `premium_discount` | `backtester.indicators.research.premium_discount` |
| `retracements` | `backtester.indicators.research.retracements` |
| `ICTFibEngine` | `backtester.indicators.research.ICTFibEngine` |

## Sizing

| Symbol | Import Path |
| ------ | ----------- |
| `BaseSizer` | `backtester.sizing.BaseSizer` |
| `SizingDecision` | `backtester.sizing.SizingDecision` |
| `FixedLotSizer` | `backtester.sizing.FixedLotSizer` |
| `RiskPercentSizer` | `backtester.sizing.RiskPercentSizer` |
| `KellySizer` | `backtester.sizing.KellySizer` |
| `VolatilitySizer` | `backtester.sizing.VolatilitySizer` |

## Performance

| Symbol | Import Path |
| ------ | ----------- |
| `PerformanceAnalyzer` | `backtester.performance.PerformanceAnalyzer` |
| `PerformanceMetrics` | `backtester.performance.PerformanceMetrics` |
| `ComparisonRun` | `backtester.performance.ComparisonRun` |
| `PerformanceComparison` | `backtester.performance.PerformanceComparison` |

## Optimization

Ranked optimization outputs now require an out-of-sample score. Use `holdout_fraction` or `evaluation_*` inputs on the optimizer entry points, or pass `allow_in_sample=True` only for diagnostic inspection of in-sample tables.

| Symbol | Import Path |
| ------ | ----------- |
| `ParameterSpec` | `backtester.optimization.ParameterSpec` |
| `ObjectiveContext` | `backtester.optimization.ObjectiveContext` |
| `ObjectiveSpec` | `backtester.optimization.ObjectiveSpec` |
| `OptimizationTrial` | `backtester.optimization.OptimizationTrial` |
| `OptimizationProgress` | `backtester.optimization.OptimizationProgress` |
| `OptimizationWarning` | `backtester.optimization.OptimizationWarning` |
| `OptimizationResult` | `backtester.optimization.OptimizationResult` |
| `run_grid_search` | `backtester.optimization.run_grid_search` |
| `run_random_search` | `backtester.optimization.run_random_search` |
| `run_scipy_optimization` | `backtester.optimization.run_scipy_optimization` |

## Walk-Forward

`python -m backtester.walk_forward` is the repo-owned Phase 10 audit CLI. It defaults to local `H4` data, the last `960` completed bars per instrument, expanding `480/160/160/160` folds, out-of-sample `total_return` ranking, and text/JSON/markdown outputs. The default matrix now includes only strategies marked `live_safe`. The Phase 10 `EmaRsiTrendStrategy` keeps `fixed_units=None` instrument-aware: `1000.0` on the covered FX pairs and `1.0` on `XAU_USD`.

| Symbol | Import Path |
| ------ | ----------- |
| `OutputSink` | `backtester.walk_forward.OutputSink` |
| `run_walk_forward` | `backtester.walk_forward.run_walk_forward` |

## Reporting

| Symbol | Import Path |
| ------ | ----------- |
| `BacktestCharts` | `backtester.reporting.BacktestCharts` |
| `build_backtest_json_payload` | `backtester.reporting.build_backtest_json_payload` |
| `build_optimization_json_payload` | `backtester.reporting.build_optimization_json_payload` |
| `export_backtest_artifacts` | `backtester.reporting.export_backtest_artifacts` |
| `export_optimization_artifacts` | `backtester.reporting.export_optimization_artifacts` |

## Examples

Canonical runnable sample strategies now live in the top-level `strategies/` package. The entries below remain available for the minimal docs/examples package.

| Symbol | Import Path |
| ------ | ----------- |
| `QuickstartStrategy` | `backtester.examples.QuickstartStrategy` |
| `WindowStrategy` | `backtester.examples.WindowStrategy` |
| `InstrumentApiStrategy` | `backtester.examples.InstrumentApiStrategy` |
