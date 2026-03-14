# Backtester API Index

This index maps the current public backtester surfaces to their module paths.

## Root Package

`run_backtest()` keeps extractor-native inputs unchanged on disk, but normalizes feed and result timestamps to completed-bar time during a run.

| Symbol | Import Path |
| ------ | ----------- |
| `BaseStrategy` | `backtester.BaseStrategy` |
| `BacktestConfig` | `backtester.BacktestConfig` |
| `BacktestResult` | `backtester.BacktestResult` |
| `ExecutionConfig` | `backtester.ExecutionConfig` |
| `run_backtest` | `backtester.run_backtest.run_backtest` |

## Config

Relevant current fields: `ExecutionConfig.leverage` controls leveraged notional-margin simulation, and `InstrumentSpec.point_value` carries the static quote-currency-to-USD conversion used by sizing and P&L.

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

Direct indicator exports are broader than the strategy runtime surface. Repainting helpers remain importable from `backtester.indicators` for offline analysis, but are not available through `BaseStrategy.instrument_api`.

| Symbol | Import Path |
| ------ | ----------- |
| `sma` | `backtester.indicators.sma` |
| `ema` | `backtester.indicators.ema` |
| `rsi` | `backtester.indicators.rsi` |
| `macd` | `backtester.indicators.macd` |
| `atr` | `backtester.indicators.atr` |
| `adx` | `backtester.indicators.adx` |
| `bollinger_bands` | `backtester.indicators.bollinger_bands` |
| `savgol_smooth` | `backtester.indicators.savgol_smooth` |
| `rolling_linreg_slope` | `backtester.indicators.rolling_linreg_slope` |
| `rolling_zscore` | `backtester.indicators.rolling_zscore` |
| `swing_highs_lows` | `backtester.indicators.swing_highs_lows` |
| `bos_choch` | `backtester.indicators.bos_choch` |
| `ob` | `backtester.indicators.ob` |
| `liquidity` | `backtester.indicators.liquidity` |
| `premium_discount` | `backtester.indicators.premium_discount` |
| `previous_high_low` | `backtester.indicators.previous_high_low` |
| `sessions` | `backtester.indicators.sessions` |
| `retracements` | `backtester.indicators.retracements` |
| `ICTFibEngine` | `backtester.indicators.ICTFibEngine` |

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

## Reporting

| Symbol | Import Path |
| ------ | ----------- |
| `BacktestCharts` | `backtester.reporting.BacktestCharts` |
| `build_backtest_json_payload` | `backtester.reporting.build_backtest_json_payload` |
| `build_optimization_json_payload` | `backtester.reporting.build_optimization_json_payload` |
| `export_backtest_artifacts` | `backtester.reporting.export_backtest_artifacts` |
| `export_optimization_artifacts` | `backtester.reporting.export_optimization_artifacts` |

## Examples

| Symbol | Import Path |
| ------ | ----------- |
| `QuickstartStrategy` | `backtester.examples.QuickstartStrategy` |
| `WindowStrategy` | `backtester.examples.WindowStrategy` |
| `InstrumentApiStrategy` | `backtester.examples.InstrumentApiStrategy` |
