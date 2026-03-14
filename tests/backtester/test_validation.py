from __future__ import annotations

import pandas as pd
import pytest

from backtester.data.loader import OANDADataLoader
from backtester.data.validation import REQUIRED_COLUMNS, validate_oanda_dataframe


def test_validate_oanda_dataframe_accepts_valid_frame(make_oanda_frame):
    frame = make_oanda_frame()

    validated = validate_oanda_dataframe(frame)

    assert list(validated.columns[: len(REQUIRED_COLUMNS)]) == list(REQUIRED_COLUMNS)
    assert str(validated["time"].dt.tz) == "UTC"
    assert validated["time"].is_monotonic_increasing


def test_loader_sets_time_index_after_validation(make_oanda_frame, write_oanda_csv):
    frame = make_oanda_frame()
    csv_path = write_oanda_csv(frame)

    loaded = OANDADataLoader().load_csv(str(csv_path))

    assert loaded.index.name == "time"
    assert "time" in loaded.columns
    assert loaded.index.equals(pd.Index(loaded["time"], name="time"))


def test_validate_oanda_dataframe_rejects_missing_columns(make_oanda_frame):
    frame = make_oanda_frame().drop(columns=["ask_close"])

    with pytest.raises(ValueError, match="Missing required columns"):
        validate_oanda_dataframe(frame)


def test_validate_oanda_dataframe_rejects_duplicate_timestamps_by_default(make_oanda_frame):
    frame = make_oanda_frame()
    frame.loc[1, "time"] = frame.loc[0, "time"]

    with pytest.raises(ValueError, match="Duplicate timestamps"):
        validate_oanda_dataframe(frame)


def test_validate_oanda_dataframe_dedupes_when_enabled(make_oanda_frame):
    frame = make_oanda_frame()
    frame.loc[1, "time"] = frame.loc[0, "time"]
    frame.loc[1, "close"] = 101.25

    validated = validate_oanda_dataframe(frame, allow_dedupe=True)

    assert len(validated) == len(frame) - 1
    assert validated.iloc[0]["close"] == 101.25


def test_validate_oanda_dataframe_rejects_non_utc_strings(make_oanda_frame):
    frame = make_oanda_frame()
    frame["time"] = [
        "2024-01-01T00:00:00+08:00",
        "2024-01-01T01:00:00+08:00",
        "2024-01-01T02:00:00+08:00",
    ]

    with pytest.raises(ValueError, match="UTC"):
        validate_oanda_dataframe(frame)


def test_validate_oanda_dataframe_rejects_bid_above_ask(make_oanda_frame):
    frame = make_oanda_frame()
    frame.loc[0, "bid_close"] = frame.loc[0, "ask_close"] + 0.01

    with pytest.raises(ValueError, match="Invalid spread relationship"):
        validate_oanda_dataframe(frame)


def test_validate_oanda_dataframe_rejects_invalid_ohlc_ranges(make_oanda_frame):
    frame = make_oanda_frame()
    frame.loc[0, "high"] = frame.loc[0, "low"] - 0.5

    with pytest.raises(ValueError, match="Invalid OHLC relationship"):
        validate_oanda_dataframe(frame)
