"""Evidence contracts and safety helpers for research reports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EvidenceKind(str, Enum):
    VERIFIED_FACT = "verified_fact"
    MARKET_RUMOR = "market_rumor"
    LOGICAL_INFERENCE = "logical_inference"
    TRADING_HYPOTHESIS = "trading_hypothesis"


@dataclass(frozen=True)
class EvidenceItem:
    kind: EvidenceKind
    source_type: str
    title: str
    summary: str
    source: str
    published_at: str | None = None
    url: str | None = None
    confidence: str | None = None


FORBIDDEN_REPORT_TERMS = (
    "买入",
    "卖出",
    "加仓",
    "减仓",
    "仓位比例",
    "止损",
    "止盈",
    "目标价",
    "核心受益标的",
    "强call",
    "强Call",
    "强CALL",
)


def sanitize_report_text(value: str | None) -> str:
    text = "" if value is None else str(value)
    for term in FORBIDDEN_REPORT_TERMS:
        text = text.replace(term, "[动作词已屏蔽]")
    return text
