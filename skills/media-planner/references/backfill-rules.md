# 已有 MP 安全回填链路规范

> 本文件定义路由 B（`existing_mp_update`）的完整子链路规范，包括各节点职责、
> 读写隔离原则、Mapping 沉淀格式、patch 校验规则、写后校验和回滚策略。
> **可独立迭代，不影响新建 MP 主链路（路由 A）。**
> 文件版本：v2.1.0 | 2026-09-15

---

## 核心设计原则

### 原文件永不修改

resolver（mp-backfill.py）全程操作临时副本。只有校验通过后才产出新文件。原文件天然是回滚点，无需额外备份。P0 不引入多快照。

### 读写隔离（参考 gl-reconciler reader/resolver 模式）

| 节点 | 接触原始文件 | 写权限 | 说明 |
|------|------------|--------|------|
| **mp-reader**（解析层） | ✅ 只读 | ❌ 无 | 唯一接触用户上传 MP 的节点 |
| **主 Agent**（critic 角色） | ❌ | ❌ | 读 Mapping + 用户需求 → 生成 patch.json |
| **validate_patch()**（独立校验器） | ✅ 只读（核对 hash / old_value） | ❌ 无 | 确定性规则校验，不依赖 Agent 自检 |
| **mp-backfill**（写入层） | ✅ 只读（打开原文件核对） | ✅ 只写副本 | 不接触原始 MP 写路径，只写输出副本 |

### Mapping 是唯一事实源

JSON Mapping 由 mp-reader.py 生成，是所有写入决策的依据。`mapping_summary.md` 由 JSON 自动渲染，供人工审阅，**不维护两份可编辑规则**。

---

## 子链路流程

```
用户上传原 MP + 变更要求
 ↓
Step B-1  mp-reader.py --input <mp.xlsx> --output mapping.json [--summary mapping_summary.md]
  - 提取 Sheet 结构、表头、数据区、writable_ranges、protected_ranges
  - 识别合并单元格（含左上角，所有格均记录）
  - 识别候选预算区，生成 budget_checks（含 budget_check_id）
  - 生成 mapping_id = hash 前 8 位 + 时间戳
  - 输出经 validate_mapping() schema 校验的 Mapping JSON
  - 可选生成 mapping_summary.md（供人工审阅，由 JSON 渲染，不可编辑）
 ↓
Step B-2  主 Agent 读 Mapping + 用户变更要求 → 生成 patch.json
  - 写入目标必须引用 Mapping 已知的 sheet_name + writable_ranges 列
  - 必须填写 expected_old_value（防盲写）
  - 预算校验引用 budget_check_id，不传坐标
  - operation 只允许 set_value（P0 白名单）
 ↓
Step B-3  validate_patch()（独立确定性校验，写入前执行）
  - mapping_id 一致
  - source_workbook_hash 与原文件实际 hash 一致
  - 所有 target 在 writable_ranges 内
  - 所有 target 不在 protected_ranges 内
  - 合并格仅允许 Mapping 明确声明的左上角输入格
  - expected_old_value 与原文件实际值一致
  - budget_check_ids 全部在 Mapping.budget_checks 中存在
  → 任一不通过 → BLOCK，不执行写入
 ↓
Step B-4  mp-backfill.py 在临时副本上应用 operations
  - 原文件只读打开（用于校验），副本单独操作
 ↓
Step B-5  verify_post_write() 写后校验
  - 预算守恒（按 budget_check_ids 引用预定义区，误差 ≤ tolerance）
  - Sheet 名称与顺序不变
  - 合并单元格结构与原文件完全一致（任何变动 → BLOCK）
  - 原有公式与样式不变
  - set_value target 格均有值（非空）
  → BLOCK → 删除副本，输出问题清单，原文件不动
  → PASS/WARN → 产出新文件，原文件不动
 ↓
Step B-6  差异输出
  - 每个 operation 的 before/after/field_status
```

---

## Mapping JSON 关键字段说明（v2.1）

