"""Validation helpers for extractor-native OANDA candle data."""

from __future__ import annotations

import re
from typing import Final

import pandas as pd

REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
)

_UTC_SUFFIX = re.compile(r"(Z|[+]00:00)$")
_NUMERIC_COLUMNS: Final[tuple[str, ...]] = tuple(
    column for column in REQUIRED_COLUMNS if column != "time"
)
_PRICE_BLOCKS: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("open", "high", "low", "close"),
    ("bid_open", "bid_high", "bid_low", "bid_close"),
    ("ask_open", "ask_high", "ask_low", "ask_close"),
)


def validate_oanda_dataframe(
    df: pd.DataFrame,
    *,
    allow_dedupe: bool = False,
) -> pd.DataFrame:
    """Validate and normalize one extractor-compatible candle DataFrame."""

    if not isinstance(df, pd.DataFrame):
        raise TypeError("Expected a pandas DataFrame")

    frame = _prepare_frame(df)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    frame = frame.copy()
    frame["time"] = _normalize_time_column(frame["time"])

    for column in _NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if frame[column].isna().any():
            raise ValueError(f"Column {column!r} contains null values")

    frame["volume"] = frame["volume"].astype(int)
    frame = frame.sort_values("time", kind="mergesort").reset_index(drop=True)

    duplicated = frame["time"].duplicated(keep=False)
    if duplicated.any():
        if not allow_dedupe:
            raise ValueError("Duplicate timestamps are not allowed")
        frame = frame.drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)

    for open_col, high_col, low_col, close_col in _PRICE_BLOCKS:
        _validate_ohlc_relationships(frame, open_col, high_col, low_col, close_col)

    for suffix in ("open", "high", "low", "close"):
        bid_col = f"bid_{suffix}"
        ask_col = f"ask_{suffix}"
        if (frame[bid_col] > frame[ask_col]).any():
            raise ValueError(f"Invalid spread relationship: {bid_col} exceeds {ask_col}")

    ordered_columns = list(REQUIRED_COLUMNS) + [
        column for column in frame.columns if column not in REQUIRED_COLUMNS
    ]
    return frame.loc[:, ordered_columns]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    if "time" in df.columns:
        return df
    if df.index.name == "time":
        return df.reset_index()
    raise ValueError("DataFrame must include a 'time' column")


def _normalize_time_column(values: pd.Series) -> pd.Series:
    if isinstance(values.dtype, pd.DatetimeTZDtype):
        tzname = str(values.dt.tz)
        if tzname not in {"UTC", "tzutc()"}:
            raise ValueError("time column must already be in UTC")
        return values.dt.tz_convert("UTC")

    if pd.api.types.is_datetime64_dtype(values):
        raise ValueError("time column must include explicit UTC timezone information")

    text_values = values.astype(str)
    if not text_values.map(_looks_like_utc).all():
        raise ValueError("time column must include explicit UTC timezone information")

    return pd.to_datetime(values, errors="raise", utc=True)


def _looks_like_utc(value: str) -> bool:
    stripped = value.strip()
    return bool(_UTC_SUFFIX.search(stripped))


def _validate_ohlc_relationships(
    frame: pd.DataFrame,
    open_col: str,
    high_col: str,
    low_col: str,
    close_col: str,
) -> None:
    invalid = (
        (frame[high_col] < frame[low_col])
        | (frame[open_col] > frame[high_col])
        | (frame[open_col] < frame[low_col])
        | (frame[close_col] > frame[high_col])
        | (frame[close_col] < frame[low_col])
    )
    if invalid.any():
        raise ValueError(
            f"Invalid OHLC relationship detected for {open_col}, {high_col}, {low_col}, {close_col}"
        )
