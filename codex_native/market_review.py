"""CLI entrypoint for Codex-native A-share market review reports."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .context import (
    CodexResearchContext,
    CoverageItem,
    DataQualityItem,
    IntelligenceContextItem,
    RiskItem,
    StageStatusItem,
    ToolAttempt,
    load_context_json,
    parse_context,
)
from .evidence import EvidenceItem, EvidenceKind, sanitize_report_text
from .indicators import calculate_indicators
from .models import DailyBar, TechnicalIndicators
from .research import VALID_PHASES, resolve_phase
from .tdx import find_tdx_index_day_file, normalize_index_symbol, parse_tdx_day_file


@dataclass(frozen=True)
class IndexSpec:
    symbol: str
    name: str


@dataclass(frozen=True)
class IndexSnapshot:
    symbol: str
    name: str
    bars: list[DailyBar]
    indicators: TechnicalIndicators
    data_sources: dict[str, str] = field(default_factory=dict)
    data_limitations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarketReviewSnapshot:
    phase: str
    indices: list[IndexSnapshot]
    coverage: list[CoverageItem] = field(default_factory=list)
    breadth: dict[str, str] = field(default_factory=dict)
    sectors: list[str] = field(default_factory=list)
    funds: dict[str, Any] = field(default_factory=dict)
    evidence: list[EvidenceItem] = field(default_factory=list)
    intelligence_items: list[IntelligenceContextItem] = field(default_factory=list)
    risk_items: list[RiskItem] = field(default_factory=list)
    tool_attempts: list[ToolAttempt] = field(default_factory=list)
    stage_status: list[StageStatusItem] = field(default_factory=list)
    data_quality: list[DataQualityItem] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    data_limitations: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


DEFAULT_INDEXES: tuple[IndexSpec, ...] = (
    IndexSpec("sh000001", "上证指数"),
    IndexSpec("sz399001", "深证成指"),
    IndexSpec("sz399006", "创业板指"),
    IndexSpec("sh000300", "沪深300"),
    IndexSpec("sh000905", "中证500"),
    IndexSpec("sh000852", "中证1000"),
    IndexSpec("sh000688", "科创50"),
)

SECTION_TITLES = {
    EvidenceKind.VERIFIED_FACT: "已验证事实",
    EvidenceKind.MARKET_RUMOR: "市场传闻",
    EvidenceKind.LOGICAL_INFERENCE: "逻辑推演",
    EvidenceKind.TRADING_HYPOTHESIS: "交易假设",
}

REQUIRED_MARKET_REVIEW_BLOCKS: tuple[tuple[str, str], ...] = (
    ("index_quotes", "指数行情"),
    ("breadth", "市场宽度"),
    ("turnover", "成交额"),
    ("real_time_funds", "实时资金"),
    ("sector_strength", "板块强度"),
    ("news_sentiment", "新闻/舆情"),
)

STRICT_FAILURE_STATUSES = {"missing", "fetch_failed", "not_supported"}


def load_market_review_snapshot(
    tdx_dir: str | Path,
    phase: str = "postmarket",
    context: dict[str, Any] | CodexResearchContext | None = None,
    strict_context: bool = False,
) -> MarketReviewSnapshot:
    selected_phase = resolve_phase(phase)
    parsed_context = context if isinstance(context, CodexResearchContext) else parse_context(context or {})
    indices: list[IndexSnapshot] = []
    missing: list[str] = []

    for spec in DEFAULT_INDEXES:
        try:
            indices.append(_load_index_snapshot(tdx_dir, spec))
        except FileNotFoundError as exc:
            missing.append(f"{spec.symbol} {spec.name}: {exc}")

    if missing:
        raise RuntimeError("missing local TDX index day files: " + "；".join(missing))

    coverage = _build_market_review_coverage(parsed_context, indices)
    strict_errors = _strict_context_errors(coverage)
    if strict_context and strict_errors:
        raise RuntimeError("strict context missing required market review blocks: " + "；".join(strict_errors))

    return MarketReviewSnapshot(
        phase=selected_phase,
        indices=indices,
        coverage=coverage,
        breadth=parsed_context.breadth,
        sectors=parsed_context.sectors,
        funds=parsed_context.funds,
        evidence=parsed_context.evidence,
        intelligence_items=parsed_context.intelligence_items,
        risk_items=parsed_context.risk_items,
        tool_attempts=parsed_context.tool_attempts,
        stage_status=parsed_context.stage_status,
        data_quality=parsed_context.data_quality,
        observations=parsed_context.observations,
        data_limitations=_build_market_review_limitations(parsed_context, coverage),
    )


def generate_market_review(
    phase: str,
    tdx_dir: str | Path,
    output_dir: str | Path,
    context_json: str | Path | None = None,
    strict_context: bool = False,
) -> Path:
    context = load_context_json(context_json) if context_json else None
    snapshot = load_market_review_snapshot(
        tdx_dir=tdx_dir,
        phase=phase,
        context=context,
        strict_context=strict_context,
    )
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{timestamp}_{snapshot.phase}_cn_market_review.md"
    appendix_path = (
        out_dir / f"{timestamp}_{snapshot.phase}_cn_market_review_appendix.md"
        if snapshot.intelligence_items
        else None
    )
    content = render_market_review_markdown(
        snapshot,
        appendix_name=appendix_path.name if appendix_path else None,
    )
    path.write_text(content, encoding="utf-8")
    if appendix_path:
        appendix_path.write_text(render_market_review_appendix_markdown(snapshot), encoding="utf-8")
    return path


def render_market_review_markdown(snapshot: MarketReviewSnapshot, appendix_name: str | None = None) -> str:
    degraded = _is_degraded(snapshot.coverage)
    lines = [
        "# " + _market_review_title(snapshot.phase, degraded=degraded),
        "",
        f"阶段：{_clean(snapshot.phase)}",
        f"生成时间：{_clean(snapshot.generated_at)}",
        "",
        "> 本报告仅用于研究记录，不构成交易建议。",
    ]
    if degraded:
        lines.extend(["", f"> 数据覆盖：降级报告，未完全补齐：{_clean(_format_degraded_blocks(snapshot.coverage))}。"])
    lines.extend(["", "## 报告质量卡", ""])
    lines.extend(_render_quality_card(snapshot, appendix_name=appendix_name))
    lines.extend(
        [
            "",
            "## 核心盘面摘要",
            "",
            _build_summary(snapshot),
            "",
            "## 主要指数表现",
            "",
            "| 指数 | 代码 | 最新交易日 | 收盘 | 1日涨跌幅 | MA5 | MA10 | MA20 | 5日量比 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    for item in snapshot.indices:
        indicator = item.indicators
        lines.append(
            "| "
            + " | ".join(
                [
                    _clean(item.name),
                    _clean(item.symbol),
                    _clean(indicator.latest_trade_date),
                    f"{indicator.last_close:.2f}",
                    _format_optional_pct(indicator.change_pct_1d),
                    _format_optional_number(indicator.ma5),
                    _format_optional_number(indicator.ma10),
                    _format_optional_number(indicator.ma20),
                    _format_optional_number(indicator.volume_ratio_5d),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 技术与量能",
            "",
        ]
    )
    lines.extend(_format_bullets(_build_technical_points(snapshot)))
    lines.extend(["", "## 板块与题材", ""])
    lines.extend(_format_bullets(_build_sector_points(snapshot)))
    lines.extend(["", "## 阶段执行状态", ""])
    lines.extend(_render_stage_status(snapshot.stage_status))
    lines.extend(["", "## 数据块对账", ""])
    lines.extend(_render_coverage(snapshot.coverage))
    lines.extend(["", "## 数据质量", ""])
    lines.extend(_render_data_quality(snapshot.data_quality))
    if snapshot.intelligence_items:
        lines.extend(["", "## 私域情报摘要", ""])
        lines.extend(_render_private_intelligence_summary(snapshot.intelligence_items, appendix_name=appendix_name))

    grouped = _group_evidence([item for item in snapshot.evidence if not _is_private_intelligence_evidence(item)])
    for kind in (
        EvidenceKind.VERIFIED_FACT,
        EvidenceKind.MARKET_RUMOR,
        EvidenceKind.LOGICAL_INFERENCE,
        EvidenceKind.TRADING_HYPOTHESIS,
    ):
        lines.extend(["", f"## {SECTION_TITLES[kind]}", ""])
        items = grouped.get(kind, [])
        if not items:
            lines.extend(["- 暂无可写入证据。"])
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

    lines.extend(["", "## 观察条件", ""])
    lines.extend(_format_bullets(snapshot.observations or _default_observations()))
    lines.extend(["", "## 风险提示", ""])
    lines.extend(_format_bullets(_format_risk_items(snapshot.risk_items) + _default_risks()))
    lines.extend(["", "## 数据缺口", ""])
    lines.extend(_format_bullets(snapshot.data_limitations or ["暂无已知数据缺口。"]))
    lines.append("")
    return "\n".join(lines)


def render_market_review_appendix_markdown(snapshot: MarketReviewSnapshot) -> str:
    lines = [
        "# " + _market_review_title(snapshot.phase, degraded=False) + "附录",
        "",
        f"阶段：{_clean(snapshot.phase)}",
        f"生成时间：{_clean(snapshot.generated_at)}",
        "",
        "> 附录用于个人研究追溯，只保存结构化元数据、短摘要和附件文件名；私域情报不作为已验证事实。",
        "",
        "## 私域情报索引",
        "",
    ]
    lines.extend(_render_private_intelligence_index(snapshot.intelligence_items))
    lines.extend(["", "## 私域情报短摘要", ""])
    lines.extend(_render_private_intelligence_notes(snapshot.intelligence_items))
    lines.extend(["", "## 附件清单", ""])
    lines.extend(_render_private_intelligence_attachments(snapshot.intelligence_items))
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Codex-native A-share market review Markdown reports.")
    parser.add_argument("--phase", default="postmarket", choices=VALID_PHASES, help="Report phase template.")
    parser.add_argument("--tdx-dir", default=os.getenv("TDX_LOCAL_DIR"), help="Local TongDaXin root directory.")
    parser.add_argument(
        "--output-dir",
        default=os.getenv("CODEX_MARKET_REVIEW_REPORT_DIR", "reports/codex_market_review"),
        help="Directory for generated Markdown reports.",
    )
    parser.add_argument(
        "--context-json",
        help="Optional JSON file prepared by Codex from MCP, skills, news, announcements, reports, and sentiment.",
    )
    parser.add_argument(
        "--strict-context",
        action="store_true",
        help="Fail when required market-review context blocks are missing or failed.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.tdx_dir:
        print("TDX local directory is required. Pass --tdx-dir or set TDX_LOCAL_DIR.", file=sys.stderr)
        return 2
    try:
        path = generate_market_review(
            phase=args.phase,
            tdx_dir=args.tdx_dir,
            output_dir=args.output_dir,
            context_json=args.context_json,
            strict_context=args.strict_context,
        )
    except Exception as exc:
        print(f"Codex-native market review generation failed: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


def _load_index_snapshot(tdx_dir: str | Path, spec: IndexSpec) -> IndexSnapshot:
    symbol = normalize_index_symbol(spec.symbol)
    day_path = find_tdx_index_day_file(tdx_dir, symbol)
    bars = parse_tdx_day_file(day_path)
    if not bars:
        raise RuntimeError(f"no local TDX daily bars found for {symbol}")
    indicators = calculate_indicators(bars)
    return IndexSnapshot(
        symbol=symbol,
        name=spec.name,
        bars=bars,
        indicators=indicators,
        data_sources={"history": f"tdx-local:{day_path}"},
        data_limitations=["本地通达信指数日线不包含实时涨跌家数、板块归因或资金拆分。"],
    )


def _build_market_review_coverage(
    context: CodexResearchContext,
    indices: list[IndexSnapshot],
) -> list[CoverageItem]:
    provided = {item.block: item for item in context.coverage}
    coverage: list[CoverageItem] = []
    for block, _label in REQUIRED_MARKET_REVIEW_BLOCKS:
        coverage.append(provided.get(block) or _infer_coverage_item(block, context, indices))
    for item in context.coverage:
        if item.block not in {block for block, _label in REQUIRED_MARKET_REVIEW_BLOCKS}:
            coverage.append(item)
    return coverage


def _infer_coverage_item(
    block: str,
    context: CodexResearchContext,
    indices: list[IndexSnapshot],
) -> CoverageItem:
    if block == "index_quotes":
        return CoverageItem(
            block=block,
            status="available" if indices else "missing",
            source="tdx-local",
            fields=[item.name for item in indices],
        )
    if block == "breadth":
        return CoverageItem(
            block=block,
            status="available" if context.breadth else "missing",
            source="context-json:breadth" if context.breadth else "",
            fields=list(context.breadth.keys()),
        )
    if block == "turnover":
        parts = _fund_parts(context.funds, "turnover")
        return CoverageItem(
            block=block,
            status="available" if parts else "missing",
            source="context-json:funds.turnover" if parts else "",
            fields=[part.split("=", 1)[0] for part in parts],
        )
    if block == "real_time_funds":
        parts = _fund_parts(context.funds, "flow")
        return CoverageItem(
            block=block,
            status="available" if parts else "missing",
            source="context-json:funds" if parts else "",
            fields=[part.split("=", 1)[0] for part in parts],
            missing_fields=[] if parts else ["主力资金", "北向/外资口径", "ETF/融资融券"],
        )
    if block == "sector_strength":
        return CoverageItem(
            block=block,
            status="available" if context.sectors else "missing",
            source="context-json:sectors" if context.sectors else "",
            fields=context.sectors,
        )
    if block == "news_sentiment":
        if not context.evidence:
            return CoverageItem(block=block, status="missing", missing_fields=["收评新闻", "政策/地缘消息", "社交情绪"])
        has_social = any(item.source_type in {"social", "sentiment"} for item in context.evidence)
        return CoverageItem(
            block=block,
            status="available" if has_social else "partial",
            source="context-json:evidence",
            fields=[item.source_type for item in context.evidence],
            missing_fields=[] if has_social else ["可量化社交情绪"],
        )
    return CoverageItem(block=block, status="missing")


def _strict_context_errors(coverage: list[CoverageItem]) -> list[str]:
    errors: list[str] = []
    for item in coverage:
        if item.block not in {block for block, _label in REQUIRED_MARKET_REVIEW_BLOCKS}:
            continue
        if item.status in STRICT_FAILURE_STATUSES:
            errors.append(f"{item.block}（{_coverage_label(item.block)}）={item.status}")
    return errors


def _build_market_review_limitations(
    context: CodexResearchContext,
    coverage: list[CoverageItem],
) -> list[str]:
    limitations: list[str] = []
    for item in context.data_limitations:
        _append_unique(limitations, item)
    for item in coverage:
        if item.status != "available":
            _append_unique(limitations, _format_coverage_limitation(item))
    for attempt in context.tool_attempts:
        if attempt.status != "available":
            _append_unique(limitations, _format_tool_attempt_limitation(attempt))
    for item in context.quality_limitations():
        _append_unique(limitations, item)
    return limitations


def _format_coverage_limitation(item: CoverageItem) -> str:
    label = _coverage_label(item.block)
    details = _coverage_details(item)
    if item.block == "real_time_funds":
        return f"实时资金未补齐：{details}成交额不是实时资金，不能用成交额替代主力资金、北向/外资、ETF/融资融券。"
    if item.status == "partial":
        return f"必查数据块 {label} 部分补齐：{details}"
    if item.status == "fetch_failed":
        return f"必查数据块 {label} 获取失败：{details}"
    if item.status == "not_supported":
        return f"必查数据块 {label} 当前不支持：{details}"
    return f"必查数据块 {label} 未采集：{details}"


def _coverage_details(item: CoverageItem) -> str:
    parts = []
    if item.source:
        parts.append(f"来源：{item.source}")
    if item.fields:
        parts.append("已补字段：" + "、".join(item.fields))
    if item.missing_fields:
        parts.append("缺失字段：" + "、".join(item.missing_fields))
    if item.notes:
        parts.append(f"说明：{item.notes}")
    return "；".join(parts) + ("；" if parts else "")


def _format_tool_attempt_limitation(item: ToolAttempt) -> str:
    parts = [f"工具 {item.tool} 状态 {item.status}"]
    if item.query:
        parts.append(f"查询：{item.query}")
    if item.error:
        parts.append(f"错误：{item.error}")
    if item.fallback:
        parts.append(f"替代：{item.fallback}")
    return "；".join(parts)


def _append_unique(values: list[str], item: str) -> None:
    if item and item not in values:
        values.append(item)


def _coverage_label(block: str) -> str:
    labels = dict(REQUIRED_MARKET_REVIEW_BLOCKS)
    return labels.get(block, block)


def _is_degraded(coverage: list[CoverageItem]) -> bool:
    return any(
        item.block in {block for block, _label in REQUIRED_MARKET_REVIEW_BLOCKS} and item.status != "available"
        for item in coverage
    )


def _format_degraded_blocks(coverage: list[CoverageItem]) -> str:
    degraded = [
        f"{_coverage_label(item.block)}={item.status}"
        for item in coverage
        if item.block in {block for block, _label in REQUIRED_MARKET_REVIEW_BLOCKS} and item.status != "available"
    ]
    return "、".join(degraded) if degraded else "无"


def _market_review_title(phase: str, degraded: bool) -> str:
    titles = {
        "premarket": "Codex Native A股盘前观察",
        "intraday": "Codex Native A股大盘盘中复盘",
        "postmarket": "Codex Native A股大盘盘后复盘",
    }
    title = titles.get(phase, "Codex Native A股大盘复盘")
    return title + ("（降级）" if degraded else "")


def _render_quality_card(snapshot: MarketReviewSnapshot, appendix_name: str | None) -> list[str]:
    score = _coverage_score(snapshot.coverage)
    status_counts = _coverage_status_counts(snapshot.coverage)
    private_status = (
        f"{len(snapshot.intelligence_items)} 条；完整索引见附录：{appendix_name or '未生成'}"
        if snapshot.intelligence_items
        else "0 条；未生成附录"
    )
    lines = [
        "| 项目 | 结果 |",
        "| --- | --- |",
        f"| 质量分 | {_clean(str(score))}/100（{_clean(_quality_grade(score))}） |",
        f"| 阶段口径 | {_clean(_phase_label(snapshot.phase))} |",
        f"| 覆盖状态 | {_clean(status_counts)} |",
        f"| 降级块 | {_clean(_format_degraded_blocks(snapshot.coverage))} |",
        f"| 私域情报 | {_clean(private_status)} |",
    ]
    return lines


def _coverage_score(coverage: list[CoverageItem]) -> int:
    if not coverage:
        return 0
    penalties = {
        "available": 0,
        "partial": 8,
        "stale": 10,
        "missing": 18,
        "fetch_failed": 18,
        "not_supported": 14,
    }
    score = 100
    required_blocks = {block for block, _label in REQUIRED_MARKET_REVIEW_BLOCKS}
    for item in coverage:
        if item.block not in required_blocks:
            continue
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


def _coverage_status_counts(coverage: list[CoverageItem]) -> str:
    if not coverage:
        return "无覆盖信息"
    counts: dict[str, int] = {}
    for item in coverage:
        counts[item.status] = counts.get(item.status, 0) + 1
    return "；".join(f"{status}={count}" for status, count in sorted(counts.items()))


def _phase_label(phase: str) -> str:
    labels = {
        "premarket": "盘前观察",
        "intraday": "盘中复盘",
        "postmarket": "盘后复盘",
    }
    return labels.get(phase, phase)


def _build_summary(snapshot: MarketReviewSnapshot) -> str:
    latest_dates = sorted({item.indicators.latest_trade_date for item in snapshot.indices})
    trade_date = latest_dates[-1] if latest_dates else "N/A"
    best = max(snapshot.indices, key=lambda item: item.indicators.change_pct_1d or -9999)
    weakest = min(snapshot.indices, key=lambda item: item.indicators.change_pct_1d or 9999)
    return (
        f"本地通达信共读取 {len(snapshot.indices)} 个 A 股核心指数，最新交易日为 {trade_date}。"
        f"当日相对较强指数为 {best.name}（{_format_optional_pct(best.indicators.change_pct_1d)}），"
        f"相对较弱指数为 {weakest.name}（{_format_optional_pct(weakest.indicators.change_pct_1d)}）。"
    )


def _build_technical_points(snapshot: MarketReviewSnapshot) -> list[str]:
    points: list[str] = []
    for item in snapshot.indices:
        indicator = item.indicators
        ma_state = "N/A"
        if indicator.ma5 is not None:
            ma_state = "收盘高于 MA5" if indicator.last_close >= indicator.ma5 else "收盘低于 MA5"
        points.append(
            f"{item.name}：收盘 {indicator.last_close:.2f}，{ma_state}，5 日量比 {_format_optional_number(indicator.volume_ratio_5d)}。"
        )
    return points


def _build_sector_points(snapshot: MarketReviewSnapshot) -> list[str]:
    points: list[str] = []
    if snapshot.sectors:
        points.append("Codex 补充板块/题材：" + "、".join(_clean(item) for item in snapshot.sectors))
    if snapshot.breadth:
        points.append("市场宽度：" + "；".join(f"{_clean(key)}={_clean(value)}" for key, value in snapshot.breadth.items()))
    points.extend(_format_fund_points(snapshot.funds, snapshot.coverage))
    if not points:
        points.append("暂无 Codex MCP / skills 补充的板块、市场宽度或资金数据。")
    return points


def _format_fund_points(funds: dict[str, Any], coverage: list[CoverageItem]) -> list[str]:
    points: list[str] = []
    turnover = _fund_parts(funds, "turnover")
    flow = _fund_parts(funds, "flow")
    if turnover:
        points.append("成交额：" + "；".join(_clean(item) for item in turnover))
    if flow:
        points.append("资金流：" + "；".join(_clean(item) for item in flow))
    elif _coverage_status(coverage, "real_time_funds") != "available":
        points.append("资金流：实时资金未补齐；成交额不是实时资金。")
    return points


def _fund_parts(funds: dict[str, Any], section: str) -> list[str]:
    parts: list[str] = []
    for key, value in funds.items():
        category = _fund_category(key, value)
        if category != section:
            continue
        parts.extend(_format_fund_value(key, value))
    return parts


def _fund_category(key: str, value: Any) -> str:
    key_text = str(key)
    nested_keys = " ".join(str(item) for item in value.keys()) if isinstance(value, dict) else ""
    text = f"{key_text} {nested_keys}"
    if key_text == "turnover" or "成交额" in text or "turnover" in text:
        return "turnover"
    if key_text in {"main_flow", "northbound", "margin_financing", "etf_flow"}:
        return "flow"
    if any(marker in text for marker in ("主力", "北向", "外资", "融资", "融券", "ETF", "资金流")):
        return "flow"
    return "flow"


def _format_fund_value(key: str, value: Any) -> list[str]:
    if isinstance(value, dict):
        return [f"{item_key}={item_value}" for item_key, item_value in value.items()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [f"{key}={value}"]


def _coverage_status(coverage: list[CoverageItem], block: str) -> str:
    for item in coverage:
        if item.block == block:
            return item.status
    return "missing"


def _group_evidence(evidence: list[EvidenceItem]) -> dict[EvidenceKind, list[EvidenceItem]]:
    grouped: dict[EvidenceKind, list[EvidenceItem]] = {}
    for item in evidence:
        grouped.setdefault(item.kind, []).append(item)
    return grouped


def _is_private_intelligence_evidence(item: EvidenceItem) -> bool:
    return item.source_type == "zsxq_intelligence"


def _render_private_intelligence_summary(
    items: list[IntelligenceContextItem],
    appendix_name: str | None,
) -> list[str]:
    pending = sum(1 for item in items if item.verification_status != "verified")
    attachment_topics = sum(1 for item in items if item.attachments)
    high_risk = sum(1 for item in items if item.source_risk == "high")
    appendix = appendix_name or "未生成"
    lines = [
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
    return lines


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
    return text[: limit - 1] + "…"


def _format_bullets(values: list[str]) -> list[str]:
    return [f"- {_clean(value)}" for value in values]


def _render_stage_status(values: list[StageStatusItem]) -> list[str]:
    if not values:
        return ["- 暂无 Codex 阶段状态上下文。"]
    lines = ["| 阶段 | 状态 | 来源 | 说明 |", "| --- | --- | --- | --- |"]
    for item in values:
        lines.append(
            f"| {_clean(item.stage)} | {_clean(item.status)} | {_clean(item.source or 'N/A')} | {_clean(item.notes or 'N/A')} |"
        )
    return lines


def _render_coverage(values: list[CoverageItem]) -> list[str]:
    if not values:
        return ["- 暂无 MarketReviewCoverage 对账信息。"]
    lines = [
        "| 数据块 | 状态 | 来源 | 已补字段 | 缺失字段 | 说明 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in values:
        lines.append(
            "| "
            + " | ".join(
                [
                    _clean(f"{item.block}（{_coverage_label(item.block)}）"),
                    _clean(item.status),
                    _clean(item.source or "N/A"),
                    _clean("、".join(item.fields) if item.fields else "N/A"),
                    _clean("、".join(item.missing_fields) if item.missing_fields else "N/A"),
                    _clean(item.notes or "N/A"),
                ]
            )
            + " |"
        )
    return lines


def _render_data_quality(values: list[DataQualityItem]) -> list[str]:
    if not values:
        return ["- 暂无 Codex 数据质量上下文。"]
    lines = ["| 数据块 | 状态 | 来源 | 更新时间 | 说明 |", "| --- | --- | --- | --- | --- |"]
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
    return lines


def _format_risk_items(values: list[RiskItem]) -> list[str]:
    formatted: list[str] = []
    for item in values:
        suffix = f"（来源：{item.source}）" if item.source else ""
        formatted.append(f"{item.category}（{item.severity}）：{item.description}{suffix}")
    return formatted


def _format_optional_number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def _format_optional_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def _default_observations() -> list[str]:
    return [
        "观察核心指数是否能同步站稳短期均线，以及成交量是否与指数方向形成确认。",
        "观察强势板块能否获得公告、业绩、资金和新闻多源验证，避免只依据单一舆情判断。",
    ]


def _default_risks() -> list[str]:
    return [
        "外部补充数据以“数据块对账”和“数据质量”为准；partial、missing、fetch_failed 数据块需降低结论置信度。",
        "新闻、研报和社交内容存在时效与噪声，需要结合交易所公告和正式披露交叉验证。",
    ]


def _clean(value: str | None) -> str:
    return sanitize_report_text(value)


if __name__ == "__main__":
    raise SystemExit(main())
