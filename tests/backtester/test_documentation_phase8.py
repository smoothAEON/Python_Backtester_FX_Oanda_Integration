from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from backtester.run_backtest import run_backtest
from strategies import EmaRsiTrendStrategy
from backtester.examples import InstrumentApiStrategy, QuickstartStrategy, WindowStrategy


ROOT = Path(__file__).resolve().parents[2]
REAL_EXTRACTOR_CSV = (
    ROOT / "oanda-candle-extractor" / "data" / "EUR_USD" / "candles_EUR_USD_D.csv"
)
DOCUMENTATION_PATHS = [
    ROOT / "fixbug.md",
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
    ROOT / "strategies" / "README.md",
]


def test_backtester_component_docs_exist():
    for path in DOCUMENTATION_PATHS:
        assert path.exists(), f"Missing documentation file: {path}"


def test_canonical_strategy_library_example_runs_with_checked_in_csv():
    result = run_backtest(
        EmaRsiTrendStrategy,
        instrument="EUR_USD",
        timeframe="D",
        csv_path=str(REAL_EXTRACTOR_CSV),
    )

    assert result.strategy_name == "EmaRsiTrendStrategy"
    assert result.instrument == "EUR_USD"
    assert result.timeframe == "D"
    assert result.timeframes == ("D",)
    assert not result.order_ledger.empty
    assert not result.closed_trade_ledger.empty


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


def test_examples_package_remains_importable_for_secondary_docs():
    assert QuickstartStrategy.__name__ == "QuickstartStrategy"
    assert WindowStrategy.__name__ == "WindowStrategy"
    assert InstrumentApiStrategy.__name__ == "InstrumentApiStrategy"


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
    assert "--allow-research-only" in completed.stdout


def test_walk_forward_help_cli_succeeds():
    completed = subprocess.run(
        [sys.executable, "-m", "backtester.walk_forward", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "--repo-root" in completed.stdout
    assert "--output-json" in completed.stdout
    assert "--output-audit" in completed.stdout


def test_documented_cli_example_runs_against_strategy_library():
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
            "strategies.ema_rsi_trend",
            "--strategy-class",
            "EmaRsiTrendStrategy",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "strategy=EmaRsiTrendStrategy" in completed.stdout
    assert "instrument=EUR_USD" in completed.stdout
    assert "timeframe=D" in completed.stdout


def test_docs_describe_live_safe_defaults_and_research_only_quarantine():
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    backtester_readme = (ROOT / "backtester" / "README.md").read_text(encoding="utf-8")
    api_index = (ROOT / "backtester" / "API_INDEX.md").read_text(encoding="utf-8")
    indicators_readme = (ROOT / "backtester" / "indicators" / "README.md").read_text(
        encoding="utf-8"
    )
    strategies_readme = (ROOT / "strategies" / "README.md").read_text(encoding="utf-8")
    fixbug = (ROOT / "fixbug.md").read_text(encoding="utf-8")

    assert "live_safe" in root_readme
    assert "fixbug.md" in root_readme
    assert "--allow-research-only" in backtester_readme
    assert "default walk-forward matrix includes only `live_safe` strategies" in backtester_readme
    assert "confirmed_swings" in backtester_readme
    assert "backtester.indicators.research" in api_index
    assert "backtester.indicators.savgol_smooth" not in api_index
    assert "CausalICTFibEngine" in api_index
    assert "backtester.indicators.research" in indicators_readme
    assert "confirmed_swings" in indicators_readme
    assert "`research_only`" in strategies_readme
    assert "strategies.research" in strategies_readme
    assert "supersedes the current integrity conclusions" in fixbug
