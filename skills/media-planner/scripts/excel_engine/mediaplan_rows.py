"""
MediaPlan 数据行工具
- 按数据行数扩展或收缩 R7-R12（默认模板预留 6 行）
- R13 Grand Total 保持在最后一行（锁定）
- 渠道汇总行（R6）公式跟随扩展
- 新行继承 R7 样式 + I 列公式模板
"""
from openpyxl.utils import get_column_letter
from .style_helper import copy_row_style, safe_write


DATA_ROW_START = 7
TEMPLATE_DATA_ROWS = 6
TEMPLATE_DATA_ROW_END = 12
TEMPLATE_GRAND_TOTAL_ROW = 13
CHANNEL_SUM_ROW = 6  # 渠道汇总行（模板 R6）
LINE_TOTAL_COL = 9  # I
DATE_START_COL = 10  # J


def adjust_data_rows(ws, need_rows, last_date_col):
    """
    调整数据行数到 need_rows（模板原 6 行）
    返回：实际的最后数据行号、Grand Total 新行号

    关键：
    - 插入发生在 TEMPLATE_DATA_ROW_END 之后，使 R13 Grand Total 下移
    - R6 和 Grand Total 的公式范围跟着重写
    - 新行从 R7 复制样式，I 列写 Line Total 公式模板
    """
    current_rows = TEMPLATE_DATA_ROWS
    delta = need_rows - current_rows

    if delta > 0:
        # 在 TEMPLATE_DATA_ROW_END 之后插入 delta 行（R13 被推下）
        insert_at = TEMPLATE_DATA_ROW_END + 1  # 即 13 位置，把原 R13 推到 R13+delta
        ws.insert_rows(insert_at, delta)
        # 为新行复制 R7 的样式（整行 + 行高）
        max_col = DATE_START_COL + (last_date_col - DATE_START_COL)  # = last_date_col
        for i in range(delta):
            tgt_row = insert_at + i
            copy_row_style(ws, DATA_ROW_START, tgt_row, 1, last_date_col)
    elif delta < 0:
        # 删除末尾多余数据行（但至少保留 1 行，防止公式范围异常）
        delete_count = min(abs(delta), TEMPLATE_DATA_ROWS - 1)
        delete_at = TEMPLATE_DATA_ROW_END - delete_count + 1
        ws.delete_rows(delete_at, delete_count)

    actual_data_rows = TEMPLATE_DATA_ROWS + delta if delta >= 0 else (TEMPLATE_DATA_ROWS + max(delta, -(TEMPLATE_DATA_ROWS - 1)))
    last_data_row = DATA_ROW_START + actual_data_rows - 1
    grand_total_row = last_data_row + 1
    last_date_letter = get_column_letter(last_date_col)

    # —— 重写每个数据行的 I 列 Line Total 公式（包括新插入的） ——
    for r in range(DATA_ROW_START, last_data_row + 1):
        # 只有当 I 列是空或不是有效公式时才覆盖
        cell = ws.cell(row=r, column=LINE_TOTAL_COL)
        new_formula = f"=SUM(J{r}:{last_date_letter}{r})"
        safe_write(ws, r, LINE_TOTAL_COL, new_formula)

    # —— 重写渠道汇总行（R6）公式 ——
    # I6: =SUM(I7:I<last>)
    safe_write(ws, CHANNEL_SUM_ROW, LINE_TOTAL_COL,
               f"=SUM(I{DATA_ROW_START}:I{last_data_row})")
    # 每日列 R6: =SUM(J7:J<last>) ... 
    for col_idx in range(DATE_START_COL, last_date_col + 1):
        col_letter = get_column_letter(col_idx)
        safe_write(ws, CHANNEL_SUM_ROW, col_idx,
                   f"=SUM({col_letter}{DATA_ROW_START}:{col_letter}{last_data_row})")

    # —— Grand Total 行：清空整行，避免与标签行小计双重计数 ——
    for col_idx in range(1, last_date_col + 1):
        ws.cell(row=grand_total_row, column=col_idx).value = None

    return last_data_row, grand_total_row
