from __future__ import annotations

import numpy as np
import pandas as pd

from backtester.indicators import (
    adx,
    atr,
    bollinger_bands,
    ema,
    macd,
    rolling_linreg_slope,
    rolling_zscore,
    rsi,
    sma,
)
from backtester.indicators.research import savgol_smooth
from backtester.strategy import (
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


def test_talib_wrappers_preserve_index_length_and_warmup():
    index = pd.date_range("2024-01-01", periods=8, freq="h", tz="UTC")
    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], index=index)
    high = close + 0.5
    low = close - 0.5

    sma_result = sma(close, period=3)
    ema_result = ema(close, period=3)
    rsi_result = rsi(close, period=3)
    macd_result = macd(close, fast=2, slow=3, signal=2)
    atr_result = atr(high, low, close, period=2)
    bands_result = bollinger_bands(close, period=3)
    adx_result = adx(high, low, close, period=2)

    assert sma_result.index.equals(index)
    assert ema_result.index.equals(index)
    assert rsi_result.index.equals(index)
    assert atr_result.index.equals(index)
    assert adx_result.index.equals(index)
    assert macd_result.index.equals(index)
    assert bands_result.index.equals(index)
    assert len(sma_result) == len(close)
    assert sma_result.iloc[:2].isna().all()
    assert ema_result.iloc[:2].isna().all()
    assert list(macd_result.columns) == ["MACD", "Signal", "Histogram"]
    assert list(bands_result.columns) == ["UpperBand", "MiddleBand", "LowerBand"]
    assert np.isnan(atr_result.iloc[0])
    assert np.isnan(adx_result.iloc[0])


def test_talib_wrappers_accept_numpy_arrays():
    values = np.asarray([1.0, 2.0, 3.0, 4.0, 5.0], dtype=float)

    result = ema(values, period=2)

    assert isinstance(result, np.ndarray)
    assert result.shape == values.shape


def test_scipy_wrappers_preserve_shapes_and_nan_edges():
    index = pd.date_range("2024-01-01", periods=7, freq="h", tz="UTC")
    values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0], index=index)

    savgol_result = savgol_smooth(values, window_length=5, polyorder=2)
    slope_result = rolling_linreg_slope(values, window=3)
    zscore_result = rolling_zscore(values, window=3)

    assert savgol_result.index.equals(index)
    assert slope_result.index.equals(index)
    assert zscore_result.index.equals(index)
    assert savgol_result.iloc[:2].isna().all()
    assert savgol_result.iloc[-2:].isna().all()
    assert slope_result.iloc[:2].isna().all()
    assert zscore_result.iloc[:2].isna().all()
    assert slope_result.iloc[-1] > 0.0
    assert np.isfinite(zscore_result.iloc[-1])


def test_signal_helpers_are_pure_current_prior_checks():
    assert crossed_above(1.0, 3.0, 2.0, 2.5) is True
    assert crossed_below(3.0, 1.0, 2.0, 1.5) is True
    assert is_bullish_candle(100.0, 101.0) is True
    assert is_bearish_candle(101.0, 100.0) is True
    assert candle_closes_above_level(101.0, 100.5) is True
    assert candle_closes_below_level(99.0, 99.5) is True
    assert structure_bias(np.nan, 1.0) == 1
    assert structure_bias(-1.0, np.nan) == -1
    assert is_discount(1) is True
    assert is_premium(-1) is True
    assert is_equilibrium(0) is True
    assert smc_bullish_confluence(1, 1, order_block_signal=1, liquidity_swept=True) is True
    assert smc_bearish_confluence(-1, -1, order_block_signal=-1, liquidity_swept=True) is True
    assert smc_bullish_confluence(1, -1) is False
