"""Hybrid showcase strategy that changes behavior by ADX regime."""

from __future__ import annotations

import pandas as pd

from backtester.indicators import bos_choch, premium_discount, rolling_linreg_slope, savgol_smooth, swing_highs_lows
from backtester.sizing import KellySizer
from backtester.strategy import (
    is_equilibrium,
    smc_bearish_confluence,
    smc_bullish_confluence,
    structure_bias,
)

from ._shared import ShowcaseStrategy, latest_defined_value, latest_value, tail_is_ready


class HybridRegimeStrategy(ShowcaseStrategy):
    """Switch between momentum and equilibrium logic based on ADX."""

    params = (
        ("adx_period", 5),
        ("adx_threshold", 10.0),
        ("smoothing_window", 5),
        ("smoothing_polyorder", 2),
        ("slope_window", 4),
        ("swing_length", 1),
        ("risk_reward", 1.5),
        ("max_hold_bars", 8),
        ("win_probability", 0.57),
        ("payoff_ratio", 1.9),
        ("kelly_fraction", 0.25),
        ("max_risk_percent", 0.01),
    )

    def __init__(self) -> None:
        super().__init__()
        self.position_sizer = KellySizer(
            win_probability=float(self.p.win_probability),
            payoff_ratio=float(self.p.payoff_ratio),
            kelly_fraction=float(self.p.kelly_fraction),
            max_risk_percent=float(self.p.max_risk_percent),
        )
        self._entry_bar: int | None = None

    def next(self) -> None:
        if self.has_open_order():
            return

        frame = self.to_ohlcv_dataframe()
        if len(frame) < 8:
            return

        adx_values = self.indicator(None, "adx", period=int(self.p.adx_period))
        slope_values = rolling_linreg_slope(frame["close"], window=int(self.p.slope_window))
        smooth_values = savgol_smooth(
            frame["close"],
            window_length=int(self.p.smoothing_window),
            polyorder=int(self.p.smoothing_polyorder),
        )
        swings = swing_highs_lows(frame, swing_length=int(self.p.swing_length))
        structure = bos_choch(frame, swings, close_break=True)
        zones = premium_discount(frame, swings)
        if not all(
            (
                tail_is_ready(adx_values, 1),
                tail_is_ready(slope_values, 1),
            )
        ):
            return
        defined_smooth = smooth_values.dropna()
        if len(defined_smooth) < 2:
            return

        adx_now = latest_value(adx_values)
        slope_now = latest_value(slope_values)
        smooth_prev = float(defined_smooth.iloc[-2])
        smooth_now = latest_defined_value(defined_smooth)
        structure_signal = structure_bias(
            latest_defined_value(structure, "BOS"),
            latest_defined_value(structure, "CHOCH"),
        )
        zone_value = zones["Zone"].iloc[-1] if not pd.isna(zones["Zone"].iloc[-1]) else 0
        if None in {adx_now, slope_now, smooth_prev, smooth_now}:
            return

        trend_up = smooth_now > smooth_prev
        trend_down = smooth_now < smooth_prev
        bullish_confluence = smc_bullish_confluence(structure_signal, int(zone_value))
        bearish_confluence = smc_bearish_confluence(structure_signal, int(zone_value))
        trending = adx_now >= float(self.p.adx_threshold)
        long_signal = False
        short_signal = False
        if trending:
            long_signal = trend_up and slope_now > 0.0 and (
                bullish_confluence or structure_signal >= 0
            )
            short_signal = trend_down and slope_now < 0.0 and (
                bearish_confluence or structure_signal <= 0
            )
        else:
            long_signal = trend_up and slope_now > 0.0 and (
                is_equilibrium(int(zone_value)) or structure_signal > 0
            )
            short_signal = trend_down and slope_now < 0.0 and (
                is_equilibrium(int(zone_value)) or structure_signal < 0
            )

        if self.is_flat():
            if long_signal:
                stop_price = self.round_price(float(frame["low"].iloc[-3:].min()))
                if stop_price >= self.ask.close:
                    return
                decision = self.size_entry(
                    self.position_sizer,
                    side="long",
                    entry_price=self.ask.close,
                    stop_price=stop_price,
                )
                if decision.accepted:
                    take_profit = self.round_price(
                        self.ask.close
                        + ((self.ask.close - stop_price) * float(self.p.risk_reward))
                    )
                    self.submit_long_market(
                        size=decision.final_size,
                        stop_loss=stop_price,
                        take_profit=take_profit,
                        sizing_decision=decision,
                    )
                    self._entry_bar = len(self)
                return

            if short_signal:
                stop_price = self.round_price(float(frame["high"].iloc[-3:].max()))
                if stop_price <= self.bid.close:
                    return
                decision = self.size_entry(
                    self.position_sizer,
                    side="short",
                    entry_price=self.bid.close,
                    stop_price=stop_price,
                )
                if decision.accepted:
                    take_profit = self.round_price(
                        self.bid.close
                        - ((stop_price - self.bid.close) * float(self.p.risk_reward))
                    )
                    self.submit_short_market(
                        size=decision.final_size,
                        stop_loss=stop_price,
                        take_profit=take_profit,
                        sizing_decision=decision,
                    )
                    self._entry_bar = len(self)
                return

        if self.position and self._entry_bar is not None:
            if len(self) - self._entry_bar >= int(self.p.max_hold_bars):
                self.cancel_open_orders()
                self.close()
                self._entry_bar = None
