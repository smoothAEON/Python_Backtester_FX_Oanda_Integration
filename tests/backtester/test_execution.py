from __future__ import annotations

import backtrader as bt

from backtester.run_backtest import run_backtest


class MarketBuyStrategy(bt.Strategy):
    def next(self):
        if len(self) == 1 and not self.position:
            self.buy(size=1)


class MarketSellStrategy(bt.Strategy):
    def next(self):
        if len(self) == 1 and not self.position:
            self.sell(size=1)


class BuyLimitStrategy(bt.Strategy):
    def next(self):
        if len(self) == 1:
            self.buy(size=1, exectype=bt.Order.Limit, price=100.2)


class BuyStopStrategy(bt.Strategy):
    def next(self):
        if len(self) == 1:
            self.buy(size=1, exectype=bt.Order.Stop, price=100.8)


class SellLimitStrategy(bt.Strategy):
    def next(self):
        if len(self) == 1:
            self.sell(size=1, exectype=bt.Order.Limit, price=100.8)


class SellStopStrategy(bt.Strategy):
    def next(self):
        if len(self) == 1:
            self.sell(size=1, exectype=bt.Order.Stop, price=99.8)


class PendingLimitStrategy(bt.Strategy):
    def next(self):
        if len(self) == 1:
            self.buy(size=1, exectype=bt.Order.Limit, price=99.0)


class SameBarBracketStrategy(bt.Strategy):
    def next(self):
        if len(self) == 1:
            self.buy_bracket(size=1, price=100.2, stopprice=99.8, limitprice=101.0)


def _run(strategy_class, frame):
    return run_backtest(
        strategy_class,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
    )


def _completed_orders(result):
    return result.order_ledger[result.order_ledger["status_name"] == "Completed"]


def _latest_status_for_ref(result, ref: int):
    events = result.order_ledger[result.order_ledger["ref"] == ref]
    return events.iloc[-1]["status_name"]


def _only_order_ref(result):
    refs = result.order_ledger["ref"].dropna().unique().tolist()
    assert len(refs) == 1
    return int(refs[0])


def test_buy_market_orders_fill_on_ask_open(make_oanda_frame):
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.5, "low": 99.8, "close": 100.2},
            {
                "open": 101.0,
                "high": 101.3,
                "low": 100.8,
                "close": 101.1,
                "bid_open": 100.9,
                "bid_high": 101.2,
                "bid_low": 100.7,
                "bid_close": 101.0,
                "ask_open": 101.1,
                "ask_high": 101.4,
                "ask_low": 100.9,
                "ask_close": 101.2,
            },
            {"open": 101.1, "high": 101.2, "low": 100.9, "close": 101.0},
        ]
    )

    result = _run(MarketBuyStrategy, frame)
    completed = _completed_orders(result)

    assert completed.iloc[-1]["executed_price"] == 101.1
    assert completed.iloc[-1]["execution_side"] == "ask"


def test_sell_market_orders_fill_on_bid_open(make_oanda_frame):
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.5, "low": 99.8, "close": 100.2},
            {
                "open": 101.0,
                "high": 101.3,
                "low": 100.8,
                "close": 101.1,
                "bid_open": 100.9,
                "bid_high": 101.2,
                "bid_low": 100.7,
                "bid_close": 101.0,
                "ask_open": 101.1,
                "ask_high": 101.4,
                "ask_low": 100.9,
                "ask_close": 101.2,
            },
            {"open": 101.1, "high": 101.2, "low": 100.9, "close": 101.0},
        ]
    )

    result = _run(MarketSellStrategy, frame)
    completed = _completed_orders(result)

    assert completed.iloc[-1]["executed_price"] == 100.9
    assert completed.iloc[-1]["execution_side"] == "bid"


def test_buy_limit_orders_trigger_from_ask_prices(make_oanda_frame):
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.5, "low": 99.8, "close": 100.2},
            {
                "open": 100.4,
                "high": 100.8,
                "low": 100.2,
                "close": 100.5,
                "bid_open": 100.3,
                "bid_high": 100.7,
                "bid_low": 99.9,
                "bid_close": 100.4,
                "ask_open": 100.6,
                "ask_high": 100.9,
                "ask_low": 100.0,
                "ask_close": 100.6,
            },
            {"open": 100.5, "high": 100.7, "low": 100.3, "close": 100.4},
        ]
    )

    result = _run(BuyLimitStrategy, frame)
    completed = _completed_orders(result)

    assert completed.iloc[-1]["executed_price"] == 100.2


