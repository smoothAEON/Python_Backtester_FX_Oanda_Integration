"""TA-Lib indicator wrappers with stable pandas handling."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import talib


def sma(values: Any, period: int) -> pd.Series | np.ndarray:
    _validate_period(period)
    array, template = _coerce_1d(values)
    return _wrap_series(talib.SMA(array, timeperiod=period), template, "SMA")


def ema(values: Any, period: int) -> pd.Series | np.ndarray:
    _validate_period(period)
    array, template = _coerce_1d(values)
    return _wrap_series(talib.EMA(array, timeperiod=period), template, "EMA")


def rsi(values: Any, period: int) -> pd.Series | np.ndarray:
    _validate_period(period)
    array, template = _coerce_1d(values)
    return _wrap_series(talib.RSI(array, timeperiod=period), template, "RSI")


def macd(values: Any, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    _validate_period(fast)
    _validate_period(slow)
    _validate_period(signal)
    array, template = _coerce_1d(values)
    macd_line, signal_line, histogram = talib.MACD(
        array,
        fastperiod=fast,
        slowperiod=slow,
        signalperiod=signal,
    )
    index = template.index if template is not None else pd.RangeIndex(len(array))
    return pd.DataFrame(
        {
            "MACD": macd_line,
            "Signal": signal_line,
            "Histogram": histogram,
        },
        index=index,
    )


def atr(high: Any, low: Any, close: Any, period: int) -> pd.Series | np.ndarray:
    _validate_period(period)
    high_array, template = _coerce_1d(high)
    low_array, _ = _coerce_1d(low)
    close_array, _ = _coerce_1d(close)
    return _wrap_series(
        talib.ATR(high_array, low_array, close_array, timeperiod=period),
        template,
        "ATR",
    )


def bollinger_bands(
    values: Any,
    period: int = 20,
    nbdevup: float = 2.0,
    nbdevdn: float = 2.0,
    matype: int = 0,
) -> pd.DataFrame:
    _validate_period(period)
    array, template = _coerce_1d(values)
    upper, middle, lower = talib.BBANDS(
        array,
        timeperiod=period,
        nbdevup=nbdevup,
        nbdevdn=nbdevdn,
        matype=matype,
    )
    index = template.index if template is not None else pd.RangeIndex(len(array))
    return pd.DataFrame(
        {
            "UpperBand": upper,
            "MiddleBand": middle,
            "LowerBand": lower,
        },
        index=index,
    )


def adx(high: Any, low: Any, close: Any, period: int) -> pd.Series | np.ndarray:
    _validate_period(period)
    high_array, template = _coerce_1d(high)
    low_array, _ = _coerce_1d(low)
    close_array, _ = _coerce_1d(close)
    return _wrap_series(
        talib.ADX(high_array, low_array, close_array, timeperiod=period),
        template,
        "ADX",
    )


def _coerce_1d(values: Any) -> tuple[np.ndarray, pd.Series | None]:
    template = values if isinstance(values, pd.Series) else None
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError("Indicator inputs must be one-dimensional")
    return array, template


def _validate_period(period: int) -> None:
    if period <= 0:
        raise ValueError("period must be positive")


def _wrap_series(
    values: np.ndarray,
    template: pd.Series | None,
    name: str,
) -> pd.Series | np.ndarray:
    if template is None:
        return values
    return pd.Series(values, index=template.index, name=name)
