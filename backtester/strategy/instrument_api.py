"""Master-owned instrument runtime and indicator API for strategies."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import numpy as np
import pandas as pd

from backtester.indicators.scipy_indicators import (
    rolling_linreg_slope,
    rolling_zscore,
)
from backtester.indicators.talib_indicators import adx, atr, bollinger_bands, ema, macd, rsi, sma

PriceSide = Literal["mid", "bid", "ask"]
IndicatorOutput = pd.Series | pd.DataFrame | dict[str, Any] | np.ndarray | float | int | None


@dataclass(slots=True, frozen=True)
class PriceBar:
    """Read-only OHLC snapshot for one timeframe and side."""

    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(slots=True, frozen=True)
class IndicatorRequest:
    """One built-in indicator request used by snapshot queries."""

    name: str
    params: dict[str, Any] | None = None
    source: str | None = None
    alias: str | None = None

    def __post_init__(self) -> None:
        normalized_name = str(self.name).strip()
        if not normalized_name:
            raise ValueError("IndicatorRequest.name must be a non-empty string")
        object.__setattr__(self, "name", normalized_name)

        if self.params is None:
            object.__setattr__(self, "params", {})
        elif not isinstance(self.params, dict):
            raise TypeError("IndicatorRequest.params must be a dict when provided")
        else:
            object.__setattr__(self, "params", dict(self.params))

        if self.source is not None:
            normalized_source = str(self.source).strip().lower()
            if not normalized_source:
                raise ValueError("IndicatorRequest.source must be non-empty when provided")
            object.__setattr__(self, "source", normalized_source)

        if self.alias is not None:
            normalized_alias = str(self.alias).strip()
            if not normalized_alias:
                raise ValueError("IndicatorRequest.alias must be non-empty when provided")
            object.__setattr__(self, "alias", normalized_alias)


class InstrumentRuntime:
    """Master-owned runtime for one strategy/instrument run.

    The runtime owns access to attached feeds, visible completed-bar history,
    and built-in indicator evaluation without lookahead.
    """

    _PRICE_SOURCE_COLUMNS = {"open", "high", "low", "close", "volume"}
    _UNSAFE_INDICATORS = frozenset(
        {
            "savgol_smooth",
            "swing_highs_lows",
            "bos_choch",
            "ob",
            "liquidity",
            "premium_discount",
            "retracements",
            "ict_fib",
        }
    )
    _PRICE_INDICATORS = {
        "sma": sma,
        "ema": ema,
        "rsi": rsi,
        "macd": macd,
        "bollinger_bands": bollinger_bands,
        "rolling_linreg_slope": rolling_linreg_slope,
        "rolling_zscore": rolling_zscore,
    }

    def __init__(
        self,
        *,
        strategy,
        feeds_by_timeframe: dict[str, Any],
        dataframes_by_timeframe: dict[str, pd.DataFrame],
        instrument: str | None,
        primary_timeframe: str | None,
    ) -> None:
        self._strategy = strategy
        self._feeds_by_timeframe = dict(feeds_by_timeframe)
        self._dataframes_by_timeframe = dict(dataframes_by_timeframe)
        self._instrument = instrument
        self._primary_timeframe = primary_timeframe
        self._memo_bar: int | None = None
        self._memo: dict[tuple[Any, ...], IndicatorOutput] = {}

    @property
    def instrument(self) -> str | None:
        return self._instrument

    @property
    def primary_timeframe(self) -> str | None:
        return self._primary_timeframe

    def available_timeframes(self) -> tuple[str, ...]:
        return tuple(self._feeds_by_timeframe)

    def ohlcv(
        self,
        timeframe: str | None,
        window: int | None = None,
    ) -> pd.DataFrame:
        active_timeframe = self._normalize_timeframe(timeframe)
        if window is not None and window <= 0:
            raise ValueError("window must be positive when provided")

        frame = self._visible_frame(active_timeframe)
        if window is not None:
            frame = frame.tail(window)
        return frame.copy()

    def price_bar(
        self,
        timeframe: str | None,
        side: PriceSide = "mid",
    ) -> PriceBar:
        active_timeframe = self._normalize_timeframe(timeframe)
        frame = self._visible_source_frame(active_timeframe)
        if frame.empty:
            raise RuntimeError(f"No completed bars are available yet for {active_timeframe}")

        if side == "mid":
            prefix = ""
        elif side in {"bid", "ask"}:
            prefix = f"{side}_"
        else:
            raise ValueError("side must be one of 'mid', 'bid', or 'ask'")

        latest = frame.iloc[-1]
        return PriceBar(
            open=float(latest[f"{prefix}open"]),
            high=float(latest[f"{prefix}high"]),
            low=float(latest[f"{prefix}low"]),
            close=float(latest[f"{prefix}close"]),
            volume=float(latest["volume"]),
        )

    def indicator(
        self,
        timeframe: str | None,
        name: str,
        *,
        source: str | None = None,
        **params: Any,
    ) -> IndicatorOutput:
        result = self._indicator_result(
            self._normalize_timeframe(timeframe),
            name,
            source,
            params,
        )
        return _clone_output(result)

    def snapshot(
        self,
        timeframe: str | None,
        indicators: list[IndicatorRequest],
    ) -> dict[str, Any]:
        active_timeframe = self._normalize_timeframe(timeframe)
        if not isinstance(indicators, list):
            raise TypeError("indicators must be a list of IndicatorRequest instances")

        snapshot: dict[str, Any] = {}
        for request in indicators:
            if not isinstance(request, IndicatorRequest):
                raise TypeError("snapshot indicators must be IndicatorRequest instances")
            key = request.alias or request.name
            result = self._indicator_result(
                active_timeframe,
                request.name,
                request.source,
                dict(request.params or {}),
            )
            snapshot[key] = _latest_indicator_value(result)
        return deepcopy(snapshot)

    def _indicator_result(
        self,
        timeframe: str,
        name: str,
        source: str | None,
        params: dict[str, Any],
    ) -> IndicatorOutput:
        self._reset_bar_local_memo()
        normalized_name = str(name).strip().lower()
        if not normalized_name:
            raise ValueError("indicator name must be a non-empty string")
        if normalized_name in self._UNSAFE_INDICATORS:
            raise ValueError(
                f"{normalized_name} is unavailable through instrument_api because it is "
                "unsafe/repainting in live-like backtests; use backtester.indicators.research "
                "directly for offline research only"
            )

        normalized_source = None
        if source is not None:
            normalized_source = str(source).strip().lower()
            if not normalized_source:
                raise ValueError("indicator source must be non-empty when provided")

        key = (
            "indicator",
            timeframe,
            normalized_name,
            normalized_source,
            _stable_value(dict(params)),
        )
        if key in self._memo:
            return self._memo[key]

        result = self._compute_indicator(
            timeframe=timeframe,
            name=normalized_name,
            source=normalized_source,
            params=dict(params),
        )
        self._memo[key] = result
        return result

    def _compute_indicator(
        self,
        *,
        timeframe: str,
        name: str,
        source: str | None,
        params: dict[str, Any],
    ) -> IndicatorOutput:
        if name in self._PRICE_INDICATORS:
            series = self._price_source_series(timeframe, source)
            return self._PRICE_INDICATORS[name](series, **params)

        frame = self.ohlcv(timeframe)
        if name == "atr":
            self._reject_source(name, source)
            return atr(frame["high"], frame["low"], frame["close"], **params)
        if name == "adx":
            self._reject_source(name, source)
            return adx(frame["high"], frame["low"], frame["close"], **params)

        if name == "previous_high_low":
            self._reject_source(name, source)
            return _smc_exports()["previous_high_low"](frame, **params)
        if name == "sessions":
            self._reject_source(name, source)
            return _smc_exports()["sessions"](frame, **params)
        if name == "confirmed_swings":
            self._reject_source(name, source)
            return _causal_smc_exports()["confirmed_swings"](frame, **params)
        if name == "confirmed_structure":
            self._reject_source(name, source)
            remaining, swing_params = self._split_swing_params(params)
            swings = _causal_smc_exports()["confirmed_swings"](frame, **swing_params)
            return _causal_smc_exports()["confirmed_structure"](frame, swings, **remaining)
        if name == "confirmed_order_blocks":
            self._reject_source(name, source)
            remaining, swing_params = self._split_swing_params(params)
            structure_params = self._pop_dict_param(remaining, "structure_params")
            swings = _causal_smc_exports()["confirmed_swings"](frame, **swing_params)
            structure = _causal_smc_exports()["confirmed_structure"](
                frame,
                swings,
                **structure_params,
            )
            return _causal_smc_exports()["confirmed_order_blocks"](frame, structure, **remaining)
        if name == "confirmed_liquidity":
            self._reject_source(name, source)
            remaining, swing_params = self._split_swing_params(params)
            swings = _causal_smc_exports()["confirmed_swings"](frame, **swing_params)
            return _causal_smc_exports()["confirmed_liquidity"](frame, swings, **remaining)
        if name == "confirmed_premium_discount":
            self._reject_source(name, source)
            remaining, swing_params = self._split_swing_params(params)
            swings = _causal_smc_exports()["confirmed_swings"](frame, **swing_params)
            return _causal_smc_exports()["confirmed_premium_discount"](frame, swings, **remaining)
        if name == "confirmed_retracements":
            self._reject_source(name, source)
            remaining, swing_params = self._split_swing_params(params)
            swings = _causal_smc_exports()["confirmed_swings"](frame, **swing_params)
            return _causal_smc_exports()["confirmed_retracements"](frame, swings, **remaining)

        raise ValueError(f"Unknown built-in indicator: {name!r}")

    def _split_swing_params(
        self,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        remaining = dict(params)
        swing_params: dict[str, Any] = {}
        raw_swing_params = remaining.pop("swing_params", None)
        if raw_swing_params is not None:
            if not isinstance(raw_swing_params, dict):
                raise TypeError("swing_params must be a dict when provided")
            swing_params.update(raw_swing_params)
        if "swing_length" in remaining:
            swing_params["swing_length"] = remaining.pop("swing_length")
        return remaining, swing_params

    def _price_source_series(
        self,
        timeframe: str,
        source: str | None,
    ) -> pd.Series:
        column = source or "close"
        if column not in self._PRICE_SOURCE_COLUMNS:
            supported = ", ".join(sorted(self._PRICE_SOURCE_COLUMNS))
            raise ValueError(
                f"Unsupported source column {column!r}. Expected one of {supported}"
            )
        frame = self.ohlcv(timeframe)
        return frame[column]

    def _visible_frame(self, timeframe: str) -> pd.DataFrame:
        return self._visible_source_frame(timeframe).loc[
            :,
            ["open", "high", "low", "close", "volume"],
        ]

    def _visible_source_frame(self, timeframe: str) -> pd.DataFrame:
        dataframe_source = self._dataframes_by_timeframe.get(timeframe)
        if dataframe_source is None:
            raise TypeError(
                f"Instrument runtime requires a DataFrame-backed feed for {timeframe}"
            )
        current_primary_bar_end = self._current_primary_bar_end()
        if "bar_end_time" in dataframe_source.columns:
            visible = dataframe_source.loc[
                dataframe_source["bar_end_time"] <= current_primary_bar_end
            ]
        else:
            visible = dataframe_source.loc[dataframe_source.index <= current_primary_bar_end]
        return visible.copy()

    def _current_primary_bar_end(self) -> pd.Timestamp:
        primary_timeframe = self._normalize_timeframe(None)
        primary_feed = self._feed(primary_timeframe)
        if len(primary_feed) <= 0:
            raise RuntimeError(f"No completed bars are available yet for {primary_timeframe}")
        timestamp = pd.Timestamp(primary_feed.datetime.datetime(0))
        if timestamp.tzinfo is None:
            return timestamp.tz_localize("UTC")
        return timestamp.tz_convert("UTC")

    def _feed(self, timeframe: str):
        feed = self._feeds_by_timeframe.get(timeframe)
        if feed is None:
            available = ", ".join(self.available_timeframes()) or "<none>"
            raise KeyError(
                f"Unknown timeframe {timeframe!r}. Available timeframes: {available}"
            )
        return feed

    def _normalize_timeframe(self, timeframe: str | None) -> str:
        if timeframe is None:
            if self._primary_timeframe is None:
                raise ValueError("No primary timeframe is attached to this runtime")
            return self._primary_timeframe

        normalized = str(timeframe).strip().upper()
        if not normalized:
            raise ValueError("timeframe must be a non-empty string")
        if normalized not in self._feeds_by_timeframe:
            available = ", ".join(self.available_timeframes()) or "<none>"
            raise KeyError(
                f"Unknown timeframe {timeframe!r}. Available timeframes: {available}"
            )
        return normalized

    def _reject_source(self, name: str, source: str | None) -> None:
        if source is not None:
            raise ValueError(f"{name} does not accept a source parameter")

    def _pop_dict_param(self, params: dict[str, Any], key: str) -> dict[str, Any]:
        raw_value = params.pop(key, None)
        if raw_value is None:
            return {}
        if not isinstance(raw_value, dict):
            raise TypeError(f"{key} must be a dict when provided")
        return dict(raw_value)

    def _reset_bar_local_memo(self) -> None:
        current_bar = len(self._strategy)
        if self._memo_bar != current_bar:
            self._memo_bar = current_bar
            self._memo.clear()


def _latest_indicator_value(value: IndicatorOutput) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Series):
        if value.empty:
            return None
        return value.iloc[-1]
    if isinstance(value, pd.DataFrame):
        if value.empty:
            return None
        return value.iloc[-1].to_dict()
    if isinstance(value, np.ndarray):
        if value.size == 0:
            return None
        return value[-1]
    if isinstance(value, (dict, list, tuple)):
        return deepcopy(value)
    return value


def _clone_output(value: IndicatorOutput) -> IndicatorOutput:
    if value is None:
        return None
    if isinstance(value, pd.DataFrame):
        return value.copy(deep=True)
    if isinstance(value, pd.Series):
        return value.copy(deep=True)
    if isinstance(value, np.ndarray):
        return value.copy()
    if isinstance(value, (dict, list, tuple)):
        return deepcopy(value)
    return value


def _stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _stable_value(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_stable_value(item) for item in value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.isoformat()
    return value


@lru_cache(maxsize=1)
def _smc_exports() -> dict[str, Any]:
    from backtester.indicators import (
        previous_high_low,
        sessions,
    )

    return {
        "previous_high_low": previous_high_low,
        "sessions": sessions,
    }


@lru_cache(maxsize=1)
def _causal_smc_exports() -> dict[str, Any]:
    from backtester.indicators import (
        confirmed_liquidity,
        confirmed_order_blocks,
        confirmed_premium_discount,
        confirmed_retracements,
        confirmed_structure,
        confirmed_swings,
    )

    return {
        "confirmed_liquidity": confirmed_liquidity,
        "confirmed_order_blocks": confirmed_order_blocks,
        "confirmed_premium_discount": confirmed_premium_discount,
        "confirmed_retracements": confirmed_retracements,
        "confirmed_structure": confirmed_structure,
        "confirmed_swings": confirmed_swings,
    }
