"""Deterministic core for the channel-neutral Media Planner skill."""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable

from strategy_engines import (
    allocate_matrix,
    audience_budget_alignment,
    audience_overlap_check,
    compute_kpi,
    compute_weights,
    currency_convert,
    derive_daily_schedule,
    evaluate_strategy_gates,
    kpi_budget_feasibility,
    normalize_budget,
    suggest_budget,
)


FIELD_STATUSES = {
    "confirmed", "extracted", "derived", "recommended", "defaulted",
    "missing", "conflict", "unverified", "not_applicable",
}

REQUIRED_FIELDS = (
    "market", "business_goal", "total_budget", "currency",
    "campaign_start", "campaign_end", "product_or_service", "audience",
    "destination", "creative_readiness",
)

# channel_plan and budget_allocation start as recommended (Agent-generated)
# and are confirmed by the user during strategy-analysis.  They are intentionally
# kept out of REQUIRED_FIELDS so that the initial completeness check does not
# BLOCK before the Agent has had a chance to produce them.
OPTIONAL_FIELDS = (
    "channel_plan", "budget_allocation",
    "historical_performance", "competitors", "brand_guidelines",
    "internal_resources", "optimization_cadence", "regional_priority",
    "creative_inventory", "language", "timezone", "fees_and_tax_basis",
)

EXTENDED_FIELDS = (
    "deep_consumer_insight", "industry_reports", "experiment_design",
    "long_term_learning_agenda",
)

DEFAULT_MAX_ATTEMPTS = {
    "material-parsing": 2,
    "dimension-discovery": 2,
    "completeness-check": 2,
    "evidence-search": 3,
    "strategy-analysis": 2,
    "deterministic-calculation": 2,
    "preflight-self-check": 2,
    "workbook-generation": 2,
    "template-mapping": 2,
    "change-analysis": 2,
    "safe-backfill": 1,
    "delivery-validation": 2,
}

# budget_mode options
BUDGET_MODES = {"daily_equal", "lifecycle_total", "custom"}

EVIDENCE_WEIGHTS = {
    "source_reliability": Decimal("0.30"),
    "scenario_match": Decimal("0.25"),
    "recency": Decimal("0.15"),
    "metric_definition": Decimal("0.15"),
    "authorization": Decimal("0.15"),
}


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be numeric: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _payload_value(payload: dict, key: str, default: Any = None) -> Any:
    """Read a canonical field consistently from root, values, or brief."""
    if key in payload and payload[key] is not None:
        return payload[key]
    for container_name in ("values", "brief"):
        container = payload.get(container_name, {})
        if isinstance(container, dict) and key in container and container[key] is not None:
            return container[key]
    return default


def _issue(
    severity: str,
    rule: str,
    detail: str,
    responsible_node: str,
    *,
    auto_fixable: bool = False,
    rerun_from: str | None = None,
    attempts_used: int = 0,
    max_attempts: int | None = None,
    action: str = "",
) -> dict:
    maximum = max_attempts if max_attempts is not None else DEFAULT_MAX_ATTEMPTS.get(responsible_node, 1)
    remaining = max(0, maximum - attempts_used)
    return {
        "severity": severity,
        "rule": rule,
        "detail": detail,
        "responsible_node": responsible_node,
        "auto_fixable": bool(auto_fixable),
        "rerun_from": rerun_from or responsible_node,
        "attempts_used": attempts_used,
        "max_attempts": maximum,
        "attempts_remaining": remaining,
        "human_intervention": severity == "BLOCK" and (not auto_fixable or remaining == 0),
        "action": action,
    }


def route_task(payload: dict) -> dict:
    """Route by requested work, never by channel name."""
    task = str(payload.get("task_type", "")).strip().lower()
    aliases = {
        "new": "new_plan", "new_plan": "new_plan", "create": "new_plan",
        "revise": "revise_plan", "update": "revise_plan",
        "existing_mp_update": "revise_plan", "revise_plan": "revise_plan",
        "module": "module_analysis", "analysis": "module_analysis",
        "module_analysis": "module_analysis",
    }
    if task in aliases:
        route = aliases[task]
    elif payload.get("existing_workbook"):
        route = "revise_plan"
    elif payload.get("requested_module"):
        route = "module_analysis"
    else:
        route = "new_plan"
    return {
        "route": route,
        "first_node": {
            "new_plan": "material-parsing",
            "revise_plan": "template-mapping",
            "module_analysis": "material-parsing",
        }[route],
    }


