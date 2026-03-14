"""Centralized Cerebro construction for backtests."""

from __future__ import annotations

import backtrader as bt

from backtester.config import BacktestConfig, InstrumentSpec

from .execution import BidAskBroker, ExecutionModel
from .result import BacktestRecorder


def build_cerebro(
    strategy_class: type[bt.Strategy],
    data_feeds,
    *,
    config: BacktestConfig | None = None,
    strategy_params: dict | None = None,
    instrument_spec: InstrumentSpec | None = None,
) -> bt.Cerebro:
    """Create a consistently configured Cerebro instance for one strategy run."""

    active_config = config or BacktestConfig()
    cerebro = bt.Cerebro(stdstats=False)

    broker = BidAskBroker(execution_model=ExecutionModel(active_config.execution))
    broker.setcash(active_config.cash)
    point_value = instrument_spec.point_value if instrument_spec is not None else 1.0
    # Use futures-like commission info so FX cash usage follows leveraged notional
    # and P&L stays scaled into the USD account currency via ``point_value``.
    broker.setcommission(
        commission=active_config.execution.commission,
        margin=1.0,
        mult=point_value,
        commtype=bt.CommInfoBase.COMM_PERC,
        percabs=True,
        stocklike=False,
        leverage=active_config.execution.leverage,
        automargin=-1,
    )
    broker.set_slippage_perc(active_config.execution.slippage)
    cerebro.setbroker(broker)

    feeds = list(data_feeds)
    if not feeds:
        raise ValueError("build_cerebro requires at least one data feed")

    for feed in feeds:
        cerebro.adddata(feed)
    cerebro.addstrategy(strategy_class, **(strategy_params or {}))
    cerebro.addanalyzer(BacktestRecorder, _name="phase1_recorder")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade_analyzer")
    return cerebro
