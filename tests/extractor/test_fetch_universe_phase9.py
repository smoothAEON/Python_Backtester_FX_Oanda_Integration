from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

import fetch_universe
import oanda_provider
from oandapyV20.exceptions import V20Error


ROOT = Path(__file__).resolve().parents[2]


class _SequenceClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def request(self, endpoint):
        del endpoint
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_universe_manifest_matches_phase9_core_set():
    assert fetch_universe.UNIVERSE_INSTRUMENTS == (
        "EUR_USD",
        "USD_JPY",
        "GBP_USD",
        "AUD_USD",
        "USD_CHF",
        "USD_CAD",
        "NZD_USD",
        "EUR_JPY",
        "GBP_JPY",
        "EUR_GBP",
        "EUR_CHF",
        "AUD_JPY",
        "GBP_CHF",
        "EUR_AUD",
        "EUR_CAD",
        "XAU_USD",
    )


def test_default_timeframes_cover_full_supported_range():
    assert fetch_universe.DEFAULT_TIMEFRAMES == (
        "S5",
        "M1",
        "M5",
        "M15",
        "M30",
        "H1",
        "H4",
        "D",
        "W",
    )


def test_prepare_batch_options_uses_count_mode_when_count_is_present():
    parser = fetch_universe.build_parser()
    args = parser.parse_args(["--count", "500", "--price", "MBA"])

    options = fetch_universe.prepare_batch_options(args)

    assert options.mode == "count"
    assert options.count == 500
    assert options.start_date is None
    assert options.end_date is None
    assert options.timeframes == fetch_universe.DEFAULT_TIMEFRAMES


def test_prepare_batch_options_uses_explicit_date_range():
    parser = fetch_universe.build_parser()
    args = parser.parse_args(["--start-date", "2025-01-01", "--end-date", "2025-01-10"])

    options = fetch_universe.prepare_batch_options(args)

    assert options.mode == "date_range"
    assert options.start_date == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert options.end_date == datetime(2025, 1, 10, tzinfo=timezone.utc)


def test_prepare_batch_options_defaults_to_last_365_days():
    parser = fetch_universe.build_parser()
    args = parser.parse_args([])
    fixed_now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)

    options = fetch_universe.prepare_batch_options(args, now=fixed_now)

    assert options.mode == "date_range"
    assert options.start_date == datetime(2025, 3, 14, 12, 0, tzinfo=timezone.utc)
    assert options.end_date == fixed_now


def test_prepare_batch_options_rejects_partial_date_args():
    parser = fetch_universe.build_parser()
    args = parser.parse_args(["--start-date", "2025-01-01"])

    with pytest.raises(ValueError, match="start-date and end-date must be provided together"):
        fetch_universe.prepare_batch_options(args)


def test_prepare_batch_options_rejects_non_mba_price():
    parser = fetch_universe.build_parser()
    args = parser.parse_args(["--count", "50", "--price", "M"])

    with pytest.raises(ValueError, match="Only price='MBA' is supported"):
        fetch_universe.prepare_batch_options(args)


def test_execute_batch_runs_instruments_sequentially_and_continues_after_failure(monkeypatch, tmp_path):
    parser = fetch_universe.build_parser()
    args = parser.parse_args(
        [
            "--count",
            "10",
            "--oanda-api-key",
            "token",
            "--oanda-account-id",
            "account",
            "--data-dir",
            str(tmp_path),
        ]
    )
    order: list[str] = []
    init_kwargs = {}

    class DummyExtractor:
        def __init__(self, **kwargs):
            init_kwargs.update(kwargs)

        def extract_all_timeframes(self, *, instrument, count, timeframes, price):
            order.append(instrument)
            if instrument == "USD_JPY":
                raise RuntimeError("boom")
            return {
                timeframe: tmp_path / instrument / f"candles_{instrument}_{timeframe}.csv"
                for timeframe in timeframes
            }

    monkeypatch.setattr(fetch_universe, "UNIVERSE_INSTRUMENTS", ("EUR_USD", "USD_JPY", "GBP_USD"))

    exit_code = fetch_universe.execute_batch(args, extractor_factory=DummyExtractor)

    assert exit_code == 1
    assert order == ["EUR_USD", "USD_JPY", "GBP_USD"]
    assert init_kwargs["target_rps"] == fetch_universe.DEFAULT_TARGET_RPS
    assert init_kwargs["max_workers"] == fetch_universe.DEFAULT_MAX_WORKERS


def test_execute_batch_marks_incomplete_timeframe_outputs_as_failure(monkeypatch, tmp_path):
    parser = fetch_universe.build_parser()
    args = parser.parse_args(
        [
            "--count",
            "10",
            "--oanda-api-key",
            "token",
            "--oanda-account-id",
            "account",
            "--data-dir",
            str(tmp_path),
            "--timeframes",
            "1m",
            "1h",
        ]
    )

    class DummyExtractor:
        def __init__(self, **kwargs):
            del kwargs

        def extract_all_timeframes(self, *, instrument, count, timeframes, price):
            del instrument, count, price
            return {timeframes[0]: tmp_path / "only_one.csv"}

    monkeypatch.setattr(fetch_universe, "UNIVERSE_INSTRUMENTS", ("EUR_USD",))

    exit_code = fetch_universe.execute_batch(args, extractor_factory=DummyExtractor)

    assert exit_code == 1


