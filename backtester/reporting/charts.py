"""Matplotlib chart generation for completed backtest runs."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from backtester.core.result import BacktestResult
from backtester.performance import PerformanceAnalyzer


class BacktestCharts:
    """Render the default chart set for one completed backtest run."""

    def __init__(
        self,
        result: BacktestResult,
        *,
        risk_free_rate: float = 0.0,
        analyzer: PerformanceAnalyzer | None = None,
    ) -> None:
        self.result = result
        self.analyzer = analyzer or PerformanceAnalyzer(result, risk_free_rate=risk_free_rate)

    def equity_curve(self, output_path: str | Path) -> Path:
        curve = self.result.equity_curve.copy()
        if curve.empty:
            return self._render_placeholder(
                output_path,
                title=self._title("Equity Curve"),
                message="No equity data was captured for this run.",
            )

        curve["time"] = pd.to_datetime(curve["time"], utc=True, errors="coerce")
        curve["value"] = pd.to_numeric(curve["value"], errors="coerce")
        curve = curve.dropna(subset=["time", "value"]).sort_values("time")
        if curve.empty:
            return self._render_placeholder(
                output_path,
                title=self._title("Equity Curve"),
                message="Equity data could not be normalized for charting.",
            )

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(curve["time"], curve["value"], color="#0f4c81", linewidth=2.0, label="Equity")
        ax.axhline(
            float(self.result.start_cash),
            color="#7f8c8d",
            linestyle="--",
            linewidth=1.0,
            label="Start Cash",
        )
        ax.set_title(self._title("Equity Curve"))
        ax.set_xlabel("Time (UTC)")
        ax.set_ylabel("Account Value")
        ax.legend(loc="best")
        fig.autofmt_xdate()
        return self._save_figure(fig, output_path)

    def drawdown_chart(self, output_path: str | Path) -> Path:
        drawdown = self.analyzer.drawdown_series()
        if drawdown.empty:
            return self._render_placeholder(
                output_path,
                title=self._title("Drawdown"),
                message="No drawdown data is available for this run.",
            )

        drawdown["time"] = pd.to_datetime(drawdown["time"], utc=True, errors="coerce")
        drawdown["drawdown"] = pd.to_numeric(drawdown["drawdown"], errors="coerce")
        drawdown = drawdown.dropna(subset=["time", "drawdown"]).sort_values("time")
        if drawdown.empty:
            return self._render_placeholder(
                output_path,
                title=self._title("Drawdown"),
                message="Drawdown data could not be normalized for charting.",
            )

        drawdown_pct = drawdown["drawdown"] * 100.0
        fig, ax = plt.subplots(figsize=(10, 4.5))
        ax.fill_between(drawdown["time"], 0.0, drawdown_pct, color="#c44536", alpha=0.3)
        ax.plot(drawdown["time"], drawdown_pct, color="#c44536", linewidth=1.5)
        ax.set_title(self._title("Drawdown"))
        ax.set_xlabel("Time (UTC)")
        ax.set_ylabel("Drawdown (%)")
        fig.autofmt_xdate()
        return self._save_figure(fig, output_path)

    def trade_distribution(self, output_path: str | Path) -> Path:
        trades = self.analyzer.closed_trades()
        if trades.empty or trades["net_pnl"].dropna().empty:
            return self._render_placeholder(
                output_path,
                title=self._title("Trade PnL Distribution"),
                message="No closed trades are available for the trade distribution chart.",
            )

        pnl = pd.to_numeric(trades["net_pnl"], errors="coerce").dropna()
        if pnl.empty:
            return self._render_placeholder(
                output_path,
                title=self._title("Trade PnL Distribution"),
                message="Closed-trade PnL values could not be normalized for charting.",
            )

        bins = min(max(len(pnl), 5), 20)
        fig, ax = plt.subplots(figsize=(8.5, 4.5))
        ax.hist(pnl, bins=bins, color="#1f7a8c", edgecolor="#0b1f2a")
        ax.axvline(0.0, color="#8e3b46", linestyle="--", linewidth=1.0)
        ax.set_title(self._title("Trade PnL Distribution"))
        ax.set_xlabel("Net PnL")
        ax.set_ylabel("Trade Count")
        return self._save_figure(fig, output_path)

    def monthly_returns(self, output_path: str | Path) -> Path:
        curve = self.result.equity_curve.copy()
        if curve.empty:
            return self._render_placeholder(
                output_path,
                title=self._title("Monthly Returns"),
                message="No equity data is available for monthly return aggregation.",
            )

        curve["time"] = pd.to_datetime(curve["time"], utc=True, errors="coerce")
        curve["value"] = pd.to_numeric(curve["value"], errors="coerce")
        curve = curve.dropna(subset=["time", "value"]).sort_values("time")
        if curve.empty:
            return self._render_placeholder(
                output_path,
                title=self._title("Monthly Returns"),
                message="Equity data could not be normalized for monthly return aggregation.",
            )

        curve["month"] = curve["time"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("M")
        month_end = curve.groupby("month", sort=True)["value"].last()
        if len(month_end) < 2:
            return self._render_placeholder(
                output_path,
                title=self._title("Monthly Returns"),
                message="At least two month-end equity points are required for monthly returns.",
            )

        monthly_returns = month_end.pct_change().dropna()
        if monthly_returns.empty:
            return self._render_placeholder(
                output_path,
                title=self._title("Monthly Returns"),
                message="Monthly returns are unavailable for this run.",
            )

        labels = [period.strftime("%Y-%m") for period in monthly_returns.index]
        values = monthly_returns * 100.0
        colors = ["#2d6a4f" if value >= 0.0 else "#b00020" for value in values]

        fig, ax = plt.subplots(figsize=(9.5, 4.5))
        ax.bar(labels, values, color=colors)
        ax.axhline(0.0, color="#555555", linewidth=1.0)
        ax.set_title(self._title("Monthly Returns"))
        ax.set_xlabel("Month")
        ax.set_ylabel("Return (%)")
        ax.tick_params(axis="x", rotation=45)
        return self._save_figure(fig, output_path)

    def render_all(self, output_dir: str | Path) -> dict[str, Path]:
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        return {
            "equity_curve": self.equity_curve(target_dir / "equity_curve.png"),
            "drawdown": self.drawdown_chart(target_dir / "drawdown.png"),
            "trade_distribution": self.trade_distribution(target_dir / "trade_distribution.png"),
            "monthly_returns": self.monthly_returns(target_dir / "monthly_returns.png"),
        }

    def _title(self, name: str) -> str:
        return f"{name} - {self.result.instrument} {self.result.timeframe}"

    def _render_placeholder(
        self,
        output_path: str | Path,
        *,
        title: str,
        message: str,
    ) -> Path:
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.axis("off")
        ax.set_title(title)
        ax.text(
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            wrap=True,
            fontsize=11,
            color="#444444",
        )
        return self._save_figure(fig, output_path)

    def _save_figure(self, fig, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.tight_layout()
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return path
