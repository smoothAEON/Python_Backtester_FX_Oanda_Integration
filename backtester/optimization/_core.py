"""Shared optimization data structures and helpers."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from numbers import Real
from pathlib import Path
from typing import Any, Literal

import backtrader as bt
import numpy as np
import pandas as pd

from backtester.config import BacktestConfig
from backtester.core.result import BacktestResult
from backtester.performance import PerformanceAnalyzer, PerformanceMetrics
from backtester.run_backtest import run_backtest

ParameterKind = Literal["int", "float", "categorical"]
DistributionKind = Literal["uniform", "loguniform"]
ObjectiveDirection = Literal["maximize", "minimize"]
TrialStatus = Literal["completed", "invalid", "failed"]

SUMMARY_METRIC_COLUMNS = [
    "total_return",
    "cagr",
    "sharpe_ratio",
    "sortino_ratio",
    "calmar_ratio",
    "max_drawdown",
    "win_rate",
    "profit_factor",
    "expectancy",
    "total_closed_trades",
]

ALLOWED_OBJECTIVE_METRICS = {
    "total_return",
    "annualized_return",
    "cagr",
    "sharpe_ratio",
    "sortino_ratio",
    "calmar_ratio",
    "max_drawdown",
    "max_drawdown_duration_bars",
    "max_drawdown_duration_time",
    "average_drawdown",
    "total_closed_trades",
    "return_intervals",
    "win_rate",
    "loss_rate",
    "profit_factor",
    "average_win",
    "average_loss",
    "expectancy",
    "max_consecutive_wins",
    "max_consecutive_losses",
    "average_hold_time",
    "best_trade",
    "worst_trade",
}

DEFAULT_OBJECTIVE_DIRECTIONS: dict[str, ObjectiveDirection] = {
    "total_return": "maximize",
    "annualized_return": "maximize",
    "cagr": "maximize",
    "sharpe_ratio": "maximize",
    "sortino_ratio": "maximize",
    "calmar_ratio": "maximize",
    "max_drawdown": "minimize",
    "max_drawdown_duration_bars": "minimize",
    "max_drawdown_duration_time": "minimize",
    "average_drawdown": "minimize",
    "total_closed_trades": "maximize",
    "return_intervals": "maximize",
    "win_rate": "maximize",
    "loss_rate": "minimize",
    "profit_factor": "maximize",
    "average_win": "maximize",
    "average_loss": "maximize",
    "expectancy": "maximize",
    "max_consecutive_wins": "maximize",
    "max_consecutive_losses": "minimize",
    "average_hold_time": "minimize",
    "best_trade": "maximize",
    "worst_trade": "maximize",
}

INVALID_OBJECTIVE_PENALTY = 1e12

ProgressCallback = Callable[["OptimizationProgress"], None]
CheckpointCallback = Callable[["OptimizationResult"], None]
EarlyStopCallback = Callable[["OptimizationProgress"], bool]


@dataclass(slots=True, frozen=True)
class ParameterSpec:
    """One tunable strategy parameter and its search-space metadata."""

    name: str
    kind: ParameterKind
    grid_values: tuple[Any, ...] | None = None
    bounds: tuple[float, float] | None = None
    step: float | None = None
    distribution: DistributionKind | None = None

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name:
            raise ValueError("ParameterSpec.name must be a non-empty string")
        object.__setattr__(self, "name", normalized_name)

        if self.kind not in {"int", "float", "categorical"}:
            raise ValueError(f"Unsupported parameter kind: {self.kind!r}")

        if self.distribution is not None and self.distribution not in {"uniform", "loguniform"}:
            raise ValueError(f"Unsupported parameter distribution: {self.distribution!r}")

        if self.grid_values is not None:
            values = tuple(self.grid_values)
            if not values:
                raise ValueError(f"{self.name!r} grid_values must contain at least one value")
            object.__setattr__(self, "grid_values", values)

        if self.bounds is not None:
            if len(self.bounds) != 2:
                raise ValueError(f"{self.name!r} bounds must contain exactly two values")
            lower, upper = float(self.bounds[0]), float(self.bounds[1])
            if not math.isfinite(lower) or not math.isfinite(upper):
                raise ValueError(f"{self.name!r} bounds must be finite")
            if lower > upper:
                raise ValueError(f"{self.name!r} lower bound must be <= upper bound")
            if self.kind == "int" and (
                not float(lower).is_integer() or not float(upper).is_integer()
            ):
                raise ValueError(f"{self.name!r} int bounds must be whole numbers")
            if self.kind == "categorical":
                raise ValueError(f"{self.name!r} categorical parameters cannot declare bounds")
            object.__setattr__(self, "bounds", (lower, upper))

        if self.step is not None:
            step = float(self.step)
            if not math.isfinite(step) or step <= 0.0:
                raise ValueError(f"{self.name!r} step must be a positive finite number")
            if self.kind == "categorical":
                raise ValueError(f"{self.name!r} categorical parameters cannot declare step")
            if self.kind == "int" and not step.is_integer():
                raise ValueError(f"{self.name!r} int step must be a whole number")
            object.__setattr__(self, "step", step)


@dataclass(slots=True, frozen=True)
class ObjectiveContext:
    """Context passed to user-defined callable objectives."""

    result: BacktestResult
    analyzer: PerformanceAnalyzer
    metrics: PerformanceMetrics
    parameters: dict[str, Any]


@dataclass(slots=True, frozen=True)
class ObjectiveSpec:
    """Explicit optimization objective configuration."""

    name: str
    direction: ObjectiveDirection
    metric_name: str | None = None
    evaluator: Callable[[ObjectiveContext], float] | None = None

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name:
            raise ValueError("ObjectiveSpec.name must be a non-empty string")
        object.__setattr__(self, "name", normalized_name)

        if self.direction not in {"maximize", "minimize"}:
            raise ValueError(f"Unsupported objective direction: {self.direction!r}")

        has_metric_name = self.metric_name is not None
        has_evaluator = self.evaluator is not None
        if has_metric_name == has_evaluator:
            raise ValueError("ObjectiveSpec requires exactly one of metric_name or evaluator")

        if has_metric_name:
            metric_name = str(self.metric_name).strip()
            if metric_name not in ALLOWED_OBJECTIVE_METRICS:
                raise ValueError(f"Unknown objective metric: {metric_name!r}")
            object.__setattr__(self, "metric_name", metric_name)

        if has_evaluator and not callable(self.evaluator):
            raise TypeError("ObjectiveSpec.evaluator must be callable")


@dataclass(slots=True)
class OptimizationTrial:
    """One normalized optimization trial record."""

    run_id: int
    optimizer_name: str
    status: TrialStatus
    parameters: dict[str, Any]
    objective_name: str
    objective_direction: ObjectiveDirection
    objective_metric: str | None
    objective_score: float | None
    strategy_name: str
    instrument: str
    timeframe: str
    timeframes: tuple[str, ...] = field(default_factory=tuple)
    metrics: dict[str, Any] = field(default_factory=dict)
    warning_count: int | None = None
    error: str | None = None
    result: BacktestResult | None = None
    cache_hit: bool = False

    def __post_init__(self) -> None:
        normalized = tuple(str(item) for item in self.timeframes if str(item))
        if not normalized:
            normalized = (str(self.timeframe),)
        self.timeframes = normalized

    def to_record(self) -> dict[str, Any]:
        record = {
            "run_id": self.run_id,
            "optimizer_name": self.optimizer_name,
            "status": self.status,
            "cache_hit": self.cache_hit,
            "strategy_name": self.strategy_name,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "timeframes": tuple(self.timeframes),
            "parameters": dict(self.parameters),
            "objective_name": self.objective_name,
            "objective_metric": self.objective_metric,
            "objective_direction": self.objective_direction,
            "objective_score": self.objective_score,
            "warning_count": self.warning_count,
            "error": self.error,
        }
        for metric_name in SUMMARY_METRIC_COLUMNS:
            record[metric_name] = self.metrics.get(metric_name)
        return record


@dataclass(slots=True, frozen=True)
class OptimizationWarning:
    """One optimization-level caveat."""

    code: str
    message: str


@dataclass(slots=True, frozen=True)
class OptimizationProgress:
    """Progress snapshot emitted during a long optimization run."""

    optimizer_name: str
    objective_name: str
    total_trials: int
    completed_trials: int
    invalid_trials: int
    failed_trials: int
    cache_hit_trials: int
    unique_evaluated_trials: int
    target_trial_count: int | None
    target_evaluations: int | None
    latest_trial: OptimizationTrial | None
    best_trial: OptimizationTrial | None
    stopped_early: bool
    stop_reason: str | None


TRIAL_TABLE_COLUMNS = [
    "run_id",
    "optimizer_name",
    "status",
    "cache_hit",
    "strategy_name",
    "instrument",
    "timeframe",
    "timeframes",
    "parameters",
    "objective_name",
    "objective_metric",
    "objective_direction",
    "objective_score",
    *SUMMARY_METRIC_COLUMNS,
    "warning_count",
    "error",
]


@dataclass(slots=True)
class OptimizationResult:
    """Collected trial output for one optimizer invocation."""

    optimizer_name: str
    objective: ObjectiveSpec
    search_space: tuple[ParameterSpec, ...]
    fixed_params: dict[str, Any] = field(default_factory=dict)
    trials: list[OptimizationTrial] = field(default_factory=list)
    warnings: list[OptimizationWarning] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def table(self) -> pd.DataFrame:
        if not self.trials:
            return pd.DataFrame(columns=TRIAL_TABLE_COLUMNS)
        records = [trial.to_record() for trial in self.trials]
        return pd.DataFrame.from_records(records, columns=TRIAL_TABLE_COLUMNS)

    def ranking(self, *, include_invalid: bool = False) -> pd.DataFrame:
        table = self.table()
        if not include_invalid:
            table = table.loc[table["status"] == "completed"].copy()
        if table.empty:
            ranked = table.reset_index(drop=True)
            ranked.insert(0, "rank", pd.Series(dtype=int))
            return ranked

        ascending = self.objective.direction == "minimize"
        ranked = table.sort_values(
            by=["objective_score", "run_id"],
            ascending=[ascending, True],
            na_position="last",
            kind="mergesort",
        ).reset_index(drop=True)
        ranked.insert(0, "rank", range(1, len(ranked) + 1))
        return ranked

    def best_trial(self) -> OptimizationTrial:
        completed = [trial for trial in self.trials if trial.status == "completed"]
        if not completed:
            raise ValueError("No completed optimization trials are available")

        if self.objective.direction == "maximize":
            return max(completed, key=lambda trial: (trial.objective_score, -trial.run_id))
        return min(completed, key=lambda trial: (trial.objective_score, trial.run_id))

    def best_result(self) -> BacktestResult:
        best = self.best_trial()
        if best.result is None:
            raise ValueError("The best trial does not include a completed backtest result")
        return best.result


def resolve_objective_spec(objective: str | ObjectiveSpec) -> ObjectiveSpec:
    """Normalize a string or explicit objective spec into an ObjectiveSpec."""

    if isinstance(objective, ObjectiveSpec):
        return objective

    if isinstance(objective, str):
        metric_name = objective.strip()
        if metric_name not in ALLOWED_OBJECTIVE_METRICS:
            raise ValueError(f"Unknown objective metric: {metric_name!r}")
        return ObjectiveSpec(
            name=metric_name,
            direction=DEFAULT_OBJECTIVE_DIRECTIONS[metric_name],
            metric_name=metric_name,
        )

    raise TypeError("objective must be a metric-name string or ObjectiveSpec")


def normalize_search_space(search_space: Sequence[ParameterSpec]) -> tuple[ParameterSpec, ...]:
    """Validate and freeze one optimization search space."""

    if not search_space:
        raise ValueError("search_space must contain at least one ParameterSpec")

    normalized: list[ParameterSpec] = []
    seen: set[str] = set()
    for spec in search_space:
        if not isinstance(spec, ParameterSpec):
            raise TypeError("search_space must contain only ParameterSpec instances")
        if spec.name in seen:
            raise ValueError(f"Duplicate parameter name in search_space: {spec.name!r}")
        seen.add(spec.name)
        normalized.append(spec)
    return tuple(normalized)


def validate_fixed_params(
    fixed_params: dict[str, Any] | None,
    search_space: Sequence[ParameterSpec],
) -> dict[str, Any]:
    """Copy fixed params and reject overlap with searched keys."""

    normalized = dict(fixed_params or {})
    overlaps = sorted(set(normalized) & {spec.name for spec in search_space})
    if overlaps:
        raise ValueError(
            "fixed_params cannot overlap searched parameters: " + ", ".join(overlaps)
        )
    return normalized


def normalize_grid_value(spec: ParameterSpec, value: Any) -> Any:
    """Coerce one explicit grid value into the parameter's runtime form."""

    return normalize_runtime_value(spec, value, clip=True)


