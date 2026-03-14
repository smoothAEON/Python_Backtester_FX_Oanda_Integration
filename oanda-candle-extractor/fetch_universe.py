#!/usr/bin/env python3
"""Batch-fetch the fixed Phase 9 core universe with sequential instrument orchestration."""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from extract_candles import (
    DEFAULT_DATA_DIR,
    OANDACandleExtractor,
    load_default_env,
    normalize_price,
    normalize_timeframe,
    parse_date,
)

logger = logging.getLogger(__name__)

UNIVERSE_INSTRUMENTS = (
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
DEFAULT_TIMEFRAMES = ("S5", "M1", "M5", "M15", "M30", "H1", "H4", "D", "W")
DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_TARGET_RPS = 100
DEFAULT_MAX_WORKERS = 16


@dataclass(slots=True, frozen=True)
class BatchOptions:
    """Normalized batch-fetch inputs."""

    mode: str
    timeframes: tuple[str, ...]
    price: str
    count: int | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


@dataclass(slots=True, frozen=True)
class BatchResult:
    """One instrument's batch outcome."""

    instrument: str
    mode: str
    success: bool
    output_timeframes: tuple[str, ...]
    timeframe_states: tuple[str, ...] = ()
    missing_timeframes: tuple[str, ...] = ()
    error: str | None = None


def _output_path(data_dir: Path, instrument: str, timeframe: str) -> Path:
    """Return the canonical CSV path for one universe output."""
    return data_dir / instrument / f"candles_{instrument}_{timeframe}.csv"


def _output_signature(path: Path) -> tuple[int, int] | None:
    """Return a stable file signature for change detection."""
    if not path.exists():
        return None
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _snapshot_outputs(
    data_dir: Path,
    instrument: str,
    timeframes: Sequence[str],
) -> dict[str, tuple[int, int] | None]:
    """Capture file signatures before one batch run."""
    return {
        timeframe: _output_signature(_output_path(data_dir, instrument, timeframe))
        for timeframe in timeframes
    }


def _classify_outputs(
    data_dir: Path,
    instrument: str,
    timeframes: Sequence[str],
    before_signatures: dict[str, tuple[int, int] | None],
) -> tuple[str, ...]:
    """Classify each successful timeframe output as created, updated, or reused."""
    states: list[str] = []
    for timeframe in timeframes:
        after_signature = _output_signature(_output_path(data_dir, instrument, timeframe))
        if after_signature is None:
            continue

        before_signature = before_signatures.get(timeframe)
        if before_signature is None:
            state = "created"
        elif before_signature == after_signature:
            state = "reused"
        else:
            state = "updated"
        states.append(f"{timeframe}={state}")
    return tuple(states)


def build_parser() -> argparse.ArgumentParser:
    """Build the batch CLI parser."""
    parser = argparse.ArgumentParser(
        description="Fetch the fixed Phase 9 core universe into canonical extractor CSVs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Refresh the default 1-year universe backfill
  python fetch_universe.py

  # Refresh the last 500 candles for every instrument/timeframe
  python fetch_universe.py --count 500

  # Fetch a specific date range for the full universe
  python fetch_universe.py --start-date 2025-01-01 --end-date 2025-12-31
        """,
    )
    parser.add_argument(
        "--oanda-api-key",
        default=os.getenv("OANDA_API_KEY"),
        help="OANDA API token (or set OANDA_API_KEY env var)",
    )
    parser.add_argument(
        "--oanda-account-id",
        default=os.getenv("OANDA_ACCOUNT_ID"),
        help="OANDA account ID (or set OANDA_ACCOUNT_ID env var)",
    )
    parser.add_argument(
        "--account-type",
        choices=("live", "practice"),
        default=None,
        help="OANDA account type (defaults to OANDA_ENVIRONMENT or practice)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Number of candles per timeframe in recent-history mode (max: 5000)",
    )
    parser.add_argument(
        "--timeframes",
        nargs="*",
        default=None,
        help="Optional subset of timeframes (default: S5 M1 M5 M15 M30 H1 H4 D W)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date for date-range mode (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date for date-range mode (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)",
    )
    parser.add_argument(
        "--price",
        default="MBA",
        help="Persisted extractor output requires MBA (default: MBA)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help=f"Directory for CSV files (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--target-rps",
        type=int,
        default=DEFAULT_TARGET_RPS,
        help=f"Global request pacing target in requests per second (default: {DEFAULT_TARGET_RPS})",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help=f"Maximum worker threads for concurrent fetches (default: {DEFAULT_MAX_WORKERS})",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Log level (default: INFO)",
    )
    return parser


def prepare_batch_options(args: argparse.Namespace, *, now: datetime | None = None) -> BatchOptions:
    """Validate and normalize CLI arguments into a fixed batch request."""
    selected_timeframes = tuple(
        normalize_timeframe(timeframe)
        for timeframe in (args.timeframes or DEFAULT_TIMEFRAMES)
    )
    normalized_price = normalize_price(args.price)

    has_start = args.start_date is not None
    has_end = args.end_date is not None
    if has_start != has_end:
        raise ValueError("start-date and end-date must be provided together")

    if args.count is not None:
        if args.count < 1 or args.count > 5000:
            raise ValueError("count must be between 1 and 5000")
        if has_start and has_end:
            logger.warning("Ignoring start-date/end-date because count mode was requested")
        return BatchOptions(
            mode="count",
            timeframes=selected_timeframes,
            price=normalized_price,
            count=args.count,
        )

    if has_start and has_end:
        start_date = parse_date(args.start_date)
        end_date = parse_date(args.end_date)
        if end_date <= start_date:
            raise ValueError("end-date must be after start-date")
        return BatchOptions(
            mode="date_range",
            timeframes=selected_timeframes,
            price=normalized_price,
            start_date=start_date,
            end_date=end_date,
        )

    end_date = now or datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    return BatchOptions(
        mode="date_range",
        timeframes=selected_timeframes,
        price=normalized_price,
        start_date=start_date,
        end_date=end_date,
    )


def run_batch(
    extractor: OANDACandleExtractor,
    options: BatchOptions,
    *,
    data_dir: Path,
) -> list[BatchResult]:
    """Run the fixed universe sequentially and collect per-instrument outcomes."""
    results: list[BatchResult] = []

    for index, instrument in enumerate(UNIVERSE_INSTRUMENTS, start=1):
        before_signatures = _snapshot_outputs(data_dir, instrument, options.timeframes)
        logger.info(
            "Universe fetch %s/%s: %s (%s)",
            index,
            len(UNIVERSE_INSTRUMENTS),
            instrument,
            options.mode,
        )

        try:
            if options.mode == "count":
                outputs = extractor.extract_all_timeframes(
                    instrument=instrument,
                    count=options.count or 500,
                    timeframes=list(options.timeframes),
                    price=options.price,
                )
            else:
                outputs = extractor.extract_all_timeframes_by_date_range(
                    instrument=instrument,
                    start_date=options.start_date,
                    end_date=options.end_date,
                    timeframes=list(options.timeframes),
                )
        except Exception as exc:
            logger.error("Universe fetch failed for %s: %s", instrument, exc)
            results.append(
                BatchResult(
                    instrument=instrument,
                    mode=options.mode,
                    success=False,
                    output_timeframes=(),
                    missing_timeframes=options.timeframes,
                    error=str(exc),
                )
            )
            continue

        completed = tuple(timeframe for timeframe in options.timeframes if timeframe in outputs)
        missing = tuple(timeframe for timeframe in options.timeframes if timeframe not in outputs)
        timeframe_states = _classify_outputs(data_dir, instrument, completed, before_signatures)
        if missing:
            logger.error(
                "Universe fetch for %s was incomplete; missing timeframe outputs: %s",
                instrument,
                ", ".join(missing),
            )
            results.append(
                BatchResult(
                    instrument=instrument,
                    mode=options.mode,
                    success=False,
                    output_timeframes=completed,
                    timeframe_states=timeframe_states,
                    missing_timeframes=missing,
                    error="missing_timeframe_outputs",
                )
            )
            continue

        logger.info(
            "Completed %s with %s",
            instrument,
            ", ".join(timeframe_states) if timeframe_states else "no persisted outputs",
        )
        results.append(
            BatchResult(
                instrument=instrument,
                mode=options.mode,
                success=True,
                output_timeframes=completed,
                timeframe_states=timeframe_states,
            )
        )

    return results


def log_batch_summary(results: Sequence[BatchResult]) -> None:
    """Log one final batch summary."""
    successes = sum(1 for result in results if result.success)
    logger.info("Universe batch summary: %s/%s instruments succeeded", successes, len(results))
    for result in results:
        if result.success:
            logger.info(
                "%s: ok (%s)",
                result.instrument,
                ", ".join(result.timeframe_states or result.output_timeframes),
            )
            continue

        logger.error(
            "%s: failed (%s)%s%s",
            result.instrument,
            result.error or "unknown_error",
            f"; outputs={', '.join(result.timeframe_states)}" if result.timeframe_states else "",
            f"; missing={', '.join(result.missing_timeframes)}" if result.missing_timeframes else "",
        )


def execute_batch(
    args: argparse.Namespace,
    *,
    extractor_factory=OANDACandleExtractor,
    now: datetime | None = None,
) -> int:
    """Execute the universe fetch from parsed arguments."""
    if not args.oanda_api_key or not args.oanda_account_id:
        logger.error("OANDA API key and account ID are required")
        logger.error("Set OANDA_API_KEY and OANDA_ACCOUNT_ID environment variables")
        logger.error("Or use --oanda-api-key and --oanda-account-id arguments")
        return 1

    options = prepare_batch_options(args, now=now)
    extractor = extractor_factory(
        api_key=args.oanda_api_key,
        account_id=args.oanda_account_id,
        account_type=args.account_type,
        data_dir=args.data_dir,
        target_rps=args.target_rps,
        max_workers=args.max_workers,
    )
    data_dir = Path(args.data_dir) if args.data_dir is not None else DEFAULT_DATA_DIR
    results = run_batch(extractor, options, data_dir=data_dir)
    log_batch_summary(results)
    return 1 if any(not result.success for result in results) else 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    load_default_env()
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    if args.log_level != "DEBUG":
        logging.getLogger("oandapyV20").setLevel(logging.WARNING)

    try:
        return execute_batch(args)
    except Exception as exc:
        logger.error("Universe fetch failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
