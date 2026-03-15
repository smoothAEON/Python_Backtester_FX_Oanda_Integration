from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import backtester.walk_forward as walk_forward
from backtester.run_backtest import run_backtest
from backtester.walk_forward import (
    DEFAULT_LEVERAGE,
    DEFAULT_CASH,
    INITIAL_TRAIN_BARS,
    LOOKBACK_BARS,
    OutputSink,
    RESEARCH_ONLY_STRATEGY_SPECS,
    STRATEGY_SPECS,
    TEST_BARS,
    TIMEFRAME,
    build_fold_anomalies,
    build_runtime_audit,
    build_sizing_audit,
    load_recent_frame,
    run_walk_forward,
)
from strategies import EmaRsiTrendStrategy


ROOT = Path(__file__).resolve().parents[2]


def _subset_spec(strategy_class: type, instruments: tuple[str, ...]):
    base_spec = next(spec for spec in STRATEGY_SPECS if spec.strategy_class is strategy_class)
    return replace(base_spec, instruments=instruments)


def test_default_walk_forward_matrix_is_live_safe_only():
    assert STRATEGY_SPECS
    assert all(spec.runtime_contract == "live_safe" for spec in STRATEGY_SPECS)
    assert {spec.strategy_class.__name__ for spec in STRATEGY_SPECS} == {
        "BollingerZscoreReversionStrategy",
        "EmaRsiTrendStrategy",
        "HybridRegimeStrategy",
        "IctOteSniperStrategy",
        "MacdAtrBreakoutStrategy",
        "SmcPullbackStrategy",
    }
    assert all(spec.runtime_contract == "research_only" for spec in RESEARCH_ONLY_STRATEGY_SPECS)


