"""Shared helpers for the Phase 10 showcase strategy library."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd

from backtester.config import resolve_instrument_spec
from backtester.sizing import BaseSizer, SizingDecision
from backtester.strategy import BaseStrategy


def latest_value(series: pd.Series | pd.DataFrame, column: str | None = None, offset: int = -1):
    """Return one latest scalar value or ``None`` when the value is unavailable."""

    target = series[column] if isinstance(series, pd.DataFrame) and column is not None else series
    if len(target) < abs(offset):
        return None
    value = target.iloc[offset]
    if pd.isna(value):
        return None
    return float(value)


def latest_defined_value(series: pd.Series | pd.DataFrame, column: str | None = None):
    """Return the latest non-null scalar value or ``None`` when none exists."""

    target = series[column] if isinstance(series, pd.DataFrame) and column is not None else series
    non_null = target.dropna()
    if non_null.empty:
        return None
    return float(non_null.iloc[-1])


def tail_is_ready(series: pd.Series | pd.DataFrame, count: int, column: str | None = None) -> bool:
    """Check that the latest ``count`` values are present."""

    target = series[column] if isinstance(series, pd.DataFrame) and column is not None else series
    if len(target) < count:
        return False
    return not target.iloc[-count:].isna().any()


class ShowcaseStrategy(BaseStrategy):
    """Small utility layer shared by the runnable sample strategies."""

    def __init__(self) -> None:
        super().__init__()
        self.instrument_spec = resolve_instrument_spec(self.instrument or "EUR_USD")

    def round_price(self, value: float) -> float:
        step = Decimal(str(self.instrument_spec.price_step))
        rounded_steps = (Decimal(str(value)) / step).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
        rounded = rounded_steps * step
        return round(float(rounded), self.instrument_spec.display_precision)

    def size_entry(
        self,
        sizer: BaseSizer,
        *,
        side: str,
        entry_price: float,
        stop_price: float | None,
        metadata: dict[str, Any] | None = None,
    ) -> SizingDecision:
        return sizer.size_for_entry(
            equity=self.current_equity(),
            side=side,
            entry_price=float(entry_price),
            stop_price=float(stop_price) if stop_price is not None else None,
            instrument=self.instrument or self.instrument_spec.instrument,
            metadata=dict(metadata or {}),
        )
