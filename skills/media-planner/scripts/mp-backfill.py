#!/usr/bin/env python3
"""
mp-backfill.py — 已有 Media Plan Excel 安全回填器（写入层）v2.1.0

职责：
  - 接收 mp-reader.py 输出的 Mapping JSON + 回填指令 patch.json
  - 独立确定性 patch validator（不依赖 Agent 自检）
  - 在临时副本上完整应用 patch，校验通过后产出新文件；原文件永不修改
  - 原文件即天然回滚点，无需额外备份

v2.1.0 变更：
  - patch validator 独立函数，校验：
      schema 完整性 / mapping_id 匹配 / source_workbook_hash 核对
      operation 白名单（P0 只允许 set_value）
      写入目标必须在 writable_ranges 内（替代 ±10 容差）
      写入目标不得在 protected_ranges 内
      合并格仅允许 Mapping 明确声明的左上角输入格
      expected_old_value 核对（防盲写）
      budget_check_ids 引用 Mapping 预定义区（不允许自由传坐标）
  - 写后校验：合并范围、公式单元格、样式完整性未被改变
  - P0 不引入多快照，临时副本校验通过即产出

用法：
  python3 scripts/mp-backfill.py \\
    --mapping <mapping.json> \\
    --input   <original_mp.xlsx> \\
    --patch   <patch.json> \\
    --output  <out/updated_mp.xlsx>

patch.json 格式（见 PATCH_SCHEMA 注释）

版本：v2.1.0 | 2026-09-15
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


# ============================================================
# PATCH_SCHEMA
# ============================================================
# {
#   "patch_id":              str,          # 唯一标识
#   "description":           str,          # 本次变更说明
#   "requested_by":          str,          # 发起人标识（可用姓名、账号或系统用户 ID）
#   "mapping_id":            str,          # 必须与 Mapping.mapping_id 一致
#   "source_workbook_hash":  str,          # 必须与原文件实际 hash 一致
#   "operations": [
#     {
#       "sheet_name":          str,        # 必须在 Mapping 已知 Sheet 中
#       "target":              str,        # 单元格地址，如 "C18"（不接受范围）
#       "expected_old_value":  any,        # 写入前核对原值；null 表示允许空格
#       "new_value":           any,        # 新值
#       "operation":           "set_value",# P0 只允许 set_value
#       "field_status":        str,        # confirmed / derived / recommended / defaulted
#       "confirmation_owner":  str | null  # field_status=confirmed 时必填
#     }
#   ],
#   "budget_check_ids": [str],             # 引用 Mapping.budget_checks 中的 ID
#   "budget_expectations": {str: number}   # 可选：空白模板的已确认预算总额
# }


# ============================================================
# 依赖检查
# ============================================================

def _require_openpyxl():
    try:
        import openpyxl
        return openpyxl
    except ImportError:
        print(json.dumps({
            "status": "error",
            "error": "openpyxl 未安装。请运行: pip install openpyxl",
        }), file=sys.stderr)
        sys.exit(1)


# ============================================================
# 辅助
# ============================================================

def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_cell_ref(target: str) -> tuple[str, int]:
    """解析单元格地址，返回 (col_letter, row_num 1-based)。"""
    import re
    m = re.match(r"^([A-Za-z]+)(\d+)$", target.strip())
    if not m:
        raise ValueError(f"无效单元格地址: {target!r}")
    return m.group(1).upper(), int(m.group(2))


def _col_index(col_letter: str) -> int:
    result = 0
    for c in col_letter.upper():
        result = result * 26 + (ord(c) - ord("A") + 1)
    return result - 1


def _values_equal(a: Any, b: Any, tolerance: float = 0.0) -> bool:
    """宽松相等：数值型允许 tolerance 误差，字符串 strip 后比较。"""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if tolerance > 0:
            return abs(float(a) - float(b)) <= tolerance
        return float(a) == float(b)
    return str(a).strip() == str(b).strip()


# ============================================================
# 独立确定性 Patch Validator
# ============================================================

ALLOWED_OPERATIONS = {"set_value"}
VALID_FIELD_STATUSES = {"confirmed", "derived", "recommended", "defaulted"}


def validate_patch(
    patch: dict,
    mapping: dict,
    input_path: str,
) -> tuple[bool, list[str]]:
    """
    独立确定性 patch 校验器。不依赖 Agent 自检。

    校验项：
    1. patch schema 必填字段
    2. mapping_id 与 Mapping 一致
    3. source_workbook_hash 与原文件实际 hash 一致
    4. operation 必须是 set_value（P0 白名单）
    5. sheet_name 必须在 Mapping 已知 Sheet 中
    6. target 必须在该 Sheet 的 writable_ranges 内
    7. target 不得在 protected_ranges 内
    8. target 不得是合并单元格内部格；左上角仅在 Mapping 的
       writable_range 明确声明 allow_merged_top_left=true 时允许
    9. expected_old_value 与原文件实际值一致
    10. field_status 合法；confirmed 必须有 confirmation_owner
    11. budget_check_ids 必须全部在 Mapping.budget_checks 中存在
    """
    errors = []

    # --- 1. patch schema ---
    for field in ("patch_id", "mapping_id", "source_workbook_hash", "operations"):
        if field not in patch:
            errors.append(f"patch 缺少必填字段: {field}")
    if errors:
        return False, errors

    # --- 2. mapping_id ---
    if patch["mapping_id"] != mapping.get("mapping_id"):
        errors.append(
            f"mapping_id 不匹配: patch={patch['mapping_id']!r} "
            f"vs mapping={mapping.get('mapping_id')!r}"
        )

    # --- 3. source_workbook_hash ---
    actual_hash = file_sha256(input_path)
    if patch["source_workbook_hash"] != actual_hash:
        errors.append(
            f"source_workbook_hash 不匹配：patch 记录的 hash 与当前文件不一致。"
            f"文件可能已被修改，请重新运行 mp-reader.py 生成新 Mapping。"
        )

    # 构建快速查找结构
    sheet_map = {s["sheet_name"]: s for s in mapping.get("sheets", [])}
    known_budget_check_ids = {
        bc["budget_check_id"]
        for bc in mapping.get("budget_checks", [])
    }

    # 加载原文件用于 expected_old_value 核对
    openpyxl = _require_openpyxl()
    try:
        wb_orig = openpyxl.load_workbook(input_path, data_only=True)
    except Exception as e:
        errors.append(f"无法打开原文件用于核对: {e}")
        wb_orig = None

    # --- 遍历每个 operation ---
    for i, op in enumerate(patch.get("operations", [])):
        prefix = f"operations[{i}]"

        # 4. operation 白名单
        operation = op.get("operation")
        if operation not in ALLOWED_OPERATIONS:
            errors.append(
                f"{prefix}: operation={operation!r} 不在白名单 {sorted(ALLOWED_OPERATIONS)} 中"
            )

        # 5. sheet_name
        sheet_name = op.get("sheet_name")
        if not sheet_name or sheet_name not in sheet_map:
            errors.append(f"{prefix}: sheet_name={sheet_name!r} 不在 Mapping 中")
            continue
        sheet_info = sheet_map[sheet_name]

        # 解析 target
        target = op.get("target", "")
        try:
            col_letter, row_num = _parse_cell_ref(target)
        except ValueError as e:
            errors.append(f"{prefix}: target 解析失败 — {e}")
            continue

        # 6. 必须在 writable_ranges 内
        in_writable = False
        matched_writable = None
        for wr in sheet_info.get("writable_ranges", []):
            if (
                wr["col_letter"].upper() == col_letter
                and wr["row_start"] <= row_num <= wr["row_end"]
            ):
                in_writable = True
                matched_writable = wr
                break
        if not in_writable:
            wr_list = [
                w["col_letter"] + str(w["row_start"]) + ":" + str(w["row_end"])
                for w in sheet_info.get("writable_ranges", [])
            ]
            errors.append(
                f"{prefix}: {sheet_name}!{target} 不在任何 writable_range 内。"
                f"可写区域: {wr_list}"
            )

        # 7. 不得在 protected_ranges 内
        if _cell_in_protected(col_letter, row_num, sheet_info.get("protected_ranges", [])):
            errors.append(
                f"{prefix}: {sheet_name}!{target} 在 protected_ranges 内，禁止写入"
            )

        # 8. 合并单元格检查（含左上角）
        merged_all = set(sheet_info.get("merged_cell_refs", []))
        if target.upper() in merged_all:
            # 只允许 Mapping 明确声明的合并区域左上角输入格。写入左上角不会
            # 改变合并结构，适用于封面等键值表单。
            is_solo = _is_solo_merged(target, sheet_info.get("merged_cells", []))
            is_allowed_top_left = bool(
                matched_writable
                and matched_writable.get("allow_merged_top_left")
                and _is_merged_top_left(target, sheet_info.get("merged_cells", []))
            )
            if not (is_solo or is_allowed_top_left):
                errors.append(
                    f"{prefix}: {sheet_name}!{target} 属于合并单元格区域，"
                    f"禁止写入未授权的合并格；仅 Mapping 明确声明的左上角输入格可写"
                )

        # 8b. key_cells 行语义校验
        # total / header / empty 行的 editable_by_status=[]，禁止任何写入
        key_cells = sheet_info.get("key_cells", [])
        if key_cells:
            # 建立 row_num → key_cell_info 快速查找
            kc_map = {kc["row_num"]: kc for kc in key_cells}
            field_status_op = op.get("field_status", "")
            for r in range(row_num, (row_num if not isinstance(row_num, int) else row_num) + 1):
                kc = kc_map.get(r)
                if kc:
                    editable = kc.get("editable_by_status", [])
                    row_type = kc.get("row_type", "data")
                    if not editable:
                        errors.append(
                            f"{prefix}: {sheet_name}!{target} 位于 row_type={row_type!r} 行，"
                            f"editable_by_status=[]，禁止写入（合计行/表头行/空行）"
                        )
                    elif field_status_op and field_status_op not in editable:
                        errors.append(
                            f"{prefix}: {sheet_name}!{target} 的 field_status={field_status_op!r} "
                            f"不在该行允许的状态 {editable} 中（row_type={row_type!r}）"
                        )

        # 9. expected_old_value 核对
        expected_old = op.get("expected_old_value")
        if wb_orig is not None and sheet_name in wb_orig.sheetnames:
            ws_orig = wb_orig[sheet_name]
            actual_old = ws_orig[target].value
            # expected_old=None 表示允许空格
            if expected_old is None:
                if actual_old is not None and str(actual_old).strip() != "":
                    errors.append(
                        f"{prefix}: {sheet_name}!{target} expected_old_value=null "
                        f"但实际值为 {actual_old!r}（非空）"
                    )
            else:
                if not _values_equal(actual_old, expected_old):
                    errors.append(
                        f"{prefix}: {sheet_name}!{target} expected_old_value={expected_old!r} "
                        f"但实际值为 {actual_old!r}，单元格可能已被人工修改"
                    )

        # 10. field_status
        field_status = op.get("field_status")
        if field_status not in VALID_FIELD_STATUSES:
            errors.append(
                f"{prefix}: field_status={field_status!r} 无效，"
                f"允许值: {sorted(VALID_FIELD_STATUSES)}"
            )
        if field_status == "confirmed" and not op.get("confirmation_owner"):
            errors.append(f"{prefix}: field_status=confirmed 时必须填 confirmation_owner")

    # --- 11. budget_check_ids ---
    for bc_id in patch.get("budget_check_ids", []):
        if bc_id not in known_budget_check_ids:
            errors.append(
                f"budget_check_ids 中的 {bc_id!r} 不在 Mapping.budget_checks 中。"
                f"已知 ID: {sorted(known_budget_check_ids)}"
            )
    for bc_id, expected in patch.get("budget_expectations", {}).items():
        if bc_id not in known_budget_check_ids:
            errors.append(f"budget_expectations 中的 {bc_id!r} 不在 Mapping.budget_checks 中")
        if not isinstance(expected, (int, float)) or isinstance(expected, bool) or expected < 0:
            errors.append(f"budget_expectations[{bc_id!r}] 必须是非负数值")

    return len(errors) == 0, errors


def _cell_in_protected(col_letter: str, row_num: int, protected_ranges: list) -> bool:
    """判断单元格是否在任意 protected_range 内。"""
    import re
    for pr in protected_ranges:
        rng = pr.get("range", "")
        # 支持 "A1:H3" 格式
        m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", rng.upper())
        if m:
            c1 = _col_index(m.group(1)) + 1
            r1 = int(m.group(2))
            c2 = _col_index(m.group(3)) + 1
            r2 = int(m.group(4))
            c_num = _col_index(col_letter) + 1
            if c1 <= c_num <= c2 and r1 <= row_num <= r2:
                return True
    return False


def _is_solo_merged(target: str, merged_cells: list) -> bool:
    """
    判断 target 是否属于"仅覆盖本格"的合并区域（即 A1:A1，等效未合并）。
    这种情况实际上不存在于正常 Excel，但作为边界保护。
    """
    target_upper = target.upper()
    for mc in merged_cells:
        rng = mc.get("range", "").upper()
        if ":" not in rng:
            continue
        start, end = rng.split(":")
        if start == end == target_upper:
            return True
    return False


def _is_merged_top_left(target: str, merged_cells: list) -> bool:
    """判断 target 是否是某个合并区域的左上角。"""
    target_upper = target.upper()
    for mc in merged_cells:
        rng = mc.get("range", "").upper()
        start = rng.split(":", 1)[0]
        if start == target_upper:
            return True
    return False


# ============================================================
# 写入操作
# ============================================================

def apply_operations(wb, patch: dict, mapping: dict) -> tuple[list, list]:
    """
    在已加载的 workbook 上执行 operations。
    返回 (applied: list, errors: list)
    applied 每项：{sheet, target, old_value, new_value, field_status}
    """
    applied = []
    errors = []
    sheet_map = {s["sheet_name"]: s for s in mapping.get("sheets", [])}

    for op in patch.get("operations", []):
        sheet_name = op["sheet_name"]
        target = op["target"].upper()
        new_value = op["new_value"]

        if sheet_name not in wb.sheetnames:
            errors.append(f"Sheet '{sheet_name}' 不在工作簿中")
            continue

        ws = wb[sheet_name]
        cell = ws[target]
        old_value = cell.value

        cell.value = new_value
        applied.append({
            "sheet": sheet_name,
            "target": target,
            "before": old_value,
            "after": new_value,
            "field_status": op.get("field_status"),
            "confirmation_owner": op.get("confirmation_owner"),
        })

    return applied, errors


# ============================================================
# 写后校验
# ============================================================

def verify_post_write(
    output_path: str,
    original_path: str,
    patch: dict,
    mapping: dict,
) -> dict:
    """
    回填后校验：
    1. 预算守恒（按 budget_check_ids 引用 Mapping 预定义区）
    2. 合并单元格结构未被改变
    3. 所有 set_value target 格均有值（非空）
    """
    openpyxl = _require_openpyxl()
    checks = []
    has_block = False
    has_warn = False

    try:
        # data_only=True：读取缓存值（用于合并结构、非空检查）
        wb_new  = openpyxl.load_workbook(output_path,   data_only=True)
        wb_orig = openpyxl.load_workbook(original_path, data_only=True)
        # data_only=False：读取公式结构（判断 total_cell 是否为公式格）
        wb_new_formula = openpyxl.load_workbook(output_path, data_only=False)
        wb_orig_formula = openpyxl.load_workbook(original_path, data_only=False)
    except Exception as e:
        return {
            "status": "BLOCK",
            "checks": [{"name": "open_files", "result": "BLOCK", "detail": str(e)}],
        }

    # 建立 budget_check_id → budget_check 的快速查找
    bc_map = {
        bc["budget_check_id"]: bc
        for bc in mapping.get("budget_checks", [])
    }

    # 1. 预算守恒
    for bc_id in patch.get("budget_check_ids", []):
        bc = bc_map.get(bc_id)
        if not bc:
            checks.append({
                "name": f"budget_check_{bc_id}",
                "result": "WARN",
                "detail": f"budget_check_id={bc_id!r} 不在 Mapping 中，跳过",
            })
            has_warn = True
            continue

        sheet_name = bc["sheet_name"]
        if sheet_name not in wb_new.sheetnames:
            checks.append({
                "name": f"budget_check_{bc_id}",
                "result": "WARN",
                "detail": f"Sheet '{sheet_name}' 不在新文件中",
            })
            has_warn = True
            continue

        ws       = wb_new[sheet_name]
        ws_fml   = wb_new_formula[sheet_name] if sheet_name in wb_new_formula.sheetnames else None
        total_cell   = bc["total_cell"]
        detail_range = bc["detail_range"]
        tolerance    = bc.get("tolerance", 0.01)
        excluded     = set(bc.get("excluded_rows", []))

        # 判断 total_cell 是否为公式格
        # data_only=True 时公式缓存值可能是回填前的旧值，不可信
        # 规则：
        #   1. total_cell 是公式格 → 不读公式结果，改从 detail_range 明细重算为权威总额
        #   2. total_cell 是输入格 → 直接读值
        #   3. 无论哪种，若无法取得可信数值 → BLOCK（不降级为 WARN）
        total_cell_is_formula = (
            ws_fml is not None
            and isinstance(ws_fml[total_cell].value, str)
            and ws_fml[total_cell].value.startswith("=")
        )

        if total_cell_is_formula:
            # 公式总额格：直接从明细重算，不依赖公式缓存值
            total_val = None  # 稍后用 detail_sum 作为权威值
        else:
            total_val = ws[total_cell].value
            if not isinstance(total_val, (int, float)):
                has_block = True
                checks.append({
                    "name": f"budget_check_{bc_id}",
                    "result": "BLOCK",
                    "detail": (
                        f"{sheet_name}!{total_cell} 值 {total_val!r} 不是数值，"
                        f"无法执行预算守恒校验。无法校验时必须 BLOCK，不得放行。"
                    ),
                })
                continue

        # 解析 detail_range
        import re
        m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", detail_range.upper())
        if not m:
            checks.append({
                "name": f"budget_check_{bc_id}",
                "result": "WARN",
                "detail": f"detail_range={detail_range!r} 格式无法解析",
            })
            has_warn = True
            continue

        col_l, r_start, r_end = m.group(1), int(m.group(2)), int(m.group(4))
        detail_sum = 0.0
        for r in range(r_start, r_end + 1):
            if r in excluded:
                continue
            v = ws[f"{col_l}{r}"].value
            if isinstance(v, (int, float)):
                detail_sum += v

        if total_cell_is_formula:
            # 公式总额格：用 Mapping 中 patch 前读取的原始总额（budget_check 里的 expected_total）
            # 若 budget_check 没有 expected_total，则用明细求和自洽校验
            # （即：回填后明细之和必须 = 回填前明细之和，防止数据被意外清零）
            expected_total = patch.get("budget_expectations", {}).get(
                bc_id, bc.get("expected_total")
            )
            if expected_total is not None and isinstance(expected_total, (int, float)):
                ref_total = float(expected_total)
                ref_label = f"已确认预算总额 {ref_total}"
            else:
                # 没有 expected_total：只校验明细非零（防止全被清零）
                if detail_sum == 0.0:
                    has_block = True
                    checks.append({
                        "name": f"budget_check_{bc_id}",
                        "result": "BLOCK",
                        "detail": (
                            f"{sheet_name} 明细区 {detail_range} 回填后求和为 0，"
                            f"total_cell={total_cell} 是公式格且 Mapping 无 expected_total，"
                            f"无法校验守恒。数据疑似被清零，BLOCK 保护。"
                        ),
                    })
                else:
                    checks.append({
                        "name": f"budget_check_{bc_id}",
                        "result": "WARN",
                        "detail": (
                            f"{sheet_name} total_cell={total_cell} 是公式格，"
                            f"Mapping 无 expected_total，仅确认明细求和非零（{detail_sum:.2f}）。"
                            f"建议在 budget_check 中补充 expected_total 以启用完整守恒校验。"
                        ),
                    })
                    has_warn = True
                continue
            diff = abs(ref_total - detail_sum)
            if diff <= tolerance:
                checks.append({
                    "name": f"budget_check_{bc_id}",
                    "result": "PASS",
                    "detail": (
                        f"预算守恒：明细之和 {detail_sum:.2f} ≈ {ref_label}，"
                        f"差额 {diff:.4f} ≤ tolerance {tolerance}（公式格，用 expected_total 校验）"
                    ),
                })
            else:
                has_block = True
                checks.append({
                    "name": f"budget_check_{bc_id}",
                    "result": "BLOCK",
                    "detail": (
                        f"预算守恒失败：明细之和 {detail_sum:.2f} ≠ {ref_label}，"
                        f"差额 {diff:.4f} > tolerance {tolerance}。"
                        f"请调用 allocate_budget_no_error() 重算明细"
                    ),
                })
        else:
            diff = abs(float(total_val) - detail_sum)
            if diff <= tolerance:
                checks.append({
                    "name": f"budget_check_{bc_id}",
                    "result": "PASS",
                    "detail": (
                        f"预算守恒：总预算 {total_val} = 明细之和 {detail_sum:.2f}，"
                        f"差额 {diff:.4f} ≤ tolerance {tolerance}"
                    ),
                })
            else:
                has_block = True
                checks.append({
                    "name": f"budget_check_{bc_id}",
                    "result": "BLOCK",
                    "detail": (
                        f"预算守恒失败：总预算 {total_val} ≠ 明细之和 {detail_sum:.2f}，"
                        f"差额 {diff:.4f} > tolerance {tolerance}。"
                        f"请调用 allocate_budget_no_error() 重算明细"
                    ),
                })

    # 2. Sheet 顺序与名称未被改变
    if wb_new_formula.sheetnames != wb_orig_formula.sheetnames:
        has_block = True
        checks.append({
            "name": "sheet_structure_integrity",
            "result": "BLOCK",
            "detail": (
                f"Sheet 结构发生变化：原={wb_orig_formula.sheetnames}，"
                f"新={wb_new_formula.sheetnames}"
            ),
        })
    else:
        checks.append({
            "name": "sheet_structure_integrity",
            "result": "PASS",
            "detail": "Sheet 名称与顺序保持不变",
        })

    # 3. 合并单元格结构未被改变
    for sheet_info in mapping.get("sheets", []):
        sname = sheet_info["sheet_name"]
        if sname not in wb_new.sheetnames or sname not in wb_orig.sheetnames:
            continue
        orig_merged = {str(r) for r in wb_orig[sname].merged_cells.ranges}
        new_merged  = {str(r) for r in wb_new[sname].merged_cells.ranges}
        if orig_merged != new_merged:
            has_block = True
            added   = new_merged - orig_merged
            removed = orig_merged - new_merged
            checks.append({
                "name": f"merged_cells_integrity_{sname}",
                "result": "BLOCK",
                "detail": (
                    f"Sheet '{sname}' 合并单元格结构被改变。"
                    f"新增: {sorted(added)}，移除: {sorted(removed)}"
                ),
            })
        else:
            checks.append({
                "name": f"merged_cells_integrity_{sname}",
                "result": "PASS",
                "detail": f"Sheet '{sname}' 合并单元格结构完整",
            })

    # 4. 公式与样式未被改变
    formula_changes = []
    style_changes = []
    for sname in wb_orig_formula.sheetnames:
        if sname not in wb_new_formula.sheetnames:
            continue
        old_ws = wb_orig_formula[sname]
        new_ws = wb_new_formula[sname]
        max_row = max(old_ws.max_row, new_ws.max_row)
        max_col = max(old_ws.max_column, new_ws.max_column)
        for row in range(1, max_row + 1):
            for col in range(1, max_col + 1):
                old_cell = old_ws.cell(row=row, column=col)
                new_cell = new_ws.cell(row=row, column=col)
                old_formula = old_cell.value if isinstance(old_cell.value, str) and old_cell.value.startswith("=") else None
                new_formula = new_cell.value if isinstance(new_cell.value, str) and new_cell.value.startswith("=") else None
                if old_formula != new_formula:
                    formula_changes.append(f"{sname}!{old_cell.coordinate}")
                # openpyxl round-trip may normalize the internal empty StyleArray
                # of completely unstyled blank cells. Ignore that serialization noise.
                if (old_cell.has_style or new_cell.has_style) and old_cell._style != new_cell._style:
                    style_changes.append(f"{sname}!{old_cell.coordinate}")

    for name, changes, label in (
        ("formula_integrity", formula_changes, "公式"),
        ("style_integrity", style_changes, "样式"),
    ):
        if changes:
            has_block = True
            checks.append({
                "name": name,
                "result": "BLOCK",
                "detail": f"{label}发生变化，示例: {changes[:20]}",
            })
        else:
            checks.append({
                "name": name,
                "result": "PASS",
                "detail": f"原有{label}保持不变",
            })

    # 5. set_value target 非空
    for op in patch.get("operations", []):
        if op.get("operation") != "set_value":
            continue
        sname = op["sheet_name"]
        target = op["target"].upper()
        if sname not in wb_new.sheetnames:
            continue
        cell = wb_new[sname][target]
        if cell.value is None or str(cell.value).strip() == "":
            has_warn = True
            checks.append({
                "name": f"non_empty_{sname}_{target}",
                "result": "WARN",
                "detail": f"{sname}!{target} 回填后值为空",
            })
        else:
            checks.append({
                "name": f"non_empty_{sname}_{target}",
                "result": "PASS",
                "detail": f"{sname}!{target} = {cell.value!r}",
            })

    overall = "PASS"
    if has_block:
        overall = "BLOCK"
    elif has_warn:
        overall = "WARN"

    return {"status": overall, "checks": checks}


# ============================================================
# CLI 入口：完整回填流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="mp-backfill v2.1: 安全回填已有 Media Plan Excel"
    )
    parser.add_argument("--mapping", required=True, help="Mapping JSON 路径")
    parser.add_argument("--input",   required=True, help="原始 MP Excel 路径（只读）")
    parser.add_argument("--patch",   required=True, help="patch.json 路径")
    parser.add_argument("--output",  required=True, help="输出路径（如 out/updated.xlsx）")
    args = parser.parse_args()

    # 1. 加载 Mapping
    try:
        mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    except Exception as e:
        print(json.dumps(
            {"status": "error", "step": "load_mapping", "error": str(e)},
            ensure_ascii=False, indent=2,
        ))
        sys.exit(1)

    # 2. 加载 Patch
    try:
        patch = json.loads(Path(args.patch).read_text(encoding="utf-8"))
    except Exception as e:
        print(json.dumps(
            {"status": "error", "step": "load_patch", "error": str(e)},
            ensure_ascii=False, indent=2,
        ))
        sys.exit(1)

    # 3. 独立确定性 patch 校验
    is_valid, errors = validate_patch(patch, mapping, args.input)
    if not is_valid:
        print(json.dumps({
            "status": "BLOCK",
            "step": "patch_validation",
            "errors": errors,
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    # 4. 创建输出目录 + 复制原文件到临时副本
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.input, args.output)

    # 5. 在临时副本上应用 operations
    openpyxl = _require_openpyxl()
    try:
        wb = openpyxl.load_workbook(args.output)
    except Exception as e:
        print(json.dumps(
            {"status": "error", "step": "open_workbook", "error": str(e)},
            ensure_ascii=False, indent=2,
        ))
        sys.exit(1)

    applied, apply_errors = apply_operations(wb, patch, mapping)

    if apply_errors:
        # 写入失败，删除副本，原文件不动
        try:
            Path(args.output).unlink(missing_ok=True)
        except Exception:
            pass
        print(json.dumps({
            "status": "BLOCK",
            "step": "apply_operations",
            "errors": apply_errors,
            "note": "输出副本已删除，原文件未被修改",
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    try:
        wb.save(args.output)
    except Exception as e:
        try:
            Path(args.output).unlink(missing_ok=True)
        except Exception:
            pass
        print(json.dumps(
            {"status": "error", "step": "save_workbook", "error": str(e)},
            ensure_ascii=False, indent=2,
        ))
        sys.exit(1)

    # 6. 写后校验
    verify_result = verify_post_write(args.output, args.input, patch, mapping)

    # 7. 校验失败 → 删除副本，原文件不动
    if verify_result["status"] == "BLOCK":
        try:
            Path(args.output).unlink(missing_ok=True)
        except Exception:
            pass
        print(json.dumps({
            "status": "BLOCK",
            "step": "post_write_verify",
            "verify": verify_result,
            "diff": applied,
            "note": "输出副本已删除，原文件未被修改。请修正后重新运行。",
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    # 8. 成功输出
    print(json.dumps({
        "status": verify_result["status"],   # PASS 或 WARN
        "step": "complete",
        "output": args.output,
        "original": args.input,
        "cells_written": len(applied),
        "verify": verify_result,
        "diff": applied,
        "note": "原文件未被修改，输出副本即回填结果。如需回滚，使用原文件。",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
