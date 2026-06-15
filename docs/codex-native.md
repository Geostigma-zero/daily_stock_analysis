# Codex Native A 股研究工作流

`codex_native` 是一个面向 Codex 的轻量研究入口，不替代现有 Web/API 主链路。它只做三件事：读取本地历史日线、计算基础指标、生成 Markdown 研究报告骨架。单股研究优先只读 `a_share_ranker` 共享行情库；读不到时可回退到本地通达信 `.day` 文件。

## 运行方式

推荐先配置 `a_share_ranker` 共享行情库路径：

```bash
set A_SHARE_RANKINGS_DB=E:\workspace\a_share_ranker\data\a_share_rankings.sqlite
```

生成单股报告：

```bash
python -m codex_native.research --codes 600519,300750 --phase auto --daily-db "%A_SHARE_RANKINGS_DB%"
```

也可以配置通达信根目录作为单股 fallback 和大盘指数日线来源：

```bash
set TDX_LOCAL_DIR=<your_tdx_root>
```

用本地通达信生成单股报告：

```bash
python -m codex_native.research --codes 600519,300750 --phase auto --tdx-dir "%TDX_LOCAL_DIR%"
```

`--daily-db` 默认读取 `A_SHARE_RANKINGS_DB`，`--tdx-dir` 默认读取 `TDX_LOCAL_DIR`。两者都配置时，单股研究优先读 `daily_prices`，缺失或读取失败再回退本地通达信。默认输出到 `reports/codex_research/`，可用 `--output-dir` 或 `CODEX_RESEARCH_REPORT_DIR` 覆盖。`--phase` 支持 `auto`、`premarket`、`intraday`、`postmarket`。

Codex 从 MCP / skills / 新闻搜索整理出的个股补充数据可以先保存为 JSON，再传入：

```bash
python -m codex_native.research --codes 600519 --phase postmarket --daily-db "%A_SHARE_RANKINGS_DB%" --context-json path/to/context.json
```

单股研究报告会在正文前部输出“研究质量卡”，展示阶段口径、数据质量状态、降级/缺失块、公开证据数和私域情报附录状态。主报告不会暴露本地绝对路径，`a_share_ranker` 共享库和本地通达信路径会显示为 `ranker-db:<redacted>` / `tdx-local:<redacted>` 或稳定逻辑来源名。若 `context-json` 包含 `intelligence_items`，主报告只展示“私域情报摘要”，并在同目录旁路生成同时间戳 `_appendix.md`，保存 topic 索引、短摘要和附件文件名；未经二次核验的私域情报不会逐条展开进主报告，也不会写入“已验证事实”。

生成 A 股大盘盘后复盘：

```bash
python -m codex_native.market_review --phase postmarket --tdx-dir "%TDX_LOCAL_DIR%"
```

默认输出到 `reports/codex_market_review/`，可用 `--output-dir` 或 `CODEX_MARKET_REVIEW_REPORT_DIR` 覆盖。默认指数为上证指数、深证成指、创业板指、沪深300、中证500、中证1000、科创50。报告标题会随 `--phase` 变化：`premarket` 为盘前观察，`intraday` 为盘中复盘，`postmarket` 为盘后复盘；所有报告都会在正文前部输出“报告质量卡”，用于展示覆盖分、降级块和私域情报附录状态。

Codex 从 MCP / skills / 新闻搜索整理出的补充数据可以先保存为 JSON，再传入：

```bash
python -m codex_native.market_review --phase postmarket --tdx-dir "%TDX_LOCAL_DIR%" --context-json path/to/context.json
```

如果 `context-json` 包含 `intelligence_items`，主报告只展示“私域情报摘要”，并在同目录旁路生成同时间戳 `_appendix.md`。附录保存 topic 索引、短摘要和附件文件名，供个人研究追溯；未经二次核验的私域情报不会逐条展开进主报告，也不会写入“已验证事实”。

需要强制校验大盘复盘必查块时，增加：

```bash
python -m codex_native.market_review --phase postmarket --tdx-dir "%TDX_LOCAL_DIR%" --context-json path/to/context.json --strict-context
```

生成小牛研报纪要情报早报/晚报：

```bash
python -m codex_native.zsxq_intelligence --session premarket --date YYYYMMDD --context-json reports/zsxq_intelligence/context_YYYYMMDD_premarket_xiaoniu.json
python -m codex_native.zsxq_intelligence --session evening --date YYYYMMDD --context-json reports/zsxq_intelligence/context_YYYYMMDD_evening_xiaoniu.json
```

