from __future__ import annotations

import math

import pytest

from backtester.config import resolve_instrument_spec
from backtester.run_backtest import run_backtest
from backtester.sizing import (
    FixedLotSizer,
    KellySizer,
    RiskPercentSizer,
    VolatilitySizer,
)
from backtester.strategy import BaseStrategy


class SwitchingSizerStrategy(BaseStrategy):
    snapshot: dict | None = None

    params = (
        ("sizer_kind", "fixed"),
        ("fixed_units", 7.9),
        ("risk_percent", 0.004),
        ("volatility", 0.4),
        ("volatility_multiplier", 3.0),
        ("win_probability", 0.6),
        ("payoff_ratio", 2.0),
        ("kelly_fraction", 0.25),
        ("max_risk_percent", 0.004),
        ("stop_offset", 0.6),
    )

    def __init__(self):
        super().__init__()
        self.position_sizer = self._build_sizer()

    def _build_sizer(self):
        if self.p.sizer_kind == "fixed":
            return FixedLotSizer(self.p.fixed_units)
        if self.p.sizer_kind == "risk_percent":
            return RiskPercentSizer(self.p.risk_percent)
        if self.p.sizer_kind == "volatility":
            return VolatilitySizer(
                self.p.risk_percent,
                volatility_multiplier=self.p.volatility_multiplier,
            )
        if self.p.sizer_kind == "kelly":
            return KellySizer(
                win_probability=self.p.win_probability,
                payoff_ratio=self.p.payoff_ratio,
                kelly_fraction=self.p.kelly_fraction,
                max_risk_percent=self.p.max_risk_percent,
            )
        raise ValueError(f"Unsupported sizer_kind: {self.p.sizer_kind!r}")

    def next(self):
        if len(self) != 1 or not self.is_flat() or self.has_open_order():
            return

        entry_price = self.ask.close
        stop_price = self.bid.close - float(self.p.stop_offset)
        decision = self.position_sizer.size_for_entry(
            equity=self.current_equity(),
            side="long",
            entry_price=entry_price,
            stop_price=stop_price,
            instrument=self.instrument or "XAU_USD",
            metadata={"volatility": self.p.volatility},
        )
        type(self).snapshot = {
            "decision": decision,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "equity": self.current_equity(),
        }
        if decision.accepted:
            self.submit_long_market(
                size=decision.final_size,
                stop_loss=stop_price,
                sizing_decision=decision,
            )


class RejectedSizingStrategy(BaseStrategy):
    decision = None

    def __init__(self):
        super().__init__()
        self.position_sizer = RiskPercentSizer(0.01)

    def next(self):
        if len(self) != 1 or not self.is_flat() or self.has_open_order():
            return

        entry_price = self.ask.close
        decision = self.position_sizer.size_for_entry(
            equity=self.current_equity(),
            side="long",
            entry_price=entry_price,
            stop_price=entry_price,
            instrument=self.instrument or "XAU_USD",
        )
        type(self).decision = decision
        if decision.accepted:
            self.submit_long_market(size=decision.final_size, sizing_decision=decision)


def _run(strategy_class, frame, *, strategy_params=None, cash: float = 10_000.0):
    return run_backtest(
        strategy_class,
        instrument="XAU_USD",
        timeframe="H1",
        dataframe=frame,
        cash=cash,
        strategy_params=strategy_params,
    )


def test_instrument_resolver_handles_xau_fx_and_jpy_pairs():
    xau = resolve_instrument_spec("XAU_USD")
    eur = resolve_instrument_spec("EUR_USD")
    jpy = resolve_instrument_spec("USD_JPY")

    assert xau.pip_size == 0.01
    assert eur.pip_size == 0.0001
    assert jpy.pip_size == 0.01
    assert xau.min_size == 1.0
    assert eur.size_step == 1.0


def test_fixed_lot_sizer_returns_configured_size_and_rounds_down():
    decision = FixedLotSizer(7.9).size_for_entry(
        equity=10_000.0,
        side="long",
        entry_price=100.0,
        stop_price=None,
        instrument="XAU_USD",
    )

    assert decision.accepted is True
    assert decision.raw_size == pytest.approx(7.9)
    assert decision.final_size == pytest.approx(7.0)


def test_fixed_lot_sizer_rejects_sizes_below_the_minimum():
    decision = FixedLotSizer(0.9).size_for_entry(
        equity=10_000.0,
        side="long",
        entry_price=100.0,
        stop_price=None,
        instrument="XAU_USD",
    )

    assert decision.accepted is False
    assert decision.reason == "size_below_minimum"


def test_risk_percent_sizer_matches_hand_calculated_long_and_short_examples():
    sizer = RiskPercentSizer(0.01)

    long_decision = sizer.size_for_entry(
        equity=10_000.0,
        side="long",
        entry_price=100.0,
        stop_price=99.5,
        instrument="XAU_USD",
    )
    short_decision = sizer.size_for_entry(
        equity=10_000.0,
        side="short",
        entry_price=100.0,
        stop_price=100.5,
        instrument="XAU_USD",
    )

    assert long_decision.accepted is True
    assert short_decision.accepted is True
    assert long_decision.raw_size == pytest.approx(200.0)
    assert short_decision.raw_size == pytest.approx(200.0)
    assert long_decision.final_size == pytest.approx(200.0)
    assert short_decision.final_size == pytest.approx(200.0)


