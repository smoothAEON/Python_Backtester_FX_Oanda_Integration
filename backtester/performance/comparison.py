"""Compare multiple completed backtest runs."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtester.core.result import BacktestResult

from .analyzer import PerformanceAnalyzer

CORE_METRIC_COLUMNS = [
    "total_return",
    "annualized_return",
    "cagr",
    "sharpe_ratio",
    "sortino_ratio",
    "calmar_ratio",
    "max_drawdown",
    "max_drawdown_duration_bars",
    "average_drawdown",
    "win_rate",
    "loss_rate",
    "profit_factor",
    "average_win",
    "average_loss",
    "expectancy",
    "max_consecutive_wins",
    "max_consecutive_losses",
    "total_closed_trades",
]


@dataclass(slots=True, frozen=True)
class ComparisonRun:
    """One labeled run to include in a comparison table."""

    label: str
    result: BacktestResult


class PerformanceComparison:
    """Compare multiple normalized backtest results side by side."""

    def __init__(
        self,
        runs: list[ComparisonRun],
        ranking_metric: str = "calmar_ratio",
        *,
        strict: bool = True,
        risk_free_rate: float = 0.0,
    ) -> None:
        if not runs:
            raise ValueError("runs must contain at least one labeled result")

        labels = [run.label for run in runs]
        if len(set(labels)) != len(labels):
            raise ValueError("comparison run labels must be unique")

        self.runs = list(runs)
        self.ranking_metric = ranking_metric
        self.strict = bool(strict)
        self.risk_free_rate = float(risk_free_rate)

    def table(self) -> pd.DataFrame:
        self._validate_runs()
        reference = self.runs[0]
        rows: list[dict] = []

        for run in self.runs:
            analyzer = PerformanceAnalyzer(run.result, risk_free_rate=self.risk_free_rate)
            metrics = analyzer.metrics.to_dict()
            mismatch_flags = self._mismatch_flags(reference.result, run.result)
            rows.append(
                {
                    "label": run.label,
                    "strategy_name": run.result.strategy_name,
                    "instrument": run.result.instrument,
                    "timeframe": run.result.timeframe,
                    "timeframes": tuple(run.result.timeframes),
                    "parameters": dict(run.result.parameters),
                    "execution_policy": dict(run.result.execution_policy),
                    **{metric: metrics.get(metric) for metric in CORE_METRIC_COLUMNS},
                    "warning_count": len(analyzer.warnings()),
                    "strategy_mismatch": mismatch_flags["strategy_mismatch"],
                    "instrument_mismatch": mismatch_flags["instrument_mismatch"],
                    "timeframe_mismatch": mismatch_flags["timeframe_mismatch"],
                    "timeframes_mismatch": mismatch_flags["timeframes_mismatch"],
                    "execution_policy_mismatch": mismatch_flags["execution_policy_mismatch"],
                    "mismatch_notes": self._mismatch_notes(mismatch_flags),
                }
            )

        return pd.DataFrame.from_records(rows)

    def ranking(self) -> pd.DataFrame:
        table = self.table()
        if self.ranking_metric not in table.columns:
            raise ValueError(f"Unknown ranking metric: {self.ranking_metric!r}")

        ranked = table.sort_values(
            by=self.ranking_metric,
            ascending=False,
            na_position="last",
            kind="mergesort",
        ).reset_index(drop=True)
        ranked.insert(0, "rank", range(1, len(ranked) + 1))
        return ranked

    def pairwise(self, reference_label: str | None = None) -> pd.DataFrame:
        table = self.table()
        if reference_label is None:
            reference_label = self.runs[0].label

        reference_rows = table[table["label"] == reference_label]
        if reference_rows.empty:
            raise ValueError(f"Unknown reference label: {reference_label!r}")

        reference = reference_rows.iloc[0]
        rows: list[dict] = []
        for _, row in table.iterrows():
            if row["label"] == reference_label:
                continue

            delta_row = {
                "label": row["label"],
                "reference_label": reference_label,
            }
            for metric in CORE_METRIC_COLUMNS:
                if pd.isna(row[metric]) or pd.isna(reference[metric]):
                    delta_row[f"{metric}_delta"] = None
                else:
                    delta_row[f"{metric}_delta"] = row[metric] - reference[metric]
            rows.append(delta_row)

        return pd.DataFrame.from_records(rows)

    def _validate_runs(self) -> None:
        if not self.strict or len(self.runs) <= 1:
            return

        reference = self.runs[0]
        mismatches: list[str] = []
        for run in self.runs[1:]:
            flags = self._mismatch_flags(reference.result, run.result)
            notes = self._mismatch_notes(flags)
            if notes:
                mismatches.append(
                    f"{run.label!r} does not match {reference.label!r}: {notes}"
                )

        if mismatches:
            raise ValueError(
                "Cannot compare mismatched runs in strict mode: " + "; ".join(mismatches)
            )

    def _mismatch_flags(
        self,
        reference: BacktestResult,
        current: BacktestResult,
    ) -> dict[str, bool]:
        return {
            "strategy_mismatch": current.strategy_name != reference.strategy_name,
            "instrument_mismatch": current.instrument != reference.instrument,
            "timeframe_mismatch": current.timeframe != reference.timeframe,
            "timeframes_mismatch": (
                current.timeframe == reference.timeframe
                and tuple(current.timeframes) != tuple(reference.timeframes)
            ),
            "execution_policy_mismatch": current.execution_policy != reference.execution_policy,
        }

    def _mismatch_notes(self, flags: dict[str, bool]) -> str:
        labels = [
            name.replace("_mismatch", "")
            for name, enabled in flags.items()
            if enabled
        ]
        return ", ".join(labels)
