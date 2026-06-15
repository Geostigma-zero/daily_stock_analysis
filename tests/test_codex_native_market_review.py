# -*- coding: utf-8 -*-
"""Codex-native A-share market review workflow tests."""

from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path


def _write_day_file(path: Path, start_close: int = 1000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx in range(24):
        trade_date = 20260501 + idx
        close_i = start_close + idx * 10
        open_i = close_i - 5
        high_i = close_i + 8
        low_i = close_i - 12
        amount_f = float(1_000_000 + idx * 50_000)
        volume_i = 10_000 + idx * 500
        rows.append((trade_date, open_i, high_i, low_i, close_i, amount_f, volume_i, 0))
    path.write_bytes(b"".join(struct.pack("<IIIIIfII", *row) for row in rows))


def _build_index_fixture(tmp_path: Path) -> Path:
    tdx_dir = tmp_path / "tdx"
    index_files = {
        "sh000001": 300000,
        "sz399001": 980000,
        "sz399006": 210000,
        "sh000300": 420000,
        "sh000905": 610000,
        "sh000852": 650000,
        "sh000688": 120000,
    }
    for symbol, start_close in index_files.items():
        market = symbol[:2]
        code = symbol[2:]
        _write_day_file(tdx_dir / "vipdoc" / market / "lday" / f"{market}{code}.day", start_close)
    return tdx_dir


def test_default_indexes_include_star50_and_load_local_snapshot(tmp_path: Path) -> None:
    from codex_native.market_review import DEFAULT_INDEXES, load_market_review_snapshot

    tdx_dir = _build_index_fixture(tmp_path)

    assert ("sh000688", "科创50") in [(item.symbol, item.name) for item in DEFAULT_INDEXES]

    snapshot = load_market_review_snapshot(tdx_dir=tdx_dir, phase="postmarket")

    assert snapshot.phase == "postmarket"
    assert snapshot.indices[-1].symbol == "sh000688"
    assert snapshot.indices[-1].name == "科创50"
    assert snapshot.indices[-1].indicators.latest_trade_date == "20260524"
    assert snapshot.indices[-1].indicators.change_pct_1d == 0.01
    assert "history" in snapshot.indices[-1].data_sources
    assert snapshot.data_limitations


def test_market_review_cli_generates_markdown_with_context_json(tmp_path: Path) -> None:
    tdx_dir = _build_index_fixture(tmp_path)
    output_dir = tmp_path / "reports"
    context_path = tmp_path / "context.json"
    context_path.write_text(
        json.dumps(
            {
                "breadth": {"上涨家数": "3200", "下跌家数": "1800"},
                "sectors": ["半导体", "光通信"],
                "funds": {"主力资金": "净流出"},
                "evidence": [
                    {
                        "kind": "verified_fact",
                        "source_type": "news",
                        "title": "指数样本调整公告",
                        "summary": "交易所披露指数样本定期调整信息。",
                        "source": "交易所公告",
                        "published_at": "2026-06-05",
                    },
                    {
                        "kind": "market_rumor",
                        "source_type": "social",
                        "title": "社交平台传言建议买入并加仓",
                        "summary": "该说法未见正式披露验证。",
                        "source": "舆情搜索",
                    },
                ],
                "stage_status": [
                    {"stage": "技术面", "status": "available", "source": "tdx-local"},
                    {"stage": "风险面", "status": "partial", "source": "news-search", "notes": "缺少完整舆情"},
                ],
                "data_quality": [
                    {"block": "breadth", "status": "available", "source": "mcp__tdx_official"},
                    {"block": "social", "status": "stale", "source": "舆情搜索", "notes": "样本时间偏旧"},
                ],
                "risk_items": [
                    {
                        "category": "行业政策",
                        "severity": "medium",
                        "description": "需关注盘后政策消息对强势板块的持续影响。",
                        "source": "news-search",
                    }
                ],
                "observations": ["观察科创50与创业板指是否继续同步放量。"],
                "data_limitations": ["未取得完整逐笔成交与北向实时拆分数据。"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_native.market_review",
            "--phase",
            "postmarket",
            "--tdx-dir",
            str(tdx_dir),
            "--output-dir",
            str(output_dir),
            "--context-json",
            str(context_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    paths = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip().endswith(".md")]
    assert len(paths) == 1
    content = paths[0].read_text(encoding="utf-8")

    assert "# Codex Native A股大盘盘后复盘" in content
    assert "科创50" in content
    assert "## 主要指数表现" in content
    assert "## 板块与题材" in content
    assert "## 阶段执行状态" in content
    assert "## 数据质量" in content
    assert "## 已验证事实" in content
    assert "## 市场传闻" in content
    assert "## 逻辑推演" in content
    assert "## 研究假设" in content
    assert "行业政策（medium）" in content
    assert "观察科创50与创业板指是否继续同步放量" in content
    assert "数据块 social 状态 stale" in content
    assert "## 数据缺口" in content
    assert "未取得完整逐笔成交与北向实时拆分数据" in content
    for forbidden in ("买入", "卖出", "加仓", "减仓", "仓位比例", "止损"):
        assert forbidden not in content


def test_market_review_intraday_report_uses_quality_card_and_private_appendix(tmp_path: Path) -> None:
    tdx_dir = _build_index_fixture(tmp_path)
    output_dir = tmp_path / "reports"
    context_path = tmp_path / "private-context.json"
    context_path.write_text(
        json.dumps(
            {
                "coverage": [
                    {"block": "index_quotes", "status": "available", "source": "tdx-local"},
                    {
                        "block": "breadth",
                        "status": "partial",
                        "source": "mcp__tdx",
                        "fields": ["上涨家数"],
                        "missing_fields": ["跌停"],
                    },
                    {"block": "turnover", "status": "available", "source": "mcp__tdx"},
                    {
                        "block": "real_time_funds",
                        "status": "partial",
                        "source": "mcp__tdx_official",
                        "fields": ["主力样本"],
                        "missing_fields": ["北向/外资口径"],
                    },
                    {"block": "sector_strength", "status": "partial", "source": "zsxq"},
                    {"block": "news_sentiment", "status": "partial", "source": "zsxq"},
                ],
                "intelligence_items": [
                    {
                        "source_group": "小牛研报纪要",
                        "group_id": "15555851111822",
                        "topic_id": "private-1",
                        "title": "KLA市值超过3000亿美元，持续强call量测设备",
                        "summary": "核心受益标的提法需要降噪；原文还写了目标价和强call。",
                        "tags": ["#文字观点#"],
                        "published_at": "2026-06-12T08:00:00+0800",
                        "attachments": ["私域研报.pdf"],
                        "matched_symbols": ["精测电子"],
                        "matched_sectors": ["半导体设备"],
                        "verification_status": "needs_verification",
                        "source_policy": "private_intelligence_only",
                        "source_risk": "medium",
                        "suggested_section": "market_rumor",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_native.market_review",
            "--phase",
            "intraday",
            "--tdx-dir",
            str(tdx_dir),
            "--output-dir",
            str(output_dir),
            "--context-json",
            str(context_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    paths = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip().endswith(".md")]
    assert len(paths) == 1
    content = paths[0].read_text(encoding="utf-8")
    appendix_path = paths[0].with_name(paths[0].name.replace("_cn_market_review.md", "_cn_market_review_appendix.md"))
    appendix = appendix_path.read_text(encoding="utf-8")

    assert "# Codex Native A股大盘盘中复盘（降级）" in content
    assert "# Codex Native A股大盘盘后复盘" not in content
    assert "## 报告质量卡" in content
    assert "完整索引见附录" in content
    assert appendix_path.name in content
    assert "## 私域情报摘要" in content
    assert "private-1" not in content
    assert "核心受益标的" not in content
    assert "强call" not in content
    assert appendix_path.exists()
    assert "## 私域情报索引" in appendix
    assert "topic_id=private-1" in appendix
    assert "核心受益标的" not in appendix
    assert "强call" not in appendix
    assert "[动作词已屏蔽]" in appendix


def test_market_review_coverage_prevents_generic_gap_and_splits_turnover_from_fund_flow(tmp_path: Path) -> None:
    tdx_dir = _build_index_fixture(tmp_path)
    output_dir = tmp_path / "reports"
    context_path = tmp_path / "coverage-context.json"
    context_path.write_text(
        json.dumps(
            {
                "coverage": [
                    {
                        "block": "index_quotes",
                        "status": "available",
                        "source": "tdx-local",
                        "fields": ["上证指数", "深证成指", "创业板指", "沪深300", "中证500", "中证1000", "科创50"],
                    },
                    {
                        "block": "breadth",
                        "status": "available",
                        "source": "mcp__tdx_official",
                        "fields": ["上涨家数", "下跌家数", "平盘", "涨停"],
                    },
                    {
                        "block": "turnover",
                        "status": "available",
                        "source": "mcp__tdx_official",
                        "fields": ["沪市成交额", "深市成交额", "全市场成交额"],
                    },
                    {
                        "block": "real_time_funds",
                        "status": "missing",
                        "source": "mcp__tdx.symbol_zjlx",
                        "missing_fields": ["主力资金", "北向/外资口径", "ETF/融资融券"],
                        "notes": "资金工具未返回可用数据。",
                    },
                    {
                        "block": "sector_strength",
                        "status": "available",
                        "source": "mcp__tdx_official",
                        "fields": ["行业涨幅前列", "概念跌幅前列"],
                    },
                    {
                        "block": "news_sentiment",
                        "status": "partial",
                        "source": "news-search",
                        "fields": ["收评新闻"],
                        "missing_fields": ["可量化社交情绪"],
                    },
                ],
                "tool_attempts": [
                    {
                        "tool": "mcp__tdx.symbol_zjlx",
                        "query": "A股大盘主力资金",
                        "status": "fetch_failed",
                        "error": "schema validation failed",
                        "fallback": "仅使用成交额，不把成交额当作实时资金。",
                    }
                ],
                "breadth": {"上涨家数": "663", "下跌家数": "4507", "平盘": "337", "涨停": "62"},
                "sectors": ["油气开采 +3.11%", "半导体制造 -5.63%"],
                "funds": {
                    "turnover": {
                        "沪市成交额": "约1.267万亿元",
                        "深市成交额": "约1.525万亿元",
                        "全市场成交额": "约2.82万亿元",
                    }
                },
                "data_quality": [
                    {"block": "breadth", "status": "available", "source": "mcp__tdx_official"},
                    {"block": "turnover", "status": "available", "source": "mcp__tdx_official"},
                    {"block": "real_time_funds", "status": "missing", "source": "mcp__tdx.symbol_zjlx"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_native.market_review",
            "--phase",
            "postmarket",
            "--tdx-dir",
            str(tdx_dir),
            "--output-dir",
            str(output_dir),
            "--context-json",
            str(context_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    paths = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip().endswith(".md")]
    content = paths[0].read_text(encoding="utf-8")

    assert "# Codex Native A股大盘盘后复盘（降级）" in content
    assert "## 数据块对账" in content
    assert "实时资金未补齐" in content
    assert "mcp__tdx.symbol_zjlx" in content
    assert "schema validation failed" in content
    assert "成交额：" in content
    assert "资金流：" in content
    assert "成交额不是实时资金" in content
    assert "涨跌家数、成交额、实时资金、板块强度需由 Codex 调用 MCP 或 skills 补齐" not in content
    assert "资金信息：" not in content


def test_market_review_strict_context_fails_when_required_block_missing(tmp_path: Path) -> None:
    tdx_dir = _build_index_fixture(tmp_path)
    context_path = tmp_path / "strict-context.json"
    context_path.write_text(
        json.dumps(
            {
                "coverage": [
                    {"block": "index_quotes", "status": "available", "source": "tdx-local"},
                    {"block": "breadth", "status": "available", "source": "mcp__tdx_official"},
                    {"block": "turnover", "status": "available", "source": "mcp__tdx_official"},
                    {"block": "real_time_funds", "status": "missing", "source": "mcp__tdx.symbol_zjlx"},
                    {"block": "sector_strength", "status": "available", "source": "mcp__tdx_official"},
                    {"block": "news_sentiment", "status": "partial", "source": "news-search"},
                ],
                "breadth": {"上涨家数": "663"},
                "funds": {"turnover": {"全市场成交额": "约2.82万亿元"}},
                "sectors": ["油气开采 +3.11%"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_native.market_review",
            "--phase",
            "postmarket",
            "--tdx-dir",
            str(tdx_dir),
            "--context-json",
            str(context_path),
            "--strict-context",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "real_time_funds" in result.stderr
    assert "实时资金" in result.stderr


def test_market_review_cli_fails_when_core_index_file_missing(tmp_path: Path) -> None:
    tdx_dir = _build_index_fixture(tmp_path)
    (tdx_dir / "vipdoc" / "sh" / "lday" / "sh000688.day").unlink()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_native.market_review",
            "--phase",
            "postmarket",
            "--tdx-dir",
            str(tdx_dir),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "sh000688" in result.stderr
    assert "missing local TDX index day files" in result.stderr


def test_market_review_docs_document_codex_orchestration_rules() -> None:
    doc_path = Path(__file__).resolve().parents[1] / "docs" / "codex-native.md"
    content = doc_path.read_text(encoding="utf-8")

    assert "python -m codex_native.market_review" in content
    assert "mcp__tdx" in content
    assert "mcp__tdx_official" in content
    assert "news-search" in content
    assert "公告" in content
    assert "研报" in content
    assert "科创50" in content
    assert "不输出直接操作动作" in content
    assert "available / partial / stale / missing / fetch_failed / not_supported" in content
    assert "涨跌家数" in content
    assert "成交额" in content
    assert "主要指数表现" in content
    assert "板块与题材" in content
    assert "风险提示" in content
    assert "--strict-context" in content
    assert "成交额不是实时资金" in content
    assert "报告质量卡" in content
    assert "_appendix.md" in content
    assert "报告标题会随 `--phase` 变化" in content
