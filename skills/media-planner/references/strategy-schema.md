# strategy JSON 规范

`context['strategy']` 是 `strategy-analysis` 节点的输出，也是 `generate_mediaplan_excel()` 的主要输入。
本文件定义其结构和字段约束。

---

## 顶层结构

```json
{
  "brand":            "品牌名",
  "project_name":     "项目名称",
  "product":          "主推产品",
  "market":           ["US", "UK"],
  "currency":         "USD",
  "total_budget":     100000,
  "campaign_start":   "2026-10-01",
  "campaign_end":     "2026-12-31",
  "total_days":       92,
  "business_goal":    "purchase",
  "summary":          "一句话策略概述",

  "phases":           [...],
  "delivery_units":   [...],
  "audience":         {...},
  "landing_utm":      {...},
  "platform_copy":    [...],
  "risks":            [...],

  "budget_matrix":    {...},
  "engine_outputs":   {...},

  "mp_type":                    { "value": "brand", "field_status": "confirmed", "evidence_refs": [], "reason": "..." },
  "brand_supply_package":       {
    "source_ref": "飞书多维表 URL / 客户交付包",
    "field_status": "confirmed | extracted | partial | missing",
    "creative_inventory": { "assets": [] },
    "copy_inventory": [],
    "landing_inventory": []
  },

  "_meta": {
    "deliverable_status": "draft | final_candidate | final",
    "revision":           1,
    "confirmer":          "确认人姓名或 open_id",
    "updated_at":         "2026-09-15T08:00:00Z"
  }
}
```

---

## engine_outputs（策略引擎中间产物，v1.6 新增）

`strategy-analysis` 节点不再是黑盒：Agent 必须按
（E0 参数清点 → E1 卖点翻译 → E2 受众分层 → E3 平台角色 → E4 阶段里程碑 → E5 预算矩阵 → E6 KPI 分解 → E7 创意策略）
在同一个暂停点内完成推导，每引擎产出一个标准信封块：

```json
"engine_outputs": {
  "usp-inventory":   { "engine": "usp-inventory", "status": "complete", "payload": { } },
  "usp-translation": { },
  "audience-tier":   { },
  "platform-role":   { },
  "phase-milestone": { },
  "budget-matrix":   { },
  "kpi-framework":   { },
  "creative-matrix": { }
}
```

标准信封字段：

| 字段 | 约束 |
|---|---|
| `engine` | 引擎 id |
| `status` | `complete` / `partial` / `not_applicable`；`not_applicable` 必须给 `not_applicable_reason`（preflight WARN 转人工） |
| `assumptions` | `[{assumption, impact: low\|medium\|high}]`，假设进内部风险表 |
| `evidence_refs` | 事实性判断引用的 evidence id / brief source_ref |
| `field_status` | 建议内容默认 `recommended`，用户确认后升 `confirmed`；脚本回写为 `derived` |
| `payload` | 各引擎契约见 E0–E6 输出契约段 |

> **【2026-09 松绑】engine_outputs 不再强制齐全。** 此前要求 new_plan 必须含 usp-inventory/usp-translation/audience-tier/platform-role/phase-milestone/budget-matrix/kpi-framework 七块、缺块 BLOCK——这等于用代码把策略思考流程写死，压垮 LLM 泛化能力（此前正是因此换的 prompt 逻辑）。**现已停用该强制**：`evaluate_engine_output_gates` 调用已注释，上述七块为**可选脚手架**，Agent 按 playbook 开放引导自由推导，不要求凑齐七块、不按固定 E0–E6 顺序。
>
> 保留的只是**算术守恒不变量**（不是思考流程）：
>
> - `budget-matrix.payload.matrix` 必须是 `allocate_matrix` 的原样输出（带 `generated_by` 戳记），
>   并镜像到顶层 `budget_matrix`；LLM 不得手算/手改金额、占比、日期（`numbers_must_be_script_derived`）。
> - `audience-tier.payload.tiers[].proposed_share` 合计 = 1（代码归一）。
> - 差异点卖点翻译建议覆盖全 differentiator、带 source_ref；但"每映射场景 ≥2、话术 ≥2"不再是硬 BLOCK，由 Agent 按市场证据自行把握。
> - 引擎中间表（参数清点、三段映射、矩阵、指标树）是脚手架，存 JSON/进内部审计；
>   只有客户执行所需结果映射到现有对客字段（零新增 sheet）。
>
> `creative-matrix`（E7）：作为**树状排期表的输出格式契约**保留，
> 它规定素材分配表的结构/校验/对接，不规定思考过程；新计划建议产出，但不再以"缺块"硬 BLOCK 思考流程。

