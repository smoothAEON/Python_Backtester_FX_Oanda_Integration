# OANDA Candle Extractor

A standalone Python script directory for extracting historical OANDA candles with paced request scheduling, transient retry hardening, a shared date-range window scheduler, and canonical CSV persistence.

For repo navigation, see [../README.md](../README.md). If you want to consume extractor output with the backtester, see [../backtester/README.md](../backtester/README.md).

## Features

- Full timeframe support from `S5` through `W`
- Fixed-universe Phase 9 batch CLI at `fetch_universe.py`
- Date-range fetching in deterministic 5000-candle windows
- Global request pacing with a default `119 rps` target
- Worker-local persistent API sessions with a `2 new connections/second` warm-up ceiling
- Memory + CSV caching with stale-series refresh and gap-only date-range fetches
- One shared date-range worker pool across all selected timeframes
- Retries for dropped connections, request timeouts, and retriable 5xx responses
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

### How To Use It

Use the extractor in this order:

1. Install the extractor requirements.
2. Put `OANDA_API_KEY`, `OANDA_ACCOUNT_ID`, and optionally `OANDA_ENVIRONMENT` in `oanda-candle-extractor/.env` or export them in your PowerShell session.
3. Decide whether you want one instrument with `extract_candles.py` or the fixed 16-instrument batch with `fetch_universe.py`.
4. Choose one mode:
   - recent candles with `--count`
   - explicit historical range with `--start-date` and `--end-date`
   - default last-365-days batch mode by running `fetch_universe.py` without either of those
5. Re-run the same command safely when data already exists:
   - date ranges reuse the existing CSV and fetch only missing gaps
   - count mode preserves the full CSV and only appends newer completed candles when needed
6. Check the generated CSVs under `oanda-candle-extractor/data/<INSTRUMENT>/`.

### CLI

From the repo root:

```powershell
python oanda-candle-extractor\extract_candles.py --help
python oanda-candle-extractor\extract_candles.py --validate
python oanda-candle-extractor\extract_candles.py --instrument XAU_USD --timeframes 1h --count 500
python oanda-candle-extractor\extract_candles.py --instrument EUR_USD --timeframes 5s --count 5000 --target-rps 119 --max-workers 16
python oanda-candle-extractor\extract_candles.py --instrument XAU_USD --start-date 2024-01-01 --end-date 2024-12-31 --timeframes 1h --target-rps 119 --max-workers 16
python oanda-candle-extractor\fetch_universe.py
python oanda-candle-extractor\fetch_universe.py --count 500
python oanda-candle-extractor\fetch_universe.py --start-date 2025-01-01 --end-date 2025-12-31 --target-rps 100 --max-workers 16
```

From inside `oanda-candle-extractor/`:

```powershell
python extract_candles.py --help
```

### 10 PowerShell Examples

```powershell
python oanda-candle-extractor\extract_candles.py --help
python oanda-candle-extractor\extract_candles.py --validate
python oanda-candle-extractor\extract_candles.py --instrument XAU_USD --timeframes 1h --count 500
python oanda-candle-extractor\extract_candles.py --instrument EUR_USD --timeframes 5s --count 5000 --target-rps 119 --max-workers 16
python oanda-candle-extractor\extract_candles.py --instrument EUR_USD --timeframes 1m 5m 1h --count 1500
python oanda-candle-extractor\extract_candles.py --instrument GBP_JPY --start-date 2025-01-01 --end-date 2025-03-31 --timeframes 15m 1h 4h
python oanda-candle-extractor\fetch_universe.py
python oanda-candle-extractor\fetch_universe.py --count 500
python oanda-candle-extractor\fetch_universe.py --start-date 2025-01-01 --end-date 2025-12-31 --target-rps 119 --max-workers 16
python oanda-candle-extractor\fetch_universe.py --timeframes 1m 5m 15m 1h 4h d --data-dir C:\temp\oanda-universe --log-level DEBUG
```

### Phase 9 Batch CLI

`fetch_universe.py` refreshes one fixed 16-instrument universe sequentially by instrument:

- `EUR_USD`, `USD_JPY`, `GBP_USD`, `AUD_USD`, `USD_CHF`, `USD_CAD`, `NZD_USD`
- `EUR_JPY`, `GBP_JPY`, `EUR_GBP`, `EUR_CHF`, `AUD_JPY`, `GBP_CHF`, `EUR_AUD`, `EUR_CAD`
- `XAU_USD`

