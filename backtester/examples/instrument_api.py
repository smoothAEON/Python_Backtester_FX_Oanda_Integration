"""Example ``BaseStrategy`` using the instrument API."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backtester.strategy import BaseStrategy, IndicatorRequest


class InstrumentApiStrategy(BaseStrategy):
    """Read indicator snapshots from ``instrument_api`` before trading."""

    params = (
        ("ema_period", 3),
        ("rsi_period", 2),
        ("exit_after_bars", 3),
    )

    latest_snapshot: dict[str, Any] = {}
    latest_bar_close: float | None = None

    def __init__(self) -> None:
        super().__init__()
        self._entry_bar: int | None = None
        self._latest_snapshot: dict[str, Any] = {}
        self._latest_bar_close: float | None = None

    def next(self) -> None:
        if self.has_open_order():
            return

        snapshot = self.indicator_snapshot(
            None,
            [
                IndicatorRequest("ema", params={"period": int(self.p.ema_period)}, alias="ema"),
                IndicatorRequest("rsi", params={"period": int(self.p.rsi_period)}, alias="rsi"),
            ],
        )
        bar = self.instrument_api.price_bar(None, side="mid")
        self._latest_snapshot = snapshot
        self._latest_bar_close = float(bar.close)

        ema_value = snapshot["ema"]
        if ema_value is None or pd.isna(ema_value):
            return

        if self.is_flat():
            self.submit_long_market(size=1)
            self._entry_bar = len(self)
            return

        if self._entry_bar is not None and len(self) - self._entry_bar >= int(self.p.exit_after_bars):
            self.close()

    def stop(self) -> None:
        type(self).latest_snapshot = dict(self._latest_snapshot)
        type(self).latest_bar_close = self._latest_bar_close
