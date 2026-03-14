"""CSV exporters for reporting artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from backtester.core.result import BacktestResult
from backtester.optimization import OptimizationResult
from backtester.performance import PerformanceAnalyzer

from .json_report import _build_caveats, _build_execution_assumptions, _sanitize_for_serialization


def write_backtest_csv_reports(
    result: BacktestResult,
    output_dir: str | Path,
    *,
    risk_free_rate: float = 0.0,
    analyzer: PerformanceAnalyzer | None = None,
) -> dict[str, Path]:
    """Write all CSV artifacts for one completed backtest run."""

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    if analyzer is None:
        analyzer = PerformanceAnalyzer(result, risk_free_rate=risk_free_rate)
    warnings = analyzer.warnings()

    paths = {
        "metrics_csv": _write_frame(
            pd.DataFrame([_build_metrics_row(result, analyzer, warnings)]),
            target_dir / "metrics.csv",
        ),
        "warnings_csv": _write_frame(
            pd.DataFrame.from_records(warnings, columns=["code", "message"]),
            target_dir / "warnings.csv",
        ),
        "orders_csv": _write_frame(result.order_ledger, target_dir / "orders.csv"),
        "trade_events_csv": _write_frame(result.trade_ledger, target_dir / "trade_events.csv"),
        "closed_trades_csv": _write_frame(analyzer.closed_trades(), target_dir / "closed_trades.csv"),
        "open_trades_csv": _write_frame(analyzer.open_trades(), target_dir / "open_trades.csv"),
        "equity_csv": _write_frame(result.equity_curve, target_dir / "equity.csv"),
        "drawdown_csv": _write_frame(analyzer.drawdown_series(), target_dir / "drawdown.csv"),
        "drawdown_episodes_csv": _write_frame(
            analyzer.drawdown_episodes(),
            target_dir / "drawdown_episodes.csv",
        ),
    }
    return paths


def write_optimization_csv_reports(
    result: OptimizationResult,
    output_dir: str | Path,
    *,
    top_n: int = 10,
) -> dict[str, Path]:
    """Write all CSV artifacts for one completed optimization run."""

    if top_n <= 0:
        raise ValueError("top_n must be positive")

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    warnings_frame = pd.DataFrame.from_records(
        [{"code": warning.code, "message": warning.message} for warning in result.warnings],
        columns=["code", "message"],
    )
    return {
        "optimization_results_csv": _write_frame(
            result.table(),
            target_dir / "optimization_results.csv",
        ),
        "best_runs_csv": _write_frame(
            result.ranking().head(top_n),
            target_dir / "best_runs.csv",
        ),
        "warnings_csv": _write_frame(warnings_frame, target_dir / "warnings.csv"),
    }


def _build_metrics_row(
    result: BacktestResult,
    analyzer: PerformanceAnalyzer,
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    metadata = analyzer.summary()["metadata"]
    row = {
        "strategy_name": result.strategy_name,
        "instrument": result.instrument,
        "timeframe": result.timeframe,
        "timeframes_json": json.dumps(
            _sanitize_for_serialization(list(result.timeframes)),
            sort_keys=True,
        ),
        "parameters_json": json.dumps(
            _sanitize_for_serialization(dict(result.parameters)),
            sort_keys=True,
        ),
        "execution_assumptions_json": json.dumps(
            _sanitize_for_serialization(_build_execution_assumptions(result)),
            sort_keys=True,
        ),
        "caveats_json": json.dumps(
            _sanitize_for_serialization(_build_caveats(result)),
            sort_keys=True,
        ),
        "start_cash": float(result.start_cash),
        "end_cash": float(result.end_cash),
        "end_value": float(result.end_value),
        "start_time": metadata["start_time"],
        "end_time": metadata["end_time"],
        "elapsed_time": metadata["elapsed_time"],
        "warning_count": len(warnings),
        **analyzer.metrics.to_dict(),
    }
    return _csv_ready_record(row)


def _write_frame(frame: pd.DataFrame, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ready = _frame_to_csv_ready(frame)
    ready.to_csv(output_path, index=False)
    return output_path


def _frame_to_csv_ready(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=frame.columns)

    records = frame.to_dict(orient="records")
    ready_records = [_csv_ready_record(record) for record in records]
    return pd.DataFrame.from_records(ready_records, columns=frame.columns)


def _csv_ready_record(record: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _csv_scalar(value) for key, value in record.items()}


def _csv_scalar(value: Any) -> Any:
    normalized = _sanitize_for_serialization(value)
    if isinstance(normalized, (dict, list)):
        return json.dumps(normalized, sort_keys=True)
    return normalized
