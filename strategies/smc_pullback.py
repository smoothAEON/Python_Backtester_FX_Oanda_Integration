"""SMC showcase strategy using pending limit entries and staged exits."""

from __future__ import annotations

import pandas as pd

from backtester.indicators import (
    bos_choch,
    liquidity,
    ob,
    premium_discount,
    retracements,
    swing_highs_lows,
)
from backtester.sizing import RiskPercentSizer
from backtester.strategy import (
    is_discount,
    is_premium,
    smc_bearish_confluence,
    smc_bullish_confluence,
    structure_bias,
)

from ._shared import ShowcaseStrategy, latest_defined_value, latest_value


class SmcPullbackStrategy(ShowcaseStrategy):
    """Look for session-active structural pullbacks back into an order block."""

    params = (
        ("swing_length", 1),
        ("range_percent", 0.02),
        ("retracement_threshold", 10.0),
        ("risk_percent", 0.003),
        ("session_name", "London"),
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
        if len(frame) < 8:
            return

        swings = swing_highs_lows(frame, swing_length=int(self.p.swing_length))
        structure = bos_choch(frame, swings, close_break=True)
        order_blocks = ob(frame, swings)
        liquidity_pools = liquidity(
            frame,
            swings,
            range_percent=float(self.p.range_percent),
        )
        zones = premium_discount(frame, swings)
        retracement_stats = retracements(frame, swings)
        previous_levels = self.instrument_api.indicator(None, "previous_high_low", time_frame="1D")
        session_state = self.instrument_api.indicator(
            None,
            "sessions",
            session=str(self.p.session_name),
        )

        structure_signal = structure_bias(
            latest_defined_value(structure, "BOS"),
            latest_defined_value(structure, "CHOCH"),
        )
        zone_value = zones["Zone"].iloc[-1] if not pd.isna(zones["Zone"].iloc[-1]) else 0
        order_block_value = latest_defined_value(order_blocks, "OB")
        order_block_signal = int(order_block_value) if order_block_value is not None else 0
        liquidity_value = latest_defined_value(liquidity_pools, "Swept")
        liquidity_swept = liquidity_value is not None
        retracement_depth = latest_value(retracement_stats, "CurrentRetracement%")
        session_active = bool(int(session_state["Active"].iloc[-1])) if not pd.isna(
            session_state["Active"].iloc[-1]
        ) else False
        if retracement_depth is None or not session_active:
            return
        if retracement_depth < float(self.p.retracement_threshold):
            return

        order_block_top = latest_defined_value(order_blocks, "Top")
        order_block_bottom = latest_defined_value(order_blocks, "Bottom")
        if order_block_top is None or order_block_bottom is None:
            order_block_top = float(frame["high"].iloc[-3:].max())
            order_block_bottom = float(frame["low"].iloc[-3:].min())
        order_block_width = max(order_block_top - order_block_bottom, self.instrument_spec.price_step)

        bullish = smc_bullish_confluence(
            structure_signal,
            int(zone_value),
            order_block_signal=order_block_signal if order_block_value is not None else None,
            liquidity_swept=liquidity_swept if liquidity_value is not None else None,
        )
        bearish = smc_bearish_confluence(
            structure_signal,
            int(zone_value),
            order_block_signal=order_block_signal if order_block_value is not None else None,
            liquidity_swept=liquidity_swept if liquidity_value is not None else None,
        )

        if bullish and is_discount(int(zone_value)):
            previous_high = latest_value(previous_levels, "PreviousHigh")
            if previous_high is None:
                return
            entry_price = self.round_price(order_block_bottom + (order_block_width * 0.25))
            stop_price = self.round_price(order_block_bottom - (order_block_width * 0.5))
            take_profit = self.round_price(previous_high)
            if take_profit <= entry_price or stop_price >= entry_price:
                return
            decision = self.size_entry(
                self.position_sizer,
                side="long",
                entry_price=entry_price,
                stop_price=stop_price,
            )
            if decision.accepted:
                self.submit_long_limit(
                    price=entry_price,
                    size=decision.final_size,
                    stop_loss=stop_price,
                    take_profit=take_profit,
                    sizing_decision=decision,
                )
                self._pending_entry_bar = len(self)
            return

        if bearish and is_premium(int(zone_value)):
            previous_low = latest_value(previous_levels, "PreviousLow")
            if previous_low is None:
                return
            entry_price = self.round_price(order_block_top - (order_block_width * 0.25))
            stop_price = self.round_price(order_block_top + (order_block_width * 0.5))
            take_profit = self.round_price(previous_low)
            if take_profit >= entry_price or stop_price <= entry_price:
                return
            decision = self.size_entry(
                self.position_sizer,
                side="short",
                entry_price=entry_price,
                stop_price=stop_price,
            )
            if decision.accepted:
                self.submit_short_limit(
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
