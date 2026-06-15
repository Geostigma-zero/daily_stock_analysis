"""Shared data contracts for the Codex-native research workflow."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DailyBar:
    trade_date: str
    code: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float
    adj_close: float | None = None
    source: str = "tdx-local"


@dataclass(frozen=True)
class TechnicalIndicators:
    latest_trade_date: str
    last_close: float
    change_pct_1d: float | None
    ma5: float | None
    ma10: float | None
    ma20: float | None
    volume_ratio_5d: float | None


@dataclass(frozen=True)
class MarketDataSnapshot:
    code: str
    name: str
    phase: str
    bars: list[DailyBar]
    indicators: TechnicalIndicators
    data_sources: dict[str, str] = field(default_factory=dict)
    data_limitations: list[str] = field(default_factory=list)
    f10: dict[str, str] = field(default_factory=dict)
    funds: dict[str, str] = field(default_factory=dict)
    sectors: list[str] = field(default_factory=list)
    realtime: dict[str, str] = field(default_factory=dict)
