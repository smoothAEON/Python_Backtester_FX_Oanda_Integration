"""Parameterized example strategy for optimization documentation."""

from __future__ import annotations

import backtrader as bt


class WindowStrategy(bt.Strategy):
    """Open and close once at fixed bar numbers."""

    params = (
        ("entry_bar", 2),
        ("exit_bar", 5),
    )

    def next(self) -> None:
        if len(self) == int(self.p.entry_bar) and not self.position:
            self.buy(size=1)
            return

        if len(self) == int(self.p.exit_bar) and self.position:
            self.close()
