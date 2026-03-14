"""JSON payload builders for reporting artifacts."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backtester.core.result import BacktestResult
from backtester.optimization import OptimizationResult, ParameterSpec
from backtester.performance import PerformanceAnalyzer

REPORT_VERSION = "phase6.v1"


def build_backtest_json_payload(
    result: BacktestResult,
    *,
    risk_free_rate: float = 0.0,
    analyzer: PerformanceAnalyzer | None = None,
) -> dict[str, Any]:
    """Build one stable JSON-serializable payload for a backtest result."""

    if analyzer is None:
        analyzer = PerformanceAnalyzer(result, risk_free_rate=risk_free_rate)
    metadata = analyzer.summary()["metadata"]
    execution_assumptions = _build_execution_assumptions(result)

    payload = {
        "report_version": REPORT_VERSION,
        "generated_at": _now_utc_iso(),
        "report_kind": "backtest",
        "metadata": {
            "strategy_name": metadata["strategy_name"],
            "instrument": metadata["instrument"],
            "timeframe": metadata["timeframe"],
            "timeframes": tuple(metadata.get("timeframes", (metadata["timeframe"],))),
            "parameters": dict(metadata["parameters"]),
            "start_cash": metadata["start_cash"],
            "end_cash": metadata["end_cash"],
            "end_value": metadata["end_value"],
            "start_time": metadata["start_time"],
            "end_time": metadata["end_time"],
            "elapsed_time": metadata["elapsed_time"],
            "risk_free_rate": float(risk_free_rate),
        },
        "execution_assumptions": execution_assumptions,
        "caveats": _build_caveats(result),
        "metrics": analyzer.metrics.to_dict(),
        "trade_breakdown": analyzer.trade_breakdown(),
        "warnings": analyzer.warnings(),
        "ledgers": {
            "orders": _frame_to_records(result.order_ledger),
            "trade_events": _frame_to_records(result.trade_ledger),
            "closed_trades": _frame_to_records(analyzer.closed_trades()),
            "open_trades": _frame_to_records(analyzer.open_trades()),
            "equity_curve": _frame_to_records(result.equity_curve),
            "drawdown_series": _frame_to_records(analyzer.drawdown_series()),
            "drawdown_episodes": _frame_to_records(analyzer.drawdown_episodes()),
        },
    }
    return _sanitize_for_serialization(payload)


def build_optimization_json_payload(
    result: OptimizationResult,
    *,
    top_n: int = 10,
) -> dict[str, Any]:
    """Build one stable JSON-serializable payload for an optimization result."""

    if top_n <= 0:
        raise ValueError("top_n must be positive")

    payload = {
        "report_version": REPORT_VERSION,
        "generated_at": _now_utc_iso(),
        "report_kind": "optimization",
        "objective": {
            "name": result.objective.name,
            "direction": result.objective.direction,
            "metric_name": result.objective.metric_name,
        },
        "search_space": [_parameter_spec_record(spec) for spec in result.search_space],
        "fixed_params": dict(result.fixed_params),
        "metadata": {
            "optimizer_name": result.optimizer_name,
            **dict(result.metadata),
            "top_n": int(top_n),
            "ranking_score_source": result.ranking_score_source,
            "ranking_available": result.can_rank_out_of_sample(),
        },
        "warnings": [
            {"code": warning.code, "message": warning.message}
            for warning in result.warnings
        ],
        "trials": _frame_to_records(result.table()),
        "best_runs": _frame_to_records(_best_runs_frame(result, top_n=top_n)),
    }
    return _sanitize_for_serialization(payload)


def write_json_report(payload: dict[str, Any], output_path: str | Path) -> Path:
    """Write one JSON report payload to disk."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _build_execution_assumptions(result: BacktestResult) -> dict[str, Any]:
    policy = dict(result.execution_policy)
    return {
        "buy_side": policy.get("buy_side", "ask"),
        "sell_side": policy.get("sell_side", "bid"),
        "same_bar_policy": policy.get("same_bar_policy"),
        "commission": policy.get("commission"),
        "slippage": policy.get("slippage"),
        "account_currency": policy.get("account_currency", "USD"),
        "margin_model": policy.get("margin_model", "notional_margin"),
        "leverage": policy.get("leverage"),
        "point_value": policy.get("point_value"),
        "pending_orders": "supported",
        "pending_order_activation": "same_bar_children_activate_after_parent_fill",
        "partial_fills": False,
        "bar_based_execution_only": True,
        "single_strategy_only": True,
        "single_instrument_only": True,
        "multi_timeframe_support": len(result.timeframes) > 1,
    }


