"""Tests for SMC indicators backed by the ``smartmoneyconcepts`` package.

swing_highs_lows, bos_choch, ob, and liquidity now delegate to the
upstream package.  premium_discount is kept as a local helper.  These
tests verify that the wrappers return correctly-shaped DataFrames with
the expected column schemas.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtester.indicators.research import (
    bos_choch,
    liquidity,
    ob,
    premium_discount,
    retracements,
    swing_highs_lows,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _structure_fixture() -> pd.DataFrame:
    """8-bar zigzag suitable for swing detection with swing_length=1."""
    rows = [
        (100, 101, 99, 100, 100),
        (100, 103, 99, 102, 110),
        (102, 101, 98, 99, 120),
        (99, 104, 99, 103, 130),
        (103, 102, 97, 98, 140),
        (98, 105, 98, 104, 150),
        (104, 103, 96, 97, 160),
        (97, 106, 97, 105, 170),
    ]
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def _large_fixture() -> pd.DataFrame:
    """100-bar fixture with enough data for upstream default swing_length=50."""
    import numpy as np

    np.random.seed(42)
    close = np.cumsum(np.random.randn(100)) + 100
    high = close + np.abs(np.random.randn(100))
    low = close - np.abs(np.random.randn(100))
    opn = close + np.random.randn(100) * 0.5
    volume = np.random.randint(100, 500, 100).astype(float)
    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close, "volume": volume}
    )


# ---------------------------------------------------------------------------
# swing_highs_lows (upstream)
# ---------------------------------------------------------------------------


def test_swing_highs_lows_returns_correct_columns():
    frame = _structure_fixture()
    result = swing_highs_lows(frame, swing_length=1)

    assert isinstance(result, pd.DataFrame)
    assert "HighLow" in result.columns
    assert "Level" in result.columns
    assert len(result) == len(frame)


def test_swing_highs_lows_detects_swings():
    frame = _structure_fixture()
    result = swing_highs_lows(frame, swing_length=1)

    non_nan = result["HighLow"].dropna()
    assert len(non_nan) > 0, "Should detect at least one swing"
    assert set(non_nan.unique()).issubset({1.0, -1.0})


# ---------------------------------------------------------------------------
# bos_choch (upstream)
# ---------------------------------------------------------------------------


def test_bos_choch_returns_correct_columns():
    frame = _structure_fixture()
    swings = swing_highs_lows(frame, swing_length=1)
    result = bos_choch(frame, swings, close_break=True)

    assert isinstance(result, pd.DataFrame)
    assert "BOS" in result.columns
    assert "CHOCH" in result.columns
    assert "Level" in result.columns
    assert "BrokenIndex" in result.columns
    assert len(result) == len(frame)


# ---------------------------------------------------------------------------
# ob (upstream)
# ---------------------------------------------------------------------------


def test_ob_returns_correct_columns():
    frame = _structure_fixture()
    swings = swing_highs_lows(frame, swing_length=1)
    result = ob(frame, swings)

    assert isinstance(result, pd.DataFrame)
    assert "OB" in result.columns
    assert "Top" in result.columns
    assert "Bottom" in result.columns
    assert "OBVolume" in result.columns
    assert "Percentage" in result.columns
    assert len(result) == len(frame)


# ---------------------------------------------------------------------------
# liquidity (upstream)
# ---------------------------------------------------------------------------


def test_liquidity_returns_correct_columns():
    frame = _structure_fixture()
    swings = swing_highs_lows(frame, swing_length=1)
    result = liquidity(frame, swings, range_percent=0.02)

    assert isinstance(result, pd.DataFrame)
    assert "Liquidity" in result.columns
    assert "Level" in result.columns
    assert "End" in result.columns
    assert "Swept" in result.columns
    assert len(result) == len(frame)




# ---------------------------------------------------------------------------
# retracements (upstream, new)
# ---------------------------------------------------------------------------


def test_retracements_returns_correct_columns():
    frame = _structure_fixture()
    swings = swing_highs_lows(frame, swing_length=1)
    result = retracements(frame, swings)

    assert isinstance(result, pd.DataFrame)
    assert "Direction" in result.columns
    assert "CurrentRetracement%" in result.columns
    assert "DeepestRetracement%" in result.columns
    assert len(result) == len(frame)


# ---------------------------------------------------------------------------
# premium_discount (local helper, kept)
# ---------------------------------------------------------------------------


def test_premium_discount_uses_latest_alternating_swing_range():
    frame = _structure_fixture()
    swings = swing_highs_lows(frame, swing_length=1)
    result = premium_discount(frame, swings)

    assert isinstance(result, pd.DataFrame)
    assert "RangeHigh" in result.columns
    assert "RangeLow" in result.columns
    assert "Equilibrium" in result.columns
    assert "Zone" in result.columns
    assert len(result) == len(frame)

    # The zone should classify close vs midpoint
    zone_values = set(result["Zone"].unique())
    assert zone_values.issubset({-1, 0, 1})


# ---------------------------------------------------------------------------
# Large fixture tests (upstream default swing_length)
# ---------------------------------------------------------------------------


def test_swing_highs_lows_works_with_default_swing_length():
    frame = _large_fixture()
    result = swing_highs_lows(frame)

    assert isinstance(result, pd.DataFrame)
    assert len(result) == len(frame)


def test_bos_choch_works_with_large_fixture():
    frame = _large_fixture()
    swings = swing_highs_lows(frame, swing_length=5)
    result = bos_choch(frame, swings)

    assert isinstance(result, pd.DataFrame)
    assert len(result) == len(frame)
