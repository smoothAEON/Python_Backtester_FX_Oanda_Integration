"""Trend-following showcase strategy using safe built-in indicators."""

from __future__ import annotations

from backtester.sizing import FixedLotSizer
from backtester.strategy import (
    crossed_above,
    crossed_below,
    is_bearish_candle,
    is_bullish_candle,
)

from ._shared import ShowcaseStrategy, latest_value, tail_is_ready


class EmaRsiTrendStrategy(ShowcaseStrategy):
    """Use EMA momentum with RSI/ADX confirmation and simple time-based exits."""

    params = (
        ("trend_period", 5),
        ("fast_period", 2),
        ("slow_period", 4),
        ("rsi_period", 3),
        ("rsi_long_threshold", 52.0),
        ("rsi_short_threshold", 48.0),
        ("adx_period", 3),
        ("adx_min", 5.0),
        ("fixed_units", 1_000.0),
        ("max_hold_bars", 4),
    )

    def __init__(self) -> None:
        super().__init__()
        self.position_sizer = FixedLotSizer(float(self.p.fixed_units))
        self._entry_bar: int | None = None

    def next(self) -> None:
        fast = self.indicator(None, "ema", period=int(self.p.fast_period))
        slow = self.indicator(None, "ema", period=int(self.p.slow_period))
        trend = self.indicator(None, "sma", period=int(self.p.trend_period))
        rsi = self.indicator(None, "rsi", period=int(self.p.rsi_period))
        adx = self.indicator(None, "adx", period=int(self.p.adx_period))

        if not all(
            (
                tail_is_ready(fast, 2),
                tail_is_ready(slow, 2),
                tail_is_ready(trend, 1),
                tail_is_ready(rsi, 1),
                tail_is_ready(adx, 1),
            )
        ):
            return

        fast_prev = latest_value(fast, offset=-2)
        fast_curr = latest_value(fast)
        slow_prev = latest_value(slow, offset=-2)
        slow_curr = latest_value(slow)
        trend_curr = latest_value(trend)
        rsi_curr = latest_value(rsi)
        adx_curr = latest_value(adx)
        if None in {
            fast_prev,
            fast_curr,
            slow_prev,
            slow_curr,
            trend_curr,
            rsi_curr,
            adx_curr,
        }:
            return

        bullish_candle = is_bullish_candle(self.mid.open, self.mid.close)
        bearish_candle = is_bearish_candle(self.mid.open, self.mid.close)
        long_signal = (
            self.mid.close > trend_curr
            and crossed_above(fast_prev, fast_curr, slow_prev, slow_curr)
            and rsi_curr >= float(self.p.rsi_long_threshold)
            and adx_curr >= float(self.p.adx_min)
            and bullish_candle
        )
        short_signal = (
            self.mid.close < trend_curr
            and crossed_below(fast_prev, fast_curr, slow_prev, slow_curr)
            and rsi_curr <= float(self.p.rsi_short_threshold)
            and adx_curr >= float(self.p.adx_min)
            and bearish_candle
        )

        if self.is_flat() and not self.has_open_order():
            if long_signal:
                decision = self.size_entry(
                    self.position_sizer,
                    side="long",
                    entry_price=self.ask.close,
                    stop_price=None,
                )
                if decision.accepted:
                    self.submit_long_market(
                        size=decision.final_size,
                        sizing_decision=decision,
                    )
                    self._entry_bar = len(self)
                return
            if short_signal:
                decision = self.size_entry(
                    self.position_sizer,
                    side="short",
                    entry_price=self.bid.close,
                    stop_price=None,
                )
                if decision.accepted:
                    self.submit_short_market(
                        size=decision.final_size,
                        sizing_decision=decision,
                    )
                    self._entry_bar = len(self)
                return

        if self.position:
            hold_limit_reached = (
                self._entry_bar is not None
                and len(self) - self._entry_bar >= int(self.p.max_hold_bars)
            )
            if self.is_long() and (short_signal or hold_limit_reached):
                self.close()
            elif self.is_short() and (long_signal or hold_limit_reached):
                self.close()

            if not self.position:
                self._entry_bar = None
