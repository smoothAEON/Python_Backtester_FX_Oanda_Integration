from __future__ import annotations

import pandas as pd
import pytest

import backtester.strategy.instrument_api as instrument_api_module
from backtester.optimization import ParameterSpec, run_grid_search
from backtester.reporting import build_backtest_json_payload
from backtester.run_backtest import run_backtest
from backtester.strategy import BaseStrategy, IndicatorRequest


def _frame_for_hours(make_oanda_frame, closes: list[float], *, start: str) -> pd.DataFrame:
    start_time = pd.Timestamp(start, tz="UTC")
    candles = []
    for index, close in enumerate(closes):
        candles.append(
            {
                "time": start_time + pd.Timedelta(hours=index),
                "open": close - 0.3,
                "high": close + 0.4,
                "low": close - 0.5,
                "close": close,
                "volume": 100 + index,
            }
        )
    return make_oanda_frame(candles)


def _frame_for_four_hours(
    make_oanda_frame,
    closes: list[float],
    *,
    start: str,
) -> pd.DataFrame:
    start_time = pd.Timestamp(start, tz="UTC")
    candles = []
    for index, close in enumerate(closes):
        candles.append(
            {
                "time": start_time + pd.Timedelta(hours=index * 4),
                "open": close - 0.6,
                "high": close + 0.7,
                "low": close - 0.8,
                "close": close,
                "volume": 250 + index,
            }
        )
    return make_oanda_frame(candles)


class InstrumentApiObservationStrategy(BaseStrategy):
    runtime_ids: list[int] = []
    htf_slope_values: list[float] = []
    snapshots: list[dict] = []
    summary: dict[str, object] = {}

    def __init__(self):
        super().__init__()
        self._runtime_ids: list[int] = []
        self._htf_slope_values: list[float] = []
        self._snapshots: list[dict] = []
        self._summary: dict[str, object] = {}

    def next(self):
        if not self.has_all_timeframes_ready():
            return

        self._runtime_ids.append(id(self.instrument_api))
        primary_ema = self.instrument_api.indicator("H1", "ema", period=2)
        context_slope = self.instrument_api.indicator("H4", "rolling_linreg_slope", window=2)
        snapshot = self.indicator_snapshot(
            "H4",
            [
                IndicatorRequest("rolling_linreg_slope", params={"window": 2}, alias="htf_slope"),
            ],
        )
        self._htf_slope_values.append(float(snapshot["htf_slope"]))
        self._snapshots.append(snapshot)
        self._summary = {
            "available_timeframes": self.instrument_api.available_timeframes(),
            "primary_ema_type": type(primary_ema).__name__,
            "context_slope_type": type(context_slope).__name__,
            "context_ohlcv_rows": len(self.instrument_api.ohlcv("H4")),
            "context_price_close": self.instrument_api.price_bar("H4", side="mid").close,
        }

    def stop(self):
        type(self).runtime_ids = list(self._runtime_ids)
        type(self).htf_slope_values = list(self._htf_slope_values)
        type(self).snapshots = list(self._snapshots)
        type(self).summary = dict(self._summary)


class InstrumentApiMemoStrategy(BaseStrategy):
    call_count: int = 0
    seen_pairs: list[tuple[float, float]] = []

    def __init__(self):
        super().__init__()
        self._seen_pairs: list[tuple[float, float]] = []

    def next(self):
        first = self.instrument_api.indicator("H1", "ema", period=2)
        second = self.instrument_api.indicator("H1", "ema", period=2)
        self._seen_pairs.append((float(first.iloc[-1]), float(second.iloc[-1])))

    def stop(self):
        type(self).seen_pairs = list(self._seen_pairs)


