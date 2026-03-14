from __future__ import annotations

import backtrader as bt
import pytest

from backtester.config import BacktestConfig, ExecutionConfig
from backtester.run_backtest import run_backtest
from backtester.sizing import RiskPercentSizer
from backtester.strategy import BaseStrategy


class JpyRoundTripStrategy(bt.Strategy):
    params = (("size", 1_000.0),)

    def next(self):
        if len(self) == 1 and not self.position:
            self.buy(size=self.p.size)
        elif len(self) == 2 and self.position:
            self.sell(size=self.p.size)


class JpyBuyAndHoldStrategy(bt.Strategy):
    params = (("size", 1_000.0),)

    def next(self):
        if len(self) == 1 and not self.position:
            self.buy(size=self.p.size)


class JpyShortAndHoldStrategy(bt.Strategy):
    params = (("size", 1_000.0),)

    def next(self):
        if len(self) == 1 and not self.position:
            self.sell(size=self.p.size)


class RiskSizedJpyStrategy(BaseStrategy):
    snapshot = None

    def __init__(self):
        super().__init__()
        self.position_sizer = RiskPercentSizer(0.01)

    def next(self):
        if len(self) != 1 or not self.is_flat() or self.has_open_order():
            return

        entry_price = float(self.ask.close)
        stop_price = entry_price - 0.50
        decision = self.position_sizer.size_for_entry(
            equity=self.current_equity(),
            side="long",
            entry_price=entry_price,
            stop_price=stop_price,
            instrument=self.instrument or "USD_JPY",
        )
        type(self).snapshot = decision
        if decision.accepted:
            self.submit_long_market(size=decision.final_size, sizing_decision=decision)


class FixedSizeJpyStrategy(bt.Strategy):
    params = (("size", 1_000.0),)

    def next(self):
        if len(self) == 1 and not self.position:
            self.buy(size=self.p.size)


class CrossRoundTripStrategy(bt.Strategy):
    params = (("size", 1_000.0),)

    def next(self):
        if len(self) == 1 and not self.position:
            self.buy(size=self.p.size)
        elif len(self) == 2 and self.position:
            self.sell(size=self.p.size)


def _run(
    strategy_class,
    frame,
    *,
    instrument: str = "USD_JPY",
    conversion_data=None,
    cash: float = 10_000.0,
    leverage: float = 30.0,
):
    return run_backtest(
        strategy_class,
        instrument=instrument,
        timeframe="H1",
        dataframe=frame,
        conversion_data=conversion_data,
        cash=cash,
        config=BacktestConfig(
            execution=ExecutionConfig(leverage=leverage),
        ),
    )


def _usd_jpy_frame(make_oanda_frame):
    return make_oanda_frame(
        [
            {
                "open": 150.0,
                "high": 150.2,
                "low": 149.8,
                "close": 150.0,
                "bid_open": 149.95,
                "bid_high": 150.15,
                "bid_low": 149.75,
                "bid_close": 149.95,
                "ask_open": 150.05,
                "ask_high": 150.25,
                "ask_low": 149.85,
                "ask_close": 150.05,
            },
            {
                "open": 150.5,
                "high": 150.7,
                "low": 150.3,
                "close": 150.5,
                "bid_open": 150.45,
                "bid_high": 150.65,
                "bid_low": 150.25,
                "bid_close": 150.45,
                "ask_open": 150.55,
                "ask_high": 150.75,
                "ask_low": 150.35,
                "ask_close": 150.55,
            },
            {
                "open": 151.0,
                "high": 151.2,
                "low": 150.8,
                "close": 151.0,
                "bid_open": 150.95,
                "bid_high": 151.15,
                "bid_low": 150.75,
                "bid_close": 150.95,
                "ask_open": 151.05,
                "ask_high": 151.25,
                "ask_low": 150.85,
                "ask_close": 151.05,
            },
            {
                "open": 151.0,
                "high": 151.1,
                "low": 150.9,
                "close": 151.0,
                "bid_open": 150.95,
                "bid_high": 151.05,
                "bid_low": 150.85,
                "bid_close": 150.95,
                "ask_open": 151.05,
                "ask_high": 151.15,
                "ask_low": 150.95,
                "ask_close": 151.05,
            },
        ]
    )


def _eur_gbp_frame(make_oanda_frame):
    return make_oanda_frame(
        [
            {
                "open": 0.8500,
                "high": 0.8504,
                "low": 0.8496,
                "close": 0.8500,
                "bid_open": 0.8499,
                "bid_high": 0.8503,
                "bid_low": 0.8495,
                "bid_close": 0.8499,
                "ask_open": 0.8501,
                "ask_high": 0.8505,
                "ask_low": 0.8497,
                "ask_close": 0.8501,
            },
            {
                "open": 0.8510,
                "high": 0.8514,
                "low": 0.8508,
                "close": 0.8510,
                "bid_open": 0.8509,
                "bid_high": 0.8513,
                "bid_low": 0.8507,
                "bid_close": 0.8509,
                "ask_open": 0.8511,
                "ask_high": 0.8515,
                "ask_low": 0.8509,
                "ask_close": 0.8511,
            },
            {
                "open": 0.8610,
                "high": 0.8613,
                "low": 0.8607,
                "close": 0.8610,
                "bid_open": 0.8609,
                "bid_high": 0.8612,
                "bid_low": 0.8606,
                "bid_close": 0.8609,
                "ask_open": 0.8611,
                "ask_high": 0.8614,
                "ask_low": 0.8608,
                "ask_close": 0.8611,
            },
            {
                "open": 0.8610,
                "high": 0.8612,
                "low": 0.8608,
                "close": 0.8610,
                "bid_open": 0.8609,
                "bid_high": 0.8611,
                "bid_low": 0.8607,
                "bid_close": 0.8609,
                "ask_open": 0.8611,
                "ask_high": 0.8613,
                "ask_low": 0.8609,
                "ask_close": 0.8611,
            },
        ]
    )


