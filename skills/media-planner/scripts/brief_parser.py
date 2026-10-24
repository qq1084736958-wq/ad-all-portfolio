"""Channel-neutral Brief parser with lossless, open-dimension output.

Known fields are a minimum schema, not a closed ontology. Every non-empty
source clause is retained, and unknown content is routed to dimension review.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DIMENSIONS = {
    "business_and_product": ["brand", "product_or_service", "business_goal", "selling_points", "price_range"],
    "market_and_time": ["market", "language", "timezone", "campaign_start", "campaign_end", "marketing_milestone"],
    "budget_and_constraints": ["total_budget", "currency", "budget_allocation", "hard_constraints", "preferences"],
    "channel_and_funnel": ["channel_plan", "funnel_stage", "objective", "destination"],
    "audience": ["audience", "age_range", "gender", "exclusions"],
    "creative": ["creative_readiness", "creative_formats", "creative_quantity", "creative_language"],
    "performance_and_evidence": ["historical_performance", "kpi_targets", "competitors", "internal_resources"],
}

FIELD_ALIASES = {
    "brand": ["品牌", "brand"],
    "product_or_service": ["产品", "服务", "sku", "product", "service"],
    "business_goal": ["业务目标", "营销目标", "campaign goal", "business goal"],
    "market": ["市场", "国家", "地区", "market", "country", "region"],
    "language": ["语言", "language"],
    "timezone": ["时区", "timezone"],
    "campaign_period": ["投放周期", "活动周期", "campaign period", "flight dates", "period"],
    "total_budget": ["总预算", "预算", "total budget", "budget"],
    "currency": ["币种", "currency"],
    "channel_plan": ["投放渠道", "媒体渠道", "平台", "channel", "media mix", "platform"],
    "budget_allocation": ["预算分配", "预算比例", "allocation", "budget split"],
    "audience": ["目标受众", "核心人群", "受众", "audience", "target audience"],
    "destination": ["落地页", "目标链接", "destination", "landing page", "url"],
    "creative_readiness": ["素材状态", "素材准备", "creative readiness", "asset status"],
    "creative_formats": ["素材形式", "素材类型", "creative format", "asset format"],
    "historical_performance": ["历史表现", "历史数据", "historical performance", "past performance"],
    "kpi_targets": ["kpi", "指标目标", "目标指标"],
    "competitors": ["竞品", "竞争对手", "competitor"],
    "internal_resources": ["内部资源", "自有资源", "internal resource"],
    "hard_constraints": ["必须", "禁止", "不得", "硬约束", "must", "prohibited", "constraint"],
    "preferences": ["偏好", "倾向", "prefer", "preference"],
}

DATE_RANGE = re.compile(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)\s*(?:至|到|~|—|-|–)\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)")
BUDGET = re.compile(r"(?:(USD|CNY|RMB|EUR|GBP|JPY|HKD)\s*)?([0-9][0-9,]*(?:\.\d+)?)\s*(万|千|million|k|m)?", re.I)
URL = re.compile(r"https?://[^\s<>]+", re.I)
CLAUSE_SPLIT = re.compile(r"\s*[；;]\s*")


def _normalize_date(value: str) -> str:
    value = value.strip().replace("年", "-").replace("月", "-").replace("日", "").replace("/", ".")
    parts = re.split(r"[-.]", value)
    if len(parts) == 3:
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return value


def _normalize_budget(raw: str) -> tuple[float | None, str | None]:
    match = BUDGET.search(raw.replace("$", "USD ").replace("¥", "CNY "))
    if not match:
        return None, None
    currency = (match.group(1) or "").upper() or None
    amount = float(match.group(2).replace(",", ""))
    suffix = (match.group(3) or "").lower()
    if suffix == "万":
        amount *= 10000
    elif suffix in {"千", "k"}:
        amount *= 1000
    elif suffix in {"million", "m"}:
        amount *= 1000000
    return amount, currency


def _field_from_label(label: str) -> str | None:
    compact = re.sub(r"\s+", " ", label.strip().lower())
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            a = alias.lower()
            # 英文别名按整词匹配，避免 "market" 命中 "marketing"、
            # "service" 命中 "services" 这类子串误匹配；中文别名保持子串。
            if re.search(r"[a-z0-9]", a):
                if re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", compact):
                    return field
            elif a in compact:
                return field
    return None


def _source_segments(text: str) -> list[dict]:
    """Split conservatively while preserving every non-empty source clause."""
    segments = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        clauses = [item.strip() for item in CLAUSE_SPLIT.split(line) if item.strip()]
        for clause_no, clause in enumerate(clauses, start=1):
            segments.append({
                "segment_id": f"L{line_no}C{clause_no}",
                "source_location": f"line:{line_no}:clause:{clause_no}",
                "line": line_no,
                "clause": clause_no,
                "raw_text": clause,
            })
    return segments


def parse_brief(text: str, source_ref: str = "user_material") -> dict:
    fields: dict[str, Any] = {}
    field_meta: dict[str, dict] = {}
    conflicts: list[dict] = []
    content_segments = _source_segments(text)

    for segment in content_segments:
        line_no, line = segment["line"], segment["raw_text"]
        recognized_fields: list[str] = []
        parts = re.split(r"[:：]", line, maxsplit=1)
        if len(parts) == 2:
            label, raw_value = parts[0].strip(), parts[1].strip()
            field = _field_from_label(label)
            if field and raw_value:
                value: Any = raw_value
                if field == "total_budget":
                    amount, currency = _normalize_budget(raw_value)
                    value = amount if amount is not None else raw_value
                    if currency and "currency" not in fields:
                        fields["currency"] = currency
                        field_meta["currency"] = _meta(source_ref, segment["source_location"], raw_value)
                        recognized_fields.append("currency")
                if field in fields and fields[field] != value:
                    conflicts.append({
                        "field": field, "existing": fields[field], "incoming": value,
                        "source_ref": source_ref, "source_location": segment["source_location"],
                    })
                    field_meta[field]["field_status"] = "conflict"
                else:
                    fields[field] = value
                    field_meta[field] = _meta(source_ref, segment["source_location"], raw_value)
                recognized_fields.append(field)

        date_match = DATE_RANGE.search(line)
        if date_match:
            fields.setdefault("campaign_start", _normalize_date(date_match.group(1)))
            fields.setdefault("campaign_end", _normalize_date(date_match.group(2)))
            field_meta.setdefault("campaign_start", _meta(source_ref, segment["source_location"], date_match.group(1)))
            field_meta.setdefault("campaign_end", _meta(source_ref, segment["source_location"], date_match.group(2)))
            recognized_fields.extend(["campaign_start", "campaign_end"])
        url_match = URL.search(line)
        if url_match:
            if "destination" not in fields:
                fields["destination"] = url_match.group(0).rstrip(".,，。")
                field_meta["destination"] = _meta(source_ref, segment["source_location"], url_match.group(0))
            recognized_fields.append("destination")

        segment["recognized_fields"] = sorted(set(recognized_fields))
        segment["coverage_status"] = "recognized" if recognized_fields else "unmapped"

    dimensions = {
        dimension: {
            "fields": names,
            "present": [name for name in names if name in fields],
            "missing": [name for name in names if name not in fields],
            "schema_role": "minimum_schema",
        }
        for dimension, names in DIMENSIONS.items()
    }
    unmapped = [segment for segment in content_segments if segment["coverage_status"] == "unmapped"]
    return {
        "source_ref": source_ref,
        "analysis_dimensions": dimensions,
        "fields": fields,
        "field_meta": field_meta,
        "conflicts": conflicts,
        "content_segments": content_segments,
        "dimension_discovery_candidates": content_segments,
        "unmapped_content": unmapped,
        "discovered_dimensions": [],
        "coverage_summary": {
            "total_segments": len(content_segments),
            "recognized_segments": len(content_segments) - len(unmapped),
            "unmapped_segments": len(unmapped),
            "requires_dimension_discovery": bool(content_segments),
        },
        "warnings": [
            "Extracted values require confirmation before final delivery.",
            *(["Unmapped content requires open-ended dimension discovery before analysis continues."] if unmapped else []),
        ],
    }


def _meta(source_ref: str, source_location: str, raw_value: str) -> dict:
    return {
        "field_status": "extracted",
        "source_type": "project_material",
        "source_ref": source_ref,
        "source_location": source_location,
        "raw_value": raw_value,
        "requires_confirmation": True,
    }


def merge_parsed_briefs(parsed_list: list[dict]) -> dict:
    """v1.9: Merge multiple parsed brief sources, detect cross-source conflicts.
    
    Args:
      parsed_list: list of dicts from parse_brief()
    
    Returns:
      merged fields, field_meta, cross_source_conflicts[]
    """
    merged_fields = {}
    merged_meta = {}
    cross_conflicts = []
    
    for parsed in parsed_list:
        src = parsed.get("source_ref", "unknown")
        fields = parsed.get("fields", {})
        meta = parsed.get("field_meta", {})
        
        for field, value in fields.items():
            if field not in merged_fields:
                merged_fields[field] = value
                merged_meta[field] = meta.get(field, {})
                merged_meta[field]["sources"] = [src]
            else:
                if merged_fields[field] != value:
                    # Cross-source conflict!
                    cross_conflicts.append({
                        "field": field,
                        "value_a": merged_fields[field],
                        "source_a": merged_meta[field].get("source_ref", "?"),
                        "value_b": value,
                        "source_b": src,
                        "status": "conflict",
                    })
                    merged_meta[field]["field_status"] = "conflict"
                    merged_meta[field]["sources"].append(src)
                else:
                    merged_meta[field]["sources"].append(src)
    
    return {
        "fields": merged_fields,
        "field_meta": merged_meta,
        "cross_source_conflicts": cross_conflicts,
        "sources_merged": [p.get("source_ref") for p in parsed_list],
        "conflict_count": len(cross_conflicts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a Media Plan brief without dropping unknown dimensions")
    parser.add_argument("--input", required=True, help="UTF-8 text/markdown file")
    parser.add_argument("--source-ref", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    path = Path(args.input)
    result = parse_brief(path.read_text(encoding="utf-8"), args.source_ref or path.name)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
