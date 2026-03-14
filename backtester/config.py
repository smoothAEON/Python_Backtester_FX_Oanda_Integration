"""Configuration objects and shared instrument metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SameBarPolicy = Literal["worst_case_first"]


@dataclass(slots=True, frozen=True)
class InstrumentSpec:
    """Lightweight instrument metadata used by position sizers and broker valuation."""

    instrument: str
    pip_size: float
    display_precision: int
    price_step: float
    contract_size: float = 1.0
    point_value: float | None = None
    min_size: float = 1.0
    size_step: float = 1.0


def _build_fx_spec(
    instrument: str,
    *,
    pip_size: float,
    display_precision: int,
    price_step: float,
) -> InstrumentSpec:
    quote = instrument.strip().upper().split("_")[-1]
    return InstrumentSpec(
        instrument=instrument,
        pip_size=pip_size,
        display_precision=display_precision,
        price_step=price_step,
        contract_size=1.0,
        point_value=1.0 if quote == "USD" else None,
        min_size=1.0,
        size_step=1.0,
    )

_CORE_FX_INSTRUMENT_SPECS: dict[str, dict[str, float | int]] = {
    "EUR_USD": {
        "pip_size": 0.0001,
        "display_precision": 5,
        "price_step": 0.00001,
    },
    "USD_JPY": {
        "pip_size": 0.01,
        "display_precision": 3,
        "price_step": 0.001,
    },
    "GBP_USD": {
        "pip_size": 0.0001,
        "display_precision": 5,
        "price_step": 0.00001,
    },
    "AUD_USD": {
        "pip_size": 0.0001,
        "display_precision": 5,
        "price_step": 0.00001,
    },
    "USD_CHF": {
        "pip_size": 0.0001,
        "display_precision": 5,
        "price_step": 0.00001,
    },
    "USD_CAD": {
        "pip_size": 0.0001,
        "display_precision": 5,
        "price_step": 0.00001,
    },
    "NZD_USD": {
        "pip_size": 0.0001,
        "display_precision": 5,
        "price_step": 0.00001,
    },
    "EUR_JPY": {
        "pip_size": 0.01,
        "display_precision": 3,
        "price_step": 0.001,
    },
    "GBP_JPY": {
        "pip_size": 0.01,
        "display_precision": 3,
        "price_step": 0.001,
    },
    "EUR_GBP": {
        "pip_size": 0.0001,
        "display_precision": 5,
        "price_step": 0.00001,
    },
    "EUR_CHF": {
        "pip_size": 0.0001,
        "display_precision": 5,
        "price_step": 0.00001,
    },
    "AUD_JPY": {
        "pip_size": 0.01,
        "display_precision": 3,
        "price_step": 0.001,
    },
    "GBP_CHF": {
        "pip_size": 0.0001,
        "display_precision": 5,
        "price_step": 0.00001,
    },
    "EUR_AUD": {
        "pip_size": 0.0001,
        "display_precision": 5,
        "price_step": 0.00001,
    },
    "EUR_CAD": {
        "pip_size": 0.0001,
        "display_precision": 5,
        "price_step": 0.00001,
    },
}

_INSTRUMENT_OVERRIDES: dict[str, InstrumentSpec] = {
    **{
        instrument: _build_fx_spec(
            instrument,
            pip_size=float(params["pip_size"]),
            display_precision=int(params["display_precision"]),
            price_step=float(params["price_step"]),
        )
        for instrument, params in _CORE_FX_INSTRUMENT_SPECS.items()
    },
    "XAU_USD": InstrumentSpec(
        instrument="XAU_USD",
        pip_size=0.01,
        display_precision=3,
        price_step=0.001,
        contract_size=1.0,
        point_value=1.0,
        min_size=0.1,
        size_step=0.1,
    ),
}


def resolve_instrument_spec(instrument: str) -> InstrumentSpec:
    """Resolve per-instrument sizing metadata with explicit core FX overrides."""

    normalized = instrument.strip().upper()
    if not normalized:
        raise ValueError("instrument must be a non-empty string")

    override = _INSTRUMENT_OVERRIDES.get(normalized)
    if override is not None:
        return override

    parts = normalized.split("_")
    quote = parts[-1] if len(parts) >= 2 else ""
    if quote == "JPY":
        pip_size = 0.01
        display_precision = 3
        price_step = 0.001
    else:
        pip_size = 0.0001
        display_precision = 5
        price_step = 0.00001
    return InstrumentSpec(
        instrument=normalized,
        pip_size=pip_size,
        display_precision=display_precision,
        price_step=price_step,
        contract_size=1.0,
        point_value=1.0 if quote == "USD" else None,
        min_size=1.0,
        size_step=1.0,
    )


@dataclass(slots=True, frozen=True)
class ExecutionConfig:
    """Execution assumptions shared by the broker and result layers."""

    commission: float = 0.0
    slippage: float = 0.0
    leverage: float = 30.0
    same_bar_policy: SameBarPolicy = "worst_case_first"
    one_active_bracket_only: bool = True


@dataclass(slots=True, frozen=True)
class BacktestConfig:
    """Top-level settings for one backtest run."""

    cash: float = 10_000.0
    allow_dedupe: bool = False
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
