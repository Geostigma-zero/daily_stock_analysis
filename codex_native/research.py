"""CLI entrypoint for Codex-native A-share research report generation."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from datetime import datetime, time
from pathlib import Path

from .context import CodexResearchContext, load_context_json, parse_context
from .indicators import calculate_indicators

from .models import MarketDataSnapshot
from .ranker_db import load_ranker_daily_snapshot
from .report import build_research_report, render_markdown, render_research_appendix_markdown
from .tdx import find_tdx_day_file, load_tdx_name_map, load_tdx_xr_events, normalize_code, parse_tdx_day_file

VALID_PHASES = ("auto", "premarket", "intraday", "postmarket")


def resolve_phase(phase: str, now: datetime | None = None) -> str:
    selected = phase.lower().strip()
    if selected != "auto":
        if selected not in VALID_PHASES:
            raise ValueError(f"phase must be one of: {', '.join(VALID_PHASES)}")
        return selected
    current = now or datetime.now()
    current_time = current.time()
    if current.weekday() >= 5:
        return "postmarket"
    if current_time < time(9, 30):
        return "premarket"
    if current_time <= time(15, 0):
        return "intraday"
    return "postmarket"


def load_snapshot(
    code: str,
    tdx_dir: str | Path | None,
    phase: str = "auto",
    daily_db_path: str | Path | None = None,
) -> MarketDataSnapshot:
    normalized = normalize_code(code)
    ranker_limitation: str | None = None
    if daily_db_path:
        try:
            ranker = load_ranker_daily_snapshot(daily_db_path, normalized)
            indicators = calculate_indicators(ranker.bars)
            return MarketDataSnapshot(
                code=normalized,
                name=ranker.name,
                phase=resolve_phase(phase),
                bars=ranker.bars,
                indicators=indicators,
                data_sources={
                    "history": f"ranker-db:{ranker.db_path}",
                    "name": "ranker-db:stocks" if ranker.name != normalized else "missing",
                },
                data_limitations=[
                    "单股历史日线优先读取 a_share_ranker 共享行情库；该库由 a_share_ranker 维护，本流程只读使用。",
                    "大盘指数日线不使用 a_share_ranker 股票行情库，需由本地通达信指数文件或 Codex MCP / skills 补充。",
                ],
            )
        except Exception as exc:
            ranker_limitation = f"a_share_ranker 共享行情库读取失败：{exc}"
            if not tdx_dir:
                raise RuntimeError(ranker_limitation) from exc
    if not tdx_dir:
        raise RuntimeError("no daily data source available; pass --daily-db/A_SHARE_RANKINGS_DB or --tdx-dir/TDX_LOCAL_DIR")
    root = Path(tdx_dir)
    names = load_tdx_name_map(root)
    name = names.get(normalized, normalized)
    day_path = find_tdx_day_file(root, normalized)
    xr_events = load_tdx_xr_events(root).get(normalized, [])
    bars = parse_tdx_day_file(day_path, xr_events=xr_events)
    if not bars:
        raise RuntimeError(f"no local TDX daily bars found for {normalized}")
    indicators = calculate_indicators(bars)
    limitations = [
        "Python 侧仅读取本地通达信历史日线；实时行情、F10、资金、板块需由 Codex 调用 MCP 或 skills 补齐。",
        "新闻、公告、研报和社交舆情未由 CLI 自动拉取，需要在 Codex skill 编排阶段补充并分类。",
    ]
    if name == normalized:
        limitations.append("本地通达信名称文件未找到该标的名称，报告暂以代码展示。")
    if not xr_events:
        limitations.append("未读取到该标的复权事件，指标按本地原始日线计算。")
    if ranker_limitation:
        limitations.append(ranker_limitation)
    return MarketDataSnapshot(
        code=normalized,
        name=name,
        phase=resolve_phase(phase),
        bars=bars,
        indicators=indicators,
        data_sources={
            "history": f"tdx-local:{day_path}",
            "name": "tdx-local:tnf" if name != normalized else "missing",
            "xr_events": "tdx-local:gbbq" if xr_events else "missing",
        },
        data_limitations=limitations,
    )


def generate_reports(
    codes: list[str],
    phase: str,
    tdx_dir: str | Path | None,
    output_dir: str | Path,
    context_json: str | Path | None = None,
    daily_db_path: str | Path | None = None,
) -> list[Path]:
    selected_phase = resolve_phase(phase)
    context = load_context_json(context_json) if context_json else parse_context({})
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for code in codes:
        snapshot = load_snapshot(code, tdx_dir=tdx_dir, phase=selected_phase, daily_db_path=daily_db_path)
        report = _build_report_from_context(snapshot, selected_phase, context)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"{timestamp}_{selected_phase}_{snapshot.code}.md"
        appendix_path = out_dir / f"{timestamp}_{selected_phase}_{snapshot.code}_appendix.md" if report.intelligence_items else None
        content = render_markdown(report, appendix_name=appendix_path.name if appendix_path else None)
        path.write_text(content, encoding="utf-8")
        if appendix_path:
            appendix_path.write_text(render_research_appendix_markdown(report), encoding="utf-8")
        paths.append(path)
    return paths


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Codex-native A-share Markdown research reports.")
    parser.add_argument("--codes", required=True, help="Comma-separated A-share codes, such as 600519,300750.")
    parser.add_argument("--phase", default="auto", choices=VALID_PHASES, help="Report phase template.")
    parser.add_argument("--tdx-dir", default=os.getenv("TDX_LOCAL_DIR"), help="Local TongDaXin root directory.")
    parser.add_argument(
        "--daily-db",
        default=os.getenv("A_SHARE_RANKINGS_DB"),
        help="Read-only a_share_ranker SQLite database path; defaults to A_SHARE_RANKINGS_DB.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("CODEX_RESEARCH_REPORT_DIR", "reports/codex_research"),
        help="Directory for generated Markdown reports.",
    )
    parser.add_argument(
        "--context-json",
        help="Optional JSON file prepared by Codex from MCP, skills, news, announcements, reports, and sentiment.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.tdx_dir and not args.daily_db:
        print(
            "A daily data source is required. Pass --daily-db or set A_SHARE_RANKINGS_DB; "
            "or pass --tdx-dir / set TDX_LOCAL_DIR.",
            file=sys.stderr,
        )
        return 2
    codes = [item.strip() for item in args.codes.split(",") if item.strip()]
    if not codes:
        print("--codes must contain at least one A-share code.", file=sys.stderr)
        return 2
    try:
        paths = generate_reports(
            codes,
            phase=args.phase,
            tdx_dir=args.tdx_dir,
            output_dir=args.output_dir,
            context_json=args.context_json,
            daily_db_path=args.daily_db,
        )
    except Exception as exc:
        print(f"Codex-native research generation failed: {exc}", file=sys.stderr)
        return 1
    for path in paths:
        print(path)
    return 0


def _build_report_from_context(snapshot: MarketDataSnapshot, phase: str, context: CodexResearchContext):
    if context.stage_status or context.data_quality or context.evidence:
        snapshot = replace(snapshot, data_limitations=_filter_snapshot_limitations(snapshot.data_limitations, context))
    return build_research_report(
        snapshot,
        phase=phase,
        evidence=context.evidence,
        observations=context.observations or None,
        risks=_context_risks(context),
        risk_items=context.risk_items,
        stage_status=context.stage_status,
        data_quality=context.data_quality,
        intelligence_items=context.intelligence_items,
        data_limitations=context.all_limitations(),
    )


def _filter_snapshot_limitations(limitations: list[str], context: CodexResearchContext) -> list[str]:
    available_blocks = {
        item.block
        for item in context.data_quality
        if item.status in {"available", "partial", "stale"}
    }
    available_stages = {
        item.stage
        for item in context.stage_status
        if item.status in {"available", "partial", "stale"}
    }
    has_market_context = bool(
        available_blocks
        & {
            "realtime_quote",
            "f10_financials",
            "fund_flow",
            "sector",
            "sector_strength",
        }
    ) or any(stage in available_stages for stage in ("实时行情", "F10/财务/股东", "资金流"))
    has_intel_context = bool(
        available_blocks
        & {
            "announcement",
            "research_report",
            "news",
            "news_sentiment",
            "social_sentiment",
        }
    ) or any(stage in available_stages for stage in ("公告/研报/新闻/舆情", "情报面", "舆情面"))

    filtered: list[str] = []
    for limitation in limitations:
        if has_market_context and "实时行情、F10、资金、板块需由 Codex 调用 MCP 或 skills 补齐" in limitation:
            continue
        if has_intel_context and "新闻、公告、研报和社交舆情未由 CLI 自动拉取" in limitation:
            continue
        filtered.append(limitation)
    return filtered


def _context_risks(context: CodexResearchContext) -> list[str] | None:
    if not (context.stage_status or context.data_quality or context.evidence):
        return None
    return [
        "外部补充数据以“阶段执行状态”和“数据质量”为准；partial、stale、fetch_failed 数据块需降低结论置信度。",
        "新闻、研报与社交内容存在时效和噪声，需要结合公告、交易所文件和公司披露核验。",
    ]


if __name__ == "__main__":
    raise SystemExit(main())