@pytest.mark.parametrize(
    ("stop_price", "reason"),
    [
        (None, "missing_stop_price"),
        (100.0, "zero_stop_distance"),
        (101.0, "stop_not_below_entry"),
    ],
)
def test_risk_percent_sizer_rejects_invalid_stop_inputs(stop_price, reason):
    decision = RiskPercentSizer(0.01).size_for_entry(
        equity=10_000.0,
        side="long",
        entry_price=100.0,
        stop_price=stop_price,
        instrument="XAU_USD",
    )

    assert decision.accepted is False
    assert decision.reason == reason


def test_volatility_sizer_shrinks_as_volatility_rises():
    sizer = VolatilitySizer(0.01, volatility_multiplier=1.0)

    low_vol = sizer.size_for_entry(
        equity=10_000.0,
        side="long",
        entry_price=100.0,
        stop_price=99.0,
        instrument="XAU_USD",
        metadata={"volatility": 0.5},
    )
    high_vol = sizer.size_for_entry(
        equity=10_000.0,
        side="long",
        entry_price=100.0,
        stop_price=99.0,
        instrument="XAU_USD",
        metadata={"volatility": 2.0},
    )

    assert low_vol.accepted is True
    assert high_vol.accepted is True
    assert low_vol.final_size > high_vol.final_size
    assert low_vol.final_size == pytest.approx(100.0)
    assert high_vol.final_size == pytest.approx(50.0)


@pytest.mark.parametrize(
    ("metadata", "reason"),
    [
        ({}, "missing_volatility"),
        ({"volatility": math.nan}, "invalid_volatility"),
        ({"volatility": 0.0}, "invalid_volatility"),
    ],
)
def test_volatility_sizer_rejects_missing_or_invalid_volatility(metadata, reason):
    decision = VolatilitySizer(0.01).size_for_entry(
        equity=10_000.0,
        side="long",
        entry_price=100.0,
        stop_price=99.0,
        instrument="XAU_USD",
        metadata=metadata,
    )

    assert decision.accepted is False
    assert decision.reason == reason


def test_kelly_sizer_handles_bad_inputs_safely_and_caps_risk():
    capped = KellySizer(
        win_probability=0.6,
        payoff_ratio=2.0,
        kelly_fraction=0.25,
        max_risk_percent=0.02,
    ).size_for_entry(
        equity=10_000.0,
        side="long",
        entry_price=100.0,
        stop_price=99.0,
        instrument="XAU_USD",
    )
    rejected = KellySizer(
        win_probability=0.4,
        payoff_ratio=1.0,
        kelly_fraction=0.25,
        max_risk_percent=0.02,
    ).size_for_entry(
        equity=10_000.0,
        side="long",
        entry_price=100.0,
        stop_price=99.0,
        instrument="XAU_USD",
    )

    assert capped.accepted is True
    assert capped.details["effective_risk_percent"] == pytest.approx(0.02)
    assert capped.final_size == pytest.approx(200.0)
    assert rejected.accepted is False
    assert rejected.reason == "non_positive_kelly_edge"


@pytest.mark.parametrize(
    ("sizer_kind", "expected_method", "expected_size"),
    [
        ("fixed", "fixed_lot", 7.0),
        ("risk_percent", "risk_percent", 50.0),
        ("volatility", "volatility", 33.0),
        ("kelly", "kelly", 50.0),
    ],
)
def test_strategy_can_switch_sizers_without_changing_entry_logic(
    make_oanda_frame,
    sizer_kind,
    expected_method,
    expected_size,
):
    SwitchingSizerStrategy.snapshot = None
    frame = make_oanda_frame()

    result = _run(
        SwitchingSizerStrategy,
        frame,
        strategy_params={"sizer_kind": sizer_kind},
    )

    assert SwitchingSizerStrategy.snapshot is not None
    assert SwitchingSizerStrategy.snapshot["instrument"] == "XAU_USD"
    assert SwitchingSizerStrategy.snapshot["timeframe"] == "H1"
    assert SwitchingSizerStrategy.snapshot["equity"] == pytest.approx(10_000.0)

    entry_events = result.order_ledger[result.order_ledger["role"] == "entry"]
    assert not entry_events.empty
    assert set(entry_events["sizing_method"]) == {expected_method}
    assert set(entry_events["sizing_final_size"]) == {expected_size}
    assert set(entry_events["size"]) == {expected_size}
    assert "Completed" in set(entry_events["status_name"])


def test_entry_sizing_details_are_recorded_and_protective_orders_stay_null(
    make_oanda_frame,
):
    SwitchingSizerStrategy.snapshot = None
    frame = make_oanda_frame()

    result = _run(
        SwitchingSizerStrategy,
        frame,
        strategy_params={"sizer_kind": "risk_percent"},
    )

    entry_events = result.order_ledger[result.order_ledger["role"] == "entry"]
    protective_events = result.order_ledger[result.order_ledger["role"] == "stop_loss"]

    assert not entry_events.empty
    assert not protective_events.empty
    assert entry_events["thesis_ref"].notna().all()
    assert entry_events["sizing_equity"].eq(10_000.0).all()
    assert all(value == pytest.approx(0.8) for value in entry_events["sizing_stop_distance"])
    assert entry_events["sizing_details"].iloc[0]["risk_percent"] == pytest.approx(0.004)
    assert protective_events["sizing_method"].isna().all()
    assert protective_events["sizing_details"].isna().all()


def test_rejected_sizing_decisions_do_not_submit_orders(make_oanda_frame):
    RejectedSizingStrategy.decision = None
    frame = make_oanda_frame()

    result = _run(RejectedSizingStrategy, frame)

    assert RejectedSizingStrategy.decision is not None
    assert RejectedSizingStrategy.decision.accepted is False
    assert RejectedSizingStrategy.decision.reason == "zero_stop_distance"
    assert result.order_ledger.empty
