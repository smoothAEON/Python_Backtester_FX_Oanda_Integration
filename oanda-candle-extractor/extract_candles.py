#!/usr/bin/env python3
"""OANDA candle extractor with concurrent batching support."""

from __future__ import annotations

import argparse
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:  # pragma: no cover - dependency is listed, but keep CLI usable without it.
    _load_dotenv = None

from csv_persistence import CSVPersistence
from oanda_provider import OANDADataProvider

logger = logging.getLogger(__name__)

TIMEFRAMES = ['S5', 'M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D', 'W']
TIMEFRAME_ALIASES = {
    '5s': 'S5',
    '1m': 'M1',
    '5m': 'M5',
    '15m': 'M15',
    '30m': 'M30',
    '1h': 'H1',
    '4h': 'H4',
    '1d': 'D',
    '1w': 'W',
    'daily': 'D',
    'weekly': 'W',
}
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_default_env(override: bool = False) -> bool:
    """Load the extractor-local .env file if python-dotenv is available."""
    if _load_dotenv is None:
        logger.debug("python-dotenv is unavailable; skipping .env load")
        return False
    if not DEFAULT_ENV_FILE.exists():
        return False
    return bool(_load_dotenv(dotenv_path=DEFAULT_ENV_FILE, override=override))


def resolve_account_type(account_type: Optional[str] = None) -> str:
    """Resolve the OANDA environment from args/env into practice/live."""
    candidate = account_type or os.getenv("OANDA_ENVIRONMENT") or "practice"
    normalized = candidate.strip().lower()

    aliases = {
        "practice": "practice",
        "fxpractice": "practice",
        "demo": "practice",
        "live": "live",
        "fxlive": "live",
        "real": "live",
    }
    resolved = aliases.get(normalized)
    if resolved is None:
        raise ValueError("account_type must resolve to 'live' or 'practice'")
    return resolved


def normalize_timeframe(timeframe: str) -> str:
    """Normalize timeframe string to OANDA format."""
    tf = timeframe.strip().lower()
    if tf in TIMEFRAME_ALIASES:
        return TIMEFRAME_ALIASES[tf]

    for valid_tf in TIMEFRAMES:
        if tf == valid_tf.lower():
            return valid_tf

    raise ValueError(f"Invalid timeframe: {timeframe}. Must be one of {TIMEFRAMES}")


def normalize_instrument(instrument: str) -> str:
    """Normalize user instrument text into OANDA format (AAA_BBB)."""
    cleaned = instrument.strip().upper().replace("/", "_").replace("-", "_").replace(" ", "")

    if "_" in cleaned:
        parts = cleaned.split("_")
        if len(parts) == 2 and all(len(part) == 3 and part.isalpha() for part in parts):
            return f"{parts[0]}_{parts[1]}"
    elif len(cleaned) == 6 and cleaned.isalpha():
        return f"{cleaned[:3]}_{cleaned[3:]}"

    raise ValueError(f"Invalid instrument format: {instrument}")


def normalize_price(price: str) -> str:
    """Normalize the requested price component."""
    normalized = price.strip().upper()
    if normalized != "MBA":
        raise ValueError("Only price='MBA' is supported for extractor output")
    return normalized


