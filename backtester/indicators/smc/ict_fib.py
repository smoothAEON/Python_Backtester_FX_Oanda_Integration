"""ICT Optimal Trade Entry helper built from shared SMC swings.

Example:
    >>> from backtester.indicators.research import ICTFibEngine
    >>> engine = ICTFibEngine(swing_length=3)
    >>> fib = engine.update(strategy.to_ohlcv_dataframe())
    >>> if fib is not None and fib["direction"] == "up":
    ...     discount_entry = fib["ote_zone"]["lower"]
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import math

import numpy as np
import pandas as pd

from . import swing_highs_lows
from ..talib_indicators import atr


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
    swing_frame: pd.DataFrame,
    index: pd.Index,
) -> pd.DataFrame:
    """Validate and normalise a swing-highs-lows DataFrame."""
    required = ("HighLow", "Level")
    missing = [column for column in required if column not in swing_frame.columns]
    if missing:
        raise ValueError(f"Missing required swing columns: {missing}")
    frame = swing_frame.loc[:, list(required)].copy()
    if len(frame) != len(index):
        raise ValueError("swing_highs_lows must have the same length as ohlc")
    frame.index = index
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame

_HIGH_PIVOT = 1
_LOW_PIVOT = -1

type PivotSignature = tuple[int, int, float]
type PairSignature = tuple[PivotSignature, PivotSignature]


@dataclass(slots=True, frozen=True)
class _ConfirmedPivot:
    index: int
    side: int
    price: float

    def signature(self) -> PivotSignature:
        return (int(self.index), int(self.side), float(self.price))

    def as_dict(self) -> dict[str, object]:
        return {
            "index": int(self.index),
            "kind": "high" if self.side == _HIGH_PIVOT else "low",
            "price": float(self.price),
        }


class ICTFibEngine:
    """Track the latest frozen ICT OTE fib from shared swing-high/low pivots."""

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
                "ICTFibEngine now requires swing_length; left_bars/right_bars are no longer supported"
            )
        if legacy_params:
            unexpected = ", ".join(sorted(legacy_params))
            raise TypeError(f"Unexpected ICTFibEngine parameters: {unexpected}")
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
        """Process newly closed bars and return the current frozen fib if one exists."""

        frame = _coerce_ohlc_frame(ohlc)
        length = len(frame)
        if length < self._processed_length:
            raise ValueError(
                "ICTFibEngine only supports append-only updates; call reset() for shorter inputs"
            )

        swing_frame = _coerce_swing_frame(
            swing_highs_lows(frame, swing_length=self.swing_length),
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
        high_low_values = swing_frame["HighLow"].to_numpy(dtype=float)
        candidate_positions = np.where(~np.isnan(high_low_values))[0]
        final_index = len(swing_frame) - 1

        for position in candidate_positions:
            if position == final_index:
                continue

            side_value = float(swing_frame["HighLow"].iloc[position])
            level_value = float(swing_frame["Level"].iloc[position])
            if math.isnan(level_value):
                continue
            if side_value not in (_HIGH_PIVOT, _LOW_PIVOT):
                continue

            pivot = _ConfirmedPivot(int(position), int(side_value), float(level_value))
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
        atr_at_anchor = float(atr_values.iloc[right_pivot.index])
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
            "start_price": start_price,
            "end_price": end_price,
            "levels": levels,
            "ote_zone": {
                "upper": max(level_062, level_079),
                "mid": float(levels["0.705"]),
                "lower": min(level_062, level_079),
            },
        }
