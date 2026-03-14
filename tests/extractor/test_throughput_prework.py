from __future__ import annotations

import threading
import time as pytime
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import extract_candles
import oanda_provider
import rate_limiter
from csv_persistence import CSVPersistence


def _frame_for_task(provider, task, make_candle_frame, base_price=1.1000):
    step_seconds = provider.TIMEFRAME_SECONDS[task.timeframe]
    candle_time = task.start if task.include_first else task.start + timedelta(seconds=step_seconds)
    if candle_time >= task.end:
        return provider._empty_frame()
    return make_candle_frame(candle_time, periods=1, step_seconds=step_seconds, base_price=base_price)


def test_rate_limiter_allows_full_normal_capacity(monkeypatch):
    clock = {"now": 0.0}

    def fake_monotonic() -> float:
        return clock["now"]

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(rate_limiter.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(rate_limiter.time, "sleep", fake_sleep)

    limiter = rate_limiter.RateLimiter(max_requests=119, window_seconds=1.0)
    for _ in range(119):
        assert limiter.acquire(timeout=1.0)

    assert limiter.get_current_rate() == pytest.approx(119.0)


def test_rate_limiter_uses_retry_after_backoff(monkeypatch):
    clock = {"now": 0.0}

    def fake_monotonic() -> float:
        return clock["now"]

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(rate_limiter.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(rate_limiter.time, "sleep", fake_sleep)

    limiter = rate_limiter.RateLimiter(max_requests=119, window_seconds=1.0)
    assert limiter.acquire(timeout=0.0)
    limiter.record_429(retry_after_seconds=2.5)

    start = clock["now"]
    assert limiter.acquire(timeout=3.0)
    assert clock["now"] - start == pytest.approx(2.5, abs=1e-6)


def test_extractor_auto_loads_local_env_file(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("OANDA_API_KEY=test_key\nOANDA_ACCOUNT_ID=test_account\n", encoding="utf-8")

    class DummyProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(extract_candles, "DEFAULT_ENV_FILE", env_path)
    monkeypatch.setattr(extract_candles, "OANDADataProvider", DummyProvider)
    monkeypatch.delenv("OANDA_API_KEY", raising=False)
    monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)

    extractor = extract_candles.OANDACandleExtractor(data_dir=tmp_path / "data")

    assert extractor.api_key == "test_key"
    assert extractor.account_id == "test_account"


def test_extractor_honors_oanda_environment_from_env_file(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OANDA_API_KEY=test_key\nOANDA_ACCOUNT_ID=test_account\nOANDA_ENVIRONMENT=live\n",
        encoding="utf-8",
    )

    class DummyProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(extract_candles, "DEFAULT_ENV_FILE", env_path)
    monkeypatch.setattr(extract_candles, "OANDADataProvider", DummyProvider)
    monkeypatch.delenv("OANDA_API_KEY", raising=False)
    monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("OANDA_ENVIRONMENT", raising=False)

    extractor = extract_candles.OANDACandleExtractor(data_dir=tmp_path / "data")

    assert extractor.account_type == "live"


def test_window_planner_uses_include_first_only_on_first_window(tmp_path):
    provider = oanda_provider.OANDADataProvider(
        api_key="token",
        account_id="account",
        data_dir=tmp_path,
    )
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=10050)

    windows = provider._plan_windows(start, end, "M1", include_first_initial=True, start_index=0)

    assert len(windows) == 3
    assert [window.include_first for window in windows] == [True, False, False]
    assert windows[0].end == windows[1].start
    assert windows[1].end == windows[2].start


def test_canonical_candle_path_is_nested_per_instrument(tmp_path):
    csv = CSVPersistence(tmp_path)
    path = csv.get_candle_path("EUR_USD", "H1")

    assert path == tmp_path / "EUR_USD" / "candles_EUR_USD_H1.csv"


def test_load_candles_migrates_legacy_flat_file(tmp_path, make_candle_frame):
    csv = CSVPersistence(tmp_path)
    legacy_path = tmp_path / "candles_EUR_USD_H1.csv"
    frame = make_candle_frame(datetime(2024, 1, 1, tzinfo=timezone.utc), periods=3, step_seconds=3600)
    frame.to_csv(legacy_path, index=False)

    loaded = csv.load_candles("EUR_USD", "H1")
    canonical_path = csv.get_candle_path("EUR_USD", "H1")

    assert loaded is not None
    assert canonical_path.exists()
    assert not legacy_path.exists()
    assert list(loaded["time"]) == list(frame["time"])


def test_append_and_staging_files_live_in_instrument_folder(tmp_path, make_candle_frame):
    csv = CSVPersistence(tmp_path)
    frame = make_candle_frame(datetime(2024, 1, 1, tzinfo=timezone.utc), periods=2, step_seconds=60)

    staging_path = csv.start_staging_file("EUR_USD", "M1")
    assert staging_path == tmp_path / "EUR_USD" / "candles_EUR_USD_M1.tmp"

    assert csv.append_candles(frame, "EUR_USD", "M1")
    assert csv.get_candle_path("EUR_USD", "M1").exists()


def test_bulk_migration_and_usd_jpy_cleanup_targets_only_requested_files(tmp_path, make_candle_frame):
    csv = CSVPersistence(tmp_path)
    eur = make_candle_frame(datetime(2024, 1, 1, tzinfo=timezone.utc), periods=2, step_seconds=3600)
    jpy = make_candle_frame(datetime(2024, 1, 1, tzinfo=timezone.utc), periods=2, step_seconds=3600)

    eur_legacy = tmp_path / "candles_EUR_USD_H1.csv"
    jpy_legacy = tmp_path / "candles_USD_JPY_H1.csv"
    eur.to_csv(eur_legacy, index=False)
    jpy.to_csv(jpy_legacy, index=False)

    migrated = csv.migrate_legacy_files(instrument="EUR_USD")
    assert migrated == [tmp_path / "EUR_USD" / "candles_EUR_USD_H1.csv"]
    assert (tmp_path / "EUR_USD" / "candles_EUR_USD_H1.csv").exists()
    assert jpy_legacy.exists()


def test_fetch_candles_refreshes_stale_csv_incrementally(tmp_path, monkeypatch, make_candle_frame):
    provider = oanda_provider.OANDADataProvider(
        api_key="token",
        account_id="account",
        data_dir=tmp_path,
    )
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    cached = make_candle_frame(start, periods=3, step_seconds=60)
    provider._csv.save_candles(cached, "EUR_USD", "M1")

    fixed_now = start + timedelta(minutes=5)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(oanda_provider, "datetime", FixedDateTime)

    updates = make_candle_frame(start + timedelta(minutes=3), periods=2, step_seconds=60, base_price=1.1030)
    captured = {}

    def fake_fetch_window_results(instrument, timeframe, windows, max_workers):
        captured["windows"] = windows
        return {windows[0].index: updates}

    monkeypatch.setattr(provider, "_fetch_window_results", fake_fetch_window_results)
    monkeypatch.setattr(
        provider,
        "_fetch_candles_from_api",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected direct API fetch")),
    )

    result = provider.fetch_candles("EUR_USD", "M1", count=3)
    saved = provider._csv.load_candles("EUR_USD", "M1")

    assert captured["windows"][0].include_first is False
    assert list(result["time"]) == list(saved.tail(3)["time"])
    assert len(saved) == 5
    assert saved["time"].is_monotonic_increasing


def test_extract_to_csv_preserves_broader_cached_history_in_count_mode(tmp_path, monkeypatch, make_candle_frame):
    class DummyProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(extract_candles, "OANDADataProvider", DummyProvider)

    extractor = extract_candles.OANDACandleExtractor(
        api_key="token",
        account_id="account",
        data_dir=tmp_path,
    )
    full = make_candle_frame(datetime(2024, 1, 1, tzinfo=timezone.utc), periods=6, step_seconds=60)
    extractor.csv.save_candles(full, "EUR_USD", "M1")
    narrower = full.tail(3).reset_index(drop=True)

    monkeypatch.setattr(extractor, "fetch_candles", lambda **kwargs: narrower)

    output = extractor.extract_to_csv("EUR_USD", "1m", count=3)
    saved = extractor.csv.load_candles("EUR_USD", "M1")

    assert output == tmp_path / "EUR_USD" / "candles_EUR_USD_M1.csv"
    assert saved is not None
    assert len(saved) == 6
    assert list(saved["time"]) == list(full["time"])


def test_extract_to_csv_appends_new_candles_without_truncating_cached_history(
    tmp_path,
    monkeypatch,
    make_candle_frame,
):
    extractor = extract_candles.OANDACandleExtractor(
        api_key="token",
        account_id="account",
        data_dir=tmp_path,
    )
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    cached = make_candle_frame(start, periods=5, step_seconds=60)
    extractor.csv.save_candles(cached, "EUR_USD", "M1")

    fixed_now = start + timedelta(minutes=7)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(oanda_provider, "datetime", FixedDateTime)

    updates = make_candle_frame(start + timedelta(minutes=5), periods=2, step_seconds=60, base_price=1.1070)

    def fake_fetch_window_results(instrument, timeframe, windows, max_workers):
        return {windows[0].index: updates}

    monkeypatch.setattr(extractor.provider, "_fetch_window_results", fake_fetch_window_results)
    monkeypatch.setattr(
        extractor.provider,
        "_fetch_candles_from_api",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected direct API fetch")),
    )

    output = extractor.extract_to_csv("EUR_USD", "1m", count=3)
    saved = extractor.csv.load_candles("EUR_USD", "M1")

    assert output == tmp_path / "EUR_USD" / "candles_EUR_USD_M1.csv"
    assert saved is not None
    assert len(saved) == 7
    assert saved["time"].is_monotonic_increasing
    assert list(saved["time"]) == list(extractor.provider._merge_frames(cached, updates)["time"])


def test_fetch_candles_by_date_range_fetches_only_missing_gap(tmp_path, monkeypatch, make_candle_frame):
    provider = oanda_provider.OANDADataProvider(
        api_key="token",
        account_id="account",
        data_dir=tmp_path,
    )
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    full = make_candle_frame(start, periods=6, step_seconds=60)
    cached = pd.concat([full.iloc[:2], full.iloc[4:]], ignore_index=True)
    provider._csv.save_candles(cached, "EUR_USD", "M1")

    captured = []

    def fake_fetch_window_task(instrument, task):
        captured.append(task)
        return full.iloc[2:5].reset_index(drop=True)

    monkeypatch.setattr(provider, "_fetch_window_task", fake_fetch_window_task)

    result = provider.fetch_candles_by_date_range(
        "EUR_USD",
        "M1",
        start_date=full["time"].iloc[0].to_pydatetime(),
        end_date=full["time"].iloc[-1].to_pydatetime(),
    )

    assert len(captured) == 1
    assert captured[0].include_first is False
    assert captured[0].start == full["time"].iloc[1].to_pydatetime()
    assert captured[0].end == full["time"].iloc[4].to_pydatetime()
    assert list(result["time"]) == list(full["time"])


def test_fetch_candles_by_date_range_reuses_full_cached_coverage_without_rewrite(
    tmp_path,
    monkeypatch,
    make_candle_frame,
):
    provider = oanda_provider.OANDADataProvider(
        api_key="token",
        account_id="account",
        data_dir=tmp_path,
    )
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    full = make_candle_frame(start, periods=6, step_seconds=60)
    provider._csv.save_candles(full, "EUR_USD", "M1")
    path = provider._csv.get_candle_path("EUR_USD", "M1")
    before_signature = (path.stat().st_size, path.stat().st_mtime_ns)

    monkeypatch.setattr(
        provider,
        "_fetch_window_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected gap fetch")),
    )

    result = provider.fetch_candles_by_date_range(
        "EUR_USD",
        "M1",
        start_date=full["time"].iloc[0].to_pydatetime(),
        end_date=full["time"].iloc[-1].to_pydatetime(),
    )
    after_signature = (path.stat().st_size, path.stat().st_mtime_ns)

    assert before_signature == after_signature
    assert list(result["time"]) == list(full["time"])


