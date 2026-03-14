"""Smart Money Concepts order block helper."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .structure import _coerce_ohlc_frame, _coerce_swing_frame


def ob(
    ohlcv: pd.DataFrame,
    swing_highs_lows: pd.DataFrame,
    close_mitigation: bool = False,
) -> pd.DataFrame:
    """Mirror the upstream order-block defaults for local backtests."""

    frame = _coerce_ohlc_frame(ohlcv)
    if "volume" not in ohlcv.columns:
        raise ValueError("Missing required OHLCV columns: ['volume']")
    frame["volume"] = pd.to_numeric(ohlcv["volume"], errors="raise")
    swing_frame = _coerce_swing_frame(swing_highs_lows, frame.index)

    length = len(frame)
    open_values = frame["open"].to_numpy(dtype=float)
    high_values = frame["high"].to_numpy(dtype=float)
    low_values = frame["low"].to_numpy(dtype=float)
    close_values = frame["close"].to_numpy(dtype=float)
    volume_values = frame["volume"].to_numpy(dtype=float)
    swing_values = swing_frame["HighLow"].to_numpy(dtype=float)

    crossed = np.full(length, False, dtype=bool)
    ob_values = np.zeros(length, dtype=np.int32)
    top_values = np.zeros(length, dtype=np.float64)
    bottom_values = np.zeros(length, dtype=np.float64)
    ob_volume_values = np.zeros(length, dtype=np.float64)
    low_volume_values = np.zeros(length, dtype=np.float64)
    high_volume_values = np.zeros(length, dtype=np.float64)
    percentage_values = np.zeros(length, dtype=np.float64)
    mitigated_index = np.zeros(length, dtype=np.int32)
    breaker = np.full(length, False, dtype=bool)

    swing_high_indices = np.flatnonzero(swing_values == 1.0)
    swing_low_indices = np.flatnonzero(swing_values == -1.0)

    active_bullish: list[int] = []
    for close_index in range(length):
        for idx in active_bullish.copy():
            if breaker[idx]:
                if high_values[close_index] > top_values[idx]:
                    ob_values[idx] = 0
                    top_values[idx] = 0.0
                    bottom_values[idx] = 0.0
                    ob_volume_values[idx] = 0.0
                    low_volume_values[idx] = 0.0
                    high_volume_values[idx] = 0.0
                    mitigated_index[idx] = 0
                    percentage_values[idx] = 0.0
                    active_bullish.remove(idx)
            else:
                breached = low_values[close_index] < bottom_values[idx]
                if close_mitigation:
                    breached = (
                        min(open_values[close_index], close_values[close_index])
                        < bottom_values[idx]
                    )
                if breached:
                    breaker[idx] = True
                    mitigated_index[idx] = close_index - 1

        pos = np.searchsorted(swing_high_indices, close_index)
        last_top_index = swing_high_indices[pos - 1] if pos > 0 else None
        if last_top_index is None:
            continue
        if close_values[close_index] <= high_values[last_top_index] or crossed[last_top_index]:
            continue

        crossed[last_top_index] = True
        default_index = close_index - 1
        ob_bottom = high_values[default_index]
        ob_top = low_values[default_index]
        ob_index = default_index
        if close_index - last_top_index > 1:
            start = last_top_index + 1
            end = close_index
            if end > start:
                segment = low_values[start:end]
                min_value = segment.min()
                candidates = np.nonzero(segment == min_value)[0]
                if candidates.size:
                    candidate_index = start + int(candidates[-1])
                    ob_bottom = low_values[candidate_index]
                    ob_top = high_values[candidate_index]
                    ob_index = candidate_index
        ob_values[ob_index] = 1
        top_values[ob_index] = ob_top
        bottom_values[ob_index] = ob_bottom
        current_volume = volume_values[close_index]
        previous_one = volume_values[close_index - 1] if close_index >= 1 else 0.0
        previous_two = volume_values[close_index - 2] if close_index >= 2 else 0.0
        ob_volume_values[ob_index] = current_volume + previous_one + previous_two
        low_volume_values[ob_index] = previous_two
        high_volume_values[ob_index] = current_volume + previous_one
        max_volume = max(high_volume_values[ob_index], low_volume_values[ob_index])
        percentage_values[ob_index] = (
            min(high_volume_values[ob_index], low_volume_values[ob_index]) / max_volume * 100.0
            if max_volume != 0.0
            else 100.0
        )
        active_bullish.append(ob_index)

    active_bearish: list[int] = []
    for close_index in range(length):
        for idx in active_bearish.copy():
            if breaker[idx]:
                if low_values[close_index] < bottom_values[idx]:
                    ob_values[idx] = 0
                    top_values[idx] = 0.0
                    bottom_values[idx] = 0.0
                    ob_volume_values[idx] = 0.0
                    low_volume_values[idx] = 0.0
                    high_volume_values[idx] = 0.0
                    mitigated_index[idx] = 0
                    percentage_values[idx] = 0.0
                    active_bearish.remove(idx)
            else:
                breached = high_values[close_index] > top_values[idx]
                if close_mitigation:
                    breached = (
                        max(open_values[close_index], close_values[close_index])
                        > top_values[idx]
                    )
                if breached:
                    breaker[idx] = True
                    mitigated_index[idx] = close_index

        pos = np.searchsorted(swing_low_indices, close_index)
        last_bottom_index = swing_low_indices[pos - 1] if pos > 0 else None
        if last_bottom_index is None:
            continue
        if close_values[close_index] >= low_values[last_bottom_index] or crossed[last_bottom_index]:
            continue

        crossed[last_bottom_index] = True
        default_index = close_index - 1
        ob_top = high_values[default_index]
        ob_bottom = low_values[default_index]
        ob_index = default_index
        if close_index - last_bottom_index > 1:
            start = last_bottom_index + 1
            end = close_index
            if end > start:
                segment = high_values[start:end]
                max_value = segment.max()
                candidates = np.nonzero(segment == max_value)[0]
                if candidates.size:
                    candidate_index = start + int(candidates[-1])
                    ob_top = high_values[candidate_index]
                    ob_bottom = low_values[candidate_index]
                    ob_index = candidate_index
        ob_values[ob_index] = -1
        top_values[ob_index] = ob_top
        bottom_values[ob_index] = ob_bottom
        current_volume = volume_values[close_index]
        previous_one = volume_values[close_index - 1] if close_index >= 1 else 0.0
        previous_two = volume_values[close_index - 2] if close_index >= 2 else 0.0
        ob_volume_values[ob_index] = current_volume + previous_one + previous_two
        low_volume_values[ob_index] = current_volume + previous_one
        high_volume_values[ob_index] = previous_two
        max_volume = max(high_volume_values[ob_index], low_volume_values[ob_index])
        percentage_values[ob_index] = (
            min(high_volume_values[ob_index], low_volume_values[ob_index]) / max_volume * 100.0
            if max_volume != 0.0
            else 100.0
        )
        active_bearish.append(ob_index)

    mask = ob_values != 0
    return pd.DataFrame(
        {
            "OB": pd.Series(np.where(mask, ob_values, np.nan), index=frame.index, dtype=float),
            "Top": pd.Series(np.where(mask, top_values, np.nan), index=frame.index, dtype=float),
            "Bottom": pd.Series(
                np.where(mask, bottom_values, np.nan),
                index=frame.index,
                dtype=float,
            ),
            "OBVolume": pd.Series(
                np.where(mask, ob_volume_values, np.nan),
                index=frame.index,
                dtype=float,
            ),
            "Percentage": pd.Series(
                np.where(mask, percentage_values, np.nan),
                index=frame.index,
                dtype=float,
            ),
        }
    )
