# Codex Native 旧 Agent 框架沉淀

本文记录从原 `src/agent/`、`src/analyzer.py`、`src/market_analyzer.py` 中保留下来的分析方法论。目标是让 Codex-native 工作流吸收有用结构，但不迁移旧运行时、旧 Web/API/Bot 主链路或自动交易决策。

## 保留的方法论

- 分阶段研究顺序：技术面 → 情报面 → 风险面 → 综合结论。Codex 先读本地通达信日线与指标，再补新闻、公告、研报、舆情、F10、资金和板块，最后只基于已收集证据做综合。
- 数据质量：继承旧 `AnalysisContextPack` 的数据块状态思想，统一使用 `available / partial / stale / missing / fetch_failed / not_supported`。非 `available` 的块必须进入报告“数据缺口”。
- 风险清单：吸收旧 `RiskAgent` 的风险分类，包括监管、业绩、解禁、股东减持、质押、行业政策、估值异常、资金流、技术破位。风险只写为提示和观察影响。
- 深度研究拆解：吸收旧 `ResearchAgent` 的子问题拆解方法。复杂主题按公司基本面、行业景气、催化事件、风险证据、市场预期分开取证。
- 大盘复盘维度：吸收 `src/market_analyzer.py` 中的市场宽度、涨跌家数、成交额、指数表现、强弱板块、风险提示，用于 Codex-native 大盘复盘。
- 最终综合边界：吸收旧综合阶段“只基于前序证据”的原则，不在结论阶段凭空新增事实。

## 融入方式

- Codex 负责调用本机通达信 MCP、已安装 skills、`news-search`、公告和研报查询，并整理成 `context-json`。
- Python 只读取本地通达信数据、解析 `context-json`、计算基础指标、渲染 Markdown。
- 个股和大盘共用轻量上下文结构：`stage_status`、`data_quality`、`evidence`、`risk_items`、`observations`、`data_limitations`。
- 报告中把风险清单和数据质量单独分区，避免把情报、传闻、推演和观察条件混写。

## 不迁移内容

- 不迁移旧 LiteLLM/OpenAI-compatible Agent loop。
- 不迁移旧 Web/API/Bot/scheduler 主链路。
- 不迁移旧交易决策字段，例如 `operation_advice`、`decision_type`、`position_strategy`、`sniper_points`。
- 不输出买卖动作、仓位比例、狙击点、止损价。
- 不把风险清单转成自动交易纪律，也不实现 433、5% 试探仓或违纪记录。

## 验收口径

- 旧框架经验必须沉淀到 Codex skill、文档和报告结构，而不是引入旧 runtime 依赖。
- 所有缺失、过期、失败或部分可用的数据源必须进入“数据缺口”。
- 已验证事实、市场传闻、逻辑推演、交易假设必须分区展示。
- 报告只输出研究证据、风险提示和观察条件。
