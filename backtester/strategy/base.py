"""Shared strategy helpers for single-instrument backtests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import backtrader as bt
import pandas as pd

from backtester.sizing.base import SizingDecision
from .instrument_api import IndicatorRequest, InstrumentRuntime, PriceBar


@dataclass(slots=True, frozen=True)
class _ProtectionSpec:
    is_long: bool
    stop_loss: float | None
    take_profit: float | None


_FINAL_ORDER_STATUSES = {
    bt.Order.Completed,
    bt.Order.Canceled,
    bt.Order.Rejected,
    bt.Order.Expired,
    bt.Order.Margin,
}


class BaseStrategy(bt.Strategy):
    """Add one-thesis order helpers on top of ``bt.Strategy``.

    Strategies that override ``__init__`` or ``notify_order`` should call ``super()``.
    """

    params = ()

    def __init__(self) -> None:
        super().__init__()
        self.order_history: list[dict[str, Any]] = []
        self._tracked_orders: dict[int, bt.Order] = {}
        self._active_entry_ref: int | None = None
        self._pending_protection_specs: dict[int, _ProtectionSpec] = {}
        self._protective_order_refs: set[int] = set()
        self._feeds_by_timeframe = self._build_timeframe_feed_map()
        self._dataframes_by_timeframe = self._extract_source_dataframes()
        self._instrument_name, self._timeframe_name = self._extract_primary_feed_identity()
        self._instrument_runtime = InstrumentRuntime(
            strategy=self,
            feeds_by_timeframe=self._feeds_by_timeframe,
            dataframes_by_timeframe=self._dataframes_by_timeframe,
            instrument=self._instrument_name,
            primary_timeframe=self._timeframe_name,
        )

    @property
    def instrument_api(self) -> InstrumentRuntime:
        return self._instrument_runtime

    @property
    def mid(self) -> PriceBar:
        return self.mid_for(self.timeframe)

    @property
    def bid(self) -> PriceBar:
        return self.bid_for(self.timeframe)

    @property
    def ask(self) -> PriceBar:
        return self.ask_for(self.timeframe)

    @property
    def spread(self) -> float:
        return self.ask.close - self.bid.close

    @property
    def instrument(self) -> str | None:
        return self._instrument_name

    @property
    def timeframe(self) -> str | None:
        return self._timeframe_name

    @property
    def available_timeframes(self) -> tuple[str, ...]:
        return self.instrument_api.available_timeframes()

    def current_equity(self) -> float:
        return float(self.broker.getvalue())

    def is_flat(self) -> bool:
        return float(self.position.size) == 0.0

    def is_long(self) -> bool:
        return float(self.position.size) > 0.0

    def is_short(self) -> bool:
        return float(self.position.size) < 0.0

    def has_open_order(self) -> bool:
        return any(order.alive() for order in self._tracked_orders.values())

    def cancel_open_orders(self) -> None:
        for order in list(self._tracked_orders.values()):
            if order.alive():
                self.cancel(order)

    def submit_long_market(
        self,
        size: float,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        sizing_decision: SizingDecision | None = None,
    ) -> bt.Order:
        return self._submit_entry(
            is_long=True,
            size=size,
            exectype=bt.Order.Market,
            stop_loss=stop_loss,
            take_profit=take_profit,
            sizing_decision=sizing_decision,
        )

    def submit_long_limit(
        self,
        price: float,
        size: float,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        sizing_decision: SizingDecision | None = None,
    ) -> bt.Order:
        return self._submit_entry(
            is_long=True,
            size=size,
            exectype=bt.Order.Limit,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            sizing_decision=sizing_decision,
        )

    def submit_long_stop(
        self,
        price: float,
        size: float,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        sizing_decision: SizingDecision | None = None,
    ) -> bt.Order:
        return self._submit_entry(
            is_long=True,
            size=size,
            exectype=bt.Order.Stop,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            sizing_decision=sizing_decision,
        )

    def submit_short_market(
        self,
        size: float,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        sizing_decision: SizingDecision | None = None,
    ) -> bt.Order:
        return self._submit_entry(
            is_long=False,
            size=size,
            exectype=bt.Order.Market,
            stop_loss=stop_loss,
            take_profit=take_profit,
            sizing_decision=sizing_decision,
        )

    def submit_short_limit(
        self,
        price: float,
        size: float,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        sizing_decision: SizingDecision | None = None,
    ) -> bt.Order:
        return self._submit_entry(
            is_long=False,
            size=size,
            exectype=bt.Order.Limit,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            sizing_decision=sizing_decision,
        )

    def submit_short_stop(
        self,
        price: float,
        size: float,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        sizing_decision: SizingDecision | None = None,
    ) -> bt.Order:
        return self._submit_entry(
            is_long=False,
            size=size,
            exectype=bt.Order.Stop,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            sizing_decision=sizing_decision,
        )

    def has_all_timeframes_ready(self) -> bool:
        return all(len(feed) > 0 for feed in self._feeds_by_timeframe.values())

    def data_for_timeframe(self, timeframe: str | None):
        if timeframe is None:
            return self.data0

        normalized = self._normalize_timeframe_key(timeframe)
        feed = self._feeds_by_timeframe.get(normalized)
        if feed is None:
            available = ", ".join(self.available_timeframes) or "<none>"
            raise KeyError(
                f"Unknown timeframe {timeframe!r}. Available timeframes: {available}"
            )
        return feed

    def mid_for(self, timeframe: str | None) -> PriceBar:
        return self.instrument_api.price_bar(timeframe, side="mid")

    def bid_for(self, timeframe: str | None) -> PriceBar:
        return self.instrument_api.price_bar(timeframe, side="bid")

    def ask_for(self, timeframe: str | None) -> PriceBar:
        return self.instrument_api.price_bar(timeframe, side="ask")

    def to_ohlcv_dataframe(
        self,
        timeframe: str | None = None,
        window: int | None = None,
    ) -> pd.DataFrame:
        """Return the loaded mid-price OHLCV history up to the current bar."""

        return self.instrument_api.ohlcv(timeframe, window=window)

    def indicator(
        self,
        timeframe: str | None,
        name: str,
        *,
        source: str | None = None,
        **params: Any,
    ):
        return self.instrument_api.indicator(
            timeframe,
            name,
            source=source,
            **params,
        )

    def indicator_snapshot(
        self,
        timeframe: str | None,
        indicators: list[IndicatorRequest],
    ) -> dict[str, Any]:
        return self.instrument_api.snapshot(timeframe, indicators)

    def notify_order(self, order: bt.Order) -> None:
        self._tracked_orders.setdefault(order.ref, order)
        thesis_ref = order.info.get("thesis_ref")
        self.order_history.append(
            {
                "bar": len(self),
                "ref": int(order.ref),
                "status": int(order.status),
                "status_name": order.getstatusname(),
                "role": order.info.get("role"),
                "parent_ref": int(thesis_ref)
                if order.info.get("role") != "entry" and thesis_ref is not None
                else None,
                "thesis_ref": int(thesis_ref) if thesis_ref is not None else None,
                "is_buy": bool(order.isbuy()),
                "size": float(order.size),
                "executed_size": float(order.executed.size),
                "executed_price": float(order.executed.price),
                "sizing_method": order.info.get("sizing_method"),
                "sizing_raw_size": order.info.get("sizing_raw_size"),
                "sizing_final_size": order.info.get("sizing_final_size"),
                "sizing_equity": order.info.get("sizing_equity"),
                "sizing_stop_price": order.info.get("sizing_stop_price"),
                "sizing_stop_distance": order.info.get("sizing_stop_distance"),
                "sizing_reason": order.info.get("sizing_reason"),
                "sizing_details": order.info.get("sizing_details"),
            }
        )

        if order.status == bt.Order.Completed and order.info.get("role") == "entry":
            self._activate_protective_orders(order)

        if order.status in _FINAL_ORDER_STATUSES:
            if order.ref == self._active_entry_ref and order.status != bt.Order.Completed:
                self._pending_protection_specs.pop(order.ref, None)
            self._cleanup_resolved_thesis()

    def _build_timeframe_feed_map(self) -> dict[str, Any]:
        feeds: dict[str, Any] = {}
        for feed in self.datas:
            timeframe = getattr(feed, "_phase_timeframe", None)
            if isinstance(timeframe, str) and timeframe:
                feeds[timeframe] = feed
        if feeds:
            return feeds

        primary_timeframe = self._extract_timeframe_from_name(self.data0)
        if primary_timeframe is None:
            return {}
        return {primary_timeframe: self.data0}

    def _extract_source_dataframes(self) -> dict[str, pd.DataFrame]:
        sources: dict[str, pd.DataFrame] = {}
        for timeframe, feed in self._feeds_by_timeframe.items():
            dataname = getattr(getattr(feed, "p", None), "dataname", None)
            if isinstance(dataname, pd.DataFrame):
                sources[timeframe] = dataname
        return sources

    def _extract_primary_feed_identity(self) -> tuple[str | None, str | None]:
        instrument = getattr(self.data0, "_phase_instrument", None)
        timeframe = getattr(self.data0, "_phase_timeframe", None)
        if instrument is not None or timeframe is not None:
            return instrument, timeframe

        feed_name = getattr(self.data0, "_name", None)
        if isinstance(feed_name, str) and "_" in feed_name:
            instrument_name, timeframe_name = feed_name.rsplit("_", 1)
            return instrument_name or None, timeframe_name or None
        return None, self._extract_timeframe_from_name(self.data0)

    def _submit_entry(
        self,
        *,
        is_long: bool,
        size: float,
        exectype: bt.Order.ExecType,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        sizing_decision: SizingDecision | None = None,
    ) -> bt.Order:
        self._assert_can_open_new_entry()
        if size <= 0:
            raise ValueError("size must be positive")
        if price is not None and price <= 0:
            raise ValueError("price must be positive")

        submitter = self.buy if is_long else self.sell
        kwargs: dict[str, Any] = {"data": self.data0, "size": size, "exectype": exectype}
        if price is not None:
            kwargs["price"] = price
        order = submitter(**kwargs)
        order.addinfo(
            role="entry",
            thesis_ref=order.ref,
            thesis_side="long" if is_long else "short",
        )
        if sizing_decision is not None:
            order.addinfo(**self._sizing_info(sizing_decision))

        self._tracked_orders[order.ref] = order
        self._active_entry_ref = order.ref
        if stop_loss is not None or take_profit is not None:
            self._pending_protection_specs[order.ref] = _ProtectionSpec(
                is_long=is_long,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
        return order

    def _assert_can_open_new_entry(self) -> None:
        if self._active_entry_ref is not None or self.has_open_order() or not self.is_flat():
            raise RuntimeError(
                "BaseStrategy supports only one active entry thesis at a time"
            )

    def _activate_protective_orders(self, order: bt.Order) -> None:
        spec = self._pending_protection_specs.pop(order.ref, None)
        if spec is None:
            return

        filled_size = abs(float(order.executed.size or order.size))
        oco_order: bt.Order | None = None
        if spec.stop_loss is not None:
            oco_order = self._submit_protective_order(
                is_long_entry=spec.is_long,
                thesis_ref=order.ref,
                role="stop_loss",
                size=filled_size,
                price=spec.stop_loss,
                exectype=bt.Order.Stop,
            )
        if spec.take_profit is not None:
            self._submit_protective_order(
                is_long_entry=spec.is_long,
                thesis_ref=order.ref,
                role="take_profit",
                size=filled_size,
                price=spec.take_profit,
                exectype=bt.Order.Limit,
                oco=oco_order,
            )

    def _submit_protective_order(
        self,
        *,
        is_long_entry: bool,
        thesis_ref: int,
        role: str,
        size: float,
        price: float,
        exectype: bt.Order.ExecType,
        oco: bt.Order | None = None,
    ) -> bt.Order:
        submitter = self.sell if is_long_entry else self.buy
        order = submitter(
            data=self.data0,
            size=size,
            price=price,
            exectype=exectype,
            oco=oco,
        )
        order.addinfo(role=role, thesis_ref=thesis_ref)
        self._tracked_orders[order.ref] = order
        self._protective_order_refs.add(order.ref)
        return order

    def _sizing_info(self, decision: SizingDecision) -> dict[str, Any]:
        return {
            "sizing_method": decision.method,
            "sizing_raw_size": float(decision.raw_size),
            "sizing_final_size": float(decision.final_size),
            "sizing_equity": float(decision.equity),
            "sizing_stop_price": float(decision.stop_price)
            if decision.stop_price is not None
            else None,
            "sizing_stop_distance": float(decision.stop_distance)
            if decision.stop_distance is not None
            else None,
            "sizing_reason": decision.reason,
            "sizing_details": dict(decision.details),
        }

    def _cleanup_resolved_thesis(self) -> None:
        stale_refs = [
            ref
            for ref, order in self._tracked_orders.items()
            if order.status in _FINAL_ORDER_STATUSES
        ]
        for ref in stale_refs:
            if ref != self._active_entry_ref:
                self._tracked_orders.pop(ref, None)
                self._protective_order_refs.discard(ref)

        if self.has_open_order() or not self.is_flat():
            return

        self._tracked_orders.clear()
        self._pending_protection_specs.clear()
        self._protective_order_refs.clear()
        self._active_entry_ref = None

    def _extract_timeframe_from_name(self, feed) -> str | None:
        feed_name = getattr(feed, "_name", None)
        if isinstance(feed_name, str) and "_" in feed_name:
            _, timeframe_name = feed_name.rsplit("_", 1)
            return timeframe_name or None
        return None

    def _normalize_timeframe_key(self, timeframe: str) -> str:
        normalized = str(timeframe).strip().upper()
        if not normalized:
            raise ValueError("timeframe must be a non-empty string")
        return normalized
