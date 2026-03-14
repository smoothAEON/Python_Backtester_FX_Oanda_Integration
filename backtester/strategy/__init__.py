"""Shared strategy helpers and pure signal checks."""

from .base import BaseStrategy
from .instrument_api import IndicatorRequest, PriceBar
from .signals import (
    candle_closes_above_level,
    candle_closes_below_level,
    crossed_above,
    crossed_below,
    is_bearish_candle,
    is_bullish_candle,
    is_discount,
    is_equilibrium,
    is_premium,
    smc_bearish_confluence,
    smc_bullish_confluence,
    structure_bias,
)

__all__ = [
    "BaseStrategy",
    "IndicatorRequest",
    "PriceBar",
    "candle_closes_above_level",
    "candle_closes_below_level",
    "crossed_above",
    "crossed_below",
    "is_bearish_candle",
    "is_bullish_candle",
    "is_discount",
    "is_equilibrium",
    "is_premium",
    "smc_bearish_confluence",
    "smc_bullish_confluence",
    "structure_bias",
]