def normalize_runtime_value(spec: ParameterSpec, value: Any, *, clip: bool) -> Any:
    """Coerce a sampled or optimized value into the parameter's runtime form."""

    if spec.kind == "categorical":
        return value

    numeric = _as_float(value, name=spec.name)
    if clip and spec.bounds is not None:
        lower, upper = spec.bounds
        numeric = min(max(numeric, lower), upper)

    if spec.step is not None:
        base = spec.bounds[0] if spec.bounds is not None else 0.0
        numeric = _quantize_to_step(numeric, step=spec.step, base=base)

    if clip and spec.bounds is not None:
        lower, upper = spec.bounds
        numeric = min(max(numeric, lower), upper)

    if spec.kind == "int":
        return int(round(numeric))
    return float(numeric)


def sample_parameter(spec: ParameterSpec, rng: np.random.Generator) -> Any:
    """Sample one parameter value for random search."""

    if spec.kind == "categorical":
        if spec.grid_values is None:
            raise ValueError(f"{spec.name!r} categorical random search requires grid_values")
        index = int(rng.integers(0, len(spec.grid_values)))
        return spec.grid_values[index]

    if spec.bounds is None:
        raise ValueError(f"{spec.name!r} numeric random search requires bounds")

    lower, upper = spec.bounds
    distribution = spec.distribution or "uniform"
    if distribution == "loguniform":
        if lower <= 0.0 or upper <= 0.0:
            raise ValueError(f"{spec.name!r} loguniform bounds must be strictly positive")
        sampled = float(np.exp(rng.uniform(math.log(lower), math.log(upper))))
    else:
        sampled = float(rng.uniform(lower, upper))

    return normalize_runtime_value(spec, sampled, clip=True)


