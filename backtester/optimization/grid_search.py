"""Deterministic grid-search optimization."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from pathlib import Path
from itertools import product
from typing import Any

import backtrader as bt
import pandas as pd

from backtester.config import BacktestConfig

from ._core import (
    CheckpointCallback,
    EarlyStopCallback,
    ObjectiveSpec,
    OptimizationResult,
    ParameterSpec,
    ProgressCallback,
    _OptimizationSession,
    validate_grid_parameter,
)


def run_grid_search(
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
    max_grid_size: int = 1000,
    progress_every: int | None = None,
    progress_callback: ProgressCallback | None = None,
    checkpoint_every: int | None = None,
    checkpoint_callback: CheckpointCallback | None = None,
    early_stop: EarlyStopCallback | None = None,
    allow_research_only: bool = False,
) -> OptimizationResult:
    """Run a deterministic grid search over explicit parameter values."""

    if max_grid_size <= 0:
        raise ValueError("max_grid_size must be positive")

    session = _OptimizationSession(
        optimizer_name="grid_search",
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
        target_evaluations=None,
    )

    value_sets = [validate_grid_parameter(spec) for spec in session.search_space]
    raw_grid_size = math.prod(len(values) for values in value_sets)
    if raw_grid_size > max_grid_size:
        raise ValueError(
            f"Grid search size {raw_grid_size} exceeds max_grid_size={max_grid_size}"
        )
    session.set_target_trial_count(raw_grid_size)

    for combination in product(*value_sets):
        candidate = {
            spec.name: value
            for spec, value in zip(session.search_space, combination, strict=True)
        }
        session.evaluate_candidate(candidate)
        if session.should_stop:
            break

    return session.result()