def assess_completeness(payload: dict) -> dict:
    """Apply required/optional/extended completeness and confirmation rules."""
    values = payload.get("values", payload.get("brief", payload))
    statuses = payload.get("statuses", payload.get("field_statuses", {}))
    required_fields = tuple(payload.get("required_fields", REQUIRED_FIELDS))
    optional_fields = tuple(payload.get("optional_fields", OPTIONAL_FIELDS))
    extended_fields = tuple(payload.get("extended_fields", EXTENDED_FIELDS))

    invalid_statuses = sorted({value for value in statuses.values() if value not in FIELD_STATUSES})
    missing_required, conflict_required, unconfirmed_required = [], [], []
    for field in required_fields:
        status = statuses.get(field)
        if status == "conflict":
            conflict_required.append(field)
        elif not _present(values.get(field)) or status == "missing":
            missing_required.append(field)
        elif status not in {"confirmed", "derived"}:
            unconfirmed_required.append(field)

    missing_optional = [field for field in optional_fields if not _present(values.get(field)) or statuses.get(field) == "missing"]
    missing_extended = [field for field in extended_fields if not _present(values.get(field)) or statuses.get(field) == "missing"]
    optional_rate = len(missing_optional) / len(optional_fields) if optional_fields else 0.0

    issues = []
    if invalid_statuses:
        issues.append(_issue("BLOCK", "invalid_field_status", f"Unknown statuses: {invalid_statuses}", "material-parsing"))
    if missing_required:
        issues.append(_issue("BLOCK", "required_fields_missing", f"Missing: {missing_required}", "completeness-check", action="Ask only for the missing core facts."))
    if conflict_required:
        issues.append(_issue("BLOCK", "required_fields_conflict", f"Conflicts: {conflict_required}", "completeness-check", action="Show competing values and request a decision."))
    if unconfirmed_required:
        issues.append(_issue("WARN", "required_fields_unconfirmed", f"Unconfirmed: {unconfirmed_required}", "completeness-check", action="A draft may continue; final delivery requires confirmation."))
    if optional_rate > 0.30:
        issues.append(_issue("WARN", "optional_missing_over_30pct", f"Optional missing rate={optional_rate:.1%}", "completeness-check", action="Ask a compact batch of high-value questions or continue only as an explicitly accepted draft."))
    elif optional_rate > 0.10:
        issues.append(_issue("WARN", "optional_missing_over_10pct", f"Optional missing rate={optional_rate:.1%}", "completeness-check", action="Record assumptions and risks."))

    for item in payload.get("discovered_dimensions", []):
        name = item.get("dimension_name", "unnamed_dimension")
        if item.get("blocking") and not _present(item.get("resolved_value")):
            issues.append(_issue(
                "BLOCK", "discovered_dimension_unresolved",
                f"Discovered high-impact dimension requires resolution: {name}",
                "completeness-check", action="Ask for the missing decision or fact without discarding the source evidence.",
            ))
        elif item.get("business_impact") == "high" and item.get("requires_confirmation") and item.get("field_status") != "confirmed":
            issues.append(_issue(
                "WARN", "discovered_dimension_unconfirmed",
                f"High-impact discovered dimension is not confirmed: {name}",
                "completeness-check", action="Keep it visible in the draft and request confirmation before final delivery.",
            ))

    has_block = any(item["severity"] == "BLOCK" for item in issues)
    has_warn = any(item["severity"] == "WARN" for item in issues)
    if has_block:
        # P2 partial-draft: even when required fields are missing the assessment
        # returns a structured partial_output so the Agent can present an
        # "initial direction + missing checklist" instead of silently stopping.
        known_values = {key: values.get(key) for key in required_fields if _present(values.get(key)) and statuses.get(key) not in {"missing", "conflict"}}
        outcome, status = "BLOCK", "blocked"
    elif unconfirmed_required or optional_rate > 0.30:
        known_values = None
        outcome, status = "WARN", "draft"
    elif has_warn:
        known_values = None
        outcome, status = "WARN", "final_candidate"
    else:
        known_values = None
        outcome, status = "PASS", "final_candidate"

    return {
        "outcome": outcome,
        "deliverable_status": status,
        "missing_required": missing_required,
        "conflict_required": conflict_required,
        "unconfirmed_required": unconfirmed_required,
        "missing_optional": missing_optional,
        "missing_extended": missing_extended,
        "optional_missing_rate": round(optional_rate, 4),
        "thresholds": {"continue_max": 0.10, "warn_max": 0.30},
        "issues": issues,
        # partial_output is non-None when BLOCK but some required fields ARE known.
        # The Agent should use this to present an initial direction + ask only for
        # the missing items, rather than refusing to output anything.
        "partial_output": {
            "known_required": known_values,
            "guidance": (
                "Use the known fields to present an initial strategic direction. "
                "Explicitly list missing_required fields and ask for them in one "
                "compact message before proceeding to a draft."
            ),
        } if known_values else None,
    }


