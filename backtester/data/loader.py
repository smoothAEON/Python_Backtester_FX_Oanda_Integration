"""Data loading entry points for backtests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .validation import validate_oanda_dataframe


class OANDADataLoader:
    """Load and normalize extractor-native CSVs or in-memory DataFrames."""

    def __init__(self, *, allow_dedupe: bool = False) -> None:
        self.allow_dedupe = allow_dedupe

    def load_csv(self, csv_path: str) -> pd.DataFrame:
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV path does not exist: {path}")

        df = pd.read_csv(path)
        return self.load_dataframe(df)

    def load_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        validated = validate_oanda_dataframe(df, allow_dedupe=self.allow_dedupe)
        return validated.set_index("time", drop=False)