Batch defaults:

- timeframes: `S5`, `M1`, `M5`, `M15`, `M30`, `H1`, `H4`, `D`, `W`
- mode: last 365 UTC days if neither `--count` nor `--start-date` / `--end-date` is supplied
- pacing: `100 rps`
- max workers: `16`

The batch wrapper never parallelizes across instruments. It reuses the extractor's existing inner concurrency for each instrument and exits non-zero if any instrument finishes with missing timeframe outputs or an unrecovered error.
If a batch rerun finds that a timeframe file already covers the requested data, it reuses that file instead of rewriting it and logs the result as `reused`. If newer completed candles are appended, it logs `updated`.

### Which CLI To Use

- Use `extract_candles.py` when you want one instrument and a custom timeframe subset.
- Use `fetch_universe.py` when you want the fixed Phase 9 universe in one repeatable batch run.
- Use `--count` when you want a fast refresh of recent candles.
- Use `--start-date` and `--end-date` when you need a bounded historical backfill.
- Use bare `fetch_universe.py` when you want the default last-365-days universe refresh.

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

## How The Extractor Works

At a high level, one run goes through these stages:

1. `extract_candles.py` parses the CLI arguments and normalizes the instrument and timeframe names.
2. `OANDACandleExtractor` resolves credentials from CLI args, environment variables, or `oanda-candle-extractor/.env`.
3. `OANDADataProvider` decides whether the request can be served from memory cache, CSV cache, or needs live API calls.
4. If API calls are needed, the provider turns the request into one or more fetch jobs.
5. Worker threads execute those jobs under one shared rate limiter.
6. Returned candle chunks are normalized, deduplicated, and written in chronological order.
7. Finished output is promoted into the canonical CSV path with an atomic rename, so partial files do not replace a good file.

The important design choice is that fetching is concurrent, but final CSV ordering is centralized and deterministic. Workers fetch data. The provider owns merge order, dedupe rules, and file promotion.

## Why Workers Exist

Workers are there because the bottleneck is not Python math, it is waiting on the OANDA API:

- Each request can return at most `5000` candles, so large date ranges must be split into many requests.
- Network latency means a single-threaded fetcher would spend most of its time waiting for responses.
- Different timeframes can all have missing data at the same time, so one shared pool keeps the connection pipeline busy instead of fetching each timeframe strictly one after another.
- The global rate limiter still caps total request pace, so adding workers improves overlap and utilization, not the allowed request ceiling.

In this codebase, a "worker" is a thread from `ThreadPoolExecutor`, not a separate process.

Each worker keeps its own OANDA API client in thread-local storage. That avoids creating a brand-new client for every request while still keeping sessions isolated per thread. New client creation is separately paced to `2 new connections/second` so worker startup does not spike connection churn.

## How Jobs Are Split

The extractor has two main fetch modes, and they split work differently.

### Count Mode

Count mode is the `--count` path for "give me the latest N candles".

If you request multiple timeframes in one count-mode CLI run, the extractor first splits work by timeframe. Each selected timeframe becomes one outer task submitted by `extract_all_timeframes()`. Inside that timeframe task, the provider either serves from cache, does one direct fetch, or performs a stale-tail refresh.

If a CSV already exists for that instrument and timeframe, the provider:

1. Loads the cached series.
2. Checks the last completed candle timestamp.
3. Plans only the missing tail from that candle up to `now`.
4. Splits that tail into chronological windows capped at `5000` candles each.
5. Fetches only those windows.
6. Merges the new rows into the existing full CSV without truncating older history.

If there is no usable cache, count mode is usually just one direct API request because the CLI already caps `--count` at `5000`.

### Date-Range Mode

Date-range mode is the `--start-date` plus `--end-date` path.

For each requested timeframe, the provider:

1. Loads the existing CSV if present.
2. Restricts it to the requested date range.
3. Splits cached rows into contiguous segments.
4. Detects gaps between those segments.
5. Plans only the uncovered gaps as fetch windows.
6. Caps every window at `5000` candles.
7. Marks only the first window with `includeFirst=True`; all later adjacent windows use `includeFirst=False` so the boundary candle is not duplicated.

