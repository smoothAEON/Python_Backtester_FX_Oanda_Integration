from __future__ import annotations

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

import backtester.indicators as safe_indicators
from backtester.indicators import (
    CausalICTFibEngine,
    adx,
    atr,
    bollinger_bands,
    confirmed_liquidity,
    confirmed_order_blocks,
    confirmed_premium_discount,
    confirmed_retracements,
    confirmed_structure,
    confirmed_swings,
    ema,
    macd,
    rolling_linreg_slope,
    rolling_zscore,
    rsi,
    sma,
)
from backtester.indicators.research import (
    ICTFibEngine,
    bos_choch,
    liquidity,
    ob,
    premium_discount,
    retracements,
    savgol_smooth,
    swing_highs_lows,
)
from backtester.run_backtest import run_backtest
from backtester.strategy.safety import inspect_strategy_safety
from strategies import (
    BollingerZscoreReversionStrategy,
    EmaRsiTrendStrategy,
    HybridRegimeStrategy,
    IctOteSniperStrategy,
    MacdAtrBreakoutStrategy,
    SmcPullbackStrategy,
)
from strategies.research import (
    BollingerZscoreReversionStrategy as ResearchBollingerZscoreReversionStrategy,
)
from strategies.research import HybridRegimeStrategy as ResearchHybridRegimeStrategy
from strategies.research import IctOteSniperStrategy as ResearchIctOteSniperStrategy
from strategies.research import SmcPullbackStrategy as ResearchSmcPullbackStrategy


LIVE_SAFE_STRATEGIES = (
    BollingerZscoreReversionStrategy,
    EmaRsiTrendStrategy,
    HybridRegimeStrategy,
    IctOteSniperStrategy,
    MacdAtrBreakoutStrategy,
    SmcPullbackStrategy,
)
RESEARCH_ONLY_STRATEGIES = (
    ResearchBollingerZscoreReversionStrategy,
    ResearchSmcPullbackStrategy,
    ResearchIctOteSniperStrategy,
    ResearchHybridRegimeStrategy,
)


@pytest.mark.parametrize("strategy_class", LIVE_SAFE_STRATEGIES)
def test_live_safe_repo_strategies_pass_import_validation(strategy_class):
    report = inspect_strategy_safety(strategy_class)

    assert report.runtime_contract == "live_safe"
    assert report.forbidden_imports == ()


@pytest.mark.parametrize("strategy_class", RESEARCH_ONLY_STRATEGIES)
def test_research_only_repo_strategies_report_research_imports(strategy_class):
    report = inspect_strategy_safety(strategy_class)

    assert report.runtime_contract == "research_only"
    assert report.runtime_contract_reason is not None
    assert report.forbidden_imports


def test_safe_indicator_namespace_hides_research_only_exports():
    for name in (
        "CausalICTFibEngine",
        "confirmed_swings",
        "confirmed_structure",
        "confirmed_order_blocks",
        "confirmed_liquidity",
        "confirmed_premium_discount",
        "confirmed_retracements",
    ):
        assert name in safe_indicators.__all__
        assert getattr(safe_indicators, name) is not None

    for name in (
        "ICTFibEngine",
        "bos_choch",
        "liquidity",
        "ob",
        "premium_discount",
        "retracements",
        "savgol_smooth",
        "swing_highs_lows",
    ):
        assert name not in safe_indicators.__all__
        with pytest.raises(AttributeError):
            getattr(safe_indicators, name)

    assert savgol_smooth is not None
    assert swing_highs_lows is not None
    assert bos_choch is not None
    assert ob is not None
    assert liquidity is not None
    assert premium_discount is not None
    assert retracements is not None
    assert ICTFibEngine is not None


def _smc_fixture() -> pd.DataFrame:
    rows = [
        (100.0, 101.0, 99.0, 100.0, 100.0),
        (100.0, 103.0, 99.0, 102.0, 110.0),
        (102.0, 101.0, 98.0, 99.0, 120.0),
        (99.0, 104.0, 99.0, 103.0, 130.0),
        (103.0, 102.0, 97.0, 98.0, 140.0),
        (98.0, 105.0, 98.0, 104.0, 150.0),
        (104.0, 103.0, 96.0, 97.0, 160.0),
        (97.0, 106.0, 97.0, 105.0, 170.0),
        (105.0, 106.4, 102.0, 103.0, 180.0),
        (103.0, 106.8, 101.0, 106.4, 190.0),
        (106.4, 106.6, 98.0, 98.5, 200.0),
        (98.5, 102.0, 97.8, 101.5, 210.0),
        (101.5, 103.0, 101.2, 102.8, 220.0),
        (102.8, 104.8, 102.5, 104.5, 230.0),
        (104.5, 104.8, 97.9, 98.2, 240.0),
        (98.2, 101.6, 98.1, 101.2, 250.0),
    ]
    index = pd.date_range("2024-01-01T00:00:00Z", periods=len(rows), freq="h", tz="UTC")
    return pd.DataFrame(
        rows,
        columns=["open", "high", "low", "close", "volume"],
        index=index,
    )