def midpoint_value(spec: ParameterSpec) -> Any:
    """Choose a deterministic midpoint default for scipy initialization."""

    if spec.bounds is None:
        raise ValueError(f"{spec.name!r} scipy optimization requires bounds")
    lower, upper = spec.bounds
    midpoint = lower + ((upper - lower) / 2.0)
    return normalize_runtime_value(spec, midpoint, clip=True)


def build_scipy_vector(
    search_space: Sequence[ParameterSpec],
    x0: dict[str, float] | None = None,
) -> np.ndarray:
    """Build a deterministic scipy starting vector."""

    initial_values: list[float] = []
    provided = dict(x0 or {})
    unknown = sorted(set(provided) - {spec.name for spec in search_space})
    if unknown:
        raise ValueError("x0 contains unknown parameters: " + ", ".join(unknown))

    for spec in search_space:
        if spec.bounds is None:
            raise ValueError(f"{spec.name!r} scipy optimization requires bounds")
        raw_value = provided.get(spec.name, midpoint_value(spec))
        normalized = normalize_runtime_value(spec, raw_value, clip=True)
        initial_values.append(float(normalized))
    return np.asarray(initial_values, dtype=float)


def parameter_hash(parameters: dict[str, Any]) -> str:
    """Build a deterministic cache key for one parameter set."""

    items = sorted((str(key), _stable_value(value)) for key, value in parameters.items())
    return repr(tuple(items))


