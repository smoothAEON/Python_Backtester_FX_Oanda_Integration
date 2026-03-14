"""Smart Money Concepts liquidity helper."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .structure import _coerce_ohlc_frame, _coerce_swing_frame


def liquidity(
    ohlc: pd.DataFrame,
    swing_highs_lows: pd.DataFrame,
    range_percent: float = 0.01,
) -> pd.DataFrame:
    """Mirror the upstream liquidity defaults for local backtests."""

    if range_percent <= 0:
        raise ValueError("range_percent must be positive")

    frame = _coerce_ohlc_frame(ohlc)
    swing_frame = _coerce_swing_frame(swing_highs_lows, frame.index)
    length = len(frame)
    pip_range = (frame["high"].max() - frame["low"].min()) * range_percent

    high_values = frame["high"].to_numpy(dtype=float)
    low_values = frame["low"].to_numpy(dtype=float)
    swing_values = swing_frame["HighLow"].to_numpy(dtype=float).copy()
    swing_levels = swing_frame["Level"].to_numpy(dtype=float).copy()

    liquidity_values = np.full(length, np.nan, dtype=float)
    level_values = np.full(length, np.nan, dtype=float)
    end_values = np.full(length, np.nan, dtype=float)
    swept_values = np.full(length, np.nan, dtype=float)

    bullish_indices = np.nonzero(swing_values == 1.0)[0]
    for i in bullish_indices:
        if swing_values[i] != 1.0:
            continue
        high_level = swing_levels[i]
        range_low = high_level - pip_range
        range_high = high_level + pip_range
        group_levels = [high_level]
        group_end = i

        start = i + 1
        if start < length:
            swept_mask = high_values[start:] >= range_high
            swept = start + int(np.argmax(swept_mask)) if np.any(swept_mask) else 0
        else:
            swept = 0

        for j in bullish_indices:
            if j <= i:
                continue
            if swept and j >= swept:
                break
            if swing_values[j] == 1.0 and range_low <= swing_levels[j] <= range_high:
                group_levels.append(swing_levels[j])
                group_end = j
                swing_values[j] = 0.0
        if len(group_levels) > 1:
            liquidity_values[i] = 1.0
            level_values[i] = float(sum(group_levels) / len(group_levels))
            end_values[i] = float(group_end)
            swept_values[i] = float(swept) if swept else np.nan

    bearish_indices = np.nonzero(swing_values == -1.0)[0]
    for i in bearish_indices:
        if swing_values[i] != -1.0:
            continue
        low_level = swing_levels[i]
        range_low = low_level - pip_range
        range_high = low_level + pip_range
        group_levels = [low_level]
        group_end = i

        start = i + 1
        if start < length:
            swept_mask = low_values[start:] <= range_low
            swept = start + int(np.argmax(swept_mask)) if np.any(swept_mask) else 0
        else:
            swept = 0

        for j in bearish_indices:
            if j <= i:
                continue
            if swept and j >= swept:
                break
            if swing_values[j] == -1.0 and range_low <= swing_levels[j] <= range_high:
                group_levels.append(swing_levels[j])
                group_end = j
                swing_values[j] = 0.0
        if len(group_levels) > 1:
            liquidity_values[i] = -1.0
            level_values[i] = float(sum(group_levels) / len(group_levels))
            end_values[i] = float(group_end)
            swept_values[i] = float(swept) if swept else np.nan

    return pd.DataFrame(
        {
            "Liquidity": pd.Series(
                liquidity_values,
                index=frame.index,
                dtype=float,
            ),
            "Level": pd.Series(level_values, index=frame.index, dtype=float),
            "End": pd.Series(end_values, index=frame.index, dtype=float),
            "Swept": pd.Series(swept_values, index=frame.index, dtype=float),
        }
    )
