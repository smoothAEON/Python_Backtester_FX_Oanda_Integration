"""Causal SMC-style helpers for live-safe strategy/runtime use.

These helpers never rewrite prior rows based on future candles. When a pivot
or derived structure becomes known only after additional bars close, the signal
is emitted on the confirmation bar and carries the original pivot index as
metadata.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from ..talib_indicators import atr

_HIGH_PIVOT = 1
_LOW_PIVOT = -1


def _coerce_ohlc_frame(ohlc: pd.DataFrame) -> pd.DataFrame:
    required = ("open", "high", "low", "close")
    missing = [column for column in required if column not in ohlc.columns]
    if missing:
        raise ValueError(f"Missing required OHLC columns: {missing}")

    frame = ohlc.loc[:, list(required)].copy()
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    return frame


def _coerce_ohlcv_frame(ohlcv: pd.DataFrame) -> pd.DataFrame:
    frame = _coerce_ohlc_frame(ohlcv)
    if "volume" in ohlcv.columns:
        frame["volume"] = pd.to_numeric(ohlcv["volume"], errors="raise")
    else:
        frame["volume"] = 0.0
    return frame


def _coerce_confirmed_swing_frame(
    swing_frame: pd.DataFrame,
    index: pd.Index,
) -> pd.DataFrame:
    required = ("HighLow", "Level", "PivotIndex", "ConfirmationIndex")
    missing = [column for column in required if column not in swing_frame.columns]
    if missing:
        raise ValueError(f"Missing required confirmed swing columns: {missing}")

    frame = swing_frame.loc[:, list(required)].copy()
    if len(frame) != len(index):
        raise ValueError("confirmed swings must have the same length as ohlc")
    frame.index = index
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


@dataclass(frozen=True, slots=True)
class _PivotEvent:
    confirmation_index: int
    pivot_index: int
    side: int
    level: float

    def signature(self) -> tuple[int, int, float]:
        return (int(self.pivot_index), int(self.side), float(self.level))


def confirmed_swings(
    ohlc: pd.DataFrame,
    *,
    swing_length: int = 1,
) -> pd.DataFrame:
    """Emit confirmed swing events on the bar where they become knowable."""

    frame = _coerce_ohlc_frame(ohlc)
    lookaround = int(swing_length)
    if lookaround <= 0:
        raise ValueError("swing_length must be positive")

    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    length = len(frame)
    high_low = np.full(length, np.nan, dtype=float)
    levels = np.full(length, np.nan, dtype=float)
    pivot_indexes = np.full(length, np.nan, dtype=float)
    confirmation_indexes = np.full(length, np.nan, dtype=float)

    for confirmation_index in range(length):
        pivot_index = confirmation_index - lookaround
        if pivot_index < 0:
            continue

        left = max(0, pivot_index - lookaround)
        right = confirmation_index
        window_highs = highs[left : right + 1]
        window_lows = lows[left : right + 1]
        candidate_high = highs[pivot_index]
        candidate_low = lows[pivot_index]

        is_high = bool(
            window_highs.size
            and np.sum(np.isclose(window_highs, candidate_high, atol=1e-12, rtol=0.0)) == 1
            and candidate_high >= float(np.max(window_highs))
        )
        is_low = bool(
            window_lows.size
            and np.sum(np.isclose(window_lows, candidate_low, atol=1e-12, rtol=0.0)) == 1
            and candidate_low <= float(np.min(window_lows))
        )
        if is_high == is_low:
            continue

        high_low[confirmation_index] = float(_HIGH_PIVOT if is_high else _LOW_PIVOT)
        levels[confirmation_index] = float(candidate_high if is_high else candidate_low)
        pivot_indexes[confirmation_index] = float(pivot_index)
        confirmation_indexes[confirmation_index] = float(confirmation_index)

    return pd.DataFrame(
        {
            "HighLow": pd.Series(high_low, index=frame.index, dtype=float),
            "Level": pd.Series(levels, index=frame.index, dtype=float),
            "PivotIndex": pd.Series(pivot_indexes, index=frame.index, dtype=float),
            "ConfirmationIndex": pd.Series(confirmation_indexes, index=frame.index, dtype=float),
        }
    )


def confirmed_structure(
    ohlc: pd.DataFrame,
    swing_frame: pd.DataFrame,
    *,
    close_break: bool = True,
) -> pd.DataFrame:
    """Emit one-time BOS/CHOCH events from confirmed swing levels."""

    frame = _coerce_ohlc_frame(ohlc)
    swings = _coerce_confirmed_swing_frame(swing_frame, frame.index)
    length = len(frame)
    bos = np.full(length, np.nan, dtype=float)
    choch = np.full(length, np.nan, dtype=float)
    levels = np.full(length, np.nan, dtype=float)
    broken_indexes = np.full(length, np.nan, dtype=float)

    latest_high: _PivotEvent | None = None
    latest_low: _PivotEvent | None = None
    broken_high_signature: tuple[int, int, float] | None = None
    broken_low_signature: tuple[int, int, float] | None = None
    structure_side = 0

    for index in range(length):
        event = _event_at(swings, index)
        if event is not None:
            if event.side == _HIGH_PIVOT:
                latest_high = event
            else:
                latest_low = event

        close_price = float(frame["close"].iloc[index])
        high_price = float(frame["high"].iloc[index])
        low_price = float(frame["low"].iloc[index])

        bullish_break = False
        bearish_break = False
        if latest_high is not None and latest_high.signature() != broken_high_signature:
            bullish_break = close_price > latest_high.level if close_break else high_price > latest_high.level
        if latest_low is not None and latest_low.signature() != broken_low_signature:
            bearish_break = close_price < latest_low.level if close_break else low_price < latest_low.level

        if bullish_break and not bearish_break and latest_high is not None:
            if structure_side < 0:
                choch[index] = 1.0
            else:
                bos[index] = 1.0
            levels[index] = latest_high.level
            broken_indexes[index] = float(latest_high.pivot_index)
            broken_high_signature = latest_high.signature()
            structure_side = 1
        elif bearish_break and not bullish_break and latest_low is not None:
            if structure_side > 0:
                choch[index] = -1.0
            else:
                bos[index] = -1.0
            levels[index] = latest_low.level
            broken_indexes[index] = float(latest_low.pivot_index)
            broken_low_signature = latest_low.signature()
            structure_side = -1

    return pd.DataFrame(
        {
            "BOS": pd.Series(bos, index=frame.index, dtype=float),
            "CHOCH": pd.Series(choch, index=frame.index, dtype=float),
            "Level": pd.Series(levels, index=frame.index, dtype=float),
            "BrokenIndex": pd.Series(broken_indexes, index=frame.index, dtype=float),
        }
    )


def confirmed_order_blocks(
    ohlcv: pd.DataFrame,
    structure_frame: pd.DataFrame,
    *,
    lookback: int = 6,
) -> pd.DataFrame:
    """Emit order-block definitions on confirmed structure-break bars."""

    frame = _coerce_ohlcv_frame(ohlcv)
    if lookback <= 0:
        raise ValueError("lookback must be positive")

    required = ("BOS", "CHOCH")
    missing = [column for column in required if column not in structure_frame.columns]
    if missing:
        raise ValueError(f"Missing required structure columns: {missing}")

    structure = structure_frame.loc[:, list(required)].copy()
    if len(structure) != len(frame):
        raise ValueError("structure_frame must have the same length as ohlcv")
    structure.index = frame.index

    length = len(frame)
    order_block = np.full(length, np.nan, dtype=float)
    top = np.full(length, np.nan, dtype=float)
    bottom = np.full(length, np.nan, dtype=float)
    origin_indexes = np.full(length, np.nan, dtype=float)
    break_indexes = np.full(length, np.nan, dtype=float)

    for index in range(length):
        side = _structure_event_side(structure, index)
        if side == 0:
            continue
        if index == 0:
            continue

        start = max(0, index - int(lookback))
        if start >= index:
            continue

        if side > 0:
            origin_index = next(
                (
                    candidate
                    for candidate in range(index - 1, start - 1, -1)
                    if float(frame["close"].iloc[candidate]) < float(frame["open"].iloc[candidate])
                ),
                min(range(start, index), key=lambda candidate: float(frame["low"].iloc[candidate])),
            )
        else:
            origin_index = next(
                (
                    candidate
                    for candidate in range(index - 1, start - 1, -1)
                    if float(frame["close"].iloc[candidate]) > float(frame["open"].iloc[candidate])
                ),
                max(range(start, index), key=lambda candidate: float(frame["high"].iloc[candidate])),
            )

        order_block[index] = float(side)
        top[index] = float(frame["high"].iloc[origin_index])
        bottom[index] = float(frame["low"].iloc[origin_index])
        origin_indexes[index] = float(origin_index)
        break_indexes[index] = float(index)

    return pd.DataFrame(
        {
            "OB": pd.Series(order_block, index=frame.index, dtype=float),
            "Top": pd.Series(top, index=frame.index, dtype=float),
            "Bottom": pd.Series(bottom, index=frame.index, dtype=float),
            "OriginIndex": pd.Series(origin_indexes, index=frame.index, dtype=float),
            "BreakIndex": pd.Series(break_indexes, index=frame.index, dtype=float),
        }
    )


def confirmed_liquidity(
    ohlc: pd.DataFrame,
    swing_frame: pd.DataFrame,
    *,
    range_percent: float = 0.01,
) -> pd.DataFrame:
    """Emit sweep events once clustered confirmed swing levels are taken."""

    frame = _coerce_ohlc_frame(ohlc)
    if range_percent <= 0:
        raise ValueError("range_percent must be positive")
    swings = _coerce_confirmed_swing_frame(swing_frame, frame.index)
    length = len(frame)

    liquidity_values = np.full(length, np.nan, dtype=float)
    levels = np.full(length, np.nan, dtype=float)
    ends = np.full(length, np.nan, dtype=float)
    swept = np.full(length, np.nan, dtype=float)

    seen_events: list[_PivotEvent] = []
    swept_signatures: set[tuple[int, int, int]] = set()

    for index in range(length):
        event = _event_at(swings, index)
        if event is not None:
            seen_events.append(event)

        for side in (_HIGH_PIVOT, _LOW_PIVOT):
            cluster = _latest_same_side_cluster(seen_events, side=side)
            if cluster is None:
                continue
            tolerance = max(abs(cluster["level"]), 1.0) * float(range_percent)
            if cluster["width"] > tolerance:
                continue
            if index <= cluster["confirmation_index"]:
                continue

            signature = (
                int(side),
                int(cluster["left"].pivot_index),
                int(cluster["right"].pivot_index),
            )
            if signature in swept_signatures:
                continue

            if side == _HIGH_PIVOT and float(frame["high"].iloc[index]) > cluster["level"]:
                liquidity_values[index] = 1.0
                levels[index] = cluster["level"]
                ends[index] = float(index)
                swept[index] = 1.0
                swept_signatures.add(signature)
            elif side == _LOW_PIVOT and float(frame["low"].iloc[index]) < cluster["level"]:
                liquidity_values[index] = -1.0
                levels[index] = cluster["level"]
                ends[index] = float(index)
                swept[index] = -1.0
                swept_signatures.add(signature)

    return pd.DataFrame(
        {
            "Liquidity": pd.Series(liquidity_values, index=frame.index, dtype=float),
            "Level": pd.Series(levels, index=frame.index, dtype=float),
            "End": pd.Series(ends, index=frame.index, dtype=float),
            "Swept": pd.Series(swept, index=frame.index, dtype=float),
        }
    )


def confirmed_premium_discount(
    ohlc: pd.DataFrame,
    swing_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Classify price against the latest alternating confirmed swing pair."""

    frame = _coerce_ohlc_frame(ohlc)
    swings = _coerce_confirmed_swing_frame(swing_frame, frame.index)
    length = len(frame)

    range_high = np.full(length, np.nan, dtype=float)
    range_low = np.full(length, np.nan, dtype=float)
    equilibrium = np.full(length, np.nan, dtype=float)
    zone = np.zeros(length, dtype=np.int32)
    left_indexes = np.full(length, np.nan, dtype=float)
    right_indexes = np.full(length, np.nan, dtype=float)

    seen_events: list[_PivotEvent] = []
    for index in range(length):
        event = _event_at(swings, index)
        if event is not None:
            seen_events.append(event)

        pair = _latest_alternating_pair(seen_events)
        if pair is None:
            continue

        left_event, right_event = pair
        high_level = left_event.level if left_event.side == _HIGH_PIVOT else right_event.level
        low_level = left_event.level if left_event.side == _LOW_PIVOT else right_event.level
        midpoint = (high_level + low_level) / 2.0
        close_price = float(frame["close"].iloc[index])

        range_high[index] = high_level
        range_low[index] = low_level
        equilibrium[index] = midpoint
        left_indexes[index] = float(left_event.pivot_index)
        right_indexes[index] = float(right_event.pivot_index)

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
            "LeftPivotIndex": pd.Series(left_indexes, index=frame.index, dtype=float),
            "RightPivotIndex": pd.Series(right_indexes, index=frame.index, dtype=float),
        }
    )


