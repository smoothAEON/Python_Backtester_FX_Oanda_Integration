"""CSV persistence layer with atomic writes and legacy-path migration."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class CSVPersistence:
    """
    Thread-safe CSV persistence with atomic writes.

    Canonical layout:
    data/<INSTRUMENT>/candles_<INSTRUMENT>_<TIMEFRAME>.csv
    """

    CANDLE_COLUMNS = [
        'time', 'open', 'high', 'low', 'close', 'volume',
        'bid_open', 'bid_high', 'bid_low', 'bid_close',
        'ask_open', 'ask_high', 'ask_low', 'ask_close',
    ]

    def __init__(self, data_dir: Path):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _normalize_instrument_name(self, instrument: str) -> str:
        """Normalize the instrument name for filesystem usage."""
        return instrument.replace('/', '_').replace('-', '_')

    def _get_instrument_dir(self, instrument: str) -> Path:
        """Get the canonical directory for an instrument."""
        safe_instrument = self._normalize_instrument_name(instrument)
        instrument_dir = self._data_dir / safe_instrument
        instrument_dir.mkdir(parents=True, exist_ok=True)
        return instrument_dir

    def _get_candle_path(self, instrument: str, timeframe: str) -> Path:
        """
        Get canonical path for candle CSV.

        Naming: data/<INSTRUMENT>/candles_<INSTRUMENT>_<TIMEFRAME>.csv
        Example: data/XAU_USD/candles_XAU_USD_H1.csv
        """
        safe_instrument = self._normalize_instrument_name(instrument)
        return self._get_instrument_dir(instrument) / f"candles_{safe_instrument}_{timeframe}.csv"

    def _get_legacy_candle_path(self, instrument: str, timeframe: str) -> Path:
        """Get the legacy flat candle CSV path under data/."""
        safe_instrument = self._normalize_instrument_name(instrument)
        return self._data_dir / f"candles_{safe_instrument}_{timeframe}.csv"

    def get_candle_path(self, instrument: str, timeframe: str) -> Path:
        """Public wrapper for the canonical candle path."""
        return self._get_candle_path(instrument, timeframe)

    def _get_staging_path(self, instrument: str, timeframe: str) -> Path:
        """Get the staging path used for an atomic save cycle."""
        return self._get_candle_path(instrument, timeframe).with_suffix('.tmp')

    def _validate_candle_frame(self, df: pd.DataFrame) -> bool:
        """Validate the minimum candle columns required for persistence."""
        missing_cols = set(self.CANDLE_COLUMNS) - set(df.columns)
        if missing_cols:
            logger.error(f"Missing columns in DataFrame: {missing_cols}")
            return False
        return True

    def _load_path(self, path: Path) -> pd.DataFrame:
        """Load and normalize candles from a specific path."""
        df = pd.read_csv(path, encoding='utf-8')
        missing_cols = set(self.CANDLE_COLUMNS) - set(df.columns)
        if missing_cols:
            raise ValueError(f"CSV missing columns {missing_cols}")
        df['time'] = pd.to_datetime(df['time'], utc=True)
        return df.sort_values('time').drop_duplicates(subset=['time'], keep='last').reset_index(drop=True)

    def _promote_file(self, source_path: Path, target_path: Path) -> bool:
        """Move a file into place, creating parent directories when needed."""
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                target_path.unlink()
            source_path.rename(target_path)
            return True
        except Exception as error:
            logger.error(f"Failed to move {source_path} to {target_path}: {error}")
            return False

    def promote_staging_file(self, temp_path: Path, instrument: str, timeframe: str) -> bool:
        """Atomically promote a staging file to the canonical candle path."""
        target_path = self._get_candle_path(instrument, timeframe)
        backup_path = target_path.with_suffix('.csv.bak')

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                if backup_path.exists():
                    backup_path.unlink()
                target_path.rename(backup_path)
            temp_path.rename(target_path)
            return True
        except Exception as error:
            logger.error(f"Failed to promote staging file {temp_path}: {error}")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            return False

    def migrate_legacy_file(self, instrument: str, timeframe: str) -> Optional[Path]:
        """Move a legacy flat file and sidecar artifacts into the canonical folder."""
        legacy_path = self._get_legacy_candle_path(instrument, timeframe)
        target_path = self._get_candle_path(instrument, timeframe)
        if not legacy_path.exists():
            return None

        if not self._promote_file(legacy_path, target_path):
            return None

        legacy_backup = legacy_path.with_suffix('.csv.bak')
        if legacy_backup.exists():
            self._promote_file(legacy_backup, target_path.with_suffix('.csv.bak'))

        legacy_temp = legacy_path.with_suffix('.tmp')
        if legacy_temp.exists():
            self._promote_file(legacy_temp, target_path.with_suffix('.tmp'))

        logger.info(f"Migrated legacy candle file to {target_path}")
        return target_path

    def migrate_legacy_files(self, instrument: Optional[str] = None) -> list[Path]:
        """Bulk-migrate legacy flat files under data/ into canonical instrument folders."""
        migrated: list[Path] = []
        pattern = "candles_*.csv"
        for legacy_path in self._data_dir.glob(pattern):
            if legacy_path.parent != self._data_dir:
                continue
            stem = legacy_path.stem
            if not stem.startswith("candles_"):
                continue
            suffix = stem[len("candles_"):]
            instrument_part, _, timeframe = suffix.rpartition("_")
            if not instrument_part or not timeframe:
                continue
            if instrument is not None and self._normalize_instrument_name(instrument) != instrument_part:
                continue
            migrated_path = self.migrate_legacy_file(instrument_part, timeframe)
            if migrated_path is not None:
                migrated.append(migrated_path)
        return migrated

    def save_candles(self, df: pd.DataFrame, instrument: str, timeframe: str) -> bool:
        """Save candles to CSV with atomic write pattern."""
        target_path = self._get_candle_path(instrument, timeframe)
        temp_path = self.start_staging_file(instrument, timeframe)

        try:
            if not self._validate_candle_frame(df):
                return False
            df.to_csv(temp_path, index=False, encoding='utf-8')
            if not self.promote_staging_file(temp_path, instrument, timeframe):
                return False
            logger.debug(f"Saved {len(df)} candles to {target_path}")
            return True
        except Exception as error:
            logger.error(f"Failed to save candles: {error}")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            return False

    def load_candles(self, instrument: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Load candles from CSV with validation and legacy-path migration."""
        target_path = self._get_candle_path(instrument, timeframe)
        if not target_path.exists():
            self.migrate_legacy_file(instrument, timeframe)

        if target_path.exists():
            try:
                return self._load_path(target_path)
            except Exception as error:
                logger.warning(f"Failed to load CSV: {error}, attempting backup")
                return self._try_backup(instrument, timeframe)

        logger.debug(f"No CSV found at {target_path}")
        return None

    def _try_backup(self, instrument: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Attempt to load from backup file, including legacy backup migration."""
        target_backup = self._get_candle_path(instrument, timeframe).with_suffix('.csv.bak')
        legacy_backup = self._get_legacy_candle_path(instrument, timeframe).with_suffix('.csv.bak')

        if not target_backup.exists() and legacy_backup.exists():
            self._promote_file(legacy_backup, target_backup)

        if not target_backup.exists():
            return None

        try:
            df = self._load_path(target_backup)
            logger.info(f"Recovered {len(df)} candles from backup {target_backup}")
            return df
        except Exception as error:
            logger.error(f"Backup recovery failed: {error}")
            return None

    def candles_exist(self, instrument: str, timeframe: str) -> bool:
        """Check if candles CSV exists in canonical or legacy storage."""
        target_path = self._get_candle_path(instrument, timeframe)
        legacy_path = self._get_legacy_candle_path(instrument, timeframe)
        return target_path.exists() or legacy_path.exists()

    def append_candles(self, df: pd.DataFrame, instrument: str, timeframe: str) -> bool:
        """Append candles to the canonical CSV or create a new one."""
        return self.append_to_path(df, self._get_candle_path(instrument, timeframe))

    def start_staging_file(self, instrument: str, timeframe: str) -> Path:
        """Create a clean staging path for streamed atomic writes."""
        temp_path = self._get_staging_path(instrument, timeframe)
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        if temp_path.exists():
            temp_path.unlink()
        return temp_path

    def append_to_path(self, df: pd.DataFrame, path: Path) -> bool:
        """Append candle rows to an arbitrary CSV path."""
        try:
            if not self._validate_candle_frame(df):
                return False
            if df.empty:
                return True

            path.parent.mkdir(parents=True, exist_ok=True)
            file_exists = path.exists() and path.stat().st_size > 0
            df.to_csv(
                path,
                index=False,
                encoding='utf-8',
                mode='a',
                header=not file_exists,
            )
            logger.debug(f"Appended {len(df)} candles to {path}")
            return True
        except Exception as error:
            logger.error(f"Failed to append candles to {path}: {error}")
            return False

    def get_latest_time(self, instrument: str, timeframe: str) -> Optional[pd.Timestamp]:
        """Get the latest candle time from CSV."""
        df = self.load_candles(instrument, timeframe)
        if df is None or df.empty:
            return None
        return df['time'].max()

    def get_earliest_time(self, instrument: str, timeframe: str) -> Optional[pd.Timestamp]:
        """Get the earliest candle time from CSV."""
        df = self.load_candles(instrument, timeframe)
        if df is None or df.empty:
            return None
        return df['time'].min()
