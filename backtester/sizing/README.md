# backtester.sizing

## Purpose

`backtester.sizing` contains deterministic, explainable position-sizing helpers. Each sizer returns a `SizingDecision` object that records the raw size, rounded size, acceptance state, and rejection reason.

## Main Public APIs

- `BaseSizer`
- `SizingDecision`
- `FixedLotSizer`
- `RiskPercentSizer`
- `KellySizer`
- `VolatilitySizer`

## How To Use It

Use these classes directly for offline sizing checks or inside strategies that want inspectable size decisions before submitting an order.

## Example

```python
from backtester.sizing import FixedLotSizer

decision = FixedLotSizer(3).size_for_entry(
    equity=10_000.0,
    side="long",
    entry_price=1.1000,
    stop_price=1.0950,
    instrument="EUR_USD",
)

print(decision.accepted)
print(decision.final_size)
print(decision.details["configured_units"])
```

All built-in sizers share the same `size_for_entry(...)` contract.

## Command-Line Flags

None. `backtester.sizing` is library-only.
