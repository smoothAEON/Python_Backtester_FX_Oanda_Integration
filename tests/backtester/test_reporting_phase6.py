from __future__ import annotations

import json

import pandas as pd

from backtester.core.result import BacktestResult
from backtester.optimization import (
    ObjectiveSpec,
    OptimizationResult,
    OptimizationTrial,
    OptimizationWarning,
    ParameterSpec,
)
from backtester.performance import PerformanceAnalyzer
from backtester.reporting import (
    BacktestCharts,
    build_backtest_json_payload,
    build_optimization_json_payload,
    export_backtest_artifacts,
    export_optimization_artifacts,
)

ORDER_COLUMNS = [
    "event_time",
    "ref",
    "parent_ref",
    "role",
    "thesis_ref",
    "status",
    "status_name",
    "order_name",
    "is_buy",
    "size",
    "created_time",
    "created_price",
    "created_pricelimit",
    "executed_time",
    "executed_size",
    "executed_price",
    "executed_value",
    "executed_commission",
    "executed_pnl",
    "remaining_size",
    "execution_side",
    "trigger_side",
    "same_bar_policy",
    "sizing_method",
    "sizing_raw_size",
    "sizing_final_size",
    "sizing_equity",
    "sizing_stop_price",
    "sizing_stop_distance",
    "sizing_reason",
    "sizing_details",
]

TRADE_COLUMNS = [
    "event_time",
    "ref",
    "tradeid",
    "status",
    "status_name",
    "size",
    "price",
    "value",
    "commission",
    "pnl",
    "pnlcomm",
    "isopen",
    "isclosed",
    "justopened",
    "barlen",
    "dtopen",
    "dtclose",
]

CLOSED_TRADE_COLUMNS = [
    "ref",
    "tradeid",
    "entry_order_ref",
    "exit_order_ref",
    "entry_time",
    "exit_time",
    "direction",
    "entry_price",
    "exit_price",
    "size",
    "gross_pnl",
    "net_pnl",
    "commission",
    "bars_held",
    "hold_time",
    "exit_reason",
    "exit_order_name",
]

EQUITY_COLUMNS = [
    "time",
    "cash",
    "value",
    "position_size",
    "close",
    "bid_close",
    "ask_close",
]