---

## mp_type（计划类型，Slice 4 新增）

```json
"mp_type": {
  "value": "brand | performance | hybrid",
  "field_status": "recommended | confirmed",
  "evidence_refs": [],
  "reason": "判定依据一句话"
}
```

- 位置：`context['values']['mp_type']`，material-parsing 提取、completeness-check 复核、strategy-analysis（E7 Step 0）确认。
- 三分类定稿，不设第四类：赞助/代言/资源包断等"客户供素材、目标曝光、代理不制作"的单子归 `brand`（E3 角色可为固定资源位）。
- 判定信号（渠道中立，Brief 明示最强）：素材/文案/落地页供给方（客户全包成品=brand；代理生产=performance；混合=hybrid）、business_goal、KPI 重心。信号冲突不静默选边，进风险表请客户确认。
- **型变规则（唯一灰色出口）**：品牌计划执行中客户提出改尺寸/剪辑/代写文案/制作新素材，不在品牌轨道开口子；发起 mp_type 重判，相关单元或整单改 hybrid/performance → 客户书面确认 → 风险表记录 → revision +1 → 重判部分走效果轨道。未完成重判前制作类动作一律 BLOCK。

---

## brand_supply_package（品牌交付包，Slice 4 新增）

品牌模式（及 hybrid 的上漏斗单元）的输入态工作数据，三部分：成品素材、文案、落地页，均由客户供给。
明细不进对客 9 sheet；接受任意来源格式（飞书多维表、Excel/Google Sheet、附件、粘贴文本），由 material-parsing 归一化。

```json
"brand_supply_package": {
  "source_ref": "飞书多维表 URL / 附件名 / 客户邮件",
  "field_status": "confirmed | extracted | partial | missing",
  "creative_inventory": {
    "assets": [
      {
        "asset_id": "A01",
        "title": "30s TVC 主片",
        "asset_type": "video | image | carousel | copy | other",
        "format_spec": {
          "duration_sec": 30,
          "aspect_ratio": "9:16",
          "dimensions": "1080x1920",
          "file_type": "mp4"
        },
        "is_final_deliverable": true,
        "usp_refs": ["usp_01"],
        "language": "ar",
        "quantity": 1,
        "rights": {"usage_expiry": "2027-09-30", "regions": ["SA"], "status": "confirmed | unknown | expired"},
        "location": "素材链接",
        "source_ref": "素材表第 3 行",
        "field_status": "extracted"
      }
    ]
  },
  "copy_inventory": [
    {"copy_id": "C01", "language": "ar", "product": "Product",
     "intended_platform": "Meta",
     "primary_text": "...", "headline": "...", "description": "...", "cta": "...",
     "source_ref": "..."}
  ],
  "landing_inventory": [
    {"landing_id": "L01", "url": "https://...", "language": "ar",
     "stage": "pre-order", "source_ref": "..."}
  ]
}
```

约束：

