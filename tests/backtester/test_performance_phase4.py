from __future__ import annotations

import math

import backtrader as bt
import pandas as pd
import pytest

from backtester.core.result import BacktestResult
from backtester.performance import (
    ComparisonRun,
    PerformanceAnalyzer,
    PerformanceComparison,
    PerformanceMetrics,
)
from backtester.run_backtest import run_backtest
from backtester.strategy import BaseStrategy

CLOSED_TRADE_COLUMNS = [
    "ref",
    "tradeid",
    "entry_order_ref",
    "exit_order_ref",
    "entry_time",
    "exit_time",
    "direction",
    "entry_price",
    "exit_price",
    "size",
    "gross_pnl",
    "net_pnl",
    "commission",
    "bars_held",
    "hold_time",
    "exit_reason",
    "exit_order_name",
]


class ManualExitStrategy(bt.Strategy):
    def next(self):
        if len(self) == 1 and not self.position:
            self.buy(size=1)
        elif len(self) == 2 and self.position:
            self.sell(size=1)


class StopLossExitStrategy(BaseStrategy):
    def next(self):
        if len(self) == 1 and self.is_flat() and not self.has_open_order():
            self.submit_long_market(size=1, stop_loss=100.5)


class TakeProfitExitStrategy(BaseStrategy):
    def next(self):
        if len(self) == 1 and self.is_flat() and not self.has_open_order():
            self.submit_long_market(size=1, take_profit=101.4)


class OpenPositionStrategy(bt.Strategy):
    def next(self):
        if len(self) == 1 and not self.position:
            self.buy(size=1)


def _run(strategy_class, frame: pd.DataFrame):
    return run_backtest(
        strategy_class,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
    )


def _empty_closed_trade_ledger() -> pd.DataFrame:
    return pd.DataFrame(columns=CLOSED_TRADE_COLUMNS)


def _build_result(
    *,
    equity_values: list[float],
    closed_trades: list[dict] | None = None,
    strategy_name: str = "SyntheticStrategy",
    instrument: str = "XAU_USD",
    timeframe: str = "H1",
    parameters: dict | None = None,
    execution_policy: dict | None = None,
    start_cash: float = 100.0,
    frequency: str = "D",
) -> BacktestResult:
    times = pd.date_range("2024-01-01", periods=len(equity_values), freq=frequency, tz="UTC")
    equity_curve = pd.DataFrame(
        {
            "time": times,
            "cash": equity_values,
            "value": equity_values,
            "position_size": 0.0,
            "close": equity_values,
            "bid_close": equity_values,
            "ask_close": equity_values,
        }
    )
    closed_trade_ledger = (
        pd.DataFrame.from_records(closed_trades, columns=CLOSED_TRADE_COLUMNS)
        if closed_trades
        else _empty_closed_trade_ledger()
    )
    return BacktestResult(
        strategy_name=strategy_name,
        instrument=instrument,
        timeframe=timeframe,
        parameters=dict(parameters or {}),
        start_cash=start_cash,
        end_cash=float(equity_values[-1]),
        end_value=float(equity_values[-1]),
        order_ledger=pd.DataFrame(),
        trade_ledger=pd.DataFrame(),
        closed_trade_ledger=closed_trade_ledger,
        equity_curve=equity_curve,
        analyzer_snapshots={},
        execution_policy=dict(
            execution_policy
            or {
                "buy_side": "ask",
                "sell_side": "bid",
                "same_bar_policy": "worst_case_first",
                "commission": 0.0,
                "slippage": 0.0,
            }
        ),
    )