def allocate_budget(payload: dict) -> dict:
    """Allocate non-negative amounts with largest-remainder cent conservation.

    budget_mode (optional, default "daily_equal"):
      - "daily_equal"      : split total evenly by weight; result = total amount per item.
      - "lifecycle_total"  : same as daily_equal but semantically labelled as lifetime spend.
      - "custom"           : user supplies budget_custom_rule (plain-text); Agent parses it
                             into explicit item weights/amounts before calling this function.
                             The rule is recorded in the output for audit.
    """
    mode = str(payload.get("budget_mode", "daily_equal")).strip().lower()
    if mode not in BUDGET_MODES:
        raise ValueError(f"budget_mode must be one of {sorted(BUDGET_MODES)}, got {mode!r}")
    custom_rule = payload.get("budget_custom_rule", "") if mode == "custom" else ""
    total = _decimal(payload["total_budget"], "total_budget")
    if total < 0:
        raise ValueError("total_budget must be non-negative")
    cent = Decimal("0.01")
    if total != total.quantize(cent):
        raise ValueError("total_budget must have at most two decimal places")
    items = payload.get("items", [])
    if not items:
        raise ValueError("items must not be empty")
    weights = [_decimal(item.get("weight", 0), f"items[{index}].weight") for index, item in enumerate(items)]
    if any(weight < 0 for weight in weights):
        raise ValueError("weights must be non-negative")
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise ValueError("sum of weights must be positive")

    total_cents = int(total / cent)
    exact_cents = [Decimal(total_cents) * weight / weight_sum for weight in weights]
    floor_cents = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact_cents]
    remainder = total_cents - sum(floor_cents)
    ranking = sorted(
        range(len(items)),
        key=lambda index: (exact_cents[index] - Decimal(floor_cents[index]), -index),
        reverse=True,
    )
    allocated_cents = list(floor_cents)
    for index in ranking[:remainder]:
        allocated_cents[index] += 1

    amounts = []
    for item, weight, cents in zip(items, weights, allocated_cents):
        amount = Decimal(cents) * cent
        amounts.append({
            **item,
            "normalized_weight": float(weight / weight_sum),
            "amount": float(amount),
        })
    allocated_total = sum(Decimal(cents) * cent for cents in allocated_cents)
    return {
        "total_budget": float(total),
        "budget_mode": mode,
        "budget_custom_rule": custom_rule,
        "items": amounts,
        "allocated_total": float(allocated_total),
        "conserved": allocated_total == total,
        "difference": float(allocated_total - total),
    }