- 品牌模式素材 `is_final_deliverable=true`，**尺寸即最终投放尺寸**；不接收"半成品待改编"，非成品视为该版位素材缺失（走索取，不走改编）。
- 最小可用素材字段：asset_type / aspect_ratio / duration_sec（视频）/ quantity / language。
- 整包齐全 → E7 匹配；链接无权限 → 风险表 + ⑤ 开放权限/导出任务；素材/文案/落地页任一缺失 → E7 partial + ⑤ 对应索取任务（`素材索取`/`文案索取`/`落地页索取`），计划只能草案；落地页缺失正式版 BLOCK。
- 效果模式只需 `creative_inventory`（存量可复用素材，允许为空，缺口由生产矩阵覆盖）。

---

## E7 creative-matrix payload（Slice 4 双模式）

payload 骨架：

```json
{
  "mp_type": "hybrid",
  "assignments": [
    {"unit_ref": "META|Launch", "asset_ids": ["A01"], "copy_id": "C01", "landing_id": "L01",
     "ad_format": "Reels Video", "placement": "Feed/Reels",
     "spec_evidence_ref": "evidence_...", "match_rationale": "成品 9:16/15s 落在版位接受区间，usp_01 对齐"}
  ],
  "creative_gaps": [
    {"platform": "YouTube", "phase": "Pre-Buzz",
     "required_spec": {"aspect_ratio": "16:9", "duration_sec_max": 30, "file_type": "mp4"},
     "usp_ref": "usp_02", "reason": "客户成品包无该版位素材",
     "todo_task_ref": "TASK-12", "request_type": "client_supply_final_asset"}
  ],
  "production_matrix": [
    {"usp_ref": "usp_02", "asset_type": "video",
     "required_spec": {"aspect_ratio": "9:16", "duration_sec": 15},
     "platform": "TikTok", "funnel_position": "conversion",
     "quantity": 3, "todo_task_ref": "TASK-13", "rationale": "..."}
  ],
  "testing_plan": {
    "variants_per_cell": [3, 5],
    "triggers": [
      {"metric": "CTR", "condition": "< 同单元/同类均值 50% 持续 48h", "action": "pause_creative", "cadence": "daily", "field_status": "defaulted"},
      {"metric": "frequency", "condition": "> 3", "action": "rotate_creative", "cadence": "daily", "field_status": "defaulted"},
      {"metric": "CPA", "condition": "> 目标 130%", "action": "adjust_bid_or_targeting", "cadence": "daily", "field_status": "defaulted"}
    ],
    "cadence_task_refs": []
  }
}
```

- 三条触发阈值为 `defaulted` 默认值；客户合同或团队标准存在时覆盖默认值并升 `confirmed`。
- brand：只用 assignments + creative_gaps（`request_type` 恒为客户供给成品），production_matrix 必须为空。
- performance：production_matrix + testing_plan 必填，存量成品可复用 assignments。
- hybrid：按 E3 单元 `funnel_position` 分流（awareness/consideration 走品牌规则，conversion/remarketing 走效果规则），不按平台名分流。

---

## phases（投放阶段）

每个阶段对应一段连续投放周期，用于预算分配和日期展开。

```json
{
  "name":        "Phase_Awareness",
  "label":       "品牌曝光期",
  "start_date":  "2026-10-01",
  "end_date":    "2026-10-21",
  "days":        21,
  "budget":      30000,
  "objective":   "awareness"
}
```

**约束**：
- 所有阶段 `budget` 之和 = `total_budget`（由 `plan_core.allocate_budget` 保证）
- `days` = `end_date` - `start_date` + 1（含首尾）
- 阶段连续且不重叠

---

## delivery_units（投放单元）

替代旧字段名 `ad_sets`，对应 Excel ④ MediaPlan Sheet 的每一行。

```json
{
  "channel":      "任意渠道名",
  "nation":       "US",
  "ad_format":    "Video",
  "goal":         "Purchase",
  "product":      "Product A",
  "targeting":    "Audience_A",
  "placement":    "Feed",
  "creative":     "15s 竖屏",
  "field_status": "confirmed",

  "daily_budget_by_phase": {
    "Phase_Awareness": 500,
    "Phase_Conversion": 1200
  },

  "budget_field":       "daily_budget",
  "line_total_display": null
}
```

