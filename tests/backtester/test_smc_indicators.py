from __future__ import annotations

import pandas as pd
import pytest

from backtester.indicators import bos_choch, liquidity, ob, premium_discount, swing_highs_lows


def _structure_fixture() -> pd.DataFrame:
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


def _order_block_fixture() -> pd.DataFrame:
    rows = [
        (100, 101, 99, 100, 100),
        (100, 104, 100, 103, 110),
        (103, 102, 98, 99, 120),
        (99, 101, 97, 100, 130),
        (100, 106, 100, 105, 140),
        (105, 107, 104, 106, 150),
    ]
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def _liquidity_fixture() -> pd.DataFrame:
    rows = [
        (100, 101.00, 99.0, 100, 100),
        (100, 104.00, 99.5, 103, 110),
        (103, 101.50, 98.0, 99, 120),
        (99, 104.05, 98.5, 103, 130),
        (103, 102.00, 97.5, 99, 140),
        (99, 105.50, 98.8, 105, 150),
        (105, 103.00, 98.0, 100, 160),
    ]
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def test_swing_highs_lows_returns_expected_levels_on_fixed_fixture():
    frame = _structure_fixture()

    result = swing_highs_lows(frame, swing_length=1)

    assert result["HighLow"].tolist() == [-1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0]
    assert result["Level"].tolist() == [99.0, 103.0, 98.0, 104.0, 97.0, 105.0, 96.0, 106.0]


def test_bos_choch_requires_future_break_confirmation():
    frame = _structure_fixture()

    early_swings = swing_highs_lows(frame.iloc[:5], swing_length=1)
    early_structure = bos_choch(frame.iloc[:5], early_swings, close_break=True)
    full_swings = swing_highs_lows(frame, swing_length=1)
    full_structure = bos_choch(frame, full_swings, close_break=True)

    assert early_structure["CHOCH"].isna().all()
    assert full_structure.loc[1, "CHOCH"] == 1.0
    assert full_structure.loc[1, "BrokenIndex"] == 5.0
    assert full_structure.loc[2, "CHOCH"] == -1.0
    assert full_structure.loc[2, "BrokenIndex"] == 6.0
    assert full_structure.loc[3, "CHOCH"] == 1.0
    assert full_structure.loc[3, "BrokenIndex"] == 7.0
    assert full_structure["BOS"].isna().all()


def test_order_block_detects_bullish_zone_on_break_fixture():
    frame = _order_block_fixture()
    swings = swing_highs_lows(frame, swing_length=1)

    result = ob(frame, swings)

    assert result.loc[3, "OB"] == 1.0
    assert result.loc[3, "Top"] == 101.0
    assert result.loc[3, "Bottom"] == 97.0
    assert result.loc[3, "OBVolume"] == 390.0
    assert result.loc[3, "Percentage"] == pytest.approx(44.4444444444)


def test_liquidity_detects_cluster_and_sweep():
    frame = _liquidity_fixture()
    swings = swing_highs_lows(frame, swing_length=1)

    result = liquidity(frame, swings, range_percent=0.02)

    assert result.loc[1, "Liquidity"] == 1.0
    assert result.loc[1, "Level"] == pytest.approx(104.025)
    assert result.loc[1, "End"] == 3.0
    assert result.loc[1, "Swept"] == 5.0


def test_premium_discount_uses_latest_alternating_swing_range():
    frame = _structure_fixture()
    swings = swing_highs_lows(frame, swing_length=1)

    result = premium_discount(frame, swings)

    assert pd.isna(result.loc[0, "RangeHigh"])
    assert result.loc[0, "Zone"] == 0
    assert result.loc[4, "RangeHigh"] == 104.0
    assert result.loc[4, "RangeLow"] == 97.0
    assert result.loc[4, "Equilibrium"] == 100.5
    assert result.loc[4, "Zone"] == 1
    assert result.loc[5, "RangeHigh"] == 105.0
    assert result.loc[5, "RangeLow"] == 97.0
    assert result.loc[5, "Equilibrium"] == 101.0
    assert result.loc[5, "Zone"] == -1
