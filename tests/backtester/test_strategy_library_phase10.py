from __future__ import annotations

import os
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest

from backtester.optimization import ParameterSpec, run_grid_search
from backtester.reporting import export_backtest_artifacts
from backtester.run_backtest import run_backtest
from strategies import (
    BollingerZscoreReversionStrategy,
    EmaRsiTrendStrategy,
    HybridRegimeStrategy,
    IctOteSniperStrategy,
    MacdAtrBreakoutStrategy,
    SmcPullbackStrategy,
)


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "oanda-candle-extractor" / "data"
REAL_EUR_USD_D = DATA_ROOT / "EUR_USD" / "candles_EUR_USD_D.csv"
REAL_USD_JPY_D = DATA_ROOT / "USD_JPY" / "candles_USD_JPY_D.csv"
REAL_EUR_GBP_D = DATA_ROOT / "EUR_GBP" / "candles_EUR_GBP_D.csv"
REAL_GBP_USD_D = DATA_ROOT / "GBP_USD" / "candles_GBP_USD_D.csv"
REAL_XAU_USD_D = DATA_ROOT / "XAU_USD" / "candles_XAU_USD_D.csv"

STRATEGY_SPECS = [
    ("strategies.ema_rsi_trend", "EmaRsiTrendStrategy", EmaRsiTrendStrategy, "Market"),
    ("strategies.macd_atr_breakout", "MacdAtrBreakoutStrategy", MacdAtrBreakoutStrategy, "Stop"),
    (
        "strategies.bollinger_zscore_reversion",
        "BollingerZscoreReversionStrategy",
        BollingerZscoreReversionStrategy,
        "Limit",
    ),
    ("strategies.smc_pullback", "SmcPullbackStrategy", SmcPullbackStrategy, "Limit"),
    ("strategies.ict_ote_sniper", "IctOteSniperStrategy", IctOteSniperStrategy, "Limit"),
    ("strategies.hybrid_regime", "HybridRegimeStrategy", HybridRegimeStrategy, "Market"),
]


def _frame_from_candles(make_oanda_frame, candles: list[dict], *, start: str = "2024-01-01T00:00:00Z"):
    base = pd.Timestamp(start)
    normalized: list[dict] = []
    for index, candle in enumerate(candles):
        item = dict(candle)
        item.setdefault("time", base + pd.Timedelta(hours=index))
        normalized.append(item)
    return make_oanda_frame(normalized)


def _ema_trend_frame(make_oanda_frame):
    return _frame_from_candles(
        make_oanda_frame,
        [
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
            {"open": 100.0, "high": 100.2, "low": 99.7, "close": 99.8},
            {"open": 99.8, "high": 99.9, "low": 99.4, "close": 99.5},
            {"open": 99.5, "high": 99.7, "low": 99.3, "close": 99.4},
            {"open": 99.4, "high": 99.8, "low": 99.3, "close": 99.7},
            {"open": 99.7, "high": 100.4, "low": 99.6, "close": 100.3},
            {"open": 100.3, "high": 101.0, "low": 100.2, "close": 100.9},
            {"open": 100.9, "high": 101.3, "low": 100.8, "close": 101.1},
            {"open": 101.1, "high": 101.2, "low": 100.6, "close": 100.7},
            {"open": 100.7, "high": 100.8, "low": 100.1, "close": 100.2},
            {"open": 100.2, "high": 100.3, "low": 99.7, "close": 99.9},
            {"open": 99.9, "high": 100.0, "low": 99.5, "close": 99.6},
        ],
    )


def _macd_breakout_frame(make_oanda_frame):
    return _frame_from_candles(
        make_oanda_frame,
        [
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 99.6, "close": 99.7},
            {"open": 99.7, "high": 99.9, "low": 99.2, "close": 99.4},
            {"open": 99.4, "high": 99.6, "low": 99.0, "close": 99.2},
            {"open": 99.2, "high": 99.5, "low": 99.1, "close": 99.4},
            {"open": 99.4, "high": 100.2, "low": 99.3, "close": 100.1},
            {"open": 100.1, "high": 100.8, "low": 100.0, "close": 100.7},
            {"open": 100.7, "high": 101.2, "low": 100.6, "close": 101.0},
            {"open": 101.0, "high": 101.5, "low": 100.9, "close": 101.3},
            {"open": 101.3, "high": 102.2, "low": 101.2, "close": 102.0},
            {"open": 102.0, "high": 102.5, "low": 101.9, "close": 102.3},
            {"open": 102.3, "high": 103.4, "low": 102.2, "close": 103.1},
            {"open": 103.1, "high": 103.6, "low": 102.8, "close": 103.4},
        ],
    )


def _bollinger_frame(make_oanda_frame):
    return _frame_from_candles(
        make_oanda_frame,
        [
            {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 98.8, "close": 99.0},
            {"open": 99.0, "high": 99.4, "low": 98.7, "close": 98.9},
            {"open": 98.9, "high": 99.9, "low": 98.8, "close": 99.8},
            {"open": 99.8, "high": 100.5, "low": 99.7, "close": 100.3},
            {"open": 100.3, "high": 100.6, "low": 100.2, "close": 100.5},
        ],
    )


