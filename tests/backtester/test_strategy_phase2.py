from __future__ import annotations

import pandas as pd
import pytest

from backtester.indicators import ema, premium_discount, swing_highs_lows
from backtester.run_backtest import run_backtest
from backtester.strategy import BaseStrategy, crossed_above


def _run(strategy_class, frame: pd.DataFrame, *, cash: float = 10_000.0):
    return run_backtest(
        strategy_class,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        cash=cash,
    )


def _completed_orders(result):
    return result.order_ledger[result.order_ledger["status_name"] == "Completed"]


def _latest_status_for_role(history: list[dict], role: str) -> str:
    matching = [event for event in history if event["role"] == role]
    assert matching
    return matching[-1]["status_name"]


class AccessorStrategy(BaseStrategy):
    snapshot: dict | None = None

    def next(self):
        if len(self) == 2 and type(self).snapshot is None:
            frame = self.to_ohlcv_dataframe()
            type(self).snapshot = {
                "mid_close": self.mid.close,
                "bid_close": self.bid.close,
                "ask_close": self.ask.close,
                "spread": self.spread,
                "rows": len(frame),
                "columns": list(frame.columns),
            }


class HelperMarketStrategy(BaseStrategy):
    def next(self):
        if len(self) == 1 and self.is_flat() and not self.has_open_order():
            self.submit_long_market(size=1)


class HelperLimitStrategy(BaseStrategy):
    def next(self):
        if len(self) == 1 and self.is_flat() and not self.has_open_order():
            self.submit_long_limit(price=100.2, size=1)


class HelperStopStrategy(BaseStrategy):
    def next(self):
        if len(self) == 1 and self.is_flat() and not self.has_open_order():
            self.submit_short_stop(price=99.8, size=1)


class SingleThesisStrategy(BaseStrategy):
    error_message: str | None = None

    def next(self):
        if len(self) == 1 and type(self).error_message is None:
            self.submit_long_market(size=1)
            try:
                self.submit_short_market(size=1)
            except RuntimeError as exc:
                type(self).error_message = str(exc)


class ProtectiveExitStrategy(BaseStrategy):
    history: list[dict] = []
    final_state: dict[str, bool] = {}

    def next(self):
        if len(self) == 1 and self.is_flat() and not self.has_open_order():
            self.submit_long_market(size=1, stop_loss=100.5, take_profit=101.4)

    def stop(self):
        type(self).history = list(self.order_history)
        type(self).final_state = {
            "has_open_order": self.has_open_order(),
            "is_flat": self.is_flat(),
        }


class CancelPendingStrategy(BaseStrategy):
    history: list[dict] = []
    final_state: dict[str, bool] = {}

    def next(self):
        if len(self) == 1 and self.is_flat() and not self.has_open_order():
            self.submit_long_limit(price=95.0, size=1)
        elif len(self) == 2 and self.has_open_order():
            self.cancel_open_orders()

    def stop(self):
        type(self).history = list(self.order_history)
        type(self).final_state = {
            "has_open_order": self.has_open_order(),
            "is_flat": self.is_flat(),
        }


class MarginCleanupStrategy(BaseStrategy):
    history: list[dict] = []
    final_state: dict[str, bool] = {}

    def next(self):
        if len(self) == 1 and self.is_flat() and not self.has_open_order():
            self.submit_long_market(size=1_000)

    def stop(self):
        type(self).history = list(self.order_history)
        type(self).final_state = {
            "has_open_order": self.has_open_order(),
            "is_flat": self.is_flat(),
        }


class Phase2SmokeStrategy(BaseStrategy):
    def next(self):
        frame = self.to_ohlcv_dataframe()
        if len(frame) < 6 or self.has_open_order() or not self.is_flat():
            return

        fast = ema(frame["close"], period=2)
        slow = ema(frame["close"], period=3)
        swings = swing_highs_lows(frame, swing_length=1)
        zones = premium_discount(frame, swings)

        if crossed_above(
            float(fast.iloc[-2]),
            float(fast.iloc[-1]),
            float(slow.iloc[-2]),
            float(slow.iloc[-1]),
        ) and int(zones.iloc[-1]["Zone"]) == -1:
            self.submit_long_market(size=1, stop_loss=99.0, take_profit=102.8)


def test_base_strategy_exposes_accessors_and_dataframe_adapter(make_oanda_frame):
    AccessorStrategy.snapshot = None
    frame = make_oanda_frame()

    _run(AccessorStrategy, frame)

    assert AccessorStrategy.snapshot is not None
    assert AccessorStrategy.snapshot["mid_close"] == 101.0
    assert AccessorStrategy.snapshot["bid_close"] == 100.9
    assert AccessorStrategy.snapshot["ask_close"] == 101.1
    assert AccessorStrategy.snapshot["spread"] == pytest.approx(0.2)
    assert AccessorStrategy.snapshot["rows"] == 2
    assert AccessorStrategy.snapshot["columns"] == [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]


