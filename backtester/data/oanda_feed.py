"""Custom backtrader feed for extractor-native OANDA candles."""

from __future__ import annotations

import backtrader as bt


class OANDABidAskData(bt.feeds.PandasData):
    """Expose mid OHLC as standard lines and bid/ask OHLC as extra lines."""

    lines = (
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
    )

    params = (
        ("datetime", None),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", -1),
        ("bid_open", "bid_open"),
        ("bid_high", "bid_high"),
        ("bid_low", "bid_low"),
        ("bid_close", "bid_close"),
        ("ask_open", "ask_open"),
        ("ask_high", "ask_high"),
        ("ask_low", "ask_low"),
        ("ask_close", "ask_close"),
    )