def test_extract_all_timeframes_by_date_range_uses_provider_multi_timeframe_entrypoint(
    tmp_path,
    monkeypatch,
    make_candle_frame,
):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    sample = make_candle_frame(start, periods=2, step_seconds=60)
    calls = {}

    class DummyProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def fetch_timeframes_by_date_range(self, **kwargs):
            calls["kwargs"] = kwargs
            return {"M1": sample, "H1": sample}

        def fetch_candles_by_date_range(self, **kwargs):
            raise AssertionError("extractor should use the shared provider entrypoint")

    monkeypatch.setattr(extract_candles, "OANDADataProvider", DummyProvider)

    extractor = extract_candles.OANDACandleExtractor(
        api_key="token",
        account_id="account",
        data_dir=tmp_path,
        max_workers=16,
    )
    outputs = extractor.extract_all_timeframes_by_date_range(
        instrument="EUR_USD",
        start_date=start,
        end_date=start + timedelta(hours=1),
        timeframes=["1m", "1h"],
    )

    assert calls["kwargs"]["instrument"] == "EUR_USD"
    assert calls["kwargs"]["timeframes"] == ["M1", "H1"]
    assert calls["kwargs"]["max_workers"] == 16
    assert outputs == {
        "M1": tmp_path / "EUR_USD" / "candles_EUR_USD_M1.csv",
        "H1": tmp_path / "EUR_USD" / "candles_EUR_USD_H1.csv",
    }


