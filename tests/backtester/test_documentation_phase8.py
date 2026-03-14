from __future__ import annotations

from pathlib import Path

import backtrader as bt

from backtester.run_backtest import run_backtest


REAL_EXTRACTOR_CSV = (
    Path(__file__).resolve().parents[2]
    / "oanda-candle-extractor"
    / "data"
    / "EUR_USD"
    / "candles_EUR_USD_D.csv"
)


class ReadmeQuickstartStrategy(bt.Strategy):
    def next(self):
        if not self.position:
            self.buy(size=1)
        elif len(self) >= 3 and self.position:
            self.close()


def test_phase8_readme_quickstart_runs_with_checked_in_csv():
    result = run_backtest(
        ReadmeQuickstartStrategy,
        instrument="EUR_USD",
        timeframe="D",
        csv_path=str(REAL_EXTRACTOR_CSV),
    )

    assert result.strategy_name == "ReadmeQuickstartStrategy"
    assert result.instrument == "EUR_USD"
    assert result.timeframe == "D"
    assert result.timeframes == ("D",)
    assert not result.order_ledger.empty
    assert not result.trade_ledger.empty