def _trade(
    ref: int,
    *,
    direction: str,
    entry_time: str,
    exit_time: str,
    entry_price: float,
    exit_price: float,
    gross_pnl: float,
    net_pnl: float,
    bars_held: int,
    size: float = 1.0,
    exit_reason: str | None = None,
    exit_order_name: str | None = "Market",
) -> dict:
    entry_timestamp = pd.Timestamp(entry_time, tz="UTC")
    exit_timestamp = pd.Timestamp(exit_time, tz="UTC")
    return {
        "ref": ref,
        "tradeid": 0,
        "entry_order_ref": ref,
        "exit_order_ref": ref + 100,
        "entry_time": entry_timestamp,
        "exit_time": exit_timestamp,
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": size,
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "commission": gross_pnl - net_pnl,
        "bars_held": bars_held,
        "hold_time": exit_timestamp - entry_timestamp,
        "exit_reason": exit_reason,
        "exit_order_name": exit_order_name,
    }


def test_result_adds_closed_trade_ledger_without_changing_raw_trade_ledger(make_oanda_frame):
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

    result = _run(ManualExitStrategy, frame)

    assert list(result.trade_ledger["status_name"]) == ["Open", "Closed"]
    assert result.trade_ledger.iloc[0]["price"] == pytest.approx(101.1)
    assert result.trade_ledger.iloc[1]["pnlcomm"] == pytest.approx(-0.5)

    assert list(result.closed_trade_ledger.columns) == CLOSED_TRADE_COLUMNS
    closed_trade = result.closed_trade_ledger.iloc[0]
    completed_orders = result.order_ledger[result.order_ledger["status_name"] == "Completed"]
    entry_fill = completed_orders[completed_orders["is_buy"]].iloc[0]
    exit_fill = completed_orders[~completed_orders["is_buy"]].iloc[0]
    assert closed_trade["entry_order_ref"] == entry_fill["ref"]
    assert closed_trade["exit_order_ref"] == exit_fill["ref"]
    assert closed_trade["entry_time"] == pd.Timestamp("2024-01-01T02:00:00Z")
    assert closed_trade["exit_time"] == pd.Timestamp("2024-01-01T03:00:00Z")
    assert closed_trade["direction"] == "long"
    assert closed_trade["entry_price"] == pytest.approx(101.1)
    assert closed_trade["exit_price"] == pytest.approx(100.6)
    assert closed_trade["size"] == pytest.approx(1.0)
    assert closed_trade["gross_pnl"] == pytest.approx(-0.5)
    assert closed_trade["net_pnl"] == pytest.approx(-0.5)
    assert closed_trade["bars_held"] == 1
    assert closed_trade["hold_time"] == pd.Timedelta(hours=1)
    assert pd.isna(closed_trade["exit_reason"])
    assert closed_trade["exit_order_name"] == "Market"


def test_closed_trade_ledger_captures_stop_loss_and_take_profit_exit_reasons(make_oanda_frame):
    stop_frame = make_oanda_frame(
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
                "open": 100.8,
                "high": 101.0,
                "low": 100.3,
                "close": 100.6,
                "bid_open": 100.7,
                "bid_high": 100.9,
                "bid_low": 100.3,
                "bid_close": 100.5,
                "ask_open": 100.9,
                "ask_high": 101.1,
                "ask_low": 100.5,
                "ask_close": 100.7,
            },
            {"open": 100.7, "high": 100.8, "low": 100.6, "close": 100.7},
        ]
    )
    target_frame = make_oanda_frame(
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

    stop_result = _run(StopLossExitStrategy, stop_frame)
    target_result = _run(TakeProfitExitStrategy, target_frame)

    stop_trade = stop_result.closed_trade_ledger.iloc[0]
    target_trade = target_result.closed_trade_ledger.iloc[0]

    assert stop_trade["exit_reason"] == "stop_loss"
    assert stop_trade["exit_order_name"] == "Stop"
    assert stop_trade["exit_price"] == pytest.approx(100.5)

    assert target_trade["exit_reason"] == "take_profit"
    assert target_trade["exit_order_name"] == "Limit"
    assert target_trade["exit_price"] == pytest.approx(101.4)


def test_no_closed_trade_run_preserves_empty_closed_trade_ledger_and_open_trade_snapshot(
    make_oanda_frame,
):
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
        ]
    )

    result = _run(OpenPositionStrategy, frame)
    analyzer = PerformanceAnalyzer(result)

    assert result.closed_trade_ledger.empty
    open_trades = analyzer.open_trades()
    assert len(open_trades) == 1
    assert open_trades.iloc[0]["direction"] == "long"
    assert open_trades.iloc[0]["entry_price"] == pytest.approx(101.1)