def confirmed_retracements(
    ohlc: pd.DataFrame,
    swing_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Track current and deepest retracement from the latest confirmed impulse."""

    frame = _coerce_ohlc_frame(ohlc)
    swings = _coerce_confirmed_swing_frame(swing_frame, frame.index)
    length = len(frame)

    direction = np.full(length, np.nan, dtype=float)
    current_retracement = np.full(length, np.nan, dtype=float)
    deepest_retracement = np.full(length, np.nan, dtype=float)

    seen_events: list[_PivotEvent] = []
    active_pair_signature: tuple[tuple[int, int, float], tuple[int, int, float]] | None = None
    active_deepest = 0.0

    for index in range(length):
        event = _event_at(swings, index)
        if event is not None:
            seen_events.append(event)

        pair = _latest_alternating_pair(seen_events)
        if pair is None:
            continue

        left_event, right_event = pair
        pair_signature = (left_event.signature(), right_event.signature())
        if pair_signature != active_pair_signature:
            active_pair_signature = pair_signature
            active_deepest = 0.0

        if left_event.side == _LOW_PIVOT and right_event.side == _HIGH_PIVOT:
            range_size = right_event.level - left_event.level
            if range_size <= 0:
                continue
            retracement = max(0.0, ((right_event.level - float(frame["close"].iloc[index])) / range_size) * 100.0)
            direction[index] = 1.0
        elif left_event.side == _HIGH_PIVOT and right_event.side == _LOW_PIVOT:
            range_size = left_event.level - right_event.level
            if range_size <= 0:
                continue
            retracement = max(0.0, ((float(frame["close"].iloc[index]) - right_event.level) / range_size) * 100.0)
            direction[index] = -1.0
        else:
            continue

        active_deepest = max(active_deepest, retracement)
        current_retracement[index] = retracement
        deepest_retracement[index] = active_deepest

    return pd.DataFrame(
        {
            "Direction": pd.Series(direction, index=frame.index, dtype=float),
            "CurrentRetracement%": pd.Series(current_retracement, index=frame.index, dtype=float),
            "DeepestRetracement%": pd.Series(deepest_retracement, index=frame.index, dtype=float),
        }
    )


type PivotSignature = tuple[int, int, float]
type PairSignature = tuple[PivotSignature, PivotSignature]


@dataclass(slots=True, frozen=True)
class _ConfirmedPivot:
    confirmation_index: int
    index: int
    side: int
    price: float

    def signature(self) -> PivotSignature:
        return (int(self.index), int(self.side), float(self.price))

    def as_dict(self) -> dict[str, object]:
        return {
            "index": int(self.index),
            "confirmation_index": int(self.confirmation_index),
            "kind": "high" if self.side == _HIGH_PIVOT else "low",
            "price": float(self.price),
        }


class CausalICTFibEngine:
    """Track the latest frozen ICT OTE fib from confirmed causal pivots."""

    def __init__(
        self,
        *,
        swing_length: int | None = None,
        atr_period: int = 14,
        atr_multiplier: float | None = None,
        **legacy_params: object,
    ) -> None:
        legacy_names = sorted(
            name for name in ("left_bars", "right_bars") if name in legacy_params
        )
        if legacy_names:
            raise TypeError(
                "CausalICTFibEngine now requires swing_length; left_bars/right_bars are no longer supported"
            )
        if legacy_params:
            unexpected = ", ".join(sorted(legacy_params))
            raise TypeError(f"Unexpected CausalICTFibEngine parameters: {unexpected}")
        if swing_length is None:
            raise ValueError("swing_length must be provided explicitly")
        if atr_period <= 0:
            raise ValueError("atr_period must be positive")
        if atr_multiplier is not None and atr_multiplier <= 0:
            raise ValueError("atr_multiplier must be positive when provided")

        self.swing_length = int(swing_length)
        if self.swing_length <= 0:
            raise ValueError("swing_length must be positive")
        self.atr_period = int(atr_period)
        self.atr_multiplier = float(atr_multiplier) if atr_multiplier is not None else None
        self.reset()

    @property
    def active_fib(self) -> dict[str, object] | None:
        return deepcopy(self._active_fib)

    @property
    def confirmed_pivots(self) -> tuple[dict[str, object], ...]:
        return tuple(pivot.as_dict() for pivot in self._confirmed_pivots)

    @property
    def last_fib_signature(self) -> PairSignature | None:
        return self._last_fib_signature

    @property
    def last_handled_pair_signature(self) -> PairSignature | None:
        return self._last_handled_pair_signature

    def reset(self) -> None:
        self._confirmed_pivots: list[_ConfirmedPivot] = []
        self._active_fib: dict[str, object] | None = None
        self._last_fib_signature: PairSignature | None = None
        self._last_handled_pair_signature: PairSignature | None = None
        self._processed_pivot_signatures: set[PivotSignature] = set()
        self._processed_length = 0

    def update(self, ohlc: pd.DataFrame) -> dict[str, object] | None:
        frame = _coerce_ohlc_frame(ohlc)
        length = len(frame)
        if length < self._processed_length:
            raise ValueError(
                "CausalICTFibEngine only supports append-only updates; call reset() for shorter inputs"
            )

        swing_frame = _coerce_confirmed_swing_frame(
            confirmed_swings(frame, swing_length=self.swing_length),
            frame.index,
        )
        self._ingest_swing_candidates(frame, swing_frame)
        self._processed_length = length
        return self.active_fib

    def _ingest_swing_candidates(
        self,
        frame: pd.DataFrame,
        swing_frame: pd.DataFrame,
    ) -> None:
        candidate_positions = np.where(~np.isnan(swing_frame["HighLow"].to_numpy(dtype=float)))[0]
        for confirmation_index in candidate_positions:
            side_value = int(float(swing_frame["HighLow"].iloc[confirmation_index]))
            level_value = float(swing_frame["Level"].iloc[confirmation_index])
            pivot_index = int(float(swing_frame["PivotIndex"].iloc[confirmation_index]))

            pivot = _ConfirmedPivot(
                confirmation_index=int(confirmation_index),
                index=pivot_index,
                side=side_value,
                price=level_value,
            )
            signature = pivot.signature()
            if signature in self._processed_pivot_signatures:
                continue

            self._processed_pivot_signatures.add(signature)
            self._ingest_pivot(frame, pivot)

    def _ingest_pivot(self, frame: pd.DataFrame, pivot: _ConfirmedPivot) -> None:
        if not self._confirmed_pivots:
            self._confirmed_pivots.append(pivot)
            return

        last_pivot = self._confirmed_pivots[-1]
        if pivot.side == last_pivot.side:
            if self._is_more_extreme(pivot, last_pivot):
                self._confirmed_pivots[-1] = pivot
            return

        self._confirmed_pivots.append(pivot)
        left_pivot = self._confirmed_pivots[-2]
        right_pivot = self._confirmed_pivots[-1]
        pair_signature = (left_pivot.signature(), right_pivot.signature())
        if pair_signature == self._last_handled_pair_signature:
            return

        self._last_handled_pair_signature = pair_signature
        if not self._passes_atr_filter(frame, left_pivot, right_pivot):
            return
        if pair_signature == self._last_fib_signature:
            return

        self._active_fib = self._build_fib(left_pivot, right_pivot)
        self._last_fib_signature = pair_signature

    @staticmethod
    def _is_more_extreme(candidate: _ConfirmedPivot, current: _ConfirmedPivot) -> bool:
        if candidate.side == _HIGH_PIVOT:
            return candidate.price > current.price
        return candidate.price < current.price

    def _passes_atr_filter(
        self,
        frame: pd.DataFrame,
        left_pivot: _ConfirmedPivot,
        right_pivot: _ConfirmedPivot,
    ) -> bool:
        if self.atr_multiplier is None:
            return True

        atr_values = atr(
            frame["high"],
            frame["low"],
            frame["close"],
            period=self.atr_period,
        )
        atr_at_anchor = float(atr_values.iloc[right_pivot.confirmation_index])
        if math.isnan(atr_at_anchor):
            return True

        swing_size = abs(right_pivot.price - left_pivot.price)
        return swing_size >= self.atr_multiplier * atr_at_anchor

    def _build_fib(
        self,
        left_pivot: _ConfirmedPivot,
        right_pivot: _ConfirmedPivot,
    ) -> dict[str, object]:
        if left_pivot.side == _LOW_PIVOT and right_pivot.side == _HIGH_PIVOT:
            direction = "up"
            start_price = left_pivot.price
            end_price = right_pivot.price
            range_size = end_price - start_price
            levels = {
                "0.0": start_price,
                "0.5": end_price - (range_size * 0.5),
                "0.62": end_price - (range_size * 0.62),
                "0.705": end_price - (range_size * 0.705),
                "0.79": end_price - (range_size * 0.79),
                "1.0": end_price,
            }
        elif left_pivot.side == _HIGH_PIVOT and right_pivot.side == _LOW_PIVOT:
            direction = "down"
            start_price = left_pivot.price
            end_price = right_pivot.price
            range_size = start_price - end_price
            levels = {
                "0.0": start_price,
                "0.5": end_price + (range_size * 0.5),
                "0.62": end_price + (range_size * 0.62),
                "0.705": end_price + (range_size * 0.705),
                "0.79": end_price + (range_size * 0.79),
                "1.0": end_price,
            }
        else:
            raise ValueError("Fib anchors must be an opposite confirmed pivot pair")

        level_062 = float(levels["0.62"])
        level_079 = float(levels["0.79"])
        return {
            "direction": direction,
            "start_idx": left_pivot.index,
            "end_idx": right_pivot.index,
            "confirmed_on_idx": right_pivot.confirmation_index,
            "start_price": start_price,
            "end_price": end_price,
            "levels": levels,
            "ote_zone": {
                "upper": max(level_062, level_079),
                "mid": float(levels["0.705"]),
                "lower": min(level_062, level_079),
            },
        }


def _event_at(swing_frame: pd.DataFrame, index: int) -> _PivotEvent | None:
    side = swing_frame["HighLow"].iloc[index]
    if pd.isna(side):
        return None
    return _PivotEvent(
        confirmation_index=int(float(swing_frame["ConfirmationIndex"].iloc[index])),
        pivot_index=int(float(swing_frame["PivotIndex"].iloc[index])),
        side=int(float(side)),
        level=float(swing_frame["Level"].iloc[index]),
    )


def _latest_alternating_pair(events: list[_PivotEvent]) -> tuple[_PivotEvent, _PivotEvent] | None:
    for right_index in range(len(events) - 1, 0, -1):
        right = events[right_index]
        left = events[right_index - 1]
        if left.side != right.side:
            return left, right
    return None


def _latest_same_side_cluster(
    events: list[_PivotEvent],
    *,
    side: int,
) -> dict[str, object] | None:
    same_side = [event for event in events if event.side == side]
    if len(same_side) < 2:
        return None

    left = same_side[-2]
    right = same_side[-1]
    level = max(left.level, right.level) if side == _HIGH_PIVOT else min(left.level, right.level)
    width = abs(left.level - right.level)
    return {
        "left": left,
        "right": right,
        "level": float(level),
        "width": float(width),
        "confirmation_index": max(left.confirmation_index, right.confirmation_index),
    }


def _structure_event_side(structure_frame: pd.DataFrame, index: int) -> int:
    choch = structure_frame["CHOCH"].iloc[index]
    if pd.notna(choch):
        return int(float(choch))
    bos = structure_frame["BOS"].iloc[index]
    if pd.notna(bos):
        return int(float(bos))
    return 0
