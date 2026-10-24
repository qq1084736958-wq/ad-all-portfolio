"""
media-planner 环境自检脚本
用法：python selfcheck.py
换环境/新机器第一次跑 plan 前先跑这个，确认依赖齐全。
"""
import sys
import importlib
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
CHECKS = []

def check(name, ok, detail=""):
    CHECKS.append((name, ok, detail))

# 1. Python 版本
py_ok = sys.version_info >= (3, 10)
check(f"Python >= 3.10 (当前 {sys.version.split()[0]})", py_ok,
      "建议 3.10+" if py_ok else "升级 Python")

# 2. Python 依赖
for pkg, import_name in [("openpyxl", "openpyxl"), ("PyYAML", "yaml"), ("python-docx", "docx")]:
    try:
        importlib.import_module(import_name)
        check(f"Python 包 {pkg}", True)
    except ImportError:
        check(f"Python 包 {pkg}", False, "pip install -r requirements.txt")

# 3. 关键脚本
for f in ["plan_core.py", "generate_mediaplan.py", "strategy_engines.py",
          "mp-reader.py", "mp-backfill.py"]:
    p = SKILL_ROOT / "scripts" / f
    check(f"脚本 scripts/{f}", p.exists())

# 4. Excel 模板
for f in ["MediaPlan_Template_Standard.xlsx", "MediaPlan_Internal_Template.xlsx"]:
    p = SKILL_ROOT / "references" / f
    check(f"模板 references/{f}", p.exists())

# 5. Mapping 文件
mp_dir = SKILL_ROOT / "scripts" / "mappings"
yaml_count = len(list(mp_dir.glob("*.yaml"))) if mp_dir.exists() else 0
check(f"Mapping yaml 文件 (≥7，当前 {yaml_count})", yaml_count >= 7)

# 6. Playbook 与规则
for f in ["references/strategy-playbook.md", "references/strategy-schema.md",
          "memory/global/learnings.md", "SKILL.md"]:
    p = SKILL_ROOT / f
    check(f"规则 {f}", p.exists())

# 7. Excel 引擎子模块
engine_dir = SKILL_ROOT / "scripts" / "excel_engine"
engine_ok = engine_dir.exists() and len(list(engine_dir.glob("*.py"))) >= 5
check("excel_engine 子模块齐全", engine_ok)

# ── 输出 ──
print("=" * 60)
print("media-planner 环境自检")
print(f"Skill root: {SKILL_ROOT}")
print("=" * 60)
fail = 0
for name, ok, detail in CHECKS:
    mark = "✅" if ok else "❌"
    line = f"{mark} {name}"
    if detail and not ok:
        line += f"  → {detail}"
    print(line)
    if not ok:
        fail += 1
print("=" * 60)
if fail == 0:
    print("全部通过，可以开始跑 plan。")
    sys.exit(0)
else:
    print(f"{fail} 项未通过，先解决上面的 ❌ 再开始。")
    sys.exit(1)
