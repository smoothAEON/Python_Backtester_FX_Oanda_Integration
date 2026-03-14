"""Smart Money Concepts structure helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd


def swing_highs_lows(ohlc: pd.DataFrame, swing_length: int = 50) -> pd.DataFrame:
    """Mirror the upstream swing-high/swing-low defaults on local data."""

    if swing_length <= 0:
        raise ValueError("swing_length must be positive")

    frame = _coerce_ohlc_frame(ohlc)
    effective = swing_length * 2
    swings = np.where(
        frame["high"] == frame["high"].shift(-(effective // 2)).rolling(effective).max(),
        1.0,
        np.where(
            frame["low"] == frame["low"].shift(-(effective // 2)).rolling(effective).min(),
            -1.0,
            np.nan,
        ),
    )

    while True:
        positions = np.where(~np.isnan(swings))[0]
        if len(positions) < 2:
            break

        current = swings[positions[:-1]]
        nxt = swings[positions[1:]]
        highs = frame["high"].iloc[positions[:-1]].to_numpy(dtype=float)
        lows = frame["low"].iloc[positions[:-1]].to_numpy(dtype=float)
        next_highs = frame["high"].iloc[positions[1:]].to_numpy(dtype=float)
        next_lows = frame["low"].iloc[positions[1:]].to_numpy(dtype=float)

        index_to_remove = np.zeros(len(positions), dtype=bool)
        consecutive_highs = (current == 1.0) & (nxt == 1.0)
        index_to_remove[:-1] |= consecutive_highs & (highs < next_highs)
        index_to_remove[1:] |= consecutive_highs & (highs >= next_highs)

        consecutive_lows = (current == -1.0) & (nxt == -1.0)
        index_to_remove[:-1] |= consecutive_lows & (lows > next_lows)
        index_to_remove[1:] |= consecutive_lows & (lows <= next_lows)

        if not index_to_remove.any():
            break

        swings[positions[index_to_remove]] = np.nan

    positions = np.where(~np.isnan(swings))[0]
    if len(positions) > 0:
        if swings[positions[0]] == 1.0:
            swings[0] = -1.0
        if swings[positions[0]] == -1.0:
            swings[0] = 1.0
        if swings[positions[-1]] == -1.0:
            swings[-1] = 1.0
        if swings[positions[-1]] == 1.0:
            swings[-1] = -1.0

    level = np.where(
        ~np.isnan(swings),
        np.where(
            swings == 1.0,
            frame["high"].to_numpy(dtype=float),
            frame["low"].to_numpy(dtype=float),
        ),
        np.nan,
    )
    return pd.DataFrame(
        {
            "HighLow": pd.Series(swings, index=frame.index, dtype=float),
            "Level": pd.Series(level, index=frame.index, dtype=float),
        }
    )


def bos_choch(
    ohlc: pd.DataFrame,
    swing_highs_lows: pd.DataFrame,
    close_break: bool = True,
) -> pd.DataFrame:
    """Mirror upstream BOS/CHOCH semantics with local deterministic output."""

    frame = _coerce_ohlc_frame(ohlc)
    swing_frame = _coerce_swing_frame(swing_highs_lows, frame.index)

    level_order: list[float] = []
    highs_lows_order: list[float] = []
    bos = np.zeros(len(frame), dtype=np.int32)
    choch = np.zeros(len(frame), dtype=np.int32)
    level = np.zeros(len(frame), dtype=np.float64)
    last_positions: list[int] = []

    for i in range(len(swing_frame["HighLow"])):
        high_low = swing_frame["HighLow"].iloc[i]
        if np.isnan(high_low):
            continue

        level_order.append(float(swing_frame["Level"].iloc[i]))
        highs_lows_order.append(float(high_low))
        if len(level_order) >= 4:
            anchor = last_positions[-2]

            bos[anchor] = (
                1
                if (
                    highs_lows_order[-4:] == [-1.0, 1.0, -1.0, 1.0]
                    and np.all(
                        [
                            level_order[-4] < level_order[-2],
                            level_order[-2] < level_order[-3],
                            level_order[-3] < level_order[-1],
                        ]
                    )
                )
                else 0
            )
            level[anchor] = level_order[-3] if bos[anchor] != 0 else 0.0

            bos[anchor] = (
                -1
                if (
                    highs_lows_order[-4:] == [1.0, -1.0, 1.0, -1.0]
                    and np.all(
                        [
                            level_order[-4] > level_order[-2],
                            level_order[-2] > level_order[-3],
                            level_order[-3] > level_order[-1],
                        ]
                    )
                )
                else bos[anchor]
            )
            level[anchor] = level_order[-3] if bos[anchor] != 0 else 0.0

            choch[anchor] = (
                1
                if (
                    highs_lows_order[-4:] == [-1.0, 1.0, -1.0, 1.0]
                    and np.all(
                        [
                            level_order[-1] > level_order[-3],
                            level_order[-3] > level_order[-4],
                            level_order[-4] > level_order[-2],
                        ]
                    )
                )
                else 0
            )
            if choch[anchor] != 0:
                level[anchor] = level_order[-3]

            choch[anchor] = (
                -1
                if (
                    highs_lows_order[-4:] == [1.0, -1.0, 1.0, -1.0]
                    and np.all(
                        [
                            level_order[-1] < level_order[-3],
                            level_order[-3] < level_order[-4],
                            level_order[-4] < level_order[-2],
                        ]
                    )
                )
                else choch[anchor]
            )
            if choch[anchor] != 0:
                level[anchor] = level_order[-3]

        last_positions.append(i)

    broken = np.zeros(len(frame), dtype=np.int32)
    for i in np.where(np.logical_or(bos != 0, choch != 0))[0]:
        if bos[i] == 1 or choch[i] == 1:
            mask = (
                frame["close" if close_break else "high"]
                .iloc[i + 2 :]
                .to_numpy(dtype=float)
                > level[i]
            )
        else:
            mask = (
                frame["close" if close_break else "low"]
                .iloc[i + 2 :]
                .to_numpy(dtype=float)
                < level[i]
            )
        if np.any(mask):
            broken_index = int(np.argmax(mask)) + i + 2
            broken[i] = broken_index
            for k in np.where(np.logical_or(bos != 0, choch != 0))[0]:
                if k < i and broken[k] >= broken_index:
                    bos[k] = 0
                    choch[k] = 0
                    level[k] = 0.0

    unresolved = np.where(
        np.logical_and(np.logical_or(bos != 0, choch != 0), broken == 0)
    )[0]
    bos[unresolved] = 0
    choch[unresolved] = 0
    level[unresolved] = 0.0

    return pd.DataFrame(
        {
            "BOS": pd.Series(np.where(bos != 0, bos, np.nan), index=frame.index, dtype=float),
            "CHOCH": pd.Series(
                np.where(choch != 0, choch, np.nan),
                index=frame.index,
                dtype=float,
            ),
            "Level": pd.Series(
                np.where(level != 0.0, level, np.nan),
                index=frame.index,
                dtype=float,
            ),
            "BrokenIndex": pd.Series(
                np.where(broken != 0, broken, np.nan),
                index=frame.index,
                dtype=float,
            ),
        }
    )


def _coerce_ohlc_frame(ohlc: pd.DataFrame) -> pd.DataFrame:
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
