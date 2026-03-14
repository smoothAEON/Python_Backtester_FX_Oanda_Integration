from __future__ import annotations

import math

import backtrader as bt
import numpy as np
import pandas as pd
import pytest

import backtester.optimization.scipy_optimizer as scipy_optimizer_module
from backtester.optimization import (
    ObjectiveSpec,
    ParameterSpec,
    run_grid_search,
    run_random_search,
    run_scipy_optimization,
)


class WindowTradeStrategy(bt.Strategy):
    run_counter = 0

    params = (
        ("entry_bar", 1),
        ("exit_bar", 3),
    )

    def __init__(self):
        type(self).run_counter += 1

    def next(self):
        if len(self) == int(self.p.entry_bar) and not self.position:
            self.buy(size=1)
        elif len(self) == int(self.p.exit_bar) and self.position:
            self.sell(size=1)


class ExplodingWindowTradeStrategy(WindowTradeStrategy):
    params = (
        ("entry_bar", 1),
        ("exit_bar", 3),
        ("explode", False),
    )

    def next(self):
        if bool(self.p.explode):
            raise RuntimeError("requested explosion")
        super().next()


def _phase5_frame(make_oanda_frame):
    return make_oanda_frame(
        [
            {"open": 100.0, "high": 100.4, "low": 99.8, "close": 100.0},
            {"open": 102.0, "high": 102.4, "low": 101.8, "close": 102.0},
            {"open": 104.0, "high": 104.3, "low": 103.7, "close": 104.0},
            {"open": 103.0, "high": 103.2, "low": 102.5, "close": 103.0},
            {"open": 101.0, "high": 101.2, "low": 100.7, "close": 101.0},
            {"open": 99.0, "high": 99.4, "low": 98.8, "close": 99.0},
        ]
    )


def _sorted_parameter_items(result_table):
    return [tuple(sorted(parameters.items())) for parameters in result_table["parameters"]]


def test_grid_search_enumerates_in_declared_order_and_ranks_best_run(make_oanda_frame):
    frame = _phase5_frame(make_oanda_frame)

    result = run_grid_search(
        WindowTradeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        search_space=[
            ParameterSpec("entry_bar", "int", grid_values=(1, 2)),
            ParameterSpec("exit_bar", "int", grid_values=(1, 3)),
        ],
        objective="total_return",
        constraint=lambda parameters: parameters["exit_bar"] > parameters["entry_bar"],
    )

    table = result.table()
    ranking = result.ranking(allow_in_sample=True)

    assert len(table) == 4
    assert list(table["status"]) == ["invalid", "completed", "invalid", "completed"]
    assert table.iloc[0]["error"] == "constraint_rejected"
    assert pd.isna(table.iloc[1]["error"])
    assert table.iloc[2]["error"] == "constraint_rejected"
    assert pd.isna(table.iloc[3]["error"])
    assert list(table["parameters"]) == [
        {"entry_bar": 1, "exit_bar": 1},
        {"entry_bar": 1, "exit_bar": 3},
        {"entry_bar": 2, "exit_bar": 1},
        {"entry_bar": 2, "exit_bar": 3},
    ]
    assert len(ranking) == 2
    assert ranking.iloc[0]["parameters"] == {"entry_bar": 1, "exit_bar": 3}
    assert result.best_trial(allow_in_sample=True).parameters == {"entry_bar": 1, "exit_bar": 3}
    assert result.best_result(allow_in_sample=True).parameters == {"entry_bar": 1, "exit_bar": 3}


def test_random_search_is_reproducible_and_avoids_duplicate_parameter_sets(make_oanda_frame):
    frame = _phase5_frame(make_oanda_frame)
    search_space = [
        ParameterSpec("entry_bar", "int", bounds=(1, 2)),
        ParameterSpec("exit_bar", "int", bounds=(3, 5)),
    ]

    first = run_random_search(
        WindowTradeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        search_space=search_space,
        objective="total_return",
        trial_count=4,
        seed=7,
    )
    second = run_random_search(
        WindowTradeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        search_space=search_space,
        objective="total_return",
        trial_count=4,
        seed=7,
    )

    first_table = first.table()
    second_table = second.table()

    assert _sorted_parameter_items(first_table) == _sorted_parameter_items(second_table)
    assert list(first_table["objective_score"]) == list(second_table["objective_score"])
    assert len(set(_sorted_parameter_items(first_table))) == len(first_table)
    assert first_table["cache_hit"].eq(False).all()
    assert _sorted_parameter_items(first.ranking(allow_in_sample=True)) == _sorted_parameter_items(
        second.ranking(allow_in_sample=True)
    )


