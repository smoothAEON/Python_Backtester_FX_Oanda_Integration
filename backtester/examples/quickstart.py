"""Minimal example strategy for quickstart and CLI documentation."""

from __future__ import annotations

import backtrader as bt


class QuickstartStrategy(bt.Strategy):
    """Enter immediately and close after a small fixed hold period."""

    params = (("exit_after_bars", 3),)

    def next(self) -> None:
        if not self.position:
            self.buy(size=1)
            return

        if len(self) >= int(self.p.exit_after_bars):
            self.close()
