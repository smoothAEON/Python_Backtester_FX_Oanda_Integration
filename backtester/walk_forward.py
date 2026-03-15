"""Phase 10 walk-forward runner and audit CLI."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

import pandas as pd

from backtester.config import BacktestConfig, ExecutionConfig, resolve_instrument_spec
from backtester.core.fx_conversion import direct_quote_to_account_rate
from backtester.optimization import ParameterSpec, run_grid_search
from strategies import (
    BollingerZscoreReversionStrategy,
    EmaRsiTrendStrategy,
    HybridRegimeStrategy,
    IctOteSniperStrategy,
    MacdAtrBreakoutStrategy,
    SmcPullbackStrategy,
)
from strategies.research import (
    BollingerZscoreReversionStrategy as ResearchBollingerZscoreReversionStrategy,
)
from strategies.research import HybridRegimeStrategy as ResearchHybridRegimeStrategy
from strategies.research import IctOteSniperStrategy as ResearchIctOteSniperStrategy
from strategies.research import SmcPullbackStrategy as ResearchSmcPullbackStrategy

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT_ROOT = Path(tempfile.gettempdir())
DEFAULT_OUTPUT_TEXT = _DEFAULT_OUTPUT_ROOT / "phase10_walk_forward_output.txt"
DEFAULT_OUTPUT_JSON = _DEFAULT_OUTPUT_ROOT / "phase10_walk_forward_summary.json"
DEFAULT_OUTPUT_AUDIT = _DEFAULT_OUTPUT_ROOT / "phase10_walk_forward_audit.md"
TIMEFRAME = "H4"
LOOKBACK_BARS = 960
INITIAL_TRAIN_BARS = 480
TEST_BARS = 160
FOLDS = 3
OBJECTIVE = "total_return"
DEFAULT_CASH = 20_000.0
LOW_TRADE_THRESHOLD = 3
DEFAULT_LEVERAGE = ExecutionConfig().leverage

AUDIT_CONDITIONS = (
    "Use the Phase 10 H4 walk-forward setup: last 960 completed bars per instrument, expanding folds 480/160/160/160, objective total_return.",
    "Keep the execution model unchanged: 20,000 USD starting cash, default leverage 30.0, bid/ask-aware broker, worst_case_first same-bar policy, zero slippage, zero commission.",
    "Use only local extractor CSVs already present in oanda-candle-extractor/data. Do not introduce live fetches or conversion side inputs for this audit pass.",
    "The default matrix includes only strategies marked live_safe. Legacy research-only variants remain under strategies.research and are excluded from rankings, summaries, and recommendations.",
    "USD_CHF is included as a control instrument for the live-safe showcase strategies that cover the repo's major sizing/execution styles.",
    f"Positive folds with fewer than {LOW_TRADE_THRESHOLD} closed trades are flagged as low-confidence results.",
)


@dataclass(frozen=True)
class StrategySpec:
    strategy_class: type
    runtime_contract: str
    instruments: tuple[str, ...]
    search_space: tuple[ParameterSpec, ...]
    order_style: str
    pending_entry: bool
    stale_cancel_logic: bool
    sizer_type: str
    protective_orders: bool
    indicator_access_mode: str
    helper_usage: str


STRATEGY_SPECS: tuple[StrategySpec, ...] = (
    StrategySpec(
        strategy_class=EmaRsiTrendStrategy,
        runtime_contract=EmaRsiTrendStrategy.runtime_contract,
        instruments=("EUR_USD", "USD_JPY", "XAU_USD", "USD_CHF"),
        search_space=(
            ParameterSpec("fast_period", "int", grid_values=(2, 3, 4)),
            ParameterSpec("slow_period", "int", grid_values=(5, 7, 9)),
        ),
        order_style="market",
        pending_entry=False,
        stale_cancel_logic=False,
        sizer_type="fixed_lot",
        protective_orders=False,
        indicator_access_mode="instrument_api runtime indicators",
        helper_usage="backtester.strategy crossover and candle helpers",
    ),
    StrategySpec(
        strategy_class=BollingerZscoreReversionStrategy,
        runtime_contract=BollingerZscoreReversionStrategy.runtime_contract,
        instruments=("EUR_USD", "USD_JPY", "XAU_USD", "USD_CHF"),
        search_space=(
            ParameterSpec(
                "zscore_threshold",
                "float",
                grid_values=(0.5, 0.75, 1.0, 1.25, 1.5),
            ),
        ),
        order_style="limit",
        pending_entry=True,
        stale_cancel_logic=True,
        sizer_type="volatility",
        protective_orders=True,
        indicator_access_mode="instrument_api plus live-safe slope confirmation",
        helper_usage="live-safe bollinger, z-score, EMA, and rolling-slope helpers",
    ),
    StrategySpec(
        strategy_class=SmcPullbackStrategy,
        runtime_contract=SmcPullbackStrategy.runtime_contract,
        instruments=("EUR_USD", "USD_JPY", "XAU_USD", "USD_CHF"),
        search_space=(
            ParameterSpec(
                "retracement_threshold",
                "float",
                grid_values=(10.0, 20.0, 30.0, 40.0, 50.0),
            ),
        ),
        order_style="limit",
        pending_entry=True,
        stale_cancel_logic=True,
        sizer_type="risk_percent",
        protective_orders=True,
        indicator_access_mode="instrument_api plus live-safe confirmed SMC helpers",
        helper_usage="confirmed swings, structure, order blocks, liquidity, premium/discount, retracements",
    ),
    StrategySpec(
        strategy_class=IctOteSniperStrategy,
        runtime_contract=IctOteSniperStrategy.runtime_contract,
        instruments=("USD_CAD", "USD_CHF", "EUR_USD"),
        search_space=(
            ParameterSpec(
                "stop_atr_buffer",
                "float",
                grid_values=(0.25, 0.5, 0.75, 1.0, 1.25),
            ),
        ),
        order_style="limit",
        pending_entry=True,
        stale_cancel_logic=True,
        sizer_type="risk_percent",
        protective_orders=True,
        indicator_access_mode="instrument_api plus CausalICTFibEngine and confirmed SMC helpers",
        helper_usage="confirmed swings, structure, premium/discount, and causal ICT fib levels",
    ),
    StrategySpec(
        strategy_class=HybridRegimeStrategy,
        runtime_contract=HybridRegimeStrategy.runtime_contract,
        instruments=("EUR_USD", "USD_JPY", "XAU_USD", "USD_CHF"),
        search_space=(
            ParameterSpec("adx_threshold", "float", grid_values=(10.0, 15.0, 20.0, 25.0, 30.0)),
        ),
        order_style="market",
        pending_entry=False,
        stale_cancel_logic=False,
        sizer_type="kelly",
        protective_orders=True,
        indicator_access_mode="instrument_api plus live-safe confirmed SMC context",
        helper_usage="ADX, EMA trend, rolling slope, confirmed structure, and confirmed premium/discount",
    ),
    StrategySpec(
        strategy_class=MacdAtrBreakoutStrategy,
        runtime_contract=MacdAtrBreakoutStrategy.runtime_contract,
        instruments=("EUR_USD", "USD_JPY", "XAU_USD", "USD_CHF"),
        search_space=(
            ParameterSpec("breakout_lookback", "int", grid_values=(4, 6, 8, 10, 12)),
        ),
        order_style="stop",
        pending_entry=True,
        stale_cancel_logic=True,
        sizer_type="risk_percent",
        protective_orders=True,
        indicator_access_mode="instrument_api runtime indicators",
        helper_usage="backtester.strategy breakout helpers",
    ),
)

RESEARCH_ONLY_STRATEGY_SPECS: tuple[StrategySpec, ...] = (
    StrategySpec(
        strategy_class=ResearchBollingerZscoreReversionStrategy,
        runtime_contract=ResearchBollingerZscoreReversionStrategy.runtime_contract,
        instruments=("EUR_USD", "USD_JPY", "XAU_USD", "USD_CHF"),
        search_space=(
            ParameterSpec(
                "zscore_threshold",
                "float",
                grid_values=(0.5, 0.75, 1.0, 1.25, 1.5),
            ),
        ),
        order_style="limit",
        pending_entry=True,
        stale_cancel_logic=True,
        sizer_type="volatility",
        protective_orders=True,
        indicator_access_mode="instrument_api plus direct savgol_smooth helper",
        helper_usage="direct research-only Savitzky-Golay helper",
    ),
    StrategySpec(
        strategy_class=ResearchSmcPullbackStrategy,
        runtime_contract=ResearchSmcPullbackStrategy.runtime_contract,
        instruments=("EUR_USD", "USD_JPY", "XAU_USD", "USD_CHF"),
        search_space=(
            ParameterSpec(
                "retracement_threshold",
                "float",
                grid_values=(10.0, 20.0, 30.0, 40.0, 50.0),
            ),
        ),
        order_style="limit",
        pending_entry=True,
        stale_cancel_logic=True,
        sizer_type="risk_percent",
        protective_orders=True,
        indicator_access_mode="instrument_api plus direct SMC helper modules",
        helper_usage="direct BOS, order block, liquidity, premium/discount, retracement helpers",
    ),
    StrategySpec(
        strategy_class=ResearchIctOteSniperStrategy,
        runtime_contract=ResearchIctOteSniperStrategy.runtime_contract,
        instruments=("USD_CAD", "USD_CHF", "EUR_USD"),
        search_space=(
            ParameterSpec(
                "stop_atr_buffer",
                "float",
                grid_values=(0.25, 0.5, 0.75, 1.0, 1.25),
            ),
        ),
        order_style="limit",
        pending_entry=True,
        stale_cancel_logic=True,
        sizer_type="risk_percent",
        protective_orders=True,
        indicator_access_mode="instrument_api plus direct ICT/SMC helper modules",
        helper_usage="direct ICTFibEngine and direct BOS/premium-discount helpers",
    ),
    StrategySpec(
        strategy_class=ResearchHybridRegimeStrategy,
        runtime_contract=ResearchHybridRegimeStrategy.runtime_contract,
        instruments=("EUR_USD", "USD_JPY", "XAU_USD", "USD_CHF"),
        search_space=(
            ParameterSpec("adx_threshold", "float", grid_values=(10.0, 15.0, 20.0, 25.0, 30.0)),
        ),
        order_style="market",
        pending_entry=False,
        stale_cancel_logic=False,
        sizer_type="kelly",
        protective_orders=True,
        indicator_access_mode="instrument_api plus direct smoothing and SMC helper modules",
        helper_usage="direct rolling slope, Savitzky-Golay, BOS, and premium/discount helpers",
    ),
)


class OutputSink:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8", newline="\n")

    def write_line(self, text: str = "") -> None:
        print(text)
        self._handle.write(text + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an expanding-window walk-forward test matrix for the Phase 10 strategies."
    )
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--output-text", type=Path, default=DEFAULT_OUTPUT_TEXT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-audit", type=Path, default=DEFAULT_OUTPUT_AUDIT)
    parser.add_argument("--cash", type=float, default=DEFAULT_CASH)
    parser.add_argument("--leverage", type=float, default=DEFAULT_LEVERAGE)
    return parser.parse_args()


def load_recent_frame(repo_root: Path, instrument: str, timeframe: str) -> pd.DataFrame:
    csv_path = (
        repo_root
        / "oanda-candle-extractor"
        / "data"
        / instrument
        / f"candles_{instrument}_{timeframe}.csv"
    )
    frame = pd.read_csv(csv_path)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame = frame.sort_values("time").reset_index(drop=True)
    if len(frame) < LOOKBACK_BARS:
        raise ValueError(
            f"{instrument} {timeframe} only has {len(frame)} bars; need at least {LOOKBACK_BARS}"
        )
    return frame.tail(LOOKBACK_BARS).reset_index(drop=True)


def fold_slices(frame: pd.DataFrame) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    folds: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    for fold_index in range(FOLDS):
        train_end = INITIAL_TRAIN_BARS + (fold_index * TEST_BARS)
        test_end = train_end + TEST_BARS
        train = frame.iloc[:train_end].reset_index(drop=True)
        test = frame.iloc[train_end:test_end].reset_index(drop=True)
        folds.append((train, test))
    return folds


def equity_value(result) -> float | None:
    if result is None or result.equity_curve.empty:
        return None
    return float(result.equity_curve.iloc[-1]["value"])


def serialize_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): serialize_value(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_value(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def search_space_label(search_space: tuple[ParameterSpec, ...]) -> str:
    parts: list[str] = []
    for spec in search_space:
        if spec.grid_values is not None:
            parts.append(f"{spec.name}={list(spec.grid_values)}")
        elif spec.bounds is not None:
            parts.append(f"{spec.name}=bounds{spec.bounds}")
        else:
            parts.append(spec.name)
    return ", ".join(parts)


def strategy_default_params(strategy_class: type) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    params = getattr(strategy_class, "params", ())
    if hasattr(params, "_getitems"):
        items = list(params._getitems())
    else:
        items = params
    for item in items:
        if isinstance(item, tuple) and len(item) == 2:
            defaults[str(item[0])] = item[1]
    return defaults


def round_down_to_step(value: float, size_step: float) -> float:
    if value <= 0.0:
        return 0.0
    step = Decimal(str(size_step))
    return float((Decimal(str(value)) / step).to_integral_value(rounding=ROUND_DOWN) * step)


def final_order_rows(order_ledger: pd.DataFrame) -> pd.DataFrame:
    if order_ledger.empty:
        return order_ledger.copy()
    ordered = order_ledger.reset_index(drop=True)
    return ordered.groupby("ref", sort=False).tail(1).reset_index(drop=True)


def accepted_entry_rows(order_ledger: pd.DataFrame) -> pd.DataFrame:
    entry_rows = order_ledger[
        (order_ledger["role"] == "entry")
        & (order_ledger["status_name"].isin(["Accepted", "Completed"]))
    ].copy()
    if entry_rows.empty:
        return entry_rows
    priority = {"Accepted": 0, "Completed": 1}
    entry_rows["status_priority"] = entry_rows["status_name"].map(priority).fillna(99)
    entry_rows = entry_rows.sort_values(["ref", "status_priority", "event_time"])
    accepted = entry_rows.groupby("ref", sort=False).head(1).drop(columns=["status_priority"])
    return accepted.reset_index(drop=True)


def count_same_bar_protective_activations(order_ledger: pd.DataFrame) -> int:
    completed_entries = order_ledger[
        (order_ledger["role"] == "entry") & (order_ledger["status_name"] == "Completed")
    ]
    protective_orders = order_ledger[order_ledger["role"].isin(["stop_loss", "take_profit"])]
    activated_refs: set[int] = set()
    for _, entry_row in completed_entries.iterrows():
        entry_ref = int(entry_row["ref"])
        entry_time = entry_row["executed_time"]
        if pd.isna(entry_time):
            continue
        matching = protective_orders[
            (protective_orders["thesis_ref"] == entry_ref)
            & (protective_orders["created_time"] == entry_time)
        ]
        if not matching.empty:
            activated_refs.add(entry_ref)
    return len(activated_refs)


def manual_exit_count(result) -> int:
    closed_trades = result.closed_trade_ledger
    if "exit_reason" not in closed_trades.columns or closed_trades.empty:
        return 0
    return int((closed_trades["exit_reason"] == "manual_exit").sum())


def has_sign_flip(objective_score: float | None, search_score: float | None) -> bool:
    if objective_score is None or search_score is None:
        return False
    if objective_score == 0.0 or search_score == 0.0:
        return False
    return (objective_score > 0.0 > search_score) or (objective_score < 0.0 < search_score)


def flat_grid_detected(trial_rows: list[dict[str, Any]]) -> bool:
    completed_scores = [
        round(float(row["objective_score"]), 12)
        for row in trial_rows
        if row.get("status") == "completed" and row.get("objective_score") is not None
    ]
    return len(completed_scores) > 1 and len(set(completed_scores)) == 1


def positive_fold_has_low_trade_count(record: dict[str, Any]) -> bool:
    if record.get("status") != "completed":
        return False
    objective_score = record.get("objective_score")
    if objective_score is None or float(objective_score) <= 0.0:
        return False
    return int(record.get("closed_trades", 0) or 0) < LOW_TRADE_THRESHOLD


def protective_sizing_clean(order_ledger: pd.DataFrame) -> tuple[bool, list[str]]:
    protective_orders = order_ledger[order_ledger["role"].isin(["stop_loss", "take_profit"])]
    if protective_orders.empty:
        return True, []

    issues: list[str] = []
    for column in (
        "sizing_method",
        "sizing_raw_size",
        "sizing_final_size",
        "sizing_equity",
        "sizing_entry_price",
        "sizing_stop_price",
        "sizing_stop_distance",
        "sizing_details",
    ):
        if not protective_orders[column].isna().all():
            issues.append(f"{column} should stay null on protective orders")
    return not issues, issues


def build_runtime_audit(result) -> dict[str, Any]:
    final_entries = final_order_rows(result.order_ledger[result.order_ledger["role"] == "entry"])
    completed_entries = result.order_ledger[
        (result.order_ledger["role"] == "entry")
        & (result.order_ledger["status_name"] == "Completed")
    ]
    stale_canceled_entries = final_entries[
        (final_entries["status_name"] == "Canceled") & (final_entries["executed_size"] == 0.0)
    ]
    final_status_counts = Counter(str(value) for value in final_entries["status_name"])
    margin_or_rejected = int(
        sum(final_status_counts.get(status, 0) for status in ("Margin", "Rejected"))
    )
    entry_ref_count = int(len(final_entries))
    return {
        "entry_ref_count": entry_ref_count,
        "accepted_entry_count": int(len(accepted_entry_rows(result.order_ledger))),
        "completed_entry_count": int(completed_entries["ref"].nunique()),
        "stale_canceled_entry_count": int(len(stale_canceled_entries)),
        "same_bar_protective_activation_count": int(
            count_same_bar_protective_activations(result.order_ledger)
        ),
        "manual_exit_count": manual_exit_count(result),
        "closed_trade_count": int(len(result.closed_trade_ledger)),
        "order_event_count": int(len(result.order_ledger)),
        "entries_detected": bool(entry_ref_count),
        "margin_or_rejected_entry_count": margin_or_rejected,
        "all_entries_margin_or_rejected": bool(
            entry_ref_count > 0 and margin_or_rejected == entry_ref_count
        ),
        "final_entry_status_counts": dict(final_status_counts),
    }


def _quote_rate_tolerance(
    instrument: str,
    *,
    entry_price: float,
    price_step: float,
) -> float:
    reference_rate = direct_quote_to_account_rate(instrument, price=entry_price)
    if reference_rate is None:
        return 0.0

    deltas = [0.0]
    for direction in (-1.0, 1.0):
        adjusted_price = entry_price + (direction * price_step)
        if adjusted_price <= 0.0:
            continue
        adjusted_rate = direct_quote_to_account_rate(instrument, price=adjusted_price)
        if adjusted_rate is not None:
            deltas.append(abs(float(adjusted_rate) - float(reference_rate)))
    return max(deltas) + 1e-12


def build_sizing_audit(
    result,
    *,
    strategy_class: type,
    instrument: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    merged_params = strategy_default_params(strategy_class)
    merged_params.update(dict(parameters))
    instrument_spec = resolve_instrument_spec(instrument)
    accepted_entries = accepted_entry_rows(result.order_ledger)
    entry_checks: list[dict[str, Any]] = []

    for _, row in accepted_entries.iterrows():
        details = row["sizing_details"] if isinstance(row["sizing_details"], dict) else {}
        method = str(row["sizing_method"]) if pd.notna(row["sizing_method"]) else None
        check = {
            "ref": int(row["ref"]),
            "method": method,
            "passed": True,
            "issues": [],
            "final_size": (
                float(row["sizing_final_size"]) if pd.notna(row["sizing_final_size"]) else None
            ),
            "recorded_size_abs": abs(float(row["size"])) if pd.notna(row["size"]) else None,
            "expected_risk_amount": None,
            "recorded_risk_amount": None,
            "actual_risk_amount": None,
            "allowed_gap": None,
            "abs_risk_gap": None,
        }

        if check["final_size"] is None:
            check["passed"] = False
            check["issues"].append("missing sizing_final_size")
        elif check["recorded_size_abs"] is not None:
            if abs(check["recorded_size_abs"] - check["final_size"]) > 1e-9:
                check["passed"] = False
                check["issues"].append("entry size does not match sizing_final_size")

        if method == "fixed_lot":
            configured_units = details.get("configured_units", merged_params.get("fixed_units"))
            if configured_units is None:
                check["passed"] = False
                check["issues"].append("missing fixed lot configured units")
            else:
                expected_size = round_down_to_step(float(configured_units), instrument_spec.size_step)
                check["expected_final_size"] = expected_size
                if check["final_size"] is None or abs(check["final_size"] - expected_size) > 1e-9:
                    check["passed"] = False
                    check["issues"].append("fixed lot size does not match configured units")
        elif method in {"risk_percent", "volatility", "kelly"}:
            per_unit_risk = details.get("per_unit_risk")
            risk_amount = details.get("risk_amount")
            if per_unit_risk is None or risk_amount is None or check["final_size"] is None:
                check["passed"] = False
                check["issues"].append("missing risk sizing details")
            else:
                per_unit_risk = float(per_unit_risk)
                risk_amount = float(risk_amount)
                if method == "kelly":
                    effective_risk_percent = details.get("effective_risk_percent")
                    max_risk_percent = details.get("max_risk_percent")
                    if effective_risk_percent is None or max_risk_percent is None:
                        check["passed"] = False
                        check["issues"].append("missing Kelly effective risk metadata")
                    else:
                        effective_risk_percent = float(effective_risk_percent)
                        max_risk_percent = float(max_risk_percent)
                        if effective_risk_percent > max_risk_percent + 1e-12:
                            check["passed"] = False
                            check["issues"].append(
                                "effective_risk_percent exceeds max_risk_percent"
                            )
                        expected_risk_amount = float(row["sizing_equity"]) * effective_risk_percent
                        check["expected_risk_amount"] = expected_risk_amount
                else:
                    risk_percent = details.get("risk_percent")
                    if risk_percent is None:
                        check["passed"] = False
                        check["issues"].append("missing risk_percent metadata")
                        expected_risk_amount = None
                    else:
                        expected_risk_amount = float(row["sizing_equity"]) * float(risk_percent)
                        check["expected_risk_amount"] = expected_risk_amount

                check["recorded_risk_amount"] = risk_amount
                actual_risk_amount = check["final_size"] * per_unit_risk
                allowed_gap = (float(instrument_spec.size_step) * per_unit_risk) + 1e-9
                abs_risk_gap = abs(actual_risk_amount - risk_amount)
                check["actual_risk_amount"] = actual_risk_amount
                check["allowed_gap"] = allowed_gap
                check["abs_risk_gap"] = abs_risk_gap
                if check["expected_risk_amount"] is not None and abs(
                    risk_amount - check["expected_risk_amount"]
                ) > 1e-6:
                    check["passed"] = False
                    check["issues"].append("recorded risk amount does not match programmed risk")
                if abs_risk_gap > allowed_gap:
                    check["passed"] = False
                    check["issues"].append("rounded risk gap exceeds one size-step tolerance")

                if method == "volatility":
                    if details.get("volatility") is None or float(details["volatility"]) <= 0.0:
                        check["passed"] = False
                        check["issues"].append("missing positive volatility metadata")
                    effective_distance = details.get("effective_distance")
                    if (
                        effective_distance is None
                        or pd.isna(row["sizing_stop_distance"])
                        or abs(float(effective_distance) - float(row["sizing_stop_distance"])) > 1e-9
                    ):
                        check["passed"] = False
                        check["issues"].append(
                            "effective_distance does not match recorded sizing_stop_distance"
                        )

                if instrument.startswith("USD_"):
                    entry_price_value = row["sizing_entry_price"]
                    if pd.isna(entry_price_value):
                        check["passed"] = False
                        check["issues"].append("missing sizing_entry_price")
                    else:
                        expected_rate = direct_quote_to_account_rate(
                            instrument,
                            price=float(entry_price_value),
                        )
                        recorded_rate = details.get("quote_to_account_rate")
                        if expected_rate is not None:
                            tolerance = _quote_rate_tolerance(
                                instrument,
                                entry_price=float(entry_price_value),
                                price_step=float(instrument_spec.price_step),
                            )
                            check["expected_quote_to_account_rate"] = expected_rate
                            check["quote_rate_tolerance"] = tolerance
                            if recorded_rate is None:
                                check["passed"] = False
                                check["issues"].append("missing quote_to_account_rate")
                            elif abs(float(recorded_rate) - expected_rate) > tolerance:
                                check["passed"] = False
                                check["issues"].append(
                                    "quote_to_account_rate exceeds one price-step tolerance"
                                )
        else:
            check["passed"] = False
            check["issues"].append(f"unsupported sizing method: {method!r}")

        entry_checks.append(serialize_value(check))

    protective_clean, protective_issues = protective_sizing_clean(result.order_ledger)
    max_abs_risk_gap = max(
        (
            float(check["abs_risk_gap"])
            for check in entry_checks
            if check.get("abs_risk_gap") is not None
        ),
        default=0.0,
    )
    max_allowed_gap = max(
        (
            float(check["allowed_gap"])
            for check in entry_checks
            if check.get("allowed_gap") is not None
        ),
        default=0.0,
    )

    return {
        "checked_entries": int(len(entry_checks)),
        "passed_entries": int(sum(1 for check in entry_checks if bool(check["passed"]))),
        "failed_entries": int(sum(1 for check in entry_checks if not bool(check["passed"]))),
        "protective_rows_checked": int(
            len(result.order_ledger[result.order_ledger["role"].isin(["stop_loss", "take_profit"])])
        ),
        "protective_sizing_clean": bool(protective_clean),
        "protective_issues": protective_issues,
        "max_abs_risk_gap": float(max_abs_risk_gap),
        "max_allowed_gap": float(max_allowed_gap),
        "entry_checks": entry_checks,
    }


def build_fold_anomalies(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for record in records:
        base = {
            "strategy": record["strategy"],
            "instrument": record["instrument"],
            "fold": int(record["fold"]),
        }
        if record.get("status") != "completed":
            anomalies.append(
                {
                    **base,
                    "type": "failed_or_empty_fold",
                    "severity": "high",
                    "detail": record.get("error") or "No completed trials in ranking output",
                }
            )
            continue

        if record.get("flat_grid"):
            anomalies.append(
                {
                    **base,
                    "type": "flat_grid",
                    "severity": "medium",
                    "detail": "All completed parameter values produced the same out-of-sample score.",
                }
            )

        if record.get("search_vs_oos_sign_flip"):
            anomalies.append(
                {
                    **base,
                    "type": "search_oos_sign_flip",
                    "severity": "medium",
                    "detail": (
                        f"search_total_return={record.get('search_objective_score')} "
                        f"vs oos_total_return={record.get('objective_score')}"
                    ),
                }
            )

        runtime_audit = record.get("runtime_audit") or {}
        if runtime_audit.get("all_entries_margin_or_rejected"):
            anomalies.append(
                {
                    **base,
                    "type": "entry_execution_failure",
                    "severity": "high",
                    "detail": (
                        "All detected entry refs finished as Margin or Rejected: "
                        f"{runtime_audit.get('final_entry_status_counts', {})}"
                    ),
                }
            )

        if positive_fold_has_low_trade_count(record):
            anomalies.append(
                {
                    **base,
                    "type": "low_trade_count_positive_fold",
                    "severity": "medium",
                    "detail": (
                        f"Positive OOS fold with only {record.get('closed_trades', 0)} "
                        f"closed trades."
                    ),
                }
            )

        sizing_audit = record.get("sizing_audit") or {}
        if sizing_audit.get("failed_entries", 0) > 0 or not sizing_audit.get(
            "protective_sizing_clean",
            True,
        ):
            anomalies.append(
                {
                    **base,
                    "type": "sizing_validation_failure",
                    "severity": "high",
                    "detail": (
                        f"failed_entries={sizing_audit.get('failed_entries', 0)} "
                        f"protective_sizing_clean={sizing_audit.get('protective_sizing_clean', True)}"
                    ),
                }
            )
    return anomalies


def build_feature_matrix(
    strategy_specs: tuple[StrategySpec, ...],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for spec in strategy_specs:
        strategy_name = spec.strategy_class.__name__
        for instrument in spec.instruments:
            matching = [
                record
                for record in records
                if record["strategy"] == strategy_name and record["instrument"] == instrument
            ]
            completed = [record for record in matching if record.get("status") == "completed"]
            objective_scores = [
                float(record["objective_score"])
                for record in completed
                if record.get("objective_score") is not None
            ]
            matrix.append(
                {
                    "strategy": strategy_name,
                    "instrument": instrument,
                    "runtime_contract": spec.runtime_contract,
                    "order_style": spec.order_style,
                    "pending_entry": spec.pending_entry,
                    "stale_cancel_logic": spec.stale_cancel_logic,
                    "sizer_type": spec.sizer_type,
                    "protective_orders": spec.protective_orders,
                    "indicator_access_mode": spec.indicator_access_mode,
                    "helper_usage": spec.helper_usage,
                    "folds": int(len(matching)),
                    "completed_folds": int(len(completed)),
                    "failed_or_empty_folds": int(len(matching) - len(completed)),
                    "entry_folds": int(
                        sum(
                            1
                            for record in completed
                            if (record.get("runtime_audit") or {}).get("entries_detected")
                        )
                    ),
                    "stale_canceled_entries": int(
                        sum(
                            int((record.get("runtime_audit") or {}).get("stale_canceled_entry_count", 0))
                            for record in completed
                        )
                    ),
                    "same_bar_protective_activations": int(
                        sum(
                            int(
                                (record.get("runtime_audit") or {}).get(
                                    "same_bar_protective_activation_count",
                                    0,
                                )
                            )
                            for record in completed
                        )
                    ),
                    "manual_exit_count": int(
                        sum(
                            int((record.get("runtime_audit") or {}).get("manual_exit_count", 0))
                            for record in completed
                        )
                    ),
                    "margin_or_rejected_entry_folds": int(
                        sum(
                            bool((record.get("runtime_audit") or {}).get("all_entries_margin_or_rejected"))
                            for record in completed
                        )
                    ),
                    "total_closed_trades": int(
                        sum(int(record.get("closed_trades", 0) or 0) for record in completed)
                    ),
                    "warning_count_total": int(
                        sum(int(record.get("warning_count", 0) or 0) for record in completed)
                    ),
                    "sign_flip_folds": int(
                        sum(bool(record.get("search_vs_oos_sign_flip")) for record in completed)
                    ),
                    "flat_grid_folds": int(sum(bool(record.get("flat_grid")) for record in completed)),
                    "sizing_failure_folds": int(
                        sum(
                            (
                                int((record.get("sizing_audit") or {}).get("failed_entries", 0)) > 0
                                or not (record.get("sizing_audit") or {}).get(
                                    "protective_sizing_clean",
                                    True,
                                )
                            )
                            for record in completed
                        )
                    ),
                    "avg_oos_total_return": (
                        sum(objective_scores) / len(objective_scores) if objective_scores else None
                    ),
                }
            )
    return matrix


def build_known_issue_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "issue_id": "live_safe_strategy_library",
        "status": "not_applicable",
        "reproducer": None,
        "diagnosis": (
            "The default walk-forward matrix uses the rewritten live-safe strategy library. "
            "Legacy research-only variants remain available under strategies.research for "
            "offline comparison only."
        ),
        "shared_pattern_scope": [],
        "current_completed_folds": int(
            sum(record.get("status") == "completed" for record in records)
        ),
        "current_failed_or_empty_folds": int(
            sum(record.get("status") != "completed" for record in records)
        ),
    }


def build_instrument_coverage(strategy_specs: tuple[StrategySpec, ...]) -> list[dict[str, Any]]:
    return [
        {
            "strategy": spec.strategy_class.__name__,
            "runtime_contract": spec.runtime_contract,
            "instruments": list(spec.instruments),
            "instrument_count": int(len(spec.instruments)),
        }
        for spec in strategy_specs
    ]


def build_recommendations(
    *,
    known_issue_summary: dict[str, Any],
    feature_matrix: list[dict[str, Any]],
    fold_anomalies: list[dict[str, Any]],
) -> list[str]:
    recommendations: list[str] = []

    if known_issue_summary["status"] == "resolved_in_current_audit":
        recommendations.append(
            "Keep the new stale-cancel regression coverage in place; the EUR/USD ICT issue appears resolved in the current audited run."
        )
    elif known_issue_summary["status"] == "still_present":
        recommendations.append(
            "Do not trust ICT EUR/USD walk-forward output until the stale-cancel re-entry issue is fully resolved across all folds."
        )
    else:
        recommendations.append(
            "Use strategies.research only for offline comparison; treat the live-safe matrix as the canonical audited surface."
        )

    unstable = [row for row in feature_matrix if int(row["sign_flip_folds"]) > 0]
    if unstable:
        top = ", ".join(f"{row['strategy']} {row['instrument']}" for row in unstable[:5])
        recommendations.append(
            f"Review search-vs-OOS sign-flip cases for overfit behavior: {top}."
        )

    flat = [row for row in feature_matrix if int(row["flat_grid_folds"]) > 0]
    if flat:
        top = ", ".join(f"{row['strategy']} {row['instrument']}" for row in flat[:5])
        recommendations.append(
            f"Broaden or remove non-informative search parameters where grids stayed flat: {top}."
        )

    entry_failures = [
        anomaly for anomaly in fold_anomalies if anomaly["type"] == "entry_execution_failure"
    ]
    if entry_failures:
        top = ", ".join(
            f"{item['strategy']} {item['instrument']} fold {item['fold']}"
            for item in entry_failures[:5]
        )
        recommendations.append(
            f"Investigate entry-margin/rejection failures before treating the affected folds as strategy no-trade outcomes: {top}."
        )

    low_trade = [
        anomaly for anomaly in fold_anomalies if anomaly["type"] == "low_trade_count_positive_fold"
    ]
    if low_trade:
        top = ", ".join(
            f"{item['strategy']} {item['instrument']} fold {item['fold']}"
            for item in low_trade[:5]
        )
        recommendations.append(
            f"Treat low-trade positive folds as weak evidence and avoid overweighting them: {top}."
        )

    sizing_failures = [
        anomaly for anomaly in fold_anomalies if anomaly["type"] == "sizing_validation_failure"
    ]
    if sizing_failures:
        recommendations.append(
            "Investigate sizing-validation failures before acting on the affected strategy results."
        )

    if not recommendations:
        recommendations.append(
            "No additional audit recommendations were generated beyond maintaining the current regression coverage."
        )

    return recommendations


def build_markdown_audit(
    *,
    output_text: Path,
    output_json: Path,
    summary_rows: list[dict[str, Any]],
    instrument_coverage: list[dict[str, Any]],
    known_issue_summary: dict[str, Any],
    feature_matrix: list[dict[str, Any]],
    sizing_checks: list[dict[str, Any]],
    fold_anomalies: list[dict[str, Any]],
    recommendations: list[str],
    elapsed_seconds: float,
) -> str:
    summary_frame = pd.DataFrame(summary_rows)
    coverage_frame = pd.DataFrame(
        [
            {
                "strategy": row["strategy"],
                "instrument_count": row["instrument_count"],
                "instruments": ", ".join(row["instruments"]),
            }
            for row in instrument_coverage
        ]
    )
    feature_frame = pd.DataFrame(feature_matrix)
    sizing_frame = pd.DataFrame(sizing_checks)
    anomaly_frame = pd.DataFrame(fold_anomalies)

    lines: list[str] = [
        "# Phase 10 Walk-Forward Audit",
        "",
        "## Audit Conditions",
    ]
    lines.extend(f"- {condition}" for condition in AUDIT_CONDITIONS)
    lines.extend(
        [
            "",
            "## Known Issue",
            f"- Issue ID: {known_issue_summary['issue_id']}",
            f"- Status: {known_issue_summary['status']}",
            f"- Diagnosis: {known_issue_summary['diagnosis']}",
            "- Shared pattern scope: " + ", ".join(known_issue_summary["shared_pattern_scope"]),
            (
                "- Current audit observation: "
                f"completed_folds={known_issue_summary['current_completed_folds']} "
                f"failed_or_empty_folds={known_issue_summary['current_failed_or_empty_folds']}"
            ),
            "",
            "## Instrument Coverage",
            "```text",
            coverage_frame.to_string(index=False),
            "```",
            "",
            "## Walk-Forward Summary",
            "```text",
            summary_frame.to_string(index=False),
            "```",
            "",
            "## Feature Usage",
            "```text",
            feature_frame[
                [
                    "strategy",
                    "instrument",
                    "order_style",
                    "sizer_type",
                    "pending_entry",
                    "completed_folds",
                    "failed_or_empty_folds",
                    "sign_flip_folds",
                    "flat_grid_folds",
                    "avg_oos_total_return",
                ]
            ].to_string(index=False),
            "```",
            "",
            "## Sizing Validation",
            "```text",
            (
                sizing_frame[
                    [
                        "strategy",
                        "instrument",
                        "fold",
                        "checked_entries",
                        "failed_entries",
                        "protective_sizing_clean",
                        "max_abs_risk_gap",
                        "max_allowed_gap",
                    ]
                ].to_string(index=False)
                if not sizing_frame.empty
                else "<none>"
            ),
            "```",
            "",
            "## Fold Anomalies",
        ]
    )

    if anomaly_frame.empty:
        lines.append("- None")
    else:
        for _, row in anomaly_frame.iterrows():
            lines.append(
                f"- {row['strategy']} | {row['instrument']} | fold {row['fold']} | "
                f"{row['type']} | {row['detail']}"
            )

    lines.extend(["", "## Recommendations"])
    lines.extend(f"- {recommendation}" for recommendation in recommendations)
    lines.extend(
        [
            "",
            "## Artifacts",
            f"- Text output: `{output_text}`",
            f"- JSON summary: `{output_json}`",
            f"- Elapsed seconds: `{elapsed_seconds}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run_walk_forward(
    repo_root: Path,
    sink: OutputSink,
    output_json: Path,
    output_audit: Path,
    *,
    cash: float,
    leverage: float,
    strategy_specs: tuple[StrategySpec, ...] = STRATEGY_SPECS,
) -> dict[str, Any]:
    started_at = time.time()
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    records: list[dict[str, Any]] = []
    config = BacktestConfig(
        cash=cash,
        execution=ExecutionConfig(leverage=leverage),
    )

    sink.write_line("Phase 10 Walk-Forward Matrix")
    sink.write_line(f"repo_root={repo_root}")
    sink.write_line(f"timeframe={TIMEFRAME}")
    sink.write_line(
        f"lookback_bars={LOOKBACK_BARS} initial_train_bars={INITIAL_TRAIN_BARS} "
        f"test_bars={TEST_BARS} folds={FOLDS}"
    )
    sink.write_line(f"objective={OBJECTIVE}")
    sink.write_line(f"cash={cash}")
    sink.write_line(f"leverage={leverage}")
    sink.write_line()

    for spec in strategy_specs:
        strategy_name = spec.strategy_class.__name__
        sink.write_line("=" * 96)
        sink.write_line(f"Strategy: {strategy_name}")
        sink.write_line(f"Runtime Contract: {spec.runtime_contract}")
        sink.write_line(f"Search Space: {search_space_label(spec.search_space)}")
        sink.write_line(f"Instruments: {', '.join(spec.instruments)}")
        sink.write_line("=" * 96)
        sink.write_line()

        for instrument in spec.instruments:
            cache_key = (instrument, TIMEFRAME)
            if cache_key not in frame_cache:
                frame_cache[cache_key] = load_recent_frame(repo_root, instrument, TIMEFRAME)
            frame = frame_cache[cache_key]

            sink.write_line("-" * 96)
            sink.write_line(f"{strategy_name} | {instrument} | {TIMEFRAME}")
            sink.write_line("-" * 96)

            for fold_index, (train, test) in enumerate(fold_slices(frame), start=1):
                train_start = pd.Timestamp(train["time"].iloc[0]).isoformat()
                train_end = pd.Timestamp(train["time"].iloc[-1]).isoformat()
                test_start = pd.Timestamp(test["time"].iloc[0]).isoformat()
                test_end = pd.Timestamp(test["time"].iloc[-1]).isoformat()
                sink.write_line(
                    f"Fold {fold_index}/{FOLDS}: "
                    f"train[{len(train)}]={train_start} -> {train_end} | "
                    f"test[{len(test)}]={test_start} -> {test_end}"
                )

                fold_record: dict[str, Any] = {
                    "strategy": strategy_name,
                    "instrument": instrument,
                    "timeframe": TIMEFRAME,
                    "fold": fold_index,
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                    "search_space": search_space_label(spec.search_space),
                }

                try:
                    optimization = run_grid_search(
                        spec.strategy_class,
                        instrument=instrument,
                        timeframe=TIMEFRAME,
                        dataframe=train,
                        evaluation_dataframe=test,
                        cash=cash,
                        config=config,
                        search_space=list(spec.search_space),
                        objective=OBJECTIVE,
                    )
                    ranking = optimization.ranking(include_invalid=True)
                    ranking_rows = serialize_value(ranking.to_dict(orient="records"))
                    sink.write_line("Ranking:")
                    if ranking.empty:
                        sink.write_line("<empty>")
                    else:
                        sink.write_line(ranking.to_string(index=False))

                    completed = ranking.loc[ranking["status"] == "completed"].copy()
                    if completed.empty:
                        fold_record.update(
                            {
                                "status": "no_completed_trials",
                                "trial_rows": ranking_rows,
                                "flat_grid": False,
                                "search_vs_oos_sign_flip": False,
                                "runtime_audit": None,
                                "sizing_audit": None,
                            }
                        )
                        sink.write_line("Best Trial: none")
                        sink.write_line()
                        records.append(fold_record)
                        continue

                    best_trial = optimization.best_trial()
                    best_result = best_trial.result
                    best_equity = equity_value(best_result)
                    closed_trades = (
                        int(len(best_result.closed_trade_ledger)) if best_result is not None else 0
                    )
                    orders = int(len(best_result.order_ledger)) if best_result is not None else 0
                    runtime_audit = build_runtime_audit(best_result)
                    sizing_audit = build_sizing_audit(
                        best_result,
                        strategy_class=spec.strategy_class,
                        instrument=instrument,
                        parameters=best_trial.parameters,
                    )
                    search_score = (
                        float(best_trial.search_objective_score)
                        if best_trial.search_objective_score is not None
                        else None
                    )
                    objective_score = (
                        float(best_trial.objective_score)
                        if best_trial.objective_score is not None
                        else None
                    )

                    fold_record.update(
                        {
                            "status": "completed",
                            "best_parameters": serialize_value(best_trial.parameters),
                            "objective_score": serialize_value(best_trial.objective_score),
                            "search_objective_score": serialize_value(
                                best_trial.search_objective_score
                            ),
                            "objective_score_source": best_trial.objective_score_source,
                            "metrics": serialize_value(best_trial.metrics),
                            "warning_count": int(best_trial.warning_count),
                            "closed_trades": closed_trades,
                            "orders": orders,
                            "ending_equity": best_equity,
                            "trial_rows": ranking_rows,
                            "flat_grid": flat_grid_detected(ranking_rows),
                            "search_vs_oos_sign_flip": has_sign_flip(objective_score, search_score),
                            "runtime_audit": runtime_audit,
                            "sizing_audit": sizing_audit,
                        }
                    )

                    sink.write_line(
                        "Best Trial: "
                        f"params={best_trial.parameters} "
                        f"oos_total_return={best_trial.objective_score} "
                        f"search_total_return={best_trial.search_objective_score} "
                        f"closed_trades={closed_trades} orders={orders} ending_equity={best_equity}"
                    )
                except Exception as exc:
                    fold_record.update(
                        {
                            "status": "failed",
                            "error": f"{type(exc).__name__}: {exc}",
                            "trial_rows": [],
                            "flat_grid": False,
                            "search_vs_oos_sign_flip": False,
                            "runtime_audit": None,
                            "sizing_audit": None,
                        }
                    )
                    sink.write_line(f"ERROR: {type(exc).__name__}: {exc}")

                sink.write_line()
                records.append(fold_record)

    summary_rows: list[dict[str, Any]] = []
    for spec in strategy_specs:
        strategy_name = spec.strategy_class.__name__
        for instrument in spec.instruments:
            matching = [
                record
                for record in records
                if record["strategy"] == strategy_name and record["instrument"] == instrument
            ]
            completed = [record for record in matching if record["status"] == "completed"]
            objective_scores = [
                float(record["objective_score"])
                for record in completed
                if record.get("objective_score") is not None
            ]
            summary_rows.append(
                {
                    "strategy": strategy_name,
                    "instrument": instrument,
                    "timeframe": TIMEFRAME,
                    "folds": len(matching),
                    "completed_folds": len(completed),
                    "failed_or_empty_folds": len(matching) - len(completed),
                    "avg_oos_total_return": (
                        sum(objective_scores) / len(objective_scores)
                        if objective_scores
                        else None
                    ),
                    "sum_closed_trades": sum(
                        int(record.get("closed_trades", 0) or 0) for record in completed
                    ),
                }
            )

    feature_matrix = build_feature_matrix(strategy_specs, records)
    instrument_coverage = build_instrument_coverage(strategy_specs)
    sizing_checks = [
        {
            "strategy": record["strategy"],
            "instrument": record["instrument"],
            "fold": int(record["fold"]),
            **serialize_value(record["sizing_audit"]),
        }
        for record in records
        if record.get("status") == "completed" and record.get("sizing_audit") is not None
    ]
    fold_anomalies = build_fold_anomalies(records)
    known_issue_summary = build_known_issue_summary(records)
    recommendations = build_recommendations(
        known_issue_summary=known_issue_summary,
        feature_matrix=feature_matrix,
        fold_anomalies=fold_anomalies,
    )

    summary_frame = pd.DataFrame(summary_rows)
    sink.write_line("=" * 96)
    sink.write_line("Summary")
    sink.write_line("=" * 96)
    sink.write_line(summary_frame.to_string(index=False))
    sink.write_line()
    sink.write_line(f"known_issue_status={known_issue_summary['status']}")
    sink.write_line(f"fold_anomaly_count={len(fold_anomalies)}")
    sink.write_line(f"elapsed_seconds={round(time.time() - started_at, 2)}")
    sink.write_line(f"json_summary={output_json}")
    sink.write_line(f"audit_markdown={output_audit}")

    elapsed_seconds = round(time.time() - started_at, 2)
    audit_markdown = build_markdown_audit(
        output_text=sink.path,
        output_json=output_json,
        summary_rows=summary_rows,
        instrument_coverage=instrument_coverage,
        known_issue_summary=known_issue_summary,
        feature_matrix=feature_matrix,
        sizing_checks=sizing_checks,
        fold_anomalies=fold_anomalies,
        recommendations=recommendations,
        elapsed_seconds=elapsed_seconds,
    )
    output_audit.parent.mkdir(parents=True, exist_ok=True)
    output_audit.write_text(audit_markdown, encoding="utf-8")

    payload = {
        "repo_root": str(repo_root),
        "timeframe": TIMEFRAME,
        "lookback_bars": LOOKBACK_BARS,
        "initial_train_bars": INITIAL_TRAIN_BARS,
        "test_bars": TEST_BARS,
        "folds": FOLDS,
        "objective": OBJECTIVE,
        "cash": cash,
        "leverage": leverage,
        "audit_conditions": list(AUDIT_CONDITIONS),
        "known_issue_summary": serialize_value(known_issue_summary),
        "instrument_coverage": serialize_value(instrument_coverage),
        "feature_matrix": serialize_value(feature_matrix),
        "sizing_checks": serialize_value(sizing_checks),
        "fold_anomalies": serialize_value(fold_anomalies),
        "strategy_specs": [
            {
                "strategy": spec.strategy_class.__name__,
                "runtime_contract": spec.runtime_contract,
                "instruments": list(spec.instruments),
                "search_space": search_space_label(spec.search_space),
                "order_style": spec.order_style,
                "pending_entry": spec.pending_entry,
                "stale_cancel_logic": spec.stale_cancel_logic,
                "sizer_type": spec.sizer_type,
                "protective_orders": spec.protective_orders,
                "indicator_access_mode": spec.indicator_access_mode,
                "helper_usage": spec.helper_usage,
            }
            for spec in strategy_specs
        ],
        "records": serialize_value(records),
        "summary": serialize_value(summary_rows),
        "recommendations": recommendations,
        "audit_markdown_path": str(output_audit),
        "elapsed_seconds": elapsed_seconds,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    sink = OutputSink(args.output_text)
    try:
        run_walk_forward(
            repo_root,
            sink,
            args.output_json,
            args.output_audit,
            cash=args.cash,
            leverage=args.leverage,
        )
    finally:
        sink.write_line()
        sink.write_line(f"text_output={args.output_text}")
        sink.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
