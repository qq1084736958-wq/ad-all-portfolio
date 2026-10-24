#!/usr/bin/env python3
"""
mp-reader.py — 已有 Media Plan Excel 解析器（只读层）v2.1.0

职责：
  - 读取用户上传的原始 MP Excel，提取 Sheet 结构、表头、数据区域、
    writable_ranges、protected_ranges、合并单元格、budget_checks、格式约定
  - 输出结构化 Mapping JSON（供 mp-backfill.py 使用）
  - 可选生成 mapping_summary.md（由 JSON 自动渲染，不维护两份规则）
  - 【隔离原则】本模块只读，不持有写工具，不修改任何文件

v2.1.0 变更：
  - Mapping 新增 mapping_id（文件 hash 前缀 + 时间戳）
  - 每个 Sheet 新增 writable_ranges / protected_ranges（替代 ±10 容差）
  - 每个 Sheet 新增 budget_checks（reader 识别候选预算区，patch 按 ID 引用）
  - 精确保护公式格，不因汇总公式锁死整列明细输入区
  - 支持封面键值区、纵向文案表单和带样式的模板预留行
  - 列信息保留 is_formula / is_header 标记
  - 新增 --summary 参数，输出 mapping_summary.md

用法：
  python3 scripts/mp-reader.py --input <path.xlsx> --output <mapping.json>
  python3 scripts/mp-reader.py --input <path.xlsx> --output <mapping.json> --summary <summary.md>
  python3 scripts/mp-reader.py --input <path.xlsx> --validate-only

版本：v2.1.0 | 2026-09-15
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
# 文件 Hash
# ============================================================

def file_sha256(path: str) -> str:
    """计算文件 SHA-256，用于 source_workbook_hash 校验。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ============================================================
# Mapping ID 生成
# ============================================================

def make_mapping_id(file_hash: str) -> str:
    """mapping_id = hash 前 8 位 + 时间戳，全局唯一，供 patch 引用校验。"""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"mapping_{file_hash[:8]}_{ts}"


# ============================================================
# 辅助：列字母
# ============================================================

def _col_letter(col_index: int) -> str:
    """0-based 列索引 → Excel 列字母"""
    result = ""
    n = col_index + 1
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _col_index(col_letter: str) -> int:
    """Excel 列字母 → 0-based 列索引"""
    result = 0
    for c in col_letter.upper():
        result = result * 26 + (ord(c) - ord("A") + 1)
    return result - 1


# ============================================================
# 辅助：格式检测
# ============================================================