默认输出到 `reports/zsxq_intelligence/`。建议由 Codex 自动化任务在交易日 `08:45` 生成盘前情报、`22:30` 生成晚间情报。盘前默认采集窗口为“上次晚间报告结束时间到当前运行时间”；若没有晚间报告记录，则用“前一交易日 `22:30` 到当前运行时间”。晚间默认采集窗口为 `15:00-22:30`，或“上次盘前报告结束时间到当前时间”；只有用户明确要求“全日归档”时才采集 `00:00-当前时间`。采集侧使用 `zsxq-cli group +topics --limit 30 --json --group-id 15555851111822` 只读拉取，并通过 `--end-time` 翻页直到早于本次采集窗口；`intelligence_items` 保留窗口内全部主题，标签只用于报告优先级和分区。知识星球「小牛研报纪要」固定 `group_id=15555851111822`，内容只作为私人情报线索，不是直接事实源；进入个股或大盘报告前必须用公告、新闻、研报、MCP/问财等来源二次核验。

小牛研报纪要情报报告拆成主报告和附录。主报告 `YYYYMMDD_session_xiaoniu.md` 只放“情报扫描总览”“主题簇摘要”“今日/次日主线”“重点行业/个股”“低置信舆情”和“数据缺口”，优先控制阅读长度；附录 `YYYYMMDD_session_xiaoniu_appendix.md` 放完整附件清单、全量条目索引和可注入 context 摘要。全量索引只列时间、topic_id、标签和标题，用于证明采集窗口内主题已过一遍；正文不转载付费全文。

报告展示层会做确定性降噪，但不会删除或改写原始 `intelligence_items`。标签分布只统计白名单标签（如 `#文字观点#`、`#纪要文档#`、`#外资研报#`、`#财联社#`、`#逻辑精选#`、`#脱水研报#`、`#市场段子#`、`#出处未知#`），正文误识别的长句 `#...#` 不进入主报告标签分布；重点个股会过滤纯数字、纯英文 ticker 噪声和行业泛词，`机器人` 等歧义词放入“歧义标的/行业词”。若需要回退到旧口径，可恢复 `codex_native.zsxq_intelligence` 的单文件渲染逻辑和对应 skill 文档。

个股和大盘复盘共用轻量 `context-json`。它可包含：

```json
{
  "coverage": [
    {"block": "index_quotes", "status": "available", "source": "tdx-local"},
    {"block": "breadth", "status": "available", "source": "mcp__tdx_official"},
    {"block": "turnover", "status": "available", "source": "mcp__tdx_official"},
    {
      "block": "real_time_funds",
      "status": "fetch_failed",
      "source": "mcp__tdx.symbol_zjlx",
      "missing_fields": ["主力资金", "北向/外资口径", "ETF/融资融券"],
      "notes": "资金工具未返回可用数据"
    },
    {"block": "sector_strength", "status": "available", "source": "mcp__tdx_official"},
    {"block": "news_sentiment", "status": "partial", "source": "news-search"}
  ],
  "tool_attempts": [
    {
      "tool": "mcp__tdx.symbol_zjlx",
      "query": "A股大盘主力资金",
      "status": "fetch_failed",
      "error": "schema validation failed",
      "fallback": "仅使用成交额，不把成交额当作实时资金。"
    }
  ],
  "stage_status": [
    {"stage": "技术面", "status": "available", "source": "tdx-local", "notes": "本地日线已读取"}
  ],
  "data_quality": [
    {"block": "news", "status": "partial", "source": "news-search", "notes": "只覆盖盘后新闻"}
  ],
  "breadth": {"上涨家数": "3200", "下跌家数": "1800"},
  "sectors": ["半导体", "光通信"],
  "funds": {
    "turnover": {"沪市成交额": "1.26万亿元", "深市成交额": "1.52万亿元"},
    "main_flow": {"主力资金": "未取得"},
    "northbound": {"北向/外资口径": "未取得"}
  },
  "evidence": [
    {
      "kind": "verified_fact",
      "source_type": "announcement",
      "title": "交易所发布指数样本调整公告",
      "summary": "公告披露指数样本定期调整信息。",
      "source": "交易所公告",
      "published_at": "2026-06-05"
    }
  ],
  "collection_coverage": {
    "window_start": "2026-06-10 08:00:00+0800",
    "window_end": "2026-06-10 23:30:00+0800",
    "source": "zsxq-cli group +topics",
    "fetched_topics": "120",
    "kept_topics": "120"
  },
  "intelligence_items": [
    {
      "source_group": "小牛研报纪要",
      "group_id": "15555851111822",
      "topic_id": "123456",
      "title": "星球主题标题",
      "summary": "短摘要，不粘贴全文。",
      "tags": ["#逻辑精选#"],
      "attachments": ["附件文件名.pdf"],
      "matched_symbols": ["沪电股份"],
      "matched_sectors": ["PCB"],
      "verification_status": "needs_verification",
      "source_policy": "private_intelligence_only",
      "source_risk": "medium",
      "suggested_section": "logical_inference"
    }
  ],
  "source_policy": {"group_name": "小牛研报纪要", "policy": "private_intelligence_only"},
  "matched_symbols": ["沪电股份"],
  "matched_sectors": ["PCB"],
  "verification_status": "needs_verification",
  "source_risk": "medium",
  "risk_items": [
    {"category": "行业政策", "severity": "medium", "description": "需关注盘后政策消息。", "source": "news-search"}
  ],
  "observations": ["观察指数、量能和消息面是否交叉验证。"],
  "data_limitations": ["未取得完整逐笔成交与北向实时拆分数据。"]
}
```

