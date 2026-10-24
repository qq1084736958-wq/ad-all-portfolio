"""strategy_engines.py — 策略层确定性引擎（v1.6 策略生成层）

本模块只承载“可被代码验收”的策略数学与硬约束，不承载任何渠道专属知识：

- allocate_matrix()：平台 × 阶段二维预算矩阵
    * 行/列边际用最大余数法按权重分配，总额精确守恒（最小货币单位整数）
    * 支持 cell_overrides 固定格，残差按比例 + 西北角法补齐，保证行和=列和=总额
    * 预留预算作为“伪平台行”（is_reserve）参与守恒，但不进入平台优先级比较
    * 平台优先级（客户显式给出时）行总额必须单调不增，否则 BLOCK

- kpi_budget_feasibility()：由预算与目标量级反推隐含单价（CPM/CPC/CPA），
  与证据区间比对；公开 benchmark 只给 WARN，硬证据才允许 BLOCK。

- evaluate_strategy_gates()：供 plan_core.preflight 调用的策略层门禁集合：
    matrix_three_way_conservation / schedule_rollup_matches_matrix /
    reserve_not_in_scheduled_spend / platform_priority_monotonic /
    cold_start_remarketing_check / kpi_budget_feasibility

渠道名称、阶段名称都只是数据；本文件不出现任何平台枚举或行业经验值。
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _num(value: Any, field: str = "value") -> Decimal:
    try:
        d = Decimal(str(value))
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"{field} must be numeric, got {value!r}") from exc
    if not d.is_finite() or d < 0:
        raise ValueError(f"{field} must be a finite non-negative number, got {value!r}")
    return d


# ---------------------------------------------------------------------------
# Config file loaders (v1.9: externalize defaults from code)
# ---------------------------------------------------------------------------

def _load_json_config(filename: str) -> dict:
    """Load a JSON config from references/ directory."""
    import json
    refs_dir = Path(__file__).resolve().parent.parent / "references"
    path = refs_dir / filename
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_default_cpm(platform: str, market_tier: str = "emerging") -> dict:
    """Fallback CPM when no search evidence exists."""
    config = _load_json_config("platform-cpm-defaults.json")
    tiers = config.get("market_tiers", {})
    tier_data = tiers.get(market_tier, tiers.get("emerging", {}))
    plat_lower = platform.lower()
    platform_data = tier_data.get(plat_lower, tier_data.get("default", {}))
    if not platform_data:
        return {"cpm_mid": 5.0, "reach_potential": 0.4, "evidence_source": "default_fallback"}
    return {
        "cpm_mid": platform_data.get("cpm_mid", 5.0),
        "reach_potential": platform_data.get("reach_potential", 0.4),
        "evidence_source": f"default_{market_tier}",
    }


def _get_phase_prior(profile_name: str = "new_launch") -> dict:
    """Load phase weight prior from config file."""
    config = _load_json_config("phase-prior-profiles.json")
    profiles = config.get("profiles", {})
    profile = profiles.get(profile_name, profiles.get("new_launch", {}))
    phases = profile.get("phases", [])
    result = {}
    for ph in phases:
        obj = ph.get("objective", "")
        result[obj] = ph.get("share", 0.25)
    return result


def _apply_llm_adjustment(shares: list, target_idx: int, delta: Decimal, min_share: Decimal = Decimal("0.01")) -> tuple[list, Decimal]:
    """Apply LLM delta precisely to target, redistribute excess proportionally to others.
    
    Instead of global renormalization (which dilutes the delta), this:
    1. Applies delta to target (clamped to min_share)
    2. Redistributes the excess/deficit proportionally to all other items
    3. Returns (new_shares, actual_delta) where actual_delta is the real change
    """
    n = len(shares)
    if n < 2:
        return shares, Decimal("0")
    
    old_target = shares[target_idx]
    new_target = max(old_target + delta, min_share)
    actual_delta = new_target - old_target
    
    # Excess to redistribute = -actual_delta (if target went down, others go up)
    excess = -actual_delta
    
    # Sum of all other shares
    other_sum = sum(shares[i] for i in range(n) if i != target_idx)
    if other_sum <= 0:
        return shares, Decimal("0")
    
    new_shares = list(shares)
    new_shares[target_idx] = new_target
    for i in range(n):
        if i != target_idx:
            new_shares[i] = shares[i] + excess * (shares[i] / other_sum)
    
    # Verify sum is ~1.0
    total = sum(new_shares)
    if abs(total - Decimal("1")) > Decimal("0.001"):
        # Fallback: normalize as last resort
        new_shares = [s / total for s in new_shares]
    
    return new_shares, actual_delta


def normalize_budget(payload: dict) -> dict:
    """v1.9: Normalize budget to net media spend caliber.
    
    payload:
      total_budget: float (as stated by client)
      budget_caliber: {
        "caliber": "gross" | "net",  # gross=含税总价, net=纯媒体采买
        "tax_rate": float (default 0.16),
        "service_fee_rate": float (default 0),
        "rebate_rate": float (default 0)
      }
    
    Returns:
      original_budget: as stated
      net_budget: usable media spend
      adjustments: list of deductions applied
      caliber_status: "confirmed" | "assumed_gross"
    """
    original = Decimal(str(payload.get("total_budget", 0)))
    if original <= 0:
        raise ValueError("total_budget must be positive")
    
    caliber = payload.get("budget_caliber", {})
    is_gross = caliber.get("caliber", "gross") == "gross"
    tax_rate = Decimal(str(caliber.get("tax_rate", 0.16)))
    service_fee = Decimal(str(caliber.get("service_fee_rate", 0)))
    rebate = Decimal(str(caliber.get("rebate_rate", 0)))
    
    adjustments = []
    net = original
    
    if is_gross:
        net = net / (Decimal("1") + tax_rate)
        adjustments.append(f"含税价÷(1+{float(tax_rate):.0%}) = 不含税价")
    
    if service_fee > 0:
        net = net * (Decimal("1") - service_fee)
        adjustments.append(f"扣除服务费 {float(service_fee):.0%}")
    
    if rebate > 0:
        net = net * (Decimal("1") + rebate)
        adjustments.append(f"加回返点 {float(rebate):.0%}")
    
    assumed = "caliber" not in payload or "caliber" not in caliber
    caliber_status = "assumed_gross" if assumed else "confirmed"
    
    return {
        "original_budget": float(original),
        "net_budget": float(net.quantize(Decimal("0.01"))),
        "currency": payload.get("currency", "USD"),
        "caliber_status": caliber_status,
        "adjustments": adjustments,
        "tax_rate": float(tax_rate),
        "service_fee_rate": float(service_fee),
        "rebate_rate": float(rebate),
        "generated_by": "strategy_engines.normalize_budget",
    }


# Approximate exchange rates (as of 2026-09, for fallback only)
_FALLBACK_EXCHANGE = {
    "USD": 1.0,
    "LKR": 305.0,
    "INR": 83.0,
    "IDR": 16000.0,
    "PHP": 56.0,
    "VND": 25000.0,
    "THB": 36.0,
    "MYR": 4.7,
    "BRL": 5.4,
    "MXN": 18.0,
    "NGN": 1500.0,
    "KES": 129.0,
    "EGP": 49.0,
}


def currency_convert(payload: dict) -> dict:
    """v1.9: Convert any currency to USD for CPM-based calculations.
    
    payload:
      amount: float
      from_currency: str (e.g. "LKR")
      to_currency: str (default "USD")
      rate: float? (optional, if not provided uses fallback table)
    
    Returns:
      converted_amount, rate_used, rate_source
    """
    amount = Decimal(str(payload.get("amount", 0)))
    from_cur = payload.get("from_currency", "USD").upper()
    to_cur = payload.get("to_currency", "USD").upper()
    
    if from_cur == to_cur:
        return {
            "original_amount": float(amount),
            "converted_amount": float(amount),
            "from_currency": from_cur,
            "to_currency": to_cur,
            "rate": 1.0,
            "rate_source": "same_currency",
        }
    
    # Use provided rate if available
    if "rate" in payload:
        rate = Decimal(str(payload["rate"]))
        source = "user_provided"
    else:
        # Use fallback table
        from_usd = Decimal(str(_FALLBACK_EXCHANGE.get(from_cur, 1.0)))
        to_usd = Decimal(str(_FALLBACK_EXCHANGE.get(to_cur, 1.0)))
        rate = from_usd / to_usd
        source = "fallback_table"
    
    converted = amount / rate
    
    return {
        "original_amount": float(amount),
        "converted_amount": float(converted.quantize(Decimal("0.01"))),
        "from_currency": from_cur,
        "to_currency": to_cur,
        "rate": float(rate),
        "rate_source": source,
        "note": "Fallback rate used. Verify with current market rate." if source == "fallback_table" else None,
        "generated_by": "strategy_engines.currency_convert",
    }


# Budget benchmarks by product tier and market tier (USD)
_BUDGET_BENCHMARKS = {
    "frontier": {
        "entry": {"low": 5000, "mid": 15000, "high": 30000},
        "mid": {"low": 10000, "mid": 25000, "high": 50000},
        "premium": {"low": 20000, "mid": 50000, "high": 100000},
    },
    "emerging": {
        "entry": {"low": 10000, "mid": 30000, "high": 60000},
        "mid": {"low": 20000, "mid": 50000, "high": 100000},
        "premium": {"low": 40000, "mid": 100000, "high": 200000},
    },
    "developed": {
        "entry": {"low": 20000, "mid": 50000, "high": 100000},
        "mid": {"low": 40000, "mid": 100000, "high": 200000},
        "premium": {"low": 100000, "mid": 250000, "high": 500000},
    },
}


def suggest_budget(payload: dict) -> dict:
    """v1.9: Suggest a budget range when client hasn't specified.
    
    payload:
      market_tier: "frontier" | "emerging" | "developed"
      product_tier: "entry" | "mid" | "premium"
      campaign_weeks: int (default 4)
      audience_size: int? (optional, for reach-based estimate)
      kpi_target_reach_pct: float? (optional, e.g. 0.25)
    """
    market_tier = payload.get("market_tier", "emerging")
    product_tier = payload.get("product_tier", "mid")
    weeks = int(payload.get("campaign_weeks", 4))
    
    tier_data = _BUDGET_BENCHMARKS.get(market_tier, _BUDGET_BENCHMARKS["emerging"])
    range_data = tier_data.get(product_tier, tier_data["mid"])
    
    # Adjust by duration (benchmarks assume 4 weeks)
    duration_factor = weeks / 4.0
    low = range_data["low"] * duration_factor
    mid = range_data["mid"] * duration_factor
    high = range_data["high"] * duration_factor
    
    result = {
        "market_tier": market_tier,
        "product_tier": product_tier,
        "campaign_weeks": weeks,
        "suggested_budget_usd": {
            "low": round(low, -2),
            "mid": round(mid, -2),
            "high": round(high, -2),
        },
        "rationale": f"{market_tier}市场 × {product_tier}产品 × {weeks}周投放",
        "note": "This is a directional estimate. Final budget depends on specific goals and channel mix.",
        "generated_by": "strategy_engines.suggest_budget",
    }
    
    # If audience size and reach target provided, calculate reach-based estimate
    audience_size = payload.get("audience_size")
    target_reach_pct = payload.get("kpi_target_reach_pct")
    if audience_size and target_reach_pct:
        # Rough estimate: CPM = $3 (frontier), frequency = 3
        cpm = {"frontier": 3, "emerging": 6, "developed": 12}.get(market_tier, 6)
        target_reach = float(audience_size) * float(target_reach_pct)
        needed_impressions = target_reach * 3.0  # frequency = 3
        reach_budget = needed_impressions / 1000 * cpm
        result["reach_based_estimate_usd"] = round(reach_budget, -2)
        result["reach_based_note"] = f"基于 {target_reach_pct*100:.0f}% reach 目标反推，CPM=${cpm}, frequency=3"
    
    return result


def _largest_remainder(weights: list[Decimal], total_units: int) -> list[int]:
    """把整数总额按非负权重分配为整数，最大余数法保证逐项非负且和=总额。"""
    if total_units < 0:
        raise ValueError("total_units must be non-negative")
    ws = [max(w, Decimal(0)) for w in weights]
    weight_sum = sum(ws)
    if weight_sum <= 0:
        raise ValueError("weights must sum to a positive number")
    exact = [Decimal(total_units) * w / weight_sum for w in ws]
    floors = [int(x.to_integral_value(rounding=ROUND_FLOOR)) for x in exact]
    remainder = total_units - sum(floors)
    order = sorted(
        range(len(ws)),
        key=lambda i: (exact[i] - Decimal(floors[i]), -i),
        reverse=True,
    )
    for i in order[:remainder]:
        floors[i] += 1
    return floors


def _amount(units: int, unit: Decimal) -> float:
    value = unit * Decimal(units)
    if unit == int(unit):
        return int(value)
    return float(value.quantize(Decimal("0.01")))


# ---------------------------------------------------------------------------
# 平台 × 阶段预算矩阵
# ---------------------------------------------------------------------------

def allocate_matrix(payload: dict) -> dict:
    """生成平台×阶段预算矩阵，三向（行/列/总额）精确守恒。

    payload:
      total_budget : 数值
      minor_unit   : 最小货币单位（默认 0.01；整数预算可传 1）
      platforms    : [{"name": str, "weight": 数值, "is_reserve": bool?}]
      phases       : [{"name": str, "weight": 数值}]
      cell_overrides : {"平台名||阶段名": 金额, ...}（可选，固定格金额）
      platform_priority : [平台名, ...]（客户显式优先级，靠前=预算应更多）
      priority_strict   : True 时违反单调性给 BLOCK，否则 WARN（默认 True）
    """
    unit = _num(payload.get("minor_unit", 0.01), "minor_unit")
    if unit <= 0:
        raise ValueError("minor_unit must be positive")
    total_amount = _num(payload["total_budget"], "total_budget")
    total_units = int((total_amount / unit).to_integral_value(rounding=ROUND_FLOOR))
    if total_amount != unit * Decimal(total_units):
        raise ValueError("total_budget must be a multiple of minor_unit")

    platforms = payload.get("platforms", [])
    phases = payload.get("phases", [])
    if not platforms or not phases:
        raise ValueError("platforms and phases must both be non-empty")

    platform_names = [str(p["name"]) for p in platforms]
    phase_names = [str(p["name"]) for p in phases]
    if len(set(platform_names)) != len(platform_names) or len(set(phase_names)) != len(phase_names):
        raise ValueError("platform and phase names must be unique")

    reserve_names = {
        str(p["name"]) for p in platforms if p.get("is_reserve")
    }
    row_units = _largest_remainder(
        [_num(p.get("weight", 0), f"platform:{p.get('name')}.weight") for p in platforms],
        total_units,
    )
    col_units = _largest_remainder(
        [_num(p.get("weight", 0), f"phase:{p.get('name')}.weight") for p in phases],
        total_units,
    )
    row_margin = dict(zip(platform_names, row_units))
    col_margin = dict(zip(phase_names, col_units))

    # --- 固定格 -------------------------------------------------------------
    fixed: dict[tuple[str, str], int] = {}
    raw_overrides = payload.get("cell_overrides", {}) or {}
    for key, amount in raw_overrides.items():
        if "||" not in key:
            raise ValueError(f"cell_overrides key must be '平台||阶段', got {key!r}")
        pname, phname = [part.strip() for part in key.split("||", 1)]
        if pname not in row_margin:
            raise ValueError(f"cell_overrides references unknown platform {pname!r}")
        if phname not in col_margin:
            raise ValueError(f"cell_overrides references unknown phase {phname!r}")
        amt_units = int((_num(amount, f"override:{key}") / unit).to_integral_value(rounding=ROUND_FLOOR))
        if amt_units * unit != _num(amount, f"override:{key}"):
            raise ValueError(f"cell_overrides {key} amount must be a multiple of minor_unit")
        fixed[(pname, phname)] = amt_units

    fixed_row = {name: 0 for name in platform_names}
    fixed_col = {name: 0 for name in phase_names}
    for (pname, phname), units in fixed.items():
        fixed_row[pname] += units
        fixed_col[phname] += units
    for name, units in fixed_row.items():
        if units > row_margin[name]:
            raise ValueError(f"cell_overrides for platform {name!r} exceed its row margin")
    for name, units in fixed_col.items():
        if units > col_margin[name]:
            raise ValueError(f"cell_overrides for phase {name!r} exceed its column margin")

    # --- 残差矩阵：比例取整 + 余数西北角补齐 --------------------------------
    rem_row = {name: row_margin[name] - fixed_row[name] for name in platform_names}
    rem_col = {name: col_margin[name] - fixed_col[name] for name in phase_names}
    residual_total = sum(rem_row.values())
    if residual_total != sum(rem_col.values()):
        raise ValueError("residual row/column margins diverge after applying overrides")

    cells: dict[tuple[str, str], int] = dict(fixed)
    free = [(p, ph) for p in platform_names for ph in phase_names if (p, ph) not in fixed]
    floors = {key: 0 for key in free}
    if residual_total > 0:
        if fixed:
            # 受限运输问题（存在固定格/禁格）：比例 floor 本身可能不可行。
            # 改用自由度升序西北角法——最受限的行/列先分配，跳过固定格；
            # 只要固定格模式可行就能精确满足全部边际。
            row_order = sorted(
                platform_names,
                key=lambda n: (sum(1 for ph in phase_names if (n, ph) not in fixed),
                               platform_names.index(n)),
            )
            col_order = sorted(
                phase_names,
                key=lambda n: (sum(1 for p in platform_names if (p, n) not in fixed),
                               phase_names.index(n)),
            )
            rem_row_count = dict(rem_row)
            rem_col_count = dict(rem_col)
            for pname in row_order:
                for phname in col_order:
                    if (pname, phname) in fixed:
                        continue
                    add = min(rem_row_count[pname], rem_col_count[phname])
                    floors[(pname, phname)] = add
                    rem_row_count[pname] -= add
                    rem_col_count[phname] -= add
            if sum(rem_row_count.values()) or sum(rem_col_count.values()):
                raise ValueError(
                    "matrix fitting failed: cell_overrides pattern makes the residual matrix infeasible"
                )
        else:
            # 完整二部图：比例 floor + 按比例缺口饱和补齐，结果贴近比例分布
            exact = {}
            for key in free:
                pname, phname = key
                exact[key] = Decimal(rem_row[pname]) * Decimal(rem_col[phname]) / Decimal(residual_total)
                floors[key] = int(exact[key].to_integral_value(rounding=ROUND_FLOOR))
            rem_row_count = {name: rem_row[name] for name in platform_names}
            rem_col_count = {name: rem_col[name] for name in phase_names}
            for key, val in floors.items():
                pname, phname = key
                rem_row_count[pname] -= val
                rem_col_count[phname] -= val
            while sum(rem_row_count.values()) > 0:
                open_cells = [
                    key for key in free
                    if rem_row_count[key[0]] > 0 and rem_col_count[key[1]] > 0
                ]
                if not open_cells:
                    raise ValueError("matrix fitting failed on the complete graph")

                def _gap(key):
                    pname, phname = key
                    continuous = Decimal(rem_row[pname]) * Decimal(rem_col[phname]) / Decimal(residual_total)
                    return continuous - Decimal(floors[key])

                key = max(
                    open_cells,
                    key=lambda k: (_gap(k), -platform_names.index(k[0]), -phase_names.index(k[1])),
                )
                pname, phname = key
                add = min(rem_row_count[pname], rem_col_count[phname])
                floors[key] += add
                rem_row_count[pname] -= add
                rem_col_count[phname] -= add
        for key, val in floors.items():
            cells[key] = val

    # --- 组装输出 -----------------------------------------------------------
    cell_rows = []
    for pname in platform_names:
        row_cells = []
        for phname in phase_names:
            row_cells.append({
                "platform": pname,
                "phase": phname,
                "amount": _amount(cells.get((pname, phname), 0), unit),
            })
        cell_rows.append(row_cells)

    rows_out = [
        {"platform": name, "amount": _amount(row_margin[name], unit),
         "is_reserve": name in reserve_names}
        for name in platform_names
    ]
    cols_out = [
        {"phase": name, "amount": _amount(col_margin[name], unit)}
        for name in phase_names
    ]
    row_sum = sum(row_margin.values())
    col_sum = sum(col_margin.values())
    cell_sum = sum(cells.values())

    issues: list[dict] = []
    # --- 平台优先级单调性 ---------------------------------------------------
    priority = payload.get("platform_priority") or []
    if priority:
        strict = payload.get("priority_strict", True)
        ranked = [(name, row_margin[name]) for name in priority if name in row_margin and name not in reserve_names]
        for (n1, a), (n2, b) in zip(ranked, ranked[1:]):
            if a < b:
                issues.append({
                    "severity": "BLOCK" if strict else "WARN",
                    "rule": "platform_priority_monotonic",
                    "detail": f"客户显式优先级 {n1} > {n2}，但矩阵预算 {_amount(a, unit)} < {_amount(b, unit)}。",
                    "action": "调整平台权重使预算随客户显式优先级单调不增，或回到客户处确认优先级。",
                })

    return {
        "generated_by": "strategy_engines.allocate_matrix",
        "total_budget": _amount(total_units, unit),
        "minor_unit": float(unit),
        "platforms": rows_out,
        "phases": cols_out,
        "cells": [cell for row in cell_rows for cell in row],
        "totals": {
            "row_sum": _amount(row_sum, unit),
            "column_sum": _amount(col_sum, unit),
            "cell_sum": _amount(cell_sum, unit),
        },
        "conserved": row_sum == col_sum == cell_sum == total_units,
        "reserve_platforms": sorted(reserve_names),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# 矩阵 → 日预算排期反算（④ writer 只接受"每阶段一个日预算"）
# ---------------------------------------------------------------------------

def derive_daily_schedule(payload: dict) -> dict:
    """由预算矩阵 cells + 阶段天数反算每个平台的 daily_budget_by_phase。

    ④ writer 对同一阶段的每一天写同一个日预算值，因此本函数：
      daily = round(matrix_cell / phase_days, 2位小数)
    尾差（每格 ≤ 0.005×天数，货币分级取整所致）逐格记录并汇总，
    与 evaluate_strategy_gates 的排期互溯容差（max(1, total*1e-4)）对齐；
    预留行不排日预算，金额以 reserved_amount 挂在行上供生成器守恒校验。

    payload:
      matrix : allocate_matrix 的原样输出（含 cells/platforms）
      phases : [{"name": str, "days": int}] 或带 start_date/end_date
      daily_minor_unit : 日预算最小单位，默认 0.01
    """
    matrix = payload.get("matrix") or payload.get("budget_matrix")
    if not matrix or matrix.get("generated_by") != "strategy_engines.allocate_matrix":
        raise ValueError("matrix 必须是 allocate_matrix 的原样输出（含 generated_by 戳记）")
    phases = payload.get("phases", [])
    if not phases:
        raise ValueError("phases must be non-empty")
    days_by_name = {ph["name"]: _phase_days(ph) for ph in phases}
    missing_days = [name for name, d in days_by_name.items() if not d]
    if missing_days:
        raise ValueError(f"阶段缺少天数/日期，无法反算日预算: {missing_days}")

    cent = Decimal(str(payload.get("daily_minor_unit", 0.01)))
    reserve_names = set(matrix.get("reserve_platforms", []))

    cell_index = {(c["platform"], c["phase"]): Decimal(str(c["amount"]))
                  for c in matrix.get("cells", [])}

    units, reserve_units = [], []
    max_abs_delta = Decimal("0")
    for row in matrix.get("platforms", []):
        name = row["platform"]
        if row.get("is_reserve") or name in reserve_names:
            reserve_units.append({
                "channel": name,
                "budget_field": "reserved_pending",
                "reserved_amount": float(row["amount"]),
                "line_total_display": f"预留待确认（{row['amount']:g}）",
                "daily_budget_by_phase": {},
            })
            continue
        daily_map, phase_spend = {}, {}
        line_total = Decimal("0")
        for ph_name, days in days_by_name.items():
            cell_amount = cell_index.get((name, ph_name), Decimal("0"))
            daily = (cell_amount / Decimal(days)).quantize(cent)
            spend = daily * Decimal(days)
            delta = spend - cell_amount
            if abs(delta) > abs(max_abs_delta):
                max_abs_delta = delta
            daily_map[ph_name] = float(daily)
            phase_spend[ph_name] = float(spend)
            line_total += spend
        units.append({
            "channel": name,
            "daily_budget_by_phase": daily_map,
            "phase_spend": phase_spend,
            "line_total": float(line_total.quantize(cent)),
            "line_total_delta_vs_matrix": float((line_total - Decimal(str(
                next(r["amount"] for r in matrix["platforms"] if r["platform"] == name)
            ))).quantize(cent)),
        })

    scheduled_total = sum((Decimal(str(u["line_total"])) for u in units), Decimal("0"))
    reserve_total = sum((Decimal(str(u["reserved_amount"])) for u in reserve_units), Decimal("0"))
    matrix_total = Decimal(str(matrix["totals"]["cell_sum"]))
    grand = scheduled_total + reserve_total
    tolerance = max(Decimal("1"), matrix_total * Decimal("0.0001"))
    return {
        "generated_by": "strategy_engines.derive_daily_schedule",
        "phases": [{"name": n, "days": d} for n, d in days_by_name.items()],
        "units": units,
        "reserve_units": reserve_units,
        "scheduled_total": float(scheduled_total.quantize(cent)),
        "reserve_total": float(reserve_total.quantize(cent)),
        "matrix_total": float(matrix_total),
        "grand_total": float(grand.quantize(cent)),
        "max_cell_rounding_delta": float(max_abs_delta.quantize(cent)),
        "within_generation_tolerance": abs(grand - matrix_total) <= tolerance,
        "tolerance": float(tolerance),
    }


# ---------------------------------------------------------------------------
# KPI 量级可行性（漏斗数学反推单价）
# ---------------------------------------------------------------------------

# 目标量级指标 -> (成本指标, 成本=预算/量级*factor)
_VOLUME_COST = {
    "impressions": ("cpm", Decimal(1000)),
    "reach": ("cpm", Decimal(1000)),
    "clicks": ("cpc", Decimal(1)),
    "landing_page_visits": ("cpc", Decimal(1)),
    "conversions": ("cpa", Decimal(1)),
    "orders": ("cpa", Decimal(1)),
}


def kpi_budget_feasibility(payload: dict) -> dict:
    """由预算与目标量级反推隐含单价，与证据区间比对。

    payload:
      budget : 数值
      items  : [{
        "metric": impressions|reach|clicks|landing_page_visits|conversions|orders,
        "target": 目标量级,
        "evidence_low": 单价区间下限, "evidence_high": 上限,
        "admissibility": "hard_check_allowed" | "directional_only" | ...,
        "source_ref": str?
      }]
    """
    budget = _num(payload.get("budget", payload.get("total_budget", 0)), "budget")
    results = []
    issues = []
    for idx, item in enumerate(payload.get("items", [])):
        metric = str(item["metric"]).lower()
        if metric not in _VOLUME_COST:
            raise ValueError(f"unsupported volume metric: {metric}")
        cost_metric, factor = _VOLUME_COST[metric]
        target = _num(item["target"], f"items[{idx}].target")
        if target <= 0:
            raise ValueError(f"items[{idx}].target must be positive")
        # 桶级预算覆盖：漏斗桶 KPI（如 R&F reach、DI LPV）应按桶预算验，不用总预算。
        item_budget = _num(item.get("budget", budget), f"items[{idx}].budget")
        # reach 的成本口径是"每千次曝光"：有效曝光 = reach × 频次。
        # item.frequency 缺省 1（即直接把 target 当曝光量）；R&F 3+ reach 传 frequency=3。
        freq = _num(item.get("frequency", 1.0), f"items[{idx}].frequency")
        effective_target = target * freq if metric == "reach" else target
        implied = (item_budget / effective_target * factor).quantize(Decimal("0.0001"))
        low = _num(item.get("evidence_low", 0), f"items[{idx}].evidence_low")
        high = _num(item.get("evidence_high", 0), f"items[{idx}].evidence_high")
        if low > high:
            low, high = high, low
        in_range = low <= implied <= high if high > 0 else True
        hard_allowed = item.get("admissibility") == "hard_check_allowed"
        severity = "PASS" if in_range or high == 0 else ("BLOCK" if hard_allowed else "WARN")
        detail = (
            f"目标 {metric}={float(target):g}（预算={float(item_budget):g}"
            + (f"，频次={float(freq):g}" if metric == "reach" and freq != 1.0 else "")
            + f"）隐含 {cost_metric}={float(implied):g}"
            + (f"，证据区间 [{float(low):g}, {float(high):g}]" if high > 0 else "，缺少证据区间")
        )
        result = {
            "metric": metric,
            "target": float(target),
            "budget": float(item_budget),
            "frequency": float(freq) if metric == "reach" else 1.0,
            "implied_cost_metric": cost_metric,
            "implied_cost": float(implied),
            "evidence_range": [float(low), float(high)] if high > 0 else None,
            "in_evidence_range": bool(in_range),
            "severity": severity,
            "source_ref": item.get("source_ref"),
            "detail": detail,
        }
        results.append(result)
        if severity in ("BLOCK", "WARN"):
            issues.append({
                "severity": severity,
                "rule": "kpi_budget_feasibility",
                "detail": result["detail"],
                "action": "重算目标量级或补充同口径成本证据；不得改写客户已确认 KPI，应单列建议。",
            })
    return {"result": "BLOCK" if any(i["severity"] == "BLOCK" for i in issues)
            else "WARN" if issues else "PASS",
            "items": results, "issues": issues}


# ---------------------------------------------------------------------------
# preflight 策略层门禁
# ---------------------------------------------------------------------------

def _phase_days(phase: dict, campaign_start=None) -> int | None:
    if phase.get("days") is not None:
        return int(phase["days"])
    try:
        from datetime import date
        s = date.fromisoformat(str(phase.get("start_date", phase.get("start")))[:10])
        e = date.fromisoformat(str(phase.get("end_date", phase.get("end")))[:10])
        return (e - s).days + 1
    except Exception:
        return None


def _scheduled_rollup(delivery_units: list, phases: list) -> tuple[dict, dict, float, list]:
    """按 平台/阶段 汇总日预算×天数，返回 (by_platform, by_phase, scheduled_total, problems)。"""
    days_by_name = {ph.get("name"): _phase_days(ph) for ph in phases}
    by_platform: dict[str, float] = {}
    by_phase: dict[str, float] = {}
    scheduled_total = 0.0
    problems = []
    for idx, unit in enumerate(delivery_units):
        if unit.get("budget_field") == "reserved_pending":
            daily_map = unit.get("daily_budget_by_phase", {})
            leaked = {k: v for k, v in daily_map.items() if v not in (None, 0)}
            if leaked:
                problems.append({
                    "severity": "BLOCK",
                    "rule": "reserve_not_in_scheduled_spend",
                    "detail": f"delivery_units[{idx}] 是预留待确认行，却配置了日预算 {leaked}。",
                    "action": "预留行不得进入排期消耗；把金额移回矩阵预留行或改为正式投放单元。",
                })
            continue
        name = unit.get("channel") or unit.get("platform") or f"unit_{idx}"
        daily_map = unit.get("daily_budget_by_phase", {})
        for ph_name, daily in daily_map.items():
            daily = float(daily or 0)
            days = days_by_name.get(ph_name)
            if days is None:
                problems.append({
                    "severity": "BLOCK",
                    "rule": "schedule_phase_unknown",
                    "detail": f"delivery_units[{idx}] 引用了未定义阶段 {ph_name!r}。",
                    "action": "在 phases 中补齐该阶段及天数，或改正引用。",
                })
                continue
            amount = daily * days
            by_platform[name] = by_platform.get(name, 0.0) + amount
            by_phase[ph_name] = by_phase.get(ph_name, 0.0) + amount
            scheduled_total += amount
    return by_platform, by_phase, scheduled_total, problems


def evaluate_strategy_gates(payload: dict) -> list[dict]:
    """返回策略层门禁发现的问题（plain dict，由 plan_core 转成标准 issue）。"""
    findings: list[dict] = []
    # 【2026-09 停用】强制 E0-E6 七块齐全+逐块结构门禁压垮 LLM 泛化，已停用；保留纯算术守恒门禁。
    #findings.extend(evaluate_engine_output_gates(payload))
    total = float(_num(payload.get("total_budget", 0), "total_budget"))
    matrix = payload.get("budget_matrix")
    delivery_units = payload.get("delivery_units", [])
    phases = payload.get("phases", [])

    # --- 矩阵三向守恒（从 cells 重算，不信任传入的 totals）-------------------
    if matrix:
        cells = matrix.get("cells", [])
        row_sum: dict[str, float] = {}
        col_sum: dict[str, float] = {}
        grand = 0.0
        for c in cells:
            amount = float(c.get("amount", 0))
            row_sum[c["platform"]] = row_sum.get(c["platform"], 0.0) + amount
            col_sum[c["phase"]] = col_sum.get(c["phase"], 0.0) + amount
            grand += amount
        tol = max(0.01, abs(total) * 1e-6)
        declared_rows = {r["platform"]: float(r["amount"]) for r in matrix.get("platforms", [])}
        declared_cols = {c["phase"]: float(c["amount"]) for c in matrix.get("phases", [])}
        row_ok = all(abs(row_sum.get(k, 0.0) - v) <= tol for k, v in declared_rows.items())
        col_ok = all(abs(col_sum.get(k, 0.0) - v) <= tol for k, v in declared_cols.items())
        if not (row_ok and col_ok and abs(grand - total) <= tol
                and abs(sum(row_sum.values()) - total) <= tol
                and abs(sum(col_sum.values()) - total) <= tol):
            findings.append({
                "severity": "BLOCK",
                "rule": "matrix_three_way_conservation",
                "detail": (
                    f"预算矩阵三向不守恒：行和={sum(row_sum.values()):g}，"
                    f"列和={sum(col_sum.values()):g}，格合计={grand:g}，总预算={total:g}。"
                ),
                "action": "重跑 allocate_matrix，禁止手工改格；改动边际必须重算全矩阵。",
            })
        # 客户显式优先级单调性（矩阵引擎已算，这里兜底透传）
        for issue in matrix.get("issues", []):
            findings.append(issue)

        # --- 排期滚动汇总必须与矩阵互溯 ------------------------------------
        if delivery_units and phases:
            by_platform, by_phase, scheduled_total, problems = _scheduled_rollup(delivery_units, phases)
            findings.extend(problems)
            matrix_by_platform = {
                r["platform"]: float(r["amount"]) for r in matrix.get("platforms", [])
                if not r.get("is_reserve")
            }
            reserve_total = sum(
                float(r["amount"]) for r in matrix.get("platforms", []) if r.get("is_reserve")
            )
            tol2 = max(1.0, abs(total) * 1e-4)
            # 预留行参与矩阵守恒但不进入日排期；阶段排期目标 = 矩阵列 - 该阶段预留额
            reserve_platform_names = {
                r["platform"] for r in matrix.get("platforms", []) if r.get("is_reserve")
            }
            reserve_by_phase: dict[str, float] = {}
            for c in cells:
                if c["platform"] in reserve_platform_names:
                    reserve_by_phase[c["phase"]] = reserve_by_phase.get(c["phase"], 0.0) + float(c["amount"])
            for name, amount in matrix_by_platform.items():
                if abs(by_platform.get(name, 0.0) - amount) > tol2:
                    findings.append({
                        "severity": "BLOCK",
                        "rule": "schedule_rollup_matches_matrix",
                        "detail": f"平台 {name} 排期汇总 {by_platform.get(name, 0.0):g} 与矩阵行 {amount:g} 不一致。",
                        "action": "由矩阵行总额反推 daily_budget_by_phase，重算排期。",
                    })
            for ph in matrix.get("phases", []):
                name, amount = ph["phase"], float(ph["amount"])
                expected_phase = amount - reserve_by_phase.get(name, 0.0)
                if abs(by_phase.get(name, 0.0) - expected_phase) > tol2:
                    findings.append({
                        "severity": "BLOCK",
                        "rule": "schedule_rollup_matches_matrix",
                        "detail": (
                            f"阶段 {name} 排期汇总 {by_phase.get(name, 0.0):g} 与矩阵列 {amount:g}"
                            f"（扣预留 {reserve_by_phase.get(name, 0.0):g} 后应为 {expected_phase:g}）不一致。"
                        ),
                        "action": "由矩阵列总额（扣除该阶段预留）重排各阶段日预算。",
                    })
            if abs(scheduled_total - (total - reserve_total)) > tol2:
                findings.append({
                    "severity": "BLOCK",
                    "rule": "reserve_not_in_scheduled_spend",
                    "detail": (
                        f"排期消耗合计 {scheduled_total:g}，应=总预算 {total:g} - 预留 {reserve_total:g}"
                        f" = {total - reserve_total:g}。"
                    ),
                    "action": "预留预算不得排入日预算；核对排期总额。",
                })

    # --- 冷启动再营销占比上限 ----------------------------------------------
    # 再营销身份由显式字段判定（is_remarketing / segment 含 remarket），
    # 不再按 tier id（如 T1）硬编码——竞品 conquest、新客首发等场景 T1 不是再营销。
    cap = float(payload.get("remarketing_cap", 0.15))
    tiers = payload.get("audience_tiers", [])
    for tier in tiers:
        share = float(tier.get("share", 0) or 0)
        seg_hint = str(tier.get("segment", tier.get("tier", ""))).lower()
        is_remarketing = bool(tier.get("is_remarketing")) or ("remarket" in seg_hint)
        has_evidence = bool(tier.get("installed_base_evidence") or tier.get("has_remarketing_evidence"))
        if is_remarketing and share > cap and not has_evidence:
            findings.append({
                "severity": "BLOCK",
                "rule": "cold_start_remarketing_check",
                "detail": (
                    f"再营销人群（{tier.get('id', tier.get('tier', '?'))}）预算占比 {share:.0%} "
                    f"超过冷启动上限 {cap:.0%}，且未提供客户装基规模或历史再营销表现证据。"
                ),
                "action": "下调再营销占比至上限内，或让客户提供装基/历史数据作为证据。"
                "（非再营销人群请在 tier 上置 is_remarketing=false，勿仅靠 id 命名推断。）",
            })

    # --- KPI 量级可行性 -----------------------------------------------------
    feasibility_inputs = payload.get("kpi_feasibility_inputs")
    if feasibility_inputs:
        report = kpi_budget_feasibility({
            "budget": payload.get("total_budget", 0),
            "items": feasibility_inputs,
        })
        findings.extend(report["issues"])

    return findings


# ---------------------------------------------------------------------------
# 引擎产出结构门禁（Slice 2，定性层）
# ---------------------------------------------------------------------------

REQUIRED_ENGINES = (
    "usp-inventory", "usp-translation", "audience-tier",
    "platform-role", "phase-milestone", "budget-matrix", "kpi-framework",
)


def _gate(severity: str, rule: str, detail: str, action: str = "") -> dict:
    return {"severity": severity, "rule": rule, "detail": detail, "action": action}


def _engine_payload(engine_outputs: dict, engine_id: str):
    block = engine_outputs.get(engine_id) or {}
    return block, block.get("payload") or {}




# ---------------------------------------------------------------------------
# E7 创意策略双模式门禁（Slice 4）
# ---------------------------------------------------------------------------

# 品牌模式 creative 文本中禁止出现的制作/改编动作
_BRAND_PRODUCTION_KEYWORDS = ("待生产", "改编", "裁切", "裁剪", "剪辑", "转码", "改尺寸", "重剪", "代理制作")














# ---------------------------------------------------------------------------
# compute_weights — E2/E3/E4 weights data-driven calculation (v1.9)
# ---------------------------------------------------------------------------

def compute_weights(payload: dict) -> dict:
    """E2 audience share / E3 platform weight / E4 phase weight data-driven formula."""
    result = {"generated_by": "strategy_engines.compute_weights", "sections": {}}
    issues = []

    # E2: Audience shares = f(audience_size, conversion_rate)
    e2 = payload.get("e2_audience")
    if e2:
        tiers = e2.get("tiers", [])
        if not tiers:
            issues.append({"section": "e2", "level": "BLOCK", "msg": "e2_audience.tiers is empty"})
        elif e2.get("client_confirmed_shares"):
            # v1.9: Client confirmed shares take priority, skip formula
            confirmed = e2["client_confirmed_shares"]
            result["sections"]["e2_audience"] = {
                "tiers": [{"id": t["id"], "proposed_share": float(confirmed.get(t["id"], 0)),
                           "weight_source": "client_confirmed"} for t in tiers],
                "shares_sum": round(sum(float(confirmed.get(t["id"], 0)) for t in tiers), 4),
                "weight_source": "client_confirmed",
            }
            issues.append({"section": "e2", "level": "INFO",
                           "msg": "Using client-confirmed audience shares, skipping formula"})
        else:
            cap = _num(e2.get("remarketing_cap", 0.15), "remarketing_cap")
            rm_max = _num(e2.get("remarketing_max", 0.50), "remarketing_max")
            exp_min = _num(e2.get("expansion_min", 0.15), "expansion_min")
            raw_values = []
            for t in tiers:
                size = _num(t["audience_size"], f"tier:{t['id']}.audience_size")
                cvr = _num(t["conversion_rate"], f"tier:{t['id']}.conversion_rate")
                raw_values.append(size * cvr)
            total_raw = sum(raw_values)
            if total_raw <= 0:
                raise ValueError("e2: sum of (audience_size * conversion_rate) must be positive")
            shares = [v / total_raw for v in raw_values]
            for i, t in enumerate(tiers):
                is_rm = t.get("is_remarketing", False)
                has_ev = t.get("has_remarketing_evidence", False)
                if is_rm and not has_ev and shares[i] > cap:
                    shares[i] = cap
                    issues.append({"section": "e2", "level": "WARN",
                                   "msg": f"tier {t['id']} no remarketing evidence, capped at {cap}"})
                if is_rm and has_ev and shares[i] > rm_max:
                    shares[i] = rm_max
                if t.get("is_expansion", False) and shares[i] < exp_min:
                    shares[i] = exp_min
            shares = [s / sum(shares) for s in shares]
            adj = e2.get("llm_adjustments", []) or []
            for a in adj:
                tid = a["tier_id"]
                delta = Decimal(str(a["delta"]))  # v1.9: allow negative deltas
                if abs(delta) > Decimal("0.05"):
                    issues.append({"section": "e2", "level": "WARN",
                                   "msg": f"LLM adjustment for {tid} exceeds +/-5pp ({delta})"})
                    delta = max(min(delta, Decimal("0.05")), Decimal("-0.05"))
                target_idx = None
                for i, t in enumerate(tiers):
                    if t["id"] == tid:
                        target_idx = i
                        break
                if target_idx is not None:
                    shares, actual_delta = _apply_llm_adjustment(shares, target_idx, delta)
                    issues.append({"section": "e2", "level": "INFO",
                                   "msg": f"Adjusted {tid}: intended={delta:+.2%}, actual={actual_delta:+.2%}"})
            result["sections"]["e2_audience"] = {
                "tiers": [{"id": t["id"],
                           "audience_size": float(_num(t["audience_size"], "")),
                           "conversion_rate": float(_num(t["conversion_rate"], "")),
                           "raw_expected_value": float(raw_values[i]),
                           "proposed_share": round(float(shares[i]), 4)}
                          for i, t in enumerate(tiers)],
                "shares_sum": round(float(sum(shares)), 4),
            }

    # E3: Platform weights = f(1/CPM, reach_potential, priority_coefficient)
    e3 = payload.get("e3_platforms")
    if e3:
        platforms = e3.get("platforms", [])
        if not platforms:
            issues.append({"section": "e3", "level": "BLOCK", "msg": "e3_platforms.platforms is empty"})
        elif e3.get("client_confirmed_shares"):
            # v1.9: Client confirmed shares take priority
            confirmed = e3["client_confirmed_shares"]
            result["sections"]["e3_platforms"] = {
                "platforms": [{"name": p["name"], "proposed_share": float(confirmed.get(p["name"], 0)),
                               "weight_source": "client_confirmed"} for p in platforms],
                "shares_sum": round(sum(float(confirmed.get(p["name"], 0)) for p in platforms), 4),
            }
            issues.append({"section": "e3", "level": "INFO",
                           "msg": "Using client-confirmed platform shares, skipping formula"})
        else:
            min_s = _num(e3.get("min_share", 0.05), "min_share")
            max_s = _num(e3.get("max_share", 0.35), "max_share")
            default_coeffs = [Decimal("1.20"), Decimal("1.00"), Decimal("0.85"), Decimal("0.70")]
            coeffs = [Decimal(str(c)) for c in e3.get("priority_coefficients", default_coeffs)]
            raw_weights = []
            market_tier = e3.get("market_tier", "emerging")
            for p in platforms:
                # E3 v1.9: fallback to default CPM when no evidence
                cpm_val = p.get("cpm")
                if cpm_val is None or float(cpm_val) <= 0:
                    defaults = _get_default_cpm(p["name"], market_tier)
                    cpm = _num(defaults["cpm_mid"], f"platform:{p['name']}.cpm")
                    p["cpm"] = defaults["cpm_mid"]
                    issues.append({"section": "e3", "level": "WARN",
                                   "msg": f"{p['name']} no CPM evidence, using default {defaults['evidence_source']}={defaults['cpm_mid']}"})
                else:
                    cpm = _num(cpm_val, f"platform:{p['name']}.cpm")
                reach_val = p.get("reach_potential")
                if reach_val is None or float(reach_val) <= 0:
                    defaults = _get_default_cpm(p["name"], market_tier)
                    reach = _num(defaults["reach_potential"], f"platform:{p['name']}.reach_potential")
                    p["reach_potential"] = defaults["reach_potential"]
                    issues.append({"section": "e3", "level": "WARN",
                                   "msg": f"{p['name']} no reach_potential evidence, using default"})
                else:
                    reach = _num(reach_val, f"platform:{p['name']}.reach_potential")
                rank = int(p.get("priority_rank", len(platforms)))
                coeff = coeffs[max(0, min(rank - 1, len(coeffs) - 1))]
                raw_weights.append((Decimal("1") / cpm) * reach * coeff)
            total_raw_w = sum(raw_weights)
            if total_raw_w <= 0:
                raise ValueError("e3: sum of raw weights must be positive")
            weights = [w / total_raw_w for w in raw_weights]
            for i in range(len(platforms)):
                if weights[i] < min_s:
                    weights[i] = min_s
                if weights[i] > max_s:
                    weights[i] = max_s
            weights = [w / sum(weights) for w in weights]
            adj = e3.get("llm_adjustments", []) or []
            for a in adj:
                pname = a["platform"]
                delta = Decimal(str(a["delta"]))  # v1.9: allow negative deltas
                if abs(delta) > Decimal("0.05"):
                    issues.append({"section": "e3", "level": "WARN",
                                   "msg": f"LLM adjustment for {pname} exceeds +/-5pp ({delta})"})
                    delta = max(min(delta, Decimal("0.05")), Decimal("-0.05"))
                target_idx = None
                for i, p in enumerate(platforms):
                    if p["name"] == pname:
                        target_idx = i
                        break
                if target_idx is not None:
                    weights, actual_delta = _apply_llm_adjustment(weights, target_idx, delta, min_s)
                    issues.append({"section": "e3", "level": "INFO",
                                   "msg": f"Adjusted {pname}: intended={delta:+.2%}, actual={actual_delta:+.2%}"})
            result["sections"]["e3_platforms"] = {
                "platforms": [{"name": p["name"],
                                "cpm": float(_num(p["cpm"], "")),
                                "reach_potential": float(_num(p["reach_potential"], "")),
                                "priority_rank": int(p.get("priority_rank", len(platforms))),
                                "raw_weight": float(raw_weights[i]),
                                "proposed_share": round(float(weights[i]), 4)}
                               for i, p in enumerate(platforms)],
                "shares_sum": round(float(sum(weights)), 4),
            }

    # E4: Phase weights = f(days, prior_profile, launch_peak_boost)
    e4 = payload.get("e4_phases")
    if e4:
        phases = e4.get("phases", [])
        if not phases:
            issues.append({"section": "e4", "level": "BLOCK", "msg": "e4_phases.phases is empty"})
        elif e4.get("client_confirmed_shares"):
            # v1.9: Client confirmed shares take priority
            confirmed = e4["client_confirmed_shares"]
            result["sections"]["e4_phases"] = {
                "phases": [{"id": p["id"], "proposed_share": float(confirmed.get(p["id"], 0)),
                            "weight_source": "client_confirmed"} for p in phases],
                "shares_sum": round(sum(float(confirmed.get(p["id"], 0)) for p in phases), 4),
            }
            issues.append({"section": "e4", "level": "INFO",
                           "msg": "Using client-confirmed phase shares, skipping formula"})
        else:
            # E4 v1.9: load prior_profile from config file instead of hardcoded
            prior = e4.get("prior_profile")
            if not prior:
                profile_name = e4.get("prior_profile_name", "new_launch")
                prior = _get_phase_prior(profile_name)
                issues.append({"section": "e4", "level": "WARN",
                               "msg": f"prior_profile not provided, loaded from config: {profile_name}"})
            if not prior:
                raise ValueError("e4: prior_profile is empty")
            boost_peak = _num(e4.get("launch_peak_boost", 1.5), "launch_peak_boost")
            boost_pre = _num(e4.get("prelaunch_boost", 1.2), "prelaunch_boost")
            min_s = _num(e4.get("min_share", 0.10), "e4.min_share")
            max_s = _num(e4.get("max_share", 0.50), "e4.max_share")
            total_days = sum(int(p["days"]) for p in phases)
            if total_days <= 0:
                raise ValueError("e4: total days must be positive")
            raw_weights = []
            for p in phases:
                days = int(p["days"])
                obj = p.get("objective", "consideration")
                base_prior = Decimal(str(prior.get(obj, 0.25)))
                w = base_prior * (Decimal(days) / Decimal(total_days))
                if p.get("is_launch_peak", False):
                    w *= boost_peak
                if p.get("is_prelaunch", False):
                    w *= boost_pre
                raw_weights.append(w)
            total_raw_p = sum(raw_weights)
            if total_raw_p <= 0:
                raise ValueError("e4: sum of raw phase weights must be positive")
            weights = [w / total_raw_p for w in raw_weights]
            for i in range(len(phases)):
                if weights[i] < min_s:
                    weights[i] = min_s
                if weights[i] > max_s:
                    weights[i] = max_s
            weights = [w / sum(weights) for w in weights]
            adj = e4.get("llm_adjustments", []) or []
            for a in adj:
                pid = a["phase_id"]
                delta = Decimal(str(a["delta"]))  # v1.9: allow negative deltas
                if abs(delta) > Decimal("0.05"):
                    issues.append({"section": "e4", "level": "WARN",
                                   "msg": f"LLM adjustment for {pid} exceeds +/-5pp ({delta})"})
                    delta = max(min(delta, Decimal("0.05")), Decimal("-0.05"))
                target_idx = None
                for i, p in enumerate(phases):
                    if p["id"] == pid:
                        target_idx = i
                        break
                if target_idx is not None:
                    weights, actual_delta = _apply_llm_adjustment(weights, target_idx, delta, min_s)
                    issues.append({"section": "e4", "level": "INFO",
                                   "msg": f"Adjusted {pid}: intended={delta:+.2%}, actual={actual_delta:+.2%}"})
            result["sections"]["e4_phases"] = {
                "total_days": total_days,
                "phases": [{"id": p["id"], "days": int(p["days"]),
                            "objective": p.get("objective", ""),
                            "raw_weight": float(raw_weights[i]),
                            "proposed_share": round(float(weights[i]), 4)}
                           for i, p in enumerate(phases)],
                "shares_sum": round(float(sum(weights)), 4),
            }

    result["issues"] = issues
    result["status"] = "ok" if not any(i["level"] == "BLOCK" for i in issues) else "blocked"
    return result


def audience_budget_alignment(payload: dict) -> dict:
    """E2 v1.9: check that actual budget allocation by audience tier matches proposed shares.

    payload:
      tiers: [{"id": str, "proposed_share": float}]
      delivery_units: [{"serving_tiers": [str], "budget": float}]
      tolerance: float (default 0.10, WARN if actual deviates more than this)
    """
    tiers = payload.get("tiers", [])
    units = payload.get("delivery_units", [])
    tolerance = float(payload.get("tolerance", 0.10))

    if not tiers or not units:
        return {"status": "SKIP", "reason": "no tiers or units to check", "alignment": []}

    # Sum budget per tier
    tier_budget = {t["id"]: 0.0 for t in tiers}
    total_budget = 0.0
    for u in units:
        budget = float(u.get("budget", 0))
        total_budget += budget
        for tid in u.get("serving_tiers", []):
            if tid in tier_budget:
                tier_budget[tid] += budget

    if total_budget <= 0:
        return {"status": "SKIP", "reason": "zero budget", "alignment": []}

    # Compare actual vs proposed
    issues = []
    alignment = []
    for t in tiers:
        tid = t["id"]
        actual_share = tier_budget.get(tid, 0.0) / total_budget
        proposed = float(t.get("proposed_share", 0))
        deviation = abs(actual_share - proposed)
        level = "PASS" if deviation <= tolerance else "WARN"
        alignment.append({
            "tier_id": tid,
            "proposed_share": round(proposed, 4),
            "actual_share": round(actual_share, 4),
            "deviation": round(deviation, 4),
            "level": level,
        })
        if level == "WARN":
            issues.append({
                "severity": "WARN",
                "rule": "audience_budget_alignment",
                "detail": f"Tier {tid}: proposed={proposed:.1%}, actual={actual_share:.1%}, deviation={deviation:.1%}",
                "action": "检查投放单元的 serving_tiers 标注是否正确，或调整平台/阶段权重使人群预算更匹配分层建议。",
            })

    return {
        "status": "WARN" if issues else "PASS",
        "alignment": alignment,
        "issues": issues,
        "generated_by": "strategy_engines.audience_budget_alignment",
    }


def audience_overlap_check(payload: dict) -> dict:
    """v1.9: Check audience tier overlap risk.
    
    payload:
      tiers: [{"id": str, "targeting_logic": str, "intent_distance": str}]
    
    Heuristics:
    - remarketing vs competitor_interest: usually disjoint (PASS)
    - competitor_interest vs broad_interest: likely overlap (WARN)
    - Same intent_distance group: WARN
    """
    tiers = payload.get("tiers", [])
    if len(tiers) < 2:
        return {"status": "SKIP", "reason": "fewer than 2 tiers", "checks": []}
    
    # Define overlap rules by intent_distance
    overlap_groups = {
        "remarketing": ["conversion", "retention"],  # disjoint from awareness
        "core_potential": ["consideration"],  # adjacent
        "expansion": ["awareness"],  # adjacent
    }
    
    issues = []
    checks = []
    
    for i in range(len(tiers)):
        for j in range(i + 1, len(tiers)):
            t1 = tiers[i]
            t2 = tiers[j]
            id1 = t1.get("intent_distance", "")
            id2 = t2.get("intent_distance", "")
            
            # Check if both are in the same funnel position
            overlap_risk = False
            reason = ""
            
            # Known overlap patterns
            if id1 == "core_potential" and id2 == "expansion":
                overlap_risk = True
                reason = "竞品人群和泛兴趣人群可能重叠（都包含品类兴趣）"
            elif id1 == "expansion" and id2 == "core_potential":
                overlap_risk = True
                reason = "泛兴趣人群和竞品人群可能重叠（都包含品类兴趣）"
            elif id1 == id2:
                overlap_risk = True
                reason = f"两人群 intent_distance 相同（{id1}），可能定位重叠"
            
            level = "WARN" if overlap_risk else "PASS"
            checks.append({
                "pair": f"{t1.get('id', '?')} vs {t2.get('id', '?')}",
                "level": level,
                "reason": reason if overlap_risk else "定向逻辑互斥",
            })
            
            if overlap_risk:
                issues.append({
                    "severity": "WARN",
                    "rule": "audience_overlap_check",
                    "detail": f"{t1.get('id', '?')} vs {t2.get('id', '?')}: {reason}",
                    "action": "考虑在定向逻辑中加排除条件（exclusion），或调整人群定义使两层互斥。",
                })
    
    return {
        "status": "WARN" if issues else "PASS",
        "checks": checks,
        "issues": issues,
        "overlap_estimate": "unknown",
        "note": "精确重叠率需要平台 audience overlap 数据，当前仅做定向逻辑启发式检查",
        "generated_by": "strategy_engines.audience_overlap_check",
    }


# ---------------------------------------------------------------------------
# compute_kpi — E6 KPI feasibility estimation (v1.9)
# ---------------------------------------------------------------------------

def compute_kpi(payload: dict) -> dict:
    """E6 KPI 可行性预估：从预算 + CPM 反推曝光/Reach，和客户目标对比。

    payload:
      total_budget: 数值
      target_audience_size: 数值（目标人群规模）
      kpi_targets: {"reach_pct": float?, "awareness_lift_pct": float?}
      platforms: [{"name": str, "cpm": float, "share": float}]
      frequency_assumption: float (默认 3.0)
      benchmark_cpms: {平台名: 数值} (可选，搜索得到的 benchmark)
      objective_cvr: float (可选，转化目标人群转化率基准，默认 0.01)
      avg_order_value: float (可选，客单价，用于 ROAS 估算)
    """
    result = {"generated_by": "strategy_engines.compute_kpi", "sections": {}}
    issues = []

    budget = _num(payload["total_budget"], "total_budget")
    audience_size = _num(payload["target_audience_size"], "target_audience_size")
    freq = _num(payload.get("frequency_assumption", 3.0), "frequency_assumption")

    platforms = payload.get("platforms", [])
    if not platforms:
        raise ValueError("platforms must be non-empty")

    # v1.9: fallback to default CPM when no evidence
    market_tier = payload.get("market_tier", "emerging")
    for p in platforms:
        if "cpm" not in p or float(p.get("cpm", 0)) <= 0:
            defaults = _get_default_cpm(p["name"], market_tier)
            p["cpm"] = defaults["cpm_mid"]
            p["cpm_source"] = defaults["evidence_source"]
            issues.append({"section": "kpi", "level": "WARN",
                           "msg": f"{p['name']} no CPM evidence, using default {defaults['cpm_mid']}"})

    # 1. Weighted average CPM across platforms
    total_share = sum(_num(p["share"], f"platform:{p['name']}.share") for p in platforms)
    if total_share <= 0:
        raise ValueError("platform shares must sum to positive")

    weighted_cpm = sum(
        _num(p["cpm"], f"platform:{p['name']}.cpm") * _num(p["share"], f"platform:{p['name']}.share")
        for p in platforms
    ) / total_share

    # 2. Total impressions = budget / CPM * 1000
    total_impressions = (budget / weighted_cpm) * 1000

    # 3. Estimated reach = impressions / frequency
    estimated_reach = total_impressions / freq
    estimated_reach_pct = estimated_reach / audience_size

    # 4. Per-platform breakdown
    per_platform = []
    for p in platforms:
        p_budget = budget * (_num(p["share"], "share") / total_share)
        p_cpm = _num(p["cpm"], "cpm")
        p_impressions = (p_budget / p_cpm) * 1000
        p_reach = p_impressions / freq
        per_platform.append({
            "platform": p["name"],
            "budget": float(p_budget),
            "cpm": float(p_cpm),
            "impressions": float(p_impressions),
            "estimated_reach": float(p_reach),
        })

    # 5. Feasibility check vs target
    kpi_targets = payload.get("kpi_targets", {})
    target_reach_pct = kpi_targets.get("reach_pct")
    feasibility = "not_assessed"
    gap = None
    if target_reach_pct is not None:
        target_reach = audience_size * _num(target_reach_pct, "reach_pct")
        gap = float(estimated_reach - target_reach)
        gap_pct = float(estimated_reach / target_reach) if target_reach > 0 else 0
        if gap_pct >= 1.2:
            feasibility = "comfortable"
        elif gap_pct >= 0.9:
            feasibility = "tight"
        else:
            feasibility = "insufficient"
            issues.append({
                "section": "kpi", "level": "BLOCK",
                "msg": f"Reach 目标 {target_reach_pct*100:.0f}% 预估不足："
                       f"预算可覆盖 {estimated_reach_pct*100:.1f}%，需调整预算或降低目标"
            })

    # 6. CPM benchmark comparison (if provided)
    benchmark_cpms = payload.get("benchmark_cpms", {})
    cpm_benchmark_avg = None
    if benchmark_cpms:
        weighted_benchmark = sum(
            _num(benchmark_cpms.get(p["name"], p["cpm"]), "benchmark") * _num(p["share"], "share")
            for p in platforms if p["name"] in benchmark_cpms
        ) / total_share
        cpm_benchmark_avg = float(weighted_benchmark)

    # 7. Conversion layer estimates (if objective is conversion)
    objective_cvr = payload.get("objective_cvr")
    conversion_estimate = None
    if objective_cvr:
        cvr = _num(objective_cvr, "objective_cvr")
        # Use clicks (estimate from impressions * CTR assumption)
        avg_ctr = Decimal("0.015")  # assume 1.5% CTR across platforms
        estimated_clicks = total_impressions * avg_ctr
        estimated_conversions = estimated_clicks * cvr
        conversion_estimate = {
            "avg_ctr_assumption": 0.015,
            "estimated_clicks": float(estimated_clicks),
            "estimated_conversions": float(estimated_conversions),
            "estimated_cpa": float(budget / estimated_conversions) if estimated_conversions > 0 else None,
        }

    result["sections"]["kpi_feasibility"] = {
        "weighted_cpm": round(float(weighted_cpm), 2),
        "total_impressions": float(total_impressions),
        "estimated_reach": float(estimated_reach),
        "estimated_reach_pct": round(float(estimated_reach_pct), 4),
        "frequency_assumption": float(freq),
        "per_platform": per_platform,
        "feasibility": feasibility,
        "gap_to_target": gap,
        "benchmark_cpm_comparison": {
            "estimated_weighted_cpm": float(weighted_cpm),
            "benchmark_weighted_cpm": cpm_benchmark_avg,
        },
        "conversion_estimate": conversion_estimate,
    }
    result["issues"] = issues
    result["status"] = "ok" if not any(i["level"] == "BLOCK" for i in issues) else "blocked"
    return result