def _ict_frame(make_oanda_frame):
    return _frame_from_candles(
        make_oanda_frame,
        [
            {"open": 7.5, "high": 10.0, "low": 5.0, "close": 7.5},
            {"open": 13.0, "high": 20.0, "low": 6.0, "close": 13.0},
            {"open": 11.0, "high": 15.0, "low": 7.0, "close": 11.0},
            {"open": 10.0, "high": 14.0, "low": 8.0, "close": 10.0},
            {"open": 10.0, "high": 11.0, "low": 9.2, "close": 9.4},
            {"open": 9.4, "high": 10.9, "low": 8.0, "close": 10.8},
            {"open": 10.8, "high": 20.5, "low": 10.7, "close": 20.0},
            {"open": 20.0, "high": 20.8, "low": 16.0, "close": 16.5},
            {"open": 16.5, "high": 17.6, "low": 16.2, "close": 17.4},
            {"open": 17.4, "high": 17.7, "low": 7.5, "close": 8.2},
            {"open": 8.2, "high": 20.4, "low": 8.1, "close": 19.8},
        ],
    )


def _hybrid_frame(make_oanda_frame):
    return _frame_from_candles(
        make_oanda_frame,
        [
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
            {"open": 100.0, "high": 100.5, "low": 99.9, "close": 100.4},
            {"open": 100.4, "high": 100.9, "low": 100.3, "close": 100.8},
            {"open": 100.8, "high": 101.2, "low": 100.6, "close": 101.0},
            {"open": 101.0, "high": 101.4, "low": 100.8, "close": 101.2},
            {"open": 101.2, "high": 101.6, "low": 101.0, "close": 101.4},
            {"open": 101.4, "high": 101.8, "low": 101.2, "close": 101.6},
            {"open": 101.6, "high": 102.0, "low": 101.4, "close": 101.8},
            {"open": 101.8, "high": 102.6, "low": 101.7, "close": 102.5},
            {"open": 102.5, "high": 103.0, "low": 102.4, "close": 102.9},
            {"open": 102.9, "high": 103.6, "low": 102.8, "close": 103.4},
            {"open": 103.4, "high": 103.8, "low": 103.3, "close": 103.7},
            {"open": 103.7, "high": 104.2, "low": 103.6, "close": 104.1},
            {"open": 104.1, "high": 105.5, "low": 104.0, "close": 105.2},
        ],
    )


def _smc_frame(make_oanda_frame):
    prelude = []
    for index in range(24):
        price = 100.0 + ((index % 6) * 0.2)
        prelude.append(
            {
                "open": price,
                "high": price + 0.3,
                "low": price - 0.3,
                "close": price + 0.05,
            }
        )
    setup = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0},
        {"open": 102.0, "high": 102.2, "low": 98.0, "close": 99.0},
        {"open": 99.0, "high": 104.0, "low": 99.0, "close": 103.0},
        {"open": 103.0, "high": 103.2, "low": 97.0, "close": 98.0},
        {"open": 98.0, "high": 105.0, "low": 98.0, "close": 104.0},
        {"open": 104.0, "high": 104.2, "low": 96.0, "close": 97.0},
        {"open": 97.0, "high": 106.0, "low": 97.0, "close": 105.0},
        {"open": 105.0, "high": 106.5, "low": 102.0, "close": 103.0},
        {"open": 103.0, "high": 106.8, "low": 101.0, "close": 106.4},
        {"open": 106.4, "high": 106.6, "low": 98.0, "close": 98.5},
        {"open": 98.5, "high": 102.0, "low": 97.8, "close": 101.5},
        {"open": 101.5, "high": 103.0, "low": 101.2, "close": 102.8},
        {"open": 102.8, "high": 104.8, "low": 102.5, "close": 104.5},
        {"open": 104.5, "high": 104.8, "low": 97.9, "close": 98.2},
        {"open": 98.2, "high": 101.6, "low": 98.1, "close": 101.2},
    ]
    return _frame_from_candles(
        make_oanda_frame,
        prelude + setup,
        start="2024-01-01T04:00:00Z",
    )


def _fixture_frame(make_oanda_frame, strategy_name: str):
    frames = {
        "EmaRsiTrendStrategy": _ema_trend_frame,
        "MacdAtrBreakoutStrategy": _macd_breakout_frame,
        "BollingerZscoreReversionStrategy": _bollinger_frame,
        "SmcPullbackStrategy": _smc_frame,
        "IctOteSniperStrategy": _ict_frame,
        "HybridRegimeStrategy": _hybrid_frame,
    }
    return frames[strategy_name](make_oanda_frame)


@pytest.mark.parametrize(("module_name", "class_name", "strategy_class", "_order_name"), STRATEGY_SPECS)
def test_strategy_library_modules_export_expected_classes(
    module_name,
    class_name,
    strategy_class,
    _order_name,
):
    module = import_module(module_name)
    exported = getattr(module, class_name)

    assert exported is strategy_class
    assert getattr(import_module("strategies"), class_name) is strategy_class