数据质量状态统一为 `available / partial / stale / missing / fetch_failed / not_supported`。所有非 `available` 状态会进入报告“数据缺口”。
大盘复盘中，“成交额”和“实时资金”必须分开：成交额不是实时资金，不能替代主力资金、北向/外资、ETF/融资融券。

## 数据边界

- 单股历史 K 线：优先只读 `a_share_ranker` 共享行情库 `daily_prices`（`trade_date/code/open/close/high/low/volume/amount/adj_close/source`）；若未配置或缺失，再读取本地通达信 `vipdoc/*/lday/*.day`。
- 大盘指数：不使用 `a_share_ranker` 股票行情库，避免 `000001` 等代码与股票冲突。指数日线可读取本地通达信 `sh000001`、`sz399001`、`sz399006`、`sh000300`、`sh000905`、`sh000852`、`sh000688` 等指数文件，指数实时行情、涨跌家数、成交额和板块强弱可由 Codex 通过同花顺/ifind skills 或通达信 MCP 写入 `context-json`。
- 股票名称：读取本地通达信 `T0002/hq_cache/*.tnf`，北交所可补读 `addedcode_bj.cfg`。
- 复权事件：若本地存在 `T0002/hq_cache/gbbq` 且可用，会尝试读取除权除息事件；缺失时按原始日线计算，并写入“数据缺口”。
- 实时行情：由 Codex 调用本机 `mcp__tdx.symbol_info` 补充。
- F10、财务、资金、板块：由 Codex 优先调用 `mcp__tdx_official.tdx_wenda_quotes` 或相关 skills 补充；若原始 `mcp__tdx` 工具返回空结果或 schema 错误，必须写入“数据缺口”。
- 新闻、公告、研报、社交舆情：由 Codex 使用 `news-search`、公告查询、研报查询、同花顺/问财类 skills 补充。
- 知识星球情报：由 Codex 使用 `a-share-zsxq-intelligence` 拉取小牛研报纪要并写入 `intelligence_items`；Python 只消费 context，不直接调用 `zsxq-cli`。情报日报会基于 `collection_coverage` 或 `source_policy.collection_window_*` 展示采集窗口，缺失时用条目发布时间范围推断；主报告返回路径保持不变，同目录旁路生成 `_appendix.md` 追溯文件。

大盘复盘的涨跌家数、板块强弱、资金和盘后消息同样由 Codex MCP / skills 补充；Python CLI 只消费本地指数日线和可选 `context-json`。

Python 侧不直接调用 Codex 内部工具，也不要求仓库内新增 OpenAI API Key。模型选择由 Codex 当前环境负责。

## 报告口径

报告按证据类别分区：

- 已验证事实
- 市场传闻
- 逻辑推演
- 研究假设
- 风险清单
- 数据质量
- 数据缺口

报告只输出研究结论、证据、风险提示和观察条件，不输出直接操作动作、仓位安排或自动交易纪律。若数据缺失，必须写入“数据缺口”，不得用推测填成确定性结论。

大盘复盘报告额外包含：核心盘面摘要、主要指数表现、技术与量能、板块与题材、观察条件和风险提示。它不替代原项目 Web/API/Bot 大盘复盘，也不负责通知推送或定时任务；这些可以由 Codex 自动化任务在外部编排。
