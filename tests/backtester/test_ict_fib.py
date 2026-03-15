from __future__ import annotations

import pandas as pd
import pytest

from backtester.indicators.research import ICTFibEngine


def _make_frame(
    highs: list[float],
    lows: list[float],
    closes: list[float] | None = None,
) -> pd.DataFrame:
    if closes is None:
        closes = [(high + low) / 2.0 for high, low in zip(highs, lows, strict=True)]

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


def test_ict_fib_requires_explicit_swing_length():
    with pytest.raises(ValueError, match="swing_length must be provided explicitly"):
        ICTFibEngine()


def test_ict_fib_rejects_legacy_pivot_params():
    with pytest.raises(
        TypeError,
        match="swing_length; left_bars/right_bars are no longer supported",
    ):
        ICTFibEngine(left_bars=1, right_bars=1)


def test_ict_fib_uses_smc_swing_levels_for_wick_based_anchors():
    frame = _make_frame(
        [10.0, 20.0, 15.0, 14.0],
        [5.0, 6.0, 7.0, 8.0],
        closes=[7.5, 13.0, 11.0, 11.0],
    )
    engine = ICTFibEngine(swing_length=1)

    fib = engine.update(frame)

    assert fib is not None
    assert fib["direction"] == "up"
    assert fib["start_idx"] == 0
    assert fib["end_idx"] == 1
    assert fib["start_price"] == 5.0
    assert fib["end_price"] == 20.0
    assert engine.confirmed_pivots == (
        {"index": 0, "kind": "low", "price": 5.0},
        {"index": 1, "kind": "high", "price": 20.0},
    )


def test_ict_fib_ignores_a_swing_on_the_current_final_bar_until_next_bar():
    frame = _make_frame(
        [10.0, 20.0, 15.0, 14.0, 16.0],
        [5.0, 6.0, 7.0, 4.0, 8.0],
    )
    engine = ICTFibEngine(swing_length=1)

    early = engine.update(frame.iloc[:4])

    assert early is not None
    assert early["direction"] == "up"
    assert engine.confirmed_pivots == (
        {"index": 0, "kind": "low", "price": 5.0},
        {"index": 1, "kind": "high", "price": 20.0},
    )

    confirmed = engine.update(frame)

    assert confirmed is not None
    assert confirmed["direction"] == "down"
    assert confirmed["start_idx"] == 1
    assert confirmed["end_idx"] == 3
    assert engine.confirmed_pivots == (
        {"index": 0, "kind": "low", "price": 5.0},
        {"index": 1, "kind": "high", "price": 20.0},
        {"index": 3, "kind": "low", "price": 4.0},
    )


def test_ict_fib_keeps_existing_fib_frozen_while_a_higher_same_side_swing_replaces_the_anchor():
    frame = _make_frame(
        [10.0, 20.0, 15.0, 22.0, 18.0, 17.0, 21.0],
        [9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 6.0],
    )
    engine = ICTFibEngine(swing_length=1)

    first_fib = engine.update(frame.iloc[:4])

    assert first_fib is not None
    assert first_fib["direction"] == "up"
    assert first_fib["start_idx"] == 0
    assert first_fib["end_idx"] == 1

    frozen_after_higher_high = engine.update(frame.iloc[:6])

    assert frozen_after_higher_high == first_fib
    assert engine.confirmed_pivots == (
        {"index": 0, "kind": "low", "price": 9.0},
        {"index": 3, "kind": "high", "price": 22.0},
    )
    assert engine.last_fib_signature == ((0, -1, 9.0), (1, 1, 20.0))

    bearish_fib = engine.update(frame)

    assert bearish_fib is not None
    assert bearish_fib["direction"] == "down"
    assert bearish_fib["start_idx"] == 3
    assert bearish_fib["end_idx"] == 5
    assert bearish_fib["start_price"] == 22.0
    assert bearish_fib["end_price"] == 4.0


def test_ict_fib_does_not_regenerate_the_same_pair_on_repeated_updates():
    frame = _make_frame([10.0, 20.0, 15.0, 14.0], [5.0, 6.0, 7.0, 8.0])
    extended = _make_frame([10.0, 20.0, 15.0, 14.0, 13.0], [5.0, 6.0, 7.0, 8.0, 9.0])
    engine = ICTFibEngine(swing_length=1)

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
        {"index": 0, "kind": "low", "price": 5.0},
        {"index": 1, "kind": "high", "price": 20.0},
    )


def test_ict_fib_bullish_ote_levels_match_expected_prices():
    frame = _make_frame([10.0, 20.0, 15.0, 14.0], [5.0, 6.0, 7.0, 8.0])
    engine = ICTFibEngine(swing_length=1)

    fib = engine.update(frame)

    assert fib is not None
    assert fib["levels"]["0.0"] == 5.0
    assert fib["levels"]["0.5"] == 12.5
    assert fib["levels"]["0.62"] == pytest.approx(10.7)
    assert fib["levels"]["0.705"] == pytest.approx(9.425)
    assert fib["levels"]["0.79"] == pytest.approx(8.15)
    assert fib["levels"]["1.0"] == 20.0
    assert fib["ote_zone"] == {
        "upper": pytest.approx(10.7),
        "mid": pytest.approx(9.425),
        "lower": pytest.approx(8.15),
    }


def test_ict_fib_bearish_ote_levels_match_expected_prices():
    frame = _make_frame(
        [10.0, 20.0, 15.0, 14.0, 16.0],
        [5.0, 6.0, 7.0, 4.0, 8.0],
    )
    engine = ICTFibEngine(swing_length=1)

    fib = engine.update(frame)

    assert fib is not None
    assert fib["direction"] == "down"
    assert fib["levels"]["0.0"] == 20.0
    assert fib["levels"]["0.5"] == 12.0
    assert fib["levels"]["0.62"] == pytest.approx(13.92)
    assert fib["levels"]["0.705"] == pytest.approx(15.28)
    assert fib["levels"]["0.79"] == pytest.approx(16.64)
    assert fib["levels"]["1.0"] == 4.0
    assert fib["ote_zone"] == {
        "upper": pytest.approx(16.64),
        "mid": pytest.approx(15.28),
        "lower": pytest.approx(13.92),
    }


def test_ict_fib_optional_atr_filter_skips_small_swings_without_retrying_same_pair():
    frame = _make_frame(
        [10.1, 10.2, 10.1, 10.15],
        [10.0, 10.0, 10.0, 10.05],
        closes=[100.0, 0.0, 100.0, 100.0],
    )
    engine = ICTFibEngine(
        swing_length=1,
        atr_period=1,
        atr_multiplier=0.5,
    )

    skipped = engine.update(frame.iloc[:3])
    handled_signature = engine.last_handled_pair_signature
    repeated = engine.update(frame.iloc[:3])
    extended_result = engine.update(frame)

    assert skipped is None
    assert repeated is None
    assert extended_result is None
    assert handled_signature is not None
    assert engine.last_fib_signature is None
    assert engine.last_handled_pair_signature == ((1, 1, 10.2), (2, -1, 10.0))