def _build_backtest_result(
    *,
    value_count: int = 80,
    frequency: str = "D",
    include_closed_trades: bool = True,
    include_trade_events: bool = True,
    parameters: dict | None = None,
) -> BacktestResult:
    times = pd.date_range("2024-01-01", periods=value_count, freq=frequency, tz="UTC")
    values = [1000.0]
    for index in range(1, value_count):
        step = 12.0 if index % 7 else -6.0
        values.append(values[-1] + step)

    equity_curve = pd.DataFrame(
        {
            "time": times,
            "cash": values,
            "value": values,
            "position_size": [0.0] * value_count,
            "close": values,
            "bid_close": [value - 0.1 for value in values],
            "ask_close": [value + 0.1 for value in values],
        },
        columns=EQUITY_COLUMNS,
    )

    order_ledger = pd.DataFrame.from_records(
        [
            {
                "event_time": pd.Timestamp("2024-01-05T00:00:00Z"),
                "ref": 1,
                "parent_ref": None,
                "role": "entry",
                "thesis_ref": 100,
                "status": 4,
                "status_name": "Completed",
                "order_name": "Market",
                "is_buy": True,
                "size": 1.0,
                "created_time": pd.Timestamp("2024-01-05T00:00:00Z"),
                "created_price": 100.2,
                "created_pricelimit": 0.0,
                "executed_time": pd.Timestamp("2024-01-05T00:00:00Z"),
                "executed_size": 1.0,
                "executed_price": 100.3,
                "executed_value": 100.3,
                "executed_commission": 0.0,
                "executed_pnl": 0.0,
                "remaining_size": 0.0,
                "execution_side": "ask",
                "trigger_side": None,
                "same_bar_policy": "worst_case_first",
                "sizing_method": "risk_percent",
                "sizing_raw_size": float("nan"),
                "sizing_final_size": 1.0,
                "sizing_equity": 1000.0,
                "sizing_stop_price": 95.0,
                "sizing_stop_distance": 5.3,
                "sizing_reason": None,
                "sizing_details": {
                    "risk": {
                        "fraction": 0.01,
                        "max_loss": float("nan"),
                    },
                    "tags": ["alpha", None],
                },
            }
        ],
        columns=ORDER_COLUMNS,
    )

    trade_ledger = pd.DataFrame.from_records(
        [
            {
                "event_time": pd.Timestamp("2024-01-10T00:00:00Z"),
                "ref": 1,
                "tradeid": 0,
                "status": 2,
                "status_name": "Closed",
                "size": 1.0,
                "price": 100.3,
                "value": 100.3,
                "commission": 0.0,
                "pnl": 12.0,
                "pnlcomm": 12.0,
                "isopen": False,
                "isclosed": True,
                "justopened": False,
                "barlen": 5,
                "dtopen": pd.Timestamp("2024-01-05T00:00:00Z"),
                "dtclose": pd.Timestamp("2024-01-10T00:00:00Z"),
            }
        ]
        if include_trade_events
        else [],
        columns=TRADE_COLUMNS,
    )

    closed_trade_ledger = pd.DataFrame.from_records(
        [
            {
                "ref": 1,
                "tradeid": 0,
                "entry_order_ref": 1,
                "exit_order_ref": 2,
                "entry_time": pd.Timestamp("2024-01-05T00:00:00Z"),
                "exit_time": pd.Timestamp("2024-01-10T00:00:00Z"),
                "direction": "long",
                "entry_price": 100.3,
                "exit_price": 112.3,
                "size": 1.0,
                "gross_pnl": 12.0,
                "net_pnl": 12.0,
                "commission": 0.0,
                "bars_held": 5,
                "hold_time": pd.Timedelta(days=5),
                "exit_reason": "take_profit",
                "exit_order_name": "Limit",
            },
            {
                "ref": 2,
                "tradeid": 1,
                "entry_order_ref": 3,
                "exit_order_ref": 4,
                "entry_time": pd.Timestamp("2024-02-01T00:00:00Z"),
                "exit_time": pd.Timestamp("2024-02-12T00:00:00Z"),
                "direction": "short",
                "entry_price": 109.0,
                "exit_price": 105.0,
                "size": 1.0,
                "gross_pnl": 4.0,
                "net_pnl": 4.0,
                "commission": 0.0,
                "bars_held": 11,
                "hold_time": pd.Timedelta(days=11),
                "exit_reason": "manual_exit",
                "exit_order_name": "Market",
            },
        ]
        if include_closed_trades
        else [],
        columns=CLOSED_TRADE_COLUMNS,
    )

    return BacktestResult(
        strategy_name="ReportingStrategy",
        instrument="XAU_USD",
        timeframe="H1",
        parameters=dict(parameters or {"ema_fast": 20, "ema_slow": 50}),
        start_cash=float(values[0]),
        end_cash=float(values[-1]),
        end_value=float(values[-1]),
        order_ledger=order_ledger,
        trade_ledger=trade_ledger,
        closed_trade_ledger=closed_trade_ledger,
        equity_curve=equity_curve,
        analyzer_snapshots={},
        execution_policy={
            "buy_side": "ask",
            "sell_side": "bid",
            "same_bar_policy": "worst_case_first",
            "commission": 0.0,
            "slippage": 0.0,
            "account_currency": "USD",
            "margin_model": "notional_margin",
            "leverage": 30.0,
            "point_value": 1.0,
        },
    )


def _build_low_sample_result() -> BacktestResult:
    return _build_backtest_result(
        value_count=2,
        frequency="D",
        include_closed_trades=False,
        include_trade_events=False,
        parameters={},
    )