def test_performance_metrics_match_hand_calculated_fixture():
    result = _build_result(
        equity_values=[100.0, 110.0, 105.0, 115.0, 108.0],
        closed_trades=[
            _trade(
                1,
                direction="long",
                entry_time="2024-01-01T00:00:00Z",
                exit_time="2024-01-02T00:00:00Z",
                entry_price=100.0,
                exit_price=110.0,
                gross_pnl=10.0,
                net_pnl=10.0,
                bars_held=1,
            ),
            _trade(
                2,
                direction="short",
                entry_time="2024-01-03T00:00:00Z",
                exit_time="2024-01-05T00:00:00Z",
                entry_price=110.0,
                exit_price=115.0,
                gross_pnl=-5.0,
                net_pnl=-5.0,
                bars_held=2,
            ),
            _trade(
                3,
                direction="long",
                entry_time="2024-01-06T00:00:00Z",
                exit_time="2024-01-07T00:00:00Z",
                entry_price=115.0,
                exit_price=115.0,
                gross_pnl=0.0,
                net_pnl=0.0,
                bars_held=1,
            ),
            _trade(
                4,
                direction="short",
                entry_time="2024-01-08T00:00:00Z",
                exit_time="2024-01-11T00:00:00Z",
                entry_price=115.0,
                exit_price=111.0,
                gross_pnl=4.0,
                net_pnl=4.0,
                bars_held=3,
            ),
        ],
    )
    metrics = PerformanceMetrics(result)

    elapsed_years = 4.0 / 365.25
    returns = pd.Series([0.1, -5.0 / 110.0, 10.0 / 105.0, -7.0 / 115.0], dtype=float)
    sharpe = float(returns.mean() / returns.std(ddof=0) * math.sqrt(365.25))
    downside = returns[returns < 0.0]
    sortino = float(returns.mean() / math.sqrt((downside**2).mean()) * math.sqrt(365.25))
    max_drawdown = 7.0 / 115.0
    average_drawdown = ((5.0 / 110.0) + (7.0 / 115.0)) / 2.0

    assert metrics.total_return() == pytest.approx(0.08)
    assert metrics.annualized_return() == pytest.approx(0.08 / elapsed_years)
    assert metrics.cagr() == pytest.approx((1.08 ** (1.0 / elapsed_years)) - 1.0)
    assert metrics.sharpe_ratio() == pytest.approx(sharpe)
    assert metrics.sortino_ratio() == pytest.approx(sortino)
    assert metrics.calmar_ratio() == pytest.approx(metrics.cagr() / max_drawdown)
    assert metrics.max_drawdown() == pytest.approx(max_drawdown)
    assert metrics.max_drawdown_duration() == 1
    assert metrics.average_drawdown() == pytest.approx(average_drawdown)
    assert metrics.win_rate() == pytest.approx(0.75)
    assert metrics.loss_rate() == pytest.approx(0.25)
    assert metrics.profit_factor() == pytest.approx(2.8)
    assert metrics.average_win() == pytest.approx(14.0 / 3.0)
    assert metrics.average_loss() == pytest.approx(-5.0)
    assert metrics.expectancy() == pytest.approx(2.25)
    assert metrics.max_consecutive_wins() == 2
    assert metrics.max_consecutive_losses() == 1
    assert metrics.average_hold_time() == pd.Timedelta(hours=42)
    assert metrics.best_trade() == pytest.approx(10.0)
    assert metrics.worst_trade() == pytest.approx(-5.0)

    episodes = metrics.drawdown_episodes()
    assert len(episodes) == 2
    assert bool(episodes.iloc[0]["recovered"]) is True
    assert bool(episodes.iloc[1]["recovered"]) is False


