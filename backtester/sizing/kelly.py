"""Kelly-criterion position sizing."""

from __future__ import annotations

from backtester.sizing.base import BaseSizer, EntrySide, SizingDecision


class KellySizer(BaseSizer):
    """Cap fractional Kelly risk and size through the shared risk path."""

    method = "kelly"

    def __init__(
        self,
        *,
        win_probability: float,
        payoff_ratio: float,
        kelly_fraction: float = 0.25,
        max_risk_percent: float = 0.02,
    ) -> None:
        if win_probability <= 0 or win_probability >= 1:
            raise ValueError("win_probability must be between 0 and 1")
        if payoff_ratio <= 0:
            raise ValueError("payoff_ratio must be positive")
        if kelly_fraction <= 0 or kelly_fraction > 1:
            raise ValueError("kelly_fraction must be between 0 and 1")
        if max_risk_percent <= 0 or max_risk_percent > 1:
            raise ValueError("max_risk_percent must be between 0 and 1")
        self.win_probability = float(win_probability)
        self.payoff_ratio = float(payoff_ratio)
        self.kelly_fraction = float(kelly_fraction)
        self.max_risk_percent = float(max_risk_percent)

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
        raw_kelly = self.win_probability - ((1.0 - self.win_probability) / self.payoff_ratio)
        effective_kelly = raw_kelly * self.kelly_fraction
        effective_risk_percent = min(effective_kelly, self.max_risk_percent)
        details = self._default_details(spec=spec, metadata=normalized_metadata)
        details.update(
            {
                "win_probability": self.win_probability,
                "payoff_ratio": self.payoff_ratio,
                "kelly_fraction": self.kelly_fraction,
                "raw_kelly": raw_kelly,
                "effective_kelly": effective_kelly,
                "effective_risk_percent": effective_risk_percent,
                "max_risk_percent": self.max_risk_percent,
            }
        )
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

        if raw_kelly <= 0 or effective_risk_percent <= 0:
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
                reason="non_positive_kelly_edge",
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

        risk_amount = equity * effective_risk_percent
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
