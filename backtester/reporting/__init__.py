"""Reporting helpers for completed backtest and optimization workflows."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from backtester.core.result import BacktestResult
from backtester.optimization import OptimizationResult
from backtester.performance import PerformanceAnalyzer

from .charts import BacktestCharts
from .csv_report import write_backtest_csv_reports, write_optimization_csv_reports
from .html_report import write_backtest_html_report
from .json_report import (
    build_backtest_json_payload,
    build_optimization_json_payload,
    write_json_report,
)

__all__ = [
    "BacktestCharts",
    "build_backtest_json_payload",
    "build_optimization_json_payload",
    "export_backtest_artifacts",
    "export_optimization_artifacts",
]


def export_backtest_artifacts(
    result: BacktestResult,
    output_root: str | Path,
    *,
    risk_free_rate: float = 0.0,
    run_label: str | None = None,
    include_charts: bool = True,
    include_html: bool = True,
) -> dict[str, Path]:
    """Export one completed backtest run into a structured artifact directory."""

    artifact_dir = _create_artifact_dir(
        Path(output_root),
        kind="run",
        run_label=run_label,
    )
    paths: dict[str, Path] = {"artifact_dir": artifact_dir}
    analyzer = PerformanceAnalyzer(result, risk_free_rate=risk_free_rate)
    payload = build_backtest_json_payload(
        result,
        risk_free_rate=risk_free_rate,
        analyzer=analyzer,
    )

    summary_path = artifact_dir / "summary.json"
    write_json_report(payload, summary_path)
    paths["summary_json"] = summary_path
    paths.update(
        write_backtest_csv_reports(
            result,
            artifact_dir,
            risk_free_rate=risk_free_rate,
            analyzer=analyzer,
        )
    )

    chart_paths: dict[str, Path] = {}
    if include_charts:
        charts_dir = artifact_dir / "charts"
        chart_paths = BacktestCharts(
            result,
            risk_free_rate=risk_free_rate,
            analyzer=analyzer,
        ).render_all(charts_dir)
        paths["charts_dir"] = charts_dir
        paths.update({f"{name}_chart": path for name, path in chart_paths.items()})

    if include_html:
        html_path = artifact_dir / "report.html"
        write_backtest_html_report(
            result,
            html_path,
            risk_free_rate=risk_free_rate,
            chart_paths=chart_paths,
            payload=payload,
        )
        paths["report_html"] = html_path

    return paths


def export_optimization_artifacts(
    result: OptimizationResult,
    output_root: str | Path,
    *,
    run_label: str | None = None,
    top_n: int = 10,
) -> dict[str, Path]:
    """Export one optimization result into a structured artifact directory."""

    artifact_dir = _create_artifact_dir(
        Path(output_root),
        kind="optimization",
        run_label=run_label,
    )
    paths: dict[str, Path] = {"artifact_dir": artifact_dir}

    summary_path = artifact_dir / "summary.json"
    write_json_report(
        build_optimization_json_payload(result, top_n=top_n),
        summary_path,
    )
    paths["summary_json"] = summary_path
    paths.update(write_optimization_csv_reports(result, artifact_dir, top_n=top_n))
    return paths


def _create_artifact_dir(root: Path, *, kind: str, run_label: str | None) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    folder_name = f"{kind}_{timestamp}"
    label = _sanitize_label(run_label)
    if label:
        folder_name = f"{label}_{folder_name}"

    root.mkdir(parents=True, exist_ok=True)
    candidate = root / folder_name
    suffix = 1
    while candidate.exists():
        candidate = root / f"{folder_name}_{suffix}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _sanitize_label(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    normalized = normalized.strip("._-")
    return normalized or None