def validate_grid_parameter(spec: ParameterSpec) -> tuple[Any, ...]:
    """Validate one grid-search parameter spec and return normalized values."""

    if spec.grid_values is None:
        raise ValueError(f"{spec.name!r} grid search requires explicit grid_values")

    normalized_values = tuple(normalize_grid_value(spec, value) for value in spec.grid_values)
    hashes = {parameter_hash({spec.name: value}) for value in normalized_values}
    if len(hashes) != len(normalized_values):
        raise ValueError(f"{spec.name!r} grid_values contain duplicates after normalization")
    return normalized_values


def validate_random_parameter(spec: ParameterSpec) -> None:
    """Validate one random-search parameter spec."""

    if spec.kind == "categorical":
        if spec.grid_values is None:
            raise ValueError(f"{spec.name!r} categorical random search requires grid_values")
        return

    if spec.bounds is None:
        raise ValueError(f"{spec.name!r} numeric random search requires bounds")
    if spec.distribution == "loguniform":
        lower, upper = spec.bounds
        if lower <= 0.0 or upper <= 0.0:
            raise ValueError(f"{spec.name!r} loguniform bounds must be strictly positive")


def validate_scipy_parameter(spec: ParameterSpec) -> None:
    """Validate one scipy-optimization parameter spec."""

    if spec.kind == "categorical":
        raise ValueError(f"{spec.name!r} scipy optimization does not support categorical specs")
    if spec.bounds is None:
        raise ValueError(f"{spec.name!r} scipy optimization requires bounds")