def test_performance_analyzer_surfaces_sample_and_metric_warnings():
    result = _build_result(
        equity_values=[100.0, 200.0, 400.0, 800.0],
        closed_trades=[
            _trade(
                1,
                direction="long",
                entry_time="2024-01-01T00:00:00Z",
                exit_time="2024-01-02T00:00:00Z",
                entry_price=100.0,
                exit_price=160.0,
                gross_pnl=60.0,
                net_pnl=60.0,
                bars_held=1,
            ),
            _trade(
                2,
                direction="long",
                entry_time="2024-01-03T00:00:00Z",
                exit_time="2024-01-04T00:00:00Z",
                entry_price=100.0,
                exit_price=120.0,
                gross_pnl=20.0,
                net_pnl=20.0,
                bars_held=1,
            ),
        ],
    )

    analyzer = PerformanceAnalyzer(result)
    summary = analyzer.summary()
    codes = {warning["code"] for warning in summary["warnings"]}
    messages = {warning["message"] for warning in summary["warnings"]}

    assert {"too_few_closed_trades", "short_elapsed_period", "too_few_return_intervals"} <= codes
    assert "profit_concentration" in codes
    assert any("sharpe_ratio was unavailable: zero_return_variance" in message for message in messages)
    assert any("sortino_ratio was unavailable: no_downside_returns" in message for message in messages)


def test_performance_comparison_ranks_by_calmar_and_builds_pairwise_deltas():
    baseline = _build_result(
        equity_values=[100.0, 110.0, 105.0, 120.0],
        closed_trades=[
            _trade(
                1,
                direction="long",
                entry_time="2024-01-01T00:00:00Z",
                exit_time="2024-01-02T00:00:00Z",
                entry_price=100.0,
                exit_price=120.0,
                gross_pnl=20.0,
                net_pnl=20.0,
                bars_held=1,
            ),
        ],
        strategy_name="Phase4Strategy",
    )
    revised = _build_result(
        equity_values=[100.0, 103.0, 90.0, 95.0],
        closed_trades=[
            _trade(
                1,
                direction="long",
                entry_time="2024-01-01T00:00:00Z",
                exit_time="2024-01-02T00:00:00Z",
                entry_price=100.0,
                exit_price=95.0,
                gross_pnl=-5.0,
                net_pnl=-5.0,
                bars_held=1,
            ),
        ],
        strategy_name="Phase4Strategy",
    )

    comparison = PerformanceComparison(
        [ComparisonRun("baseline", baseline), ComparisonRun("revised", revised)]
    )
    ranking = comparison.ranking()
    pairwise = comparison.pairwise()

    assert list(ranking["label"]) == ["baseline", "revised"]
    assert pairwise.iloc[0]["label"] == "revised"
    assert pairwise.iloc[0]["reference_label"] == "baseline"

    baseline_total_return = PerformanceMetrics(baseline).total_return()
    revised_total_return = PerformanceMetrics(revised).total_return()
    assert pairwise.iloc[0]["total_return_delta"] == pytest.approx(
        revised_total_return - baseline_total_return
    )


def test_performance_comparison_rejects_mismatches_in_strict_mode_and_labels_them_otherwise():
    baseline = _build_result(
        equity_values=[100.0, 101.0, 102.0],
        strategy_name="Phase4Strategy",
    )
    mismatch = _build_result(
        equity_values=[100.0, 101.0, 102.0],
        strategy_name="Phase4Strategy",
        timeframe="H4",
    )

    strict_comparison = PerformanceComparison(
        [ComparisonRun("baseline", baseline), ComparisonRun("mismatch", mismatch)]
    )
    with pytest.raises(ValueError, match="strict mode"):
        strict_comparison.table()

    labeled_comparison = PerformanceComparison(
        [ComparisonRun("baseline", baseline), ComparisonRun("mismatch", mismatch)],
        strict=False,
    )
    table = labeled_comparison.table()
    mismatch_row = table.loc[table["label"] == "mismatch"].iloc[0]

    assert bool(mismatch_row["timeframe_mismatch"]) is True
    assert mismatch_row["mismatch_notes"] == "timeframe"
