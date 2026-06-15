"""Markdown report rendering for Codex-native A-share research."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .context import DataQualityItem, IntelligenceContextItem, RiskItem, StageStatusItem
from .evidence import EvidenceItem, EvidenceKind, sanitize_report_text
from .models import MarketDataSnapshot


@dataclass(frozen=True)
class ResearchReport:
    snapshot: MarketDataSnapshot
    phase: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    summary: str | None = None
    observations: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    risk_items: list[RiskItem] = field(default_factory=list)
    stage_status: list[StageStatusItem] = field(default_factory=list)
    data_quality: list[DataQualityItem] = field(default_factory=list)
    intelligence_items: list[IntelligenceContextItem] = field(default_factory=list)
    data_limitations: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


SECTION_TITLES = {
    EvidenceKind.VERIFIED_FACT: "已验证事实",
    EvidenceKind.MARKET_RUMOR: "市场传闻",
    EvidenceKind.LOGICAL_INFERENCE: "逻辑推演",
    EvidenceKind.RESEARCH_HYPOTHESIS: "研究假设",
}

LOCAL_PATH_PATTERN = re.compile(r"[A-Za-z]:[\\/][^\s；，,|)]+")


def build_research_report(
    snapshot: MarketDataSnapshot,
    phase: str,
    evidence: list[EvidenceItem] | None = None,
    observations: list[str] | None = None,
    risks: list[str] | None = None,
    risk_items: list[RiskItem] | None = None,
    stage_status: list[StageStatusItem] | None = None,
    data_quality: list[DataQualityItem] | None = None,
    intelligence_items: list[IntelligenceContextItem] | None = None,
    data_limitations: list[str] | None = None,
) -> ResearchReport:
    indicator = snapshot.indicators
    summary = (
        f"{snapshot.name}（{snapshot.code}）最新本地日线为 {indicator.latest_trade_date}，"
        f"收盘价 {indicator.last_close:.2f}，1 日涨跌幅 {_format_optional_pct(indicator.change_pct_1d)}，"
        f"5 日均线 {_format_optional_number(indicator.ma5)}，5 日量比 {_format_optional_number(indicator.volume_ratio_5d)}。"
    )
    merged_limits = list(snapshot.data_limitations)
    for item in data_limitations or []:
        if item not in merged_limits:
            merged_limits.append(item)
    return ResearchReport(
        snapshot=snapshot,
        phase=phase,
        evidence=evidence or [],
        summary=summary,
        observations=observations or _default_observations(),
        risks=risks or _default_risks(),
        risk_items=risk_items or [],
        stage_status=stage_status or [],
        data_quality=data_quality or [],
        intelligence_items=intelligence_items or [],
        data_limitations=merged_limits,
    )


def render_markdown(report: ResearchReport, appendix_name: str | None = None) -> str:
    snapshot = report.snapshot
    lines = [
        "# Codex Native A股研究报告",
        "",
        f"标的：{_clean(snapshot.name)}（{snapshot.code}）",
        f"阶段：{_clean(report.phase)}",
        f"生成时间：{_clean(report.generated_at)}",
        "",
        "> 本报告仅用于研究记录，不构成交易建议。",
        "",
        "## 研究质量卡",
        "",
    ]
    lines.extend(_render_quality_card(report, appendix_name=appendix_name))
    lines.extend(
        [
            "",
        "## 核心研究摘要",
        "",
        _clean(report.summary),
        "",
        "## 数据摘要",
        "",
        f"- 最新交易日：{snapshot.indicators.latest_trade_date}",
        f"- 最新收盘价：{snapshot.indicators.last_close:.2f}",
        f"- 1 日涨跌幅：{_format_optional_pct(snapshot.indicators.change_pct_1d)}",
        f"- MA5 / MA10 / MA20：{_format_optional_number(snapshot.indicators.ma5)} / "
        f"{_format_optional_number(snapshot.indicators.ma10)} / {_format_optional_number(snapshot.indicators.ma20)}",
        f"- 5 日量比：{_format_optional_number(snapshot.indicators.volume_ratio_5d)}",
        f"- 数据来源：{_clean(_format_sources(snapshot.data_sources))}",
        "",
        ]
    )
    lines.extend(_render_stage_status(report.stage_status))
    lines.extend(_render_data_quality(report.data_quality))
    if report.intelligence_items:
        lines.extend(["## 私域情报摘要", ""])
        lines.extend(_render_private_intelligence_summary(report.intelligence_items, appendix_name=appendix_name))
        lines.append("")

    grouped = _group_evidence([item for item in report.evidence if not _is_private_intelligence_evidence(item)])
    for kind in (
        EvidenceKind.VERIFIED_FACT,
        EvidenceKind.MARKET_RUMOR,
        EvidenceKind.LOGICAL_INFERENCE,
        EvidenceKind.RESEARCH_HYPOTHESIS,
    ):
        lines.extend([f"## {SECTION_TITLES[kind]}", ""])
        items = grouped.get(kind, [])
        if not items:
            lines.extend(["- 暂无可写入证据。", ""])
            continue
        for item in items:
            meta = "；".join(
                part
                for part in (
                    f"来源类型：{_clean(item.source_type)}",
                    f"来源：{_clean(item.source)}",
                    f"时间：{_clean(item.published_at)}" if item.published_at else None,
                    f"置信度：{_clean(item.confidence)}" if item.confidence else None,
                    f"链接：{_clean(item.url)}" if item.url else None,
                )
                if part
            )
            lines.append(f"- {_clean(item.title)}")
            lines.append(f"  摘要：{_clean(item.summary)}")
            lines.append(f"  证据：{meta}")
        lines.append("")

    lines.extend(["## 观察条件", ""])
    lines.extend(_format_bullets(report.observations))
    lines.extend(["", "## 风险提示", ""])
    lines.extend(_format_bullets(_format_risk_items(report.risk_items) + report.risks))
    lines.extend(["", "## 数据缺口", ""])
    limitations = report.data_limitations or ["暂无已知数据缺口。"]
    lines.extend(_format_bullets(limitations))
    lines.append("")
    return "\n".join(lines)


def render_research_appendix_markdown(report: ResearchReport) -> str:
    snapshot = report.snapshot
    lines = [
        "# Codex Native A股研究报告附录",
        "",
        f"标的：{_clean(snapshot.name)}（{snapshot.code}）",
        f"阶段：{_clean(report.phase)}",
        f"生成时间：{_clean(report.generated_at)}",
        "",
        "> 附录用于个人研究追溯，只保存结构化元数据、短摘要和附件文件名；私域情报不作为已验证事实。",
        "",
        "## 私域情报索引",
        "",
    ]
    lines.extend(_render_private_intelligence_index(report.intelligence_items))
    lines.extend(["", "## 私域情报短摘要", ""])
    lines.extend(_render_private_intelligence_notes(report.intelligence_items))
    lines.extend(["", "## 附件清单", ""])
    lines.extend(_render_private_intelligence_attachments(report.intelligence_items))
    lines.append("")
    return "\n".join(lines)


def _group_evidence(evidence: list[EvidenceItem]) -> dict[EvidenceKind, list[EvidenceItem]]:
    grouped: dict[EvidenceKind, list[EvidenceItem]] = {}
    for item in evidence:
        grouped.setdefault(_display_kind(item.kind), []).append(item)
    return grouped


def _display_kind(kind: EvidenceKind) -> EvidenceKind:
    if kind == EvidenceKind.TRADING_HYPOTHESIS:
        return EvidenceKind.RESEARCH_HYPOTHESIS
    return kind


def _is_private_intelligence_evidence(item: EvidenceItem) -> bool:
    return item.source_type == "zsxq_intelligence"


def _render_quality_card(report: ResearchReport, appendix_name: str | None) -> list[str]:
    score = _quality_score(report)
    public_evidence_count = sum(1 for item in report.evidence if not _is_private_intelligence_evidence(item))
    private_status = (
        f"{len(report.intelligence_items)} 条；完整索引见附录：{appendix_name or '未生成'}"
        if report.intelligence_items
        else "0 条；未生成附录"
    )
    return [
        "| 项目 | 结果 |",
        "| --- | --- |",
        f"| 质量分 | {_clean(str(score))}/100（{_clean(_quality_grade(score))}） |",
        f"| 阶段口径 | {_clean(_phase_label(report.phase))} |",
        f"| 数据质量状态 | {_clean(_quality_status_counts(report.data_quality))} |",
        f"| 降级/缺失块 | {_clean(_non_available_quality_blocks(report.data_quality))} |",
        f"| 公开证据 | {_clean(str(public_evidence_count))} 条 |",
        f"| 私域情报 | {_clean(private_status)} |",
    ]


def _quality_score(report: ResearchReport) -> int:
    if not report.data_quality:
        return 75 if report.stage_status or report.evidence else 70
    penalties = {
        "available": 0,
        "partial": 8,
        "stale": 10,
        "missing": 18,
        "fetch_failed": 18,
        "not_supported": 14,
    }
    score = 100
    for item in report.data_quality:
        score -= penalties.get(item.status, 12)
    return max(0, score)


def _quality_grade(score: int) -> str:
    if score >= 90:
        return "完整"
    if score >= 75:
        return "可用"
    if score >= 60:
        return "降级可用"
    return "重度降级"


def _quality_status_counts(values: list[DataQualityItem]) -> str:
    if not values:
        return "无数据质量上下文"
    counts: dict[str, int] = {}
    for item in values:
        counts[item.status] = counts.get(item.status, 0) + 1
    return "；".join(f"{status}={count}" for status, count in sorted(counts.items()))


def _non_available_quality_blocks(values: list[DataQualityItem]) -> str:
    if not values:
        return "未提供数据质量对账"
    degraded = [f"{item.block}={item.status}" for item in values if item.status != "available"]
    return "、".join(degraded) if degraded else "无"


def _phase_label(phase: str) -> str:
    labels = {
        "premarket": "盘前观察",
        "intraday": "盘中研究",
        "postmarket": "盘后研究",
    }
    return labels.get(phase, phase)


def _render_private_intelligence_summary(
    items: list[IntelligenceContextItem],
    appendix_name: str | None,
) -> list[str]:
    pending = sum(1 for item in items if item.verification_status != "verified")
    attachment_topics = sum(1 for item in items if item.attachments)
    high_risk = sum(1 for item in items if item.source_risk == "high")
    appendix = appendix_name or "未生成"
    return [
        (
            f"- 私域情报共 {len(items)} 条；待核验 {pending} 条；"
            f"含附件主题 {attachment_topics} 条；高风险 {high_risk} 条。"
        ),
        "- Top 行业：" + (_format_inline_counts(_count_terms(items, "sectors"), limit=8) or "暂无匹配行业"),
        "- Top 标的：" + (_format_inline_counts(_count_terms(items, "symbols"), limit=8) or "暂无匹配标的"),
        (
            f"- 主报告只保留聚合摘要；单条私域线索不写入已验证事实，"
            f"完整索引见附录：{_clean(appendix)}。"
        ),
    ]


def _render_private_intelligence_index(items: list[IntelligenceContextItem]) -> list[str]:
    if not items:
        return ["- 暂无私域情报条目。"]
    lines = [
        "| 时间 | topic_id | 分区 | 核验 | 风险 | 标签 | 标的 | 行业 | 标题 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        lines.append(
            "| "
            + " | ".join(
                [
                    _table_cell(item.published_at or "N/A"),
                    _table_cell(item.topic_id or "N/A"),
                    _table_cell(item.suggested_section or "market_rumor"),
                    _table_cell(item.verification_status),
                    _table_cell(item.source_risk),
                    _table_cell("、".join(item.tags) if item.tags else "N/A"),
                    _table_cell("、".join(item.matched_symbols) if item.matched_symbols else "N/A"),
                    _table_cell("、".join(item.matched_sectors) if item.matched_sectors else "N/A"),
                    _table_cell(item.title),
                ]
            )
            + " |"
        )
    return lines


def _render_private_intelligence_notes(items: list[IntelligenceContextItem]) -> list[str]:
    if not items:
        return ["- 暂无私域情报短摘要。"]
    lines: list[str] = []
    for item in items:
        lines.append(
            f"- topic_id={_clean(item.topic_id or 'N/A')}；section={_clean(item.suggested_section or 'market_rumor')}；"
            f"summary={_clean(_trim(item.summary, limit=140))}"
        )
    return lines


def _render_private_intelligence_attachments(items: list[IntelligenceContextItem]) -> list[str]:
    lines: list[str] = []
    for item in items:
        for name in item.attachments:
            lines.append(f"- topic_id={_clean(item.topic_id or 'N/A')}；附件={_clean(_trim(name, limit=120))}")
    return lines or ["- 暂无附件元数据。"]


def _count_terms(items: list[IntelligenceContextItem], kind: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        values = item.matched_sectors if kind == "sectors" else item.matched_symbols
        for value in values:
            if not value:
                continue
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda entry: (-entry[1], entry[0])))


def _format_inline_counts(values: dict[str, int], limit: int) -> str:
    selected = list(values.items())[:limit]
    parts = [f"{_clean(key)}：{count} 条" for key, count in selected]
    remaining = len(values) - len(selected)
    if remaining > 0:
        parts.append(f"另有 {remaining} 项")
    return "、".join(parts)


def _table_cell(value: str) -> str:
    return _clean(_trim(value, limit=80)).replace("|", "/").replace("\n", " ")


def _trim(value: str, limit: int = 120) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."


def _format_bullets(values: list[str]) -> list[str]:
    return [f"- {_clean(value)}" for value in values]


def _render_stage_status(values: list[StageStatusItem]) -> list[str]:
    lines = ["## 阶段执行状态", ""]
    if not values:
        lines.extend(["- 暂无 Codex 阶段状态上下文。", ""])
        return lines
    lines.extend(["| 阶段 | 状态 | 来源 | 说明 |", "| --- | --- | --- | --- |"])
    for item in values:
        lines.append(
            f"| {_clean(item.stage)} | {_clean(item.status)} | {_clean(item.source or 'N/A')} | {_clean(item.notes or 'N/A')} |"
        )
    lines.append("")
    return lines


def _render_data_quality(values: list[DataQualityItem]) -> list[str]:
    lines = ["## 数据质量", ""]
    if not values:
        lines.extend(["- 暂无 Codex 数据质量上下文。", ""])
        return lines
    lines.extend(["| 数据块 | 状态 | 来源 | 更新时间 | 说明 |", "| --- | --- | --- | --- | --- |"])
    for item in values:
        lines.append(
            "| "
            + " | ".join(
                [
                    _clean(item.block),
                    _clean(item.status),
                    _clean(item.source or "N/A"),
                    _clean(item.updated_at or "N/A"),
                    _clean(item.notes or "N/A"),
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def _format_risk_items(values: list[RiskItem]) -> list[str]:
    formatted: list[str] = []
    for item in values:
        suffix = f"（来源：{item.source}）" if item.source else ""
        formatted.append(f"{item.category}（{item.severity}）：{item.description}{suffix}")
    return formatted


def _format_sources(values: dict[str, str]) -> str:
    if not values:
        return "未记录"
    return "；".join(f"{key}={_format_source_value(value)}" for key, value in values.items())


def _format_source_value(value: str) -> str:
    text = str(value)
    if text.startswith("ranker-db:") and text != "ranker-db:stocks":
        return "ranker-db:<redacted>"
    if text.startswith("tdx-local:") and text not in {"tdx-local:tnf", "tdx-local:gbbq"}:
        return "tdx-local:<redacted>"
    return _redact_local_paths(text)


def _format_optional_number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def _format_optional_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def _default_observations() -> list[str]:
    return [
        "关注价格相对 MA5 / MA10 的持续性，以及成交量是否与价格变化同向确认。",
        "公告、研报、新闻与社交内容需交叉验证后再提升结论置信度。",
    ]


def _default_risks() -> list[str]:
    return [
        "本地通达信日线可能缺少盘中更新、实时资金、板块归因或最新 F10 信息。",
        "新闻与社交内容存在时效和噪声，需要结合公告、交易所文件和公司披露核验。",
    ]


def _clean(value: str | None) -> str:
    return sanitize_report_text(_redact_local_paths(value))


def _redact_local_paths(value: str | None) -> str:
    text = "" if value is None else str(value)
    return LOCAL_PATH_PATTERN.sub("<local-path>", text)
