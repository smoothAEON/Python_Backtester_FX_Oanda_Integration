"""scipy-backed bounded optimization."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import backtrader as bt
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from backtester.config import BacktestConfig

from ._core import (
    CheckpointCallback,
    EarlyStopCallback,
    ObjectiveSpec,
    OptimizationResult,
    ParameterSpec,
    ProgressCallback,
    _OptimizationSession,
    build_scipy_vector,
    normalize_runtime_value,
    validate_scipy_parameter,
)


class _ScipyEarlyStop(RuntimeError):
    """Internal sentinel used to stop scipy minimization cleanly."""


def run_scipy_optimization(
    strategy_class: type[bt.Strategy],
    instrument: str,
    timeframe: str,
    *,
    csv_path: str | None = None,
    dataframe: pd.DataFrame | None = None,
    context_data: dict[str, str | Path | pd.DataFrame] | None = None,
    conversion_data: dict[str, str | Path | pd.DataFrame] | None = None,
    evaluation_csv_path: str | None = None,
    evaluation_dataframe: pd.DataFrame | None = None,
    evaluation_context_data: dict[str, str | Path | pd.DataFrame] | None = None,
    evaluation_conversion_data: dict[str, str | Path | pd.DataFrame] | None = None,
    holdout_fraction: float | None = None,
    cash: float = 10_000.0,
    config: BacktestConfig | None = None,
    fixed_params: dict[str, Any] | None = None,
    search_space: Sequence[ParameterSpec],
    objective: str | ObjectiveSpec = "calmar_ratio",
    constraint: Callable[[dict[str, Any]], bool] | None = None,
    x0: dict[str, float] | None = None,
    max_evaluations: int,
    progress_every: int | None = None,
    progress_callback: ProgressCallback | None = None,
    checkpoint_every: int | None = None,
    checkpoint_callback: CheckpointCallback | None = None,
    early_stop: EarlyStopCallback | None = None,
    allow_research_only: bool = False,
) -> OptimizationResult:
    """Run bounded scipy optimization and record every evaluated point."""

    if max_evaluations <= 0:
        raise ValueError("max_evaluations must be positive")

    session = _OptimizationSession(
        optimizer_name="scipy_optimization",
        strategy_class=strategy_class,
        instrument=instrument,
        timeframe=timeframe,
        csv_path=csv_path,
        dataframe=dataframe,
        context_data=context_data,
        conversion_data=conversion_data,
        evaluation_csv_path=evaluation_csv_path,
        evaluation_dataframe=evaluation_dataframe,
        evaluation_context_data=evaluation_context_data,
        evaluation_conversion_data=evaluation_conversion_data,
        holdout_fraction=holdout_fraction,
        cash=cash,
        config=config,
        fixed_params=fixed_params,
        search_space=search_space,
        objective=objective,
        constraint=constraint,
        progress_every=progress_every,
        progress_callback=progress_callback,
        checkpoint_every=checkpoint_every,
        checkpoint_callback=checkpoint_callback,
        early_stop=early_stop,
        allow_research_only=allow_research_only,
        target_trial_count=None,
        target_evaluations=max_evaluations,
    )

    for spec in session.search_space:
        validate_scipy_parameter(spec)

    scipy_bounds = [spec.bounds for spec in session.search_space]
    initial = build_scipy_vector(session.search_space, x0=x0)

    def objective_fn(vector: np.ndarray) -> float:
        candidate = {
            spec.name: normalize_runtime_value(spec, raw_value, clip=True)
            for spec, raw_value in zip(session.search_space, vector, strict=True)
        }
        trial = session.evaluate_candidate(candidate, record_cache_hit=True)
        if trial is None:
            raise RuntimeError("scipy optimization unexpectedly skipped a candidate")
        if session.should_stop:
            raise _ScipyEarlyStop(session.stop_reason or "early_stop_requested")
        return session.objective_value_for_minimize(trial)

    try:
        minimize(
            objective_fn,
            initial,
            method="Powell",
            bounds=scipy_bounds,
            options={"maxfev": max_evaluations, "disp": False},
        )
    except _ScipyEarlyStop:
        pass

    return session.result()
