# -*- coding: utf-8 -*-
"""Codex-native ZSXQ intelligence workflow tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _context_payload() -> dict:
    long_text = "这是很长的星球原文。" * 80
    return {
        "source_policy": {
            "default": "needs_verification",
            "verified_fact_rule": "只有公告、新闻、研报、MCP 或问财二次核验后才能进入已验证事实。",
        },
        "collection_coverage": {
            "window_start": "2026-06-10 08:00:00+0800",
            "window_end": "2026-06-10 23:30:00+0800",
            "source": "zsxq-cli group +topics",
            "fetched_topics": "3",
            "kept_topics": "3",
        },
        "intelligence_items": [
            {
                "source_group": "小牛研报纪要",
                "group_id": "15555851111822",
                "topic_id": "logic-001",
                "title": "#逻辑精选",
                "summary": "市场逻辑精选：半导体、PCB、CPO 方向热度提升。",
                "tags": ["#逻辑精选#"],
                "published_at": "2026-06-10T08:27:24.201+0800",
                "attachments": ["20260610 市场逻辑精选.pdf"],
                "matched_symbols": ["沪电股份", "胜宏科技"],
                "matched_sectors": ["半导体", "PCB", "CPO"],
                "verification_status": "needs_verification",
                "source_policy": "needs_verification",
                "source_risk": "medium",
                "suggested_section": "logical_inference",
                "readers": 320,
                "likes": 2,
            },
            {
                "source_group": "小牛研报纪要",
                "group_id": "15555851111822",
                "topic_id": "report-001",
                "title": "#外资研报",
                "summary": "海外机构讨论 CPO 与 800VDC 进度，涉及光模块和电源架构。",
                "tags": ["#外资研报#"],
                "published_at": "2026-06-10T22:09:08.351+0800",
                "attachments": ["MS-半导体 Computex takeaways.pdf"],
                "matched_symbols": [],
                "matched_sectors": ["CPO", "半导体设备"],
                "verification_status": "needs_verification",
                "source_policy": "archive_only",
                "source_risk": "medium",
                "suggested_section": "market_rumor",
                "readers": 210,
            },
            {
                "source_group": "小牛研报纪要",
                "group_id": "15555851111822",
                "topic_id": "rumor-001",
                "title": "来源未知强call某公司，建议买入并加仓",
                "summary": f"{long_text} 原文包含止损、目标价和仓位比例。",
                "tags": ["#来源未知谨慎风险#"],
                "published_at": "2026-06-10T23:00:00.000+0800",
                "attachments": [],
                "matched_symbols": ["示例公司"],
                "matched_sectors": ["机器人"],
                "verification_status": "unverified",
                "source_policy": "rumor",
                "source_risk": "high",
                "suggested_section": "market_rumor",
                "readers": 100,
            },
        ],
        "data_limitations": ["PDF 附件只记录元数据，未全文解析。"],
    }


def _large_context_payload() -> dict:
    items = []
    for idx in range(18):
        tags = ["#文字观点#"]
        sectors = ["AI", "算力", "服务器"] if idx % 2 == 0 else ["半导体", "芯片", "材料"]
        symbols = ["江丰电子", "8000", "CSP", "机器人"] if idx % 3 == 0 else ["中芯国际", "机器人"]
        attachments = [f"附件{idx}.pdf"] if idx % 4 == 0 else []
        if idx == 0:
            tags.append("#5分钟即售罄。#")
            tags.append("#逻辑精选#")
        if idx == 1:
            tags = ["#外资研报#"]
            attachments = ["MS-AI hardware.pdf"]
        if idx == 2:
            tags = ["#市场段子#"]
        items.append(
            {
                "source_group": "小牛研报纪要",
                "group_id": "15555851111822",
                "topic_id": f"topic-{idx:03d}",
                "title": f"主题{idx}",
                "summary": "围绕 AI 硬件、半导体链和数据中心的线索摘要。",
                "tags": tags,
                "published_at": f"2026-06-10T{8 + idx // 2:02d}:{idx % 60:02d}:00.000+0800",
                "attachments": attachments,
                "matched_symbols": symbols,
                "matched_sectors": sectors,
                "verification_status": "unverified" if idx == 2 else "needs_verification",
                "source_policy": "rumor" if idx == 2 else "needs_verification",
                "source_risk": "high" if idx == 2 else "medium",
                "suggested_section": "market_rumor",
                "readers": 500 - idx,
                "likes": idx % 3,
            }
        )
    return {
        "source_group": "小牛研报纪要",
        "group_id": "15555851111822",
        "collection_coverage": {
            "window_start": "2026-06-10 15:00:00+0800",
            "window_end": "2026-06-10 22:30:00+0800",
            "source": "zsxq-cli group +topics",
            "fetched_topics": str(len(items)),
            "kept_topics": str(len(items)),
        },
        "intelligence_items": items,
        "data_limitations": ["附件仅记录文件名，未全文解析。"],
    }


def test_zsxq_context_parses_and_classifies_sessions() -> None:
    from codex_native.zsxq_intelligence import (
        classify_item,
        load_zsxq_intelligence_context,
        select_session_items,
    )

    context = load_zsxq_intelligence_context(_context_payload())

    assert context.source_group == "小牛研报纪要"
    assert context.group_id == "15555851111822"
    assert len(context.items) == 3
    assert classify_item(context.items[0], "premarket") == "must_track"
    assert classify_item(context.items[1], "premarket") == "archive_only"
    assert classify_item(context.items[1], "evening") == "must_track"
    assert classify_item(context.items[2], "evening") == "low_confidence"
    assert [item.topic_id for item in select_session_items(context.items, "premarket")] == [
        "logic-001",
        "report-001",
        "rumor-001",
    ]
    assert [item.topic_id for item in select_session_items(context.items, "evening")] == [
        "logic-001",
        "report-001",
        "rumor-001",
    ]


def test_zsxq_markdown_report_is_safe_and_summarized() -> None:
    from codex_native.zsxq_intelligence import load_zsxq_intelligence_context, render_zsxq_markdown

    context = load_zsxq_intelligence_context(_context_payload())
    markdown = render_zsxq_markdown(context, session="evening", report_date="20260610")

    assert "# 小牛研报纪要情报晚报" in markdown
    assert "## 情报扫描总览" in markdown
    assert "采集窗口：2026-06-10 08:00:00+0800 至 2026-06-10 23:30:00+0800" in markdown
    assert "覆盖主题：3 条" in markdown
    assert "附件主题：2 条" in markdown
    assert "低置信：1 条" in markdown
    assert "#外资研报#：1 条" in markdown
    assert "## 主题簇摘要" in markdown
    assert "CPO：2 条线索" in markdown
    assert "完整索引和附件清单见附录" in markdown
    assert "## 研报纪要附件清单" not in markdown
    assert "MS-半导体 Computex takeaways.pdf" not in markdown
    assert "## 全量条目索引" not in markdown
    assert "report-001" in markdown
    assert "## 低置信舆情" in markdown
    assert "rumor-001" in markdown
    assert "PDF 附件只记录元数据" in markdown
    assert "这是很长的星球原文。" * 20 not in markdown
    for forbidden in ("买入", "卖出", "加仓", "减仓", "仓位比例", "止损", "止盈"):
        assert forbidden not in markdown


def test_zsxq_cli_generates_session_named_report(tmp_path: Path) -> None:
    context_path = tmp_path / "context.json"
    output_dir = tmp_path / "reports"
    context_path.write_text(json.dumps(_context_payload(), ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_native.zsxq_intelligence",
            "--session",
            "premarket",
            "--date",
            "20260610",
            "--context-json",
            str(context_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    path = output_dir / "20260610_premarket_xiaoniu.md"
    assert path.exists()
    assert str(path) in result.stdout
    content = path.read_text(encoding="utf-8")
    appendix = output_dir / "20260610_premarket_xiaoniu_appendix.md"
    assert "# 小牛研报纪要情报早报" in content
    assert appendix.exists()
    assert "logic-001" in content
    assert "report-001" in content
    assert "## 全量条目索引" not in content
    assert "## 全量条目索引" in appendix.read_text(encoding="utf-8")
    assert "覆盖主题：3 条" in content


def test_zsxq_large_report_splits_appendix_and_denoises_display(tmp_path: Path) -> None:
    from codex_native.zsxq_intelligence import generate_zsxq_report

    context_path = tmp_path / "context.json"
    output_dir = tmp_path / "reports"
    payload = _large_context_payload()
    context_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    report_path = generate_zsxq_report(
        session="evening",
        report_date="20260610",
        context_json=context_path,
        output_dir=output_dir,
    )

    appendix_path = output_dir / "20260610_evening_xiaoniu_appendix.md"
    report = report_path.read_text(encoding="utf-8")
    appendix = appendix_path.read_text(encoding="utf-8")

    assert appendix_path.exists()
    assert len(report.splitlines()) < 220
    assert "## 全量条目索引" not in report
    assert "## 研报纪要附件清单" not in report
    assert "## 全量条目索引" in appendix
    assert "## 研报纪要附件清单" in appendix
    for item in payload["intelligence_items"]:
        assert item["topic_id"] in appendix

    assert "#文字观点#：" in report
    assert "#5分钟即售罄。#" not in report
    assert "AI 硬件" in report
    assert "半导体链" in report
    assert "江丰电子" in report
    assert "8000：" not in report
    assert "CSP：" not in report
    assert "## 歧义标的/行业词" in report
    assert "机器人" in report


def test_zsxq_items_flow_into_existing_context_evidence() -> None:
    from codex_native.context import parse_context
    from codex_native.evidence import EvidenceKind

    context = parse_context(_context_payload())

    zsxq_evidence = [item for item in context.evidence if item.source_type == "zsxq_intelligence"]
    assert len(zsxq_evidence) == 3
    assert zsxq_evidence[0].kind == EvidenceKind.LOGICAL_INFERENCE
    assert zsxq_evidence[1].kind == EvidenceKind.MARKET_RUMOR
    assert zsxq_evidence[2].kind == EvidenceKind.MARKET_RUMOR
    assert "topic_id=logic-001" in zsxq_evidence[0].source
    assert "未经二次核验" in zsxq_evidence[0].summary


def test_zsxq_docs_document_schedule_and_source_policy() -> None:
    doc_path = Path(__file__).resolve().parents[1] / "docs" / "codex-native.md"
    text = doc_path.read_text(encoding="utf-8")

    assert "08:45" in text
    assert "22:30" in text
    assert "小牛研报纪要" in text
    assert "15555851111822" in text
    assert "不是直接事实源" in text
    assert "#逻辑精选#" in text
    assert "#脱水研报#" in text
    assert "#外资研报#" in text
    assert "group +topics --limit 30 --json" in text
    assert "--end-time" in text
    assert "intelligence_items` 保留窗口内全部主题" in text
    assert "盘前默认采集窗口" in text
    assert "前一交易日 `22:30` 到当前运行时间" in text
    assert "晚间默认采集窗口" in text
    assert "全日归档" in text
    assert "不输出直接操作动作" in text