@pytest.mark.parametrize(("module_name", "class_name", "strategy_class", "order_name"), STRATEGY_SPECS)
def test_strategy_library_smoke_runs_cover_expected_entry_styles(
    make_oanda_frame,
    module_name,
    class_name,
    strategy_class,
    order_name,
):
    frame = _fixture_frame(make_oanda_frame, class_name)

    result = run_backtest(
        strategy_class,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
    )

    entry_events = result.order_ledger[result.order_ledger["role"] == "entry"]

    assert not result.order_ledger.empty, module_name
    assert not entry_events.empty, module_name
    assert order_name in set(entry_events["order_name"])
    assert "Completed" in set(entry_events["status_name"])
    assert not result.closed_trade_ledger.empty, module_name
    exit_reason = result.closed_trade_ledger.iloc[0]["exit_reason"]
    if exit_reason is not None:
        assert exit_reason in {"take_profit", "manual_exit"}


@pytest.mark.parametrize(("module_name", "class_name", "_strategy_class", "_order_name"), STRATEGY_SPECS)
def test_strategies_load_through_cli_module_interface(
    tmp_path,
    make_oanda_frame,
    module_name,
    class_name,
    _strategy_class,
    _order_name,
):
    frame = _fixture_frame(make_oanda_frame, class_name)
    csv_path = tmp_path / f"{class_name}.csv"
    frame.to_csv(csv_path, index=False)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backtester.run_backtest",
            "--csv-path",
            str(csv_path),
            "--instrument",
            "XAU_USD",
            "--timeframe",
            "H1",
            "--strategy-module",
            module_name,
            "--strategy-class",
            class_name,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert f"strategy={class_name}" in completed.stdout
    assert "instrument=XAU_USD" in completed.stdout
    assert "timeframe=H1" in completed.stdout


def test_smc_cli_load_survives_cp1252_stdout(tmp_path, make_oanda_frame):
    frame = _smc_frame(make_oanda_frame)
    csv_path = tmp_path / "smc_pullback.csv"
    frame.to_csv(csv_path, index=False)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backtester.run_backtest",
            "--csv-path",
            str(csv_path),
            "--instrument",
            "XAU_USD",
            "--timeframe",
            "H1",
            "--strategy-module",
            "strategies.smc_pullback",
            "--strategy-class",
            "SmcPullbackStrategy",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "strategy=SmcPullbackStrategy" in completed.stdout


def test_hybrid_regime_runs_through_grid_search(make_oanda_frame):
    frame = _hybrid_frame(make_oanda_frame)

    result = run_grid_search(
        HybridRegimeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        holdout_fraction=0.25,
        search_space=[
            ParameterSpec("adx_threshold", "float", grid_values=(8.0, 12.0)),
            ParameterSpec("risk_reward", "float", grid_values=(1.2, 1.6)),
        ],
        objective="total_return",
    )

    table = result.table()
    ranking = result.ranking()

    assert len(table) == 4
    assert len(ranking) == 4
    assert set(table["status"]) == {"completed"}
    assert set(ranking["strategy_name"]) == {"HybridRegimeStrategy"}
    assert result.best_trial().strategy_name == "HybridRegimeStrategy"


def test_phase10_reporting_exports_real_backtest_artifacts(tmp_path):
    result = run_backtest(
        EmaRsiTrendStrategy,
        instrument="EUR_USD",
        timeframe="D",
        csv_path=str(REAL_EUR_USD_D),
    )

    paths = export_backtest_artifacts(result, tmp_path, run_label="Phase 10 Demo")

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

    assert not result.order_ledger.empty
    assert not result.closed_trade_ledger.empty
    assert expected_keys <= set(paths)
    assert all(path.exists() for key, path in paths.items() if key != "artifact_dir")


@pytest.mark.parametrize(
    ("instrument", "csv_path", "conversion_data", "expected_mode"),
    [
        ("EUR_USD", REAL_EUR_USD_D, None, "quote_currency_is_account_currency"),
        ("USD_JPY", REAL_USD_JPY_D, None, "dynamic_from_instrument_price"),
        (
            "EUR_GBP",
            REAL_EUR_GBP_D,
            {"GBP_USD": REAL_GBP_USD_D},
            "dynamic_from_conversion_data",
        ),
        ("XAU_USD", REAL_XAU_USD_D, None, "quote_currency_is_account_currency"),
    ],
)
def test_strategy_library_handles_representative_price_conventions(
    instrument,
    csv_path,
    conversion_data,
    expected_mode,
):
    result = run_backtest(
        EmaRsiTrendStrategy,
        instrument=instrument,
        timeframe="D",
        csv_path=str(csv_path),
        conversion_data=conversion_data,
    )

    assert result.instrument == instrument
    assert result.timeframe == "D"
    assert result.execution_policy["quote_to_account_mode"] == expected_mode
