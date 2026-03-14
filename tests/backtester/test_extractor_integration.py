"""Phase 7: Extractor-to-backtester integration contract tests.

These tests verify that the extractor's CSV output is directly consumable
by the backtester without manual cleanup or transformation.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import backtrader as bt
import pandas as pd
import pytest

EXTRACTOR_DIR = Path(__file__).resolve().parents[2] / "oanda-candle-extractor"
if str(EXTRACTOR_DIR) not in sys.path:
    sys.path.insert(0, str(EXTRACTOR_DIR))

REAL_EXTRACTOR_CSV = EXTRACTOR_DIR / "data" / "EUR_USD" / "candles_EUR_USD_D.csv"

from csv_persistence import CSVPersistence

from backtester.data.loader import OANDADataLoader
from backtester.data.validation import REQUIRED_COLUMNS, validate_oanda_dataframe
from backtester.run_backtest import run_backtest


def _make_extractor_frame(
    start: datetime,
    periods: int = 10,
    step_seconds: int = 3600,
    base_price: float = 2000.0,
    spread: float = 0.5,
) -> pd.DataFrame:
    """Build a DataFrame that mimics what OANDADataProvider._parse_candles() produces."""

    rows = []
    for i in range(periods):
        t = start + timedelta(seconds=step_seconds * i)
        mid_open = base_price + i * 1.0
        mid_high = mid_open + 2.0
        mid_low = mid_open - 1.0
        mid_close = mid_open + 0.5
        half = spread / 2.0
        rows.append({
            "time": t.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "open": mid_open,
            "high": mid_high,
            "low": mid_low,
            "close": mid_close,
            "volume": 100 + i,
            "bid_open": mid_open - half,
            "bid_high": mid_high - half,
            "bid_low": mid_low - half,
            "bid_close": mid_close - half,
            "ask_open": mid_open + half,
            "ask_high": mid_high + half,
            "ask_low": mid_low + half,
            "ask_close": mid_close + half,
        })
    return pd.DataFrame(rows)


def _write_extractor_csv(df: pd.DataFrame, path: Path) -> Path:
    """Write a DataFrame to CSV the same way CSVPersistence would."""

    df.to_csv(path, index=False, encoding="utf-8")
    return path


def _get_real_extractor_csv() -> Path:
    """Return the checked-in extractor CSV used as the Phase 7 real-file fixture."""

    assert REAL_EXTRACTOR_CSV.exists(), f"Expected checked-in extractor CSV at {REAL_EXTRACTOR_CSV}"
    return REAL_EXTRACTOR_CSV


# ---------------------------------------------------------------------------
# Schema compatibility
# ---------------------------------------------------------------------------


class TestSchemaCompatibility:
    """Verify extractor and backtester agree on the 14-column contract."""

    def test_extractor_columns_match_backtester_required_columns(self):
        """CSVPersistence.CANDLE_COLUMNS must be a superset of REQUIRED_COLUMNS."""

        extractor_cols = set(CSVPersistence.CANDLE_COLUMNS)
        backtester_cols = set(REQUIRED_COLUMNS)
        missing = backtester_cols - extractor_cols
        assert not missing, f"Extractor missing columns required by backtester: {missing}"

    def test_extractor_frame_passes_backtester_validation(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_extractor_frame(start)
        validated = validate_oanda_dataframe(df)
        assert len(validated) == 10
        assert list(validated.columns[:14]) == list(REQUIRED_COLUMNS)

    def test_extractor_csv_loads_through_backtester_loader(self, tmp_path):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_extractor_frame(start)
        csv_path = _write_extractor_csv(df, tmp_path / "candles_XAU_USD_H1.csv")

        loader = OANDADataLoader()
        loaded = loader.load_csv(str(csv_path))
        assert len(loaded) == 10
        assert loaded.index.name == "time"


# ---------------------------------------------------------------------------
# UTC timestamp preservation
# ---------------------------------------------------------------------------


class TestUTCPreservation:
    """Verify UTC timestamps survive the extractor-to-backtester flow."""

    def test_z_suffix_timestamps_accepted(self, tmp_path):
        start = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        df = _make_extractor_frame(start, periods=3)
        csv_path = _write_extractor_csv(df, tmp_path / "test.csv")

        loader = OANDADataLoader()
        loaded = loader.load_csv(str(csv_path))

        assert str(loaded.index[0].tzinfo) in {"UTC", "tzutc()"}
        assert loaded.index[0] == pd.Timestamp("2024-06-15 12:00:00", tz="UTC")

    def test_plus_zero_offset_timestamps_accepted(self, tmp_path):
        start = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        df = _make_extractor_frame(start, periods=3)
        df["time"] = df["time"].str.replace("Z", "+00:00")
        csv_path = _write_extractor_csv(df, tmp_path / "test.csv")

        loader = OANDADataLoader()
        loaded = loader.load_csv(str(csv_path))
        assert str(loaded.index[0].tzinfo) in {"UTC", "tzutc()"}

    def test_naive_timestamps_rejected(self, tmp_path):
        start = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        df = _make_extractor_frame(start, periods=3)
        df["time"] = df["time"].str.replace("Z", "")
        csv_path = _write_extractor_csv(df, tmp_path / "test.csv")

        loader = OANDADataLoader()
        with pytest.raises(ValueError, match="UTC"):
            loader.load_csv(str(csv_path))


# ---------------------------------------------------------------------------
# Real checked-in extractor CSV regression
# ---------------------------------------------------------------------------


class TestRealExtractorCSVContract:
    """Verify a checked-in extractor CSV stays directly backtester-compatible."""

    def test_real_extractor_csv_loads_directly(self):
        csv_path = _get_real_extractor_csv()

        loader = OANDADataLoader()
        loaded = loader.load_csv(str(csv_path))

        assert not loaded.empty
        assert list(loaded.columns) == list(REQUIRED_COLUMNS)
        assert loaded.index.name == "time"
        assert loaded.index.is_monotonic_increasing
        assert not loaded.index.has_duplicates
        assert str(loaded.index[0].tzinfo) in {"UTC", "tzutc()"}
        assert str(loaded["time"].dt.tz) in {"UTC", "tzutc()"}
        assert loaded["time"].equals(pd.Series(loaded.index, index=loaded.index, name="time"))

    def test_real_extractor_csv_runs_full_backtest(self):
        csv_path = _get_real_extractor_csv()

        result = run_backtest(
            strategy_class=_DoNothingStrategy,
            instrument="EUR_USD",
            timeframe="D",
            csv_path=str(csv_path),
            cash=10_000.0,
        )

        assert result.instrument == "EUR_USD"
        assert result.timeframe == "D"
        assert result.start_cash == 10_000.0
        assert result.end_value == 10_000.0


# ---------------------------------------------------------------------------
# CSVPersistence round-trip
# ---------------------------------------------------------------------------


class TestPersistenceRoundTrip:
    """Verify CSVPersistence save/load produces backtester-compatible output."""

    def test_persistence_save_load_produces_valid_backtester_input(self, tmp_path):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_extractor_frame(start, periods=5)
        df["time"] = pd.to_datetime(df["time"], utc=True)

        persistence = CSVPersistence(tmp_path)
        assert persistence.save_candles(df, "XAU_USD", "H1")

        csv_path = persistence.get_candle_path("XAU_USD", "H1")
        loader = OANDADataLoader()
        loaded = loader.load_csv(str(csv_path))
        assert len(loaded) == 5

    def test_persistence_validates_full_14_column_contract(self, tmp_path):
        persistence = CSVPersistence(tmp_path)
        incomplete = pd.DataFrame({
            "time": [pd.Timestamp("2024-01-01", tz="UTC")],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [100],
        })
        assert not persistence._validate_candle_frame(incomplete)


# ---------------------------------------------------------------------------
# Invalid CSV handling
# ---------------------------------------------------------------------------


class TestInvalidCSVHandling:
    """Verify the backtester fails clearly on invalid or hand-edited CSVs."""

    def test_missing_bid_ask_columns_rejected(self, tmp_path):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_extractor_frame(start, periods=3)
        df = df.drop(columns=["bid_open", "bid_high"])
        csv_path = _write_extractor_csv(df, tmp_path / "test.csv")

        loader = OANDADataLoader()
        with pytest.raises(ValueError, match="Missing required columns"):
            loader.load_csv(str(csv_path))

    def test_inverted_bid_ask_rejected(self, tmp_path):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_extractor_frame(start, periods=3)
        df["bid_open"] = df["ask_open"] + 1.0
        csv_path = _write_extractor_csv(df, tmp_path / "test.csv")

        loader = OANDADataLoader()
        with pytest.raises(ValueError, match="spread relationship"):
            loader.load_csv(str(csv_path))

    def test_invalid_ohlc_rejected(self, tmp_path):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_extractor_frame(start, periods=3)
        df.loc[0, "high"] = df.loc[0, "low"] - 1.0
        csv_path = _write_extractor_csv(df, tmp_path / "test.csv")

        loader = OANDADataLoader()
        with pytest.raises(ValueError, match="OHLC relationship"):
            loader.load_csv(str(csv_path))

    def test_duplicate_timestamps_rejected_by_default(self, tmp_path):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_extractor_frame(start, periods=3)
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        csv_path = _write_extractor_csv(df, tmp_path / "test.csv")

        loader = OANDADataLoader()
        with pytest.raises(ValueError, match="Duplicate timestamps"):
            loader.load_csv(str(csv_path))

    def test_null_values_rejected(self, tmp_path):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_extractor_frame(start, periods=3)
        df.loc[1, "close"] = None
        csv_path = _write_extractor_csv(df, tmp_path / "test.csv")

        loader = OANDADataLoader()
        with pytest.raises(ValueError, match="null values"):
            loader.load_csv(str(csv_path))


# ---------------------------------------------------------------------------
# End-to-end backtest from extractor CSV
# ---------------------------------------------------------------------------


class _DoNothingStrategy(bt.Strategy):
    """Minimal strategy that just holds and proves the pipeline works."""

    def next(self):
        pass


class TestEndToEndBacktest:
    """Verify one extractor CSV runs through a full backtest without cleanup."""

    def test_extractor_csv_runs_full_backtest(self, tmp_path):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_extractor_frame(start, periods=20, base_price=2000.0)
        csv_path = _write_extractor_csv(df, tmp_path / "candles_XAU_USD_H1.csv")

        result = run_backtest(
            strategy_class=_DoNothingStrategy,
            instrument="XAU_USD",
            timeframe="H1",
            csv_path=str(csv_path),
            cash=10_000.0,
        )

        assert result.instrument == "XAU_USD"
        assert result.timeframe == "H1"
        assert result.end_value == 10_000.0

    def test_persistence_round_trip_then_backtest(self, tmp_path):
        """Save via CSVPersistence, then load and backtest as the real workflow."""

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_extractor_frame(start, periods=20, base_price=2000.0)
        df["time"] = pd.to_datetime(df["time"], utc=True)

        persistence = CSVPersistence(tmp_path)
        assert persistence.save_candles(df, "XAU_USD", "H1")
        csv_path = persistence.get_candle_path("XAU_USD", "H1")

        result = run_backtest(
            strategy_class=_DoNothingStrategy,
            instrument="XAU_USD",
            timeframe="H1",
            csv_path=str(csv_path),
            cash=10_000.0,
        )

        assert result.end_value == 10_000.0