def _series_fixture() -> tuple[pd.Series, pd.Series]:
    index = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC")
    base = pd.Series(np.linspace(100.0, 123.0, len(index)), index=index)
    extra_index = pd.date_range(index[-1] + pd.Timedelta(hours=1), periods=6, freq="h", tz="UTC")
    extended = pd.concat(
        [
            base,
            pd.Series(np.linspace(124.0, 129.0, len(extra_index)), index=extra_index),
        ]
    )
    return base, extended


def _ohlc_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    close, extended_close = _series_fixture()
    base = pd.DataFrame(
        {
            "high": close + 0.6,
            "low": close - 0.4,
            "close": close,
        }
    )
    extended = pd.DataFrame(
        {
            "high": extended_close + 0.6,
            "low": extended_close - 0.4,
            "close": extended_close,
        }
    )
    return base, extended


@pytest.mark.parametrize(
    ("indicator_name", "builder"),
    [
        ("sma", lambda base, _extended: sma(base, period=5)),
        ("ema", lambda base, _extended: ema(base, period=5)),
        ("rsi", lambda base, _extended: rsi(base, period=5)),
        ("rolling_linreg_slope", lambda base, _extended: rolling_linreg_slope(base, window=5)),
        ("rolling_zscore", lambda base, _extended: rolling_zscore(base, window=5)),
        ("macd", lambda base, _extended: macd(base, fast=3, slow=6, signal=3)),
        ("bollinger_bands", lambda base, _extended: bollinger_bands(base, period=5)),
    ],
)
def test_runtime_safe_series_indicators_are_prefix_stable(indicator_name, builder):
    base, extended = _series_fixture()

    base_output = builder(base, extended)
    extended_output = builder(extended, extended)

    if isinstance(base_output, pd.DataFrame):
        pdt.assert_frame_equal(
            base_output.reset_index(drop=True),
            extended_output.iloc[: len(base_output)].reset_index(drop=True),
            check_exact=False,
            atol=1e-12,
            rtol=1e-12,
            obj=indicator_name,
        )
    else:
        pdt.assert_series_equal(
            base_output.reset_index(drop=True),
            extended_output.iloc[: len(base_output)].reset_index(drop=True),
            check_exact=False,
            atol=1e-12,
            rtol=1e-12,
            obj=indicator_name,
        )


@pytest.mark.parametrize(
    ("indicator_name", "builder"),
    [
        ("atr", lambda base, _extended: atr(base["high"], base["low"], base["close"], period=5)),
        ("adx", lambda base, _extended: adx(base["high"], base["low"], base["close"], period=5)),
    ],
)
def test_runtime_safe_ohlc_indicators_are_prefix_stable(indicator_name, builder):
    base, extended = _ohlc_fixture()

    base_output = builder(base, extended)
    extended_output = builder(extended, extended)

    pdt.assert_series_equal(
        base_output.reset_index(drop=True),
        extended_output.iloc[: len(base_output)].reset_index(drop=True),
        check_exact=False,
        atol=1e-12,
        rtol=1e-12,
        obj=indicator_name,
    )


def _frame_from_candles(
    make_oanda_frame,
    candles: list[dict[str, float]],
    *,
    start: str = "2024-01-01T00:00:00Z",
) -> pd.DataFrame:
    base = pd.Timestamp(start)
    normalized: list[dict[str, object]] = []
    for index, candle in enumerate(candles):
        item = dict(candle)
        item.setdefault("time", base + pd.Timedelta(hours=index))
        normalized.append(item)
    return make_oanda_frame(normalized)


