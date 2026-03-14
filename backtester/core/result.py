"""Result normalization for completed backtests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import backtrader as bt
import pandas as pd

from backtester.config import BacktestConfig


@dataclass(slots=True)
class BacktestResult:
    """Stable result object for one backtest run."""

    strategy_name: str
    instrument: str
    timeframe: str
    parameters: dict[str, Any]
    start_cash: float
    end_cash: float
    end_value: float
    order_ledger: pd.DataFrame
    trade_ledger: pd.DataFrame
    closed_trade_ledger: pd.DataFrame
    equity_curve: pd.DataFrame
    analyzer_snapshots: dict[str, Any]
    execution_policy: dict[str, Any]
    timeframes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        normalized = tuple(str(item) for item in self.timeframes if str(item))
        if not normalized:
            normalized = (str(self.timeframe),)
        self.timeframes = normalized


class BacktestRecorder(bt.Analyzer):
    """Collect stable order, trade, and equity events without strategy inheritance."""

    def create_analysis(self):
        self.order_events: list[dict[str, Any]] = []
        self.trade_events: list[dict[str, Any]] = []
        self.closed_trade_events: list[dict[str, Any]] = []
        self.equity_points: list[dict[str, Any]] = []
        self._start_cash = 0.0
        self.rets = {}

    def start(self):
        self._start_cash = float(self.strategy.broker.getcash())

    def next(self):
        primary_data = self.strategy.data0
        dt = _bt_num_to_timestamp(primary_data, primary_data.datetime[0])
        self.equity_points.append(
            {
                "time": dt,
                "cash": float(self.strategy.broker.getcash()),
                "value": float(self.strategy.broker.getvalue()),
                "position_size": float(self.strategy.position.size),
                "close": float(primary_data.close[0]),
                "bid_close": float(primary_data.bid_close[0]),
                "ask_close": float(primary_data.ask_close[0]),
            }
        )

    def notify_order(self, order):
        thesis_ref = order.info.get("thesis_ref")
        self.order_events.append(
            {
                "event_time": _bt_num_to_timestamp(order.data, order.data.datetime[0]),
                "ref": int(order.ref),
                "parent_ref": int(order.parent.ref) if order.parent else None,
                "role": order.info.get("role"),
                "thesis_ref": int(thesis_ref) if thesis_ref is not None else None,
                "status": int(order.status),
                "status_name": order.getstatusname(),
                "order_name": order.getordername(),
                "is_buy": bool(order.isbuy()),
                "size": float(order.size),
                "created_time": _bt_num_to_timestamp(order.data, order.created.dt),
                "created_price": float(order.created.price),
                "created_pricelimit": float(order.created.pricelimit),
                "executed_time": _bt_num_to_timestamp(order.data, order.executed.dt),
                "executed_size": float(order.executed.size),
                "executed_price": float(order.executed.price),
                "executed_value": float(order.executed.value),
                "executed_commission": float(order.executed.comm),
                "executed_pnl": float(order.executed.pnl),
                "remaining_size": float(order.executed.remsize),
                "execution_side": order.info.get("execution_side"),
                "trigger_side": order.info.get("trigger_side"),
                "same_bar_policy": order.info.get("same_bar_policy"),
                "sizing_method": order.info.get("sizing_method"),
                "sizing_raw_size": order.info.get("sizing_raw_size"),
                "sizing_final_size": order.info.get("sizing_final_size"),
                "sizing_equity": order.info.get("sizing_equity"),
                "sizing_stop_price": order.info.get("sizing_stop_price"),
                "sizing_stop_distance": order.info.get("sizing_stop_distance"),
                "sizing_reason": order.info.get("sizing_reason"),
                "sizing_details": _to_builtin(order.info.get("sizing_details")),
            }
        )

    def notify_trade(self, trade):
        self.trade_events.append(
            {
                "event_time": _bt_num_to_timestamp(trade.data, trade.data.datetime[0]),
                "ref": int(trade.ref),
                "tradeid": int(trade.tradeid),
                "status": int(trade.status),
                "status_name": trade.status_names[trade.status],
                "size": float(trade.size),
                "price": float(trade.price),
                "value": float(trade.value),
                "commission": float(trade.commission),
                "pnl": float(trade.pnl),
                "pnlcomm": float(trade.pnlcomm),
                "isopen": bool(trade.isopen),
                "isclosed": bool(trade.isclosed),
                "justopened": bool(trade.justopened),
                "barlen": int(trade.barlen),
                "dtopen": _bt_num_to_timestamp(trade.data, trade.dtopen),
                "dtclose": _bt_num_to_timestamp(trade.data, trade.dtclose),
            }
        )
        if trade.isclosed:
            closed_trade_event = _closed_trade_to_record(trade)
            if closed_trade_event is not None:
                self.closed_trade_events.append(closed_trade_event)

    def get_analysis(self):
        return {
            "start_cash": self._start_cash,
            "orders": list(self.order_events),
            "trades": list(self.trade_events),
            "closed_trades": list(self.closed_trade_events),
            "equity_curve": list(self.equity_points),
        }


def build_backtest_result(
    strategy: bt.Strategy,
    *,
    instrument: str,
    timeframe: str,
    timeframes: tuple[str, ...] | None = None,
    parameters: dict[str, Any],
    config: BacktestConfig,
) -> BacktestResult:
    recorder = strategy.analyzers.phase1_recorder.get_analysis()
    analyzer_snapshots = {
        "drawdown": _to_builtin(strategy.analyzers.drawdown.get_analysis()),
        "trade_analyzer": _to_builtin(strategy.analyzers.trade_analyzer.get_analysis()),
    }

    return BacktestResult(
        strategy_name=type(strategy).__name__,
        instrument=instrument,
        timeframe=timeframe,
        parameters=dict(parameters),
        start_cash=float(recorder["start_cash"] or config.cash),
        end_cash=float(strategy.broker.getcash()),
        end_value=float(strategy.broker.getvalue()),
        order_ledger=_records_to_frame(
            recorder["orders"],
            columns=[
                "event_time",
                "ref",
                "parent_ref",
                "role",
                "thesis_ref",
                "status",
                "status_name",
                "order_name",
                "is_buy",
                "size",
                "created_time",
                "created_price",
                "created_pricelimit",
                "executed_time",
                "executed_size",
                "executed_price",
                "executed_value",
                "executed_commission",
                "executed_pnl",
                "remaining_size",
                "execution_side",
                "trigger_side",
                "same_bar_policy",
                "sizing_method",
                "sizing_raw_size",
                "sizing_final_size",
                "sizing_equity",
                "sizing_stop_price",
                "sizing_stop_distance",
                "sizing_reason",
                "sizing_details",
            ],
        ),
        trade_ledger=_records_to_frame(
            recorder["trades"],
            columns=[
                "event_time",
                "ref",
                "tradeid",
                "status",
                "status_name",
                "size",
                "price",
                "value",
                "commission",
                "pnl",
                "pnlcomm",
                "isopen",
                "isclosed",
                "justopened",
                "barlen",
                "dtopen",
                "dtclose",
            ],
        ),
        closed_trade_ledger=_records_to_frame(
            recorder["closed_trades"],
            columns=[
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
            ],
        ),
        equity_curve=_records_to_frame(
            recorder["equity_curve"],
            columns=[
                "time",
                "cash",
                "value",
                "position_size",
                "close",
                "bid_close",
                "ask_close",
            ],
        ),
        analyzer_snapshots=analyzer_snapshots,
        execution_policy={
            "buy_side": "ask",
            "sell_side": "bid",
            "same_bar_policy": config.execution.same_bar_policy,
            "commission": config.execution.commission,
            "slippage": config.execution.slippage,
        },
        timeframes=tuple(timeframes or (timeframe,)),
    )


def _records_to_frame(records: list[dict[str, Any]], *, columns: list[str]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame.from_records(records, columns=columns)


def _closed_trade_to_record(trade) -> dict[str, Any] | None:
    history = list(getattr(trade, "history", []) or [])
    if not history:
        return None

    entry_event = history[0]
    exit_event = history[-1]
    entry_order = getattr(getattr(entry_event, "event", None), "order", None)
    exit_order = getattr(getattr(exit_event, "event", None), "order", None)

    entry_time = _bt_num_to_timestamp(trade.data, trade.dtopen)
    exit_time = _bt_num_to_timestamp(trade.data, trade.dtclose)
    hold_time = pd.NaT
    if not pd.isna(entry_time) and not pd.isna(exit_time):
        hold_time = exit_time - entry_time

    entry_size = float(abs(entry_event.status.size)) if entry_event.status.size else 0.0
    if entry_size == 0.0:
        entry_size = float(abs(getattr(entry_event.event, "size", 0.0)))

    return {
        "ref": int(trade.ref),
        "tradeid": int(trade.tradeid),
        "entry_order_ref": int(entry_order.ref) if entry_order is not None else None,
        "exit_order_ref": int(exit_order.ref) if exit_order is not None else None,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "direction": "long" if bool(getattr(trade, "long", False)) else "short",
        "entry_price": float(entry_event.status.price),
        "exit_price": float(getattr(exit_event.event, "price", 0.0)),
        "size": entry_size,
        "gross_pnl": float(trade.pnl),
        "net_pnl": float(trade.pnlcomm),
        "commission": float(trade.commission),
        "bars_held": int(trade.barlen),
        "hold_time": hold_time,
        "exit_reason": exit_order.info.get("role") if exit_order is not None else None,
        "exit_order_name": exit_order.getordername() if exit_order is not None else None,
    }


def _bt_num_to_timestamp(data, value: float) -> pd.Timestamp | pd.NaT:
    if not value:
        return pd.NaT
    dt = data.num2date(value, tz=None, naive=True)
    return pd.Timestamp(dt, tz="UTC")


def _to_builtin(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_builtin(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_builtin(item) for item in value]
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)