class InstrumentApiErrorStrategy(BaseStrategy):
    errors: dict[str, str] = {}

    def __init__(self):
        super().__init__()
        self._errors: dict[str, str] = {}

    def next(self):
        if self._errors:
            return

        checks = {
            "unknown_timeframe": lambda: self.instrument_api.ohlcv("D"),
            "unknown_indicator": lambda: self.instrument_api.indicator("H1", "not_a_real_indicator"),
            "invalid_param": lambda: self.instrument_api.indicator("H1", "ema", period=0),
            "unsafe_savgol": lambda: self.instrument_api.indicator(
                "H1",
                "savgol_smooth",
                window_length=5,
                polyorder=2,
            ),
            "unsafe_indicator": lambda: self.instrument_api.indicator("H1", "ict_fib"),
            "unsafe_snapshot": lambda: self.indicator_snapshot(
                "H1",
                [IndicatorRequest("swing_highs_lows", params={"swing_length": 1})],
            ),
            "unsupported_source": lambda: self.instrument_api.indicator(
                "H1",
                "atr",
                source="close",
                period=2,
            ),
        }

        for name, callback in checks.items():
            try:
                callback()
            except Exception as exc:  # noqa: BLE001 - assertions inspect messages
                self._errors[name] = str(exc)

    def stop(self):
        type(self).errors = dict(self._errors)


class InstrumentApiTimeAlignedIndicatorsStrategy(BaseStrategy):
    previous_high_first_bar: int | None = None
    tokyo_active_flags: list[int] = []

    def __init__(self):
        super().__init__()
        self._previous_high_first_bar: int | None = None
        self._tokyo_active_flags: list[int] = []

    def next(self):
        previous = self.instrument_api.indicator("H1", "previous_high_low", time_frame="1D")
        tokyo = self.instrument_api.indicator("H1", "sessions", session="Tokyo")

        previous_high = previous["PreviousHigh"].iloc[-1]
        if self._previous_high_first_bar is None and not pd.isna(previous_high):
            self._previous_high_first_bar = len(self)

        self._tokyo_active_flags.append(int(tokyo["Active"].iloc[-1]))

    def stop(self):
        type(self).previous_high_first_bar = self._previous_high_first_bar
        type(self).tokyo_active_flags = list(self._tokyo_active_flags)


class InstrumentApiSignalStrategy(BaseStrategy):
    params = (("entry_buffer", 0.2),)

    def next(self):
        if not self.has_all_timeframes_ready() or self.has_open_order():
            return

        if len(self.data0) == 5 and self.is_flat():
            primary_ema = self.instrument_api.indicator("H1", "ema", period=2)
            context_slope = self.instrument_api.indicator("H4", "rolling_linreg_slope", window=2)
            entry_price = max(
                float(primary_ema.iloc[-1]),
                float(self.instrument_api.price_bar("H1", side="mid").close),
            ) + float(self.p.entry_buffer)
            if not pd.isna(context_slope.iloc[-1]):
                entry_price += float(context_slope.iloc[-1]) / 100.0
            self.submit_long_stop(
                price=entry_price,
                size=1,
                take_profit=entry_price + 1.0,
            )


def test_instrument_api_exposes_master_runtime_and_built_ins(make_oanda_frame):
    InstrumentApiObservationStrategy.runtime_ids = []
    InstrumentApiObservationStrategy.htf_slope_values = []
    InstrumentApiObservationStrategy.snapshots = []
    InstrumentApiObservationStrategy.summary = {}

    primary = _frame_for_hours(
        make_oanda_frame,
        [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0],
        start="2024-01-01T00:00:00Z",
    )
    context = _frame_for_four_hours(
        make_oanda_frame,
        [100.0, 150.0, 260.0],
        start="2024-01-01T00:00:00Z",
    )

    run_backtest(
        InstrumentApiObservationStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=primary,
        context_data={"H4": context},
    )

    assert len(set(InstrumentApiObservationStrategy.runtime_ids)) == 1
    assert InstrumentApiObservationStrategy.summary["available_timeframes"] == ("H1", "H4")
    assert InstrumentApiObservationStrategy.summary["primary_ema_type"] == "Series"
    assert InstrumentApiObservationStrategy.summary["context_slope_type"] == "Series"
    assert InstrumentApiObservationStrategy.summary["context_ohlcv_rows"] == 3
    assert InstrumentApiObservationStrategy.summary["context_price_close"] == 260.0
    expected_slopes = [float("nan")] * 4 + [50.0] * 4 + [110.0]
    assert len(InstrumentApiObservationStrategy.htf_slope_values) == len(expected_slopes)
    for actual, expected in zip(
        InstrumentApiObservationStrategy.htf_slope_values,
        expected_slopes,
        strict=True,
    ):
        if pd.isna(expected):
            assert pd.isna(actual)
        else:
            assert actual == pytest.approx(expected)
    assert "htf_slope" in InstrumentApiObservationStrategy.snapshots[-1]
    assert InstrumentApiObservationStrategy.snapshots[-1]["htf_slope"] == pytest.approx(110.0)