def test_fetch_timeframes_by_date_range_uses_global_scheduler_across_timeframes(
    tmp_path,
    monkeypatch,
    make_candle_frame,
):
    provider = oanda_provider.OANDADataProvider(
        api_key="token",
        account_id="account",
        data_dir=tmp_path,
    )
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15010)
    barrier = threading.Barrier(4)
    started = []
    lock = threading.Lock()

    def fake_fetch_window_task(instrument, task):
        with lock:
            started.append(task.timeframe)
            current = len(started)
        if current <= 4:
            barrier.wait(timeout=1.0)
        pytime.sleep(0.01)
        return _frame_for_task(provider, task, make_candle_frame)

    monkeypatch.setattr(provider, "_fetch_window_task", fake_fetch_window_task)

    results = provider.fetch_timeframes_by_date_range(
        "EUR_USD",
        ["M1", "M5", "M15"],
        start_date=start,
        end_date=end,
        use_cache=False,
        max_workers=4,
    )

    assert len(started) == 6
    assert started[:4].count("M1") == 2
    assert set(results) == {"M1", "M5", "M15"}
    assert all(not frame.empty for frame in results.values())


def test_write_date_range_result_keeps_csv_sorted_with_out_of_order_windows(tmp_path, make_candle_frame):
    provider = oanda_provider.OANDADataProvider(
        api_key="token",
        account_id="account",
        data_dir=tmp_path,
    )
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    full = make_candle_frame(start, periods=6, step_seconds=60)

    items = [oanda_provider.RangePlanItem(kind="fetch", window_indexes=(0, 1, 2))]
    fetched = {
        2: full.iloc[3:].reset_index(drop=True),
        0: full.iloc[:2].reset_index(drop=True),
        1: full.iloc[1:4].reset_index(drop=True),
    }

    result = provider._write_date_range_result("EUR_USD", "M1", items, fetched, use_cache=True)
    saved = provider._csv.load_candles("EUR_USD", "M1")

    assert list(saved["time"]) == list(full["time"])
    assert saved["time"].is_unique
    assert list(result["time"]) == list(full["time"])