def test_execute_batch_reports_reused_outputs_on_rerun(monkeypatch, tmp_path, caplog):
    parser = fetch_universe.build_parser()
    args = parser.parse_args(
        [
            "--count",
            "10",
            "--oanda-api-key",
            "token",
            "--oanda-account-id",
            "account",
            "--data-dir",
            str(tmp_path),
            "--timeframes",
            "1m",
            "1h",
        ]
    )
    caplog.set_level("INFO")
    instrument = "EUR_USD"
    existing_paths = {
        timeframe: tmp_path / instrument / f"candles_{instrument}_{timeframe}.csv"
        for timeframe in ("M1", "H1")
    }
    for path in existing_paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("existing", encoding="utf-8")

    class DummyExtractor:
        def __init__(self, **kwargs):
            del kwargs

        def extract_all_timeframes(self, *, instrument, count, timeframes, price):
            del count, price
            return {
                timeframe: tmp_path / instrument / f"candles_{instrument}_{timeframe}.csv"
                for timeframe in timeframes
            }

    monkeypatch.setattr(fetch_universe, "UNIVERSE_INSTRUMENTS", (instrument,))

    exit_code = fetch_universe.execute_batch(args, extractor_factory=DummyExtractor)

    assert exit_code == 0
    assert "M1=reused" in caplog.text
    assert "H1=reused" in caplog.text


def test_fetch_universe_help_cli_succeeds():
    completed = subprocess.run(
        [sys.executable, "oanda-candle-extractor/fetch_universe.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "--count" in completed.stdout
    assert "--start-date" in completed.stdout
    assert "--timeframes" in completed.stdout


def test_make_request_retries_connection_errors_and_clears_client(monkeypatch, tmp_path):
    provider = oanda_provider.OANDADataProvider(api_key="token", account_id="account", data_dir=tmp_path)
    state = {"client_index": 0, "clear_calls": 0, "success_calls": 0}
    clients = [
        _SequenceClient([requests.ConnectionError("dropped")]),
        _SequenceClient([{"candles": []}]),
    ]

    monkeypatch.setattr(provider, "_get_api_client", lambda: clients[state["client_index"]])
    monkeypatch.setattr(provider._rate_limiter, "acquire", lambda timeout=30.0: True)
    monkeypatch.setattr(provider._rate_limiter, "record_success", lambda: state.__setitem__("success_calls", state["success_calls"] + 1))
    monkeypatch.setattr(provider, "_sleep_for_retry", lambda error, attempt_index: None)

    def fake_clear_api_client():
        state["clear_calls"] += 1
        state["client_index"] += 1

    monkeypatch.setattr(provider, "_clear_api_client", fake_clear_api_client)

    response = provider._make_request(object())

    assert response == {"candles": []}
    assert state["clear_calls"] == 1
    assert state["success_calls"] == 1


def test_make_request_retries_retriable_v20_status_codes(monkeypatch, tmp_path):
    provider = oanda_provider.OANDADataProvider(api_key="token", account_id="account", data_dir=tmp_path)
    client = _SequenceClient([V20Error(503, "busy"), {"candles": []}])
    sleeps = []
    clear_calls = []

    monkeypatch.setattr(provider, "_get_api_client", lambda: client)
    monkeypatch.setattr(provider._rate_limiter, "acquire", lambda timeout=30.0: True)
    monkeypatch.setattr(provider._rate_limiter, "record_success", lambda: None)
    monkeypatch.setattr(provider, "_sleep_for_retry", lambda error, attempt_index: sleeps.append((error.code, attempt_index)))
    monkeypatch.setattr(provider, "_clear_api_client", lambda: clear_calls.append(True))

    response = provider._make_request(object())

    assert response == {"candles": []}
    assert sleeps == [(503, 0)]
    assert clear_calls == []


def test_make_request_retries_are_capped_for_request_exceptions(monkeypatch, tmp_path):
    provider = oanda_provider.OANDADataProvider(api_key="token", account_id="account", data_dir=tmp_path)
    provider._max_request_attempts = 3
    clears = []
    sleeps = []
    client = _SequenceClient(
        [
            requests.Timeout("slow"),
            requests.Timeout("slow"),
            requests.Timeout("slow"),
        ]
    )

    monkeypatch.setattr(provider, "_get_api_client", lambda: client)
    monkeypatch.setattr(provider._rate_limiter, "acquire", lambda timeout=30.0: True)
    monkeypatch.setattr(provider, "_sleep_for_retry", lambda error, attempt_index: sleeps.append((type(error).__name__, attempt_index)))
    monkeypatch.setattr(provider, "_clear_api_client", lambda: clears.append(True))

    with pytest.raises(requests.Timeout, match="slow"):
        provider._make_request(object())

    assert clears == [True, True, True]
    assert sleeps == [("Timeout", 0), ("Timeout", 1)]


def test_make_request_fails_fast_on_non_retriable_v20_status(monkeypatch, tmp_path):
    provider = oanda_provider.OANDADataProvider(api_key="token", account_id="account", data_dir=tmp_path)
    client = _SequenceClient([V20Error(400, "bad request")])
    slept = []

    monkeypatch.setattr(provider, "_get_api_client", lambda: client)
    monkeypatch.setattr(provider._rate_limiter, "acquire", lambda timeout=30.0: True)
    monkeypatch.setattr(provider, "_sleep_for_retry", lambda error, attempt_index: slept.append((error, attempt_index)))

    with pytest.raises(V20Error, match="bad request"):
        provider._make_request(object())

    assert slept == []