class _OptimizationSession:
    """Shared execution and caching layer for optimization runners."""

    def __init__(
        self,
        *,
        optimizer_name: str,
        strategy_class: type[bt.Strategy],
        instrument: str,
        timeframe: str,
        csv_path: str | None,
        dataframe: pd.DataFrame | None,
        context_data: dict[str, str | Path | pd.DataFrame] | None,
        cash: float,
        config: BacktestConfig | None,
        fixed_params: dict[str, Any] | None,
        search_space: Sequence[ParameterSpec],
        objective: str | ObjectiveSpec,
        constraint: Callable[[dict[str, Any]], bool] | None,
        progress_every: int | None,
        progress_callback: ProgressCallback | None,
        checkpoint_every: int | None,
        checkpoint_callback: CheckpointCallback | None,
        early_stop: EarlyStopCallback | None,
        target_trial_count: int | None,
        target_evaluations: int | None,
    ) -> None:
        self.optimizer_name = optimizer_name
        self.strategy_class = strategy_class
        self.instrument = instrument
        self.timeframe = timeframe
        self.csv_path = csv_path
        self.dataframe = dataframe
        self.context_data = dict(context_data or {})
        self.cash = float(cash)
        self.config = config
        self.search_space = normalize_search_space(search_space)
        self.fixed_params = validate_fixed_params(fixed_params, self.search_space)
        self.objective = resolve_objective_spec(objective)
        self.constraint = constraint
        self.trials: list[OptimizationTrial] = []
        self._trial_cache: dict[str, OptimizationTrial] = {}
        self._valid_unique_trials = 0
        self._progress_every = _normalize_interval(
            progress_every,
            callback=progress_callback,
            name="progress_every",
        )
        self._progress_callback = progress_callback
        self._checkpoint_every = _normalize_interval(
            checkpoint_every,
            callback=checkpoint_callback,
            name="checkpoint_every",
        )
        self._checkpoint_callback = checkpoint_callback
        self._early_stop = early_stop
        self._target_trial_count = (
            None if target_trial_count is None else int(target_trial_count)
        )
        self._target_evaluations = (
            None if target_evaluations is None else int(target_evaluations)
        )
        self._last_progress_emit_trial_count = 0
        self._last_checkpoint_emit_trial_count = 0
        self._stop_requested = False
        self._stop_reason: str | None = None
        self._data_bars: int | None = None
        self._finalized = False

    @property
    def valid_unique_trials(self) -> int:
        return self._valid_unique_trials

    @property
    def should_stop(self) -> bool:
        return self._stop_requested

    @property
    def stop_reason(self) -> str | None:
        return self._stop_reason

    def set_target_trial_count(self, target_trial_count: int | None) -> None:
        if target_trial_count is None:
            self._target_trial_count = None
            return
        self._target_trial_count = int(target_trial_count)

    def set_target_evaluations(self, target_evaluations: int | None) -> None:
        if target_evaluations is None:
            self._target_evaluations = None
            return
        self._target_evaluations = int(target_evaluations)

    def is_duplicate_candidate(self, search_params: dict[str, Any]) -> bool:
        merged = self._merged_parameters(search_params)
        return parameter_hash(merged) in self._trial_cache

    def evaluate_candidate(
        self,
        search_params: dict[str, Any],
        *,
        record_cache_hit: bool = False,
    ) -> OptimizationTrial | None:
        merged = self._merged_parameters(search_params)
        cache_key = parameter_hash(merged)
        cached = self._trial_cache.get(cache_key)
        if cached is not None:
            if not record_cache_hit:
                return None
            replay = self._copy_trial(cached, cache_hit=True)
            self.trials.append(replay)
            self._after_trial_recorded(replay)
            return replay

        trial = self._execute_candidate(merged)
        self._trial_cache[cache_key] = trial
        self.trials.append(trial)
        if not (trial.status == "invalid" and trial.error == "constraint_rejected"):
            self._valid_unique_trials += 1
        self._after_trial_recorded(trial)
        return trial

    def result(self) -> OptimizationResult:
        self._emit_final_callbacks()
        return self._snapshot_result()

    def objective_value_for_minimize(self, trial: OptimizationTrial) -> float:
        if trial.status != "completed" or trial.objective_score is None:
            return INVALID_OBJECTIVE_PENALTY
        if self.objective.direction == "maximize":
            return -float(trial.objective_score)
        return float(trial.objective_score)

    def _after_trial_recorded(self, trial: OptimizationTrial) -> None:
        if self._data_bars is None and trial.result is not None:
            self._data_bars = len(trial.result.equity_curve)

        if self._early_stop is not None and not self._stop_requested:
            should_stop = self._early_stop(self._progress_snapshot())
            if not isinstance(should_stop, bool):
                raise TypeError("early_stop must return True or False")
            if should_stop:
                self._stop_requested = True
                self._stop_reason = "early_stop_requested"

        progress = self._progress_snapshot()
        total_trials = progress.total_trials

        if (
            self._progress_callback is not None
            and self._progress_every is not None
            and total_trials % self._progress_every == 0
        ):
            self._progress_callback(progress)
            self._last_progress_emit_trial_count = total_trials

        if (
            self._checkpoint_callback is not None
            and self._checkpoint_every is not None
            and total_trials % self._checkpoint_every == 0
        ):
            self._checkpoint_callback(self._snapshot_result())
            self._last_checkpoint_emit_trial_count = total_trials

    def _emit_final_callbacks(self) -> None:
        if self._finalized:
            return
        self._finalized = True

        total_trials = len(self.trials)
        if total_trials <= 0:
            return

        if (
            self._progress_callback is not None
            and self._last_progress_emit_trial_count != total_trials
        ):
            self._progress_callback(self._progress_snapshot())
            self._last_progress_emit_trial_count = total_trials

        if (
            self._checkpoint_callback is not None
            and self._last_checkpoint_emit_trial_count != total_trials
        ):
            self._checkpoint_callback(self._snapshot_result())
            self._last_checkpoint_emit_trial_count = total_trials

    def _snapshot_result(self) -> OptimizationResult:
        return OptimizationResult(
            optimizer_name=self.optimizer_name,
            objective=self.objective,
            search_space=self.search_space,
            fixed_params=dict(self.fixed_params),
            trials=list(self.trials),
            warnings=self._warnings(),
            metadata=self._metadata(),
        )

    def _warnings(self) -> list[OptimizationWarning]:
        warnings: list[OptimizationWarning] = []
        if self._data_bars is not None and self._valid_unique_trials > self._data_bars:
            warnings.append(
                OptimizationWarning(
                    code="optimization_trials_large_relative_to_data_length",
                    message=(
                        f"{self._valid_unique_trials} unique evaluated parameter sets were "
                        f"run over {self._data_bars} data bars; optimization results may "
                        "be overfit."
                    ),
                )
            )
        return warnings

    def _metadata(self) -> dict[str, Any]:
        progress = self._progress_snapshot()
        return {
            "total_trials": progress.total_trials,
            "completed_trials": progress.completed_trials,
            "invalid_trials": progress.invalid_trials,
            "failed_trials": progress.failed_trials,
            "cache_hit_trials": progress.cache_hit_trials,
            "unique_evaluated_trials": progress.unique_evaluated_trials,
            "data_bars": self._data_bars,
            "target_trial_count": self._target_trial_count,
            "target_evaluations": self._target_evaluations,
            "stopped_early": self._stop_requested,
            "stop_reason": self._stop_reason,
        }

    def _progress_snapshot(self) -> OptimizationProgress:
        completed_trials = [trial for trial in self.trials if trial.status == "completed"]
        return OptimizationProgress(
            optimizer_name=self.optimizer_name,
            objective_name=self.objective.name,
            total_trials=len(self.trials),
            completed_trials=len(completed_trials),
            invalid_trials=sum(trial.status == "invalid" for trial in self.trials),
            failed_trials=sum(trial.status == "failed" for trial in self.trials),
            cache_hit_trials=sum(bool(trial.cache_hit) for trial in self.trials),
            unique_evaluated_trials=self._valid_unique_trials,
            target_trial_count=self._target_trial_count,
            target_evaluations=self._target_evaluations,
            latest_trial=self.trials[-1] if self.trials else None,
            best_trial=self._best_completed_trial(completed_trials),
            stopped_early=self._stop_requested,
            stop_reason=self._stop_reason,
        )

    def _best_completed_trial(
        self,
        completed_trials: list[OptimizationTrial],
    ) -> OptimizationTrial | None:
        if not completed_trials:
            return None
        if self.objective.direction == "maximize":
            return max(completed_trials, key=lambda trial: (trial.objective_score, -trial.run_id))
        return min(completed_trials, key=lambda trial: (trial.objective_score, trial.run_id))

    def _execute_candidate(self, parameters: dict[str, Any]) -> OptimizationTrial:
        strategy_name = self.strategy_class.__name__

        if self.constraint is not None:
            try:
                constraint_result = self.constraint(dict(parameters))
            except Exception as exc:
                return self._build_failed_trial(parameters, strategy_name, exc)
            if not isinstance(constraint_result, bool):
                return self._build_failed_trial(
                    parameters,
                    strategy_name,
                    TypeError("constraint must return True or False"),
                )
            if not constraint_result:
                return self._build_invalid_trial(
                    parameters,
                    strategy_name,
                    error="constraint_rejected",
                )

        try:
            result = run_backtest(
                strategy_class=self.strategy_class,
                instrument=self.instrument,
                timeframe=self.timeframe,
                csv_path=self.csv_path,
                dataframe=self.dataframe,
                context_data=self.context_data,
                cash=self.cash,
                strategy_params=parameters,
                config=self.config,
            )
            analyzer = PerformanceAnalyzer(result)
            metric_values = analyzer.metrics.to_dict()
            objective_score = self._evaluate_objective(
                result=result,
                analyzer=analyzer,
                metrics=analyzer.metrics,
                metric_values=metric_values,
                parameters=parameters,
            )
            if objective_score is None:
                skipped = analyzer.metrics.skipped_metrics()
                reason = skipped.get(
                    self.objective.metric_name or "",
                    "objective_score_not_finite",
                )
                return self._build_invalid_trial(
                    parameters,
                    strategy_name,
                    error=reason,
                    result=result,
                    metrics=metric_values,
                    warning_count=len(analyzer.warnings()),
                )
            return OptimizationTrial(
                run_id=self._next_run_id(),
                optimizer_name=self.optimizer_name,
                status="completed",
                parameters=dict(parameters),
                objective_name=self.objective.name,
                objective_direction=self.objective.direction,
                objective_metric=self.objective.metric_name,
                objective_score=objective_score,
                strategy_name=result.strategy_name,
                instrument=self.instrument,
                timeframe=self.timeframe,
                timeframes=tuple(result.timeframes),
                metrics=dict(metric_values),
                warning_count=len(analyzer.warnings()),
                error=None,
                result=result,
                cache_hit=False,
            )
        except Exception as exc:
            return self._build_failed_trial(parameters, strategy_name, exc)

    def _evaluate_objective(
        self,
        *,
        result: BacktestResult,
        analyzer: PerformanceAnalyzer,
        metrics: PerformanceMetrics,
        metric_values: dict[str, Any],
        parameters: dict[str, Any],
    ) -> float | None:
        try:
            if self.objective.metric_name is not None:
                raw_score = metric_values.get(self.objective.metric_name)
            else:
                context = ObjectiveContext(
                    result=result,
                    analyzer=analyzer,
                    metrics=metrics,
                    parameters=dict(parameters),
                )
                raw_score = self.objective.evaluator(context)  # type: ignore[misc]
        except Exception as exc:
            raise RuntimeError(
                f"objective evaluation failed: {type(exc).__name__}: {exc}"
            ) from exc

        return _coerce_objective_score(raw_score)

    def _build_invalid_trial(
        self,
        parameters: dict[str, Any],
        strategy_name: str,
        *,
        error: str,
        result: BacktestResult | None = None,
        metrics: dict[str, Any] | None = None,
        warning_count: int | None = None,
    ) -> OptimizationTrial:
        return OptimizationTrial(
            run_id=self._next_run_id(),
            optimizer_name=self.optimizer_name,
            status="invalid",
            parameters=dict(parameters),
            objective_name=self.objective.name,
            objective_direction=self.objective.direction,
            objective_metric=self.objective.metric_name,
            objective_score=None,
            strategy_name=strategy_name,
            instrument=self.instrument,
            timeframe=self.timeframe,
            timeframes=tuple(result.timeframes) if result is not None else (self.timeframe,),
            metrics=dict(metrics or {}),
            warning_count=warning_count,
            error=error,
            result=result,
            cache_hit=False,
        )

    def _build_failed_trial(
        self,
        parameters: dict[str, Any],
        strategy_name: str,
        exc: Exception,
    ) -> OptimizationTrial:
        return OptimizationTrial(
            run_id=self._next_run_id(),
            optimizer_name=self.optimizer_name,
            status="failed",
            parameters=dict(parameters),
            objective_name=self.objective.name,
            objective_direction=self.objective.direction,
            objective_metric=self.objective.metric_name,
            objective_score=None,
            strategy_name=strategy_name,
            instrument=self.instrument,
            timeframe=self.timeframe,
            timeframes=(self.timeframe,),
            metrics={},
            warning_count=None,
            error=f"{type(exc).__name__}: {exc}",
            result=None,
            cache_hit=False,
        )

    def _copy_trial(self, trial: OptimizationTrial, *, cache_hit: bool) -> OptimizationTrial:
        return OptimizationTrial(
            run_id=self._next_run_id(),
            optimizer_name=trial.optimizer_name,
            status=trial.status,
            parameters=dict(trial.parameters),
            objective_name=trial.objective_name,
            objective_direction=trial.objective_direction,
            objective_metric=trial.objective_metric,
            objective_score=trial.objective_score,
            strategy_name=trial.strategy_name,
            instrument=trial.instrument,
            timeframe=trial.timeframe,
            timeframes=tuple(trial.timeframes),
            metrics=dict(trial.metrics),
            warning_count=trial.warning_count,
            error=trial.error,
            result=trial.result,
            cache_hit=cache_hit,
        )

    def _merged_parameters(self, search_params: dict[str, Any]) -> dict[str, Any]:
        merged = dict(self.fixed_params)
        merged.update(search_params)
        return merged

    def _next_run_id(self) -> int:
        return len(self.trials) + 1


def _normalize_interval(
    value: int | None,
    *,
    callback: Callable[..., Any] | None,
    name: str,
) -> int | None:
    if callback is None:
        if value is not None:
            raise ValueError(f"{name} requires the corresponding callback")
        return None
    if value is None:
        return 1
    interval = int(value)
    if interval <= 0:
        raise ValueError(f"{name} must be positive")
    return interval


def _as_float(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name!r} expects a numeric value, got {value!r}")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{name!r} expects a finite numeric value")
    return numeric


def _coerce_objective_score(value: Any) -> float | None:
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, pd.Timedelta):
        seconds = float(value.total_seconds())
        return seconds if math.isfinite(seconds) else None
    if isinstance(value, np.timedelta64):
        seconds = float(pd.to_timedelta(value).total_seconds())
        return seconds if math.isfinite(seconds) else None
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return numeric


def _quantize_to_step(value: float, *, step: float, base: float) -> float:
    offset = (value - base) / step
    return base + (round(offset) * step)


def _stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _stable_value(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_stable_value(item) for item in value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.isoformat()
    return value
