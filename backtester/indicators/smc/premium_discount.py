"""Premium/discount zones derived from confirmed swings.

Uses upstream ``smartmoneyconcepts`` for swing detection while keeping
the custom premium/discount zone classification that has no upstream
equivalent.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _coerce_ohlc_frame(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalise an OHLC DataFrame."""
    required = ("open", "high", "low", "close")
    missing = [column for column in required if column not in ohlc.columns]
    if missing:
        raise ValueError(f"Missing required OHLC columns: {missing}")
    frame = ohlc.loc[:, list(required)].copy()
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    return frame


def _coerce_swing_frame(
    swing_highs_lows: pd.DataFrame,
    index: pd.Index,
) -> pd.DataFrame:
    """Validate and normalise a swing-highs-lows DataFrame."""
    required = ("HighLow", "Level")
    missing = [column for column in required if column not in swing_highs_lows.columns]
    if missing:
        raise ValueError(f"Missing required swing columns: {missing}")
    frame = swing_highs_lows.loc[:, list(required)].copy()
    if len(frame) != len(index):
        raise ValueError("swing_highs_lows must have the same length as ohlc")
    frame.index = index
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def premium_discount(
    ohlc: pd.DataFrame,
    swing_highs_lows: pd.DataFrame,
) -> pd.DataFrame:
    """Classify the current close against the latest alternating swing range."""

    frame = _coerce_ohlc_frame(ohlc)
    swing_frame = _coerce_swing_frame(swing_highs_lows, frame.index)

    range_high = np.full(len(frame), np.nan, dtype=float)
    range_low = np.full(len(frame), np.nan, dtype=float)
    equilibrium = np.full(len(frame), np.nan, dtype=float)
    zone = np.zeros(len(frame), dtype=np.int32)

    swing_positions = np.where(~np.isnan(swing_frame["HighLow"].to_numpy(dtype=float)))[0]
    for index in range(len(frame)):
        eligible = swing_positions[swing_positions <= index]
        if len(eligible) < 2:
            continue

        pair = _last_alternating_pair(swing_frame, eligible)
        if pair is None:
            continue
        left, right = pair
        left_type = float(swing_frame["HighLow"].iloc[left])
        right_type = float(swing_frame["HighLow"].iloc[right])
        left_level = float(swing_frame["Level"].iloc[left])
        right_level = float(swing_frame["Level"].iloc[right])

        high_level = left_level if left_type == 1.0 else right_level
        low_level = left_level if left_type == -1.0 else right_level
        midpoint = (high_level + low_level) / 2.0

        range_high[index] = high_level
        range_low[index] = low_level
        equilibrium[index] = midpoint

        close_price = float(frame["close"].iloc[index])
        if math.isclose(close_price, midpoint, rel_tol=0.0, abs_tol=1e-12):
            zone[index] = 0
        elif close_price > midpoint:
            zone[index] = -1
        else:
            zone[index] = 1

    return pd.DataFrame(
        {
            "RangeHigh": pd.Series(range_high, index=frame.index, dtype=float),
            "RangeLow": pd.Series(range_low, index=frame.index, dtype=float),
            "Equilibrium": pd.Series(equilibrium, index=frame.index, dtype=float),
            "Zone": pd.Series(zone, index=frame.index, dtype=int),
        }
    )


def _last_alternating_pair(
    swing_frame: pd.DataFrame,
    eligible: np.ndarray,
) -> tuple[int, int] | None:
    for right_index in range(len(eligible) - 1, 0, -1):
        right = int(eligible[right_index])
        left = int(eligible[right_index - 1])
        left_type = float(swing_frame["HighLow"].iloc[left])
        right_type = float(swing_frame["HighLow"].iloc[right])
        if left_type != right_type:
            return left, right
    return None
