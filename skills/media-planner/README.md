# media-planner Skill

生成可解释、可追溯、可校验的全渠道 Media Plan。

---

## 部署前置依赖

### ⚠️ 联网搜索（必须由管理员配置）

本 skill 依赖 `web_search` 工具获取行业 KPI 基准、市场数据和渠道规则。该工具需要在 **OpenClaw 服务端**安装搜索插件才能生效。

**配置步骤（管理员操作）：**

在 OpenClaw 插件配置中启用以下任意一个搜索插件：

| 插件 | 说明 |
|------|------|
| DuckDuckGo | 免费，无需 API Key，开箱即用 |
| Brave Search | 需要 API Key |
| Perplexity | 需要 API Key，结果质量较高 |

**未配置搜索插件时的影响：**
- 联网搜索节点会失败，不阻断主流程
- KPI 基准数据降级为模型推断（`directional_only`）
- 市场、渠道、人群数据无法从公网获取，策略质量下降
- 最终交付物中相关字段会标注 `insufficient_evidence`

---

## 文件结构

```
media-planner/
├── SKILL.md                    # 主技能文件
├── README.md                   # 本文件
├── references/                 # 规则与规范文档
│   ├── workflow.md             # 完整节点与回环规则
│   ├── completeness-and-routing.md
│   ├── search-and-evidence.md
│   ├── search-adapters.md
│   ├── strategy-schema.md
│   ├── plan-mode-rules.md
│   ├── backfill-rules.md
│   ├── common-validation.md
│   ├── memory.md
│   ├── data-contract.md
│   ├── outputs-and-validation.md
│   ├── acceptance-scenarios.md
│   ├── MediaPlan_Template_Standard.xlsx
│   └── MediaPlan_Internal_Template.xlsx
├── scripts/                    # 确定性计算与编排脚本
│   ├── plan_core.py
│   ├── workflow_engine.py
│   ├── brief_parser.py
│   ├── generate_mediaplan.py
│   ├── mp-reader.py
│   ├── mp-backfill.py
│   ├── strategy_io.py
│   └── search_adapter.py
├── agents/                     # Agent 配置
├── memory/                     # 记忆系统
└── tests/                      # 验收测试
```

---

## 快速验证

安装完成后，可用以下命令验证环境：

```powershell
# 验证脚本依赖
python scripts/plan_core.py --help

# 运行验收测试
python -m unittest discover -s tests -v
```
