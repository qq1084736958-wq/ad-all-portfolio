"""
MediaPlan 数据写入工具 v3.0（通用渠道版）
- 不内置任何渠道名称、颜色映射或等级判断
- 按 channel 字段分组，每组前插渠道标签行（颜色循环分配）
- reserved_pending 行：日期列留空，Line Total 显示 display_text
- 写入 8 固定字段（A-H）+ Line Total（I）+ 日期列（J 起）
"""
from collections import OrderedDict
import json
from pathlib import Path
from openpyxl.styles import PatternFill, Font
from openpyxl.utils import get_column_letter
from .style_helper import safe_write
from .mediaplan_phases import build_day_phase_map


# 统一字体（所有数据行/标签行强制应用，避免继承宋体等环境默认字体）
_BASE_FONT_NAME = "Microsoft YaHei"
_BASE_FONT_SIZE = 11


def _make_font(bold=False, italic=False, color_rgb=None):
    kwargs = {"name": _BASE_FONT_NAME, "size": _BASE_FONT_SIZE, "bold": bold, "italic": italic}
    if color_rgb:
        from openpyxl.styles import Color
        kwargs["color"] = Color(rgb=color_rgb)
    return Font(**kwargs)


# 固定字段列映射（1-based）
FIELD_COL_MAP = {
    "channel":   1,   # A（通用：渠道/媒体名称）
    "nation":    2,   # B
    "ad_format": 3,   # C
    "goal":      4,   # D
    "product":   5,   # E
    "targeting": 6,   # F
    "placement": 7,   # G
    "creative":  8,   # H
}

DATA_ROW_START = 7
DATE_START_COL = 10  # J

# 颜色轮转池（ARGB，无平台语义，按渠道出现顺序分配）
# 按平台名固定映射，颜色差异拉大，一眼区分不同平台组
_PLATFORM_COLOR_MAP = {
    "meta": "FFFFF2CC",
    "facebook": "FFFFF2CC",
    "instagram": "FFFFF2CC",
    "tiktok": "FFD9D9D9",
    "google": "FFFCE4EC",
    "youtube": "FFFCE4EC",
    "gdn": "FFFCE4EC",
    "display": "FFFCE4EC",
    "search": "FFFCE4EC",
    "sem": "FFFCE4EC",
    "snapchat": "FF9DC3E6",
    "pinterest": "FFFCE4D6",
    "linkedin": "FFD6E8F7",
    "x": "FFD6E4BC",
    "twitter": "FFD6E4BC",
    "reddit": "FFFFF9CC",
    "line": "FFE2EFDA",
    "whatsapp": "FFE2EFDA",
}
_COLOR_DEFAULT = "FFE2E2E2"
_COLOR_POOL_FALLBACK = [
    "FF9DC3E6",
    "FFE2EFDA",
    "FFFCE4D6",
    "FFFFF2CC",
]


def _get_platform_color(group_label):
    label_lower = group_label.lower().strip()
    if label_lower in _PLATFORM_COLOR_MAP:
        return _PLATFORM_COLOR_MAP[label_lower]
    for key, color in _PLATFORM_COLOR_MAP.items():
        if key in label_lower:
            return color
    idx = hash(group_label) % len(_COLOR_POOL_FALLBACK)
    return _COLOR_POOL_FALLBACK[idx]


def _channel_fill(color_argb: str) -> PatternFill:
    return PatternFill(fill_type="solid", fgColor=color_argb)


def _taxonomy_aliases() -> dict[str, tuple[str, str, bool]]:
    """Load aliases plus the owner's explicit subtotal-display policy."""
    taxonomy_path = Path(__file__).resolve().parents[2] / "references" / "media_owner_taxonomy.json"
    try:
        payload = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    aliases: dict[str, tuple[str, str, bool]] = {}
    for owner in payload.get("owners", []):
        owner_name = str(owner.get("name", "")).strip()
        show_owner_total = bool(owner.get("show_owner_total", False))
        for platform in owner.get("platforms", []):
            platform_name = str(platform.get("name", "")).strip()
            for alias in platform.get("aliases", []):
                aliases[str(alias).strip().casefold()] = (owner_name, platform_name, show_owner_total)
    return aliases


def _resolve_hierarchy(unit: dict, aliases: dict[str, tuple[str, str, bool]]) -> tuple[str, str, bool]:
    """Resolve the display label and whether an owner subtotal is permitted.

    Only taxonomy owners explicitly marked ``show_owner_total`` get a parent
    subtotal.  This prevents unrelated media from being visually nested under a
    company merely because they appear next to it in the schedule.
    """
    explicit_owner = unit.get("media_owner") or unit.get("parent_company")
    explicit_child = unit.get("sub_platform")
    legacy_platform = unit.get("platform")
    channel = unit.get("channel")

    # Legacy hierarchy: platform=owner + sub_platform=child.
    if legacy_platform and explicit_child:
        owner = str(legacy_platform).strip()
        child = str(explicit_child).strip()
        allowed = any(value[0].casefold() == owner.casefold() and value[2] for value in aliases.values())
        return owner, child, allowed
    # New hierarchy: media_owner/parent_company + platform/sub_platform=child.
    if explicit_owner:
        owner = str(explicit_owner).strip()
        child = str(explicit_child or legacy_platform or channel or owner).strip()
        allowed = any(value[0].casefold() == owner.casefold() and value[2] for value in aliases.values())
        return owner, child, allowed

    lookup_key = str(channel or legacy_platform or "OTHER").strip().casefold()
    if lookup_key in aliases:
        return aliases[lookup_key]
    # Unknown media stays flat.
    label = str(channel or legacy_platform or "OTHER").strip() or "OTHER"
    return label, label, False


