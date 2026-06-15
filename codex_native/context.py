"""Shared context-json parsing for Codex-native reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .evidence import EvidenceItem, EvidenceKind

CONTEXT_STATUSES = ("available", "partial", "stale", "missing", "fetch_failed", "not_supported")


@dataclass(frozen=True)
class StageStatusItem:
    stage: str
    status: str
    source: str = ""
    notes: str = ""


@dataclass(frozen=True)
class DataQualityItem:
    block: str
    status: str
    source: str = ""
    updated_at: str = ""
    notes: str = ""


@dataclass(frozen=True)
class RiskItem:
    category: str
    severity: str
    description: str
    source: str = ""


@dataclass(frozen=True)
class CoverageItem:
    block: str
    status: str
    source: str = ""
    fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class ToolAttempt:
    tool: str
    query: str = ""
    status: str = ""
    error: str = ""
    fallback: str = ""


@dataclass(frozen=True)
class IntelligenceContextItem:
    source_group: str
    group_id: str
    topic_id: str
    title: str
    summary: str
    tags: list[str] = field(default_factory=list)
    published_at: str = ""
    attachments: list[str] = field(default_factory=list)
    matched_symbols: list[str] = field(default_factory=list)
    matched_sectors: list[str] = field(default_factory=list)
    verification_status: str = "needs_verification"
    source_policy: str = "needs_verification"
    source_risk: str = "medium"
    suggested_section: str = "market_rumor"
    readers: int | None = None
    likes: int | None = None


@dataclass(frozen=True)
class CodexResearchContext:
    coverage: list[CoverageItem] = field(default_factory=list)
    stage_status: list[StageStatusItem] = field(default_factory=list)
    data_quality: list[DataQualityItem] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    intelligence_items: list[IntelligenceContextItem] = field(default_factory=list)
    risk_items: list[RiskItem] = field(default_factory=list)
    tool_attempts: list[ToolAttempt] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    data_limitations: list[str] = field(default_factory=list)
    breadth: dict[str, str] = field(default_factory=dict)
    sectors: list[str] = field(default_factory=list)
    funds: dict[str, Any] = field(default_factory=dict)

    def quality_limitations(self) -> list[str]:
        limitations: list[str] = []
        for item in self.data_quality:
            if item.status == "available":
                continue
            detail = f"数据块 {item.block} 状态 {item.status}"
            extras = []
            if item.source:
                extras.append(f"来源：{item.source}")
            if item.notes:
                extras.append(f"说明：{item.notes}")
            if extras:
                detail += "，" + "；".join(extras)
            limitations.append(detail)
        return limitations

    def all_limitations(self) -> list[str]:
        limitations: list[str] = []
        for item in [*self.data_limitations, *self.quality_limitations()]:
            if item and item not in limitations:
                limitations.append(item)
        return limitations


def load_context_json(path: str | Path) -> CodexResearchContext:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("context-json must contain a JSON object")
    return parse_context(data)


def parse_context(data: dict[str, Any] | None) -> CodexResearchContext:
    raw = data or {}
    intelligence_items = _coerce_intelligence_items(raw.get("intelligence_items"))
    return CodexResearchContext(
        coverage=_coerce_coverage(raw.get("coverage")),
        stage_status=_coerce_stage_status(raw.get("stage_status")),
        data_quality=_coerce_data_quality(raw.get("data_quality")),
        evidence=[*_coerce_evidence(raw.get("evidence")), *_intelligence_items_to_evidence(intelligence_items)],
        intelligence_items=intelligence_items,
        risk_items=_coerce_risk_items(raw.get("risk_items")),
        tool_attempts=_coerce_tool_attempts(raw.get("tool_attempts")),
        observations=_coerce_string_list(raw.get("observations")),
        data_limitations=_coerce_string_list(raw.get("data_limitations")),
        breadth=_coerce_string_dict(raw.get("breadth")),
        sectors=_coerce_string_list(raw.get("sectors")),
        funds=_coerce_nested_dict(raw.get("funds")),
    )


def _coerce_coverage(value: Any) -> list[CoverageItem]:
    if not isinstance(value, list):
        return []
    result: list[CoverageItem] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        status, status_note = _normalize_status(raw.get("status"))
        result.append(
            CoverageItem(
                block=_string_or_default(raw.get("block"), "unknown"),
                status=status,
                source=_string_or_default(raw.get("source"), ""),
                fields=_coerce_string_list(raw.get("fields")),
                missing_fields=_coerce_string_list(raw.get("missing_fields")),
                notes=_join_notes(_string_or_default(raw.get("notes"), ""), status_note),
            )
        )
    return result


def _coerce_stage_status(value: Any) -> list[StageStatusItem]:
    if not isinstance(value, list):
        return []
    result: list[StageStatusItem] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        status, status_note = _normalize_status(raw.get("status"))
        result.append(
            StageStatusItem(
                stage=_string_or_default(raw.get("stage"), "未命名阶段"),
                status=status,
                source=_string_or_default(raw.get("source"), ""),
                notes=_join_notes(_string_or_default(raw.get("notes"), ""), status_note),
            )
        )
    return result


def _coerce_data_quality(value: Any) -> list[DataQualityItem]:
    if not isinstance(value, list):
        return []
    result: list[DataQualityItem] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        status, status_note = _normalize_status(raw.get("status"))
        result.append(
            DataQualityItem(
                block=_string_or_default(raw.get("block"), "unknown"),
                status=status,
                source=_string_or_default(raw.get("source"), ""),
                updated_at=_string_or_default(raw.get("updated_at"), ""),
                notes=_join_notes(_string_or_default(raw.get("notes"), ""), status_note),
            )
        )
    return result


def _coerce_evidence(value: Any) -> list[EvidenceItem]:
    if not isinstance(value, list):
        return []
    result: list[EvidenceItem] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        try:
            kind = EvidenceKind(str(raw.get("kind", "")))
        except ValueError:
            continue
        result.append(
            EvidenceItem(
                kind=kind,
                source_type=_string_or_default(raw.get("source_type"), "unknown"),
                title=_string_or_default(raw.get("title"), "未命名证据"),
                summary=_string_or_default(raw.get("summary"), "未提供摘要。"),
                source=_string_or_default(raw.get("source"), "unknown"),
                published_at=_optional_string(raw.get("published_at")),
                url=_optional_string(raw.get("url")),
                confidence=_optional_string(raw.get("confidence")),
            )
        )
    return result


def _coerce_risk_items(value: Any) -> list[RiskItem]:
    if not isinstance(value, list):
        return []
    result: list[RiskItem] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        result.append(
            RiskItem(
                category=_string_or_default(raw.get("category"), "未分类风险"),
                severity=_string_or_default(raw.get("severity"), "unknown"),
                description=_string_or_default(raw.get("description"), "未提供风险说明。"),
                source=_string_or_default(raw.get("source"), ""),
            )
        )
    return result


def _coerce_tool_attempts(value: Any) -> list[ToolAttempt]:
    if not isinstance(value, list):
        return []
    result: list[ToolAttempt] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        status, status_note = _normalize_status(raw.get("status"))
        result.append(
            ToolAttempt(
                tool=_string_or_default(raw.get("tool"), "unknown"),
                query=_string_or_default(raw.get("query"), ""),
                status=status,
                error=_join_notes(_string_or_default(raw.get("error"), ""), status_note),
                fallback=_string_or_default(raw.get("fallback"), ""),
            )
        )
    return result


def _coerce_intelligence_items(value: Any) -> list[IntelligenceContextItem]:
    if not isinstance(value, list):
        return []
    result: list[IntelligenceContextItem] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        result.append(
            IntelligenceContextItem(
                source_group=_string_or_default(raw.get("source_group"), "小牛研报纪要"),
                group_id=_string_or_default(raw.get("group_id"), "15555851111822"),
                topic_id=_string_or_default(raw.get("topic_id"), ""),
                title=_string_or_default(raw.get("title"), "未命名知识星球线索"),
                summary=_string_or_default(raw.get("summary"), "未提供摘要。"),
                tags=_coerce_string_list(raw.get("tags")),
                published_at=_string_or_default(raw.get("published_at"), ""),
                attachments=_coerce_string_list(raw.get("attachments")),
                matched_symbols=_coerce_string_list(raw.get("matched_symbols")),
                matched_sectors=_coerce_string_list(raw.get("matched_sectors")),
                verification_status=_string_or_default(raw.get("verification_status"), "needs_verification"),
                source_policy=_string_or_default(raw.get("source_policy"), "needs_verification"),
                source_risk=_string_or_default(raw.get("source_risk"), "medium"),
                suggested_section=_string_or_default(raw.get("suggested_section"), "market_rumor"),
                readers=_optional_int(raw.get("readers")),
                likes=_optional_int(raw.get("likes")),
            )
        )
    return result


def _intelligence_items_to_evidence(values: list[IntelligenceContextItem]) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    for item in values:
        details = [
            "知识星球内容未经二次核验，默认作为情报线索处理。",
            item.summary,
        ]
        if item.tags:
            details.append("标签：" + "、".join(item.tags))
        if item.attachments:
            details.append("附件：" + "、".join(item.attachments))
        if item.matched_symbols:
            details.append("匹配标的：" + "、".join(item.matched_symbols))
        if item.matched_sectors:
            details.append("匹配行业：" + "、".join(item.matched_sectors))
        source = item.source_group
        if item.topic_id:
            source += f" topic_id={item.topic_id}"
        evidence.append(
            EvidenceItem(
                kind=_intelligence_kind(item),
                source_type="zsxq_intelligence",
                title=item.title,
                summary=" ".join(details),
                source=source,
                published_at=item.published_at or None,
                confidence=f"{item.verification_status}/{item.source_risk}",
            )
        )
    return evidence


def _intelligence_kind(item: IntelligenceContextItem) -> EvidenceKind:
    if item.verification_status == "verified" and item.suggested_section == EvidenceKind.VERIFIED_FACT.value:
        return EvidenceKind.VERIFIED_FACT
    if item.suggested_section == EvidenceKind.LOGICAL_INFERENCE.value:
        return EvidenceKind.LOGICAL_INFERENCE
    if item.suggested_section == EvidenceKind.TRADING_HYPOTHESIS.value:
        return EvidenceKind.TRADING_HYPOTHESIS
    return EvidenceKind.MARKET_RUMOR


def _normalize_status(value: Any) -> tuple[str, str]:
    raw = _string_or_default(value, "").lower()
    if raw in CONTEXT_STATUSES:
        return raw, ""
    return "partial", f"原始状态：{raw or 'missing'}"


def _coerce_string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


def _coerce_nested_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        if item is None:
            continue
        if isinstance(item, dict):
            result[str(key)] = _coerce_string_dict(item)
        elif isinstance(item, list):
            result[str(key)] = _coerce_string_list(item)
        else:
            result[str(key)] = str(item)
    return result


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _string_or_default(value: Any, default: str) -> str:
    text = "" if value is None else str(value).strip()
    return text or default


def _optional_string(value: Any) -> str | None:
    text = _string_or_default(value, "")
    return text or None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _join_notes(*values: str) -> str:
    return "；".join(value for value in values if value)
