"""Volatility-aware position sizing."""

from __future__ import annotations

import math

from backtester.sizing.base import BaseSizer, EntrySide, SizingDecision


class VolatilitySizer(BaseSizer):
    """Use the larger of stop distance and volatility-derived distance."""

    method = "volatility"

    def __init__(
        self,
        risk_percent: float,
        *,
        volatility_multiplier: float = 1.0,
        volatility_key: str = "volatility",
    ) -> None:
        if risk_percent <= 0 or risk_percent > 1:
            raise ValueError("risk_percent must be between 0 and 1")
        if volatility_multiplier <= 0:
            raise ValueError("volatility_multiplier must be positive")
        if not volatility_key:
            raise ValueError("volatility_key must be a non-empty string")
        self.risk_percent = float(risk_percent)
        self.volatility_multiplier = float(volatility_multiplier)
        self.volatility_key = str(volatility_key)

    def size_for_entry(
        self,
        *,
        equity: float,
        side: EntrySide,
        entry_price: float,
        stop_price: float | None,
        instrument: str,
        metadata: dict[str, object] | None = None,
    ) -> SizingDecision:
        spec = self._resolve_spec(instrument)
        normalized_metadata = self._normalize_metadata(metadata)
        invalid = self._validate_common_inputs(
            side=side,
            equity=equity,
            entry_price=entry_price,
            stop_price=stop_price,
        )
        details = self._default_details(spec=spec, metadata=normalized_metadata)
        details["risk_percent"] = self.risk_percent
        details["volatility_multiplier"] = self.volatility_multiplier
        details["volatility_key"] = self.volatility_key
        if invalid is not None:
            return self._reject(
                method=self.method,
                instrument=instrument,
                side=side,
                equity=equity,
                entry_price=entry_price,
                stop_price=stop_price,
                stop_distance=None,
                raw_size=0.0,
                spec=spec,
                reason=invalid,
                details=details,
            )

        if self.volatility_key not in normalized_metadata:
            return self._reject(
                method=self.method,
                instrument=instrument,
                side=side,
                equity=equity,
                entry_price=entry_price,
                stop_price=stop_price,
                stop_distance=None,
                raw_size=0.0,
                spec=spec,
                reason="missing_volatility",
                details=details,
            )

        volatility = float(normalized_metadata[self.volatility_key])
        details["volatility"] = volatility
        if not math.isfinite(volatility) or volatility <= 0:
            return self._reject(
                method=self.method,
                instrument=instrument,
                side=side,
                equity=equity,
                entry_price=entry_price,
                stop_price=stop_price,
                stop_distance=None,
                raw_size=0.0,
                spec=spec,
                reason="invalid_volatility",
                details=details,
            )

        stop_distance: float | None = None
        if stop_price is not None:
            stop_distance, stop_reason = self._resolve_stop_distance(
                side=side,
                entry_price=entry_price,
                stop_price=stop_price,
            )
            if stop_reason is not None:
                return self._reject(
                    method=self.method,
                    instrument=instrument,
                    side=side,
                    equity=equity,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    stop_distance=stop_distance,
                    raw_size=0.0,
                    spec=spec,
                    reason=stop_reason,
                    details=details,
                )

        volatility_distance = volatility * self.volatility_multiplier
        effective_distance = (
            max(stop_distance, volatility_distance)
            if stop_distance is not None
            else volatility_distance
        )
        per_unit_risk = self._per_unit_risk(effective_distance, spec)
        risk_amount = equity * self.risk_percent
        details["stop_distance_input"] = stop_distance
        details["volatility_distance"] = volatility_distance
        details["effective_distance"] = effective_distance
        details["per_unit_risk"] = per_unit_risk
        details["risk_amount"] = risk_amount
        raw_size = risk_amount / per_unit_risk
        return self._accept_or_reject_size(
            method=self.method,
            instrument=instrument,
            side=side,
            equity=equity,
            entry_price=entry_price,
            stop_price=stop_price,
            stop_distance=effective_distance,
            raw_size=raw_size,
            spec=spec,
            details=details,
        )
