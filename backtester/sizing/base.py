"""Shared position-sizing contracts and helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
import math
from typing import Any, Literal

from backtester.config import InstrumentSpec, resolve_instrument_spec

EntrySide = Literal["long", "short"]


@dataclass(slots=True)
class SizingDecision:
    """Explainable output from one sizing calculation."""

    method: str
    instrument: str
    side: EntrySide
    equity: float
    entry_price: float
    stop_price: float | None
    stop_distance: float | None
    raw_size: float
    final_size: float
    min_size: float
    size_step: float
    accepted: bool
    reason: str | None
    details: dict[str, Any] = field(default_factory=dict)


class BaseSizer(ABC):
    """Base class for deterministic, inspectable position sizers."""

    method = "base"

    @abstractmethod
    def size_for_entry(
        self,
        *,
        equity: float,
        side: EntrySide,
        entry_price: float,
        stop_price: float | None,
        instrument: str,
        metadata: dict[str, Any] | None = None,
    ) -> SizingDecision:
        """Return an explainable sizing decision for one entry setup."""

    def _resolve_spec(self, instrument: str) -> InstrumentSpec:
        try:
            return resolve_instrument_spec(instrument)
        except ValueError:
            return InstrumentSpec(
                instrument=str(instrument).strip().upper(),
                pip_size=0.0001,
            )

    def _normalize_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        return dict(metadata or {})

    def _validate_common_inputs(
        self,
        *,
        side: str,
        equity: float,
        entry_price: float,
        stop_price: float | None,
    ) -> str | None:
        if side not in {"long", "short"}:
            return "invalid_side"
        if not math.isfinite(equity) or equity <= 0:
            return "invalid_equity"
        if not math.isfinite(entry_price) or entry_price <= 0:
            return "invalid_entry_price"
        if stop_price is not None and (not math.isfinite(stop_price) or stop_price <= 0):
            return "invalid_stop_price"
        return None

    def _resolve_stop_distance(
        self,
        *,
        side: EntrySide,
        entry_price: float,
        stop_price: float | None,
    ) -> tuple[float | None, str | None]:
        if stop_price is None:
            return None, "missing_stop_price"
        if side == "long":
            if stop_price > entry_price:
                return None, "stop_not_below_entry"
        else:
            if stop_price < entry_price:
                return None, "stop_not_above_entry"
        distance = abs(entry_price - stop_price)
        if distance == 0:
            return None, "zero_stop_distance"
        return distance, None

    def _per_unit_risk(self, distance: float, spec: InstrumentSpec) -> float:
        return distance * spec.contract_size * spec.point_value

    def _finalize_size(self, raw_size: float, *, size_step: float) -> float:
        if raw_size <= 0:
            return 0.0
        step = Decimal(str(size_step))
        multiples = (Decimal(str(raw_size)) / step).to_integral_value(rounding=ROUND_DOWN)
        return float(multiples * step)

    def _default_details(
        self,
        *,
        spec: InstrumentSpec,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "pip_size": spec.pip_size,
            "contract_size": spec.contract_size,
            "point_value": spec.point_value,
            "metadata": dict(metadata),
        }

    def _reject(
        self,
        *,
        method: str,
        instrument: str,
        side: EntrySide,
        equity: float,
        entry_price: float,
        stop_price: float | None,
        stop_distance: float | None,
        raw_size: float,
        spec: InstrumentSpec,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> SizingDecision:
        return SizingDecision(
            method=method,
            instrument=spec.instrument or str(instrument).strip().upper(),
            side=side,
            equity=float(equity),
            entry_price=float(entry_price),
            stop_price=float(stop_price) if stop_price is not None else None,
            stop_distance=float(stop_distance) if stop_distance is not None else None,
            raw_size=float(raw_size),
            final_size=0.0,
            min_size=float(spec.min_size),
            size_step=float(spec.size_step),
            accepted=False,
            reason=reason,
            details=dict(details or {}),
        )

    def _accept_or_reject_size(
        self,
        *,
        method: str,
        instrument: str,
        side: EntrySide,
        equity: float,
        entry_price: float,
        stop_price: float | None,
        stop_distance: float | None,
        raw_size: float,
        spec: InstrumentSpec,
        details: dict[str, Any] | None = None,
    ) -> SizingDecision:
        if not math.isfinite(raw_size) or raw_size <= 0:
            return self._reject(
                method=method,
                instrument=instrument,
                side=side,
                equity=equity,
                entry_price=entry_price,
                stop_price=stop_price,
                stop_distance=stop_distance,
                raw_size=raw_size if math.isfinite(raw_size) else 0.0,
                spec=spec,
                reason="non_positive_size",
                details=details,
            )

        final_size = self._finalize_size(raw_size, size_step=spec.size_step)
        if final_size < spec.min_size:
            return self._reject(
                method=method,
                instrument=instrument,
                side=side,
                equity=equity,
                entry_price=entry_price,
                stop_price=stop_price,
                stop_distance=stop_distance,
                raw_size=raw_size,
                spec=spec,
                reason="size_below_minimum",
                details=details,
            )

        return SizingDecision(
            method=method,
            instrument=spec.instrument,
            side=side,
            equity=float(equity),
            entry_price=float(entry_price),
            stop_price=float(stop_price) if stop_price is not None else None,
            stop_distance=float(stop_distance) if stop_distance is not None else None,
            raw_size=float(raw_size),
            final_size=float(final_size),
            min_size=float(spec.min_size),
            size_step=float(spec.size_step),
            accepted=True,
            reason=None,
            details=dict(details or {}),
        )
