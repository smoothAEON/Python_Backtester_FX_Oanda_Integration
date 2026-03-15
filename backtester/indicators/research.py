"""Research-only indicator helpers that are outside the live-safe runtime contract."""

from __future__ import annotations

from importlib import import_module

from .scipy_indicators import savgol_smooth

_LAZY_EXPORTS = {
    "ICTFibEngine": (".smc", "ICTFibEngine"),
    "bos_choch": (".smc", "bos_choch"),
    "liquidity": (".smc", "liquidity"),
    "ob": (".smc", "ob"),
    "premium_discount": (".smc", "premium_discount"),
    "retracements": (".smc", "retracements"),
    "swing_highs_lows": (".smc", "swing_highs_lows"),
}

__all__ = [
    "ICTFibEngine",
    "bos_choch",
    "liquidity",
    "ob",
    "premium_discount",
    "retracements",
    "savgol_smooth",
    "swing_highs_lows",
]


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    value = getattr(import_module(module_name, __package__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