def _group_delivery_units(delivery_units: list) -> "OrderedDict":
    """Return only explicitly allowed owner-total groups; everything else is flat."""
    groups: OrderedDict = OrderedDict()
    aliases = _taxonomy_aliases()
    for unit in delivery_units:
        owner, label, show_owner_total = _resolve_hierarchy(unit, aliases)
        key = (owner, show_owner_total) if show_owner_total else (label, False)
        groups.setdefault(key, [])
        groups[key].append((label, unit))
    return groups


def calc_total_rows(delivery_units: list) -> int:
    """
    计算写入所需总行数：执行行 + 仅限允许的媒体公司合计行。
    """
    groups = _group_delivery_units(delivery_units)
    total = sum(len(units) for units in groups.values())
    owner_rows = sum(
        1 for (_, show_owner_total), units in groups.items()
        if show_owner_total and len(units) > 1
    )
    return total + owner_rows


def _clear_template_summary_rows(ws, data_start_row: int, total_days: int):
    """
    清除模板在数据区之前预置的空白汇总行（如 Row 6 的 SUM 公式行）。
    这些行在模板里是占位符，实际汇总由平台标签行承担，不应双重计数。
    扫描 data_start_row 之前（从 Row 6 起）所有 I 列含 SUM 公式的行并清空。
    """
    for r in range(6, data_start_row):
        cell_i = ws.cell(row=r, column=9)
        val = cell_i.value
        if isinstance(val, str) and val.strip().upper().startswith("=SUM"):
            # 清空 I 列及所有日期列
            cell_i.value = None
            for day_col in range(DATE_START_COL, DATE_START_COL + total_days):
                ws.cell(row=r, column=day_col).value = None



def _write_label_row(ws, row, label, fill, font, total_days, sum_formula):
    """写入平台/子平台标签行：A列标签+颜色+字体，I列汇总公式，日期列填色不填值。"""
    cell = ws.cell(row=row, column=1)
    cell.value = label
    cell.fill = fill
    cell.font = font  # 调用方传入 _make_font(...) 保证字体一致
    for col in range(2, DATE_START_COL):
        c = ws.cell(row=row, column=col)
        c.fill = fill
        c.font = _make_font()  # 统一字体
    for day_offset in range(total_days):
        c = ws.cell(row=row, column=DATE_START_COL + day_offset)
        c.fill = fill
        c.font = _make_font()
    i_cell = ws.cell(row=row, column=9)
    i_cell.value = sum_formula
    i_cell.fill = fill
    i_cell.font = font

