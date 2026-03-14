"""Scipy-powered helper indicators."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter
from scipy.stats import linregress


def savgol_smooth(
    values: Any,
    window_length: int = 5,
    polyorder: int = 2,
    *,
    mode: str = "interp",
) -> pd.Series | np.ndarray:
    if window_length <= 0 or window_length % 2 == 0:
        raise ValueError("window_length must be a positive odd integer")
    if polyorder < 0 or polyorder >= window_length:
        raise ValueError("polyorder must be non-negative and smaller than window_length")

    array, template = _coerce_1d(values)
    result = np.full(len(array), np.nan, dtype=float)
    if len(array) >= window_length and not np.isnan(array).any():
        smoothed = savgol_filter(
            array,
            window_length=window_length,
            polyorder=polyorder,
            mode=mode,
        )
        edge = window_length // 2
        result[:] = smoothed
        result[:edge] = np.nan
        result[-edge:] = np.nan
    return _wrap_output(result, template, "Savgol")


def rolling_linreg_slope(values: Any, window: int = 20) -> pd.Series | np.ndarray:
    if window < 2:
        raise ValueError("window must be at least 2")

    array, template = _coerce_1d(values)
    result = np.full(len(array), np.nan, dtype=float)
    x_axis = np.arange(window, dtype=float)
    for index in range(window - 1, len(array)):
        segment = array[index - window + 1 : index + 1]
        if np.isnan(segment).any():
            continue
        result[index] = linregress(x_axis, segment).slope
    return _wrap_output(result, template, "RollingSlope")


def rolling_zscore(values: Any, window: int = 20) -> pd.Series | np.ndarray:
    if window < 2:
        raise ValueError("window must be at least 2")

    series = values if isinstance(values, pd.Series) else pd.Series(np.asarray(values, dtype=float))
    rolling_mean = series.rolling(window=window, min_periods=window).mean()
    rolling_std = series.rolling(window=window, min_periods=window).std(ddof=0)
    result = (series - rolling_mean) / rolling_std.replace(0.0, np.nan)
    if isinstance(values, pd.Series):
        result.name = "RollingZScore"
        return result
    return result.to_numpy(dtype=float)


def _coerce_1d(values: Any) -> tuple[np.ndarray, pd.Series | None]:
    template = values if isinstance(values, pd.Series) else None
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError("Indicator inputs must be one-dimensional")
    return array, template


def _wrap_output(
    values: np.ndarray,
    template: pd.Series | None,
    name: str,
) -> pd.Series | np.ndarray:
    if template is None:
        return values
    return pd.Series(values, index=template.index, name=name)