```json
{
  "schema_version": "2.0",
  "mapping_id": "mapping_a1b2c3d4_20260910T032000Z",
  "source_file": "client_mp_2026Q3.xlsx",
  "source_workbook_hash": "sha256 完整 hash",
  "parsed_at": "2026-09-10T03:20:00Z",
  "sheet_count": 9,
  "sheets": [
    {
      "sheet_name": "Budget",
      "purpose_hint": "budget",
      "header_row": 2,           // 0-based
      "data_start_row": 3,       // 0-based，header 下一行
      "data_end_row": 25,        // 0-based，最后非空行
      "col_count": 8,
      "columns": [
        {
          "col_letter": "C",
          "header_value": "Budget (USD)",
          "detected_format": "currency",
          "is_formula": false,
          "is_header": false,
          "sample_values": ["50000", "30000", "20000"]
        }
      ],
      "merged_cells": [
        {"range": "A1:H1", "top_left_value": "2026 Q3 Media Plan"}
      ],
      "merged_cell_refs": ["A1","B1","C1","D1","E1","F1","G1","H1"],  // 所有合并格
      "writable_ranges": [
        {
          "col_letter": "C",
          "row_start": 4,       // 1-based
          "row_end": 25,        // 1-based
          "expandable": false,
          "header_value": "Budget (USD)",
          "detected_format": "currency",
          "allow_merged_top_left": false
        }
      ],
      "protected_ranges": [
        {"range": "A1:H3", "reason": "header_and_above"},
        {"range": "A1:H1", "reason": "merged_cell_range"},
        {"range": "D4:D4", "reason": "formula_cell"}
      ],
      "budget_checks": [
        {
          "budget_check_id": "budget_Budget_C_26",
          "sheet_name": "Budget",
          "total_cell": "C26",
          "detail_range": "C4:C25",
          "currency_hint": "currency",
          "excluded_rows": [],
          "tolerance": 0.01
        }
      ]
    }
  ],
  "budget_checks": [...],  // 顶层汇总，方便 patch 查找
  "format_conventions": {
    "currency_symbol": "USD",
    "date_format_hint": "YYYY-MM-DD",
    "percent_as_decimal": true
  },
  "warnings": []
}
```

---

## patch.json 格式（v2.1）

```json
{
  "patch_id": "patch_20260910_budget_update",
  "description": "调整指定渠道预算",
  "requested_by": "user_or_system_id",
  "mapping_id": "mapping_a1b2c3d4_20260910T032000Z",
  "source_workbook_hash": "实际文件 SHA-256",
  "operations": [
    {
      "sheet_name": "Budget",
      "target": "C18",
      "expected_old_value": 50000,
      "new_value": 60000,
      "operation": "set_value",
      "field_status": "confirmed",
      "confirmation_owner": "user_or_system_id"
    }
  ],
  "budget_check_ids": ["budget_Budget_C_26"],
  "budget_expectations": {
    "budget_Budget_C_26": 60000
  }
}
```

`budget_expectations` 仅用于模板总额格是公式、且原文件没有可信缓存值的情况。
值必须来自已确认总预算或确定性预算分配结果，不能由回填器自行猜测。

---

## patch 校验规则（独立确定性，validate_patch()）

| 校验项 | BLOCK 条件 |
|--------|-----------|
| patch schema 必填字段 | 缺少 patch_id / mapping_id / source_workbook_hash / operations |
| mapping_id 一致 | patch.mapping_id ≠ Mapping.mapping_id |
| source_workbook_hash 一致 | patch 记录的 hash ≠ 原文件实际 SHA-256（文件已被修改） |
| operation 白名单 | operation ≠ set_value（P0 只允许 set_value） |
| sheet_name 已知 | 不在 Mapping.sheets 中 |
| target 在 writable_ranges 内 | 不在任何 writable_range 的列+行范围内 |
| target 不在 protected_ranges 内 | 在任何 protected_range 内 |
| 合并格写入授权 | target 位于合并格，且不是 `allow_merged_top_left=true` 的左上角 |
| expected_old_value 核对 | 与原文件实际值不一致（单元格已被人工修改） |
| field_status 合法 | 不在 confirmed/derived/recommended/defaulted 中 |
| confirmed 有 confirmation_owner | field_status=confirmed 时缺少 |
| budget_check_ids 已知 | 不在 Mapping.budget_checks 中 |
| budget_expectations 合法 | ID 未知，或预算总额不是非负数值 |

---

## 写后校验规则（verify_post_write()）

| 校验项 | 等级 | 说明 |
|--------|------|------|
| 预算守恒 | BLOCK | total_cell 非公式格时：总预算 = 明细之和；是公式格时：用 expected_total 对比明细之和；无法取得可信总额 → BLOCK，不降级为 WARN |
| Sheet 结构完整 | BLOCK | Sheet 名称或顺序发生变化 |
| 合并单元格结构完整 | BLOCK | 新文件合并范围与原文件完全一致 |
| 公式完整 | BLOCK | 任一原有公式新增、删除或改变 |
| 样式完整 | BLOCK | 任一原有单元格样式改变 |
| set_value target 非空 | WARN | 回填后目标格有值 |

