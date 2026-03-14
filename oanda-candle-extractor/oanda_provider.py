"""OANDA data provider with caching, paced rate limiting, and concurrent batching."""
from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import requests

from oandapyV20 import API
from oandapyV20.endpoints import instruments
from oandapyV20.exceptions import V20Error

from csv_persistence import CSVPersistence
from market_hours import MarketHours
from rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

RETRIABLE_V20_ERROR_CODES = frozenset({500, 502, 503, 504})


@dataclass(frozen=True)
class WindowRequest:
    """A deterministic candle request window."""

    index: int
    start: datetime
    end: datetime
    include_first: bool


@dataclass(frozen=True)
class RangePlanItem:
    """A chronological segment in a date-range fetch plan."""

    kind: str
    dataframe: Optional[pd.DataFrame] = None
    window_indexes: tuple[int, ...] = ()


@dataclass(frozen=True)
class WindowTask:
    """A fetchable window task in the shared multi-timeframe scheduler."""

    timeframe: str
    window_index: int
    start: datetime
    end: datetime
    include_first: bool


@dataclass(frozen=True)
class WriteStep:
    """One chronological write step for a timeframe result."""

    kind: str
    dataframe: Optional[pd.DataFrame] = None
    window_index: Optional[int] = None


@dataclass(frozen=True)
class TimeframeRangePlan:
    """Execution plan for one timeframe in a shared date-range fetch."""

    timeframe: str
    items: tuple[RangePlanItem, ...]
    windows: tuple[WindowRequest, ...]
    cached_range: pd.DataFrame


@dataclass
class RangeWriteState:
    """Mutable ordered-write state for one timeframe."""

    timeframe: str
    steps: list[WriteStep]
    staging_path: Optional[Path]
    pending_windows: dict[int, pd.DataFrame] = field(default_factory=dict)
    written_frames: list[pd.DataFrame] = field(default_factory=list)
    step_index: int = 0
    last_written_time: Optional[pd.Timestamp] = None


