"""Bid/ask-aware broker behavior for backtests."""

from __future__ import annotations

from dataclasses import dataclass

from backtrader.brokers.bbroker import BackBroker
from backtrader.order import Order

from backtester.config import ExecutionConfig


@dataclass(slots=True, frozen=True)
class PriceWindow:
    """One side of the candle used for order execution."""

    side: str
    open: float
    high: float
    low: float
    close: float


class ExecutionModel:
    """Select the price side used for order triggering and fills."""

    def __init__(self, config: ExecutionConfig | None = None) -> None:
        self.config = config or ExecutionConfig()
        if self.config.same_bar_policy != "worst_case_first":
            raise ValueError(
                f"Unsupported same-bar policy: {self.config.same_bar_policy!r}"
            )

    def side_for_order(self, order: Order) -> str:
        return "ask" if order.isbuy() else "bid"

    def annotate_order(self, order: Order) -> str:
        side = self.side_for_order(order)
        order.info["execution_side"] = side
        order.info["trigger_side"] = side
        order.info["same_bar_policy"] = self.config.same_bar_policy
        return side

    def price_window(self, data, order: Order) -> PriceWindow:
        side = self.annotate_order(order)
        prefix = f"{side}_"
        return PriceWindow(
            side=side,
            open=float(getattr(data, f"{prefix}open")[0]),
            high=float(getattr(data, f"{prefix}high")[0]),
            low=float(getattr(data, f"{prefix}low")[0]),
            close=float(getattr(data, f"{prefix}close")[0]),
        )