def test_walk_forward_runner_emits_updated_windows_and_search_spaces(tmp_path, monkeypatch):
    captured_calls: list[dict[str, object]] = []

    def fake_load_recent_frame(_repo_root, _instrument, _timeframe):
        return pd.DataFrame(
            {
                "time": pd.date_range(
                    "2024-01-01T00:00:00Z",
                    periods=LOOKBACK_BARS,
                    freq="4h",
                    tz="UTC",
                )
            }
        )

    def fake_run_grid_search(
        strategy_class,
        *,
        instrument,
        timeframe,
        dataframe,
        evaluation_dataframe,
        cash,
        config,
        search_space,
        objective,
    ):
        captured_calls.append(
            {
                "strategy": strategy_class.__name__,
                "instrument": instrument,
                "timeframe": timeframe,
                "train_bars": len(dataframe),
                "test_bars": len(evaluation_dataframe),
                "cash": cash,
                "leverage": config.execution.leverage,
                "objective": objective,
                "search_space": [spec.name for spec in search_space],
            }
        )
        result = SimpleNamespace(
            order_ledger=pd.DataFrame([{"ref": 1}]),
            closed_trade_ledger=pd.DataFrame([{"ref": 1}]),
            equity_curve=pd.DataFrame([{"value": cash + 100.0}]),
        )
        ranking = pd.DataFrame(
            [
                {
                    "strategy_name": strategy_class.__name__,
                    "status": "completed",
                    "parameters": {"fast_period": 3, "slow_period": 7},
                    "objective_score": 0.01,
                    "search_objective_score": 0.02,
                    "objective_score_source": "out_of_sample",
                }
            ]
        )
        trial = SimpleNamespace(
            result=result,
            parameters={"fast_period": 3, "slow_period": 7},
            objective_score=0.01,
            search_objective_score=0.02,
            objective_score_source="out_of_sample",
            metrics={"total_return": 0.01},
            warning_count=0,
        )

        class FakeOptimization:
            def ranking(self, include_invalid=True):
                assert include_invalid is True
                return ranking

            def best_trial(self):
                return trial

        return FakeOptimization()

    monkeypatch.setattr(walk_forward, "load_recent_frame", fake_load_recent_frame)
    monkeypatch.setattr(walk_forward, "run_grid_search", fake_run_grid_search)
    monkeypatch.setattr(
        walk_forward,
        "build_runtime_audit",
        lambda result: {
            "entry_ref_count": 1,
            "accepted_entry_count": 1,
            "completed_entry_count": 1,
            "stale_canceled_entry_count": 0,
            "same_bar_protective_activation_count": 0,
            "manual_exit_count": 0,
            "closed_trade_count": 1,
            "order_event_count": len(result.order_ledger),
            "entries_detected": True,
            "margin_or_rejected_entry_count": 0,
            "all_entries_margin_or_rejected": False,
            "final_entry_status_counts": {"Completed": 1},
        },
    )
    monkeypatch.setattr(
        walk_forward,
        "build_sizing_audit",
        lambda *_args, **_kwargs: {
            "checked_entries": 1,
            "passed_entries": 1,
            "failed_entries": 0,
            "protective_rows_checked": 0,
            "protective_sizing_clean": True,
            "protective_issues": [],
            "max_abs_risk_gap": 0.0,
            "max_allowed_gap": 0.0,
            "entry_checks": [],
        },
    )

    output_text = tmp_path / "walk_forward_output.txt"
    output_json = tmp_path / "walk_forward_summary.json"
    output_audit = tmp_path / "walk_forward_audit.md"
    sink = OutputSink(output_text)
    try:
        payload = run_walk_forward(
            ROOT,
            sink,
            output_json,
            output_audit,
            cash=DEFAULT_CASH,
            leverage=DEFAULT_LEVERAGE,
            strategy_specs=(_subset_spec(EmaRsiTrendStrategy, ("XAU_USD",)),),
        )
    finally:
        sink.close()

    written_payload = json.loads(output_json.read_text(encoding="utf-8"))
    output_text_body = output_text.read_text(encoding="utf-8")

    assert payload["lookback_bars"] == LOOKBACK_BARS
    assert written_payload["lookback_bars"] == LOOKBACK_BARS
    assert written_payload["initial_train_bars"] == INITIAL_TRAIN_BARS
    assert written_payload["test_bars"] == TEST_BARS
    assert written_payload["folds"] == len(captured_calls)
    assert written_payload["timeframe"] == TIMEFRAME
    assert written_payload["strategy_specs"][0]["search_space"] == (
        "fast_period=[2, 3, 4], slow_period=[5, 7, 9]"
    )
    assert [call["train_bars"] for call in captured_calls] == [480, 640, 800]
    assert [call["test_bars"] for call in captured_calls] == [160, 160, 160]
    assert all(call["objective"] == "total_return" for call in captured_calls)
    assert all(call["leverage"] == DEFAULT_LEVERAGE for call in captured_calls)
    assert (
        f"lookback_bars={LOOKBACK_BARS} initial_train_bars={INITIAL_TRAIN_BARS} "
        f"test_bars={TEST_BARS} folds={len(captured_calls)}"
    ) in output_text_body
    assert "Search Space: fast_period=[2, 3, 4], slow_period=[5, 7, 9]" in output_text_body
    assert output_audit.exists()


def test_margin_only_entry_folds_surface_entry_execution_failures():
    frame = load_recent_frame(ROOT, "XAU_USD", TIMEFRAME)
    window = frame.iloc[-TEST_BARS:].reset_index(drop=True)
    result = run_backtest(
        EmaRsiTrendStrategy,
        instrument="XAU_USD",
        timeframe=TIMEFRAME,
        dataframe=window,
        cash=DEFAULT_CASH,
        strategy_params={"fixed_units": 1_000.0},
    )

    runtime_audit = build_runtime_audit(result)
    sizing_audit = build_sizing_audit(
        result,
        strategy_class=EmaRsiTrendStrategy,
        instrument="XAU_USD",
        parameters={"fixed_units": 1_000.0},
    )
    anomalies = build_fold_anomalies(
        [
            {
                "strategy": "EmaRsiTrendStrategy",
                "instrument": "XAU_USD",
                "fold": 1,
                "status": "completed",
                "objective_score": 0.0,
                "search_objective_score": 0.0,
                "closed_trades": 0,
                "flat_grid": False,
                "search_vs_oos_sign_flip": False,
                "runtime_audit": runtime_audit,
                "sizing_audit": sizing_audit,
            }
        ]
    )

    assert runtime_audit["all_entries_margin_or_rejected"] is True
    assert any(item["type"] == "entry_execution_failure" for item in anomalies)