def write_ad_sets(ws, ad_sets, campaign_start, phases, total_days):
    """
    v3.0：按 channel 分组写入，颜色轮转（无渠道名称硬编码）。

    delivery_unit 结构：
      {
        "channel":   "渠道名（任意）",
        "nation":    "US",
        "ad_format": "Video",
        "goal":      "Purchase",
        "product":   "Product A",
        "targeting": "Audience A",
        "placement": "Feed",
        "creative":  "15s 竖屏",
        "daily_budget_by_phase": {"Phase_Traffic": 210},
        # 可选：reserved_pending 行
        "budget_field":           "reserved_pending",   # 存在时不写日预算
        "line_total_display":     "待确认预算",           # reserved 行 Line Total 文字
      }

    兼容旧字段 platform（自动映射到 channel）。
    """
    if not ad_sets:
        return

    # 清除模板残留的冒产汇总行（避免双重计数）
    _clear_template_summary_rows(ws, DATA_ROW_START, total_days)

    day_phase_map = build_day_phase_map(campaign_start, phases, total_days)
    groups = _group_delivery_units(ad_sets)
    current_row = DATA_ROW_START
    color_index = 0

    for channel, units in groups.items():
        color_argb = _COLOR_POOL[color_index % len(_COLOR_POOL)]
        color_index += 1
        fill = _channel_fill(color_argb)
        bold_font = Font(bold=True)

        # ── 渠道标签行 ──
        label_cell = ws.cell(row=current_row, column=1)
        label_cell.value = channel
        label_cell.fill = fill
        label_cell.font = bold_font
        for col in range(2, DATE_START_COL):
            ws.cell(row=current_row, column=col).fill = fill

        set_count = len(units)
        ad_row_start = current_row + 1
        ad_row_end   = current_row + set_count
        # 标签行日期列：只填颜色，不写值，避免与数据行双重计数
        for day_offset in range(total_days):
            col = DATE_START_COL + day_offset
            ws.cell(row=current_row, column=col).fill = fill

        # 标签行 I 列：渠道小计（对本渠道数据行的 I 列求和）
        last_date_col = DATE_START_COL + total_days - 1
        last_date_letter = get_column_letter(last_date_col)
        ws.cell(row=current_row, column=9).value = (
            f"=SUM(I{ad_row_start}:I{ad_row_end})"
        )
        ws.cell(row=current_row, column=9).fill = fill
        current_row += 1

        # ── 数据行 ──
        for unit in units:
            is_reserved = unit.get("budget_field") == "reserved_pending"

            for field, col in FIELD_COL_MAP.items():
                # A 列（channel）在数据行留空：平台信息已由上方标签行承载，避免重复
                if field == "channel":
                    val = ""
                else:
                    val = unit.get(field, "")
                if isinstance(val, list):
                    val = ", ".join(str(x) for x in val)
                cell = ws.cell(row=current_row, column=col)
                cell.value = val if val != "" else None
                if is_reserved:
                    cell.fill = fill

            if is_reserved:
                for day_offset in range(total_days):
                    ws.cell(row=current_row, column=DATE_START_COL + day_offset).fill = fill
                display = unit.get("line_total_display", "待确认")
                lt = ws.cell(row=current_row, column=9)
                lt.value = display
                lt.fill = fill
                lt.font = Font(italic=True, color="FF888888")
            else:
                budget_by_phase = unit.get("daily_budget_by_phase", {})
                for day_offset in range(total_days):
                    col = DATE_START_COL + day_offset
                    phase = day_phase_map[day_offset]
                    daily = budget_by_phase.get(phase["name"], 0) if phase else 0
                    if daily > 0:
                        safe_write(ws, current_row, col, daily)

            current_row += 1
def write_ad_sets(ws, ad_sets, campaign_start, phases, total_days):
    """Write a flat media schedule, with owner totals only for allowed owners.

    Google and Meta are configured as owner-total groups in the taxonomy. Their
    children are written directly as executable rows; there is never a separate
    child-platform subtotal row. All other media remain flat execution rows.
    """
    if not ad_sets:
        return

    _clear_template_summary_rows(ws, DATA_ROW_START, total_days)

    day_phase_map = build_day_phase_map(campaign_start, phases, total_days)
    groups = _group_delivery_units(ad_sets)   # {(label, show_owner_total): [(display_label, unit)]}
    current_row = DATA_ROW_START

    for (group_label, configured_owner_total), labelled_units in groups.items():
        show_owner_total = configured_owner_total and len(labelled_units) > 1
        plat_color = _get_platform_color(group_label)
        plat_fill = _channel_fill(plat_color)

        owner_row = None
        if show_owner_total:
            owner_row = current_row
            _write_label_row(ws, owner_row, f"{group_label} 合计", plat_fill,
                             _make_font(bold=True), total_days, "=0")
            current_row += 1

        total_refs = []
        for display_label, unit in labelled_units:
            data_row = current_row
            _write_delivery_unit(ws, data_row, unit, day_phase_map, total_days,
                                 plat_fill, display_label)
            total_refs.append(f"I{data_row}")
            current_row += 1

        if owner_row is not None:
            ws.cell(row=owner_row, column=9).value = (
                f"=SUM({','.join(total_refs)})" if total_refs else "=0"
            )


def _write_delivery_unit(ws, row, unit, day_phase_map, total_days, fill, display_label=None):
    """Write one executable row; group labels own the company/platform hierarchy."""
    is_reserved = unit.get("budget_field") == "reserved_pending"
    for field, col in FIELD_COL_MAP.items():
        val = (display_label or unit.get("channel") or unit.get("platform") or "") if field == "channel" else unit.get(field, "")
        if isinstance(val, list):
            val = ", ".join(str(x) for x in val)
        cell = ws.cell(row=row, column=col)
        cell.value = val if val != "" else None
        cell.font = _make_font()
        if is_reserved:
            cell.fill = fill
    if is_reserved:
        for day_offset in range(total_days):
            ws.cell(row=row, column=DATE_START_COL + day_offset).fill = fill
        lt = ws.cell(row=row, column=9)
        lt.value = unit.get("line_total_display", "待确认")
        lt.fill = fill
        lt.font = Font(italic=True, color="FF888888")
        return
    budget_by_phase = unit.get("daily_budget_by_phase", {})
    last_col_letter = get_column_letter(DATE_START_COL + total_days - 1)
    for day_offset in range(total_days):
        col = DATE_START_COL + day_offset
        phase = day_phase_map[day_offset]
        daily = budget_by_phase.get(phase["name"], 0) if phase else 0
        if daily > 0:
            safe_write(ws, row, col, daily)
            ws.cell(row=row, column=col).font = _make_font()
    ws.cell(row=row, column=9).value = f"=SUM(J{row}:{last_col_letter}{row})"
    ws.cell(row=row, column=9).font = _make_font()
