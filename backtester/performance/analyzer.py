"""High-level summaries for one completed backtest run."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backtester.core.result import BacktestResult

from .metrics import PerformanceMetrics


class PerformanceAnalyzer:
    """Assemble a human-usable summary from one normalized backtest result."""

    def __init__(self, result: BacktestResult, risk_free_rate: float = 0.0) -> None:
        self.result = result
        self.metrics = PerformanceMetrics(result, risk_free_rate=risk_free_rate)

    def summary(self) -> dict[str, Any]:
        return {
            "metadata": self._metadata(),
            "metrics": self.metrics.to_dict(),
            "warnings": self.warnings(),
        }

    def warnings(self) -> list[dict[str, str]]:
        warnings: list[dict[str, str]] = []
        self.metrics.to_dict()
        closed_trades = self.closed_trades()

        if len(closed_trades) < 30:
            warnings.append(
                {
                    "code": "too_few_closed_trades",
                    "message": (
                        f"Only {len(closed_trades)} closed trades are available; "
                        "trade-level inference is likely unstable."
                    ),
                }
            )

        elapsed = self.metrics.elapsed_time()
        if elapsed is None or elapsed < pd.Timedelta(days=30):
            warnings.append(
                {
                    "code": "short_elapsed_period",
                    "message": (
                        "The analyzed run spans less than 30 days; annualized metrics "
                        "may be misleading."
                    ),
                }
            )

        if self.metrics.return_intervals() < 30:
            warnings.append(
                {
                    "code": "too_few_return_intervals",
                    "message": (
                        f"Only {self.metrics.return_intervals()} return intervals are "
                        "available for risk-adjusted metrics."
                    ),
                }
            )

        gross_profits = float(
            closed_trades.loc[closed_trades["net_pnl"] >= 0.0, "net_pnl"].sum()
        )
        if gross_profits > 0.0:
            largest_winner = float(
                closed_trades.loc[closed_trades["net_pnl"] >= 0.0, "net_pnl"].max()
            )
            if largest_winner / gross_profits >= 0.5:
                warnings.append(
                    {
                        "code": "profit_concentration",
                        "message": (
                            "At least 50% of gross profits came from one winning trade."
                        ),
                    }
                )

        for metric_name, reason in self.metrics.skipped_metrics().items():
            warnings.append(
                {
                    "code": "metric_unavailable",
                    "message": f"{metric_name} was unavailable: {reason}.",
                }
            )

        return warnings

    def closed_trades(self) -> pd.DataFrame:
        return self.metrics._closed_trades()

    def open_trades(self) -> pd.DataFrame:
        empty = pd.DataFrame(
            columns=[
                "ref",
                "tradeid",
                "entry_time",
                "as_of_time",
                "direction",
                "entry_price",
                "size",
                "gross_pnl",
                "net_pnl",
                "commission",
                "bars_held",
            ]
        )
        ledger = self.result.trade_ledger.copy()
        if ledger.empty:
            return empty

        ledger["event_time"] = pd.to_datetime(ledger["event_time"], utc=True, errors="coerce")
        ledger["dtopen"] = pd.to_datetime(ledger["dtopen"], utc=True, errors="coerce")
        latest = (
            ledger.sort_values(["event_time", "ref", "tradeid"])
            .groupby(["ref", "tradeid"], dropna=False, as_index=False)
            .tail(1)
        )
        open_rows = latest[
            latest["isopen"].fillna(False) & ~latest["isclosed"].fillna(False)
        ].copy()
        if open_rows.empty:
            return empty

        open_rows["direction"] = open_rows["size"].map(
            lambda value: "long" if float(value) >= 0.0 else "short"
        )
        open_rows["size"] = open_rows["size"].abs()
        return (
            open_rows.rename(
                columns={
                    "dtopen": "entry_time",
                    "event_time": "as_of_time",
                    "price": "entry_price",
                    "pnl": "gross_pnl",
                    "pnlcomm": "net_pnl",
                    "barlen": "bars_held",
                }
            )
            .loc[
                :,
                [
                    "ref",
                    "tradeid",
                    "entry_time",
                    "as_of_time",
                    "direction",
                    "entry_price",
                    "size",
                    "gross_pnl",
                    "net_pnl",
                    "commission",
                    "bars_held",
                ],
            ]
            .reset_index(drop=True)
        )

    def drawdown_series(self) -> pd.DataFrame:
        return self.metrics.drawdown_series()

    def drawdown_episodes(self) -> pd.DataFrame:
        return self.metrics.drawdown_episodes()

    def trade_breakdown(self) -> dict[str, dict[str, float | int | None]]:
        trades = self.closed_trades()
        return {
            "overall": self._trade_segment_summary(trades),
            "long": self._trade_segment_summary(trades[trades["direction"] == "long"]),
            "short": self._trade_segment_summary(trades[trades["direction"] == "short"]),
        }

    def _metadata(self) -> dict[str, Any]:
        start_time = pd.NaT
        end_time = pd.NaT
        equity_curve = self.result.equity_curve.copy()
        if not equity_curve.empty:
            timestamps = pd.to_datetime(equity_curve["time"], utc=True, errors="coerce").dropna()
            if not timestamps.empty:
                start_time = timestamps.iloc[0]
                end_time = timestamps.iloc[-1]

        return {
            "strategy_name": self.result.strategy_name,
            "instrument": self.result.instrument,
            "timeframe": self.result.timeframe,
            "timeframes": tuple(self.result.timeframes),
            "parameters": dict(self.result.parameters),
            "execution_policy": dict(self.result.execution_policy),
            "start_cash": float(self.result.start_cash),
            "end_cash": float(self.result.end_cash),
            "end_value": float(self.result.end_value),
            "start_time": start_time,
            "end_time": end_time,
            "elapsed_time": self.metrics.elapsed_time(),
        }

    def _trade_segment_summary(
        self,
        trades: pd.DataFrame,
    ) -> dict[str, float | int | None]:
        if trades.empty:
            return {
                "closed_trades": 0,
                "wins": 0,
                "losses": 0,
                "gross_pnl": 0.0,
                "net_pnl": 0.0,
                "average_net_pnl": None,
            }

        winners = trades["net_pnl"] >= 0.0
        return {
            "closed_trades": int(len(trades)),
            "wins": int(winners.sum()),
            "losses": int((~winners).sum()),
            "gross_pnl": float(trades["gross_pnl"].sum()),
            "net_pnl": float(trades["net_pnl"].sum()),
            "average_net_pnl": float(trades["net_pnl"].mean()),
        }