def calculate_kpi(payload: dict) -> dict:
    """Perform deterministic KPI conversion from confirmed numeric inputs."""
    formula = str(payload["formula"]).lower()
    values = {key: _decimal(value, key) for key, value in payload.get("inputs", {}).items()}
    formulas: dict[str, tuple[tuple[str, ...], Callable[[dict[str, Decimal]], Decimal], str]] = {
        "impressions": (("spend", "cpm"), lambda v: v["spend"] / v["cpm"] * 1000, "count"),
        "clicks": (("spend", "cpc"), lambda v: v["spend"] / v["cpc"], "count"),
        "conversions": (("spend", "cpa"), lambda v: v["spend"] / v["cpa"], "count"),
        "ctr": (("clicks", "impressions"), lambda v: v["clicks"] / v["impressions"], "ratio"),
        "cvr": (("conversions", "clicks"), lambda v: v["conversions"] / v["clicks"], "ratio"),
        "cpm": (("spend", "impressions"), lambda v: v["spend"] / v["impressions"] * 1000, "currency"),
        "cpc": (("spend", "clicks"), lambda v: v["spend"] / v["clicks"], "currency"),
        "cpa": (("spend", "conversions"), lambda v: v["spend"] / v["conversions"], "currency"),
    }
    if formula not in formulas:
        raise ValueError(f"Unsupported formula: {formula}")
    required, operation, unit = formulas[formula]
    missing = [key for key in required if key not in values]
    if missing:
        raise ValueError(f"Missing inputs: {missing}")
    try:
        result = operation(values)
    except (ZeroDivisionError, InvalidOperation) as exc:
        raise ValueError("Invalid zero denominator") from exc
    return {
        "formula": formula,
        "result": float(result.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
        "unit": unit,
        "currency": payload.get("currency", ""),
        "inputs": {key: float(value) for key, value in values.items()},
        "field_status": "derived",
    }


def collect_kpi_targets(payload: dict) -> dict:
    """Determine whether user-supplied KPI targets are present or need to be asked.

    Called during Step 2 (brief collection) before evidence search.
    Returns a structured prompt for the Agent to ask the user, or a pass-through
    when the user already provided targets.

    Input payload keys:
      kpi_targets   : list of {metric, value, unit, period, attribution_window} - user-confirmed.
      business_goal : confirmed string, used to suggest relevant KPI metrics.

    Returns:
      status            : "provided" | "needs_collection"
      confirmed         : list of confirmed kpi_target objects
      ask_user          : question string to show the user (only when needs_collection)
      suggested_metrics : list of metric names relevant to the goal
    """
    targets = payload.get("kpi_targets", [])
    confirmed_targets = [
        t for t in targets
        if t.get("field_status") == "confirmed" and _present(t.get("value"))
    ]
    if confirmed_targets:
        return {
            "status": "provided",
            "confirmed": confirmed_targets,
            "ask_user": None,
            "suggested_metrics": [],
        }

    goal = str(payload.get("business_goal", "")).lower()
    metric_hints: dict[str, list[str]] = {
        "purchase":    ["ROAS", "CPA", "CVR"],
        "traffic":     ["CPC", "CTR", "Outbound CTR"],
        "awareness":   ["CPM", "Reach", "Frequency"],
        "app_install": ["CPI", "CVR", "D1 Retention"],
        "lead":        ["CPL", "Lead CVR", "Form Submit Rate"],
    }
    suggested: list[str] = []
    for key, metrics in metric_hints.items():
        if key in goal:
            suggested = metrics
            break
    if not suggested:
        suggested = ["ROAS", "CPA", "CPM", "CTR"]

    goal_label = str(payload.get("business_goal", "")).strip() or "您的投放目标"
    ask = (
        f"您是否有 KPI 参考目标？（如目标 {'/'.join(suggested[:2])} 等，直接填入即可）\n"
        f"建议关注指标（基于「{goal_label}」）：{', '.join(suggested)}\n"
        "如暂无目标，回复「暂无」即可，系统将基于行业基准生成参考区间。"
    )
    return {
        "status": "needs_collection",
        "confirmed": [],
        "ask_user": ask,
        "suggested_metrics": suggested,
    }


def score_evidence(payload: dict) -> dict:
    """Score evidence using five deterministic P0 dimensions."""
    components = payload.get("components", payload)
    scores = {}
    for name in EVIDENCE_WEIGHTS:
        value = _decimal(components.get(name, 0), name)
        if value < 0 or value > 1:
            raise ValueError(f"{name} must be between 0 and 1")
        scores[name] = value
    weighted = sum(scores[name] * EVIDENCE_WEIGHTS[name] for name in EVIDENCE_WEIGHTS)
    score = float(weighted.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    tier = "high" if score >= 0.80 else "medium" if score >= 0.60 else "low"
    user_approved = bool(payload.get("user_approved"))
    source_type = str(payload.get("source_type", "")).lower()
    actual_types = {"brand_actual", "client_confirmed", "internal_actual"}
    if score >= 0.80 and (source_type in actual_types or user_approved):
        admissibility = "hard_check_allowed"
    elif score >= 0.60:
        admissibility = "directional_only"
    elif score > 0:
        admissibility = "insufficient_evidence"
    else:
        admissibility = "rejected"
    return {
        "score": score,
        "tier": tier,
        "admissibility": admissibility,
        "components": {name: float(scores[name]) for name in scores},
        "weights": {name: float(weight) for name, weight in EVIDENCE_WEIGHTS.items()},
        "hard_check_requires_user_approval": source_type not in actual_types,
    }


def check_kpi_tolerance(payload: dict) -> dict:
    """Compare a confirmed target with an evidence-supported interval."""
    target = _decimal(payload["target"], "target")
    lower = _decimal(payload["forecast_lower"], "forecast_lower")
    upper = _decimal(payload["forecast_upper"], "forecast_upper")
    if lower > upper:
        lower, upper = upper, lower
    tolerance = _decimal(payload.get("tolerance", 0.10), "tolerance")
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    direction = payload.get("direction", "range")
    admissibility = payload.get("admissibility", "insufficient_evidence")
    if admissibility != "hard_check_allowed":
        return {
            "result": "NOT_HARD_CHECKED",
            "target": float(target),
            "forecast_range": [float(lower), float(upper)],
            "reason": "Evidence is not approved for a hard feasibility check.",
            "recommendation": "Keep the client KPI unchanged and show a separate directional note.",
        }
    tolerated_lower = lower * (Decimal("1") - tolerance)
    tolerated_upper = upper * (Decimal("1") + tolerance)
    if direction == "cost_lower_is_better":
        passed = target >= tolerated_lower
    elif direction == "scale_higher_is_better":
        passed = target <= tolerated_upper
    else:
        passed = tolerated_lower <= target <= tolerated_upper
    return {
        "result": "PASS" if passed else "WARN",
        "target": float(target),
        "forecast_range": [float(lower), float(upper)],
        "tolerance": float(tolerance),
        "direction": direction,
        "comparison_range": [float(tolerated_lower), float(tolerated_upper)],
        "recommendation": None if passed else "Do not overwrite the client KPI; provide a separate optimization recommendation and evidence.",
    }


def validate_dates(payload: dict) -> list[dict]:
    start_raw = _payload_value(payload, "campaign_start")
    end_raw = _payload_value(payload, "campaign_end")
    if not start_raw or not end_raw:
        return [_issue("BLOCK", "campaign_dates_missing", "Campaign start or end date is missing.", "completeness-check")]
    try:
        start, end = date.fromisoformat(str(start_raw)[:10]), date.fromisoformat(str(end_raw)[:10])
    except ValueError:
        return [_issue("BLOCK", "campaign_dates_invalid", "Dates must use YYYY-MM-DD.", "material-parsing")]
    if end < start:
        return [_issue("BLOCK", "campaign_date_order", "campaign_end is before campaign_start.", "deterministic-calculation")]
    expected_days = (end - start).days + 1
    total_days = _payload_value(payload, "total_days")
    if total_days is not None and int(total_days) != expected_days:
        return [_issue("BLOCK", "campaign_day_count", f"Expected {expected_days} inclusive days, got {total_days}.", "deterministic-calculation", auto_fixable=True)]
    return []


def preflight(payload: dict) -> dict:
    """Run the mandatory stage 6.2 self-check."""
    issues: list[dict] = []
    attempts = payload.get("attempts", {})
    completeness = assess_completeness(payload)
    issues.extend(completeness["issues"])

    total = _decimal(_payload_value(payload, "total_budget", 0), "total_budget")
    units = payload.get("delivery_units", payload.get("media_plan", {}).get("delivery_units", []))
    # 二维预算矩阵存在时，守恒由 matrix_three_way_conservation / 排期互溯门禁负责，
    # delivery_units 使用 daily_budget_by_phase 而非一维 budget 字段，跳过旧的一维检查。
    if not payload.get("budget_matrix"):
        allocated = sum(_decimal(item.get("budget", 0), "delivery_unit.budget") for item in units)
        if allocated != total:
            issues.append(_issue(
                "BLOCK", "budget_conservation", f"Allocated {allocated} does not equal total {total}.",
                "deterministic-calculation", auto_fixable=True,
                attempts_used=int(attempts.get("deterministic-calculation", 0)),
                action="Re-run exact allocation and refresh dependent schedules and KPI calculations.",
            ))
    issues.extend(validate_dates(payload))

    # ── 策略层门禁（平台×阶段矩阵 / 排期互溯 / 预留 / 优先级 / 冷启动 / KPI 量级）──
    strategy_gate_nodes = {
        "matrix_three_way_conservation": "deterministic-calculation",
        "schedule_rollup_matches_matrix": "deterministic-calculation",
        "reserve_not_in_scheduled_spend": "deterministic-calculation",
        "schedule_phase_unknown": "deterministic-calculation",
        "kpi_budget_feasibility": "deterministic-calculation",
        "platform_priority_monotonic": "strategy-analysis",
        "cold_start_remarketing_check": "strategy-analysis",
    }
    for finding in evaluate_strategy_gates(payload):
        issues.append(_issue(
            finding["severity"], finding["rule"], finding["detail"],
            strategy_gate_nodes.get(finding["rule"], "strategy-analysis"),
            action=finding.get("action", ""),
        ))

    for index, constraint in enumerate(payload.get("hard_constraints", [])):
        if constraint.get("satisfied") is not True:
            issues.append(_issue("BLOCK", "hard_constraint_unsatisfied", f"hard_constraints[{index}]: {constraint.get('description', 'unsatisfied')}", "strategy-analysis", action="Revise the recommendation without changing the confirmed constraint."))

    kpi_items = payload.get("kpi", payload.get("_kpi", {})).get("items", [])
    for index, item in enumerate(kpi_items):
        forecast = item.get("kpi_forecast") or {}
        if forecast and not forecast.get("evidence_refs") and forecast.get("kpi_forecast_status") != "insufficient_evidence":
            issues.append(_issue("WARN", "kpi_evidence_missing", f"KPI item {index} has a forecast without evidence references.", "evidence-search"))
        recommendation = item.get("kpi_recommendation") or {}
        if recommendation.get("overwrote_target"):
            issues.append(_issue("BLOCK", "recommendation_overwrote_target", f"KPI item {index} recommendation overwrote the confirmed target.", "strategy-analysis"))

    # ── common-validation.md 规则 3：has_source_citation ────────────────────
    # Evidence records used for KPI/budget must have source, date and confidence.
    for index, ev in enumerate(payload.get("evidence_records", [])):
        conf = ev.get("confidence", {})
        if conf.get("admissibility") == "rejected":
            issues.append(_issue(
                "BLOCK", "rejected_evidence_in_plan",
                f"evidence_records[{index}] has admissibility=rejected and must not be used.",
                "evidence-search", action="Remove rejected evidence from evidence_records.",
            ))
        elif not ev.get("source_ref"):
            issues.append(_issue(
                "WARN", "evidence_missing_source_ref",
                f"evidence_records[{index}] is missing source_ref.",
                "evidence-search",
            ))

    # ── common-validation.md 规则 5：cross_sheet_reference ─────────────────
    # Audience labels referenced in delivery_units must exist in audience definitions.
    audience_labels = {
        row.get("label_name", "") for row in payload.get("audience", {}).get("rows", [])
        if isinstance(row, dict)
    } if isinstance(payload.get("audience"), dict) else set()
    if audience_labels:  # only validate when audience sheet is present
        for index, unit in enumerate(units):
            ref = unit.get("targeting_definition", "")
            if ref and ref not in audience_labels:
                issues.append(_issue(
                    "WARN", "cross_sheet_reference_missing",
                    f"delivery_units[{index}].targeting_definition '{ref}' not found in audience definitions.",
                    "strategy-analysis",
                    action="Ensure audience label is defined in the Audience sheet before referencing it.",
                ))

    # ── common-validation.md 规则：recommended 不得混入执行行 ─────────────
    statuses = payload.get("statuses", {})
    for index, unit in enumerate(units):
        unit_status = unit.get("field_status") or statuses.get(f"delivery_unit_{index}")
        if unit_status == "recommended":
            issues.append(_issue(
                "BLOCK", "recommended_in_execution_row",
                f"delivery_units[{index}] has field_status=recommended. Must be confirmed before writing to execution rows.",
                "strategy-analysis",
                action="Get user confirmation for this delivery unit before including it in the final plan.",
            ))

    meta = payload.get("_meta", payload.get("meta", {}))
    requested_final = meta.get("deliverable_status") == "final"
    has_block = any(item["severity"] == "BLOCK" for item in issues)
    has_warn = any(item["severity"] == "WARN" for item in issues)
    if requested_final and (has_block or completeness["deliverable_status"] != "final_candidate"):
        issues.append(_issue("BLOCK", "final_status_not_allowed", "The plan is marked final before required facts and checks pass.", "preflight-self-check"))
    if requested_final and not meta.get("confirmer"):
        issues.append(_issue("BLOCK", "final_confirmer_missing", "Final delivery requires a confirmer.", "preflight-self-check"))

    has_block = any(item["severity"] == "BLOCK" for item in issues)
    has_warn = any(item["severity"] == "WARN" for item in issues)
    result = "BLOCK" if has_block else "WARN" if has_warn else "PASS"
    return {
        "result": result,
        "deliverable_status": "blocked" if has_block else "draft" if has_warn else "final_candidate",
        "checks": {
            "brief_and_constraints": not any(i["rule"] in {"required_fields_missing", "required_fields_conflict", "hard_constraint_unsatisfied"} for i in issues),
            "calculations": not any(i["responsible_node"] == "deterministic-calculation" and i["severity"] == "BLOCK" for i in issues),
            "evidence": not any(i["responsible_node"] == "evidence-search" and i["severity"] == "BLOCK" for i in issues),
            "advice_separation": not any(i["rule"] == "recommendation_overwrote_target" for i in issues),
            "delivery_metadata": not any(i["rule"].startswith("final_") for i in issues),
            # common-validation.md checks
            "no_rejected_evidence": not any(i["rule"] == "rejected_evidence_in_plan" for i in issues),
            "cross_sheet_references": not any(i["rule"] == "cross_sheet_reference_missing" for i in issues),
            "no_recommended_in_execution": not any(i["rule"] == "recommended_in_execution_row" for i in issues),
        },
        "issues": issues,
        "rerun_plan": build_rerun_plan(issues),
    }


def build_rerun_plan(issues: list[dict]) -> list[dict]:
    """Return unique local reruns; never default to the full workflow."""
    result, seen = [], set()
    for issue in issues:
        node = issue.get("rerun_from") or issue.get("responsible_node")
        if not node or node in seen:
            continue
        seen.add(node)
        result.append({
            "rerun_from": node,
            "refresh_downstream": _downstream_nodes(node),
            "attempts_remaining": issue.get("attempts_remaining", 0),
            "human_intervention": issue.get("human_intervention", False),
        })
    return result


def _downstream_nodes(node: str) -> list[str]:
    order = [
        "route-confirm", "material-parsing", "dimension-discovery", "completeness-check",
        "kpi-collection", "evidence-search",
        "strategy-analysis", "deterministic-calculation",
        "preflight-self-check", "workbook-generation",
    ]
    return order[order.index(node) + 1 :] if node in order else []


def validate(payload: dict) -> dict:
    if "values" not in payload:
        payload = {**payload, "values": payload, "statuses": payload.get("field_statuses", {})}
    return preflight(payload)


FUNCTIONS = {
    "route": route_task,
    "assess": assess_completeness,
    "allocate": allocate_budget,
    "allocate-matrix": allocate_matrix,
    "derive-schedule": derive_daily_schedule,
    "compute-kpi": compute_kpi,
    "compute-weights": compute_weights,
    "audience-alignment": audience_budget_alignment,
    "audience-overlap": audience_overlap_check,
    "normalize-budget": normalize_budget,
    "currency-convert": currency_convert,
    "suggest-budget": suggest_budget,
    "kpi": calculate_kpi,
    "kpi-feasibility": kpi_budget_feasibility,
    "kpi-collect": collect_kpi_targets,
    "confidence": score_evidence,
    "kpi-check": check_kpi_tolerance,
    "preflight": preflight,
    "validate": validate,
}


def _load_input(value: str) -> dict:
    path = Path(value)
    # utf-8-sig 同时兼容带 BOM（Windows 记事本/PowerShell 默认）与无 BOM 的 UTF-8
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else json.loads(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generic Media Planner deterministic core")
    parser.add_argument("function", choices=FUNCTIONS)
    parser.add_argument("--input", required=True, help="JSON file path or inline JSON")
    args = parser.parse_args()
    print(json.dumps(FUNCTIONS[args.function](_load_input(args.input)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
