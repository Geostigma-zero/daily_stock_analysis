# Serenity Skill Usage

`serenity-skill` is installed as a project-level skill for intelligence research only. It must not change or bypass the trading-discipline system.

## Allowed Scope

Use `serenity-skill` only for:

- 产业链拆解
- 供应链瓶颈识别
- 紫苏叶 / 瓶颈候选挖掘
- 公告 / 财报 / 客户 / 产能 / 涨价 / 风险核验
- 输出研究候选清单

The expected output is a source-backed research candidate list, evidence chain, risk checklist, and next verification path.

## Forbidden Scope

`serenity-skill` must not:

- 输出直接买入 / 卖出指令
- 盘中临时放行交易
- 修改交易纪律系统规则
- 自动生成盘前交易计划
- 访问券商、钱包、账户、交易执行系统或本地密钥
- 修改全局 Codex 规则、交易纪律文件、策略规则、下单模板或券商配置

If a prompt asks for a trade action, convert the response into research-priority language:

```text
我只能输出产业链瓶颈研究候选清单和核验路径，不能给出买入/卖出指令或放行交易。
```

## How To Call

Use explicit prompts so the skill stays scoped:

```text
用 serenity-skill 做 A 股机器人产业链瓶颈研究，输出研究候选清单和核验路径。
```

```text
用 serenity-skill 拆解 AI 电力链，找供应链瓶颈和紫苏叶候选，不要生成交易计划。
```

```text
用 serenity-skill 核验某家公司是否真的卡在产业链瓶颈：查公告、财报、客户、产能、涨价和风险。
```

## Output Interface

When file output is needed, use:

```text
outputs/serenity_candidates/YYYY-MM-DD_主题_候选清单.md
```

This file is a research artifact. It is not a trading plan and cannot be used to relax trading rules.
