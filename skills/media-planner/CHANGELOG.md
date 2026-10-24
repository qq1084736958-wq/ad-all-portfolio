# Change Log — Media Planner Skill

本文件记录所有策略引擎和工作流的修改，谁改了什么、为什么改。

---

## v1.9.1 (2026-09-21)

### 修复的逻辑缺陷

| 修改 | 原因 | 文件 |
|------|------|------|
| 加 `audience_budget_alignment()` | E2 人群占比悬空，不驱动预算 | strategy_engines.py |
| 加默认 CPM 降级路径 | E3 搜索不到 CPM 直接报错 | strategy_engines.py + platform-cpm-defaults.json |
| prior_profile 移到配置文件 | E4 硬编码在代码里 | strategy_engines.py + phase-prior-profiles.json |
| LLM 调整改为精确 delta | 旧逻辑归一化稀释了 ±5pp 调整效果 | strategy_engines.py |
| E6 KPI 加 CPM 降级 | compute_kpi 无证据直接报错 | strategy_engines.py |
| 加 `normalize_budget()` | 预算口径不统一（含税/不含税） | strategy_engines.py |
| 加 `audience_overlap_check()` | 人群重叠不检查 | strategy_engines.py |
| 加 `currency_convert()` | 币种不统一（CPM USD vs 本地货币） | strategy_engines.py |
| 加 `suggest_budget()` | 客户没给预算时无建议 | strategy_engines.py |
| 加 `client_confirmed_shares` 优先级 | 客户 confirmed 应该跳过公式 | strategy_engines.py |
| 加跨源冲突合并 `merge_parsed_briefs()` | 多来源字段不一致要人工发现 | brief_parser.py |
| 加 `assemble.py` 桥接层 | 策略输出 → Excel 数据格式无桥 | scripts/assemble.py |

### 新增命令（plan_core.py）

- `audience-alignment` — 人群预算对齐校验
- `audience-overlap` — 人群重叠检查
- `normalize-budget` — 预算口径换算
- `currency-convert` — 币种换算
- `suggest-budget` — 预算建议

---

## v1.9.0 (2026-09-20)

### 策略引擎数据驱动化

- 加 `compute_weights()` — E2/E3/E4 权重公式脚本化
- 加 `compute_kpi()` — E6 KPI 可行性预估脚本化
- 加 `weights_must_be_script_derived` gate
- 加 `kpi_must_be_script_derived` gate

### 适配器内化

- 7 个适配器内化到 `references/adapters/`
- lark-doc / lark-base / lark-sheets / doubao-pdf / search / file-delivery / image-processing

### 回环纪律

- 反馈回路优先 / 最小化复现 / 假设排序 / 可证伪预测

---

## v1.8.x 及更早

（略）
