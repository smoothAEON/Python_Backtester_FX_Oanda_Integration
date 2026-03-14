"""Pure reusable signal helpers."""

from __future__ import annotations

from math import isnan


def crossed_above(
    previous_left: float,
    current_left: float,
    previous_right: float,
    current_right: float,
) -> bool:
    return previous_left <= previous_right and current_left > current_right


def crossed_below(
    previous_left: float,
    current_left: float,
    previous_right: float,
    current_right: float,
) -> bool:
    return previous_left >= previous_right and current_left < current_right


def is_bullish_candle(open_price: float, close_price: float) -> bool:
    return close_price > open_price


def is_bearish_candle(open_price: float, close_price: float) -> bool:
    return close_price < open_price


def candle_closes_above_level(close_price: float, level: float) -> bool:
    return close_price > level


def candle_closes_below_level(close_price: float, level: float) -> bool:
    return close_price < level


def structure_bias(bos: float | int | None, choch: float | int | None) -> int:
    for candidate in (choch, bos):
        if candidate is None:
            continue
        value = float(candidate)
        if isnan(value):
            continue
        if value > 0:
            return 1
        if value < 0:
            return -1
    return 0


def is_discount(zone: float | int) -> bool:
    return int(zone) == 1


def is_premium(zone: float | int) -> bool:
    return int(zone) == -1


def is_equilibrium(zone: float | int) -> bool:
    return int(zone) == 0


def smc_bullish_confluence(
    structure_signal: int,
    zone: int,
    *,
    order_block_signal: int | None = None,
    liquidity_swept: bool | None = None,
) -> bool:
    if structure_signal <= 0 or zone != 1:
        return False
    if order_block_signal is not None and order_block_signal <= 0:
        return False
    if liquidity_swept is not None and not liquidity_swept:
        return False
    return True


def smc_bearish_confluence(
    structure_signal: int,
    zone: int,
    *,
    order_block_signal: int | None = None,
    liquidity_swept: bool | None = None,
) -> bool:
    if structure_signal >= 0 or zone != -1:
        return False
    if order_block_signal is not None and order_block_signal >= 0:
        return False
    if liquidity_swept is not None and not liquidity_swept:
        return False
    return True
