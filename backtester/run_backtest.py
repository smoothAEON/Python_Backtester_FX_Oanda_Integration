"""Programmatic and CLI entry points for single-run backtests."""

from __future__ import annotations

import argparse
import ast
import importlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import backtrader as bt
import pandas as pd

from .config import BacktestConfig
from .core.cerebro_builder import build_cerebro
from .core.result import BacktestResult, build_backtest_result
from .data.loader import OANDADataLoader
from .data.oanda_feed import OANDABidAskData

_TIMEFRAME_SECONDS = {
    "S5": 5,
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D": 86400,
    "W": 604800,
}

DataSource = str | Path | pd.DataFrame


def run_backtest(
    strategy_class: type[bt.Strategy],
    instrument: str,
    timeframe: str,
    *,
    csv_path: str | None = None,
    dataframe: pd.DataFrame | None = None,
    context_data: dict[str, DataSource] | None = None,
    cash: float = 10_000.0,
    strategy_params: dict[str, Any] | None = None,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Run one strategy on one instrument and return a normalized result."""

    if (csv_path is None) == (dataframe is None):
        raise ValueError("Provide exactly one of csv_path or dataframe")

    primary_timeframe = _normalize_timeframe_label(timeframe)
    ordered_context_sources = _normalize_context_data(
        context_data,
        primary_timeframe=primary_timeframe,
    )
    active_config = replace(config, cash=cash) if config is not None else BacktestConfig(cash=cash)
    loader = OANDADataLoader(allow_dedupe=active_config.allow_dedupe)

    if csv_path is not None:
        normalized = loader.load_csv(csv_path)
    else:
        normalized = loader.load_dataframe(dataframe)

    feeds = [_build_data_feed(normalized, instrument=instrument, timeframe=primary_timeframe)]
    ordered_timeframes = [primary_timeframe]
    for context_timeframe, source in ordered_context_sources:
        context_frame = _load_source_dataframe(loader, source)
        feeds.append(
            _build_data_feed(
                context_frame,
                instrument=instrument,
                timeframe=context_timeframe,
            )
        )
        ordered_timeframes.append(context_timeframe)

    cerebro = build_cerebro(
        strategy_class,
        feeds,
        config=active_config,
        strategy_params=strategy_params,
    )

    strategies = cerebro.run(tradehistory=True)
    if not strategies:
        raise RuntimeError("Cerebro did not return any strategy instances")

    strategy = strategies[0]
    params = dict(strategy_params or {})
    return build_backtest_result(
        strategy,
        instrument=instrument,
        timeframe=primary_timeframe,
        timeframes=tuple(ordered_timeframes),
        parameters=params,
        config=active_config,
    )


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    strategy_class = _load_strategy_class(args.strategy_module, args.strategy_class)
    strategy_params = _parse_strategy_params(args.strategy_param)
    result = run_backtest(
        strategy_class=strategy_class,
        instrument=args.instrument,
        timeframe=args.timeframe,
        csv_path=args.csv_path,
        cash=args.cash,
        strategy_params=strategy_params,
    )

    print(f"strategy={result.strategy_name}")
    print(f"instrument={result.instrument}")
    print(f"timeframe={result.timeframe}")
    if len(result.timeframes) > 1:
        print(f"timeframes={','.join(result.timeframes)}")
    print(f"orders={len(result.order_ledger)}")
    print(f"trades={len(result.trade_ledger)}")
    print(f"end_value={result.end_value:.6f}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one backtest")
    parser.add_argument("--csv-path", required=True, help="Path to an extractor-native CSV file")
    parser.add_argument("--instrument", required=True, help="Instrument name, e.g. XAU_USD")
    parser.add_argument("--timeframe", required=True, help="Timeframe label, e.g. H1")
    parser.add_argument("--strategy-module", required=True, help="Import path for the strategy module")
    parser.add_argument("--strategy-class", required=True, help="Strategy class name within the module")
    parser.add_argument("--cash", type=float, default=10_000.0, help="Starting cash")
    parser.add_argument(
        "--strategy-param",
        action="append",
        default=[],
        help="Strategy parameter in key=value form. May be provided multiple times.",
    )
    return parser


def _load_strategy_class(module_name: str, class_name: str) -> type[bt.Strategy]:
    module = importlib.import_module(module_name)
    strategy_class = getattr(module, class_name)
    if not isinstance(strategy_class, type) or not issubclass(strategy_class, bt.Strategy):
        raise TypeError(f"{module_name}.{class_name} is not a backtrader Strategy class")
    return strategy_class


def _parse_strategy_params(entries: list[str]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"Invalid strategy parameter: {entry!r}")
        key, raw_value = entry.split("=", 1)
        params[key] = ast.literal_eval(raw_value)
    return params


def _build_data_feed(
    dataframe: pd.DataFrame,
    *,
    instrument: str,
    timeframe: str,
) -> OANDABidAskData:
    data_feed = OANDABidAskData(dataname=dataframe, name=f"{instrument}_{timeframe}")
    data_feed._phase_instrument = instrument
    data_feed._phase_timeframe = timeframe
    return data_feed


def _load_source_dataframe(loader: OANDADataLoader, source: DataSource) -> pd.DataFrame:
    if isinstance(source, pd.DataFrame):
        return loader.load_dataframe(source)
    if isinstance(source, (str, Path)):
        return loader.load_csv(str(source))
    raise TypeError("context_data values must be CSV paths or pandas DataFrames")


def _normalize_timeframe_label(timeframe: str) -> str:
    normalized = str(timeframe).strip().upper()
    if normalized not in _TIMEFRAME_SECONDS:
        supported = ", ".join(_TIMEFRAME_SECONDS)
        raise ValueError(
            f"Invalid timeframe: {timeframe!r}. Must be one of {supported}"
        )
    return normalized


def _normalize_context_data(
    context_data: dict[str, DataSource] | None,
    *,
    primary_timeframe: str,
) -> list[tuple[str, DataSource]]:
    if context_data is None:
        return []
    if not isinstance(context_data, dict):
        raise TypeError("context_data must be a dict keyed by timeframe")

    primary_seconds = _TIMEFRAME_SECONDS[primary_timeframe]
    normalized: dict[str, DataSource] = {}
    for raw_timeframe, source in context_data.items():
        timeframe = _normalize_timeframe_label(raw_timeframe)
        if timeframe == primary_timeframe:
            raise ValueError("context_data must not repeat the primary timeframe")
        if _TIMEFRAME_SECONDS[timeframe] <= primary_seconds:
            raise ValueError(
                "context_data timeframes must be strictly higher than the primary timeframe"
            )
        if timeframe in normalized:
            raise ValueError(f"Duplicate context timeframe after normalization: {timeframe}")
        if not isinstance(source, (str, Path, pd.DataFrame)):
            raise TypeError("context_data values must be CSV paths or pandas DataFrames")
        normalized[timeframe] = source

    return sorted(normalized.items(), key=lambda item: _TIMEFRAME_SECONDS[item[0]])


if __name__ == "__main__":
    raise SystemExit(main())
