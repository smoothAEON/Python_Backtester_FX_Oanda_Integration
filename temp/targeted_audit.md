# Phase 10 Walk-Forward Audit

## Audit Conditions
- Use the Phase 10 H4 walk-forward setup: last 960 completed bars per instrument, expanding folds 480/160/160/160, objective total_return.
- Keep the execution model unchanged: 20,000 USD starting cash, default leverage 30.0, bid/ask-aware broker, worst_case_first same-bar policy, zero slippage, zero commission.
- Use only local extractor CSVs already present in oanda-candle-extractor/data. Do not introduce live fetches or conversion side inputs for this audit pass.
- USD_CHF is added to every non-ICT strategy as a control instrument. IctOteSniperStrategy keeps its existing coverage of USD_CAD, USD_CHF, and EUR_USD.
- The known EUR/USD issue is treated as a stale pending-entry lifecycle bug rather than a quote-conversion or raw risk-sizing math issue.
- Positive folds with fewer than 3 closed trades are flagged as low-confidence results.

## Known Issue
- Issue ID: eur_usd_stale_pending_reentry
- Status: still_present
- Diagnosis: A stale pending entry can be canceled before the order lifecycle clears the active thesis reference, allowing the strategy to continue evaluating the same bar and attempt a new entry into the one-thesis guard.
- Shared pattern scope: IctOteSniperStrategy, MacdAtrBreakoutStrategy, BollingerZscoreReversionStrategy, SmcPullbackStrategy
- Current audit observation: completed_folds=0 failed_or_empty_folds=0

## Instrument Coverage
```text
            strategy  instrument_count      instruments
HybridRegimeStrategy                 2 USD_JPY, USD_CHF
 EmaRsiTrendStrategy                 1          XAU_USD
```

## Walk-Forward Summary
```text
            strategy instrument timeframe  folds  completed_folds  failed_or_empty_folds  avg_oos_total_return  sum_closed_trades
HybridRegimeStrategy    USD_JPY        H4      3                3                      0             -0.017605                 30
HybridRegimeStrategy    USD_CHF        H4      3                3                      0              0.004697                 28
 EmaRsiTrendStrategy    XAU_USD        H4      3                3                      0              0.001737                  3
```

## Feature Usage
```text
            strategy instrument order_style sizer_type  pending_entry  completed_folds  failed_or_empty_folds  sign_flip_folds  flat_grid_folds  avg_oos_total_return
HybridRegimeStrategy    USD_JPY      market      kelly          False                3                      0                0                3             -0.017605
HybridRegimeStrategy    USD_CHF      market      kelly          False                3                      0                2                3              0.004697
 EmaRsiTrendStrategy    XAU_USD      market  fixed_lot          False                3                      0                2                0              0.001737
```

## Sizing Validation
```text
            strategy instrument  fold  checked_entries  failed_entries  protective_sizing_clean  max_abs_risk_gap  max_allowed_gap
HybridRegimeStrategy    USD_JPY     1                9               0                     True          0.015474         0.019558
HybridRegimeStrategy    USD_JPY     2               15               0                     True          0.003710         0.008093
HybridRegimeStrategy    USD_JPY     3                9               0                     True          0.006510         0.010864
HybridRegimeStrategy    USD_CHF     1                9               0                     True          0.005493         0.009641
HybridRegimeStrategy    USD_CHF     2               15               0                     True          0.007490         0.010339
HybridRegimeStrategy    USD_CHF     3                7               0                     True          0.004340         0.006776
 EmaRsiTrendStrategy    XAU_USD     1                1               0                     True          0.000000         0.000000
 EmaRsiTrendStrategy    XAU_USD     2                1               0                     True          0.000000         0.000000
 EmaRsiTrendStrategy    XAU_USD     3                1               0                     True          0.000000         0.000000
```

## Fold Anomalies
- HybridRegimeStrategy | USD_JPY | fold 1 | flat_grid | All completed parameter values produced the same out-of-sample score.
- HybridRegimeStrategy | USD_JPY | fold 2 | flat_grid | All completed parameter values produced the same out-of-sample score.
- HybridRegimeStrategy | USD_JPY | fold 3 | flat_grid | All completed parameter values produced the same out-of-sample score.
- HybridRegimeStrategy | USD_CHF | fold 1 | flat_grid | All completed parameter values produced the same out-of-sample score.
- HybridRegimeStrategy | USD_CHF | fold 1 | search_oos_sign_flip | search_total_return=-0.0026875047819434617 vs oos_total_return=0.023952926382714734
- HybridRegimeStrategy | USD_CHF | fold 2 | flat_grid | All completed parameter values produced the same out-of-sample score.
- HybridRegimeStrategy | USD_CHF | fold 2 | search_oos_sign_flip | search_total_return=0.04379988480439545 vs oos_total_return=-0.03952383698005402
- HybridRegimeStrategy | USD_CHF | fold 3 | flat_grid | All completed parameter values produced the same out-of-sample score.
- EmaRsiTrendStrategy | XAU_USD | fold 1 | search_oos_sign_flip | search_total_return=-0.0006464999999999943 vs oos_total_return=0.0007399999999997409
- EmaRsiTrendStrategy | XAU_USD | fold 1 | low_trade_count_positive_fold | Positive OOS fold with only 1 closed trades.
- EmaRsiTrendStrategy | XAU_USD | fold 2 | low_trade_count_positive_fold | Positive OOS fold with only 1 closed trades.
- EmaRsiTrendStrategy | XAU_USD | fold 3 | search_oos_sign_flip | search_total_return=-0.00050400000000006 vs oos_total_return=0.003602999999999801
- EmaRsiTrendStrategy | XAU_USD | fold 3 | low_trade_count_positive_fold | Positive OOS fold with only 1 closed trades.

## Recommendations
- Do not trust ICT EUR/USD walk-forward output until the stale-cancel re-entry issue is fully resolved across all folds.
- Review search-vs-OOS sign-flip cases for overfit behavior: HybridRegimeStrategy USD_CHF, EmaRsiTrendStrategy XAU_USD.
- Broaden or remove non-informative search parameters where grids stayed flat: HybridRegimeStrategy USD_JPY, HybridRegimeStrategy USD_CHF.
- Treat low-trade positive folds as weak evidence and avoid overweighting them: EmaRsiTrendStrategy XAU_USD fold 1, EmaRsiTrendStrategy XAU_USD fold 2, EmaRsiTrendStrategy XAU_USD fold 3.

## Artifacts
- Text output: `C:\Users\yihun\AppData\Local\Temp\phase10_targeted_walk_forward\targeted_output.txt`
- JSON summary: `C:\Users\yihun\AppData\Local\Temp\phase10_targeted_walk_forward\targeted_summary.json`
- Elapsed seconds: `670.91`
