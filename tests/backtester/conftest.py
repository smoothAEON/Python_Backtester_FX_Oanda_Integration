from __future__ import annotations

import pandas as pd
import pytest


def _as_utc_timestamp(value, fallback_index: int) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp("2024-01-01T00:00:00Z") + pd.Timedelta(hours=fallback_index)
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


@pytest.fixture
def make_oanda_frame():
    def _make(candles: list[dict] | None = None) -> pd.DataFrame:
        rows: list[dict] = []
        source = candles or [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
            {"open": 100.5, "high": 101.5, "low": 100.0, "close": 101.0},
            {"open": 101.0, "high": 102.0, "low": 100.5, "close": 101.5},
        ]

        for index, candle in enumerate(source):
            item = dict(candle)
            spread = float(item.pop("spread", 0.2))
            half_spread = spread / 2.0
            open_price = float(item.pop("open", 100.0 + index))
            high_price = float(item.pop("high", open_price + 1.0))
            low_price = float(item.pop("low", open_price - 1.0))
            close_price = float(item.pop("close", open_price + 0.5))
            volume = int(item.pop("volume", 100 + index))
            row = {
                "time": _as_utc_timestamp(item.pop("time", None), index),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "bid_open": open_price - half_spread,
                "bid_high": high_price - half_spread,
                "bid_low": low_price - half_spread,
                "bid_close": close_price - half_spread,
                "ask_open": open_price + half_spread,
                "ask_high": high_price + half_spread,
                "ask_low": low_price + half_spread,
                "ask_close": close_price + half_spread,
            }
            row.update(item)
            rows.append(row)

        return pd.DataFrame(rows)

    return _make


@pytest.fixture
def write_oanda_csv(tmp_path):
    def _write(df: pd.DataFrame, name: str = "candles_XAU_USD_H1.csv"):
        path = tmp_path / name
        df.to_csv(path, index=False)
        return path

    return _write