def _ema_frame(make_oanda_frame):
    return _frame_from_candles(
        make_oanda_frame,
        [
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
            {"open": 100.0, "high": 100.2, "low": 99.7, "close": 99.8},
            {"open": 99.8, "high": 99.9, "low": 99.4, "close": 99.5},
            {"open": 99.5, "high": 99.7, "low": 99.3, "close": 99.4},
            {"open": 99.4, "high": 99.8, "low": 99.3, "close": 99.7},
            {"open": 99.7, "high": 100.4, "low": 99.6, "close": 100.3},
            {"open": 100.3, "high": 101.0, "low": 100.2, "close": 100.9},
            {"open": 100.9, "high": 101.3, "low": 100.8, "close": 101.1},
            {"open": 101.1, "high": 101.2, "low": 100.6, "close": 100.7},
            {"open": 100.7, "high": 100.8, "low": 100.1, "close": 100.2},
            {"open": 100.2, "high": 100.3, "low": 99.7, "close": 99.9},
            {"open": 99.9, "high": 100.0, "low": 99.5, "close": 99.6},
        ],
    )


def _macd_frame(make_oanda_frame):
    return _frame_from_candles(
        make_oanda_frame,
        [
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 99.6, "close": 99.7},
            {"open": 99.7, "high": 99.9, "low": 99.2, "close": 99.4},
            {"open": 99.4, "high": 99.6, "low": 99.0, "close": 99.2},
            {"open": 99.2, "high": 99.5, "low": 99.1, "close": 99.4},
            {"open": 99.4, "high": 100.2, "low": 99.3, "close": 100.1},
            {"open": 100.1, "high": 100.8, "low": 100.0, "close": 100.7},
            {"open": 100.7, "high": 101.2, "low": 100.6, "close": 101.0},
            {"open": 101.0, "high": 101.5, "low": 100.9, "close": 101.3},
            {"open": 101.3, "high": 102.2, "low": 101.2, "close": 102.0},
            {"open": 102.0, "high": 102.5, "low": 101.9, "close": 102.3},
            {"open": 102.3, "high": 103.4, "low": 102.2, "close": 103.1},
            {"open": 103.1, "high": 103.6, "low": 102.8, "close": 103.4},
        ],
    )


def _bollinger_frame(make_oanda_frame):
    return _frame_from_candles(
        make_oanda_frame,
        [
            {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 98.8, "close": 99.0},
            {"open": 99.0, "high": 99.4, "low": 98.7, "close": 98.9},
            {"open": 98.9, "high": 99.9, "low": 98.8, "close": 99.8},
            {"open": 99.8, "high": 100.5, "low": 99.7, "close": 100.3},
            {"open": 100.3, "high": 100.6, "low": 100.2, "close": 100.5},
        ],
    )


def _ict_frame(make_oanda_frame):
    return _frame_from_candles(
        make_oanda_frame,
        [
            {"open": 7.5, "high": 10.0, "low": 5.0, "close": 7.5},
            {"open": 13.0, "high": 20.0, "low": 6.0, "close": 13.0},
            {"open": 11.0, "high": 15.0, "low": 7.0, "close": 11.0},
            {"open": 10.0, "high": 14.0, "low": 8.0, "close": 10.0},
            {"open": 10.0, "high": 11.0, "low": 9.2, "close": 9.4},
            {"open": 9.4, "high": 10.9, "low": 8.0, "close": 10.8},
            {"open": 10.8, "high": 20.5, "low": 10.7, "close": 20.0},
            {"open": 20.0, "high": 20.8, "low": 16.0, "close": 16.5},
            {"open": 16.5, "high": 17.6, "low": 16.2, "close": 17.4},
            {"open": 17.4, "high": 17.7, "low": 7.5, "close": 8.2},
            {"open": 8.2, "high": 20.4, "low": 8.1, "close": 19.8},
        ],
    )


def _hybrid_frame(make_oanda_frame):
    return _frame_from_candles(
        make_oanda_frame,
        [
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
            {"open": 100.0, "high": 100.5, "low": 99.9, "close": 100.4},
            {"open": 100.4, "high": 100.9, "low": 100.3, "close": 100.8},
            {"open": 100.8, "high": 101.2, "low": 100.6, "close": 101.0},
            {"open": 101.0, "high": 101.4, "low": 100.8, "close": 101.2},
            {"open": 101.2, "high": 101.6, "low": 101.0, "close": 101.4},
            {"open": 101.4, "high": 101.8, "low": 101.2, "close": 101.6},
            {"open": 101.6, "high": 102.0, "low": 101.4, "close": 101.8},
            {"open": 101.8, "high": 102.6, "low": 101.7, "close": 102.5},
            {"open": 102.5, "high": 103.0, "low": 102.4, "close": 102.9},
            {"open": 102.9, "high": 103.6, "low": 102.8, "close": 103.4},
            {"open": 103.4, "high": 103.8, "low": 103.3, "close": 103.7},
            {"open": 103.7, "high": 104.2, "low": 103.6, "close": 104.1},
            {"open": 104.1, "high": 105.5, "low": 104.0, "close": 105.2},
        ],
    )


