"""Backtester package."""

from __future__ import annotations

from .config import BacktestConfig, ExecutionConfig
from .core.result import BacktestResult
from .strategy import BaseStrategy

__all__ = [
    "BaseStrategy",
    "BacktestConfig",
    "BacktestResult",
    "ExecutionConfig",
    "run_backtest",
]


def __getattr__(name: str):
    if name == "run_backtest":
        from .run_backtest import run_backtest

        return run_backtest
    raise AttributeError(name)