def test_scipy_optimizer_clips_bounds_rounds_ints_and_records_cached_repeats(
    make_oanda_frame,
    monkeypatch,
):
    frame = _phase5_frame(make_oanda_frame)
    WindowTradeStrategy.run_counter = 0

    calls: list[tuple[float, float]] = []

    def fake_minimize(fun, x0, method, bounds, options):
        assert method == "Powell"
        assert options == {"maxfev": 8, "disp": False}
        assert list(x0) == [2.0, 4.0]
        assert bounds == [(1.0, 2.0), (3.0, 5.0)]

        for point in (
            np.asarray([0.2, 9.9], dtype=float),
            np.asarray([1.8, 3.1], dtype=float),
            np.asarray([1.8, 3.1], dtype=float),
        ):
            calls.append((float(point[0]), float(point[1])))
            fun(point)

        return object()

    monkeypatch.setattr(scipy_optimizer_module, "minimize", fake_minimize)

    result = run_scipy_optimization(
        WindowTradeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        search_space=[
            ParameterSpec("entry_bar", "int", bounds=(1, 2)),
            ParameterSpec("exit_bar", "int", bounds=(3, 5)),
        ],
        objective="total_return",
        max_evaluations=8,
    )

    table = result.table()

    assert calls == [(0.2, 9.9), (1.8, 3.1), (1.8, 3.1)]
    assert list(table["parameters"]) == [
        {"entry_bar": 1, "exit_bar": 5},
        {"entry_bar": 2, "exit_bar": 3},
        {"entry_bar": 2, "exit_bar": 3},
    ]
    assert list(table["cache_hit"]) == [False, False, True]
    assert WindowTradeStrategy.run_counter == 2
    assert len(table) == 3
    assert result.best_trial(allow_in_sample=True).parameters == {"entry_bar": 2, "exit_bar": 3}


def test_callable_objective_receives_context_and_controls_ranking(make_oanda_frame):
    frame = _phase5_frame(make_oanda_frame)
    seen_parameters: list[dict] = []

    def custom_objective(context):
        assert context.result.strategy_name == "WindowTradeStrategy"
        assert context.metrics.total_return() is not None
        seen_parameters.append(dict(context.parameters))
        return float(context.parameters["entry_bar"]) - (10.0 * float(context.parameters["exit_bar"]))

    result = run_grid_search(
        WindowTradeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        search_space=[
            ParameterSpec("entry_bar", "int", grid_values=(1, 2)),
            ParameterSpec("exit_bar", "int", grid_values=(3, 4)),
        ],
        objective=ObjectiveSpec(
            name="entry_bias",
            direction="maximize",
            evaluator=custom_objective,
        ),
    )

    ranking = result.ranking(allow_in_sample=True)

    assert len(seen_parameters) == 4
    assert ranking.iloc[0]["objective_name"] == "entry_bias"
    assert result.best_trial(allow_in_sample=True).parameters == {"entry_bar": 2, "exit_bar": 3}


def test_non_finite_callable_objective_marks_trial_invalid_and_excludes_it_from_ranking(
    make_oanda_frame,
):
    frame = _phase5_frame(make_oanda_frame)

    result = run_grid_search(
        WindowTradeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        fixed_params={"exit_bar": 3},
        search_space=[ParameterSpec("entry_bar", "int", grid_values=(1, 2))],
        objective=ObjectiveSpec(
            name="maybe_nan",
            direction="maximize",
            evaluator=lambda context: math.nan if context.parameters["entry_bar"] == 1 else 1.0,
        ),
    )

    table = result.table()
    ranking = result.ranking(allow_in_sample=True)

    assert list(table["status"]) == ["invalid", "completed"]
    assert table.iloc[0]["error"] == "objective_score_not_finite"
    assert pd.isna(table.iloc[1]["error"])
    assert len(ranking) == 1
    assert result.best_trial(allow_in_sample=True).parameters == {"exit_bar": 3, "entry_bar": 2}


