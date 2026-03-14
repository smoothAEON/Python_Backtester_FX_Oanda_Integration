"""Fixed-size position sizing."""

from __future__ import annotations

from backtester.sizing.base import BaseSizer, EntrySide, SizingDecision


class FixedLotSizer(BaseSizer):
    """Always request the same configured number of units."""

    method = "fixed_lot"

    def __init__(self, units: float) -> None:
        if units <= 0:
            raise ValueError("units must be positive")
        self.units = float(units)

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
        details["configured_units"] = self.units
        if invalid is not None:
            return self._reject(
                method=self.method,
                instrument=instrument,
                side=side,
                equity=equity,
                entry_price=entry_price,
                stop_price=stop_price,
                stop_distance=None,
                raw_size=self.units,
                spec=spec,
                reason=invalid,
                details=details,
            )

        return self._accept_or_reject_size(
            method=self.method,
            instrument=instrument,
            side=side,
            equity=equity,
            entry_price=entry_price,
            stop_price=stop_price,
            stop_distance=abs(entry_price - stop_price) if stop_price is not None else None,
            raw_size=self.units,
            spec=spec,
            details=details,
        )