def test_base_strategy_helper_orders_cover_market_limit_and_stop(make_oanda_frame):
    market_frame = make_oanda_frame(
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
    limit_frame = make_oanda_frame(
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
    stop_frame = make_oanda_frame(
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

    market_result = _run(HelperMarketStrategy, market_frame)
    limit_result = _run(HelperLimitStrategy, limit_frame)
    stop_result = _run(HelperStopStrategy, stop_frame)

    assert _completed_orders(market_result).iloc[-1]["executed_price"] == 101.1
    assert _completed_orders(limit_result).iloc[-1]["executed_price"] == 100.2
    assert _completed_orders(stop_result).iloc[-1]["executed_price"] == 99.8


def test_base_strategy_rejects_overlapping_entry_theses(make_oanda_frame):
    SingleThesisStrategy.error_message = None
    frame = make_oanda_frame()

    _run(SingleThesisStrategy, frame)

    assert SingleThesisStrategy.error_message == (
        "BaseStrategy supports only one active entry thesis at a time"
    )


def test_base_strategy_stages_protection_orders_and_cleans_up(make_oanda_frame):
    ProtectiveExitStrategy.history = []
    ProtectiveExitStrategy.final_state = {}
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.4, "low": 99.8, "close": 100.0},
            {
                "open": 101.0,
                "high": 101.2,
                "low": 100.8,
                "close": 101.0,
                "bid_open": 100.9,
                "bid_high": 101.1,
                "bid_low": 100.7,
                "bid_close": 100.9,
                "ask_open": 101.1,
                "ask_high": 101.3,
                "ask_low": 100.9,
                "ask_close": 101.1,
            },
            {
                "open": 101.2,
                "high": 101.6,
                "low": 100.9,
                "close": 101.4,
                "bid_open": 101.1,
                "bid_high": 101.5,
                "bid_low": 100.8,
                "bid_close": 101.3,
                "ask_open": 101.3,
                "ask_high": 101.7,
                "ask_low": 101.0,
                "ask_close": 101.5,
            },
            {"open": 101.0, "high": 101.1, "low": 100.9, "close": 101.0},
        ]
    )

    _run(ProtectiveExitStrategy, frame)

    assert _latest_status_for_role(ProtectiveExitStrategy.history, "entry") == "Completed"
    assert (
        _latest_status_for_role(ProtectiveExitStrategy.history, "take_profit")
        == "Completed"
    )
    assert _latest_status_for_role(ProtectiveExitStrategy.history, "stop_loss") == "Canceled"
    assert ProtectiveExitStrategy.final_state == {
        "has_open_order": False,
        "is_flat": True,
    }


def test_base_strategy_cleans_up_after_canceled_pending_orders(make_oanda_frame):
    CancelPendingStrategy.history = []
    CancelPendingStrategy.final_state = {}
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.3, "low": 99.8, "close": 100.1},
            {"open": 100.4, "high": 100.6, "low": 100.2, "close": 100.5},
            {"open": 100.5, "high": 100.6, "low": 100.4, "close": 100.5},
        ]
    )

    _run(CancelPendingStrategy, frame)

    assert _latest_status_for_role(CancelPendingStrategy.history, "entry") == "Canceled"
    assert CancelPendingStrategy.final_state == {
        "has_open_order": False,
        "is_flat": True,
    }


def test_base_strategy_cleans_up_after_margin_rejection(make_oanda_frame):
    MarginCleanupStrategy.history = []
    MarginCleanupStrategy.final_state = {}
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.5, "low": 99.8, "close": 100.2},
            {"open": 100.1, "high": 100.4, "low": 99.9, "close": 100.0},
        ]
    )

    _run(MarginCleanupStrategy, frame, cash=1.0)

    assert _latest_status_for_role(MarginCleanupStrategy.history, "entry") == "Margin"
    assert MarginCleanupStrategy.final_state == {
        "has_open_order": False,
        "is_flat": True,
    }


def test_phase2_smoke_strategy_runs_with_talib_and_smc(make_oanda_frame):
    frame = make_oanda_frame(
        [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 100.0, "high": 103.0, "low": 100.0, "close": 102.0},
            {"open": 102.0, "high": 104.0, "low": 101.0, "close": 103.0},
            {"open": 103.0, "high": 103.0, "low": 98.0, "close": 99.0},
            {"open": 99.0, "high": 101.0, "low": 98.5, "close": 100.5},
            {"open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5},
            {"open": 101.5, "high": 103.0, "low": 101.0, "close": 102.5},
            {"open": 102.5, "high": 104.0, "low": 102.0, "close": 103.5},
            {"open": 103.0, "high": 103.5, "low": 102.5, "close": 103.0},
        ]
    )

    result = _run(Phase2SmokeStrategy, frame)

    assert not result.order_ledger.empty
    assert not result.trade_ledger.empty
