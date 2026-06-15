"""Codex-native ZSXQ intelligence report generation."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .evidence import sanitize_report_text

GROUP_ID = "15555851111822"
GROUP_NAME = "小牛研报纪要"
VALID_SESSIONS = ("premarket", "evening")

PREMARKET_TAGS = {"#逻辑精选#", "#脱水研报#", "#财联社#"}
EVENING_TAGS = {"#纪要文档#", "#外资研报#", "#文字观点#", "#财联社#", "#小牛云#"}
LOW_CONFIDENCE_TAGS = {"#来源未知#", "#未知来源谨慎风险#", "#未知来源，注意风险#", "#市场段子#", "#出处未知#"}
DISPLAY_TAG_ORDER = (
    "#逻辑精选#",
    "#脱水研报#",
    "#外资研报#",
    "#财联社#",
    "#文字观点#",
    "#纪要文档#",
    "#小牛云#",
    "#券商研报#",
    "#交易台#",
    "#音频#",
    "#笔记链接#",
    "#市场段子#",
    "#出处未知#",
    "#来源未知#",
    "#来源未知谨慎风险#",
    "#未知来源谨慎风险#",
    "#未知来源，注意风险#",
)
DISPLAY_TAGS = set(DISPLAY_TAG_ORDER)
PRIORITY_TAGS = {"#逻辑精选#", "#脱水研报#", "#外资研报#", "#财联社#"}
ARCHIVE_TAGS = {"#纪要文档#", "#小牛云#", "#券商研报#", "#音频#", "#笔记链接#"}
THEME_CLUSTERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AI 硬件", ("AI", "算力", "服务器", "数据中心", "光模块", "CPO", "PCB", "液冷", "电源")),
    ("半导体链", ("半导体", "芯片", "设备", "材料", "先进封装", "存储", "国产替代")),
    ("电力与资源", ("电力", "铜", "有色", "煤炭", "化工", "材料")),
    ("机器人与智能制造", ("机器人", "机械", "智能驾驶", "汽车")),
    ("其他主题", ("医药", "消费", "旅游", "金融", "传媒")),
)
AMBIGUOUS_SYMBOL_TERMS = {"机器人"}
SYMBOL_STOPWORDS = {
    "AI",
    "A股",
    "CPO",
    "PCB",
    "CSP",
    "GPU",
    "CPU",
    "8000",
    "人工智能",
    "算力",
    "服务器",
    "数据中心",
    "光模块",
    "液冷",
    "电源",
    "半导体",
    "芯片",
    "设备",
    "材料",
    "先进封装",
    "存储",
    "国产替代",
    "电力",
    "铜",
    "有色",
    "煤炭",
    "化工",
    "机械",
    "智能驾驶",
    "汽车",
    "医药",
    "消费",
    "旅游",
    "金融",
    "传媒",
}


@dataclass(frozen=True)
class ZSXQIntelligenceItem:
    source_group: str = GROUP_NAME
    group_id: str = GROUP_ID
    topic_id: str = ""
    title: str = "未命名知识星球线索"
    summary: str = "未提供摘要。"
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
class ZSXQIntelligenceContext:
    source_group: str = GROUP_NAME
    group_id: str = GROUP_ID
    items: list[ZSXQIntelligenceItem] = field(default_factory=list)
    source_policy: dict[str, str] = field(default_factory=dict)
    collection_coverage: dict[str, str] = field(default_factory=dict)
    data_limitations: list[str] = field(default_factory=list)


def load_zsxq_intelligence_json(path: str | Path) -> ZSXQIntelligenceContext:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("context-json must contain a JSON object")
    return load_zsxq_intelligence_context(data)


def load_zsxq_intelligence_context(data: dict[str, Any] | None) -> ZSXQIntelligenceContext:
    raw = data or {}
    items = [_coerce_item(item) for item in raw.get("intelligence_items", []) if isinstance(item, dict)]
    source_group = _string(raw.get("source_group")) or (items[0].source_group if items else GROUP_NAME)
    group_id = _string(raw.get("group_id")) or (items[0].group_id if items else GROUP_ID)
    return ZSXQIntelligenceContext(
        source_group=source_group,
        group_id=group_id,
        items=items,
        source_policy=_coerce_string_dict(raw.get("source_policy")),
        collection_coverage=_coerce_string_dict(raw.get("collection_coverage")),
        data_limitations=_coerce_string_list(raw.get("data_limitations")),
    )


def classify_item(item: ZSXQIntelligenceItem, session: str) -> str:
    tags = set(_display_tags(item.tags))
    if tags & LOW_CONFIDENCE_TAGS or item.source_policy == "rumor" or item.source_risk == "high":
        return "low_confidence"
    if session == "premarket" and tags & PREMARKET_TAGS:
        return "must_track"
    if session == "evening" and tags & EVENING_TAGS:
        return "must_track"
    if item.attachments:
        return "archive_only"
    return "ignored"


def select_session_items(items: list[ZSXQIntelligenceItem], session: str) -> list[ZSXQIntelligenceItem]:
    # Session classification controls priority only; every collected item must
    # stay visible in overview summaries and the compact full index.
    return list(items)


def render_zsxq_markdown(
    context: ZSXQIntelligenceContext,
    session: str,
    report_date: str,
    appendix_name: str | None = None,
) -> str:
    selected = select_session_items(context.items, session)
    title = "小牛研报纪要情报早报" if session == "premarket" else "小牛研报纪要情报晚报"
    priority_pool = _priority_pool(selected, session)
    priority_items = _ranked_items(priority_pool, session)
    low_confidence = _ranked_items([item for item in selected if classify_item(item, session) == "low_confidence"], session)
    foreign_items = _ranked_items([item for item in selected if "#外资研报#" in _display_tags(item.tags)], session)
    appendix_ref = appendix_name or f"{report_date}_{session}_xiaoniu_appendix.md"

    lines = [
        f"# {title}",
        "",
        f"日期：{_clean(report_date)}",
        f"采集场景：{_clean(session)}",
        f"星球：{_clean(context.source_group)}（{_clean(context.group_id)}）",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "> 知识星球内容默认是情报线索源，不是直接事实源；进入研究结论前必须二次核验。",
        "",
        "## 情报扫描总览",
        "",
    ]
    lines.extend(_format_scan_overview(context, selected, session))
    lines.append(f"- 完整索引和附件清单见附录：{_clean(appendix_ref)}")
    lines.extend(["", "## 主题簇摘要", ""])
    lines.extend(_format_theme_clusters(selected, session) or ["- 暂无可归纳主题簇。"])
    lines.extend(["", "## 今日/次日主线", ""])
    lines.extend(_format_items(priority_items, limit=12) or ["- 暂无匹配本场景的优先线索。"])
    lines.extend(["", "## 重点行业", ""])
    lines.extend(_format_counter(_collect_terms(selected, "sectors"), limit=10) or ["- 暂无匹配行业。"])
    lines.extend(["", "## 重点个股", ""])
    lines.extend(_format_counter(_collect_terms(selected, "symbols"), limit=10) or ["- 暂无匹配标的。"])
    ambiguous_terms = _collect_ambiguous_symbols(selected)
    if ambiguous_terms:
        lines.extend(["", "## 歧义标的/行业词", ""])
    lines.extend(_format_counter(ambiguous_terms, limit=12))
    lines.extend(["", "## 外资观点", ""])
    lines.extend(_format_items(foreign_items, limit=5) or ["- 暂无本场景外资观点。"])
    lines.extend(["", "## 待核验线索", ""])
    lines.extend(_format_verification_items(priority_items, limit=6) or ["- 暂无待核验线索。"])
    lines.extend(["", "## 低置信舆情", ""])
    lines.extend(_format_items(low_confidence, limit=5) or ["- 暂无低置信舆情。"])
    lines.extend(["", "## 数据缺口", ""])
    lines.extend(_format_limitations(context, selected))
    lines.append("- 主报告仅展示聚合摘要和优先线索；全量覆盖证据在附录中保留。")
    lines.append("")
    return "\n".join(lines)


def render_zsxq_appendix_markdown(context: ZSXQIntelligenceContext, session: str, report_date: str) -> str:
    selected = select_session_items(context.items, session)
    title = "小牛研报纪要情报早报附录" if session == "premarket" else "小牛研报纪要情报晚报附录"
    window_start, window_end = _collection_window(context, selected)
    lines = [
        f"# {title}",
        "",
        f"日期：{_clean(report_date)}",
        f"采集场景：{_clean(session)}",
        f"采集窗口：{_clean(window_start)} 至 {_clean(window_end)}",
        f"星球：{_clean(context.source_group)}（{_clean(context.group_id)}）",
        "",
        "> 附录用于个人研究追溯，只保存结构化元数据、短摘要和附件文件名；不转载付费全文。",
        "",
        "## 研报纪要附件清单",
        "",
    ]
    lines.extend(_format_attachments(selected) or ["- 暂无附件元数据。"])
    lines.extend(["", "## 全量条目索引", ""])
    lines.extend(_format_full_index(selected, session) or ["- 暂无采集条目。"])
    lines.extend(["", "## 可注入 Context 摘要", ""])
    lines.extend(_format_context_summary(selected, limit=None) or ["- 暂无可注入条目。"])
    lines.extend(["", "## 数据缺口", ""])
    lines.extend(_format_limitations(context, selected))
    lines.append("")
    return "\n".join(lines)


def _format_scan_overview(
    context: ZSXQIntelligenceContext,
    items: list[ZSXQIntelligenceItem],
    session: str,
) -> list[str]:
    must_track = sum(1 for item in items if classify_item(item, session) == "must_track")
    archive_only = sum(1 for item in items if classify_item(item, session) == "archive_only")
    low_confidence = sum(1 for item in items if classify_item(item, session) == "low_confidence")
    attachment_topics = sum(1 for item in items if item.attachments)
    window_start, window_end = _collection_window(context, items)
    lines = [
        f"- 采集窗口：{_clean(window_start)} 至 {_clean(window_end)}",
        (
            f"- 覆盖主题：{len(items)} 条；重点跟踪：{must_track} 条；"
            f"归档/附件：{archive_only} 条；低置信：{low_confidence} 条；附件主题：{attachment_topics} 条"
        ),
    ]
    source = context.collection_coverage.get("source") or context.source_policy.get("source")
    if source:
        lines.append(f"- 采集来源：{_clean(source)}")
    lines.append("- 标签分布：" + (_format_inline_counter(_collect_tag_counts(items), limit=12) or "暂无标签"))
    lines.append("- Top 行业：" + (_format_inline_counter(_collect_terms(items, "sectors"), limit=8) or "暂无匹配行业"))
    lines.append("- Top 标的：" + (_format_inline_counter(_collect_terms(items, "symbols"), limit=8) or "暂无匹配标的"))
    return lines


def _format_direction_summary(items: list[ZSXQIntelligenceItem], limit: int = 8) -> list[str]:
    grouped: dict[str, list[ZSXQIntelligenceItem]] = {}
    for item in items:
        for sector in item.matched_sectors:
            grouped.setdefault(sector, []).append(item)
    lines: list[str] = []
    for sector, sector_items in sorted(grouped.items(), key=lambda entry: (-len(entry[1]), entry[0]))[:limit]:
        examples = "、".join(_index_label(item) for item in sector_items[:3])
        lines.append(f"- {_clean(sector)}：{len(sector_items)} 条线索；代表主题：{_clean(examples)}")
    symbol_counts = _collect_terms(items, "symbols")
    if symbol_counts:
        lines.append("- 高频标的：" + _format_inline_counter(symbol_counts, limit=8))
    return lines


def _format_theme_clusters(items: list[ZSXQIntelligenceItem], session: str) -> list[str]:
    clusters = _theme_clusters(items, session)
    lines: list[str] = []
    for name, cluster_items in clusters:
        ranked = _ranked_items(cluster_items, session)
        examples = "、".join(_index_label(item) for item in ranked[:3]) or "暂无代表主题"
        symbols = _format_inline_counter(_collect_terms(cluster_items, "symbols"), limit=5) or "暂无明确标的"
        pending = sum(1 for item in cluster_items if item.verification_status != "verified")
        lines.append(f"- {_clean(name)}：{len(cluster_items)} 条线索；待核验 {pending} 条")
        lines.append(f"  代表主题：{_clean(examples)}")
        lines.append(f"  代表标的：{symbols}")
    return lines


def _theme_clusters(
    items: list[ZSXQIntelligenceItem],
    session: str,
) -> list[tuple[str, list[ZSXQIntelligenceItem]]]:
    clusters: list[tuple[str, list[ZSXQIntelligenceItem]]] = []
    matched_topic_ids: set[str] = set()
    for name, keywords in THEME_CLUSTERS[:-1]:
        cluster_items = [item for item in items if _matches_theme(item, keywords)]
        if not cluster_items:
            continue
        matched_topic_ids.update(item.topic_id for item in cluster_items if item.topic_id)
        clusters.append((name, _ranked_items(cluster_items, session)))

    other_keywords = THEME_CLUSTERS[-1][1]
    other_items = [
        item
        for item in items
        if (item.topic_id not in matched_topic_ids and _matches_theme(item, other_keywords))
    ]
    fallback_items = [
        item
        for item in items
        if item.topic_id not in matched_topic_ids and item not in other_items
    ]
    other_items.extend(fallback_items)
    if other_items:
        clusters.append((THEME_CLUSTERS[-1][0], _ranked_items(other_items, session)))
    return clusters


def _matches_theme(item: ZSXQIntelligenceItem, keywords: tuple[str, ...]) -> bool:
    values = [*item.matched_sectors, *item.matched_symbols]
    if not values:
        values = [item.title, item.summary]
    haystack = " ".join(values)
    return any(keyword in haystack for keyword in keywords)


def _format_full_index(items: list[ZSXQIntelligenceItem], session: str) -> list[str]:
    lines: list[str] = []
    for item in items:
        tags = "、".join(item.tags) or "N/A"
        bucket = classify_item(item, session)
        published_at = item.published_at or "N/A"
        lines.append(
            f"- {_clean(published_at)}；topic_id={_clean(item.topic_id or 'N/A')}；"
            f"bucket={_clean(bucket)}；标签={_clean(tags)}；标题={_clean(item.title)}"
        )
    return lines


def _collection_window(
    context: ZSXQIntelligenceContext,
    items: list[ZSXQIntelligenceItem],
) -> tuple[str, str]:
    coverage = context.collection_coverage
    source_policy = context.source_policy
    start = (
        coverage.get("window_start")
        or coverage.get("collection_window_start")
        or source_policy.get("window_start")
        or source_policy.get("collection_window_start")
    )
    end = (
        coverage.get("window_end")
        or coverage.get("collection_window_end")
        or source_policy.get("window_end")
        or source_policy.get("collection_window_end")
    )
    published_values = sorted(item.published_at for item in items if item.published_at)
    if not start and published_values:
        start = published_values[0]
    if not end and published_values:
        end = published_values[-1]
    return start or "未提供", end or "未提供"


def _collect_tag_counts(items: list[ZSXQIntelligenceItem]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        tags = _display_tags(item.tags)
        if tags:
            counts.update(tags)
        else:
            counts.update(["未打标签"])
    return dict(sorted(counts.items(), key=lambda entry: (-entry[1], entry[0])))


def _format_inline_counter(values: dict[str, int], limit: int) -> str:
    selected = list(values.items())[:limit]
    parts = [f"{_clean(key)}：{count} 条" for key, count in selected]
    remaining = len(values) - len(selected)
    if remaining > 0:
        parts.append(f"另有 {remaining} 项")
    return "、".join(parts)


def _index_label(item: ZSXQIntelligenceItem) -> str:
    return f"{item.title}（{item.topic_id or 'N/A'}）"


def _append_truncation(lines: list[str], total: int, shown: int) -> None:
    remaining = total - shown
    if remaining > 0:
        lines.append(f"- 另有 {remaining} 条已收入附录。")


def _limited_items(items: list[ZSXQIntelligenceItem], limit: int | None) -> list[ZSXQIntelligenceItem]:
    if limit is None:
        return items
    return items[:limit]


def _shown_count(items: list[ZSXQIntelligenceItem], limit: int | None) -> int:
    if limit is None:
        return len(items)
    return min(len(items), limit)


def generate_zsxq_report(
    session: str,
    report_date: str,
    context_json: str | Path,
    output_dir: str | Path,
) -> Path:
    context = load_zsxq_intelligence_json(context_json)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{report_date}_{session}_xiaoniu.md"
    appendix_path = out_dir / f"{report_date}_{session}_xiaoniu_appendix.md"
    content = render_zsxq_markdown(
        context,
        session=session,
        report_date=report_date,
        appendix_name=appendix_path.name,
    )
    path.write_text(content, encoding="utf-8")
    appendix_path.write_text(render_zsxq_appendix_markdown(context, session=session, report_date=report_date), encoding="utf-8")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Codex-native ZSXQ intelligence Markdown reports.")
    parser.add_argument("--session", required=True, choices=VALID_SESSIONS, help="Collection session.")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"), help="Report date, such as 20260610.")
    parser.add_argument("--context-json", required=True, help="Context JSON prepared by Codex from zsxq-cli.")
    parser.add_argument(
        "--output-dir",
        default=os.getenv("CODEX_ZSXQ_INTELLIGENCE_DIR", "reports/zsxq_intelligence"),
        help="Directory for generated Markdown reports.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        path = generate_zsxq_report(
            session=args.session,
            report_date=args.date,
            context_json=args.context_json,
            output_dir=args.output_dir,
        )
    except Exception as exc:
        print(f"Codex-native ZSXQ intelligence generation failed: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


def _coerce_item(raw: dict[str, Any]) -> ZSXQIntelligenceItem:
    return ZSXQIntelligenceItem(
        source_group=_string(raw.get("source_group")) or GROUP_NAME,
        group_id=_string(raw.get("group_id")) or GROUP_ID,
        topic_id=_string(raw.get("topic_id")),
        title=_string(raw.get("title")) or "未命名知识星球线索",
        summary=_trim(_string(raw.get("summary")) or "未提供摘要。"),
        tags=_coerce_string_list(raw.get("tags")),
        published_at=_string(raw.get("published_at")),
        attachments=_coerce_string_list(raw.get("attachments")),
        matched_symbols=_coerce_string_list(raw.get("matched_symbols")),
        matched_sectors=_coerce_string_list(raw.get("matched_sectors")),
        verification_status=_string(raw.get("verification_status")) or "needs_verification",
        source_policy=_string(raw.get("source_policy")) or "needs_verification",
        source_risk=_string(raw.get("source_risk")) or "medium",
        suggested_section=_string(raw.get("suggested_section")) or "market_rumor",
        readers=_optional_int(raw.get("readers")),
        likes=_optional_int(raw.get("likes")),
    )


def _format_items(items: list[ZSXQIntelligenceItem], limit: int | None = None) -> list[str]:
    lines: list[str] = []
    shown = _shown_count(items, limit)
    for item in _limited_items(items, limit):
        meta = _item_meta(item)
        lines.append(f"- {_clean(item.title)}（topic_id={_clean(item.topic_id or 'N/A')}）")
        lines.append(f"  摘要：{_clean(_display_summary(item.summary))}")
        lines.append(f"  元数据：{meta}")
    _append_truncation(lines, len(items), shown)
    return lines


def _format_verification_items(items: list[ZSXQIntelligenceItem], limit: int | None = None) -> list[str]:
    pending = [item for item in items if item.verification_status != "verified"]
    lines: list[str] = []
    shown = _shown_count(pending, limit)
    for item in _limited_items(pending, limit):
        targets = []
        symbols = _display_symbols(item.matched_symbols)
        if symbols:
            targets.append("标的：" + "、".join(symbols))
        if item.matched_sectors:
            targets.append("行业：" + "、".join(item.matched_sectors))
        lines.append(
            f"- {_clean(item.title)}：{_clean('；'.join(targets) or '未识别标的/行业')}；核验状态={_clean(item.verification_status)}"
        )
    _append_truncation(lines, len(pending), shown)
    return lines


def _format_attachments(items: list[ZSXQIntelligenceItem]) -> list[str]:
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        for name in item.attachments:
            key = (item.topic_id, name)
            if key in seen:
                continue
            seen.add(key)
            tags = "、".join(_display_tags(item.tags)) or "N/A"
            lines.append(
                f"- {_clean(_attachment_label(name))}（topic_id={_clean(item.topic_id or 'N/A')}；标签={_clean(tags)}）"
            )
    return lines


def _format_context_summary(items: list[ZSXQIntelligenceItem], limit: int | None = None) -> list[str]:
    lines: list[str] = []
    shown = _shown_count(items, limit)
    for item in _limited_items(items, limit):
        section = item.suggested_section or "market_rumor"
        lines.append(
            f"- topic_id={_clean(item.topic_id or 'N/A')}；section={_clean(section)}；policy={_clean(item.source_policy)}；risk={_clean(item.source_risk)}"
        )
    _append_truncation(lines, len(items), shown)
    return lines


def _collect_terms(items: list[ZSXQIntelligenceItem], kind: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        values = item.matched_sectors if kind == "sectors" else _display_symbols(item.matched_symbols)
        for value in values:
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda entry: (-entry[1], entry[0])))


def _format_counter(values: dict[str, int], limit: int | None = None) -> list[str]:
    selected = list(values.items()) if limit is None else list(values.items())[:limit]
    lines = [f"- {_clean(key)}：{count} 条线索" for key, count in selected]
    remaining = len(values) - len(selected)
    if remaining > 0:
        lines.append(f"- 另有 {remaining} 项已收入情报扫描总览。")
    return lines


def _format_limitations(context: ZSXQIntelligenceContext, items: list[ZSXQIntelligenceItem]) -> list[str]:
    limitations = context.data_limitations or ["未直接下载或全文解析 PDF 附件。", "星球观点未经二次核验，不进入已验证事实。"]
    lines: list[str] = []
    for item in limitations:
        if "主题标签统计" in item:
            summary = _format_inline_counter(_collect_tag_counts(items), limit=12) or "暂无标签"
            lines.append(f"- 本次主题标签统计（白名单）：{summary}")
            continue
        lines.append(f"- {_clean(_trim(item, limit=180))}")
    return lines


def _display_summary(summary: str) -> str:
    text = summary
    for marker in ("；附件：", "附件："):
        if marker in text:
            text = text.split(marker, 1)[0]
            break
    return _trim(text, limit=100)


def _priority_pool(items: list[ZSXQIntelligenceItem], session: str) -> list[ZSXQIntelligenceItem]:
    non_low_confidence = [item for item in items if classify_item(item, session) != "low_confidence"]
    return non_low_confidence or list(items)


def _ranked_items(items: list[ZSXQIntelligenceItem], session: str) -> list[ZSXQIntelligenceItem]:
    seen_topic_ids: set[str] = set()
    scored: list[tuple[int, str, int, ZSXQIntelligenceItem]] = []
    for index, item in enumerate(items):
        is_duplicate = bool(item.topic_id and item.topic_id in seen_topic_ids)
        if item.topic_id:
            seen_topic_ids.add(item.topic_id)
        scored.append((_priority_score(item, session, is_duplicate), item.published_at, -index, item))
    scored.sort(key=lambda entry: (entry[0], entry[1], entry[2]), reverse=True)
    return [item for _, _, _, item in scored]


def _priority_score(item: ZSXQIntelligenceItem, session: str, is_duplicate: bool = False) -> int:
    tags = set(_display_tags(item.tags))
    bucket = classify_item(item, session)
    score = 0
    if bucket == "must_track":
        score += 30
    elif bucket == "archive_only":
        score += 8
    elif bucket == "low_confidence":
        score -= 30
    if tags & PRIORITY_TAGS:
        score += 18
    if tags & ARCHIVE_TAGS:
        score += 6
    if not tags:
        score -= 5
    if item.attachments:
        score += 8
    if _matches_any_primary_theme(item):
        score += 8
    if item.readers is not None:
        score += min(max(item.readers, 0) // 100, 10)
    if item.likes is not None:
        score += min(max(item.likes, 0), 6)
    if not item.summary or item.summary == "未提供摘要。":
        score -= 4
    if is_duplicate:
        score -= 20
    return score


def _matches_any_primary_theme(item: ZSXQIntelligenceItem) -> bool:
    return any(_matches_theme(item, keywords) for _, keywords in THEME_CLUSTERS[:-1])


def _display_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    whitelisted: list[str] = []
    for tag in tags:
        if tag not in DISPLAY_TAGS or tag in seen:
            continue
        seen.add(tag)
        whitelisted.append(tag)
    return sorted(whitelisted, key=lambda tag: DISPLAY_TAG_ORDER.index(tag))


def _display_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for symbol in symbols:
        normalized = symbol.strip()
        if not normalized or normalized in seen or not _is_display_symbol(normalized):
            continue
        seen.add(normalized)
        values.append(normalized)
    return values


def _is_display_symbol(value: str) -> bool:
    if value in AMBIGUOUS_SYMBOL_TERMS or value in SYMBOL_STOPWORDS:
        return False
    if value.isdigit():
        return False
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9._:-]{0,7}", value):
        return False
    if re.fullmatch(r"\d+[A-Za-z._:-]*", value):
        return False
    return True


def _collect_ambiguous_symbols(items: list[ZSXQIntelligenceItem]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        for symbol in item.matched_symbols:
            normalized = symbol.strip()
            if normalized in AMBIGUOUS_SYMBOL_TERMS:
                counts.update([normalized])
    return dict(sorted(counts.items(), key=lambda entry: (-entry[1], entry[0])))


def _attachment_label(name: str) -> str:
    if re.match(r"https?://", name, flags=re.IGNORECASE):
        return "附件链接已隐藏"
    return name


def _item_meta(item: ZSXQIntelligenceItem) -> str:
    tags = _display_tags(item.tags)
    parts = [
        f"标签={','.join(tags) or 'N/A'}",
        f"发布时间={item.published_at or 'N/A'}",
        f"核验={item.verification_status}",
        f"风险={item.source_risk}",
    ]
    if item.readers is not None:
        parts.append(f"阅读={item.readers}")
    if item.likes is not None:
        parts.append(f"点赞={item.likes}")
    if item.attachments:
        parts.append(f"附件={len(item.attachments)}个")
    return _clean("；".join(parts))


def _trim(value: str, limit: int = 120) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _coerce_string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _clean(value: str | None) -> str:
    return sanitize_report_text(value)


if __name__ == "__main__":
    raise SystemExit(main())