def test_instrument_api_memoizes_repeated_same_bar_indicator_requests(
    make_oanda_frame,
    monkeypatch,
):
    InstrumentApiMemoStrategy.seen_pairs = []
    call_count = {"ema": 0}
    original_ema = instrument_api_module.ema

    def counting_ema(*args, **kwargs):
        call_count["ema"] += 1
        return original_ema(*args, **kwargs)

    monkeypatch.setitem(
        instrument_api_module.InstrumentRuntime._PRICE_INDICATORS,
        "ema",
        counting_ema,
    )

    primary = _frame_for_hours(
        make_oanda_frame,
        [10.0, 10.5, 11.0, 11.5],
        start="2024-01-01T00:00:00Z",
    )

    run_backtest(
        InstrumentApiMemoStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=primary,
    )

    assert call_count["ema"] == 4
    assert len(InstrumentApiMemoStrategy.seen_pairs) == 4
    for first, second in InstrumentApiMemoStrategy.seen_pairs:
        if pd.isna(first) and pd.isna(second):
            continue
        assert first == second


def test_instrument_api_rejects_invalid_requests_cleanly(make_oanda_frame):
    InstrumentApiErrorStrategy.errors = {}
    primary = _frame_for_hours(
        make_oanda_frame,
        [10.0, 11.0, 12.0],
        start="2024-01-01T00:00:00Z",
    )
    context = _frame_for_four_hours(
        make_oanda_frame,
        [100.0, 150.0],
        start="2024-01-01T00:00:00Z",
    )

    run_backtest(
        InstrumentApiErrorStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=primary,
        context_data={"H4": context},
    )

    assert "Available timeframes: H1, H4" in InstrumentApiErrorStrategy.errors["unknown_timeframe"]
    assert "Unknown built-in indicator" in InstrumentApiErrorStrategy.errors["unknown_indicator"]
    assert "period must be positive" in InstrumentApiErrorStrategy.errors["invalid_param"]
    assert "unsafe/repainting" in InstrumentApiErrorStrategy.errors["unsafe_savgol"]
    assert "unsafe/repainting" in InstrumentApiErrorStrategy.errors["unsafe_indicator"]
    assert "offline research only" in InstrumentApiErrorStrategy.errors["unsafe_snapshot"]
    assert "does not accept a source parameter" in InstrumentApiErrorStrategy.errors["unsupported_source"]


def test_instrument_api_keeps_time_aware_indicators_on_completed_bar_time(make_oanda_frame):
    InstrumentApiTimeAlignedIndicatorsStrategy.previous_high_first_bar = None
    InstrumentApiTimeAlignedIndicatorsStrategy.tokyo_active_flags = []
    primary = _frame_for_hours(
        make_oanda_frame,
        [float(value) for value in range(30)],
        start="2024-01-01T00:00:00Z",
    )

    run_backtest(
        InstrumentApiTimeAlignedIndicatorsStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=primary,
    )

    assert InstrumentApiTimeAlignedIndicatorsStrategy.previous_high_first_bar == 25
    assert InstrumentApiTimeAlignedIndicatorsStrategy.tokyo_active_flags[:10] == [1] * 9 + [0]


def test_instrument_api_strategy_flows_through_reporting_and_optimization(make_oanda_frame):
    primary = _frame_for_hours(
        make_oanda_frame,
        [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
        start="2024-01-01T00:00:00Z",
    )
    context = _frame_for_four_hours(
        make_oanda_frame,
        [100.0, 150.0, 260.0],
        start="2024-01-01T00:00:00Z",
    )

    result = run_backtest(
        InstrumentApiSignalStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=primary,
        context_data={"H4": context},
    )
    payload = build_backtest_json_payload(result)

    optimization = run_grid_search(
        InstrumentApiSignalStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=primary,
        context_data={"H4": context},
        search_space=[ParameterSpec("entry_buffer", "float", grid_values=(0.2,))],
        objective="total_return",
    )

    assert payload["metadata"]["timeframes"] == ["H1", "H4"]
    assert not result.order_ledger.empty
    assert not result.trade_ledger.empty
    assert len(optimization.table()) == 1
    assert optimization.best_trial().timeframes == ("H1", "H4")
