"""Configuration objects and shared instrument metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SameBarPolicy = Literal["worst_case_first"]


@dataclass(slots=True, frozen=True)
class InstrumentSpec:
    """Lightweight instrument metadata used by position sizers."""

    instrument: str
    pip_size: float
    contract_size: float = 1.0
    point_value: float = 1.0
    min_size: float = 1.0
    size_step: float = 1.0


_INSTRUMENT_OVERRIDES: dict[str, InstrumentSpec] = {
    "XAU_USD": InstrumentSpec(
        instrument="XAU_USD",
        pip_size=0.01,
        contract_size=1.0,
        point_value=1.0,
        min_size=1.0,
        size_step=1.0,
    )
}


def resolve_instrument_spec(instrument: str) -> InstrumentSpec:
    """Resolve per-instrument sizing metadata with conservative FX defaults."""

    normalized = instrument.strip().upper()
    if not normalized:
        raise ValueError("instrument must be a non-empty string")

    override = _INSTRUMENT_OVERRIDES.get(normalized)
    if override is not None:
        return override

    parts = normalized.split("_")
    quote = parts[-1] if len(parts) >= 2 else ""
    pip_size = 0.01 if quote == "JPY" else 0.0001
    return InstrumentSpec(
        instrument=normalized,
        pip_size=pip_size,
        contract_size=1.0,
        point_value=1.0,
        min_size=1.0,
        size_step=1.0,
    )


@dataclass(slots=True, frozen=True)
class ExecutionConfig:
    """Execution assumptions shared by the broker and result layers."""

    commission: float = 0.0
    slippage: float = 0.0
    same_bar_policy: SameBarPolicy = "worst_case_first"
    one_active_bracket_only: bool = True


@dataclass(slots=True, frozen=True)
class BacktestConfig:
    """Top-level settings for one backtest run."""

    cash: float = 10_000.0
    allow_dedupe: bool = False
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
