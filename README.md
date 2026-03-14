# Refactored Workspace

This workspace contains two connected Python tools:

- `oanda-candle-extractor/`: fetches and persists historical OANDA candles in the repo's canonical 14-column mid/bid/ask CSV format.
- `backtester/`: consumes extractor-native CSV or DataFrame input and runs deterministic `backtrader` backtests, optimization sweeps, and report exports.

The long-term goal is to build the backtester first, then reuse the same candle contract, strategy logic, sizing logic, and execution assumptions in a future OANDA trading bot.

## Current State

Implemented and verified:

- Phase 1: backtrader foundation and data integration
- Phase 2: strategy base and indicators
- Phase 3: position sizing
- Phase 4: performance analysis
- Phase 5: optimization
- Phase 6: reporting
- Phase 7: extractor/backtester contract hardening
- Phase 11: same-instrument multi-timeframe backtesting
- Phase 12: master-owned instrument API for strategies

Planned only:

- Phase 9: universe candle fetching and instrument metadata hardening
- Phase 10: runnable `strategies/` sample library

Phase 8 documentation and repo audit are implemented in this pass.

## Start Here

Read these in order:

1. [Repo Audit](plans/phase8_repo_audit.md)
2. [Extractor README](oanda-candle-extractor/README.md)
3. [Backtester README](backtester/README.md)
4. [Project Checker](plans/project_checker.md)

## Responsibilities

Extractor:

- talks to OANDA
- normalizes instruments/timeframes
- caches and persists historical candles
- writes canonical CSVs under `oanda-candle-extractor\data\<INSTRUMENT>\`

Backtester:

- validates extractor-native candles
- loads CSV/DataFrame input into `backtrader`
- centralizes bid/ask-aware execution behavior
- exposes strategy helpers, indicators, sizing, optimization, and reporting

## Current Workflow

What runs today:

- fetch data with `python oanda-candle-extractor\extract_candles.py ...`
- backtest with `run_backtest(...)` programmatically
- export artifacts with `backtester.reporting`

What is still planned:

- public CLI examples that target `--strategy-module strategies.<module>`
- a top-level `strategies/` package with runnable sample strategies

The future `strategies.<module>` workflow is documented in [backtester/README.md](backtester/README.md), but it is explicitly Phase 10 work and is not runnable yet.

## Quick Commands

From the repo root:

```powershell
python -m pip install -r oanda-candle-extractor\requirements.txt
python -m pip install -r backtester\requirements.txt
python oanda-candle-extractor\extract_candles.py --help
python -m backtester.run_backtest --help
python -m pytest tests\extractor -q
python -m pytest tests\backtester -q
```

## Planning Docs

- [Master Backtester Plan](plans/backtester_plan.md)
- [Phase Breakdown](plans/backtester_phases/)
- [Progress Tracker](plans/project_checker.md)