If you request multiple timeframes in one date-range run, those timeframe-specific window lists are not executed in isolated pools. They are combined into one shared queue, and `max_workers` becomes one global in-flight ceiling across all selected timeframes.

## How The Shared Worker Scheduler Behaves

For date-range runs, the scheduler does not dump every window into the executor at once. It keeps a bounded set of in-flight tasks and refills it as work completes.

The flow is:

1. Build one range plan per timeframe.
2. Convert missing windows into `WindowTask` jobs.
3. Order timeframes by backlog size, so the most backlogged timeframe gets first access to the queue.
4. Submit jobs across timeframes into one shared executor until the in-flight cap is reached.
5. Wait for the first finished future.
6. As each finished future returns, record its result, drain any now-ready chronological writes for that timeframe, and immediately submit the next queued job if capacity is available.

This keeps workers busy without losing deterministic file order.

## What A Worker Does

One worker job is simple:

1. Reuse or create that thread's OANDA API client.
2. Wait for the shared request-rate limiter to grant a permit.
3. Make one candle request for one `(instrument, timeframe, from, to)` window.
4. Retry transient failures when appropriate.
5. Parse the API response into the canonical 14-column DataFrame shape.
6. Return the chunk to the main scheduler.

The worker does not decide final ordering, does not append directly to the canonical CSV, and does not merge frames across timeframes. That is deliberate. It prevents race conditions and keeps the persistence logic in one place.

## What Happens After A Worker Finishes A Job

When a worker finishes a window:

1. The completed future is collected by the scheduler.
2. The returned DataFrame is stored under that timeframe's `window_index`.
3. The ordered writer checks whether the next expected step is now available.
4. If earlier windows are already present, the provider appends every newly-ready chunk to that timeframe's staging `.tmp` file in chronological order.
5. If the finished window arrived early but an older window is still missing, the chunk waits in memory inside `pending_windows` until the missing earlier window finishes.
6. The executor thread becomes free and is reused for another queued window.

After all windows for a timeframe are written:

- the staging file is atomically promoted to `candles_<INSTRUMENT>_<TIMEFRAME>.csv`
- any previous canonical CSV is first moved to `.csv.bak`
- the merged result is also stored in the in-memory cache

If a shared date-range run fails partway through, the provider removes leftover `.tmp` files instead of leaving partial output behind.

## How Date-Range Fetching Works

When fetching a date range, the extractor now:

1. Loads the canonical CSV cache if present.
2. Reuses contiguous cached coverage inside the requested range and skips candles that are already present.
3. Plans only the uncovered gaps as chronological `from`/`to` windows capped at 5000 candles each.
4. Uses `includeFirst=False` on every window after the first boundary so adjacent windows do not duplicate the starting candle.
5. Schedules uncovered windows through one shared worker pool across all selected timeframes, writes each timeframe in chronological order to a staging CSV, and atomically promotes the finished file.

## Rate Limiting and Concurrency

- Default request pacing target: `119 requests/second`
- Default worker count: `16`
- For date-range jobs, `max_workers` is one global concurrent-window ceiling across all selected timeframes
- `max_workers` does not override the rate limiter; all workers still share one global `target_rps` ceiling
- New OANDA client creation is paced to `2 new connections/second`
- Transient transport failures now retry with capped exponential backoff and a fresh worker-local client when the connection drops
- Count-mode cache refresh fetches only new candles after the latest cached completed candle and preserves any broader existing CSV history
- Date-range cache hits return immediately only when the requested range is fully covered; otherwise only missing gaps are fetched
- Per-request OANDA transport logs are suppressed at the default `INFO` level; use `--log-level DEBUG` if you need request-by-request tracing

Real wall-clock throughput can still land below `119 rps` if network latency or server-side behavior dominates. The extractor is tuned so its own scheduler is not the first bottleneck.
For the Phase 9 batch CLI, the practical cost is dominated by `S5`. A 1-year full-universe run is supported, but plan around roughly `23-50 minutes` for the fixed 16-instrument core and about `0.73 GB` per instrument for the `S5` CSV alone, or roughly `1.46 GB` including the `.csv.bak`.

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
python oanda-candle-extractor\fetch_universe.py --help
python -m pytest tests\extractor -q
```

`--validate` performs a real API request and requires valid credentials plus network access.