def test_fetch_timeframes_by_date_range_keeps_each_csv_sorted_with_out_of_order_windows(
    tmp_path,
    monkeypatch,
    make_candle_frame,
):
    provider = oanda_provider.OANDADataProvider(
        api_key="token",
        account_id="account",
        data_dir=tmp_path,
    )
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=30050)

    def fake_fetch_window_task(instrument, task):
        pytime.sleep(max(0.0, 0.03 - (task.window_index * 0.005)))
        return _frame_for_task(provider, task, make_candle_frame)

    monkeypatch.setattr(provider, "_fetch_window_task", fake_fetch_window_task)

    results = provider.fetch_timeframes_by_date_range(
        "EUR_USD",
        ["M1", "M5"],
        start_date=start,
        end_date=end,
        use_cache=True,
        max_workers=4,
    )

    saved_m1 = provider._csv.load_candles("EUR_USD", "M1")
    saved_m5 = provider._csv.load_candles("EUR_USD", "M5")

    assert saved_m1 is not None and saved_m5 is not None
    assert saved_m1["time"].is_monotonic_increasing and saved_m1["time"].is_unique
    assert saved_m5["time"].is_monotonic_increasing and saved_m5["time"].is_unique
    assert list(results["M1"]["time"]) == list(saved_m1["time"])
    assert list(results["M5"]["time"]) == list(saved_m5["time"])