def _smc_frame(make_oanda_frame):
    prelude = []
    for index in range(24):
        price = 100.0 + ((index % 6) * 0.2)
        prelude.append(
            {
                "open": price,
                "high": price + 0.3,
                "low": price - 0.3,
                "close": price + 0.05,
            }
        )
    setup = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0},
        {"open": 102.0, "high": 102.2, "low": 98.0, "close": 99.0},
        {"open": 99.0, "high": 104.0, "low": 99.0, "close": 103.0},
        {"open": 103.0, "high": 103.2, "low": 97.0, "close": 98.0},
        {"open": 98.0, "high": 105.0, "low": 98.0, "close": 104.0},
        {"open": 104.0, "high": 104.2, "low": 96.0, "close": 97.0},
        {"open": 97.0, "high": 106.0, "low": 97.0, "close": 105.0},
        {"open": 105.0, "high": 106.5, "low": 102.0, "close": 103.0},
        {"open": 103.0, "high": 106.8, "low": 101.0, "close": 106.4},
        {"open": 106.4, "high": 106.6, "low": 98.0, "close": 98.5},
        {"open": 98.5, "high": 102.0, "low": 97.8, "close": 101.5},
        {"open": 101.5, "high": 103.0, "low": 101.2, "close": 102.8},
        {"open": 102.8, "high": 104.8, "low": 102.5, "close": 104.5},
        {"open": 104.5, "high": 104.8, "low": 97.9, "close": 98.2},
        {"open": 98.2, "high": 101.6, "low": 98.1, "close": 101.2},
    ]
    return _frame_from_candles(
        make_oanda_frame,
        prelude + setup,
        start="2024-01-01T04:00:00Z",
    )


def _extended_with_tail(frame: pd.DataFrame, tail_closes: list[float]) -> pd.DataFrame:
    last_time = pd.Timestamp(frame["time"].iloc[-1])
    previous_close = float(frame["close"].iloc[-1])
    tail_rows: list[dict[str, object]] = []
    spread = 0.05
    for index, close in enumerate(tail_closes, start=1):
        close_price = float(close)
        open_price = previous_close
        high_price = max(open_price, close_price) + 0.4
        low_price = min(open_price, close_price) - 0.4
        tail_rows.append(
            {
                "time": last_time + pd.Timedelta(hours=index),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "bid_open": open_price - spread,
                "bid_high": high_price - spread,
                "bid_low": low_price - spread,
                "bid_close": close_price - spread,
                "ask_open": open_price + spread,
                "ask_high": high_price + spread,
                "ask_low": low_price + spread,
                "ask_close": close_price + spread,
                "volume": 1_000.0,
            }
        )
        previous_close = close_price
    return pd.concat([frame, frame.iloc[:0], pd.DataFrame(tail_rows)], ignore_index=True)


@pytest.mark.parametrize(
    ("indicator_name", "builder"),
    [
        ("confirmed_swings", lambda base, _extended: confirmed_swings(base, swing_length=1)),
        (
            "confirmed_structure",
            lambda base, _extended: confirmed_structure(
                base,
                confirmed_swings(base, swing_length=1),
                close_break=True,
            ),
        ),
        (
            "confirmed_order_blocks",
            lambda base, _extended: confirmed_order_blocks(
                base,
                confirmed_structure(
                    base,
                    confirmed_swings(base, swing_length=1),
                    close_break=True,
                ),
                lookback=4,
            ),
        ),
        (
            "confirmed_liquidity",
            lambda base, _extended: confirmed_liquidity(
                base,
                confirmed_swings(base, swing_length=1),
                range_percent=0.02,
            ),
        ),
        (
            "confirmed_premium_discount",
            lambda base, _extended: confirmed_premium_discount(
                base,
                confirmed_swings(base, swing_length=1),
            ),
        ),
        (
            "confirmed_retracements",
            lambda base, _extended: confirmed_retracements(
                base,
                confirmed_swings(base, swing_length=1),
            ),
        ),
    ],
)
def test_live_safe_causal_smc_helpers_are_prefix_stable(indicator_name, builder):
    base = _smc_fixture()
    extension_index = pd.date_range(
        base.index[-1] + pd.Timedelta(hours=1),
        periods=3,
        freq="h",
        tz="UTC",
    )
    tail = pd.DataFrame(
        [
            {"open": 101.2, "high": 102.0, "low": 100.8, "close": 101.0, "volume": 260.0},
            {"open": 101.0, "high": 101.4, "low": 99.2, "close": 99.5, "volume": 270.0},
            {"open": 99.5, "high": 103.2, "low": 99.4, "close": 102.8, "volume": 280.0},
        ],
        index=extension_index,
    )
    extended = pd.concat([base, tail])

    base_output = builder(base, extended)
    extended_output = builder(extended, extended)

    pdt.assert_frame_equal(
        base_output.reset_index(drop=True),
        extended_output.iloc[: len(base_output)].reset_index(drop=True),
        check_exact=False,
        atol=1e-12,
        rtol=1e-12,
        obj=indicator_name,
    )