def _build_optimization_result() -> OptimizationResult:
    trials = [
        OptimizationTrial(
            run_id=1,
            optimizer_name="grid_search",
            status="completed",
            parameters={"entry_bar": 1, "exit_bar": 3},
            objective_name="calmar_ratio",
            objective_direction="maximize",
            objective_metric="calmar_ratio",
            objective_score=1.8,
            strategy_name="ReportingStrategy",
            instrument="XAU_USD",
            timeframe="H1",
            metrics={
                "total_return": 0.18,
                "cagr": 0.30,
                "sharpe_ratio": 1.1,
                "sortino_ratio": 1.4,
                "calmar_ratio": 1.8,
                "max_drawdown": 0.10,
                "win_rate": 0.6,
                "profit_factor": 1.4,
                "expectancy": 3.0,
                "total_closed_trades": 12,
            },
            warning_count=1,
            error=None,
            result=None,
            cache_hit=False,
            objective_score_source="out_of_sample",
            search_objective_score=1.5,
        ),
        OptimizationTrial(
            run_id=2,
            optimizer_name="grid_search",
            status="completed",
            parameters={"entry_bar": 2, "exit_bar": 4},
            objective_name="calmar_ratio",
            objective_direction="maximize",
            objective_metric="calmar_ratio",
            objective_score=1.2,
            strategy_name="ReportingStrategy",
            instrument="XAU_USD",
            timeframe="H1",
            metrics={
                "total_return": 0.12,
                "cagr": 0.22,
                "sharpe_ratio": 0.9,
                "sortino_ratio": 1.1,
                "calmar_ratio": 1.2,
                "max_drawdown": 0.12,
                "win_rate": 0.5,
                "profit_factor": 1.2,
                "expectancy": 2.0,
                "total_closed_trades": 9,
            },
            warning_count=0,
            error=None,
            result=None,
            cache_hit=False,
            objective_score_source="out_of_sample",
            search_objective_score=1.0,
        ),
        OptimizationTrial(
            run_id=3,
            optimizer_name="grid_search",
            status="invalid",
            parameters={"entry_bar": 1, "exit_bar": 1},
            objective_name="calmar_ratio",
            objective_direction="maximize",
            objective_metric="calmar_ratio",
            objective_score=None,
            strategy_name="ReportingStrategy",
            instrument="XAU_USD",
            timeframe="H1",
            metrics={},
            warning_count=0,
            error="constraint_rejected",
            result=None,
            cache_hit=False,
            objective_score_source="out_of_sample",
            search_objective_score=0.8,
        ),
        OptimizationTrial(
            run_id=4,
            optimizer_name="grid_search",
            status="failed",
            parameters={"entry_bar": 4, "exit_bar": 2},
            objective_name="calmar_ratio",
            objective_direction="maximize",
            objective_metric="calmar_ratio",
            objective_score=None,
            strategy_name="ReportingStrategy",
            instrument="XAU_USD",
            timeframe="H1",
            metrics={},
            warning_count=None,
            error="RuntimeError: explosion",
            result=None,
            cache_hit=False,
            objective_score_source="out_of_sample",
            search_objective_score=None,
        ),
    ]

    return OptimizationResult(
        optimizer_name="grid_search",
        objective=ObjectiveSpec(
            name="calmar_ratio",
            direction="maximize",
            metric_name="calmar_ratio",
        ),
        search_space=(
            ParameterSpec("entry_bar", "int", grid_values=(1, 2, 4)),
            ParameterSpec("exit_bar", "int", grid_values=(1, 2, 3, 4)),
        ),
        fixed_params={"risk_fraction": 0.01},
        trials=trials,
        warnings=[
            OptimizationWarning(
                code="optimization_trials_large_relative_to_data_length",
                message="Optimization breadth may be large relative to the sample size.",
            )
        ],
        metadata={
            "total_trials": 4,
            "completed_trials": 2,
            "invalid_trials": 1,
            "failed_trials": 1,
            "cache_hit_trials": 0,
            "unique_evaluated_trials": 4,
            "data_bars": 80,
            "target_trial_count": 4,
            "target_evaluations": None,
            "stopped_early": False,
            "stop_reason": None,
            "ranking_available": True,
            "ranking_score_source": "out_of_sample",
            "evaluation_mode": "explicit_evaluation",
        },
        ranking_score_source="out_of_sample",
    )


def test_backtest_json_payload_serializes_sections_and_nested_values():
    payload = build_backtest_json_payload(_build_backtest_result())

    assert payload["report_kind"] == "backtest"
    assert set(payload["ledgers"]) == {
        "orders",
        "trade_events",
        "closed_trades",
        "open_trades",
        "equity_curve",
        "drawdown_series",
        "drawdown_episodes",
    }
    assert payload["execution_assumptions"]["buy_side"] == "ask"
    assert any(caveat["code"] == "no_slippage" for caveat in payload["caveats"])

    order = payload["ledgers"]["orders"][0]
    assert order["created_time"].endswith("+00:00")
    assert order["sizing_raw_size"] is None
    assert order["sizing_details"]["risk"]["max_loss"] is None

    closed_trade = payload["ledgers"]["closed_trades"][0]
    assert closed_trade["entry_time"].endswith("+00:00")
    assert closed_trade["hold_time"].startswith("P")

    encoded = json.dumps(payload, allow_nan=False)
    assert "NaN" not in encoded


def test_backtest_json_payload_preserves_empty_ledgers():
    payload = build_backtest_json_payload(_build_low_sample_result())

    assert payload["ledgers"]["closed_trades"] == []
    assert payload["ledgers"]["trade_events"] == []
    assert payload["ledgers"]["open_trades"] == []
    assert payload["metrics"]["total_closed_trades"] == 0


