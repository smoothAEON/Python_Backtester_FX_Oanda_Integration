"""Runtime-safe indicator wrappers and time-aware helpers.

TA-Lib and safe scipy wrappers are imported eagerly. Time-aware SMC-backed helpers are
resolved lazily so non-SMC flows do not import ``smartmoneyconcepts``
until they are explicitly used.
"""

from __future__ import annotations

from importlib import import_module

from .scipy_indicators import rolling_linreg_slope, rolling_zscore
from .talib_indicators import adx, atr, bollinger_bands, ema, macd, rsi, sma

_LAZY_EXPORTS = {
    "CausalICTFibEngine": (".smc.causal", "CausalICTFibEngine"),
    "confirmed_liquidity": (".smc.causal", "confirmed_liquidity"),
    "confirmed_order_blocks": (".smc.causal", "confirmed_order_blocks"),
    "confirmed_premium_discount": (".smc.causal", "confirmed_premium_discount"),
    "confirmed_retracements": (".smc.causal", "confirmed_retracements"),
    "confirmed_structure": (".smc.causal", "confirmed_structure"),
    "confirmed_swings": (".smc.causal", "confirmed_swings"),
    "previous_high_low": (".smc", "previous_high_low"),
    "sessions": (".smc", "sessions"),
}

__all__ = [
    "CausalICTFibEngine",
    "adx",
    "atr",
    "bollinger_bands",
    "confirmed_liquidity",
    "confirmed_order_blocks",
    "confirmed_premium_discount",
    "confirmed_retracements",
    "confirmed_structure",
    "confirmed_swings",
    "ema",
    "macd",
    "previous_high_low",
    "rolling_linreg_slope",
    "rolling_zscore",
    "rsi",
    "sessions",
    "sma",
]


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
