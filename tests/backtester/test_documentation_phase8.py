from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from backtester.examples import InstrumentApiStrategy, QuickstartStrategy, WindowStrategy
from backtester.optimization import ParameterSpec, run_grid_search
from backtester.run_backtest import run_backtest


ROOT = Path(__file__).resolve().parents[2]
REAL_EXTRACTOR_CSV = (
    ROOT / "oanda-candle-extractor" / "data" / "EUR_USD" / "candles_EUR_USD_D.csv"
)
DOCUMENTATION_PATHS = [
    ROOT / "backtester" / "README.md",
    ROOT / "backtester" / "API_INDEX.md",
    ROOT / "backtester" / "core" / "README.md",
    ROOT / "backtester" / "data" / "README.md",
    ROOT / "backtester" / "strategy" / "README.md",
    ROOT / "backtester" / "indicators" / "README.md",
    ROOT / "backtester" / "sizing" / "README.md",
    ROOT / "backtester" / "performance" / "README.md",
    ROOT / "backtester" / "optimization" / "README.md",
    ROOT / "backtester" / "reporting" / "README.md",
    ROOT / "backtester" / "examples" / "README.md",
]


def test_backtester_component_docs_exist():
    for path in DOCUMENTATION_PATHS:
        assert path.exists(), f"Missing documentation file: {path}"


def test_quickstart_example_runs_with_checked_in_csv():
    result = run_backtest(
        QuickstartStrategy,
        instrument="EUR_USD",
        timeframe="D",
        csv_path=str(REAL_EXTRACTOR_CSV),
    )

    assert result.strategy_name == "QuickstartStrategy"
    assert result.instrument == "EUR_USD"
    assert result.timeframe == "D"
    assert result.timeframes == ("D",)
    assert not result.order_ledger.empty
    assert not result.trade_ledger.empty


def test_instrument_api_example_runs_with_checked_in_csv():
    InstrumentApiStrategy.latest_snapshot = {}
    InstrumentApiStrategy.latest_bar_close = None

    result = run_backtest(
        InstrumentApiStrategy,
        instrument="EUR_USD",
        timeframe="D",
        csv_path=str(REAL_EXTRACTOR_CSV),
    )

    assert result.strategy_name == "InstrumentApiStrategy"
    assert not result.order_ledger.empty
    assert "ema" in InstrumentApiStrategy.latest_snapshot
    assert "rsi" in InstrumentApiStrategy.latest_snapshot
    assert InstrumentApiStrategy.latest_bar_close is not None


def test_window_example_runs_through_optimization_with_checked_in_csv():
    optimization = run_grid_search(
        WindowStrategy,
        instrument="EUR_USD",
        timeframe="D",
        csv_path=str(REAL_EXTRACTOR_CSV),
        search_space=[
            ParameterSpec("entry_bar", "int", grid_values=(2,)),
            ParameterSpec("exit_bar", "int", grid_values=(5,)),
        ],
        objective="total_return",
    )

    ranking = optimization.ranking()
    assert len(ranking) == 1
    assert ranking.iloc[0]["strategy_name"] == "WindowStrategy"
    assert optimization.best_trial().timeframe == "D"


def test_run_backtest_help_cli_succeeds():
    completed = subprocess.run(
        [sys.executable, "-m", "backtester.run_backtest", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "--csv-path" in completed.stdout
    assert "--strategy-module" in completed.stdout
    assert "--strategy-param" in completed.stdout


def test_documented_cli_example_runs_against_examples_package():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backtester.run_backtest",
            "--csv-path",
            str(REAL_EXTRACTOR_CSV),
            "--instrument",
            "EUR_USD",
            "--timeframe",
            "D",
            "--strategy-module",
            "backtester.examples",
            "--strategy-class",
            "QuickstartStrategy",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "strategy=QuickstartStrategy" in completed.stdout
    assert "instrument=EUR_USD" in completed.stdout
    assert "timeframe=D" in completed.stdout