def test_export_backtest_artifacts_writes_json_csv_html_and_charts(tmp_path):
    result = _build_backtest_result()

    paths = export_backtest_artifacts(result, tmp_path, run_label="Phase 6 Demo")

    expected_keys = {
        "artifact_dir",
        "summary_json",
        "metrics_csv",
        "warnings_csv",
        "orders_csv",
        "trade_events_csv",
        "closed_trades_csv",
        "open_trades_csv",
        "equity_csv",
        "drawdown_csv",
        "drawdown_episodes_csv",
        "charts_dir",
        "equity_curve_chart",
        "drawdown_chart",
        "trade_distribution_chart",
        "monthly_returns_chart",
        "report_html",
    }
    assert expected_keys <= set(paths)
    assert paths["artifact_dir"].name.startswith("Phase_6_Demo_run_")
    assert all(path.exists() for key, path in paths.items() if key != "artifact_dir")

    summary = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
    assert summary["metadata"]["strategy_name"] == "ReportingStrategy"
    assert summary["ledgers"]["closed_trades"][0]["hold_time"].startswith("P")

    metrics = pd.read_csv(paths["metrics_csv"])
    assert {
        "strategy_name",
        "instrument",
        "timeframe",
        "parameters_json",
        "execution_assumptions_json",
        "caveats_json",
        "start_cash",
        "end_cash",
        "end_value",
        "warning_count",
        "total_return",
        "calmar_ratio",
    } <= set(metrics.columns)

    orders = pd.read_csv(paths["orders_csv"])
    assert len(orders) == 1
    assert orders.loc[0, "created_time"].endswith("+00:00")

    closed_trades = pd.read_csv(paths["closed_trades_csv"])
    assert len(closed_trades) == 2
    assert closed_trades.loc[0, "entry_time"].endswith("+00:00")

    html = paths["report_html"].read_text(encoding="utf-8")
    assert "Execution Assumptions" in html
    assert "No slippage is modeled in this run." in html
    assert "data:image/png;base64" in html
    assert "12.000000" not in html


def test_export_backtest_artifacts_reuses_one_performance_analyzer(monkeypatch, tmp_path):
    result = _build_backtest_result()
    original_init = PerformanceAnalyzer.__init__
    call_count = {"count": 0}

    def counting_init(self, *args, **kwargs):
        call_count["count"] += 1
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(PerformanceAnalyzer, "__init__", counting_init)

    export_backtest_artifacts(result, tmp_path)

    assert call_count["count"] == 1


def test_chart_renderer_and_html_handle_zero_trades_and_low_history(tmp_path):
    result = _build_low_sample_result()

    charts = BacktestCharts(result).render_all(tmp_path / "charts")
    assert set(charts) == {
        "equity_curve",
        "drawdown",
        "trade_distribution",
        "monthly_returns",
    }
    assert all(path.exists() and path.stat().st_size > 0 for path in charts.values())

    paths = export_backtest_artifacts(result, tmp_path / "artifacts")
    html = paths["report_html"].read_text(encoding="utf-8")
    assert "No closed trades were recorded for this run." in html
    assert "Only 0 closed trades are available" in html


def test_optimization_json_payload_and_artifacts_write_ranked_outputs(tmp_path):
    result = _build_optimization_result()

    payload = build_optimization_json_payload(result, top_n=2)
    assert payload["report_kind"] == "optimization"
    assert payload["objective"]["name"] == "calmar_ratio"
    assert len(payload["trials"]) == 4
    assert len(payload["best_runs"]) == 2
    assert all(row["status"] == "completed" for row in payload["best_runs"])

    paths = export_optimization_artifacts(result, tmp_path, run_label="Sweep", top_n=2)
    assert {
        "artifact_dir",
        "summary_json",
        "optimization_results_csv",
        "best_runs_csv",
        "warnings_csv",
    } == set(paths)
    assert paths["artifact_dir"].name.startswith("Sweep_optimization_")
    assert all(path.exists() for key, path in paths.items() if key != "artifact_dir")

    summary = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
    assert summary["best_runs"][0]["run_id"] == int(result.ranking().iloc[0]["run_id"])

    full_table = pd.read_csv(paths["optimization_results_csv"])
    best_runs = pd.read_csv(paths["best_runs_csv"])
    warnings = pd.read_csv(paths["warnings_csv"])

    assert len(full_table) == 4
    assert len(best_runs) == 2
    assert set(best_runs["status"]) == {"completed"}
    assert list(best_runs["rank"]) == [1, 2]
    assert list(best_runs["run_id"]) == list(result.ranking().head(2)["run_id"])
    assert len(warnings) == 1
