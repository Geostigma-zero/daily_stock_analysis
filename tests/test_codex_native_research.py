# -*- coding: utf-8 -*-
"""Codex-native A-share research workflow tests."""

from __future__ import annotations

import struct
import subprocess
import sys
from datetime import datetime
import json
import sqlite3
from pathlib import Path


def _write_day_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        (20260601, 1000, 1020, 990, 1010, 1000000.0, 10000, 0),
        (20260602, 1010, 1040, 1000, 1030, 1300000.0, 13000, 0),
        (20260603, 1030, 1050, 1010, 1020, 900000.0, 9000, 0),
        (20260604, 1020, 1060, 1010, 1050, 1800000.0, 18000, 0),
        (20260605, 1050, 1080, 1040, 1070, 2200000.0, 22000, 0),
    ]
    path.write_bytes(b"".join(struct.pack("<IIIIIfII", *row) for row in rows))


def _write_tnf(path: Path, code: str, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = bytearray(360)
    record[50:56] = code.encode("ascii")
    name_bytes = name.encode("gbk")
    record[80 : 80 + len(name_bytes)] = name_bytes
    path.write_bytes(bytes(record))


def _build_tdx_fixture(tmp_path: Path) -> Path:
    tdx_dir = tmp_path / "tdx"
    _write_day_file(tdx_dir / "vipdoc" / "sh" / "lday" / "sh600519.day")
    _write_tnf(tdx_dir / "T0002" / "hq_cache" / "shs.tnf", "600519", "贵州茅台")
    return tdx_dir


def _build_ranker_db_fixture(tmp_path: Path) -> Path:
    db_path = tmp_path / "ranker.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE stocks (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                list_date TEXT,
                market TEXT,
                is_st INTEGER NOT NULL DEFAULT 0,
                latest_seen_date TEXT,
                source TEXT NOT NULL DEFAULT 'tdx',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE daily_prices (
                trade_date TEXT NOT NULL,
                code TEXT NOT NULL,
                open REAL,
                close REAL,
                high REAL,
                low REAL,
                volume REAL,
                amount REAL,
                adj_close REAL,
                source TEXT NOT NULL DEFAULT 'tdx',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (trade_date, code)
            );
            INSERT INTO stocks (code, name, market, latest_seen_date, source)
            VALUES ('600519', '贵州茅台', 'SH', '20260605', 'tdx');
            """
        )
        rows = [
            ("20260601", "600519", 10.0, 10.1, 10.2, 9.9, 10000.0, 1000000.0, 10.1, "tdx"),
            ("20260602", "600519", 10.1, 10.3, 10.4, 10.0, 13000.0, 1300000.0, 10.3, "tdx"),
            ("20260603", "600519", 10.3, 10.2, 10.5, 10.1, 9000.0, 900000.0, 10.2, "tdx"),
            ("20260604", "600519", 10.2, 10.5, 10.6, 10.1, 18000.0, 1800000.0, 10.5, "tdx"),
            ("20260605", "600519", 10.5, 10.7, 10.8, 10.4, 22000.0, 2200000.0, 10.7, "tdx"),
        ]
        conn.executemany(
            """
            INSERT INTO daily_prices
                (trade_date, code, open, close, high, low, volume, amount, adj_close, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return db_path


def test_tdx_day_and_name_parsing(tmp_path: Path) -> None:
    from codex_native.tdx import find_tdx_day_file, load_tdx_name_map, parse_tdx_day_file

    tdx_dir = _build_tdx_fixture(tmp_path)

    assert find_tdx_day_file(tdx_dir, "600519").name == "sh600519.day"
    assert load_tdx_name_map(tdx_dir)["600519"] == "贵州茅台"

    bars = parse_tdx_day_file(find_tdx_day_file(tdx_dir, "SH600519"))

    assert [bar.trade_date for bar in bars] == ["20260601", "20260602", "20260603", "20260604", "20260605"]
    assert bars[-1].close == 10.7
    assert bars[-1].source == "tdx-local"


def test_snapshot_indicators_and_auto_phase(tmp_path: Path) -> None:
    from codex_native.research import load_snapshot, resolve_phase

    tdx_dir = _build_tdx_fixture(tmp_path)

    snapshot = load_snapshot("600519", tdx_dir=tdx_dir)

    assert snapshot.code == "600519"
    assert snapshot.name == "贵州茅台"
    assert snapshot.indicators.last_close == 10.7
    assert snapshot.indicators.change_pct_1d == 1.9
    assert snapshot.indicators.volume_ratio_5d == 1.53
    assert snapshot.indicators.ma5 == 10.36
    assert snapshot.data_limitations
    assert resolve_phase("auto", now=datetime(2026, 6, 5, 10, 0, 0)) == "intraday"
    assert resolve_phase("auto", now=datetime(2026, 6, 5, 8, 45, 0)) == "premarket"
    assert resolve_phase("auto", now=datetime(2026, 6, 5, 16, 30, 0)) == "postmarket"


def test_snapshot_loads_from_ranker_daily_database_without_tdx_dir(tmp_path: Path) -> None:
    from codex_native.research import load_snapshot

    db_path = _build_ranker_db_fixture(tmp_path)

    snapshot = load_snapshot("600519", tdx_dir=None, daily_db_path=db_path)

    assert snapshot.code == "600519"
    assert snapshot.name == "贵州茅台"
    assert snapshot.indicators.latest_trade_date == "20260605"
    assert snapshot.indicators.last_close == 10.7
    assert snapshot.indicators.change_pct_1d == 1.9
    assert snapshot.indicators.ma5 == 10.36
    assert snapshot.indicators.volume_ratio_5d == 1.53
    assert snapshot.data_sources["history"].startswith("ranker-db:")
    assert "tdx-local" not in snapshot.data_sources["history"]


def test_cli_generates_report_from_ranker_daily_database_without_tdx_dir(tmp_path: Path) -> None:
    db_path = _build_ranker_db_fixture(tmp_path)
    output_dir = tmp_path / "reports"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_native.research",
            "--codes",
            "600519",
            "--phase",
            "postmarket",
            "--daily-db",
            str(db_path),
            "--output-dir",
            str(output_dir),
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
    assert "## 研究质量卡" in content
    assert "ranker-db:<redacted>" in content
    assert str(db_path) not in content
    assert "贵州茅台（600519）" in content


def test_evidence_classification_and_report_safety(tmp_path: Path) -> None:
    from codex_native.evidence import EvidenceItem, EvidenceKind
    from codex_native.report import build_research_report, render_markdown
    from codex_native.research import load_snapshot

    tdx_dir = _build_tdx_fixture(tmp_path)
    snapshot = load_snapshot("600519", tdx_dir=tdx_dir)
    evidence = [
        EvidenceItem(
            kind=EvidenceKind.VERIFIED_FACT,
            source_type="announcement",
            title="公司发布年度权益分派实施公告",
            summary="公告显示分红方案已披露。",
            source="巨潮资讯",
            published_at="2026-06-04",
        ),
        EvidenceItem(
            kind=EvidenceKind.MARKET_RUMOR,
            source_type="social",
            title="网传机构建议买入并加仓",
            summary="该内容未见公告或交易所文件验证。",
            source="舆情搜索",
        ),
    ]

    report = build_research_report(snapshot, phase="postmarket", evidence=evidence)
    markdown = render_markdown(report)

    assert "## 已验证事实" in markdown
    assert "## 市场传闻" in markdown
    assert "## 观察条件" in markdown
    assert "## 数据缺口" in markdown
    assert "不构成交易建议" in markdown
    for forbidden in ("买入", "卖出", "加仓", "减仓", "仓位比例"):
        assert forbidden not in markdown


def test_context_json_parser_keeps_framework_blocks() -> None:
    from codex_native.context import parse_context

    context = parse_context(
        {
            "stage_status": [
                {"stage": "技术面", "status": "available", "source": "tdx-local", "notes": "日线已读取"},
                {"stage": "舆情面", "status": "unknown-state", "source": "social-skill", "notes": "来源状态异常"},
            ],
            "data_quality": [
                {"block": "news", "status": "partial", "source": "news-search", "notes": "只覆盖盘后新闻"},
                {"block": "mcp_realtime", "status": "fetch_failed", "source": "mcp__tdx.symbol_info"},
            ],
            "risk_items": [
                {"category": "监管", "severity": "medium", "description": "近期问询需跟踪回复。", "source": "公告"},
            ],
            "observations": ["观察公告回复与量能是否同步改善。"],
            "data_limitations": ["缺少完整社交样本。"],
        }
    )

    assert [item.stage for item in context.stage_status] == ["技术面", "舆情面"]
    assert context.stage_status[1].status == "partial"
    assert "原始状态：unknown-state" in context.stage_status[1].notes
    assert context.data_quality[0].status == "partial"
    assert context.data_quality[1].status == "fetch_failed"
    assert context.risk_items[0].category == "监管"
    assert "数据块 news 状态 partial" in context.quality_limitations()[0]
    assert context.observations == ["观察公告回复与量能是否同步改善。"]


def test_cli_generates_markdown_report_with_context_json(tmp_path: Path) -> None:
    tdx_dir = _build_tdx_fixture(tmp_path)
    output_dir = tmp_path / "reports"
    context_path = tmp_path / "context.json"
    context_path.write_text(
        json.dumps(
            {
                "stage_status": [
                    {"stage": "技术面", "status": "available", "source": "tdx-local", "notes": "本地日线已读取"},
                    {"stage": "情报面", "status": "partial", "source": "news-search", "notes": "仅取得盘后新闻"},
                ],
                "data_quality": [
                    {"block": "realtime_quote", "status": "available", "source": "mcp__tdx.symbol_info"},
                    {"block": "news", "status": "partial", "source": "news-search", "notes": "新闻样本不完整"},
                    {"block": "mcp_realtime", "status": "fetch_failed", "source": "mcp__tdx.symbol_info"},
                ],
                "evidence": [
                    {
                        "kind": "verified_fact",
                        "source_type": "announcement",
                        "title": "公司披露经营进展",
                        "summary": "公告披露项目进展，仍需跟踪落地节奏。",
                        "source": "巨潮资讯",
                        "published_at": "2026-06-05",
                    },
                    {
                        "kind": "market_rumor",
                        "source_type": "social",
                        "title": "社交平台传言建议买入并加仓",
                        "summary": "未见正式披露验证，且包含止损讨论。",
                        "source": "舆情搜索",
                    },
                ],
                "risk_items": [
                    {
                        "category": "监管",
                        "severity": "medium",
                        "description": "需关注监管问询和回复进度。",
                        "source": "公告",
                    },
                    {
                        "category": "资金流",
                        "severity": "low",
                        "description": "MCP 资金数据缺失，不能确认盘后资金方向。",
                        "source": "mcp__tdx",
                    },
                ],
                "observations": ["观察公告回复、量能和行业新闻是否形成交叉验证。"],
                "data_limitations": ["缺少完整研报和社交舆情样本。"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_native.research",
            "--codes",
            "600519",
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
    assert "## 阶段执行状态" in content
    assert "## 数据质量" in content
    assert "技术面" in content
    assert "mcp_realtime" in content
    assert "数据块 news 状态 partial" in content
    assert "监管（medium）" in content
    assert "观察公告回复、量能和行业新闻是否形成交叉验证" in content
    assert "缺少完整研报和社交舆情样本" in content
    assert "实时行情、F10、资金、板块需由 Codex 调用 MCP 或 skills 补齐" not in content
    assert "新闻、公告、研报和社交舆情未由 CLI 自动拉取" not in content
    assert "本地通达信日线可能缺少盘中更新、实时资金、板块归因或最新 F10 信息" not in content
    assert "partial、stale、fetch_failed 数据块需降低结论置信度" in content
    for forbidden in ("买入", "卖出", "加仓", "减仓", "仓位比例", "止损"):
        assert forbidden not in content


def test_cli_generates_private_intelligence_appendix_and_quality_card(tmp_path: Path) -> None:
    db_path = _build_ranker_db_fixture(tmp_path)
    output_dir = tmp_path / "reports"
    context_path = tmp_path / "context.json"
    context_path.write_text(
        json.dumps(
            {
                "data_quality": [
                    {"block": "realtime_quote", "status": "available", "source": "mcp__tdx.symbol_info"},
                    {"block": "research_report", "status": "partial", "source": "report-search"},
                    {"block": "fund_flow", "status": "fetch_failed", "source": "mcp__tdx.symbol_zjlx"},
                ],
                "evidence": [
                    {
                        "kind": "verified_fact",
                        "source_type": "announcement",
                        "title": "公司披露经营进展",
                        "summary": "公告披露项目进展，仍需跟踪落地节奏。",
                        "source": "巨潮资讯",
                        "published_at": "2026-06-05",
                    }
                ],
                "intelligence_items": [
                    {
                        "source_group": "小牛研报纪要",
                        "group_id": "15555851111822",
                        "topic_id": "private-1",
                        "title": "PCB 目标价强call线索",
                        "summary": "纪要称该公司是核心受益标的，并出现买入和加仓讨论。",
                        "tags": ["#逻辑精选#"],
                        "attachments": ["private-note.pdf"],
                        "matched_symbols": ["沪电股份"],
                        "matched_sectors": ["PCB"],
                        "verification_status": "needs_verification",
                        "source_policy": "private_intelligence_only",
                        "source_risk": "medium",
                        "suggested_section": "market_rumor",
                    }
                ],
                "data_limitations": ["缺少完整社交舆情样本。"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_native.research",
            "--codes",
            "600519",
            "--phase",
            "postmarket",
            "--daily-db",
            str(db_path),
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
    appendix_path = paths[0].with_name(paths[0].stem + "_appendix.md")
    assert appendix_path.exists()

    content = paths[0].read_text(encoding="utf-8")
    appendix = appendix_path.read_text(encoding="utf-8")
    assert "## 研究质量卡" in content
    assert "## 私域情报摘要" in content
    assert appendix_path.name in content
    assert "private-1" not in content
    assert "小牛研报纪要" not in content
    assert "ranker-db:<redacted>" in content
    assert str(db_path) not in content
    assert "## 私域情报索引" in appendix
    assert "topic_id=private-1" in appendix
    assert "private-note.pdf" in appendix
    assert "[动作词已屏蔽]" in appendix
    for forbidden in ("买入", "卖出", "加仓", "减仓", "仓位比例", "止损", "目标价", "核心受益标的", "强call"):
        assert forbidden not in content
        assert forbidden not in appendix


def test_cli_generates_markdown_report(tmp_path: Path) -> None:
    tdx_dir = _build_tdx_fixture(tmp_path)
    output_dir = tmp_path / "reports"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_native.research",
            "--codes",
            "600519",
            "--phase",
            "postmarket",
            "--tdx-dir",
            str(tdx_dir),
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    paths = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip().endswith(".md")]
    assert len(paths) == 1
    assert paths[0].exists()
    content = paths[0].read_text(encoding="utf-8")
    assert "# Codex Native A股研究报告" in content
    assert "贵州茅台（600519）" in content
    assert "postmarket" in content


def test_docs_document_codex_orchestration_rules() -> None:
    doc_path = Path(__file__).resolve().parents[1] / "docs" / "codex-native.md"
    content = doc_path.read_text(encoding="utf-8")

    assert "mcp__tdx" in content
    assert "mcp__tdx_official.tdx_wenda_quotes" in content
    assert "news-search" in content
    assert "公告" in content
    assert "研报" in content
    assert "Python 侧不直接调用 Codex 内部工具" in content
    assert "不输出直接操作动作" in content
    assert "available / partial / stale / missing / fetch_failed / not_supported" in content
    assert "--context-json" in content
    assert "研究质量卡" in content
    assert "_appendix.md" in content
    assert "本地绝对路径" in content


def test_framework_lessons_doc_records_agent_boundaries() -> None:
    doc_path = Path(__file__).resolve().parents[1] / "docs" / "codex-native-framework-lessons.md"

    content = doc_path.read_text(encoding="utf-8")

    assert "src/agent/" in content
    assert "src/market_analyzer.py" in content
    assert "技术面 → 情报面 → 风险面 → 综合结论" in content
    assert "数据质量" in content
    assert "风险清单" in content
    assert "不迁移旧 LiteLLM/OpenAI-compatible Agent loop" in content
    assert "不输出买卖动作、仓位比例、狙击点、止损价" in content
