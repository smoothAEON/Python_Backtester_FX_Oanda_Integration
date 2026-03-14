from __future__ import annotations

import pandas as pd
import pytest

from backtester.optimization import ParameterSpec, run_grid_search
from backtester.reporting import build_backtest_json_payload
from backtester.run_backtest import run_backtest
from backtester.strategy import BaseStrategy


def _frame_for_hours(make_oanda_frame, closes: list[float], *, start: str) -> pd.DataFrame:
    start_time = pd.Timestamp(start, tz="UTC")
    candles = []
    for index, close in enumerate(closes):
        base = close - 0.2
        candles.append(
            {
                "time": start_time + pd.Timedelta(hours=index),
                "open": base,
                "high": close + 0.3,
                "low": base - 0.3,
                "close": close,
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
        base = close - 0.5
        candles.append(
            {
                "time": start_time + pd.Timedelta(hours=index * 4),
                "open": base,
                "high": close + 0.6,
                "low": base - 0.4,
                "close": close,
            }
        )
    return make_oanda_frame(candles)


class CaptureMultiTimeframeStrategy(BaseStrategy):
    observations: list[dict] = []
    summary: dict[str, object] = {}

    params = (("hold_bars", 2),)

    def __init__(self):
        super().__init__()
        self._observations: list[dict] = []
        self._entry_timeframe: str | None = None
        self._entry_bar: int | None = None

    def next(self):
        if not self.has_all_timeframes_ready():
            return

        context_frame = self.to_ohlcv_dataframe("H4")
        self._observations.append(
            {
                "primary_len": len(self.data0),
                "primary_time": pd.Timestamp(self.data0.datetime.datetime(0), tz="UTC"),
                "context_len": len(self.data_for_timeframe("H4")),
                "primary_close": self.mid.close,
                "context_close": self.mid_for("H4").close,
                "context_rows": len(context_frame),
            }
        )

        if self._entry_bar is None and self.is_flat():
            entry_order = self.submit_long_market(size=1)
            self._entry_timeframe = getattr(entry_order.data, "_phase_timeframe", None)
            self._entry_bar = len(self.data0)
        elif (
            self._entry_bar is not None
            and self.position
            and len(self.data0) - self._entry_bar >= int(self.p.hold_bars)
        ):
            self.close(data=self.data0)

    def stop(self):
        type(self).observations = list(self._observations)
        type(self).summary = {
            "available_timeframes": self.available_timeframes,
            "entry_timeframe": self._entry_timeframe,
            "primary_rows": len(self.to_ohlcv_dataframe()),
            "context_rows": len(self.to_ohlcv_dataframe("H4")),
        }


def test_run_backtest_supports_same_instrument_multi_timeframe_context(make_oanda_frame):
    CaptureMultiTimeframeStrategy.observations = []
    CaptureMultiTimeframeStrategy.summary = {}
    primary = _frame_for_hours(
        make_oanda_frame,
        [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0],
        start="2024-01-01T00:00:00Z",
    )
    context = _frame_for_four_hours(
        make_oanda_frame,
        [100.0, 200.0],
        start="2024-01-01T00:00:00Z",
    )

    result = run_backtest(
        CaptureMultiTimeframeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=primary,
        context_data={"H4": context},
    )

    assert result.timeframe == "H1"
    assert result.timeframes == ("H1", "H4")
    assert CaptureMultiTimeframeStrategy.summary["available_timeframes"] == ("H1", "H4")
    assert CaptureMultiTimeframeStrategy.summary["entry_timeframe"] == "H1"
    assert CaptureMultiTimeframeStrategy.summary["primary_rows"] == 8
    assert CaptureMultiTimeframeStrategy.summary["context_rows"] == 2
    assert [row["primary_time"] for row in CaptureMultiTimeframeStrategy.observations] == [
        pd.Timestamp("2024-01-01T04:00:00Z"),
        pd.Timestamp("2024-01-01T05:00:00Z"),
        pd.Timestamp("2024-01-01T06:00:00Z"),
        pd.Timestamp("2024-01-01T07:00:00Z"),
        pd.Timestamp("2024-01-01T08:00:00Z"),
    ]
    assert [row["context_close"] for row in CaptureMultiTimeframeStrategy.observations] == [
        100.0,
        100.0,
        100.0,
        100.0,
        200.0,
    ]
    assert [row["context_rows"] for row in CaptureMultiTimeframeStrategy.observations] == [
        1,
        1,
        1,
        1,
        2,
    ]
    assert not result.order_ledger.empty
    assert not result.trade_ledger.empty


def test_run_backtest_rejects_invalid_context_timeframes(make_oanda_frame):
    primary = _frame_for_hours(
        make_oanda_frame,
        [10.0, 11.0, 12.0],
        start="2024-01-01T00:00:00Z",
    )
    higher = _frame_for_four_hours(
        make_oanda_frame,
        [100.0, 200.0],
        start="2024-01-01T00:00:00Z",
    )

    with pytest.raises(ValueError, match="must not repeat the primary timeframe"):
        run_backtest(
            CaptureMultiTimeframeStrategy,
            instrument="XAU_USD",
            timeframe="H1",
            dataframe=primary,
            context_data={"H1": higher},
        )

    with pytest.raises(ValueError, match="strictly higher"):
        run_backtest(
            CaptureMultiTimeframeStrategy,
            instrument="XAU_USD",
            timeframe="H1",
            dataframe=primary,
            context_data={"M15": higher},
        )

    with pytest.raises(ValueError, match="Duplicate context timeframe"):
        run_backtest(
            CaptureMultiTimeframeStrategy,
            instrument="XAU_USD",
            timeframe="H1",
            dataframe=primary,
            context_data={"h4": higher, "H4": higher},
        )


def test_reporting_payload_includes_multi_timeframe_metadata(make_oanda_frame):
    primary = _frame_for_hours(
        make_oanda_frame,
        [10.0, 11.0, 12.0, 13.0],
        start="2024-01-01T00:00:00Z",
    )
    context = _frame_for_four_hours(
        make_oanda_frame,
        [100.0, 200.0],
        start="2024-01-01T00:00:00Z",
    )
    result = run_backtest(
        CaptureMultiTimeframeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=primary,
        context_data={"H4": context},
    )

    payload = build_backtest_json_payload(result)

    assert payload["metadata"]["timeframe"] == "H1"
    assert payload["metadata"]["timeframes"] == ["H1", "H4"]
    assert payload["execution_assumptions"]["multi_timeframe_support"] is True
    assert any(caveat["code"] == "multi_timeframe_context" for caveat in payload["caveats"])


def test_grid_search_passes_context_data_through_to_trials(make_oanda_frame):
    primary = _frame_for_hours(
        make_oanda_frame,
        [10.0, 11.0, 12.0, 13.0, 14.0],
        start="2024-01-01T00:00:00Z",
    )
    context = _frame_for_four_hours(
        make_oanda_frame,
        [100.0, 200.0],
        start="2024-01-01T00:00:00Z",
    )

    result = run_grid_search(
        CaptureMultiTimeframeStrategy,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=primary,
        context_data={"H4": context},
        search_space=[ParameterSpec("hold_bars", "int", grid_values=(2,))],
        objective="total_return",
    )

    table = result.table()

    assert len(table) == 1
    assert tuple(table.iloc[0]["timeframes"]) == ("H1", "H4")
    assert result.best_trial().timeframes == ("H1", "H4")