def _detect_format(cell_value: Any, number_format: str) -> str:
    if number_format:
        fmt = number_format.upper()
        if any(c in fmt for c in ["$", "USD", "¥", "€", "£"]):
            return "currency"
        if "%" in fmt:
            return "percent"
        if any(x in fmt for x in ["YY", "MM", "DD", "HH"]):
            return "date"
        if "0" in fmt and "." not in fmt and "%" not in fmt:
            return "integer"

    if cell_value is None:
        return "unknown"
    if isinstance(cell_value, bool):
        return "text"
    if isinstance(cell_value, float):
        if 0.0 < cell_value < 1.0:
            return "percent"
        return "currency"
    if isinstance(cell_value, int):
        return "integer"
    if isinstance(cell_value, str):
        import re
        if re.match(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", cell_value):
            return "date"
        if cell_value.strip().endswith("%"):
            return "percent"
        if cell_value.strip().upper().startswith("USD"):
            return "currency"
    return "text"


# ============================================================
# 辅助：Sheet 用途推断
# ============================================================

_PURPOSE_KEYWORDS = {
    "cover":    ["cover", "封面"],
    "brief":    ["brief", "input", "需求", "背景", "简报"],
    "strategy": ["strategy", "策略", "阶段"],
    "schedule": ["schedule", "timeline", "calendar", "排期", "日程"],
    "tasks":    ["to-do", "todo", "task", "任务", "待办"],
    "audience": ["audience", "targeting", "人群", "受众", "定向"],
    "landing":  ["landing", "utm", "落地页"],
    "copy":     ["copy", "文案"],
    "summary":  ["summary", "overview", "摘要", "总览", "概览"],
    "budget":   ["budget", "spend", "cost", "预算", "费用", "消耗"],
    "kpi":      ["kpi", "performance", "target", "目标", "指标", "效果"],
    "creative": ["creative", "素材", "内容", "media"],
    "platform": ["platform", "channel", "媒体", "渠道", "媒介"],
}


def _infer_purpose(sheet_name: str, header_values: list) -> str:
    # Sheet 名比表头更能代表用途。先匹配 Sheet 名，避免 Strategy 因包含
    # “预算”列而被误判为 budget，Audience 因包含 target 而被误判为 KPI。
    name_text = sheet_name.lower()
    for purpose, keywords in _PURPOSE_KEYWORDS.items():
        if any(kw in name_text for kw in keywords):
            return purpose

    all_text = " ".join(str(v).lower() for v in header_values if v)
    for purpose, keywords in _PURPOSE_KEYWORDS.items():
        if any(kw in all_text for kw in keywords):
            return purpose
    return "unknown"


# ============================================================
# 辅助：表头行识别
# ============================================================

def _find_header_row(ws, max_scan: int = 10) -> int | None:
    best_row, best_count = None, -1
    for row_idx in range(min(max_scan, ws.max_row)):
        row = list(ws.iter_rows(
            min_row=row_idx + 1, max_row=row_idx + 1, values_only=True
        ))[0]
        non_empty = sum(1 for c in row if c is not None and str(c).strip() != "")
        if non_empty > best_count:
            best_count = non_empty
            best_row = row_idx
    return best_row


def _is_cover_sheet(sheet_name: str) -> bool:
    name = sheet_name.lower()
    return "cover" in name or "封面" in name


def _build_cover_ranges(ws, merged_all: set, formula_cell_refs: set) -> tuple[list, list]:
    """为键值型封面生成精确可写格，避免把整页开放为可写。"""
    writable = []
    protected = []
    max_col = ws.max_column or 1
    max_row = ws.max_row or 1

    # 封面默认整体保护，仅对“标签右侧的单元格”逐格开放。
    protected.append({
        "range": f"A1:{_col_letter(max_col - 1)}{max_row}",
        "reason": "cover_default_protect",
    })
    allowed_refs = set()
    merged_top_left = {
        str(mr).split(":", 1)[0].upper(): str(mr)
        for mr in ws.merged_cells.ranges
    }
    for r in range(1, max_row + 1):
        for c in range(1, max_col):
            label = ws.cell(row=r, column=c).value
            target = ws.cell(row=r, column=c + 1)
            target_ref = f"{_col_letter(c)}{r}"
            if label is None or str(label).strip() == "":
                continue
            if target_ref in formula_cell_refs:
                continue
            # 仅识别带业务标签的键值行；标题、导航等展示文本不会开放。
            label_text = str(label).lower()
            if not any(token in label_text for token in (
                "name", "brand", "market", "period", "budget", "currency",
                "owner", "team", "version", "updated", "名称", "品牌", "市场",
                "周期", "预算", "币种", "负责人", "团队", "版本", "更新",
            )):
                continue
            writable.append({
                "col_letter": _col_letter(c),
                "row_start": r,
                "row_end": r,
                "expandable": False,
                "header_value": str(label).strip(),
                "detected_format": _detect_format(target.value, target.number_format or ""),
                "allow_merged_top_left": target_ref in merged_top_left,
            })
            allowed_refs.add(target_ref)

    # 精确开放的格子从默认保护区中无法表达“挖洞”，因此改为保护所有
    # 非开放行列区域及明确结构。validator 以 writable 白名单为第一道门。
    protected = []
    for mr in ws.merged_cells.ranges:
        rng = str(mr)
        if rng.split(":", 1)[0].upper() not in allowed_refs:
            protected.append({"range": rng, "reason": "merged_cell_range"})
    for ref in sorted(formula_cell_refs):
        protected.append({"range": f"{ref}:{ref}", "reason": "formula_cell"})
    return writable, protected


def _build_vertical_form_ranges(ws, formula_cell_refs: set) -> tuple[list, list]:
    """识别“左侧字段名、右侧多列填写值”的通用矩阵型表单。"""
    writable = []
    protected = []
    first_value_col = 3  # C 列起作为值区；A 为边距、B 为字段名
    for c in range(first_value_col, (ws.max_column or 0) + 1):
        col_letter = _col_letter(c - 1)
        writable.append({
            "col_letter": col_letter,
            "row_start": 2,
            "row_end": ws.max_row,
            "expandable": False,
            "header_value": f"value_column_{col_letter}",
            "detected_format": "text",
        })
    if ws.max_row:
        protected.append({"range": f"A1:B{ws.max_row}", "reason": "vertical_form_labels"})
    for ref in sorted(formula_cell_refs):
        protected.append({"range": f"{ref}:{ref}", "reason": "formula_cell"})
    return writable, protected


# ============================================================
# 辅助：合并单元格集合（所有单元格，含左上角）
# ============================================================

def _all_merged_cells(merged_ranges) -> set[str]:
    """返回所有合并范围内的单元格引用（含左上角）。"""
    import re
    result = set()
    for mr in merged_ranges:
        rng = str(mr)
        m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", rng.upper())
        if not m:
            continue
        c1 = _col_index(m.group(1)) + 1
        r1 = int(m.group(2))
        c2 = _col_index(m.group(3)) + 1
        r2 = int(m.group(4))
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                result.add(f"{_col_letter(c-1)}{r}")
    return result


# ============================================================
# 辅助：候选预算区检测
# ============================================================

_BUDGET_HEADER_KEYWORDS = [
    "budget", "spend", "cost", "amount", "line total", "预算", "费用", "小计"
]
_TOTAL_KEYWORDS = ["total", "sum", "合计", "总计", "subtotal"]


def _detect_budget_checks(ws, sheet_name: str, header_row_idx: int,
                           data_start_row: int, data_end_row: int,
                           columns: list,
                           formula_cell_refs: set | None = None) -> list[dict]:
    """
    识别候选预算汇总区，返回 budget_checks 列表。
    每条记录包含 budget_check_id、total_cell、detail_range、
    currency_hint、excluded_rows、tolerance。

    规则（全部确定性，不由模型判断）：
    - 列 header 包含预算关键词 → 候选预算列
    - 在候选预算列中，找包含 TOTAL 关键词的行 → total_cell
    - total_cell 上方（或下方）连续非空数值区 → detail_range
    """
    checks = []
    if header_row_idx is None or data_start_row is None:
        return checks

    for col_info in columns:
        hv = (col_info.get("header_value") or "").lower()
        if not any(kw in hv for kw in _BUDGET_HEADER_KEYWORDS):
            continue
        if col_info.get("detected_format") not in ("currency", "integer", "unknown"):
            continue

        col_letter = col_info["col_letter"]
        total_row = None
        detail_rows = []
        formula_cell_refs = formula_cell_refs or set()

        # 扫描数据区，找 total 行和数值行
        end = (data_end_row or ws.max_row - 1) + 1
        for r in range(data_start_row + 1, end + 1):
            cell = ws.cell(row=r, column=_col_index(col_letter) + 1)
            row_label = ""
            # 汇总标签不一定在第一列，扫描同行文本标签。
            row_label = " ".join(
                str(ws.cell(row=r, column=c).value).lower()
                for c in range(1, min(ws.max_column, 12) + 1)
                if ws.cell(row=r, column=c).value is not None
            )

            is_total = any(kw in row_label for kw in _TOTAL_KEYWORDS)

            if is_total and (
                cell.value is not None or f"{col_letter}{r}" in formula_cell_refs
            ):
                total_row = r
            elif f"{col_letter}{r}" not in formula_cell_refs:
                # 空白但可编辑的预算格也是有效明细区；不能要求模板预先有数值。
                detail_rows.append(r)

        if total_row and detail_rows:
            check_id = f"budget_{sheet_name}_{col_letter}_{total_row}".replace(" ", "_")
            check = {
                "budget_check_id": check_id,
                "sheet_name": sheet_name,
                "total_cell": f"{col_letter}{total_row}",
                "detail_range": f"{col_letter}{min(detail_rows)}:{col_letter}{max(detail_rows)}",
                "currency_hint": col_info.get("detected_format", "currency"),
                "excluded_rows": [],
                "tolerance": 0.01,
                "note": "reader 自动识别候选预算区，patch 通过 budget_check_id 引用，不传坐标",
            }
            total_ref = f"{col_letter}{total_row}"
            if (
                total_ref not in formula_cell_refs
                and isinstance(ws.cell(row=total_row, column=_col_index(col_letter) + 1).value, (int, float))
            ):
                check["expected_total"] = ws.cell(
                    row=total_row, column=_col_index(col_letter) + 1
                ).value
            checks.append(check)

    return checks


# ============================================================
# 辅助：writable_ranges / protected_ranges 生成
# ============================================================

def _build_ranges(ws, sheet_name: str, header_row_idx: int,
                  data_start_row: int, data_end_row: int,
                  merged_all: set, columns: list,
                  formula_cell_refs: set = None) -> tuple:
    """
    生成 writable_ranges 和 protected_ranges。

    writable_ranges：数据区内有明确表头的候选输入列范围
    protected_ranges：
      - 表头行及以上
      - 实际公式格（通过 data_only=False 工作簿确定性识别）
      - 合并单元格覆盖的完整区域

    Args:
        formula_cell_refs: 由 data_only=False 工作簿提取的公式单元格引用集合（如 {'C5', 'D10'}）
                           若为 None：保守模式，数据区全部保护，防止公式列被误判为可写
    """
    if header_row_idx is None or data_start_row is None:
        return [], [{"range": "A1:ZZ99999", "reason": "无法识别表头，整张表保护"}]

    protected = []
    writable = []
    end_row = (data_end_row or ws.max_row - 1) + 1

    # 保护：表头及以上
    if header_row_idx > 0:
        protected.append({
            "range": f"A1:{_col_letter(ws.max_column - 1)}{header_row_idx + 1}",
            "reason": "header_and_above",
        })

    # 保护：合并单元格覆盖区
    for mr in ws.merged_cells.ranges:
        protected.append({
            "range": str(mr),
            "reason": "merged_cell_range",
        })

    if formula_cell_refs is None:
        # 无公式信息：保守模式，数据区全部保护
        protected.append({
            "range": f"A{data_start_row + 1}:{_col_letter(ws.max_column - 1)}{end_row}",
            "reason": "formula_info_unavailable_conservative_protect",
        })
        return [], protected

    # 只保护实际公式格，不因汇总公式而锁死整列的明细输入格。
    for ref in sorted(formula_cell_refs):
        protected.append({"range": f"{ref}:{ref}", "reason": "formula_cell"})

    # writable：数据区内有明确表头的每列范围；实际公式格另行保护。
    for col_info in columns:
        col_letter = col_info["col_letter"]
        # 无表头列通常是边距或版式空间，不自动开放。
        if not col_info.get("header_value"):
            continue
        header_text = str(col_info.get("header_value") or "").strip().lower()
        if any(token in header_text for token in (
            "module", "模块", "field", "字段", "item", "项目"
        )):
            continue
        if any(token in header_text for token in (
            "notes", "note", "备注", "填写说明", "guidance"
        )):
            populated = 0
            total = max(1, end_row - data_start_row)
            for r in range(data_start_row + 1, end_row + 1):
                value = ws.cell(row=r, column=_col_index(col_letter) + 1).value
                if value is not None and str(value).strip() != "":
                    populated += 1
            if populated / total >= 0.5:
                continue
        if data_end_row is None:
            continue
        writable.append({
            "col_letter": col_letter,
            "row_start": data_start_row + 1,   # 1-based
            "row_end": end_row,                 # 1-based
            "expandable": False,
            "header_value": col_info.get("header_value"),
            "detected_format": col_info.get("detected_format"),
        })

    return writable, protected


def _parse_sheet(ws, sheet_index: int, formula_cell_refs: set = None) -> tuple:
    warnings = []

    # 合并单元格
    merged_cells = []
    merged_all = _all_merged_cells(ws.merged_cells.ranges)
    for mr in ws.merged_cells.ranges:
        rng = str(mr)
        import re
        m = re.match(r"([A-Z]+)(\d+)", rng.upper())
        top_left_val = None
        if m:
            cell = ws[f"{m.group(1)}{m.group(2)}"]
            top_left_val = str(cell.value) if cell.value is not None else None
        merged_cells.append({"range": rng, "top_left_value": top_left_val})

    # 封面采用键值布局，不套用表格表头推断。
    if _is_cover_sheet(ws.title):
        writable_ranges, protected_ranges = _build_cover_ranges(
            ws, merged_all, formula_cell_refs or set()
        )
        return {
            "sheet_index": sheet_index,
            "sheet_name": ws.title,
            "purpose_hint": "cover",
            "header_row": None,
            "data_start_row": None,
            "data_end_row": None,
            "col_count": ws.max_column or 0,
            "columns": [],
            "merged_cells": merged_cells,
            "merged_cell_refs": sorted(merged_all),
            "writable_ranges": writable_ranges,
            "protected_ranges": protected_ranges,
            "budget_checks": [],
            "key_cells": [],
        }, warnings

    if _infer_purpose(ws.title, []) == "copy":
        writable_ranges, protected_ranges = _build_vertical_form_ranges(
            ws, formula_cell_refs or set()
        )
        return {
            "sheet_index": sheet_index,
            "sheet_name": ws.title,
            "purpose_hint": "copy",
            "header_row": None,
            "data_start_row": 1,
            "data_end_row": ws.max_row - 1,
            "col_count": ws.max_column or 0,
            "columns": [],
            "merged_cells": merged_cells,
            "merged_cell_refs": sorted(merged_all),
            "writable_ranges": writable_ranges,
            "protected_ranges": protected_ranges,
            "budget_checks": [],
            "key_cells": [],
        }, warnings

    # 表头行
    header_row_idx = _find_header_row(ws)
    if header_row_idx is None:
        warnings.append(f"Sheet '{ws.title}' 无法识别表头行")
        return {
            "sheet_index": sheet_index,
            "sheet_name": ws.title,
            "purpose_hint": "unknown",
            "header_row": None,
            "data_start_row": None,
            "data_end_row": None,
            "col_count": ws.max_column or 0,
            "columns": [],
            "merged_cells": merged_cells,
            "merged_cell_refs": sorted(merged_all),
            "writable_ranges": [],
            "protected_ranges": [{"range": "A1:ZZ99999", "reason": "无法识别表头，整张表保护"}],
            "budget_checks": [],
            "key_cells": [],
        }, warnings

    header_row_data = list(ws.iter_rows(
        min_row=header_row_idx + 1, max_row=header_row_idx + 1, values_only=True
    ))[0]

    data_start_row = header_row_idx + 1  # 0-based
    data_end_row = None
    for r in range(ws.max_row, data_start_row, -1):
        row = list(ws.iter_rows(min_row=r, max_row=r, values_only=True))[0]
        if any(c is not None and str(c).strip() != "" for c in row):
            data_end_row = r - 1  # 0-based
            break
    # 纯空白但已预设样式的模板数据区，使用工作表设计末行。
    if data_end_row is None and ws.max_row > data_start_row + 1:
        data_end_row = ws.max_row - 1

    # 列分析
    columns = []
    for col_idx in range(ws.max_column or 0):
        header_val = (
            header_row_data[col_idx]
            if col_idx < len(header_row_data) else None
        )
        header_str = str(header_val).strip() if header_val is not None else None
        col_ltr = _col_letter(col_idx)

        sample_values, detected_format = [], "unknown"
        # is_formula：使用 data_only=False 的公式引用集合确定性判断
        # data_only=True 模式下公式已求值，无法从 cell.value 判断
        end = (data_end_row or ws.max_row - 1) + 1
        is_formula = (formula_cell_refs is not None) and any(
            f"{col_ltr}{r}" in formula_cell_refs
            for r in range(data_start_row + 1, min(end + 1, data_start_row + 10))
        )
        for r in range(data_start_row + 1, min(end + 1, data_start_row + 20)):
            cell = ws.cell(row=r, column=col_idx + 1)
            if cell.value is not None and str(cell.value).strip() != "":
                val_str = str(cell.value)
                sample_values.append(val_str)
                if detected_format == "unknown":
                    detected_format = _detect_format(
                        cell.value, cell.number_format or ""
                    )
                if len(sample_values) >= 3:
                    break

        # is_header：如果该列整列都在合并区域或表头，标记
        is_header = (f"{col_ltr}{header_row_idx + 1}" in merged_all)

        columns.append({
            "col_index": col_idx,
            "col_letter": col_ltr,
            "header_value": header_str,
            "sample_values": sample_values,
            "detected_format": detected_format,
            "is_formula": is_formula,
            "is_header": is_header,
        })

    purpose = _infer_purpose(ws.title, [c["header_value"] for c in columns])
    writable_ranges, protected_ranges = _build_ranges(
        ws, ws.title, header_row_idx, data_start_row,
        data_end_row, merged_all, columns,
        formula_cell_refs=formula_cell_refs,
    )
    budget_checks = _detect_budget_checks(
        ws, ws.title, header_row_idx, data_start_row,
        data_end_row, columns, formula_cell_refs=formula_cell_refs,
    )
    key_cells = _build_key_cells(
        ws, ws.title, header_row_idx, data_start_row,
        data_end_row, columns,
        formula_cell_refs=formula_cell_refs,
    )

    return {
        "sheet_index": sheet_index,
        "sheet_name": ws.title,
        "purpose_hint": purpose,
        "header_row": header_row_idx,          # 0-based
        "data_start_row": data_start_row,       # 0-based（header 下一行）
        "data_end_row": data_end_row,           # 0-based
        "col_count": ws.max_column or 0,
        "columns": columns,
        "merged_cells": merged_cells,
        "merged_cell_refs": sorted(merged_all), # 所有合并格引用（含左上角）
        "writable_ranges": writable_ranges,
        "protected_ranges": protected_ranges,
        "budget_checks": budget_checks,
        "key_cells": key_cells,                 # 行语义：row_type / first_col_value / editable_by_status
    }, warnings


# ============================================================
# 行语义分析（key_cells 生成）
# ============================================================

_TOTAL_ROW_KEYWORDS = ["total", "sum", "subtotal", "合计", "总计", "小计", "grand total"]
_NOTE_ROW_KEYWORDS  = ["note", "备注", "说明", "remark", "comment", "*"]
_HEADER_ROW_KEYWORDS = ["platform", "channel", "media", "phase", "阶段", "平台", "渠道", "period", "budget"]


def _classify_row_type(ws, row_num: int, col_count: int,
                       formula_cell_refs: set | None = None) -> str:
    """
    判断某行的语义类型（确定性规则，不由模型判断）。

    row_type:
      "data"    — 正常数据行
      "total"   — 汇总/合计行（第一列或任意列含 total 关键词）
      "header"  — 表头行（含表头关键词）
      "note"    — 备注行（第一列含备注关键词，或整行只有第一列有值）
      "template"— 已设置格式的空白模板行
      "empty"   — 无值且无模板格式的空行
    """
    # 读第一列值和全行值
    first_col_val = ws.cell(row=row_num, column=1).value
    first_str = str(first_col_val).strip().lower() if first_col_val is not None else ""

    row_vals = [ws.cell(row=row_num, column=c+1).value for c in range(min(col_count, 20))]
    non_empty = [v for v in row_vals if v is not None and str(v).strip() != ""]

    formula_cell_refs = formula_cell_refs or set()

    # 空行：有格式的预留行可用于新增数据，无格式空行继续保护。
    if not non_empty:
        if any(ws.cell(row=row_num, column=c + 1).has_style for c in range(col_count)):
            return "template"
        return "empty"

    # 合计行：第一列含 total 关键词
    if any(kw in first_str for kw in _TOTAL_ROW_KEYWORDS):
        return "total"

    # 行内任一业务标签含合计词，也视为汇总行。
    row_text = " ".join(str(v).strip().lower() for v in non_empty)
    if any(kw in row_text for kw in _TOTAL_ROW_KEYWORDS):
        return "total"

    # 带标签且大部分已用单元格是公式，通常是分组汇总/小计行。
    formula_count = sum(
        1 for c in range(col_count)
        if f"{_col_letter(c)}{row_num}" in formula_cell_refs
    )
    if first_col_val is not None and formula_count >= max(2, col_count // 3):
        return "total"

    # 备注行：第一列以 * 或含备注词开头，或只有一个非空格且在第一列
    if any(kw in first_str for kw in _NOTE_ROW_KEYWORDS):
        return "note"
    if len(non_empty) == 1 and first_col_val is not None:
        return "note"

    # 表头行
    if any(kw in first_str for kw in _HEADER_ROW_KEYWORDS):
        return "header"

    return "data"


def _build_key_cells(ws, sheet_name: str, header_row_idx: int,
                     data_start_row: int, data_end_row: int,
                     columns: list, formula_cell_refs: set = None) -> list:
    """
    生成 key_cells 列表，记录每行的语义类型，帮助回填时精确定位目标行。

    key_cells 结构：
    [
      {
        "row_num":     int,       # 1-based 行号
        "row_type":    str,       # data / total / header / note / template / empty
        "first_col_value": str,   # 第一列值（作为行主键标识，如产品名/平台名/阶段名）
        "is_formula_row": bool,   # 该行任意格是否有公式
        "editable_by_status": [str],  # 哪些 field_status 允许写该行（见下方规则）
      }
    ]

    editable_by_status 规则（确定性）：
      data 行   → ["confirmed", "derived", "recommended"]  # 正常业务数据行
      total 行  → []                                        # 禁写（通常是公式汇总，不得手动覆盖）
      header 行 → []                                        # 禁写
      note 行   → ["confirmed"]                             # 备注只允许客户确认写入
      template 行 → [confirmed, derived, recommended, defaulted] # 模板预留输入行
      empty 行  → []                                        # 无格式空行用途不明
    """
    if header_row_idx is None or data_start_row is None:
        return []

    EDITABLE_MAP = {
        "data":   ["confirmed", "derived", "recommended", "defaulted"],
        "total":  [],
        "header": [],
        "note":   ["confirmed"],
        "template": ["confirmed", "derived", "recommended", "defaulted"],
        "empty":  [],
    }

    end_row = (data_end_row or ws.max_row - 1) + 1
    col_count = ws.max_column or 0
    key_cells = []

    for r in range(data_start_row + 1, end_row + 2):  # +2：包含末行后一行（可能是合计）
        row_type = _classify_row_type(
            ws, r, col_count, formula_cell_refs=formula_cell_refs
        )

        first_col_val = ws.cell(row=r, column=1).value
        first_str = str(first_col_val).strip() if first_col_val is not None else ""

        # 是否公式行
        is_formula_row = False
        if formula_cell_refs:
            is_formula_row = any(
                f"{_col_letter(c)}{r}" in formula_cell_refs
                for c in range(col_count)
            )

        key_cells.append({
            "row_num":          r,
            "row_type":         row_type,
            "first_col_value":  first_str,
            "is_formula_row":   is_formula_row,
            "editable_by_status": EDITABLE_MAP.get(row_type, []),
        })

    return key_cells


# ============================================================
# 格式约定检测
# ============================================================

def _detect_format_conventions(sheets_data: list) -> dict:
    import re
    currency_hints, date_samples, percent_decimal_hints = [], [], []
    for sheet in sheets_data:
        for col in sheet.get("columns", []):
            fmt = col.get("detected_format", "")
            for sv in col.get("sample_values", []):
                if fmt == "currency":
                    if sv.strip().upper().startswith("USD") or "$" in sv:
                        currency_hints.append("USD")
                if fmt == "date":
                    date_samples.append(sv)
                if fmt == "percent":
                    try:
                        v = float(sv.replace("%", "").strip())
                        percent_decimal_hints.append(v < 1.0)
                    except ValueError:
                        pass

    date_format_hint = None
    for ds in date_samples:
        if re.match(r"\d{4}-\d{2}-\d{2}", ds):
            date_format_hint = "YYYY-MM-DD"
            break
        if re.match(r"\d{2}/\d{2}/\d{4}", ds):
            date_format_hint = "MM/DD/YYYY"
            break

    return {
        "currency_symbol": "USD" if currency_hints else None,
        "date_format_hint": date_format_hint,
        "percent_as_decimal": (
            sum(percent_decimal_hints) / len(percent_decimal_hints) > 0.5
            if percent_decimal_hints else None
        ),
    }


# ============================================================
# Mapping Schema 校验
# ============================================================

REQUIRED_MAPPING_KEYS = {
    "schema_version", "mapping_id", "source_file", "source_workbook_hash",
    "parsed_at", "sheet_count", "sheets", "format_conventions",
}
REQUIRED_SHEET_KEYS = {
    "sheet_index", "sheet_name", "purpose_hint", "header_row",
    "data_start_row", "col_count", "columns", "merged_cells",
    "merged_cell_refs", "writable_ranges", "protected_ranges", "budget_checks",
}


def validate_mapping(mapping: dict) -> tuple[bool, list[str]]:
    errors = []
    if mapping.get("status") == "error":
        errors.append(f"解析失败: {mapping.get('error', '未知错误')}")
        return False, errors

    missing_top = REQUIRED_MAPPING_KEYS - set(mapping.keys())
    if missing_top:
        errors.append(f"Mapping 缺少顶层字段: {sorted(missing_top)}")

    sheets = mapping.get("sheets", [])
    if not isinstance(sheets, list) or len(sheets) == 0:
        errors.append("Mapping.sheets 为空或不是列表")
    else:
        for i, sheet in enumerate(sheets):
            missing_sheet = REQUIRED_SHEET_KEYS - set(sheet.keys())
            if missing_sheet:
                errors.append(
                    f"Sheet[{i}] '{sheet.get('sheet_name', '?')}' "
                    f"缺少字段: {sorted(missing_sheet)}"
                )

    return len(errors) == 0, errors


# ============================================================
# 主函数：解析 Excel
# ============================================================

def parse_mp(input_path: str) -> dict:
    openpyxl = _require_openpyxl()
    path = Path(input_path)

    if not path.exists():
        return {"status": "error", "error": f"文件不存在: {input_path}"}
    if path.suffix.lower() not in (".xlsx", ".xlsm", ".xltx"):
        return {"status": "error", "error": f"不支持的文件格式: {path.suffix}"}

    file_hash = file_sha256(input_path)
    mapping_id = make_mapping_id(file_hash)

    # 双模式读取：
    # wb_formula（data_only=False）：提取公式结构，确定性识别公式列
    # wb_values（data_only=True）：获取缓存值，用于格式检测和 budget 求和
    # data_only=True 时公式变成缓存值，无法从 cell.value 判断是否为公式
    try:
        wb_values  = openpyxl.load_workbook(input_path, data_only=True)
        wb_formula = openpyxl.load_workbook(input_path, data_only=False)
    except Exception as e:
        return {"status": "error", "error": f"无法打开文件: {e}"}

    # 提取所有公式单元格引用（跨所有 Sheet）
    # 格式：{"SheetName": {"C5", "D10", ...}}
    formula_refs_by_sheet: dict = {}
    for sname in wb_formula.sheetnames:
        ws_f = wb_formula[sname]
        refs = set()
        for row in ws_f.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    refs.add(f"{cell.column_letter}{cell.row}")
        formula_refs_by_sheet[sname] = refs

    global_warnings = []
    sheets_data = []
    all_budget_checks = []

    for idx, sheet_name in enumerate(wb_values.sheetnames):
        ws = wb_values[sheet_name]
        formula_cell_refs = formula_refs_by_sheet.get(sheet_name, set())
        sheet_info, warnings = _parse_sheet(ws, idx, formula_cell_refs=formula_cell_refs)
        global_warnings.extend(warnings)
        all_budget_checks.extend(sheet_info.get("budget_checks", []))
        sheets_data.append(sheet_info)

    return {
        "schema_version": "2.0",
        "mapping_id": mapping_id,
        "source_file": path.name,
        "source_workbook_hash": file_hash,
        "parsed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sheet_count": len(sheets_data),
        "sheets": sheets_data,
        "budget_checks": all_budget_checks,   # 顶层汇总，方便 patch 查找
        "format_conventions": _detect_format_conventions(sheets_data),
        "warnings": global_warnings,
    }


# ============================================================
# mapping_summary.md 生成（由 JSON 自动渲染）
# ============================================================

def render_summary(mapping: dict) -> str:
    lines = [
        "# Mapping Summary",
        "",
        f"**文件**：{mapping.get('source_file')}",
        f"**mapping_id**：`{mapping.get('mapping_id')}`",
        f"**source_workbook_hash**：`{mapping.get('source_workbook_hash', '')[:16]}...`",
        f"**解析时间**：{mapping.get('parsed_at')}",
        f"**Sheet 数量**：{mapping.get('sheet_count')}",
        "",
        "---",
        "",
    ]

    for sheet in mapping.get("sheets", []):
        lines += [
            f"## Sheet: {sheet['sheet_name']} ({sheet.get('purpose_hint', 'unknown')})",
            "",
            f"- 表头行（0-based）：{sheet.get('header_row')}",
            f"- 数据区（0-based）：{sheet.get('data_start_row')} ~ {sheet.get('data_end_row')}",
            "",
        ]

        # 可写区域
        wr = sheet.get("writable_ranges", [])
        if wr:
            lines.append("**可写区域（writable_ranges）**：")
            lines.append("")
            lines.append("| 列 | 表头 | 行范围 | 格式 | 可扩展 |")
            lines.append("|---|---|---|---|---|")
            for r in wr:
                lines.append(
                    f"| {r['col_letter']} | {r.get('header_value') or '-'} "
                    f"| {r['row_start']}–{r['row_end']} "
                    f"| {r.get('detected_format', '-')} "
                    f"| {r.get('expandable', False)} |"
                )
            lines.append("")

        # 保护区域
        pr = sheet.get("protected_ranges", [])
        if pr:
            lines.append("**保护区域（protected_ranges）**：")
            lines.append("")
            for r in pr:
                lines.append(f"- `{r['range']}` — {r.get('reason', '')}")
            lines.append("")

        # 合并单元格
        mc = sheet.get("merged_cells", [])
        if mc:
            lines.append("**合并单元格**：")
            lines.append("")
            for m in mc:
                lines.append(f"- `{m['range']}` — 左上角值：{m.get('top_left_value') or '(空)'}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Budget checks
    bcs = mapping.get("budget_checks", [])
    if bcs:
        lines += [
            "## 候选预算校验区（budget_checks）",
            "",
            "| budget_check_id | total_cell | detail_range | tolerance |",
            "|---|---|---|---|",
        ]
        for bc in bcs:
            lines.append(
                f"| `{bc['budget_check_id']}` | {bc['total_cell']} "
                f"| {bc['detail_range']} | {bc.get('tolerance', 0.01)} |"
            )
        lines.append("")

    # 警告
    if mapping.get("warnings"):
        lines += ["## ⚠️ 解析警告", ""]
        for w in mapping["warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    lines.append(
        "> 本文件由 mp-reader.py 从 Mapping JSON 自动生成，勿手动编辑。"
        "如需修改规则，更新 JSON 后重新生成。"
    )

    return "\n".join(lines)


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="mp-reader v2.1: 解析已有 Media Plan Excel，输出 Mapping JSON（只读）"
    )
    parser.add_argument("--input",        required=True,  help="原始 MP Excel 文件路径")
    parser.add_argument("--output",       default=None,   help="Mapping JSON 输出路径")
    parser.add_argument("--summary",      default=None,   help="可选：mapping_summary.md 输出路径")
    parser.add_argument("--validate-only", action="store_true", help="仅校验，不输出完整 Mapping")
    args = parser.parse_args()

    mapping = parse_mp(args.input)
    is_valid, errors = validate_mapping(mapping)

    if not is_valid:
        print(json.dumps(
            {"status": "error", "errors": errors},
            ensure_ascii=False, indent=2,
        ))
        sys.exit(1)

    if args.validate_only:
        print(json.dumps({
            "status": "valid",
            "mapping_id": mapping.get("mapping_id"),
            "source_workbook_hash": mapping.get("source_workbook_hash"),
            "sheet_count": mapping["sheet_count"],
            "budget_check_count": len(mapping.get("budget_checks", [])),
            "warnings": mapping.get("warnings", []),
        }, ensure_ascii=False, indent=2))
        return

    output_str = json.dumps(mapping, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output_str, encoding="utf-8")
        result = {
            "status": "ok",
            "mapping_id": mapping.get("mapping_id"),
            "output": args.output,
            "sheet_count": mapping["sheet_count"],
            "budget_check_count": len(mapping.get("budget_checks", [])),
            "warnings": mapping.get("warnings", []),
        }
        if args.summary:
            summary_text = render_summary(mapping)
            Path(args.summary).write_text(summary_text, encoding="utf-8")
            result["summary"] = args.summary
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(output_str)
        if args.summary:
            summary_text = render_summary(mapping)
            Path(args.summary).write_text(summary_text, encoding="utf-8")


if __name__ == "__main__":
    main()