def _gbp_usd_conversion_frame(make_oanda_frame, closes: list[float]):
    candles = []
    for close in closes:
        candles.append(
            {
                "open": close,
                "high": close + 0.002,
                "low": close - 0.002,
                "close": close,
                "spread": 0.0002,
            }
        )
    return make_oanda_frame(candles)


def test_closed_usd_jpy_trade_reports_usd_pnl(make_oanda_frame):
    frame = _usd_jpy_frame(make_oanda_frame)
    result = _run(JpyRoundTripStrategy, frame)
    expected_pnl = 1_000.0 * (150.95 - 150.55) * (1.0 / 150.95)

    completed_orders = result.order_ledger[result.order_ledger["status_name"] == "Completed"]
    exit_order = completed_orders[~completed_orders["is_buy"]].iloc[-1]
    closed_trade = result.closed_trade_ledger.iloc[0]

    assert result.execution_policy["point_value"] is None
    assert result.execution_policy["leverage"] == pytest.approx(30.0)
    assert result.execution_policy["quote_to_account_mode"] == "dynamic_from_instrument_price"
    assert exit_order["executed_pnl"] == pytest.approx(expected_pnl)
    assert result.trade_ledger.iloc[-1]["pnlcomm"] == pytest.approx(expected_pnl)
    assert closed_trade["net_pnl"] == pytest.approx(expected_pnl)
    assert result.end_value == pytest.approx(10_000.0 + expected_pnl)


def test_open_usd_jpy_trade_marks_equity_in_usd(make_oanda_frame):
    frame = _usd_jpy_frame(make_oanda_frame)
    result = _run(JpyBuyAndHoldStrategy, frame)
    expected_open_pnl = 1_000.0 * (150.95 - 150.55) * (1.0 / 150.95)

    assert result.trade_ledger.iloc[-1]["status_name"] == "Open"
    assert result.end_value == pytest.approx(10_000.0 + expected_open_pnl)
    assert result.equity_curve.iloc[-1]["value"] == pytest.approx(10_000.0 + expected_open_pnl)
    assert result.equity_curve.iloc[-1]["value"] < 10_010.0


def test_open_short_usd_jpy_trade_marks_equity_to_ask(make_oanda_frame):
    frame = _usd_jpy_frame(make_oanda_frame)
    result = _run(JpyShortAndHoldStrategy, frame)
    expected_open_pnl = 1_000.0 * (150.45 - 151.05) * (1.0 / 151.05)

    assert result.trade_ledger.iloc[-1]["status_name"] == "Open"
    assert result.end_value == pytest.approx(10_000.0 + expected_open_pnl)
    assert result.equity_curve.iloc[-1]["value"] == pytest.approx(10_000.0 + expected_open_pnl)


def test_leveraged_fx_sizing_completes_instead_of_hitting_margin(make_oanda_frame):
    RiskSizedJpyStrategy.snapshot = None
    frame = _usd_jpy_frame(make_oanda_frame)
    result = _run(RiskSizedJpyStrategy, frame)

    entry_events = result.order_ledger[result.order_ledger["role"] == "entry"]
    completed_entries = entry_events[entry_events["status_name"] == "Completed"]

    assert RiskSizedJpyStrategy.snapshot is not None
    assert RiskSizedJpyStrategy.snapshot.accepted is True
    assert RiskSizedJpyStrategy.snapshot.final_size == pytest.approx(30_010.0)
    assert "Margin" not in set(entry_events["status_name"])
    assert not completed_entries.empty
    assert completed_entries.iloc[-1]["size"] == pytest.approx(30_010.0)


def test_fx_orders_still_reject_when_cash_is_insufficient_for_configured_leverage(
    make_oanda_frame,
):
    frame = _usd_jpy_frame(make_oanda_frame)
    result = _run(FixedSizeJpyStrategy, frame, cash=500.0, leverage=1.0)

    entry_events = result.order_ledger[result.order_ledger["is_buy"]]

    assert "Margin" in set(entry_events["status_name"])
    assert result.trade_ledger.empty


def test_cross_currency_pnl_uses_time_varying_conversion_series(make_oanda_frame):
    frame = _eur_gbp_frame(make_oanda_frame)
    low_conversion = _gbp_usd_conversion_frame(make_oanda_frame, [1.20, 1.20, 1.20, 1.20])
    high_conversion = _gbp_usd_conversion_frame(make_oanda_frame, [1.20, 1.20, 1.30, 1.30])

    low_result = _run(
        CrossRoundTripStrategy,
        frame,
        instrument="EUR_GBP",
        conversion_data={"GBP_USD": low_conversion},
    )
    high_result = _run(
        CrossRoundTripStrategy,
        frame,
        instrument="EUR_GBP",
        conversion_data={"GBP_USD": high_conversion},
    )

    low_expected = 1_000.0 * (0.8609 - 0.8511) * 1.20
    high_expected = 1_000.0 * (0.8609 - 0.8511) * 1.30

    assert low_result.execution_policy["point_value"] is None
    assert low_result.execution_policy["quote_to_account_mode"] == "dynamic_from_conversion_data"
    assert low_result.execution_policy["quote_to_account_source"] == "GBP_USD"
    assert low_result.closed_trade_ledger.iloc[0]["net_pnl"] == pytest.approx(low_expected)
    assert high_result.closed_trade_ledger.iloc[0]["net_pnl"] == pytest.approx(high_expected)
    assert high_result.end_value > low_result.end_value