def test_fetch_timeframes_by_date_range_cleans_staging_files_on_failure(
    tmp_path,
    monkeypatch,
    make_candle_frame,
):
    provider = oanda_provider.OANDADataProvider(
        api_key="token",
        account_id="account",
        data_dir=tmp_path,
    )
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=5010)

    def fake_fetch_window_task(instrument, task):
        if task.timeframe == "M1" and task.window_index == 1:
            raise RuntimeError("boom")
        return _frame_for_task(provider, task, make_candle_frame)

    monkeypatch.setattr(provider, "_fetch_window_task", fake_fetch_window_task)

    with pytest.raises(RuntimeError, match="boom"):
        provider.fetch_timeframes_by_date_range(
            "EUR_USD",
            ["M1", "M5"],
            start_date=start,
            end_date=end,
            use_cache=True,
            max_workers=3,
        )

    assert not provider._csv.get_candle_path("EUR_USD", "M1").exists()
    assert not provider._csv.get_candle_path("EUR_USD", "M5").exists()
    assert not provider._csv.get_candle_path("EUR_USD", "M1").with_suffix(".tmp").exists()
    assert not provider._csv.get_candle_path("EUR_USD", "M5").with_suffix(".tmp").exists()


def _measure_synthetic_rps(latency_seconds: float, workers: int, duration_seconds: float) -> float:
    limiter = rate_limiter.RateLimiter(max_requests=119, window_seconds=1.0)
    barrier = threading.Barrier(workers + 1)
    counter_lock = threading.Lock()
    acquired = 0
    deadline = 0.0

    def worker() -> None:
        nonlocal acquired
        barrier.wait()
        while pytime.perf_counter() < deadline:
            if limiter.acquire(timeout=0.5):
                acquired_at = pytime.perf_counter()
                if acquired_at < deadline:
                    with counter_lock:
                        acquired += 1
                pytime.sleep(latency_seconds)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for thread in threads:
        thread.start()

    deadline = pytime.perf_counter() + duration_seconds
    barrier.wait()
    for thread in threads:
        thread.join()

    return acquired / duration_seconds


def test_synthetic_throughput_benchmark_low_latency():
    rps = _measure_synthetic_rps(latency_seconds=0.001, workers=16, duration_seconds=1.2)
    assert 118.0 <= rps <= 119.5


def test_synthetic_throughput_benchmark_higher_latency_stays_under_ceiling():
    rps = _measure_synthetic_rps(latency_seconds=0.1, workers=16, duration_seconds=1.2)
    assert rps <= 119.5
    assert rps >= 110.0


def test_mocked_date_range_benchmark_uses_global_scheduler_for_uneven_backlogs(
    tmp_path,
    monkeypatch,
    make_candle_frame,
):
    provider = oanda_provider.OANDADataProvider(
        api_key="token",
        account_id="account",
        data_dir=tmp_path,
    )
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=40010)

    def fake_fetch_window_task(instrument, task):
        pytime.sleep(0.03)
        return _frame_for_task(provider, task, make_candle_frame)

    monkeypatch.setattr(provider, "_fetch_window_task", fake_fetch_window_task)

    started_at = pytime.perf_counter()
    results = provider.fetch_timeframes_by_date_range(
        "EUR_USD",
        ["M1", "H4", "D"],
        start_date=start,
        end_date=end,
        use_cache=False,
        max_workers=4,
    )
    elapsed = pytime.perf_counter() - started_at

    assert elapsed < 0.20
    assert set(results) == {"M1", "H4", "D"}
