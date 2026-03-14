from __future__ import annotations

import backtrader as bt

from backtester.data.oanda_feed import OANDABidAskData
from backtester.run_backtest import run_backtest


class CaptureFeedStrategy(bt.Strategy):
    captured: list[tuple[float, float, float]] = []

    def __init__(self):
        self._captured: list[tuple[float, float, float]] = []

    def next(self):
        self._captured.append(
            (
                float(self.data.close[0]),
                float(self.data.bid_close[0]),
                float(self.data.ask_close[0]),
            )
        )

    def stop(self):
        type(self).captured = list(self._captured)


class SmokeStrategy(bt.Strategy):
    def next(self):
        if len(self) == 1 and not self.position:
            self.buy(size=1)
        elif len(self) == 2 and self.position:
            self.sell(size=1)


def test_oanda_feed_exposes_bid_and_ask_lines(make_oanda_frame):
    CaptureFeedStrategy.captured = []
    frame = make_oanda_frame().set_index("time", drop=False)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(OANDABidAskData(dataname=frame))
    cerebro.addstrategy(CaptureFeedStrategy)
    cerebro.run()

    assert CaptureFeedStrategy.captured
    close_price, bid_close, ask_close = CaptureFeedStrategy.captured[0]
    assert close_price == 100.5
    assert bid_close == 100.4
    assert ask_close == 100.6


def test_run_backtest_returns_populated_result(make_oanda_frame):
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.8, "low": 99.8, "close": 100.3},
            {
                "open": 101.0,
                "high": 101.4,
                "low": 100.8,
                "close": 101.2,
                "bid_open": 100.9,
                "bid_high": 101.3,
                "bid_low": 100.7,
                "bid_close": 101.1,
                "ask_open": 101.1,
                "ask_high": 101.5,
                "ask_low": 100.9,
                "ask_close": 101.3,
            },
            {
                "open": 100.7,
                "high": 100.9,
                "low": 100.2,
                "close": 100.4,
                "bid_open": 100.6,
                "bid_high": 100.8,
                "bid_low": 100.1,
                "bid_close": 100.3,
                "ask_open": 100.8,
                "ask_high": 101.0,
                "ask_low": 100.3,
                "ask_close": 100.5,
            },
            {"open": 100.2, "high": 100.4, "low": 99.9, "close": 100.0},
        ]
    )

    result = run_backtest(
        SmokeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
    )

    assert result.strategy_name == "SmokeStrategy"
    assert not result.order_ledger.empty
    assert not result.trade_ledger.empty
    assert not result.equity_curve.empty
    assert result.execution_policy["same_bar_policy"] == "worst_case_first"
