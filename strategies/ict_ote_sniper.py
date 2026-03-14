"""ICT OTE showcase strategy using frozen fib state and limit entries."""

from __future__ import annotations

import pandas as pd

from backtester.indicators import ICTFibEngine, bos_choch, premium_discount, swing_highs_lows
from backtester.sizing import RiskPercentSizer
from backtester.strategy import is_discount, is_premium, structure_bias

from ._shared import ShowcaseStrategy, latest_defined_value, latest_value, tail_is_ready


class IctOteSniperStrategy(ShowcaseStrategy):
    """Trade one pullback attempt per frozen ICT fib signature."""

    params = (
        ("swing_length", 1),
        ("atr_period", 3),
        ("atr_multiplier", 0.5),
        ("risk_percent", 0.003),
        ("ote_level", "mid"),
        ("stop_atr_buffer", 0.5),
        ("stale_bars", 4),
    )

    def __init__(self) -> None:
        super().__init__()
        self.position_sizer = RiskPercentSizer(float(self.p.risk_percent))
        self.fib_engine = ICTFibEngine(
            swing_length=int(self.p.swing_length),
            atr_period=int(self.p.atr_period),
            atr_multiplier=float(self.p.atr_multiplier),
        )
        self._submitted_signatures: set[tuple] = set()
        self._pending_entry_bar: int | None = None

    def next(self) -> None:
        if self._cancel_stale_entry():
            return
        if self.has_open_order() or not self.is_flat():
            return

        frame = self.to_ohlcv_dataframe()
        if len(frame) < 5:
            return

        fib = self.fib_engine.update(frame)
        signature = self.fib_engine.last_fib_signature
        if fib is None or signature is None or signature in self._submitted_signatures:
            return

        atr_values = self.indicator(None, "atr", period=int(self.p.atr_period))
        if not tail_is_ready(atr_values, 1):
            return
        atr_now = latest_value(atr_values)
        if atr_now is None:
            return

        swings = swing_highs_lows(frame, swing_length=int(self.p.swing_length))
        structure = bos_choch(frame, swings, close_break=True)
        zones = premium_discount(frame, swings)
        structure_signal = structure_bias(
            latest_defined_value(structure, "BOS"),
            latest_defined_value(structure, "CHOCH"),
        )
        zone_value = zones["Zone"].iloc[-1] if not pd.isna(zones["Zone"].iloc[-1]) else 0
        if str(self.p.ote_level) == "upper":
            entry_key = "upper"
        elif str(self.p.ote_level) == "lower":
            entry_key = "lower"
        else:
            entry_key = "mid"

        entry_price = self.round_price(float(fib["ote_zone"][entry_key]))
        take_profit = self.round_price(float(fib["levels"]["1.0"]))
        stop_buffer = atr_now * float(self.p.stop_atr_buffer)

        if fib["direction"] == "up" and structure_signal >= 0 and is_discount(int(zone_value)):
            stop_price = self.round_price(float(fib["ote_zone"]["lower"]) - stop_buffer)
            if stop_price >= entry_price or self.mid.close < entry_price or take_profit <= entry_price:
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
                self._submitted_signatures.add(signature)
                self._pending_entry_bar = len(self)
            return

        if fib["direction"] == "down" and structure_signal <= 0 and is_premium(int(zone_value)):
            stop_price = self.round_price(float(fib["ote_zone"]["upper"]) + stop_buffer)
            if stop_price <= entry_price or self.mid.close > entry_price or take_profit >= entry_price:
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
                self._submitted_signatures.add(signature)
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