def test_buy_stop_orders_trigger_from_ask_prices(make_oanda_frame):
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.3, "low": 99.8, "close": 100.1},
            {
                "open": 100.4,
                "high": 100.8,
                "low": 100.2,
                "close": 100.6,
                "bid_open": 100.3,
                "bid_high": 100.7,
                "bid_low": 100.1,
                "bid_close": 100.5,
                "ask_open": 100.5,
                "ask_high": 101.0,
                "ask_low": 100.3,
                "ask_close": 100.7,
            },
            {"open": 100.6, "high": 100.7, "low": 100.4, "close": 100.5},
        ]
    )

    result = _run(BuyStopStrategy, frame)
    completed = _completed_orders(result)

    assert completed.iloc[-1]["executed_price"] == 100.8


def test_sell_limit_orders_trigger_from_bid_prices(make_oanda_frame):
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.3, "low": 99.8, "close": 100.1},
            {
                "open": 100.4,
                "high": 100.8,
                "low": 100.2,
                "close": 100.6,
                "bid_open": 100.5,
                "bid_high": 100.9,
                "bid_low": 100.3,
                "bid_close": 100.7,
                "ask_open": 100.7,
                "ask_high": 101.1,
                "ask_low": 100.5,
                "ask_close": 100.8,
            },
            {"open": 100.6, "high": 100.7, "low": 100.4, "close": 100.5},
        ]
    )

    result = _run(SellLimitStrategy, frame)
    completed = _completed_orders(result)

    assert completed.iloc[-1]["executed_price"] == 100.8


def test_sell_stop_orders_trigger_from_bid_prices(make_oanda_frame):
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.3, "low": 99.8, "close": 100.1},
            {
                "open": 100.2,
                "high": 100.4,
                "low": 99.9,
                "close": 100.0,
                "bid_open": 100.1,
                "bid_high": 100.3,
                "bid_low": 99.7,
                "bid_close": 99.9,
                "ask_open": 100.3,
                "ask_high": 100.5,
                "ask_low": 100.0,
                "ask_close": 100.1,
            },
            {"open": 100.0, "high": 100.1, "low": 99.8, "close": 99.9},
        ]
    )

    result = _run(SellStopStrategy, frame)
    completed = _completed_orders(result)

    assert completed.iloc[-1]["executed_price"] == 99.8


def test_pending_limit_orders_remain_open_when_not_touched(make_oanda_frame):
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.3, "low": 99.8, "close": 100.1},
            {
                "open": 100.4,
                "high": 100.6,
                "low": 100.2,
                "close": 100.5,
                "bid_open": 100.3,
                "bid_high": 100.5,
                "bid_low": 100.1,
                "bid_close": 100.4,
                "ask_open": 100.5,
                "ask_high": 100.7,
                "ask_low": 100.3,
                "ask_close": 100.6,
            },
            {"open": 100.5, "high": 100.6, "low": 100.4, "close": 100.5},
        ]
    )

    result = _run(PendingLimitStrategy, frame)

    assert _latest_status_for_ref(result, _only_order_ref(result)) == "Accepted"


def test_same_bar_bracket_prefers_adverse_exit(make_oanda_frame):
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.4, "low": 99.8, "close": 100.1},
            {
                "open": 100.5,
                "high": 101.2,
                "low": 99.8,
                "close": 100.6,
                "bid_open": 100.4,
                "bid_high": 101.1,
                "bid_low": 99.7,
                "bid_close": 100.5,
                "ask_open": 100.6,
                "ask_high": 101.3,
                "ask_low": 100.0,
                "ask_close": 100.7,
            },
            {"open": 100.6, "high": 100.8, "low": 100.2, "close": 100.4},
        ]
    )

    result = _run(SameBarBracketStrategy, frame)
    completed = _completed_orders(result)

    parent_fill = completed[completed["parent_ref"].isna()].iloc[-1]
    stop_fill = completed[completed["order_name"] == "Stop"].iloc[-1]
    limit_events = result.order_ledger[result.order_ledger["order_name"] == "Limit"]
    child_target_events = limit_events[limit_events["parent_ref"].notna()]

    assert parent_fill["executed_price"] == 100.2
    assert stop_fill["executed_price"] == 99.8
    assert "Canceled" in set(child_target_events["status_name"])