def test_causal_ict_fib_engine_is_prefix_stable():
    frame = _smc_fixture().reset_index(drop=True)
    extended = pd.concat(
        [
            frame,
            pd.DataFrame(
                [
                    {"open": 101.2, "high": 102.0, "low": 100.8, "close": 101.0, "volume": 260.0},
                    {"open": 101.0, "high": 101.4, "low": 99.2, "close": 99.5, "volume": 270.0},
                    {"open": 99.5, "high": 103.2, "low": 99.4, "close": 102.8, "volume": 280.0},
                ]
            ),
        ],
        ignore_index=True,
    )

    engine = CausalICTFibEngine(swing_length=1)
    base_fib = engine.update(frame)
    base_signature = engine.last_fib_signature

    engine = CausalICTFibEngine(swing_length=1)
    extended_fib = engine.update(extended)

    assert base_fib is not None
    assert base_signature is not None
    assert extended_fib is not None
    assert engine.last_fib_signature is not None
    assert extended_fib["confirmed_on_idx"] >= base_fib["confirmed_on_idx"]


@pytest.mark.parametrize(
    ("strategy_class", "frame_builder", "tail_closes"),
    [
        (EmaRsiTrendStrategy, _ema_frame, [99.4, 99.2, 99.0]),
        (BollingerZscoreReversionStrategy, _bollinger_frame, [100.2, 100.1, 100.0]),
        (SmcPullbackStrategy, _smc_frame, [102.0, 101.4, 101.0]),
        (IctOteSniperStrategy, _ict_frame, [8.8, 9.6, 10.4]),
        (HybridRegimeStrategy, _hybrid_frame, [105.0, 105.4, 105.8]),
        (MacdAtrBreakoutStrategy, _macd_frame, [103.6, 103.9, 104.2]),
    ],
)
def test_live_safe_showcase_strategies_are_prefix_stable(
    make_oanda_frame,
    strategy_class,
    frame_builder,
    tail_closes,
):
    base_frame = frame_builder(make_oanda_frame)
    extended_frame = _extended_with_tail(base_frame, tail_closes)
    cutoff = pd.Timestamp(base_frame["time"].iloc[-1]) + pd.Timedelta(hours=1)

    base_result = run_backtest(
        strategy_class,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=base_frame,
    )
    extended_result = run_backtest(
        strategy_class,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=extended_frame,
    )

    base_orders = base_result.order_ledger.loc[
        base_result.order_ledger["event_time"] <= cutoff,
        ["event_time", "role", "status_name", "order_name", "is_buy", "size", "created_price"],
    ].reset_index(drop=True)
    extended_orders = extended_result.order_ledger.loc[
        extended_result.order_ledger["event_time"] <= cutoff,
        ["event_time", "role", "status_name", "order_name", "is_buy", "size", "created_price"],
    ].reset_index(drop=True)
    pdt.assert_frame_equal(base_orders, extended_orders)

    base_trades = base_result.closed_trade_ledger.loc[
        base_result.closed_trade_ledger["exit_time"] <= cutoff,
        ["entry_time", "exit_time", "direction", "entry_price", "exit_price", "net_pnl"],
    ].reset_index(drop=True)
    extended_trades = extended_result.closed_trade_ledger.loc[
        extended_result.closed_trade_ledger["exit_time"] <= cutoff,
        ["entry_time", "exit_time", "direction", "entry_price", "exit_price", "net_pnl"],
    ].reset_index(drop=True)
    pdt.assert_frame_equal(base_trades, extended_trades)