class OANDADataProvider:
    """
    OANDA data provider for candlestick data extraction.

    Features:
    - REST candle fetching with caching (memory + CSV)
    - Paced rate limiting with 429 backoff
    - Multi-timeframe support (5s to W)
    - Concurrent date-range batching with 5000 candle windows
    """

    TIMEFRAMES = ['S5', 'M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D', 'W']
    TIMEFRAME_SECONDS = {
        'S5': 5,
        'M1': 60,
        'M5': 300,
        'M15': 900,
        'M30': 1800,
        'H1': 3600,
        'H4': 14400,
        'D': 86400,
        'W': 604800,
    }
    MAX_CANDLES_PER_REQUEST = 5000
    EMPTY_COLUMNS = [
        'time', 'open', 'high', 'low', 'close', 'volume',
        'bid_open', 'bid_high', 'bid_low', 'bid_close',
        'ask_open', 'ask_high', 'ask_low', 'ask_close',
    ]

    def __init__(
        self,
        api_key: str,
        account_id: str,
        account_type: str = 'practice',
        data_dir: Optional[Path] = None,
        weekend_bypass: bool = False,
        target_rps: int = 119,
        max_workers: int = 16,
    ):
        """
        Initialize OANDA data provider.

        Args:
            api_key: OANDA API key
            account_id: OANDA account ID
            account_type: 'practice' or 'live'
            data_dir: Directory for CSV persistence
            weekend_bypass: Bypass market hours checks
            target_rps: Global request rate target
            max_workers: Maximum worker threads for concurrent fetches
        """
        self._api_key = api_key
        self._account_id = account_id
        self._account_type = account_type.lower()
        self._target_rps = target_rps
        self._max_workers = max_workers

        if self._account_type not in ('practice', 'live'):
            raise ValueError("account_type must be 'practice' or 'live'")
        if self._target_rps <= 0:
            raise ValueError("target_rps must be positive")
        if self._max_workers <= 0:
            raise ValueError("max_workers must be positive")

        self._rate_limiter = RateLimiter(max_requests=target_rps, window_seconds=1.0)
        self._client_warmup_limiter = RateLimiter(max_requests=2, window_seconds=1.0)
        self._csv = CSVPersistence(data_dir or Path('data'))
        self._market_hours = MarketHours(weekend_bypass=weekend_bypass)
        self._cache: Dict[tuple[str, str], dict[str, Any]] = {}
        self._min_cache_ttl_seconds = 30
        self._thread_state = threading.local()
        self._request_timeout_seconds = 30.0
        self._max_request_attempts = 4
        self._retry_base_delay_seconds = 0.5
        self._retry_max_delay_seconds = 8.0

        logger.info(
            "OANDADataProvider initialized for %s environment (target_rps=%s, max_workers=%s)",
            self._account_type,
            self._target_rps,
            self._max_workers,
        )

    def _get_api_client(self) -> API:
        """Get or create the worker-local API client."""
        client = getattr(self._thread_state, 'api_client', None)
        if client is None:
            if not self._client_warmup_limiter.acquire(timeout=self._request_timeout_seconds):
                raise RuntimeError("Timed out while waiting to open a new OANDA connection")
            client = API(access_token=self._api_key, environment=self._account_type)
            self._thread_state.api_client = client
        return client

    def _clear_api_client(self) -> None:
        """Drop the worker-local API client so the next attempt creates a fresh session."""
        if hasattr(self._thread_state, "api_client"):
            delattr(self._thread_state, "api_client")

    def _retry_delay_seconds(self, attempt_index: int) -> float:
        """Return a capped exponential backoff with light jitter."""
        base_delay = min(
            self._retry_max_delay_seconds,
            self._retry_base_delay_seconds * (2 ** attempt_index),
        )
        return base_delay + random.uniform(0.0, base_delay * 0.25)

    def _sleep_for_retry(self, error: Exception, attempt_index: int) -> None:
        """Sleep before retrying a transient request failure."""
        delay_seconds = self._retry_delay_seconds(attempt_index)
        logger.warning(
            "Transient OANDA request failure on attempt %s/%s (%s). Retrying in %.2fs",
            attempt_index + 1,
            self._max_request_attempts,
            error,
            delay_seconds,
        )
        time.sleep(delay_seconds)

    def _is_retriable_v20_error(self, error: V20Error) -> bool:
        """Whether an OANDA API response should be retried."""
        return error.code in RETRIABLE_V20_ERROR_CODES

    def _make_request(self, endpoint) -> dict:
        """
        Make an API request with paced rate limiting.

        Args:
            endpoint: oandapyV20 endpoint object

        Returns:
            Response data
        """
        last_error: Exception | None = None

        for attempt_index in range(self._max_request_attempts):
            if not self._rate_limiter.acquire(timeout=self._request_timeout_seconds):
                raise RuntimeError("Rate limit timeout - too many requests")

            client = self._get_api_client()
            try:
                response = client.request(endpoint)
                self._rate_limiter.record_success()
                return response
            except V20Error as error:
                last_error = error
                if error.code == 429:
                    self._rate_limiter.record_429(self._extract_retry_after_seconds(error))
                    if attempt_index == self._max_request_attempts - 1:
                        raise RuntimeError("Rate limit retries exhausted") from error
                    continue
                if self._is_retriable_v20_error(error):
                    if attempt_index == self._max_request_attempts - 1:
                        raise
                    self._sleep_for_retry(error, attempt_index)
                    continue
                raise
            except requests.RequestException as error:
                last_error = error
                self._clear_api_client()
                if attempt_index == self._max_request_attempts - 1:
                    raise
                self._sleep_for_retry(error, attempt_index)
                continue

        raise RuntimeError("OANDA request retries exhausted") from last_error

    def _extract_retry_after_seconds(self, error: V20Error) -> Optional[float]:
        """Best-effort Retry-After extraction from an API error."""
        retry_after = getattr(error, 'retry_after', None)
        if retry_after is not None:
            try:
                return float(retry_after)
            except (TypeError, ValueError):
                return None

        headers = getattr(error, 'headers', None)
        if isinstance(headers, dict) and 'Retry-After' in headers:
            try:
                return float(headers['Retry-After'])
            except (TypeError, ValueError):
                return None
        return None

    def _empty_frame(self) -> pd.DataFrame:
        """Return an empty candle DataFrame with the canonical columns."""
        return pd.DataFrame(columns=self.EMPTY_COLUMNS)

    def _normalize_frame(
        self,
        df: Optional[pd.DataFrame],
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Sort, deduplicate, and optionally filter a candle frame."""
        if df is None or df.empty:
            return self._empty_frame()

        normalized = df.copy()
        if 'time' in normalized.columns and not pd.api.types.is_datetime64_any_dtype(normalized['time']):
            normalized['time'] = pd.to_datetime(normalized['time'], utc=True)

        normalized = normalized.sort_values('time').drop_duplicates(subset=['time'], keep='last')
        if start is not None:
            normalized = normalized[normalized['time'] >= start]
        if end is not None:
            normalized = normalized[normalized['time'] <= end]
        return normalized.reset_index(drop=True)

    def _merge_frames(self, *frames: Optional[pd.DataFrame]) -> pd.DataFrame:
        """Merge multiple candle DataFrames into one sorted, deduplicated frame."""
        non_empty = [frame for frame in frames if frame is not None and not frame.empty]
        if not non_empty:
            return self._empty_frame()
        combined = pd.concat(non_empty, ignore_index=True)
        return self._normalize_frame(combined)

    def _format_datetime(self, value: datetime) -> str:
        """Format a datetime for the OANDA API."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat(timespec='microseconds').replace('+00:00', 'Z')

    def _parse_candles(self, candles: list[dict[str, Any]]) -> pd.DataFrame:
        """Parse raw OANDA candles into the canonical DataFrame shape."""
        records = []
        for candle in candles:
            if not candle.get('complete', True):
                continue
            mid = candle.get('mid', {})
            bid = candle.get('bid', {})
            ask = candle.get('ask', {})
            records.append({
                'time': candle['time'],
                'open': float(mid.get('o', 0)),
                'high': float(mid.get('h', 0)),
                'low': float(mid.get('l', 0)),
                'close': float(mid.get('c', 0)),
                'bid_open': float(bid.get('o', 0)),
                'bid_high': float(bid.get('h', 0)),
                'bid_low': float(bid.get('l', 0)),
                'bid_close': float(bid.get('c', 0)),
                'ask_open': float(ask.get('o', 0)),
                'ask_high': float(ask.get('h', 0)),
                'ask_low': float(ask.get('l', 0)),
                'ask_close': float(ask.get('c', 0)),
                'volume': int(candle.get('volume', 0)),
            })

        if not records:
            return self._empty_frame()

        frame = pd.DataFrame.from_records(records, columns=self.EMPTY_COLUMNS)
        frame['time'] = pd.to_datetime(frame['time'], utc=True)
        return self._normalize_frame(frame)

    def _fetch_candles_from_api(
        self,
        instrument: str,
        timeframe: str,
        count: int,
    ) -> pd.DataFrame:
        """Fetch the most recent candles directly from the OANDA API."""
        params = {
            'granularity': timeframe,
            'count': min(count, self.MAX_CANDLES_PER_REQUEST),
            'price': 'MBA',
        }
        endpoint = instruments.InstrumentsCandles(instrument=instrument, params=params)
        response = self._make_request(endpoint)
        candles = response.get('candles', [])
        if not candles:
            logger.warning("No candles returned for %s/%s", instrument, timeframe)
            return self._empty_frame()
        return self._parse_candles(candles)

    def _fetch_window(
        self,
        instrument: str,
        timeframe: str,
        window: WindowRequest,
    ) -> pd.DataFrame:
        """Fetch candles for a specific chronological window."""
        params = {
            'granularity': timeframe,
            'price': 'MBA',
            'from': self._format_datetime(window.start),
            'to': self._format_datetime(window.end),
            'includeFirst': window.include_first,
        }
        endpoint = instruments.InstrumentsCandles(instrument=instrument, params=params)
        response = self._make_request(endpoint)
        return self._normalize_frame(
            self._parse_candles(response.get('candles', [])),
            start=window.start,
            end=window.end,
        )

    def _fetch_window_results(
        self,
        instrument: str,
        timeframe: str,
        windows: list[WindowRequest],
        max_workers: int,
    ) -> dict[int, pd.DataFrame]:
        """Fetch multiple windows, using concurrency when it is beneficial."""
        if not windows:
            return {}

        worker_count = max(1, min(max_workers, len(windows)))
        if worker_count == 1:
            return {window.index: self._fetch_window(instrument, timeframe, window) for window in windows}

        results: dict[int, pd.DataFrame] = {}
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(self._fetch_window, instrument, timeframe, window): window.index
                for window in windows
            }
            for future in as_completed(future_map):
                results[future_map[future]] = future.result()
        return results

    def _get_cache_ttl_seconds(self, timeframe: str) -> int:
        """Get the memory cache TTL based on timeframe granularity."""
        return max(self._min_cache_ttl_seconds, self.TIMEFRAME_SECONDS.get(timeframe.upper(), 300))

    def _get_from_cache(self, key: tuple[str, str]) -> Optional[pd.DataFrame]:
        """Get data from memory cache if not expired."""
        entry = self._cache.get(key)
        if entry and time_has_not_expired(entry['expires']):
            return entry['df']
        if entry:
            del self._cache[key]
        return None

    def _set_cache(self, key: tuple[str, str], df: pd.DataFrame) -> None:
        """Set data in memory cache with TTL."""
        timeframe = key[1]
        ttl_seconds = self._get_cache_ttl_seconds(timeframe)
        self._cache[key] = {
            'df': self._normalize_frame(df),
            'expires': monotonic_now() + ttl_seconds,
        }

    def _is_series_fresh(
        self,
        df: Optional[pd.DataFrame],
        timeframe: str,
        reference_time: Optional[datetime] = None,
    ) -> bool:
        """Whether a cached series is fresh enough to serve without refresh."""
        if df is None or df.empty:
            return False

        reference = reference_time or datetime.now(timezone.utc)
        latest_time = df['time'].max()
        latest_pydt = latest_time.to_pydatetime() if hasattr(latest_time, 'to_pydatetime') else latest_time
        age = reference - latest_pydt
        return age < timedelta(seconds=self.TIMEFRAME_SECONDS[timeframe])

    def _plan_windows(
        self,
        start: datetime,
        end: datetime,
        timeframe: str,
        include_first_initial: bool,
        start_index: int,
    ) -> list[WindowRequest]:
        """Plan deterministic chronological windows capped at 5000 candles each."""
        if end <= start:
            return []

        span_seconds = self.TIMEFRAME_SECONDS[timeframe] * self.MAX_CANDLES_PER_REQUEST
        max_span = timedelta(seconds=span_seconds)
        windows: list[WindowRequest] = []
        cursor = start
        include_first = include_first_initial
        index = start_index

        while cursor < end:
            window_end = min(cursor + max_span, end)
            windows.append(
                WindowRequest(
                    index=index,
                    start=cursor,
                    end=window_end,
                    include_first=include_first,
                )
            )
            cursor = window_end
            include_first = False
            index += 1

        return windows

    def _split_cached_segments(self, df: pd.DataFrame, timeframe: str) -> list[pd.DataFrame]:
        """Split a cached frame into contiguous segments for gap detection."""
        normalized = self._normalize_frame(df)
        if normalized.empty:
            return []

        step = pd.Timedelta(seconds=self.TIMEFRAME_SECONDS[timeframe])
        segments: list[pd.DataFrame] = []
        start_idx = 0
        times = normalized['time'].tolist()

        for idx in range(1, len(times)):
            if times[idx] - times[idx - 1] > step:
                segments.append(normalized.iloc[start_idx:idx].reset_index(drop=True))
                start_idx = idx

        segments.append(normalized.iloc[start_idx:].reset_index(drop=True))
        return segments

    def _build_range_plan(
        self,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        cached_range: pd.DataFrame,
    ) -> tuple[list[RangePlanItem], list[WindowRequest]]:
        """Build the chronological merge plan for a date-range request."""
        items: list[RangePlanItem] = []
        windows: list[WindowRequest] = []
        segments = self._split_cached_segments(cached_range, timeframe)
        cursor = start_date
        window_index = 0
        first_fetch = True

        if not segments:
            planned = self._plan_windows(start_date, end_date, timeframe, include_first_initial=True, start_index=0)
            if planned:
                items.append(RangePlanItem(kind='fetch', window_indexes=tuple(window.index for window in planned)))
            return items, planned

        for segment in segments:
            segment_start = segment['time'].iloc[0].to_pydatetime()
            segment_end = segment['time'].iloc[-1].to_pydatetime()

            if segment_start > cursor:
                planned = self._plan_windows(
                    cursor,
                    segment_start,
                    timeframe,
                    include_first_initial=first_fetch,
                    start_index=window_index,
                )
                if planned:
                    items.append(RangePlanItem(kind='fetch', window_indexes=tuple(window.index for window in planned)))
                    windows.extend(planned)
                    window_index += len(planned)
                    first_fetch = False

            items.append(RangePlanItem(kind='cached', dataframe=segment))
            cursor = max(cursor, segment_end)
            first_fetch = False

        if cursor < end_date:
            planned = self._plan_windows(
                cursor,
                end_date,
                timeframe,
                include_first_initial=False,
                start_index=window_index,
            )
            if planned:
                items.append(RangePlanItem(kind='fetch', window_indexes=tuple(window.index for window in planned)))
                windows.extend(planned)

        return items, windows

    def _plan_timeframe_range(
        self,
        instrument: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        use_cache: bool,
    ) -> TimeframeRangePlan:
        """Plan one timeframe's cache reuse and missing-window fetches."""
        cached_range = self._empty_frame()

        if use_cache:
            csv_data = self._csv.load_candles(instrument, timeframe)
            if csv_data is not None and not csv_data.empty:
                cached_range = self._normalize_frame(csv_data, start=start_date, end=end_date)

        items, windows = self._build_range_plan(timeframe, start_date, end_date, cached_range)
        return TimeframeRangePlan(
            timeframe=timeframe,
            items=tuple(items),
            windows=tuple(windows),
            cached_range=cached_range,
        )

    def _build_write_steps(self, items: tuple[RangePlanItem, ...] | list[RangePlanItem]) -> list[WriteStep]:
        """Flatten a range plan into chronological write steps."""
        steps: list[WriteStep] = []
        for item in items:
            if item.kind == 'cached':
                steps.append(WriteStep(kind='cached', dataframe=item.dataframe))
                continue

            for window_index in item.window_indexes:
                steps.append(WriteStep(kind='fetch', window_index=window_index))
        return steps

    def _fetch_window_task(self, instrument: str, task: WindowTask) -> pd.DataFrame:
        """Fetch one scheduled window task."""
        return self._fetch_window(
            instrument,
            task.timeframe,
            WindowRequest(
                index=task.window_index,
                start=task.start,
                end=task.end,
                include_first=task.include_first,
            ),
        )

    def _write_chunk_to_state(
        self,
        instrument: str,
        state: RangeWriteState,
        chunk: Optional[pd.DataFrame],
    ) -> None:
        """Append one normalized chunk to a timeframe's ordered write state."""
        normalized = self._normalize_frame(chunk)
        if state.last_written_time is not None:
            normalized = normalized[normalized['time'] > state.last_written_time]
        if normalized.empty:
            return

        if state.staging_path is not None and not self._csv.append_to_path(normalized, state.staging_path):
            raise RuntimeError(f"Failed to write staged candles for {instrument}/{state.timeframe}")

        state.written_frames.append(normalized)
        state.last_written_time = normalized['time'].iloc[-1]

    def _drain_write_state(self, instrument: str, state: RangeWriteState) -> None:
        """Write every currently-ready chronological step for one timeframe."""
        while state.step_index < len(state.steps):
            step = state.steps[state.step_index]
            if step.kind == 'cached':
                self._write_chunk_to_state(instrument, state, step.dataframe)
                state.step_index += 1
                continue

            assert step.window_index is not None
            if step.window_index not in state.pending_windows:
                break

            chunk = state.pending_windows.pop(step.window_index)
            self._write_chunk_to_state(instrument, state, chunk)
            state.step_index += 1

    def _finalize_write_state(
        self,
        instrument: str,
        state: RangeWriteState,
        use_cache: bool,
    ) -> pd.DataFrame:
        """Finalize one timeframe's ordered writer and return the merged frame."""
        self._drain_write_state(instrument, state)

        if state.step_index != len(state.steps):
            raise RuntimeError(f"Incomplete date-range write state for {instrument}/{state.timeframe}")

        if use_cache and state.staging_path is not None:
            if state.written_frames:
                if not self._csv.promote_staging_file(state.staging_path, instrument, state.timeframe):
                    raise RuntimeError(f"Failed to promote staged candles for {instrument}/{state.timeframe}")
            elif state.staging_path.exists():
                state.staging_path.unlink()

        return self._merge_frames(*state.written_frames)

    def _cleanup_range_staging_files(self, states: Dict[str, RangeWriteState]) -> None:
        """Remove leftover staging files after a failed shared date-range run."""
        for state in states.values():
            if state.staging_path is None:
                continue
            if state.staging_path.exists():
                try:
                    state.staging_path.unlink()
                except OSError:
                    logger.warning("Failed cleaning staging file %s", state.staging_path)

    def _submit_window_futures(
        self,
        executor: ThreadPoolExecutor,
        instrument: str,
        ordered_timeframes: list[str],
        pending_by_timeframe: Dict[str, deque[WindowTask]],
        future_map: dict,
        max_in_flight: int,
    ) -> None:
        """Keep a bounded global window queue filled across timeframes."""
        while len(future_map) < max_in_flight:
            submitted = False
            for timeframe in ordered_timeframes:
                queue = pending_by_timeframe.get(timeframe)
                if not queue:
                    continue

                task = queue.popleft()
                future = executor.submit(self._fetch_window_task, instrument, task)
                future_map[future] = task
                submitted = True

                if len(future_map) >= max_in_flight:
                    break

            if not submitted:
                break

    def _execute_timeframe_range_plans(
        self,
        instrument: str,
        ordered_timeframes: list[str],
        plans: Dict[str, TimeframeRangePlan],
        use_cache: bool,
        max_workers: int,
    ) -> Dict[str, pd.DataFrame]:
        """Execute one or more timeframe range plans on a shared worker pool."""
        results: Dict[str, pd.DataFrame] = {}
        states: Dict[str, RangeWriteState] = {}
        pending_by_timeframe: Dict[str, deque[WindowTask]] = {}

        for timeframe in ordered_timeframes:
            plan = plans[timeframe]
            if not plan.windows:
                results[timeframe] = plan.cached_range.copy()
                continue

            state = RangeWriteState(
                timeframe=timeframe,
                steps=self._build_write_steps(plan.items),
                staging_path=self._csv.start_staging_file(instrument, timeframe) if use_cache else None,
            )
            self._drain_write_state(instrument, state)
            states[timeframe] = state
            pending_by_timeframe[timeframe] = deque(
                WindowTask(
                    timeframe=timeframe,
                    window_index=window.index,
                    start=window.start,
                    end=window.end,
                    include_first=window.include_first,
                )
                for window in plan.windows
            )

        if states:
            schedule_order = sorted(states, key=lambda key: len(pending_by_timeframe[key]), reverse=True)
            total_windows = sum(len(queue) for queue in pending_by_timeframe.values())
            worker_count = max(1, min(max_workers, total_windows))
            max_in_flight = min(total_windows, max(worker_count, worker_count * 4))
            executor = ThreadPoolExecutor(max_workers=worker_count)
            future_map: dict = {}

            try:
                self._submit_window_futures(
                    executor,
                    instrument,
                    schedule_order,
                    pending_by_timeframe,
                    future_map,
                    max_in_flight,
                )

                while future_map:
                    done, _ = wait(tuple(future_map), return_when=FIRST_COMPLETED)
                    for future in done:
                        task = future_map.pop(future)
                        state = states[task.timeframe]
                        state.pending_windows[task.window_index] = future.result()
                        self._drain_write_state(instrument, state)

                    self._submit_window_futures(
                        executor,
                        instrument,
                        schedule_order,
                        pending_by_timeframe,
                        future_map,
                        max_in_flight,
                    )
            except Exception:
                executor.shutdown(wait=False, cancel_futures=True)
                self._cleanup_range_staging_files(states)
                raise
            else:
                executor.shutdown(wait=True)

            for timeframe, state in states.items():
                results[timeframe] = self._finalize_write_state(instrument, state, use_cache)

        for timeframe, result in results.items():
            if use_cache and not result.empty:
                self._set_cache((instrument.upper(), timeframe.upper()), result)

        return results

    def _write_date_range_result(
        self,
        instrument: str,
        timeframe: str,
        items: list[RangePlanItem],
        fetched_windows: dict[int, pd.DataFrame],
        use_cache: bool,
    ) -> pd.DataFrame:
        """Write the merged date-range result in chronological order."""
        state = RangeWriteState(
            timeframe=timeframe,
            steps=self._build_write_steps(items),
            staging_path=self._csv.start_staging_file(instrument, timeframe) if use_cache else None,
        )
        self._drain_write_state(instrument, state)
        state.pending_windows.update(fetched_windows)
        return self._finalize_write_state(instrument, state, use_cache)

    def _refresh_cached_series(
        self,
        instrument: str,
        timeframe: str,
        cached_df: pd.DataFrame,
        max_workers: int,
    ) -> pd.DataFrame:
        """Refresh a cached count-mode series by fetching only new candles."""
        normalized = self._normalize_frame(cached_df)
        if normalized.empty:
            return normalized

        latest_time = normalized['time'].iloc[-1].to_pydatetime()
        refresh_end = datetime.now(timezone.utc)
        windows = self._plan_windows(
            latest_time,
            refresh_end,
            timeframe,
            include_first_initial=False,
            start_index=0,
        )

        if not windows:
            return normalized

        updates = self._fetch_window_results(instrument, timeframe, windows, max_workers)
        merged = self._merge_frames(normalized, *updates.values())
        if not merged.equals(normalized):
            self._csv.save_candles(merged, instrument, timeframe)
        return merged

    def fetch_candles(
        self,
        instrument: str,
        timeframe: str,
        count: int = 500,
        use_cache: bool = True,
        max_workers: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candles with caching layer.

        Cache hierarchy:
        1. Memory cache (short-term)
        2. CSV persistence with freshness checks
        3. REST API (on miss)
        """
        if timeframe not in self.TIMEFRAMES:
            raise ValueError(f"Invalid timeframe: {timeframe}. Must be one of {self.TIMEFRAMES}")

        count = min(count, self.MAX_CANDLES_PER_REQUEST)
        worker_limit = max_workers or self._max_workers
        cache_key = (instrument.upper(), timeframe.upper())

        if use_cache:
            cached = self._get_from_cache(cache_key)
            if cached is not None and len(cached) >= count and self._is_series_fresh(cached, timeframe):
                logger.debug("Memory cache hit for %s/%s", instrument, timeframe)
                return cached.tail(count).copy()

        csv_data = self._csv.load_candles(instrument, timeframe) if use_cache else None
        if csv_data is not None and not csv_data.empty:
            refreshed = self._refresh_cached_series(instrument, timeframe, csv_data, worker_limit)
            if use_cache:
                self._set_cache(cache_key, refreshed)
            if len(refreshed) >= count:
                logger.debug("CSV cache hit for %s/%s after refresh", instrument, timeframe)
                return refreshed.tail(count).copy()

        logger.info("Fetching %s %s candles for %s from API", count, timeframe, instrument)
        df = self._fetch_candles_from_api(instrument, timeframe, count)

        if use_cache and not df.empty:
            self._set_cache(cache_key, df)
            self._csv.save_candles(df, instrument, timeframe)

        return df

    def fetch_candles_by_date_range(
        self,
        instrument: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        use_cache: bool = True,
        max_workers: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Fetch candles for a specific date range with concurrent batching.

        Missing ranges are planned forward in deterministic 5000-candle windows.
        Cached coverage is reused when contiguous; uncovered gaps are fetched only.
        """
        normalized_timeframe = timeframe.upper()
        results = self.fetch_timeframes_by_date_range(
            instrument=instrument,
            timeframes=[normalized_timeframe],
            start_date=start_date,
            end_date=end_date,
            use_cache=use_cache,
            max_workers=max_workers,
        )
        return results.get(normalized_timeframe, self._empty_frame())

    def fetch_timeframes_by_date_range(
        self,
        instrument: str,
        timeframes: list[str],
        start_date: datetime,
        end_date: datetime,
        use_cache: bool = True,
        max_workers: Optional[int] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch one instrument across multiple timeframes on a shared window scheduler.

        The configured worker limit is global across all selected timeframes.
        """
        selected = [timeframe.upper() for timeframe in timeframes]
        if not selected:
            return {}
        for timeframe in selected:
            if timeframe not in self.TIMEFRAMES:
                raise ValueError(f"Invalid timeframe: {timeframe}. Must be one of {self.TIMEFRAMES}")

        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        if end_date <= start_date:
            return {timeframe: self._empty_frame() for timeframe in selected}

        worker_limit = max_workers or self._max_workers
        plans = {
            timeframe: self._plan_timeframe_range(
                instrument=instrument,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                use_cache=use_cache,
            )
            for timeframe in selected
        }
        results = self._execute_timeframe_range_plans(
            instrument=instrument,
            ordered_timeframes=selected,
            plans=plans,
            use_cache=use_cache,
            max_workers=worker_limit,
        )

        for timeframe in selected:
            result = results.get(timeframe, self._empty_frame())
            logger.info(
                "Fetched %s candles for %s/%s from %s to %s",
                len(result),
                instrument,
                timeframe,
                start_date,
                end_date,
            )
            results[timeframe] = result

        return results

    def clear_cache(self, instrument: Optional[str] = None, timeframe: Optional[str] = None) -> int:
        """Clear memory cache."""
        if instrument is None and timeframe is None:
            count = len(self._cache)
            self._cache.clear()
            return count

        keys_to_delete = []
        for key in self._cache:
            inst, tf = key[0], key[1]
            if (instrument is None or inst == instrument) and (timeframe is None or tf == timeframe):
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del self._cache[key]

        return len(keys_to_delete)

    def validate_connection(self) -> bool:
        """Validate API connection and credentials."""
        try:
            params = {
                'granularity': 'H1',
                'count': 1,
                'price': 'M',
            }
            endpoint = instruments.InstrumentsCandles(instrument='EUR_USD', params=params)
            response = self._make_request(endpoint)
            candles = response.get('candles', [])
            if candles:
                logger.info("OANDA connection validated successfully")
                return True

            logger.error("OANDA connection validation failed: no data returned")
            return False
        except Exception as error:
            logger.error(f"OANDA connection validation failed: {error}")
            return False


def monotonic_now() -> float:
    """Wrapper to keep the cache timestamp source easy to patch in tests."""
    return time.monotonic()


def time_has_not_expired(expires_at: float) -> bool:
    """Wrapper to keep cache expiry checks easy to patch in tests."""
    return monotonic_now() < expires_at