def _build_caveats(result: BacktestResult) -> list[dict[str, str]]:
    policy = dict(result.execution_policy)
    same_bar_policy = policy.get("same_bar_policy", "unspecified")
    commission = policy.get("commission")
    slippage = policy.get("slippage")

    caveats = [
        {
            "code": "bar_based_execution_only",
            "message": "Execution is bar-based only; intrabar price paths are not modeled.",
        },
        {
            "code": "bid_ask_execution",
            "message": "Buy orders execute from ask candles and sell orders execute from bid candles.",
        },
        {
            "code": "pending_order_same_bar_policy",
            "message": f"Same-bar ambiguity is resolved with the {same_bar_policy} policy.",
        },
        {
            "code": "no_partial_fills",
            "message": "Partial fills are not modeled.",
        },
        {
            "code": "single_strategy_single_instrument",
            "message": "Each run covers one strategy on one instrument only.",
        },
    ]

    if len(result.timeframes) > 1:
        caveats.append(
            {
                "code": "multi_timeframe_context",
                "message": (
                    "Additional same-instrument context feeds are read-only; "
                    "orders execute on the primary timeframe only."
                ),
            }
        )

    if float(commission or 0.0) == 0.0:
        caveats.append(
            {
                "code": "no_commissions",
                "message": "No commissions are modeled in this run.",
            }
        )
    else:
        caveats.append(
            {
                "code": "configured_commissions",
                "message": f"Commissions are configured at {commission}.",
            }
        )

    if float(slippage or 0.0) == 0.0:
        caveats.append(
            {
                "code": "no_slippage",
                "message": "No slippage is modeled in this run.",
            }
        )
    else:
        caveats.append(
            {
                "code": "configured_slippage",
                "message": f"Slippage is configured at {slippage}.",
            }
        )

    return caveats


def _parameter_spec_record(spec: ParameterSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "kind": spec.kind,
        "grid_values": spec.grid_values,
        "bounds": spec.bounds,
        "step": spec.step,
        "distribution": spec.distribution,
    }


def _best_runs_frame(result: OptimizationResult, *, top_n: int) -> pd.DataFrame:
    try:
        return result.ranking().head(top_n)
    except ValueError:
        return pd.DataFrame()


def _frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    records = frame.to_dict(orient="records")
    return [_sanitize_for_serialization(record) for record in records]


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_for_serialization(value: Any) -> Any:
    if value is None or value is pd.NaT:
        return None

    if isinstance(value, dict):
        return {str(key): _sanitize_for_serialization(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_serialization(item) for item in value]

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, pd.DataFrame):
        return _frame_to_records(value)

    if isinstance(value, pd.Series):
        return [_sanitize_for_serialization(item) for item in value.tolist()]

    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        if value.tzinfo is None:
            return value.tz_localize("UTC").isoformat()
        return value.tz_convert("UTC").isoformat()

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()

    if isinstance(value, (pd.Timedelta, np.timedelta64, timedelta)):
        delta = pd.to_timedelta(value)
        if pd.isna(delta):
            return None
        return delta.isoformat()

    if isinstance(value, (date, time)):
        return value.isoformat()

    if isinstance(value, np.generic):
        return _sanitize_for_serialization(value.item())

    if isinstance(value, float):
        return None if not math.isfinite(value) else float(value)

    if isinstance(value, (int, str, bool)):
        return value

    try:
        is_missing = pd.isna(value)
    except TypeError:
        is_missing = False
    if isinstance(is_missing, bool) and is_missing:
        return None

    return str(value)
