"""Indicator wrappers and Smart Money Concepts helpers.

TA-Lib and scipy wrappers are imported eagerly. SMC-backed helpers are
resolved lazily so non-SMC flows do not import ``smartmoneyconcepts``
until they are explicitly used.
"""

from __future__ import annotations

from importlib import import_module

from .scipy_indicators import rolling_linreg_slope, rolling_zscore, savgol_smooth
from .talib_indicators import adx, atr, bollinger_bands, ema, macd, rsi, sma

_LAZY_EXPORTS = {
    "ICTFibEngine": (".smc", "ICTFibEngine"),
    "bos_choch": (".smc", "bos_choch"),
    "liquidity": (".smc", "liquidity"),
    "ob": (".smc", "ob"),
    "premium_discount": (".smc", "premium_discount"),
    "previous_high_low": (".smc", "previous_high_low"),
    "retracements": (".smc", "retracements"),
    "sessions": (".smc", "sessions"),
    "swing_highs_lows": (".smc", "swing_highs_lows"),
}

__all__ = [
    "ICTFibEngine",
    "adx",
    "atr",
    "bollinger_bands",
    "bos_choch",
    "ema",

    "liquidity",
    "macd",
    "ob",
    "premium_discount",
    "previous_high_low",
    "retracements",
    "rolling_linreg_slope",
    "rolling_zscore",
    "rsi",
    "savgol_smooth",
    "sessions",
    "sma",
    "swing_highs_lows",
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
