"""
MediaPlan 阶段合并工具
- 根据 phases 列表在 R2 上重建合并单元格
- 支持任意数量阶段 + 任意空档
- 提供 phase_of_day(day_offset) 查询
"""
from datetime import date, datetime, timedelta
from openpyxl.utils import get_column_letter

from .style_helper import safe_write, copy_cell_style


PHASE_LABEL_ROW = 2
BUDGET_ANCHOR_ROW = 5
DATE_START_COL = 10  # J


def _to_date(d):
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        return datetime.strptime(d, "%Y-%m-%d").date()
    raise ValueError(f"Unsupported date: {d!r}")


def compute_phase_columns(campaign_start, phases):
    """
    给定 campaign_start 和 phases 列表
    返回 [(phase_dict, start_col_idx, end_col_idx), ...]
    列索引是 1-based Excel 列号
    """
    start = _to_date(campaign_start)
    results = []
    for p in phases:
        p_start = _to_date(p.get("start_date", p.get("start", "")))
        p_end = _to_date(p.get("end_date",   p.get("end",   "")))
        day_start = (p_start - start).days
        day_end = (p_end - start).days
        if day_start < 0 or day_end < 0:
            raise ValueError(f"Phase {p['name']} 日期早于 campaign_start")
        col_start = DATE_START_COL + day_start
        col_end = DATE_START_COL + day_end
        results.append((p, col_start, col_end))
    return results


def apply_phase_merges(ws, campaign_start, phases, last_date_col,
                       style_source_cell="J2"):
    """
    在 R2 应用 phase 合并
    - 先解除 R2 上所有日期列区域的合并（避免残留）
    - 为每个 phase 做一次 merge_cells
    - 写入 phase name
    - 在 R5 每个 phase 起始列写 "Budget" 锚点
    """
    # 预处理：解除 R2 上日期列区域的合并
    for mr in list(ws.merged_cells.ranges):
        if mr.min_row == PHASE_LABEL_ROW and mr.max_row == PHASE_LABEL_ROW \
                and mr.min_col >= DATE_START_COL:
            ws.unmerge_cells(str(mr))

    # 清空 R2 上日期列区域现有值
    for c in range(DATE_START_COL, last_date_col + 1):
        ws.cell(row=PHASE_LABEL_ROW, column=c).value = None

    # 清空 R5 上所有 Budget 锚点（J5..last）
    for c in range(DATE_START_COL, last_date_col + 1):
        ws.cell(row=BUDGET_ANCHOR_ROW, column=c).value = None

    phase_cols = compute_phase_columns(campaign_start, phases)
    for p, c_start, c_end in phase_cols:
        if c_end > last_date_col:
            raise ValueError(f"Phase {p['name']} 超出日期轴（last_col={last_date_col}）")

        start_letter = get_column_letter(c_start)
        end_letter = get_column_letter(c_end)

        # 写 phase name（左上角）
        safe_write(ws, PHASE_LABEL_ROW, c_start, p["name"])
        # 从 J2 继承样式
        src_cell = ws[style_source_cell]
        copy_cell_style(src_cell, ws.cell(row=PHASE_LABEL_ROW, column=c_start))

        # 合并
        if c_end > c_start:
            ws.merge_cells(f"{start_letter}{PHASE_LABEL_ROW}:{end_letter}{PHASE_LABEL_ROW}")

        # Budget 锚点
        safe_write(ws, BUDGET_ANCHOR_ROW, c_start, "Budget")

    return phase_cols


def build_day_phase_map(campaign_start, phases, total_days):
    """
    返回 list[int -> phase_dict or None]
    索引 0..total_days-1
    """
    start = _to_date(campaign_start)
    result = [None] * total_days
    phase_by_date = {}
    for p in phases:
        p_start = _to_date(p.get("start_date", p.get("start", "")))
        p_end = _to_date(p.get("end_date",   p.get("end",   "")))
        cur = p_start
        while cur <= p_end:
            phase_by_date[cur] = p
            cur += timedelta(days=1)
    for i in range(total_days):
        d = start + timedelta(days=i)
        result[i] = phase_by_date.get(d)  # None 表示空档
    return result