**reserved_pending 行**（预算待确认的投放单元）：

```json
{
  "channel":            "待确认渠道",
  "budget_field":       "reserved_pending",
  "line_total_display": "待确认预算",
  "field_status":       "recommended"
}
```

**字段约束**：
- `field_status` 必须为 `confirmed` 才能进入正式交付
- `targeting` 值必须与 `audience.rows[].label_name` 对应（cross_sheet_reference 规则）
- `field_status = recommended` → 不得进入正式 MP（preflight BLOCK）

---

## audience（受众画像）

对应 Excel Audience Sheet。

```json
{
  "rows": [
    {
      "label_name":   "Audience_A",
      "description":  "25-44 岁，兴趣：家居",
      "size_estimate": "1M-3M",
      "market":       "US",
      "channel":      "任意渠道"
    }
  ]
}
```

---

## landing_utm（落地页与 UTM）

对应 Excel Landing Page & UTM Sheet。

```json
{
  "rows": [
    {
      "channel":       "任意渠道",
      "landing_url":   "https://example.com/product",
      "utm_source":    "channel_name",
      "utm_medium":    "paid_social",
      "utm_campaign":  "brand_awareness_2026q4",
      "utm_content":   "video_15s",
      "tracking_note": "UTM 追踪 + 第三方数据平台"
    }
  ]
}
```

---

## platform_copy（渠道文案）

对应 Excel 平台文案 Sheet。

```json
[
  {
    "product_name":  "Product A",
    "level":         "产品",
    "primary_text":  "主文案内容",
    "headline":      "标题",
    "description":   "描述",
    "call_to_action": "了解更多"
  }
]
```

---

## KPI 三对象（嵌入 strategy 或独立传入 preflight）

```json
{
  "kpi": {
    "items": [
      {
        "metric":     "ROAS",
        "kpi_target": {
          "value":              3.0,
          "unit":               "x",
          "period":             "campaign",
          "field_status":       "confirmed",
          "confirmation_owner": "用户"
        },
        "kpi_forecast": {
          "lower_bound":        2.5,
          "upper_bound":        4.0,
          "evidence_refs":      ["evidence_id_1"],
          "kpi_forecast_status": "estimated"
        },
        "kpi_recommendation": null
      }
    ]
  }
}
```

---

## generate_mediaplan.py 字段映射关系

| strategy 字段 | Excel Sheet | mapping 文件 |
|---|---|---|
| `brand` / `project_name` / `market` | 封面 Cover | `cover.yaml` |
| `product` / `business_goal` / `total_budget` | ① Brief | `brief.yaml` |
| `summary` / `phases` | ② Summary | `summary.yaml` |
| `phases` + `delivery_units` 策略说明 | ③ Strategy | `strategy.yaml` |
| `delivery_units` + `phases` | ④ MediaPlan（日期展开） | `generate_mediaplan.py` 直接写入 |
| `risks` / `_meta` | ⑤ TO-DO | `todo.yaml` |
| `audience` | Audience | `audience.yaml` |
| `landing_utm` | Landing Page & UTM | `landing_utm.yaml` |
| `platform_copy` | 平台文案 | `platform_copy.yaml`（brand 模式内容来自 copy_inventory，逐字段录入、带 copy_id，不改写不代写） |
| `mp_type` / `brand_supply_package` / E7 产出 | ② C12 前缀、④ C/G/H、⑤、Landing L 列 | 不新增 sheet/列，落位见 E7 节 |

---

## 调用示例

```python
from scripts.generate_mediaplan import generate_mediaplan_excel

generate_mediaplan_excel(
    data=context["strategy"],   # 本规范定义的 dict
    output_path="/tmp/output/Brand_20261001_MediaPlan.xlsx"
)
```

输出：对客工作簿（9 Sheet）。内部工作簿（风险+证据）由 `_workbook_generation` handler 单独生成。