class BidAskBroker(BackBroker):
    """BackBroker variant that evaluates buy orders on ask candles and sell orders on bid candles."""

    params = (("execution_model", None),)

    def __init__(self):
        super().__init__()
        self.execution_model = self.p.execution_model or ExecutionModel()

    def buy(
        self,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        parent=None,
        transmit=True,
        histnotify=False,
        _checksubmit=True,
        **kwargs,
    ):
        kwargs = dict(kwargs)
        kwargs.setdefault("execution_side", "ask")
        kwargs.setdefault("trigger_side", "ask")
        kwargs.setdefault("same_bar_policy", self.execution_model.config.same_bar_policy)
        return super().buy(
            owner,
            data,
            size,
            price=price,
            plimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            histnotify=histnotify,
            _checksubmit=_checksubmit,
            **kwargs,
        )

    def sell(
        self,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        parent=None,
        transmit=True,
        histnotify=False,
        _checksubmit=True,
        **kwargs,
    ):
        kwargs = dict(kwargs)
        kwargs.setdefault("execution_side", "bid")
        kwargs.setdefault("trigger_side", "bid")
        kwargs.setdefault("same_bar_policy", self.execution_model.config.same_bar_policy)
        return super().sell(
            owner,
            data,
            size,
            price=price,
            plimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            histnotify=histnotify,
            _checksubmit=_checksubmit,
            **kwargs,
        )

    def _try_exec(self, order):
        data = order.data
        prices = self.execution_model.price_window(data, order)
        pcreated = order.created.price
        plimit = order.created.pricelimit

        if order.exectype == Order.Market:
            self._try_exec_market(order, prices.open, prices.high, prices.low)
        elif order.exectype == Order.Close:
            self._try_exec_close(order, prices.close)
        elif order.exectype == Order.Limit:
            self._try_exec_limit(order, prices.open, prices.high, prices.low, pcreated)
        elif order.triggered and order.exectype in [Order.StopLimit, Order.StopTrailLimit]:
            self._try_exec_limit(order, prices.open, prices.high, prices.low, plimit)
        elif order.exectype in [Order.Stop, Order.StopTrail]:
            self._try_exec_stop(
                order,
                prices.open,
                prices.high,
                prices.low,
                pcreated,
                prices.close,
            )
        elif order.exectype in [Order.StopLimit, Order.StopTrailLimit]:
            self._try_exec_stoplimit(
                order,
                prices.open,
                prices.high,
                prices.low,
                prices.close,
                pcreated,
                plimit,
            )
        elif order.exectype == Order.Historical:
            self._try_exec_historical(order)

    def next(self):
        while self._toactivate:
            self._toactivate.popleft().activate()

        if self.p.checksubmit:
            self.check_submitted()

        credit = 0.0
        for data, pos in self.positions.items():
            if pos:
                comminfo = self.getcommissioninfo(data)
                dt0 = data.datetime.datetime()
                dcredit = comminfo.get_credit_interest(data, pos, dt0)
                self.d_credit[data] += dcredit
                credit += dcredit
                pos.datetime = dt0

        self.cash -= credit
        self._process_order_history()

        self.pending.append(None)
        while True:
            order = self.pending.popleft()
            if order is None:
                break

            if order.expire():
                self.notify(order)
                self._ococheck(order)
                self._bracketize(order, cancel=True)
            elif not order.active():
                self.pending.append(order)
            else:
                self._try_exec(order)
                if order.alive():
                    self.pending.append(order)
                elif order.status == Order.Completed:
                    self._handle_completed_order(order)

        for data, pos in self.positions.items():
            if pos:
                comminfo = self.getcommissioninfo(data)
                self.cash += comminfo.cashadjust(pos.size, pos.adjbase, data.close[0])
                pos.adjbase = data.close[0]

        self._get_value()

    def _handle_completed_order(self, order: Order) -> None:
        oref = order.ref
        pref = getattr(order.parent, "ref", oref)
        if oref != pref:
            self._bracketize(order)
            return

        children = self._pchildren.get(pref)
        if not children:
            return

        if children and children[0] is order:
            children.popleft()
        elif order in children:
            children.remove(order)

        for child in children:
            child.activate()

    def _get_value(self, datas=None, lever=False):
        """Value futures-like positions from entry-basis margin plus marked cash.

        Backtrader's default futures-style path adds unrealized P&L on top of cash
        that has already been mark-to-market adjusted each bar. That double-counts
        open P&L for our leveraged FX model. Preserve the stock-like path unchanged
        and value non-stocklike positions from entry-basis margin collateral instead.
        """

        pos_value = 0.0
        pos_value_unlever = 0.0
        unrealized = 0.0

        while self._cash_addition:
            addition = self._cash_addition.popleft()
            self._fundshares += addition / self._fundval
            self.cash += addition

        for data in datas or self.positions:
            comminfo = self.getcommissioninfo(data)
            position = self.positions[data]
            current_price = data.close[0]
            entry_price = position.price or current_price

            if comminfo.stocklike:
                if not self.p.shortcash:
                    dvalue = comminfo.getvalue(position, current_price)
                else:
                    dvalue = comminfo.getvaluesize(position.size, current_price)
            else:
                dvalue = abs(position.size) * comminfo.get_margin(entry_price)

            dunrealized = comminfo.profitandloss(position.size, position.price, current_price)
            if datas and len(datas) == 1:
                if lever and dvalue > 0:
                    if comminfo.stocklike:
                        dvalue -= dunrealized
                        return (dvalue / comminfo.get_leverage()) + dunrealized
                    return dvalue / comminfo.get_leverage()
                return dvalue if comminfo.stocklike else dvalue / comminfo.get_leverage()

            if comminfo.stocklike and not self.p.shortcash:
                dvalue = abs(dvalue)

            pos_value += dvalue
            unrealized += dunrealized

            if dvalue > 0:
                if comminfo.stocklike:
                    dvalue -= dunrealized
                    pos_value_unlever += dvalue / comminfo.get_leverage()
                    pos_value_unlever += dunrealized
                else:
                    pos_value_unlever += dvalue / comminfo.get_leverage()
            else:
                pos_value_unlever += dvalue

        if not self._fundhist:
            self._value = value = self.cash + pos_value_unlever
            self._fundval = self._value / self._fundshares
        else:
            fundval, fundvalue = self._process_fund_history()

            self._value = fundvalue
            self.cash = fundvalue - pos_value_unlever
            self._fundval = fundval
            self._fundshares = fundvalue / fundval
            lev = pos_value / (pos_value_unlever or 1.0)

            pos_value_unlever = fundvalue
            pos_value = fundvalue * lev
            value = fundvalue

        self._valuemkt = pos_value_unlever
        self._valuelever = self.cash + pos_value
        self._valuemktlever = pos_value
        self._leverage = pos_value / (pos_value_unlever or 1.0)
        self._unrealized = unrealized

        return value if not lever else self._valuelever
