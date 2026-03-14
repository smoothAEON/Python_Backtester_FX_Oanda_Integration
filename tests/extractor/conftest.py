from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest


EXTRACTOR_DIR = Path(__file__).resolve().parents[2] / "oanda-candle-extractor"
if str(EXTRACTOR_DIR) not in sys.path:
    sys.path.insert(0, str(EXTRACTOR_DIR))


@pytest.fixture
def make_candle_frame():
    def _make(
        start: datetime,
        periods: int,
        step_seconds: int,
        base_price: float = 1.1000,
    ) -> pd.DataFrame:
        rows = []
        for index in range(periods):
            time_value = start + timedelta(seconds=step_seconds * index)
            mid_open = base_price + index * 0.001
            rows.append(
                {
                    "time": pd.Timestamp(time_value),
                    "open": mid_open,
                    "high": mid_open + 0.0005,
                    "low": mid_open - 0.0005,
                    "close": mid_open + 0.0002,
                    "bid_open": mid_open - 0.0001,
                    "bid_high": mid_open + 0.0004,
                    "bid_low": mid_open - 0.0006,
                    "bid_close": mid_open + 0.0001,
                    "ask_open": mid_open + 0.0001,
                    "ask_high": mid_open + 0.0006,
                    "ask_low": mid_open - 0.0004,
                    "ask_close": mid_open + 0.0003,
                    "volume": 100 + index,
                }
            )
        return pd.DataFrame(rows)

    return _make
