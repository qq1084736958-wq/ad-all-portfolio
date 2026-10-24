"""
Mapping YAML 加载器
- 读取 YAML 文件
- 基础结构校验
- 返回 dict 结构
"""
import yaml
from pathlib import Path


class MappingValidationError(Exception):
    pass


def load_mapping(yaml_path):
    """加载并校验 mapping YAML"""
    p = Path(yaml_path)
    if not p.exists():
        raise FileNotFoundError(f"Mapping not found: {yaml_path}")

    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # 基础校验
    required_top = ["sheet_name", "table_type"]
    for k in required_top:
        if k not in data:
            raise MappingValidationError(f"Missing required top-level key: {k}")

    valid_types = {"static_kv", "list_row", "list_col", "grouped_list_row", "matrix", "schedule"}
    if data["table_type"] not in valid_types:
        raise MappingValidationError(
            f"Unknown table_type '{data['table_type']}'. Valid: {valid_types}"
        )

    return data


def validate_template_against_mapping(ws, mapping):
    """
    校验模板当前布局是否符合 mapping 描述
    返回 (ok: bool, warnings: list)
    """
    warnings_ = []
    if mapping["table_type"] == "static_kv":
        for field_key, field_def in mapping.get("fields", {}).items():
            label_cell = field_def.get("label_cell")
            expected_label = field_def.get("label_text")
            if label_cell and expected_label:
                actual = ws[label_cell].value
                if actual != expected_label:
                    warnings_.append(
                        f"Field '{field_key}': label_cell {label_cell} "
                        f"expected '{expected_label}', got '{actual}'"
                    )
    return len(warnings_) == 0, warnings_
