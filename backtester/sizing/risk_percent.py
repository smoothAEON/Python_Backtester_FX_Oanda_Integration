"""Risk-percent position sizing."""

from __future__ import annotations

from backtester.sizing.base import BaseSizer, EntrySide, SizingDecision


class RiskPercentSizer(BaseSizer):
    """Size positions from a fixed fraction of current equity."""

    method = "risk_percent"

    def __init__(self, risk_percent: float) -> None:
        if risk_percent <= 0 or risk_percent > 1:
            raise ValueError("risk_percent must be between 0 and 1")
        self.risk_percent = float(risk_percent)

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

        stop_distance, stop_reason = self._resolve_stop_distance(
            side=side,
            entry_price=entry_price,
            stop_price=stop_price,
        )
        if stop_reason is not None or stop_distance is None:
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
                reason=stop_reason or "missing_stop_price",
                details=details,
            )

        risk_amount = equity * self.risk_percent
        per_unit_risk = self._per_unit_risk(stop_distance, spec)
        details["risk_amount"] = risk_amount
        details["per_unit_risk"] = per_unit_risk
        raw_size = risk_amount / per_unit_risk
        return self._accept_or_reject_size(
            method=self.method,
            instrument=instrument,
            side=side,
            equity=equity,
            entry_price=entry_price,
            stop_price=stop_price,
            stop_distance=stop_distance,
            raw_size=raw_size,
            spec=spec,
            details=details,
        )