def test_failed_trials_stay_in_table_but_are_excluded_from_ranking(make_oanda_frame):
    frame = _phase5_frame(make_oanda_frame)

    result = run_grid_search(
        ExplodingWindowTradeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        fixed_params={"entry_bar": 1, "exit_bar": 3},
        search_space=[ParameterSpec("explode", "categorical", grid_values=(False, True))],
        objective="total_return",
    )

    table = result.table()
    ranking = result.ranking(allow_in_sample=True)

    assert list(table["status"]) == ["completed", "failed"]
    assert "RuntimeError: requested explosion" in str(table.iloc[1]["error"])
    assert len(ranking) == 1
    assert result.best_trial(allow_in_sample=True).parameters == {
        "entry_bar": 1,
        "exit_bar": 3,
        "explode": False,
    }


def test_in_sample_optimization_blocks_ranked_best_run_claims(make_oanda_frame):
    frame = _phase5_frame(make_oanda_frame)

    result = run_grid_search(
        WindowTradeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        fixed_params={"exit_bar": 3},
        search_space=[ParameterSpec("entry_bar", "int", grid_values=(1, 2))],
        objective="total_return",
    )

    assert result.can_rank_out_of_sample() is False
    assert result.metadata["ranking_available"] is False
    with pytest.raises(ValueError, match="out-of-sample evaluation"):
        result.ranking()
    with pytest.raises(ValueError, match="out-of-sample evaluation"):
        result.best_trial()


def test_grid_search_can_publish_out_of_sample_ranking_from_explicit_evaluation_data(
    make_oanda_frame,
):
    training = _phase5_frame(make_oanda_frame)
    evaluation = make_oanda_frame(
        [
            {"open": 100.0, "high": 100.4, "low": 99.8, "close": 100.0},
            {"open": 120.0, "high": 120.4, "low": 119.8, "close": 120.0},
            {"open": 100.0, "high": 100.4, "low": 99.8, "close": 100.0},
            {"open": 130.0, "high": 130.4, "low": 129.8, "close": 130.0},
            {"open": 129.0, "high": 129.3, "low": 128.7, "close": 129.0},
            {"open": 128.0, "high": 128.3, "low": 127.7, "close": 128.0},
        ]
    )

    result = run_grid_search(
        WindowTradeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=training,
        evaluation_dataframe=evaluation,
        search_space=[
            ParameterSpec("entry_bar", "int", grid_values=(1, 2)),
            ParameterSpec("exit_bar", "int", grid_values=(3,)),
        ],
        objective="total_return",
    )

    ranking = result.ranking()

    assert result.can_rank_out_of_sample() is True
    assert result.metadata["ranking_available"] is True
    assert result.metadata["evaluation_mode"] == "explicit_evaluation"
    assert len(ranking) == 2
    assert ranking.iloc[0]["parameters"] == {"entry_bar": 2, "exit_bar": 3}
    assert ranking.iloc[0]["objective_score_source"] == "out_of_sample"
    assert ranking.iloc[0]["search_objective_score"] is not None
    assert result.best_trial().parameters == {"entry_bar": 2, "exit_bar": 3}


def test_holdout_fraction_builds_contiguous_out_of_sample_split(make_oanda_frame):
    frame = _phase5_frame(make_oanda_frame)

    result = run_grid_search(
        WindowTradeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        holdout_fraction=0.5,
        fixed_params={"exit_bar": 3},
        search_space=[ParameterSpec("entry_bar", "int", grid_values=(1, 2))],
        objective="total_return",
    )

    ranking = result.ranking()

    assert result.can_rank_out_of_sample() is True
    assert result.metadata["evaluation_mode"] == "contiguous_holdout"
    assert result.metadata["ranking_available"] is True
    assert not ranking.empty


def test_optimization_rejects_bad_objectives_overlaps_and_categorical_scipy_specs(
    make_oanda_frame,
):
    frame = _phase5_frame(make_oanda_frame)

    with pytest.raises(ValueError, match="Unknown objective metric"):
        run_grid_search(
            WindowTradeStrategy,
            instrument="XAU_USD",
            timeframe="H1",
            dataframe=frame,
            search_space=[ParameterSpec("entry_bar", "int", grid_values=(1, 2))],
            objective="not_a_metric",
        )

    with pytest.raises(ValueError, match="fixed_params cannot overlap"):
        run_grid_search(
            WindowTradeStrategy,
            instrument="XAU_USD",
            timeframe="H1",
            dataframe=frame,
            fixed_params={"entry_bar": 1},
            search_space=[ParameterSpec("entry_bar", "int", grid_values=(1, 2))],
            objective="total_return",
        )

    with pytest.raises(ValueError, match="does not support categorical"):
        run_scipy_optimization(
            WindowTradeStrategy,
            instrument="XAU_USD",
            timeframe="H1",
            dataframe=frame,
            search_space=[ParameterSpec("mode", "categorical", grid_values=("a", "b"))],
            objective="total_return",
            max_evaluations=5,
        )


