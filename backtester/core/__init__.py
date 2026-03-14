"""Core broker, builder, and result primitives for backtests."""

from .cerebro_builder import build_cerebro
from .execution import BidAskBroker, ExecutionModel
from .result import BacktestResult

__all__ = [
    "BacktestResult",
    "BidAskBroker",
    "ExecutionModel",
    "build_cerebro",
]
