"""
MediaPlan 日期轴工具
- 扩展/收缩日期列（J..）
- 重写日期/星期公式
- 重写 I 列 Line Total 公式
- 重写渠道汇总行/Grand Total 每日聚合公式
- 正确处理删列时的合并范围收缩
"""
from openpyxl.utils import get_column_letter, column_index_from_string
from .style_helper import copy_col_style, safe_write


# === MediaPlan 模板布局常量 ===
DATE_START_COL = 10       # J
TEMPLATE_DATE_COLS = 46    # J..BC 共 46 天
TEMPLATE_DATE_END_COL = 55 # BC

FORMULA_DATE_ROW = 3
FORMULA_WEEK_ROW = 4

CHANNEL_SUM_ROW = 6  # 渠道汇总行（模板 R6）
DATA_ROW_START = 7
DATA_ROW_END = 12
GRAND_TOTAL_ROW = 13
LINE_TOTAL_COL = 9  # I


def adjust_date_axis(ws, target_days):
    """
    调整 MediaPlan 日期轴到 target_days
    关键：
    - 删列前先解除合并，避免合并范围"撑大"导致列数不缩
    - 新增列继承 BC 列样式
    - 重写所有日期公式和聚合公式
    - 返回最后日期列索引
    """
    current_days = TEMPLATE_DATE_COLS
    delta = target_days - current_days

    # —— 预处理：解除会被影响的合并范围 ——
    # A1:BC1 标题合并 需要重建为 A1:<new_last>1
    # J2:U2 / V2 / W2:BC2 阶段合并 需要在别处另行重建
    preserved_merges = {
        "title_row": None,  # A1:xxx1
        "phase_row": [],    # R2 所有阶段合并范围
    }

    for mr in list(ws.merged_cells.ranges):
        if mr.min_row == 1 and mr.max_row == 1:
            preserved_merges["title_row"] = str(mr)
            ws.unmerge_cells(str(mr))
        elif mr.min_row == 2 and mr.max_row == 2 and mr.min_col >= DATE_START_COL:
            # R2 上的阶段合并，先记录再解除
            preserved_merges["phase_row"].append(str(mr))
            ws.unmerge_cells(str(mr))

    # —— 调整列数 ——
    if delta > 0:
        insert_at = TEMPLATE_DATE_END_COL + 1
        ws.insert_cols(insert_at, delta)
        src_col = TEMPLATE_DATE_END_COL
        for i in range(delta):
            tgt_col = insert_at + i
            copy_col_style(ws, src_col, tgt_col, 1, GRAND_TOTAL_ROW)
    elif delta < 0:
        delete_count = abs(delta)
        delete_from = TEMPLATE_DATE_END_COL - delete_count + 1
        ws.delete_cols(delete_from, delete_count)

    final_last_col = DATE_START_COL + target_days - 1
    final_last_letter = get_column_letter(final_last_col)

    # —— 重写每日公式（R3 日期、R4 星期）——
    for offset in range(target_days):
        col_idx = DATE_START_COL + offset
        col_letter = get_column_letter(col_idx)
        safe_write(ws, FORMULA_DATE_ROW, col_idx, f"=$B$2+{offset}")
        safe_write(ws, FORMULA_WEEK_ROW, col_idx,
                   f'=TEXT({col_letter}{FORMULA_DATE_ROW},"aaa")')

    # —— 重写 I 列 Line Total ——（每个数据行 I = SUM(J:final_last)）
    for data_row in range(DATA_ROW_START, DATA_ROW_END + 1):
        safe_write(ws, data_row, LINE_TOTAL_COL,
                   f"=SUM(J{data_row}:{final_last_letter}{data_row})")

    # —— 重写渠道汇总行（R6）/ Grand Total（R13）每日公式 ——
    for offset in range(target_days):
        col_idx = DATE_START_COL + offset
        col_letter = get_column_letter(col_idx)
        safe_write(ws, CHANNEL_SUM_ROW, col_idx,
                   f"=SUM({col_letter}{DATA_ROW_START}:{col_letter}{DATA_ROW_END})")
        safe_write(ws, GRAND_TOTAL_ROW, col_idx,
                   f"=SUM({col_letter}{DATA_ROW_START}:{col_letter}{DATA_ROW_END})")

    # —— 重建标题合并 A1:<new_last>1 ——
    ws.merge_cells(f"A1:{final_last_letter}1")

    return final_last_col, preserved_merges