def parse_date(date_str: str) -> datetime:
    """Parse date string to UTC datetime."""
    formats = [
        '%Y-%m-%d',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%S.%fZ',
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")


class OANDACandleExtractor:
    """OANDA candle extractor with concurrent batching support."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        account_id: Optional[str] = None,
        account_type: Optional[str] = None,
        data_dir: Optional[Path] = None,
        target_rps: int = 119,
        max_workers: int = 16,
    ):
        """
        Initialize the candle extractor.

        Args:
            api_key: OANDA API key (or set OANDA_API_KEY env var)
            account_id: OANDA account ID (or set OANDA_ACCOUNT_ID env var)
            account_type: 'practice' or 'live'
            data_dir: Directory for CSV files
            target_rps: Global request rate target
            max_workers: Maximum worker threads for concurrent fetches
        """
        load_default_env()
        self.api_key = api_key or os.getenv("OANDA_API_KEY")
        self.account_id = account_id or os.getenv("OANDA_ACCOUNT_ID")
        self.account_type = resolve_account_type(account_type)
        self.target_rps = target_rps
        self.max_workers = max_workers

        if not self.api_key or not self.account_id:
            raise ValueError("OANDA API key and account ID must be provided")
        if self.target_rps <= 0:
            raise ValueError("target_rps must be positive")
        if self.max_workers <= 0:
            raise ValueError("max_workers must be positive")

        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.provider = OANDADataProvider(
            api_key=self.api_key,
            account_id=self.account_id,
            account_type=self.account_type,
            data_dir=self.data_dir,
            weekend_bypass=True,
            target_rps=self.target_rps,
            max_workers=self.max_workers,
        )
        self.csv = CSVPersistence(self.data_dir)

    def _output_path(self, instrument: str, timeframe: str) -> Path:
        """Get the canonical output path for a CSV file."""
        return self.csv.get_candle_path(instrument, timeframe)

    def fetch_candles(
        self,
        instrument: str,
        timeframe: str,
        count: int = 500,
        price: str = "MBA",
        max_workers: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fetch candles from OANDA and return a normalized DataFrame."""
        normalized_instrument = normalize_instrument(instrument)
        normalized_tf = normalize_timeframe(timeframe)
        normalize_price(price)

        if count < 1 or count > 5000:
            raise ValueError("count must be between 1 and 5000")

        logger.info(
            "Fetching %s candles for %s (count=%s)",
            normalized_tf,
            normalized_instrument,
            count,
        )
        return self.provider.fetch_candles(
            instrument=normalized_instrument,
            timeframe=normalized_tf,
            count=count,
            use_cache=True,
            max_workers=max_workers,
        )

    def fetch_candles_by_date_range(
        self,
        instrument: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        max_workers: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fetch candles for a specific date range with concurrent batching."""
        normalized_instrument = normalize_instrument(instrument)
        normalized_tf = normalize_timeframe(timeframe)

        logger.info(
            "Fetching %s candles for %s from %s to %s",
            normalized_tf,
            normalized_instrument,
            start_date.isoformat(),
            end_date.isoformat(),
        )
        return self.provider.fetch_candles_by_date_range(
            instrument=normalized_instrument,
            timeframe=normalized_tf,
            start_date=start_date,
            end_date=end_date,
            use_cache=True,
            max_workers=max_workers,
        )

    def extract_to_csv(
        self,
        instrument: str,
        timeframe: str,
        count: int = 500,
        price: str = "MBA",
    ) -> Optional[Path]:
        """Fetch one timeframe and save it as CSV."""
        try:
            normalized_instrument = normalize_instrument(instrument)
            normalized_tf = normalize_timeframe(timeframe)
            normalize_price(price)
            df = self.fetch_candles(
                instrument=normalized_instrument,
                timeframe=normalized_tf,
                count=count,
                price=price,
            )
        except Exception as exc:
            logger.error("Failed extracting %s %s: %s", instrument, timeframe, exc)
            return None

        if df.empty:
            return None

        file_path = self._output_path(normalized_instrument, normalized_tf)
        self.csv.save_candles(df, normalized_instrument, normalized_tf)
        logger.info("Saved %s rows to %s", len(df), file_path)
        return file_path

    def extract_date_range_to_csv(
        self,
        instrument: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[Path]:
        """Fetch candles for a date range and save as CSV."""
        try:
            normalized_instrument = normalize_instrument(instrument)
            normalized_tf = normalize_timeframe(timeframe)
            df = self.fetch_candles_by_date_range(
                instrument=normalized_instrument,
                timeframe=normalized_tf,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            logger.error("Failed extracting %s %s: %s", instrument, timeframe, exc)
            return None

        if df.empty:
            return None

        file_path = self._output_path(normalized_instrument, normalized_tf)
        logger.info("Saved %s rows to %s", len(df), file_path)
        return file_path

    def extract_all_timeframes(
        self,
        instrument: str,
        count: int = 500,
        timeframes: Optional[list[str]] = None,
        price: str = "MBA",
    ) -> dict[str, Path]:
        """Extract candles for requested timeframes and return saved file paths."""
        selected = [normalize_timeframe(tf) for tf in (timeframes or TIMEFRAMES)]
        normalize_price(price)
        outputs: dict[str, Path] = {}

        worker_count = min(self.max_workers, len(selected))
        if worker_count <= 1:
            for timeframe in selected:
                path = self.extract_to_csv(instrument=instrument, timeframe=timeframe, count=count, price=price)
                if path is not None:
                    outputs[timeframe] = path
            return outputs

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(self.extract_to_csv, instrument, timeframe, count, price): timeframe
                for timeframe in selected
            }
            completed: dict[str, Optional[Path]] = {}
            for future in as_completed(future_map):
                completed[future_map[future]] = future.result()

        for timeframe in selected:
            path = completed.get(timeframe)
            if path is not None:
                outputs[timeframe] = path
        return outputs

    def extract_all_timeframes_by_date_range(
        self,
        instrument: str,
        start_date: datetime,
        end_date: datetime,
        timeframes: Optional[list[str]] = None,
    ) -> dict[str, Path]:
        """Extract candles for a date range across all requested timeframes."""
        selected = [normalize_timeframe(tf) for tf in (timeframes or TIMEFRAMES)]
        normalized_instrument = normalize_instrument(instrument)
        outputs: dict[str, Path] = {}
        results = self.provider.fetch_timeframes_by_date_range(
            instrument=normalized_instrument,
            timeframes=selected,
            start_date=start_date,
            end_date=end_date,
            use_cache=True,
            max_workers=self.max_workers,
        )

        for timeframe in selected:
            df = results.get(timeframe)
            if df is not None and not df.empty:
                outputs[timeframe] = self._output_path(normalized_instrument, timeframe)
        return outputs

    def validate_connection(self) -> bool:
        """Validate API connection and credentials."""
        return self.provider.validate_connection()


def main() -> int:
    """CLI entry point."""
    load_default_env()
    parser = argparse.ArgumentParser(
        description="Extract OANDA candles to CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch last 500 H1 candles for EUR_USD
  python extract_candles.py --instrument EUR_USD --timeframes 1h --count 500

  # Fetch candles for a date range (concurrent batching)
  python extract_candles.py --instrument XAU_USD --start-date 2024-01-01 --end-date 2024-12-31 --timeframes 1h

  # Fetch all timeframes for a date range
  python extract_candles.py --instrument EUR_USD --start-date 2024-01-01 --end-date 2024-06-30

  # Fetch 5s candles with 119 rps pacing
  python extract_candles.py --instrument EUR_USD --timeframes 5s --count 5000 --target-rps 119 --max-workers 16
        """,
    )
    parser.add_argument(
        "--instrument",
        default="XAU_USD",
        help="Instrument pair in OANDA format (e.g., EUR_USD, XAU_USD)",
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
        default=500,
        help="Number of candles per timeframe (default: 500, max: 5000)",
    )
    parser.add_argument(
        "--timeframes",
        nargs="*",
        default=None,
        help="Optional subset of timeframes (e.g., 1m 5m 1h 4h 1d 1w)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date for date range fetch (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date for date range fetch (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)",
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
        help="Directory for CSV files (default: ./data)",
    )
    parser.add_argument(
        "--target-rps",
        type=int,
        default=119,
        help="Global request pacing target in requests per second (default: 119)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=16,
        help="Maximum worker threads for concurrent fetches (default: 16)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Log level (default: INFO)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate API connection and exit",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    if args.log_level != "DEBUG":
        logging.getLogger("oandapyV20").setLevel(logging.WARNING)

    if not args.oanda_api_key or not args.oanda_account_id:
        logger.error("OANDA API key and account ID are required")
        logger.error("Set OANDA_API_KEY and OANDA_ACCOUNT_ID environment variables")
        logger.error("Or use --oanda-api-key and --oanda-account-id arguments")
        return 1

    try:
        normalize_price(args.price)
        extractor = OANDACandleExtractor(
            api_key=args.oanda_api_key,
            account_id=args.oanda_account_id,
            account_type=args.account_type,
            data_dir=args.data_dir,
            target_rps=args.target_rps,
            max_workers=args.max_workers,
        )

        if args.validate:
            if extractor.validate_connection():
                logger.info("Connection validated successfully")
                return 0
            logger.error("Connection validation failed")
            return 1

        if args.start_date and args.end_date:
            start_date = parse_date(args.start_date)
            end_date = parse_date(args.end_date)
            logger.info("Fetching candles from %s to %s", start_date.isoformat(), end_date.isoformat())
            files = extractor.extract_all_timeframes_by_date_range(
                instrument=args.instrument,
                start_date=start_date,
                end_date=end_date,
                timeframes=args.timeframes,
            )
        else:
            files = extractor.extract_all_timeframes(
                instrument=args.instrument,
                count=args.count,
                timeframes=args.timeframes,
                price=args.price,
            )
    except Exception as exc:
        logger.error("Extraction failed: %s", exc)
        return 1

    if not files:
        logger.warning("No files were generated")
        return 1

    logger.info("Generated %s CSV files", len(files))
    for timeframe, path in files.items():
        logger.info("%s -> %s", timeframe, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
