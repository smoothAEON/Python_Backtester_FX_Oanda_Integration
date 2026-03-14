# OANDA Candle Extractor

A standalone Python script directory for extracting historical OANDA candles with paced request scheduling, a shared date-range window scheduler, and canonical CSV persistence.

For repo navigation, see [../README.md](../README.md). If you want to consume extractor output with the backtester, see [../backtester/README.md](../backtester/README.md).

## Features

- Full timeframe support from `S5` through `W`
- Date-range fetching in deterministic 5000-candle windows
- Global request pacing with a default `119 rps` target
- Worker-local persistent API sessions with a `2 new connections/second` warm-up ceiling
- Memory + CSV caching with stale-series refresh and gap-only date-range fetches
- One shared date-range worker pool across all selected timeframes
- Atomic CSV writes with `.csv.bak` recovery
- Canonical 14-column `MBA` output for backtester compatibility

## Installation

From the repo root:

```powershell
python -m pip install -r oanda-candle-extractor\requirements.txt
```

From inside `oanda-candle-extractor\`:

```powershell
python -m pip install -r requirements.txt
```

The extractor auto-loads `oanda-candle-extractor/.env` if that file exists. Explicit CLI arguments and already-exported environment variables still win because `.env` loading does not override existing process values.

## Usage

### CLI

From the repo root:

```powershell
python oanda-candle-extractor\extract_candles.py --help
python oanda-candle-extractor\extract_candles.py --validate
python oanda-candle-extractor\extract_candles.py --instrument XAU_USD --timeframes 1h --count 500
python oanda-candle-extractor\extract_candles.py --instrument EUR_USD --timeframes 5s --count 5000 --target-rps 119 --max-workers 16
python oanda-candle-extractor\extract_candles.py --instrument XAU_USD --start-date 2024-01-01 --end-date 2024-12-31 --timeframes 1h --target-rps 119 --max-workers 16
```

From inside `oanda-candle-extractor/`:

```powershell
python extract_candles.py --help
```

### Python API

Use the current script-directory import style:

```python
from datetime import datetime, timezone

from extract_candles import OANDACandleExtractor

extractor = OANDACandleExtractor(
    api_key="your_api_key",
    account_id="your_account_id",
    account_type="practice",  # or omit it and use OANDA_ENVIRONMENT
    data_dir="data",
    target_rps=119,
    max_workers=16,
)

latest = extractor.fetch_candles(
    instrument="XAU_USD",
    timeframe="H1",
    count=500,
)

historical = extractor.fetch_candles_by_date_range(
    instrument="XAU_USD",
    timeframe="H1",
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
)
```

## Canonical Output

CSV files are written to:

```text
data/<INSTRUMENT>/candles_<INSTRUMENT>_<TIMEFRAME>.csv
```

Example:

```text
data/XAU_USD/candles_XAU_USD_H1.csv
```

Persisted extractor output is always the 14-column `MBA` candle contract:

- `time`
- `open`, `high`, `low`, `close`
- `bid_open`, `bid_high`, `bid_low`, `bid_close`
- `ask_open`, `ask_high`, `ask_low`, `ask_close`
- `volume`

The CLI still accepts `--price`, but only `MBA` is valid for persisted extractor output.

## How Date-Range Fetching Works

When fetching a date range, the extractor now:

1. Loads the canonical CSV cache if present.
2. Reuses contiguous cached coverage inside the requested range.
3. Plans only the uncovered gaps as chronological `from`/`to` windows capped at 5000 candles each.
4. Uses `includeFirst=False` on every window after the first boundary so adjacent windows do not duplicate the starting candle.
5. Schedules uncovered windows through one shared worker pool across all selected timeframes, writes each timeframe in chronological order to a staging CSV, and atomically promotes the finished file.

## Rate Limiting and Concurrency

- Default request pacing target: `119 requests/second`
- Default worker count: `16`
- For date-range jobs, `max_workers` is one global concurrent-window ceiling across all selected timeframes
- New OANDA client creation is paced to `2 new connections/second`
- Count-mode cache refresh fetches only new candles after the latest cached completed candle
- Date-range cache hits return immediately only when the requested range is fully covered; otherwise only missing gaps are fetched
- Per-request OANDA transport logs are suppressed at the default `INFO` level; use `--log-level DEBUG` if you need request-by-request tracing

Real wall-clock throughput can still land below `119 rps` if network latency or server-side behavior dominates. The extractor is tuned so its own scheduler is not the first bottleneck.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OANDA_API_KEY` | Yes | Your OANDA API key |
| `OANDA_ACCOUNT_ID` | Yes | Your OANDA account ID |
| `OANDA_ENVIRONMENT` | No | Default OANDA environment when `--account-type` / `account_type` is omitted |
| `LOG_LEVEL` | No | Logging level override |
| `DATA_DIR` | No | Data directory override |

If `oanda-candle-extractor/.env` exists, those values are loaded automatically at startup.
Account type resolution order is: explicit `--account-type` / `account_type`, then `OANDA_ENVIRONMENT`, then `practice`.

## Verification

From the repo root:

```powershell
python oanda-candle-extractor\extract_candles.py --help
python -m pytest tests\extractor -q
```

`--validate` performs a real API request and requires valid credentials plus network access.
