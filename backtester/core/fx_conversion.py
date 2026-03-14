"""Account-currency conversion helpers for FX backtests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


def split_instrument_currencies(instrument: str) -> tuple[str, str]:
    """Split one OANDA-style instrument into base and quote currencies."""

    normalized = str(instrument).strip().upper()
    parts = normalized.split("_")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Unsupported instrument format for FX conversion: {instrument!r}")
    return parts[0], parts[1]


def direct_quote_to_account_rate(
    instrument: str,
    *,
    price: float,
    account_currency: str = "USD",
) -> float | None:
    """Resolve direct quote-to-account conversion when the pair contains the account currency."""

    normalized_account = str(account_currency).strip().upper()
    if not normalized_account:
        raise ValueError("account_currency must be a non-empty string")
    if price <= 0:
        raise ValueError("price must be positive for FX conversion")

    base, quote = split_instrument_currencies(instrument)
    if quote == normalized_account:
        return 1.0
    if base == normalized_account:
        return 1.0 / float(price)
    return None


@dataclass(slots=True, frozen=True)
class QuoteConversionPolicy:
    """Describe how quote-currency amounts are converted into the account currency."""

    account_currency: str
    mode: str
    source_instrument: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "account_currency": self.account_currency,
            "quote_to_account_mode": self.mode,
            "quote_to_account_source": self.source_instrument,
        }


class QuoteConversionBook:
    """Resolve quote-to-account conversion rates from direct prices or auxiliary series."""

    def __init__(
        self,
        *,
        account_currency: str = "USD",
        conversion_frames: dict[str, pd.DataFrame] | None = None,
    ) -> None:
        normalized_account = str(account_currency).strip().upper()
        if not normalized_account:
            raise ValueError("account_currency must be a non-empty string")
        self.account_currency = normalized_account
        self._conversion_frames = {
            str(instrument).strip().upper(): frame.copy()
            for instrument, frame in dict(conversion_frames or {}).items()
        }

    def policy_for_instrument(self, instrument: str) -> QuoteConversionPolicy:
        base, quote = split_instrument_currencies(instrument)
        if quote == self.account_currency:
            return QuoteConversionPolicy(
                account_currency=self.account_currency,
                mode="quote_currency_is_account_currency",
            )
        if base == self.account_currency:
            return QuoteConversionPolicy(
                account_currency=self.account_currency,
                mode="dynamic_from_instrument_price",
                source_instrument=str(instrument).strip().upper(),
            )

        direct = f"{quote}_{self.account_currency}"
        if direct in self._conversion_frames:
            return QuoteConversionPolicy(
                account_currency=self.account_currency,
                mode="dynamic_from_conversion_data",
                source_instrument=direct,
            )

        inverse = f"{self.account_currency}_{quote}"
        if inverse in self._conversion_frames:
            return QuoteConversionPolicy(
                account_currency=self.account_currency,
                mode="dynamic_from_inverse_conversion_data",
                source_instrument=inverse,
            )

        raise ValueError(
            "No quote-to-account conversion path is available for "
            f"{instrument!r} into {self.account_currency}. Provide conversion_data "
            f"for {quote}_{self.account_currency} or {self.account_currency}_{quote}."
        )

    def quote_to_account_rate(
        self,
        instrument: str,
        *,
        price: float,
        dt: pd.Timestamp | Any | None,
    ) -> float:
        direct = direct_quote_to_account_rate(
            instrument,
            price=float(price),
            account_currency=self.account_currency,
        )
        if direct is not None:
            return float(direct)

        policy = self.policy_for_instrument(instrument)
        if policy.source_instrument is None:
            raise ValueError(f"Conversion policy is missing a source for {instrument!r}")

        source_price = self._source_price(policy.source_instrument, dt)
        if policy.mode == "dynamic_from_conversion_data":
            return source_price
        if policy.mode == "dynamic_from_inverse_conversion_data":
            if source_price <= 0:
                raise ValueError(
                    f"Inverse conversion price must be positive for {policy.source_instrument}"
                )
            return 1.0 / source_price

        raise ValueError(f"Unsupported conversion mode: {policy.mode!r}")

    def _source_price(self, instrument: str, dt: pd.Timestamp | Any | None) -> float:
        frame = self._conversion_frames.get(str(instrument).strip().upper())
        if frame is None:
            raise ValueError(f"Missing conversion data for {instrument!r}")

        if dt is None:
            visible = frame
        else:
            timestamp = pd.Timestamp(dt)
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize("UTC")
            else:
                timestamp = timestamp.tz_convert("UTC")
            visible = frame.loc[frame.index <= timestamp]

        if visible.empty:
            raise ValueError(
                f"No completed conversion bar is available yet for {instrument!r}"
            )
        return float(visible.iloc[-1]["close"])
