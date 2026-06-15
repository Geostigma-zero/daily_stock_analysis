"""Small technical indicator helpers for local TDX daily bars."""

from __future__ import annotations

from .models import DailyBar, TechnicalIndicators


def calculate_indicators(bars: list[DailyBar]) -> TechnicalIndicators:
    if not bars:
        raise ValueError("at least one daily bar is required")
    ordered = sorted(bars, key=lambda bar: bar.trade_date)
    latest = ordered[-1]
    previous = ordered[-2] if len(ordered) >= 2 else None
    closes = [bar.close for bar in ordered]
    volumes = [bar.volume for bar in ordered]

    return TechnicalIndicators(
        latest_trade_date=latest.trade_date,
        last_close=round(latest.close, 2),
        change_pct_1d=_pct_change(previous.close, latest.close) if previous else None,
        ma5=_ma(closes, 5),
        ma10=_ma(closes, 10),
        ma20=_ma(closes, 20),
        volume_ratio_5d=_volume_ratio(volumes, 5),
    )


def _ma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return round(sum(values[-window:]) / window, 2)


def _pct_change(previous: float, current: float) -> float | None:
    if previous == 0:
        return None
    return round((current / previous - 1) * 100, 2)


def _volume_ratio(values: list[float], window: int) -> float | None:
    if not values:
        return None
    sample = values[-window:]
    average = sum(sample) / len(sample)
    if average == 0:
        return None
    return round(values[-1] / average, 2)
