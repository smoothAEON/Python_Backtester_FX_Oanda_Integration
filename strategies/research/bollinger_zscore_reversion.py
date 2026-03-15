"""Mean-reversion showcase strategy using limit entries and volatility sizing."""

from __future__ import annotations

from backtester.indicators.research import savgol_smooth
from backtester.sizing import VolatilitySizer

from .._shared import ShowcaseStrategy, latest_defined_value, latest_value, tail_is_ready


class BollingerZscoreReversionStrategy(ShowcaseStrategy):
    """Fade band extremes and target the middle band."""

    runtime_contract = "research_only"
    runtime_contract_reason = (
        "Imports savgol_smooth directly from the research-only indicator surface."
    )
    params = (
        ("band_period", 5),
        ("band_stddev", 1.4),
        ("zscore_window", 5),
        ("zscore_threshold", 0.75),
        ("smoothing_window", 5),
        ("smoothing_polyorder", 2),
        ("risk_percent", 0.004),
        ("volatility_multiplier", 1.0),
        ("stop_band_buffer", 0.6),
        ("stale_bars", 3),
    )

    def __init__(self) -> None:
        super().__init__()
        self.position_sizer = VolatilitySizer(
            float(self.p.risk_percent),
            volatility_multiplier=float(self.p.volatility_multiplier),
        )
        self._pending_entry_bar: int | None = None

    def next(self) -> None:
        if self._cancel_stale_entry():
            return
        if self.has_open_order() or not self.is_flat():
            return

        frame = self.to_ohlcv_dataframe()
        if len(frame) < max(int(self.p.band_period), int(self.p.zscore_window), 5):
            return

        bands = self.indicator(
            None,
            "bollinger_bands",
            period=int(self.p.band_period),
            nbdevup=float(self.p.band_stddev),
            nbdevdn=float(self.p.band_stddev),
            matype=0,
        )
        zscore = self.indicator(None, "rolling_zscore", window=int(self.p.zscore_window))
        smooth = savgol_smooth(
            frame["close"],
            window_length=int(self.p.smoothing_window),
            polyorder=int(self.p.smoothing_polyorder),
        )
        if not all(
            (
                tail_is_ready(bands, 1, "UpperBand"),
                tail_is_ready(bands, 1, "MiddleBand"),
                tail_is_ready(bands, 1, "LowerBand"),
                tail_is_ready(zscore, 1),
            )
        ):
            return
        defined_smooth = smooth.dropna()
        if len(defined_smooth) < 2:
            return

        upper_band = latest_value(bands, "UpperBand")
        middle_band = latest_value(bands, "MiddleBand")
        lower_band = latest_value(bands, "LowerBand")
        zscore_now = latest_value(zscore)
        smooth_prev = float(defined_smooth.iloc[-2])
        smooth_now = latest_defined_value(defined_smooth)
        if None in {upper_band, middle_band, lower_band, zscore_now, smooth_prev, smooth_now}:
            return

        band_width = max(upper_band - lower_band, self.instrument_spec.price_step)
        smoothing_bias = smooth_now - smooth_prev
        long_signal = (
            self.mid.close <= lower_band
            and zscore_now <= -float(self.p.zscore_threshold)
            and smoothing_bias >= -band_width
        )
        short_signal = (
            self.mid.close >= upper_band
            and zscore_now >= float(self.p.zscore_threshold)
            and smoothing_bias <= band_width
        )

        if long_signal and middle_band > lower_band:
            entry_price = self.round_price(lower_band)
            stop_price = self.round_price(entry_price - (band_width * float(self.p.stop_band_buffer)))
            decision = self.size_entry(
                self.position_sizer,
                side="long",
                entry_price=entry_price,
                stop_price=stop_price,
                metadata={"volatility": band_width},
            )
            if decision.accepted:
                self.submit_long_limit(
                    price=entry_price,
                    size=decision.final_size,
                    stop_loss=stop_price,
                    take_profit=self.round_price(middle_band),
                    sizing_decision=decision,
                )
                self._pending_entry_bar = len(self)
            return

        if short_signal and middle_band < upper_band:
            entry_price = self.round_price(upper_band)
            stop_price = self.round_price(entry_price + (band_width * float(self.p.stop_band_buffer)))
            decision = self.size_entry(
                self.position_sizer,
                side="short",
                entry_price=entry_price,
                stop_price=stop_price,
                metadata={"volatility": band_width},
            )
            if decision.accepted:
                self.submit_short_limit(
                    price=entry_price,
                    size=decision.final_size,
                    stop_loss=stop_price,
                    take_profit=self.round_price(middle_band),
                    sizing_decision=decision,
                )
                self._pending_entry_bar = len(self)

    def _cancel_stale_entry(self) -> bool:
        if not self.has_open_order():
            self._pending_entry_bar = None
            return False
        if self._pending_entry_bar is None:
            return False
        if len(self) - self._pending_entry_bar >= int(self.p.stale_bars):
            self.cancel_open_orders()
            self._pending_entry_bar = None
            return True
        return False