def test_random_search_raises_when_unique_space_is_exhausted(make_oanda_frame):
    frame = _phase5_frame(make_oanda_frame)

    with pytest.raises(RuntimeError, match="exhausted max_attempts"):
        run_random_search(
            WindowTradeStrategy,
            instrument="XAU_USD",
            timeframe="H1",
            dataframe=frame,
            search_space=[ParameterSpec("entry_bar", "int", bounds=(1, 1))],
            fixed_params={"exit_bar": 3},
            objective="total_return",
            trial_count=2,
            seed=3,
            max_attempts=5,
        )


def test_grid_search_supports_progress_checkpoint_and_early_stop(make_oanda_frame):
    frame = _phase5_frame(make_oanda_frame)
    WindowTradeStrategy.run_counter = 0
    progress_events: list[tuple[int, int, bool, int | None]] = []
    checkpoint_events: list[tuple[int, bool]] = []

    def on_progress(progress):
        best_entry_bar = None
        if progress.best_trial is not None:
            best_entry_bar = int(progress.best_trial.parameters["entry_bar"])
        progress_events.append(
            (
                progress.total_trials,
                progress.target_trial_count or 0,
                progress.stopped_early,
                best_entry_bar,
            )
        )

    def on_checkpoint(snapshot):
        checkpoint_events.append(
            (
                int(snapshot.metadata["total_trials"]),
                bool(snapshot.metadata["stopped_early"]),
            )
        )

    result = run_grid_search(
        WindowTradeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        fixed_params={"exit_bar": 6},
        search_space=[ParameterSpec("entry_bar", "int", grid_values=(1, 2, 3, 4, 5))],
        objective="total_return",
        progress_every=2,
        progress_callback=on_progress,
        checkpoint_every=2,
        checkpoint_callback=on_checkpoint,
        early_stop=lambda progress: progress.completed_trials >= 3,
    )

    assert WindowTradeStrategy.run_counter == 3
    assert [event[:3] for event in progress_events] == [(2, 5, False), (3, 5, True)]
    assert progress_events[-1][3] is not None
    assert checkpoint_events == [(2, False), (3, True)]
    assert result.metadata["stopped_early"] is True
    assert result.metadata["stop_reason"] == "early_stop_requested"
    assert result.metadata["total_trials"] == 3


def test_optimization_result_surfaces_large_trial_count_warning(make_oanda_frame):
    frame = _phase5_frame(make_oanda_frame)

    result = run_grid_search(
        WindowTradeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        fixed_params={"exit_bar": 6},
        search_space=[ParameterSpec("entry_bar", "int", grid_values=(1, 2, 3, 4, 5, 6, 7))],
        objective="total_return",
    )

    assert result.metadata["unique_evaluated_trials"] == 7
    assert result.metadata["data_bars"] == 6
    assert [warning.code for warning in result.warnings] == [
        "optimization_trials_large_relative_to_data_length"
    ]


def test_optimization_rejects_control_intervals_without_callbacks(make_oanda_frame):
    frame = _phase5_frame(make_oanda_frame)

    with pytest.raises(ValueError, match="progress_every requires"):
        run_grid_search(
            WindowTradeStrategy,
            instrument="XAU_USD",
            timeframe="H1",
            dataframe=frame,
            search_space=[ParameterSpec("entry_bar", "int", grid_values=(1, 2))],
            fixed_params={"exit_bar": 3},
            objective="total_return",
            progress_every=2,
        )

    with pytest.raises(ValueError, match="checkpoint_every requires"):
        run_grid_search(
            WindowTradeStrategy,
            instrument="XAU_USD",
            timeframe="H1",
            dataframe=frame,
            search_space=[ParameterSpec("entry_bar", "int", grid_values=(1, 2))],
            fixed_params={"exit_bar": 3},
            objective="total_return",
            checkpoint_every=2,
        )
