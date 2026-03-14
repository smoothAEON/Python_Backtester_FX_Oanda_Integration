"""ICT Optimal Trade Entry helper built from confirmed close-only swings.

Example:
    >>> from backtester.indicators import ICTFibEngine
    >>> engine = ICTFibEngine(left_bars=2, right_bars=2)
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

from ..talib_indicators import atr
from .structure import _coerce_ohlc_frame

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
        return (self.index, self.side, self.price)

    def as_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "kind": "high" if self.side == _HIGH_PIVOT else "low",
            "price": self.price,
        }


class ICTFibEngine:
    """Track the latest frozen ICT OTE fib from confirmed close-only pivots."""

    def __init__(
        self,
        *,
        left_bars: int = 3,
        right_bars: int = 3,
        atr_period: int = 14,
        atr_multiplier: float | None = None,
    ) -> None:
        if left_bars <= 0:
            raise ValueError("left_bars must be positive")
        if right_bars <= 0:
            raise ValueError("right_bars must be positive")
        if atr_period <= 0:
            raise ValueError("atr_period must be positive")
        if atr_multiplier is not None and atr_multiplier <= 0:
            raise ValueError("atr_multiplier must be positive when provided")

        self.left_bars = int(left_bars)
        self.right_bars = int(right_bars)
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
        self._processed_length = 0

    def update(self, ohlc: pd.DataFrame) -> dict[str, object] | None:
        """Process newly closed bars and return the current frozen fib if one exists."""

        frame = _coerce_ohlc_frame(ohlc)
        length = len(frame)
        if length < self._processed_length:
            raise ValueError(
                "ICTFibEngine only supports append-only updates; call reset() for shorter inputs"
            )

        close_values = frame["close"].to_numpy(dtype=float)
        for closed_bar_index in range(self._processed_length, length):
            candidate_index = closed_bar_index - self.right_bars
            pivot = self._confirm_pivot(close_values, candidate_index)
            if pivot is None:
                continue
            self._ingest_pivot(frame, pivot)

        self._processed_length = length
        return self.active_fib

    def _confirm_pivot(
        self,
        close_values: np.ndarray,
        candidate_index: int,
    ) -> _ConfirmedPivot | None:
        if candidate_index < self.left_bars:
            return None
        if candidate_index + self.right_bars >= len(close_values):
            return None

        candidate_close = float(close_values[candidate_index])
        left_window = close_values[candidate_index - self.left_bars : candidate_index]
        right_window = close_values[
            candidate_index + 1 : candidate_index + self.right_bars + 1
        ]

        if candidate_close > float(np.max(left_window)) and candidate_close > float(
            np.max(right_window)
        ):
            return _ConfirmedPivot(candidate_index, _HIGH_PIVOT, candidate_close)
        if candidate_close < float(np.min(left_window)) and candidate_close < float(
            np.min(right_window)
        ):
            return _ConfirmedPivot(candidate_index, _LOW_PIVOT, candidate_close)
        return None

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
