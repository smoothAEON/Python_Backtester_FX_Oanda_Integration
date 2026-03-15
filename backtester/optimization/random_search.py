"""Random-search optimization."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import backtrader as bt
import numpy as np
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
    sample_parameter,
    validate_random_parameter,
)


def run_random_search(
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
    trial_count: int,
    seed: int | None = None,
    max_attempts: int | None = None,
    progress_every: int | None = None,
    progress_callback: ProgressCallback | None = None,
    checkpoint_every: int | None = None,
    checkpoint_callback: CheckpointCallback | None = None,
    early_stop: EarlyStopCallback | None = None,
    allow_research_only: bool = False,
) -> OptimizationResult:
    """Run a reproducible random search over mixed parameter spaces."""

    if trial_count <= 0:
        raise ValueError("trial_count must be positive")

    if max_attempts is None:
        max_attempts = max(trial_count * 20, 100)
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")

    session = _OptimizationSession(
        optimizer_name="random_search",
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
        target_trial_count=trial_count,
        target_evaluations=None,
    )
    for spec in session.search_space:
        validate_random_parameter(spec)

    rng = np.random.default_rng(seed)
    attempts = 0
    while session.valid_unique_trials < trial_count:
        if attempts >= max_attempts:
            raise RuntimeError(
                "Random search exhausted max_attempts before reaching the requested "
                f"trial_count={trial_count}"
            )
        attempts += 1

        candidate = {spec.name: sample_parameter(spec, rng) for spec in session.search_space}
        if session.is_duplicate_candidate(candidate):
            continue
        session.evaluate_candidate(candidate)
        if session.should_stop:
            break

    return session.result()
