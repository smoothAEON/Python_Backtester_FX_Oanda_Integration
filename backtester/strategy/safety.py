"""Strategy runtime-contract metadata and repo-owned import validation."""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

LIVE_SAFE_RUNTIME_CONTRACT = "live_safe"
RESEARCH_ONLY_RUNTIME_CONTRACT = "research_only"
RUNTIME_CONTRACTS = frozenset({LIVE_SAFE_RUNTIME_CONTRACT, RESEARCH_ONLY_RUNTIME_CONTRACT})

FORBIDDEN_INDICATOR_NAMES = frozenset(
    {
        "ICTFibEngine",
        "bos_choch",
        "liquidity",
        "ob",
        "premium_discount",
        "retracements",
        "savgol_smooth",
        "swing_highs_lows",
    }
)
FORBIDDEN_IMPORT_MODULES = frozenset(
    {
        "backtester.indicators.research",
        "backtester.indicators.smc",
    }
)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_OWNED_STRATEGY_ROOTS = (
    _REPO_ROOT / "strategies",
    _REPO_ROOT / "backtester" / "examples",
)


@dataclass(frozen=True, slots=True)
class StrategySafetyReport:
    strategy_class: type
    runtime_contract: str
    runtime_contract_reason: str | None
    repo_owned: bool
    source_path: Path | None
    forbidden_imports: tuple[str, ...]


def strategy_runtime_contract(strategy_class: type) -> tuple[str, str | None]:
    contract = getattr(strategy_class, "runtime_contract", LIVE_SAFE_RUNTIME_CONTRACT)
    if not isinstance(contract, str):
        raise TypeError("strategy runtime_contract must be a string")
    normalized = contract.strip().lower()
    if normalized not in RUNTIME_CONTRACTS:
        supported = ", ".join(sorted(RUNTIME_CONTRACTS))
        raise ValueError(
            f"{strategy_class.__module__}.{strategy_class.__name__} declares unsupported "
            f"runtime_contract={contract!r}; expected one of {supported}"
        )

    reason = getattr(strategy_class, "runtime_contract_reason", None)
    if reason is not None and not isinstance(reason, str):
        raise TypeError("strategy runtime_contract_reason must be a string or None")
    normalized_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
    return normalized, normalized_reason


def inspect_strategy_safety(strategy_class: type) -> StrategySafetyReport:
    contract, reason = strategy_runtime_contract(strategy_class)
    source_path = _strategy_source_path(strategy_class)
    repo_owned = bool(source_path is not None and _is_repo_owned(source_path))
    forbidden_imports = ()
    if repo_owned and source_path is not None:
        forbidden_imports = _scan_strategy_imports(source_path)
    return StrategySafetyReport(
        strategy_class=strategy_class,
        runtime_contract=contract,
        runtime_contract_reason=reason,
        repo_owned=repo_owned,
        source_path=source_path,
        forbidden_imports=forbidden_imports,
    )


def validate_strategy_class(
    strategy_class: type,
    *,
    allow_research_only: bool = False,
) -> StrategySafetyReport:
    report = inspect_strategy_safety(strategy_class)
    if report.runtime_contract == RESEARCH_ONLY_RUNTIME_CONTRACT and not allow_research_only:
        reason = f": {report.runtime_contract_reason}" if report.runtime_contract_reason else ""
        raise ValueError(
            f"{strategy_class.__module__}.{strategy_class.__name__} is marked research_only{reason}. "
            "Pass allow_research_only=True only for offline research runs."
        )

    if report.repo_owned and report.runtime_contract == LIVE_SAFE_RUNTIME_CONTRACT and report.forbidden_imports:
        details = ", ".join(report.forbidden_imports)
        raise ValueError(
            f"{strategy_class.__module__}.{strategy_class.__name__} is marked live_safe but imports "
            f"research-only indicators: {details}"
        )

    return report


def _strategy_source_path(strategy_class: type) -> Path | None:
    source_file = inspect.getsourcefile(strategy_class)
    if source_file is None:
        return None
    return Path(source_file).resolve()


def _is_repo_owned(path: Path) -> bool:
    for root in _REPO_OWNED_STRATEGY_ROOTS:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return True
    return False


@lru_cache(maxsize=None)
def _scan_strategy_imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name
                if module_name in FORBIDDEN_IMPORT_MODULES or any(
                    module_name.startswith(f"{prefix}.") for prefix in FORBIDDEN_IMPORT_MODULES
                ):
                    violations.add(module_name)
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name in FORBIDDEN_IMPORT_MODULES or any(
                module_name.startswith(f"{prefix}.") for prefix in FORBIDDEN_IMPORT_MODULES
            ):
                violations.add(module_name)
                continue
            if module_name != "backtester.indicators":
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if alias.name in FORBIDDEN_INDICATOR_NAMES:
                    violations.add(f"{module_name}.{alias.name}")

    return tuple(sorted(violations))
