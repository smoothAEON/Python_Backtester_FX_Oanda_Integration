from __future__ import annotations

import pandas as pd
import pytest

from backtester.indicators import ICTFibEngine


def _make_frame(
    closes: list[float],
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> pd.DataFrame:
    if highs is None:
        highs = [close + 0.5 for close in closes]
    if lows is None:
        lows = [close - 0.5 for close in closes]

    rows: list[dict[str, float]] = []
    previous_close = float(closes[0])
    for index, close_price in enumerate(closes):
        rows.append(
            {
                "open": previous_close if index > 0 else float(close_price),
                "high": float(highs[index]),
                "low": float(lows[index]),
                "close": float(close_price),
            }
        )
        previous_close = float(close_price)
    return pd.DataFrame(rows)


def test_ict_fib_uses_close_only_pivots_and_close_only_anchors():
    frame = _make_frame(
        [9.0, 8.0, 12.0, 11.0, 7.0],
        highs=[9.5, 40.0, 12.5, 50.0, 7.5],
        lows=[8.5, 1.0, 11.5, 10.5, 0.5],
    )
    engine = ICTFibEngine(left_bars=1, right_bars=1)

    fib = engine.update(frame)

    assert fib is not None
    assert fib["direction"] == "up"
    assert fib["start_idx"] == 1
    assert fib["end_idx"] == 2
    assert fib["start_price"] == 8.0
    assert fib["end_price"] == 12.0
    assert engine.confirmed_pivots == (
        {"index": 1, "kind": "low", "price": 8.0},
        {"index": 2, "kind": "high", "price": 12.0},
    )


def test_ict_fib_waits_for_right_bar_confirmation_before_using_a_pivot():
    frame = _make_frame([11.0, 8.0, 12.0, 10.0, 9.0])
    engine = ICTFibEngine(left_bars=1, right_bars=2)

    early = engine.update(frame.iloc[:4])

    assert early is None
    assert engine.confirmed_pivots == ({"index": 1, "kind": "low", "price": 8.0},)

    confirmed = engine.update(frame.iloc[:5])

    assert confirmed is not None
    assert confirmed["direction"] == "up"
    assert confirmed["start_idx"] == 1
    assert confirmed["end_idx"] == 2


def test_ict_fib_keeps_existing_fib_frozen_until_a_new_opposite_pivot_confirms():
    frame = _make_frame(
        [11.0, 10.0, 8.0, 12.0, 11.0, 13.0, 12.5, 12.0, 14.0, 11.0, 10.0, 12.0, 11.0]
    )
    engine = ICTFibEngine(left_bars=2, right_bars=2)

    first_fib = engine.update(frame.iloc[:8])

    assert first_fib is not None
    assert first_fib["direction"] == "up"
    assert first_fib["start_idx"] == 2
    assert first_fib["end_idx"] == 5

    frozen_after_higher_high = engine.update(frame.iloc[:11])

    assert frozen_after_higher_high == first_fib
    assert engine.confirmed_pivots == (
        {"index": 2, "kind": "low", "price": 8.0},
        {"index": 8, "kind": "high", "price": 14.0},
    )

    bearish_fib = engine.update(frame)

    assert bearish_fib is not None
    assert bearish_fib["direction"] == "down"
    assert bearish_fib["start_idx"] == 8
    assert bearish_fib["end_idx"] == 10
    assert bearish_fib["start_price"] == 14.0
    assert bearish_fib["end_price"] == 10.0


def test_ict_fib_does_not_regenerate_the_same_pair_on_repeated_updates():
    frame = _make_frame([10.0, 8.0, 12.0, 11.0])
    extended = _make_frame([10.0, 8.0, 12.0, 11.0, 10.0])
    engine = ICTFibEngine(left_bars=1, right_bars=1)

    fib = engine.update(frame)
    signature = engine.last_fib_signature

    repeated = engine.update(frame)
    still_frozen = engine.update(extended)

    assert fib is not None
    assert repeated == fib
    assert still_frozen == fib
    assert engine.last_fib_signature == signature
    assert engine.last_handled_pair_signature == signature
    assert engine.confirmed_pivots == (
        {"index": 1, "kind": "low", "price": 8.0},
        {"index": 2, "kind": "high", "price": 12.0},
    )


def test_ict_fib_bullish_ote_levels_match_expected_prices():
    frame = _make_frame([10.0, 8.0, 12.0, 11.0])
    engine = ICTFibEngine(left_bars=1, right_bars=1)

    fib = engine.update(frame)

    assert fib is not None
    assert fib["levels"]["0.0"] == 8.0
    assert fib["levels"]["0.5"] == 10.0
    assert fib["levels"]["0.62"] == pytest.approx(9.52)
    assert fib["levels"]["0.705"] == pytest.approx(9.18)
    assert fib["levels"]["0.79"] == pytest.approx(8.84)
    assert fib["levels"]["1.0"] == 12.0
    assert fib["ote_zone"] == {
        "upper": pytest.approx(9.52),
        "mid": pytest.approx(9.18),
        "lower": pytest.approx(8.84),
    }


def test_ict_fib_bearish_ote_levels_match_expected_prices():
    frame = _make_frame([10.0, 14.0, 10.0, 12.0])
    engine = ICTFibEngine(left_bars=1, right_bars=1)

    fib = engine.update(frame)

    assert fib is not None
    assert fib["direction"] == "down"
    assert fib["levels"]["0.0"] == 14.0
    assert fib["levels"]["0.5"] == 12.0
    assert fib["levels"]["0.62"] == pytest.approx(12.48)
    assert fib["levels"]["0.705"] == pytest.approx(12.82)
    assert fib["levels"]["0.79"] == pytest.approx(13.16)
    assert fib["levels"]["1.0"] == 10.0
    assert fib["ote_zone"] == {
        "upper": pytest.approx(13.16),
        "mid": pytest.approx(12.82),
        "lower": pytest.approx(12.48),
    }


def test_ict_fib_optional_atr_filter_skips_small_swings_without_retrying_same_pair():
    frame = _make_frame(
        [10.0, 9.0, 10.2, 10.0, 10.1],
        highs=[15.0, 15.0, 15.0, 15.0, 15.0],
        lows=[5.0, 5.0, 5.0, 5.0, 5.0],
    )
    extended = _make_frame(
        [10.0, 9.0, 10.2, 10.0, 10.1, 10.15],
        highs=[15.0, 15.0, 15.0, 15.0, 15.0, 15.0],
        lows=[5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
    )
    engine = ICTFibEngine(
        left_bars=1,
        right_bars=1,
        atr_period=2,
        atr_multiplier=0.5,
    )

    skipped = engine.update(frame)
    handled_signature = engine.last_handled_pair_signature
    repeated = engine.update(frame)
    extended_result = engine.update(extended)

    assert skipped is None
    assert repeated is None
    assert extended_result is None
    assert handled_signature is not None
    assert engine.last_fib_signature is None
    assert engine.last_handled_pair_signature == handled_signature
