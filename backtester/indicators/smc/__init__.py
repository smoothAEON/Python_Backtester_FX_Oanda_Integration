"""SMC indicators backed by the ``smartmoneyconcepts`` package.

All indicators except ICTFibEngine (FIBOTE) and premium_discount
delegate to ``smartmoneyconcepts.smc``.

Source: https://github.com/joshyattridge/smart-money-concepts
"""

from smartmoneyconcepts import smc as _smc

from .ict_fib import ICTFibEngine
from .premium_discount import premium_discount

# ---------------------------------------------------------------------------
# Thin wrappers around upstream ``smc.*`` functions
# ---------------------------------------------------------------------------


def swing_highs_lows(ohlc, swing_length=50):
    """Upstream swing-high / swing-low detection."""
    return _smc.swing_highs_lows(ohlc, swing_length=swing_length)


def bos_choch(ohlc, swing_highs_lows_df, close_break=True):
    """Upstream BOS / CHoCH detection."""
    return _smc.bos_choch(ohlc, swing_highs_lows_df, close_break=close_break)


def ob(ohlcv, swing_highs_lows_df, close_mitigation=False):
    """Upstream order-block detection."""
    return _smc.ob(ohlcv, swing_highs_lows_df, close_mitigation=close_mitigation)


def liquidity(ohlc, swing_highs_lows_df, range_percent=0.01):
    """Upstream liquidity-pool detection."""
    return _smc.liquidity(ohlc, swing_highs_lows_df, range_percent=range_percent)



def previous_high_low(ohlc, time_frame="1D"):
    """Upstream previous-high / previous-low levels."""
    return _smc.previous_high_low(ohlc, time_frame=time_frame)


def sessions(ohlc, session, start_time="", end_time="", time_zone="UTC"):
    """Upstream session detection."""
    return _smc.sessions(ohlc, session, start_time=start_time, end_time=end_time, time_zone=time_zone)


def retracements(ohlc, swing_highs_lows_df):
    """Upstream retracement metrics."""
    return _smc.retracements(ohlc, swing_highs_lows_df)


__all__ = [
    "ICTFibEngine",
    "bos_choch",

    "liquidity",
    "ob",
    "premium_discount",
    "previous_high_low",
    "retracements",
    "sessions",
    "swing_highs_lows",
]