---

## key_cells 行语义规范（v2.1 新增）

mp-reader.py 在每个 Sheet 的数据区逐行分析，生成 `key_cells` 列表，每行包含：

| 字段 | 说明 |
|------|------|
| `row_num` | 1-based 行号 |
| `row_type` | `data` / `total` / `header` / `note` / `template` / `empty` |
| `first_col_value` | 第一列值（行主键标识，如产品名/平台名/阶段名） |
| `is_formula_row` | 该行任意格是否含公式（来自 data_only=False 读取） |
| `editable_by_status` | 允许写入的 field_status 列表 |

**row_type → editable_by_status 映射（确定性规则）**：

| row_type | editable_by_status | 说明 |
|----------|-------------------|------|
| `data` | `["confirmed", "derived", "recommended", "defaulted"]` | 正常业务数据行 |
| `total` | `[]` | 合计/汇总行，禁止写入（通常为公式，不得手动覆盖） |
| `header` | `[]` | 表头行，禁止写入 |
| `note` | `["confirmed"]` | 备注行，只允许客户确认值写入 |
| `template` | `["confirmed", "derived", "recommended", "defaulted"]` | 已设置格式的模板预留输入行 |
| `empty` | `[]` | 空行，禁止写入（用途不明） |

**validate_patch() 校验逻辑**：
- target 行 `row_type ∈ {total, header, empty}` → `editable_by_status=[]` → BLOCK
- target 行 `field_status` 不在 `editable_by_status` 中 → BLOCK
- 示例：向 total 行写入 `field_status=derived` → BLOCK（合计行禁止任何写入）

## 合并单元格处理规则

- `merged_cell_refs` 记录合并区域内**所有格**（含左上角）
- 默认不允许向合并格写入。
- 对封面等确定性的键值输入区，mp-reader 可在对应 writable_range 上声明
  `allow_merged_top_left=true`；此时只允许写合并区域左上角，内部格仍 BLOCK。
- 写后校验时，新旧文件的合并结构必须完全一致，任何变动 → BLOCK

---

## 降级策略

| 场景 | 处理方式 |
|------|---------|
| mp-reader 无法识别表头行 | 整张表标为 protected，Agent 须人工确认后手动补充 writable_ranges |
| source_workbook_hash 不匹配 | BLOCK，提示重新运行 mp-reader.py 生成新 Mapping |
| expected_old_value 不匹配 | BLOCK，提示单元格已被人工修改，需用户确认 |
| 预算守恒失败 | BLOCK + 删除副本，调用 allocate_budget_no_error() 重算 |
| 合并结构变化 | BLOCK + 删除副本 |
| WARN 级别 | 继续产出，在输出中显式标注风险 |

---

## 与现有链路的关系

| 节点 | 关系 |
|------|------|
| 阶段 6.2 Preflight | 回填前复用：确认 patch 数据符合业务约束和字段状态规范 |
| 成品校验 | 回填后复用：Sheet 完整性、预算、公式、样式和差异 |
| 责任节点回环 | BLOCK 且可自动修复时，仅重跑安全回填或确定性计算节点 |
| 字段状态元数据 | patch.operations 每条必须携带 field_status；confirmed 还需 confirmation_owner |
| 置信与证据 | 回填数据若来自外部搜索，仍需记录证据评分，不因“已回填”而豁免 |

---

## 文件变更汇总

| 文件 | 版本 | 动作 |
|------|------|------|
| `scripts/mp-reader.py` | v2.1.0 | 增加通用用途识别、精确公式格保护、模板预留行和安全合并输入格 |
| `scripts/mp-backfill.py` | v2.1.0 | 增加安全合并左上角与公式、样式、Sheet 结构写后校验 |
| `references/backfill-rules.md` | v2.1.0（本文件） | 更新 |
| `SKILL.md` | v1.1.0 | 通用 Media Planner 三路由与双工作簿交付规范 |

---

*文件版本：v2.1.0 | 更新时间：2026-09-15*
*设计参考：anthropic/financial-services gl-reconciler（reader/critic/resolver 三段式架构）*
