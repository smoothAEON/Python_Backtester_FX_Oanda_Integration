"""Performance metrics derived from one completed backtest run."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from backtester.core.result import BacktestResult

SECONDS_PER_YEAR = 365.25 * 24 * 60 * 60
_UNSET = object()


class PerformanceMetrics:
    """Compute scalar metrics and reusable series from one normalized result."""

    def __init__(self, result: BacktestResult, risk_free_rate: float = 0.0) -> None:
        self.result = result
        self.risk_free_rate = float(risk_free_rate)
        self._metric_cache: dict[str, Any] = {}
        self._skip_reasons: dict[str, str] = {}
        self._drawdown_series_cache: pd.DataFrame | None = None
        self._drawdown_episodes_cache: pd.DataFrame | None = None
        self._returns_cache: pd.Series | None = None
        self._periods_per_year_cache: float | None | object = _UNSET
        self._elapsed_time_cache: pd.Timedelta | None | object = _UNSET

    def total_return(self) -> float | None:
        return self._metric("total_return", self._compute_total_return)

    def annualized_return(self) -> float | None:
        return self._metric("annualized_return", self._compute_annualized_return)

    def cagr(self) -> float | None:
        return self._metric("cagr", self._compute_cagr)

    def sharpe_ratio(self) -> float | None:
        return self._metric("sharpe_ratio", self._compute_sharpe_ratio)

    def sortino_ratio(self) -> float | None:
        return self._metric("sortino_ratio", self._compute_sortino_ratio)

    def calmar_ratio(self) -> float | None:
        return self._metric("calmar_ratio", self._compute_calmar_ratio)

    def max_drawdown(self) -> float:
        return self._metric("max_drawdown", self._compute_max_drawdown)

    def max_drawdown_duration(self) -> int:
        return self._metric(
            "max_drawdown_duration_bars",
            self._compute_max_drawdown_duration_bars,
        )

    def max_drawdown_duration_time(self) -> pd.Timedelta:
        return self._metric(
            "max_drawdown_duration_time",
            self._compute_max_drawdown_duration_time,
        )

    def average_drawdown(self) -> float:
        return self._metric("average_drawdown", self._compute_average_drawdown)

    def total_closed_trades(self) -> int:
        return int(len(self._closed_trades()))

    def return_intervals(self) -> int:
        return int(len(self._returns()))

    def win_rate(self) -> float | None:
        return self._metric("win_rate", self._compute_win_rate)

    def loss_rate(self) -> float | None:
        return self._metric("loss_rate", self._compute_loss_rate)

    def profit_factor(self) -> float | None:
        return self._metric("profit_factor", self._compute_profit_factor)

    def average_win(self) -> float | None:
        return self._metric("average_win", self._compute_average_win)

    def average_loss(self) -> float | None:
        return self._metric("average_loss", self._compute_average_loss)

    def expectancy(self) -> float | None:
        return self._metric("expectancy", self._compute_expectancy)

    def max_consecutive_wins(self) -> int:
        return self._metric(
            "max_consecutive_wins",
            self._compute_max_consecutive_wins,
        )

    def max_consecutive_losses(self) -> int:
        return self._metric(
            "max_consecutive_losses",
            self._compute_max_consecutive_losses,
        )

    def average_hold_time(self) -> pd.Timedelta | None:
        return self._metric("average_hold_time", self._compute_average_hold_time)

    def best_trade(self) -> float | None:
        return self._metric("best_trade", self._compute_best_trade)

    def worst_trade(self) -> float | None:
        return self._metric("worst_trade", self._compute_worst_trade)

    def elapsed_time(self) -> pd.Timedelta | None:
        if self._elapsed_time_cache is _UNSET:
            times = self._equity_times()
            if len(times) < 2:
                self._elapsed_time_cache = None
            else:
                self._elapsed_time_cache = times.iloc[-1] - times.iloc[0]
        return self._elapsed_time_cache

    def periods_per_year(self) -> float | None:
        if self._periods_per_year_cache is _UNSET:
            deltas = self._positive_spacing_seconds()
            if deltas.empty:
                self._periods_per_year_cache = None
            else:
                median_seconds = float(deltas.median())
                self._periods_per_year_cache = (
                    None if median_seconds <= 0.0 else SECONDS_PER_YEAR / median_seconds
                )
        return self._periods_per_year_cache

    def drawdown_series(self) -> pd.DataFrame:
        if self._drawdown_series_cache is None:
            curve = self._equity_curve()
            if curve.empty:
                self._drawdown_series_cache = pd.DataFrame(
                    columns=[
                        "time",
                        "value",
                        "peak_value",
                        "peak_time",
                        "drawdown",
                        "drawdown_amount",
                        "is_drawdown",
                    ]
                )
            else:
                frame = curve.loc[:, ["time", "value"]].copy()
                frame["peak_value"] = frame["value"].cummax()

                peak_times: list[pd.Timestamp] = []
                current_peak_time = pd.NaT
                current_peak_value = -math.inf
                for row in frame.itertuples(index=False):
                    if float(row.value) >= current_peak_value:
                        current_peak_value = float(row.value)
                        current_peak_time = row.time
                    peak_times.append(current_peak_time)

                peaks = frame["peak_value"].replace(0.0, np.nan)
                frame["peak_time"] = peak_times
                frame["drawdown_amount"] = frame["peak_value"] - frame["value"]
                frame["drawdown"] = (
                    frame["drawdown_amount"].div(peaks).replace([np.inf, -np.inf], np.nan)
                )
                frame["drawdown"] = frame["drawdown"].fillna(0.0).clip(lower=0.0)
                frame["is_drawdown"] = frame["drawdown"] > 0.0
                self._drawdown_series_cache = frame
        return self._drawdown_series_cache.copy()

    def drawdown_episodes(self) -> pd.DataFrame:
        if self._drawdown_episodes_cache is None:
            series = self.drawdown_series()
            episodes: list[dict[str, Any]] = []
            current: dict[str, Any] | None = None

            for row in series.itertuples(index=False):
                if bool(row.is_drawdown):
                    if current is None:
                        current = {
                            "start_time": row.time,
                            "peak_time": row.peak_time,
                            "peak_value": float(row.peak_value),
                            "trough_time": row.time,
                            "trough_value": float(row.value),
                            "max_drawdown": float(row.drawdown),
                            "drawdown_amount": float(row.drawdown_amount),
                            "duration_bars": 1,
                            "last_underwater_time": row.time,
                        }
                    else:
                        current["duration_bars"] += 1
                        current["last_underwater_time"] = row.time

                    if float(row.drawdown) >= float(current["max_drawdown"]):
                        current["trough_time"] = row.time
                        current["trough_value"] = float(row.value)
                        current["max_drawdown"] = float(row.drawdown)
                        current["drawdown_amount"] = float(row.drawdown_amount)
                elif current is not None:
                    episodes.append(
                        self._finalize_episode(
                            current,
                            end_time=row.time,
                            recovered=True,
                        )
                    )
                    current = None

            if current is not None:
                episodes.append(
                    self._finalize_episode(
                        current,
                        end_time=pd.NaT,
                        recovered=False,
                    )
                )

            self._drawdown_episodes_cache = pd.DataFrame.from_records(
                episodes,
                columns=[
                    "start_time",
                    "peak_time",
                    "peak_value",
                    "trough_time",
                    "trough_value",
                    "end_time",
                    "recovered",
                    "duration_bars",
                    "duration",
                    "max_drawdown",
                    "drawdown_amount",
                ],
            )
        return self._drawdown_episodes_cache.copy()

    def skipped_metrics(self) -> dict[str, str]:
        self.to_dict()
        return dict(self._skip_reasons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return": self.total_return(),
            "annualized_return": self.annualized_return(),
            "cagr": self.cagr(),
            "sharpe_ratio": self.sharpe_ratio(),
            "sortino_ratio": self.sortino_ratio(),
            "calmar_ratio": self.calmar_ratio(),
            "max_drawdown": self.max_drawdown(),
            "max_drawdown_duration_bars": self.max_drawdown_duration(),
            "max_drawdown_duration_time": self.max_drawdown_duration_time(),
            "average_drawdown": self.average_drawdown(),
            "total_closed_trades": self.total_closed_trades(),
            "return_intervals": self.return_intervals(),
            "win_rate": self.win_rate(),
            "loss_rate": self.loss_rate(),
            "profit_factor": self.profit_factor(),
            "average_win": self.average_win(),
            "average_loss": self.average_loss(),
            "expectancy": self.expectancy(),
            "max_consecutive_wins": self.max_consecutive_wins(),
            "max_consecutive_losses": self.max_consecutive_losses(),
            "average_hold_time": self.average_hold_time(),
            "best_trade": self.best_trade(),
            "worst_trade": self.worst_trade(),
        }

    def _metric(
        self,
        name: str,
        compute: Callable[[], tuple[Any, str | None]],
    ) -> Any:
        if name not in self._metric_cache:
            value, reason = compute()
            self._metric_cache[name] = value
            if value is None and reason is not None:
                self._skip_reasons[name] = reason
            else:
                self._skip_reasons.pop(name, None)
        return self._metric_cache[name]

    def _compute_total_return(self) -> tuple[float | None, str | None]:
        if self.result.start_cash <= 0:
            return None, "start_cash_must_be_positive"
        return float(self.result.end_value / self.result.start_cash) - 1.0, None

    def _compute_annualized_return(self) -> tuple[float | None, str | None]:
        total_return = self.total_return()
        elapsed_years = self._elapsed_years()
        if total_return is None:
            return None, "missing_total_return"
        if elapsed_years is None or elapsed_years <= 0.0:
            return None, "elapsed_time_must_be_positive"
        return float(total_return / elapsed_years), None

    def _compute_cagr(self) -> tuple[float | None, str | None]:
        elapsed_years = self._elapsed_years()
        if elapsed_years is None or elapsed_years <= 0.0:
            return None, "elapsed_time_must_be_positive"
        if self.result.start_cash <= 0.0 or self.result.end_value <= 0.0:
            return None, "cash_and_equity_must_be_positive"
        growth = float(self.result.end_value / self.result.start_cash)
        return float(growth ** (1.0 / elapsed_years) - 1.0), None

    def _compute_sharpe_ratio(self) -> tuple[float | None, str | None]:
        returns = self._returns()
        periods_per_year = self.periods_per_year()
        if returns.empty:
            return None, "insufficient_return_intervals"
        if periods_per_year is None or periods_per_year <= 0.0:
            return None, "missing_return_frequency"

        per_period_risk_free = self.risk_free_rate / periods_per_year
        excess_returns = returns - per_period_risk_free
        volatility = float(excess_returns.std(ddof=0))
        if volatility <= 0.0 or math.isclose(volatility, 0.0, abs_tol=1e-12):
            return None, "zero_return_variance"
        return float(excess_returns.mean() / volatility * math.sqrt(periods_per_year)), None

    def _compute_sortino_ratio(self) -> tuple[float | None, str | None]:
        returns = self._returns()
        periods_per_year = self.periods_per_year()
        if returns.empty:
            return None, "insufficient_return_intervals"
        if periods_per_year is None or periods_per_year <= 0.0:
            return None, "missing_return_frequency"

        per_period_risk_free = self.risk_free_rate / periods_per_year
        excess_returns = returns - per_period_risk_free
        downside_returns = excess_returns[excess_returns < 0.0]
        if downside_returns.empty:
            return None, "no_downside_returns"

        downside_deviation = float(np.sqrt((downside_returns**2).mean()))
        if downside_deviation <= 0.0 or math.isclose(
            downside_deviation,
            0.0,
            abs_tol=1e-12,
        ):
            return None, "zero_downside_variance"

        return float(excess_returns.mean() / downside_deviation * math.sqrt(periods_per_year)), None

    def _compute_calmar_ratio(self) -> tuple[float | None, str | None]:
        cagr = self.cagr()
        max_drawdown = self.max_drawdown()
        if cagr is None:
            return None, "missing_cagr"
        if max_drawdown <= 0.0:
            return None, "max_drawdown_must_be_positive"
        return float(cagr / max_drawdown), None

    def _compute_max_drawdown(self) -> tuple[float, None]:
        episodes = self.drawdown_episodes()
        if episodes.empty:
            return 0.0, None
        return float(episodes["max_drawdown"].max()), None

    def _compute_max_drawdown_duration_bars(self) -> tuple[int, None]:
        episodes = self.drawdown_episodes()
        if episodes.empty:
            return 0, None
        return int(episodes["duration_bars"].max()), None

    def _compute_max_drawdown_duration_time(self) -> tuple[pd.Timedelta, None]:
        episodes = self.drawdown_episodes()
        if episodes.empty:
            return pd.Timedelta(0), None
        return episodes["duration"].max(), None

    def _compute_average_drawdown(self) -> tuple[float, None]:
        episodes = self.drawdown_episodes()
        if episodes.empty:
            return 0.0, None
        return float(episodes["max_drawdown"].mean()), None

    def _compute_win_rate(self) -> tuple[float | None, str | None]:
        trades = self._closed_trades()
        if trades.empty:
            return None, "no_closed_trades"
        return float((trades["net_pnl"] >= 0.0).mean()), None

    def _compute_loss_rate(self) -> tuple[float | None, str | None]:
        trades = self._closed_trades()
        if trades.empty:
            return None, "no_closed_trades"
        return float((trades["net_pnl"] < 0.0).mean()), None

    def _compute_profit_factor(self) -> tuple[float | None, str | None]:
        trades = self._closed_trades()
        if trades.empty:
            return None, "no_closed_trades"
        gross_profit = float(trades.loc[trades["net_pnl"] >= 0.0, "net_pnl"].sum())
        gross_loss = float(-trades.loc[trades["net_pnl"] < 0.0, "net_pnl"].sum())
        if gross_loss <= 0.0:
            return None, "no_gross_loss"
        return float(gross_profit / gross_loss), None

    def _compute_average_win(self) -> tuple[float | None, str | None]:
        winners = self._closed_trades().loc[lambda frame: frame["net_pnl"] >= 0.0, "net_pnl"]
        if winners.empty:
            return None, "no_winning_trades"
        return float(winners.mean()), None

    def _compute_average_loss(self) -> tuple[float | None, str | None]:
        losers = self._closed_trades().loc[lambda frame: frame["net_pnl"] < 0.0, "net_pnl"]
        if losers.empty:
            return None, "no_losing_trades"
        return float(losers.mean()), None

    def _compute_expectancy(self) -> tuple[float | None, str | None]:
        trades = self._closed_trades()
        if trades.empty:
            return None, "no_closed_trades"
        return float(trades["net_pnl"].mean()), None

    def _compute_max_consecutive_wins(self) -> tuple[int, None]:
        return _longest_streak((self._closed_trades()["net_pnl"] >= 0.0).tolist()), None

    def _compute_max_consecutive_losses(self) -> tuple[int, None]:
        return _longest_streak((self._closed_trades()["net_pnl"] < 0.0).tolist()), None

    def _compute_average_hold_time(self) -> tuple[pd.Timedelta | None, str | None]:
        hold_times = self._closed_trades()["hold_time"].dropna()
        if hold_times.empty:
            return None, "no_closed_trades"
        return hold_times.mean(), None

    def _compute_best_trade(self) -> tuple[float | None, str | None]:
        trades = self._closed_trades()
        if trades.empty:
            return None, "no_closed_trades"
        return float(trades["net_pnl"].max()), None

    def _compute_worst_trade(self) -> tuple[float | None, str | None]:
        trades = self._closed_trades()
        if trades.empty:
            return None, "no_closed_trades"
        return float(trades["net_pnl"].min()), None

    def _equity_curve(self) -> pd.DataFrame:
        frame = self.result.equity_curve.copy()
        if frame.empty:
            return frame
        frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        return frame.dropna(subset=["time", "value"]).sort_values("time").reset_index(drop=True)

    def _equity_times(self) -> pd.Series:
        frame = self._equity_curve()
        if frame.empty:
            return pd.Series(dtype="datetime64[ns, UTC]")
        return frame["time"]

    def _positive_spacing_seconds(self) -> pd.Series:
        times = self._equity_times()
        if len(times) < 2:
            return pd.Series(dtype=float)
        deltas = times.diff().dt.total_seconds().dropna()
        return deltas[deltas > 0.0]

    def _closed_trades(self) -> pd.DataFrame:
        frame = self.result.closed_trade_ledger.copy()
        if frame.empty:
            return frame
        frame["entry_time"] = pd.to_datetime(frame["entry_time"], utc=True, errors="coerce")
        frame["exit_time"] = pd.to_datetime(frame["exit_time"], utc=True, errors="coerce")
        frame["hold_time"] = pd.to_timedelta(frame["hold_time"], errors="coerce")
        for column in [
            "entry_price",
            "exit_price",
            "size",
            "gross_pnl",
            "net_pnl",
            "commission",
            "bars_held",
        ]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.sort_values(["exit_time", "entry_time", "ref"]).reset_index(drop=True)

    def _returns(self) -> pd.Series:
        if self._returns_cache is None:
            curve = self._equity_curve()
            if curve.empty:
                self._returns_cache = pd.Series(dtype=float)
            else:
                returns = curve["value"].pct_change()
                self._returns_cache = (
                    returns.replace([np.inf, -np.inf], np.nan).dropna().astype(float)
                )
        return self._returns_cache.copy()

    def _elapsed_years(self) -> float | None:
        elapsed = self.elapsed_time()
        if elapsed is None:
            return None
        seconds = float(elapsed.total_seconds())
        if seconds <= 0.0:
            return None
        return seconds / SECONDS_PER_YEAR

    def _finalize_episode(
        self,
        episode: dict[str, Any],
        *,
        end_time: pd.Timestamp | pd.NaT,
        recovered: bool,
    ) -> dict[str, Any]:
        duration_end = end_time if not pd.isna(end_time) else episode["last_underwater_time"]
        return {
            "start_time": episode["start_time"],
            "peak_time": episode["peak_time"],
            "peak_value": episode["peak_value"],
            "trough_time": episode["trough_time"],
            "trough_value": episode["trough_value"],
            "end_time": end_time,
            "recovered": recovered,
            "duration_bars": episode["duration_bars"],
            "duration": duration_end - episode["start_time"],
            "max_drawdown": episode["max_drawdown"],
            "drawdown_amount": episode["drawdown_amount"],
        }


def _longest_streak(outcomes: list[bool]) -> int:
    longest = 0
    current = 0
    for outcome in outcomes:
        if outcome:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest
