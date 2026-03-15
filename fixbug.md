# Fixbug Memo

This memo supersedes the current integrity conclusions in `plans/backtest_integrity_audit.md` for the live-safety topics covered here. That audit mixed stale findings, confirmed live-unsafe strategy behavior, policy-only violations, and unconfirmed hypotheses into one bucket. This document separates those categories and records the repo-level fix plan adopted in this pass.

## Classification Rules

- `stale finding`: a prior audit claim that no longer matches current code.
- `confirmed live-unsafe`: a runnable strategy or default audit path currently uses non-causal data in a way that makes backtest decisions non-live-like.
- `research-only/policy violation`: a helper or strategy path is outside the framework's live-safe contract and must be quarantined from normal runtime usage, even if the current call pattern is not a confirmed current-bar leak.
- `unconfirmed hypothesis`: a plausible issue that was claimed too strongly without strategy-level confirmation.

## Why The Prior Audit Failed

The prior audit failed for three distinct reasons.

1. It used stale repo assumptions.
   - The old multi-timeframe claim is obsolete. `backtester/run_backtest.py` now normalizes extractor `time` to completed-bar `bar_end_time`, and `backtester/strategy/instrument_api.py` gates higher-timeframe visibility with `bar_end_time <= current_primary_bar_end`.
   - The old optimizer claim is also obsolete. `backtester/optimization/_core.py` now rejects ranked optimization output without out-of-sample evaluation unless `allow_in_sample=True`.

2. It undercounted runnable unsafe strategies.
   - The repo-owned walk-forward matrix and canonical strategy library were not audited end to end.
   - A repo-wide dependency pass across `strategies/`, `backtester/walk_forward.py`, tests, and docs shows three confirmed live-unsafe SMC strategies, not two: `SmcPullbackStrategy`, `HybridRegimeStrategy`, and `IctOteSniperStrategy`.

3. It over-claimed some defects without checking actual strategy call patterns.
   - The existence of a research helper was treated as equivalent to a confirmed live leakage path.
   - That overstated the current severity of `savgol_smooth` usage in `BollingerZscoreReversionStrategy`.
   - It also overstated the specific near-right-edge ICT fib contamination claim without confirming the actual `ICTFibEngine` ingestion behavior.

## Current Findings

### Stale Findings

- The multi-timeframe visibility finding in `plans/backtest_integrity_audit.md` is stale because completed-bar gating is now enforced in `backtester/run_backtest.py` and `backtester/strategy/instrument_api.py`.
- The optimizer-ranking finding in `plans/backtest_integrity_audit.md` is stale because `backtester/optimization/_core.py` now blocks ranked in-sample-only results by default.

### Confirmed Live-Unsafe

- `critical`: the live-safe contract was bypassable.
  - `backtester/strategy/instrument_api.py` rejects unsafe/repainting helpers at runtime.
  - Repo-owned strategies were still importing those helpers directly from the general indicator surface.
  - `backtester/walk_forward.py` still included those strategies in the default audit matrix.
  - Result: the repo's own guardrail did not protect the headline walk-forward output.

- `critical`: three strategies were confirmed live-unsafe because they consume swing-based SMC outputs that depend on future confirmation and may synthesize a current-bar pivot state.
  - `strategies/smc_pullback.py`
  - `strategies/hybrid_regime.py`
  - `strategies/ict_ote_sniper.py`

- `high`: `SmcPullbackStrategy` has a broader unsafe dependency surface than the prior audit recorded.
  - It depends on `swing_highs_lows` and `premium_discount`.
  - It also depends on `ob`, `liquidity`, and `retracements`.

- `high`: `IctOteSniperStrategy` remains research-only.
  - It directly uses `swing_highs_lows`, `bos_choch`, and `premium_discount`.
  - `ICTFibEngine` also depends on the upstream swing helper.
  - The strategy therefore belongs in the same quarantine bucket even though the specific near-edge pivot claim was not confirmed.

### Research-Only / Policy Violations

- `medium`: `strategies/bollinger_zscore_reversion.py` is outside the live-safe contract because it imports `savgol_smooth` directly.
  - This helper is intentionally blocked from `instrument_api`.
  - Current usage should be treated as research-only/questionable, not as a confirmed current-bar lookahead defect on the same level as the SMC strategies.

- `medium`: `backtester/requirements.txt` still carries `smartmoneyconcepts` as a core dependency even though the live-safe runtime path should not require it.
  - This pass records that as a follow-up dependency split, not as an immediate packaging change.

### Unconfirmed Hypotheses

- The prior audit's specific claim that `BollingerZscoreReversionStrategy` had an active current-bar lookahead bug is not confirmed here.
- The prior audit's specific claim that `ICTFibEngine` still ingests contaminated near-right-edge pivots after excluding `final_index` is not confirmed here.

## Dependency Fallout

The unsafe path was blessed by more than the strategies themselves.

- `strategies/__init__.py`, `strategies/README.md`, and `backtester/README.md` exposed research-only strategies as part of the canonical runnable surface.
- `backtester/indicators/__init__.py`, `backtester/API_INDEX.md`, and `backtester/indicators/README.md` advertised unsafe helpers from the same public namespace as live-safe helpers.
- `tests/backtester/test_strategy_library_phase10.py`, `tests/backtester/test_walk_forward_phase10.py`, `tests/backtester/test_strategy_phase2.py`, `tests/backtester/test_smc_indicators.py`, and `tests/backtester/test_ict_fib.py` treated research-only behavior as part of the normal contract instead of a quarantined one.
- `backtester/requirements.txt` still keeps `smartmoneyconcepts` on the default dependency path.

## Exact Repo Fix Plan

This pass quarantines unsafe strategies and helpers instead of redesigning them into causal replacements.

### Strategy Contract

- Add `runtime_contract = "live_safe"` and `runtime_contract_reason = None` to `BaseStrategy`.
- Mark these repo strategies `research_only` with explicit reasons:
  - `BollingerZscoreReversionStrategy`
  - `SmcPullbackStrategy`
  - `IctOteSniperStrategy`
  - `HybridRegimeStrategy`

### Import Validation

- Add a strategy safety validator that AST-scans repo-owned strategy source files.
- Treat these imports as forbidden for `live_safe` strategies:
  - any import from `backtester.indicators.research`
  - any import from `backtester.indicators.smc`
  - forbidden names imported from `backtester.indicators`
- Reject `research_only` strategies by default unless the caller passes explicit opt-in.

### Indicator Surface Split

- Keep `backtester.indicators` live-safe only.
- Move research helpers behind `backtester.indicators.research`:
  - `savgol_smooth`
  - `swing_highs_lows`
  - `bos_choch`
  - `ob`
  - `liquidity`
  - `premium_discount`
  - `retracements`
  - `ICTFibEngine`
- Remove dead unsafe branches from `backtester/strategy/instrument_api.py` once those helpers are no longer on the runtime-safe surface.

### Runtime Rejection

- Make `backtester/run_backtest.py` reject `research_only` strategies by default.
- Add explicit opt-in:
  - programmatic: `allow_research_only=False` default
  - CLI: `--allow-research-only`

### Walk-Forward Scope

- Restrict the default walk-forward matrix to `live_safe` strategies only.
- Keep only:
  - `EmaRsiTrendStrategy`
  - `MacdAtrBreakoutStrategy`
- Move these into a research-only registry excluded from default rankings and summaries:
  - `BollingerZscoreReversionStrategy`
  - `SmcPullbackStrategy`
  - `IctOteSniperStrategy`
  - `HybridRegimeStrategy`
- Remove hardcoded default-audit logic that assumes `IctOteSniperStrategy` belongs in the main matrix.

### Documentation

- Rewrite public docs so the main runtime surfaces show only live-safe defaults.
- Label research-only strategies and helpers explicitly as quarantine paths.
- Record `plans/backtest_integrity_audit.md` as stale for current integrity conclusions.

### Tests

- Assert the default walk-forward matrix is live-safe only.
- Assert research-only strategies are rejected unless explicitly opted in.
- Add import-ban coverage for repo-owned live-safe strategies.
- Add prefix-stability checks for approved live-safe indicators and live-safe showcase strategies.
- Keep research-helper behavior tests, but move them under research-only expectations.
- Update documentation tests so public examples remain live-safe by default.

## Remaining Follow-Up

- Reimplement causal replacements for the quarantined SMC features if they are meant to return to the live-safe runtime path.
- Split `smartmoneyconcepts` into a research-only dependency manifest after the namespace split is fully settled.
- Re-audit strategy sizing realism and transaction-cost defaults separately from this live-safety quarantine.

## Assumptions

- `savgol_smooth` remains available for offline research only.
- This pass does not certify the quarantined strategies as trustworthy; it removes them from default live-like runtime surfaces.
- `plans/backtest_integrity_audit.md` remains as historical record, not as the source of truth for current integrity conclusions.
