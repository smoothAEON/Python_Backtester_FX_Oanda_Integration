"""Breakout showcase strategy using stop entries and risk sizing."""

from __future__ import annotations

from backtester.sizing import RiskPercentSizer
from backtester.strategy import candle_closes_above_level, candle_closes_below_level

from ._shared import ShowcaseStrategy, latest_value, tail_is_ready


class MacdAtrBreakoutStrategy(ShowcaseStrategy):
    """Trade stop-entry breakouts after MACD and slope confirmation."""

    params = (
        ("macd_fast", 3),
        ("macd_slow", 7),
        ("macd_signal", 3),
        ("atr_period", 5),
        ("slope_window", 4),
        ("breakout_lookback", 4),
        ("breakout_atr_buffer", 0.10),
        ("stop_atr_multiplier", 1.2),
        ("risk_reward", 1.6),
        ("risk_percent", 0.004),
        ("stale_bars", 3),
    )

    def __init__(self) -> None:
        super().__init__()
        self.position_sizer = RiskPercentSizer(float(self.p.risk_percent))
        self._pending_entry_bar: int | None = None

    def next(self) -> None:
        if self._cancel_stale_entry():
            return
        if self.has_open_order() or not self.is_flat():
            return

        frame = self.to_ohlcv_dataframe()
        lookback = int(self.p.breakout_lookback)
        if len(frame) < max(int(self.p.macd_slow) + int(self.p.macd_signal), lookback + 2):
            return

        macd_values = self.indicator(
            None,
            "macd",
            fast=int(self.p.macd_fast),
            slow=int(self.p.macd_slow),
            signal=int(self.p.macd_signal),
        )
        atr_values = self.indicator(None, "atr", period=int(self.p.atr_period))
        slope_values = self.indicator(
            None,
            "rolling_linreg_slope",
            window=int(self.p.slope_window),
        )
        if not all(
            (
                tail_is_ready(macd_values, 1, "MACD"),
                tail_is_ready(macd_values, 1, "Signal"),
                tail_is_ready(macd_values, 1, "Histogram"),
                tail_is_ready(atr_values, 1),
                tail_is_ready(slope_values, 1),
            )
        ):
            return

        resistance = float(frame["high"].iloc[-(lookback + 1) : -1].max())
        support = float(frame["low"].iloc[-(lookback + 1) : -1].min())
        atr_now = latest_value(atr_values)
        slope_now = latest_value(slope_values)
        macd_line = latest_value(macd_values, "MACD")
        macd_signal = latest_value(macd_values, "Signal")
        histogram = latest_value(macd_values, "Histogram")
        if None in {atr_now, slope_now, macd_line, macd_signal, histogram}:
            return

        long_trigger = (
            macd_line > macd_signal
            and histogram > 0.0
            and slope_now > 0.0
            and candle_closes_above_level(self.mid.close, resistance)
        )
        short_trigger = (
            macd_line < macd_signal
            and histogram < 0.0
            and slope_now < 0.0
            and candle_closes_below_level(self.mid.close, support)
        )
        buffer_size = atr_now * float(self.p.breakout_atr_buffer)
        stop_width = atr_now * float(self.p.stop_atr_multiplier)

        if long_trigger:
            entry_price = self.round_price(resistance + buffer_size)
            stop_price = self.round_price(entry_price - stop_width)
            take_profit = self.round_price(
                entry_price + ((entry_price - stop_price) * float(self.p.risk_reward))
            )
            decision = self.size_entry(
                self.position_sizer,
                side="long",
                entry_price=entry_price,
                stop_price=stop_price,
            )
            if decision.accepted:
                self.submit_long_stop(
                    price=entry_price,
                    size=decision.final_size,
                    stop_loss=stop_price,
                    take_profit=take_profit,
                    sizing_decision=decision,
                )
                self._pending_entry_bar = len(self)
            return

        if short_trigger:
            entry_price = self.round_price(support - buffer_size)
            stop_price = self.round_price(entry_price + stop_width)
            take_profit = self.round_price(
                entry_price - ((stop_price - entry_price) * float(self.p.risk_reward))
            )
            decision = self.size_entry(
                self.position_sizer,
                side="short",
                entry_price=entry_price,
                stop_price=stop_price,
            )
            if decision.accepted:
                self.submit_short_stop(
                    price=entry_price,
                    size=decision.final_size,
                    stop_loss=stop_price,
                    take_profit=take_profit,
                    sizing_decision=decision,
                )
                self._pending_entry_bar = len(self)

    def _cancel_stale_entry(self) -> bool:
        if not self.has_open_order():
            self._pending_entry_bar = None
            return False
        if self._pending_entry_bar is None:
            return False
        if len(self) - self._pending_entry_bar >= int(self.p.stale_bars):
            self.cancel_open_orders()
            self._pending_entry_bar = None
            return True
        return False
