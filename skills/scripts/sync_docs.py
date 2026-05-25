#!/usr/bin/env python3
"""
同步 references/*.md 文档 — 从 .cache/ JSON 生成字段表格和可选值列表
"""
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = SCRIPT_DIR / ".cache"
REFERENCES_DIR = SCRIPT_DIR.parent / "references"

MARKER_START = "<!-- AUTO-GENERATED-START -->"
MARKER_END = "<!-- AUTO-GENERATED-END -->"

MODULE_CACHE_MAP = {
    "lead": "form_clue.json",
    "customer": "form_account.json",
    "opportunity": "form_opportunity.json",
    "contact": "form_contact.json",
}

SKIP_TYPES = {"MEMBER", "SERIAL_NUMBER", "DIVIDER"}

TYPE_FORMAT_MAP = {
    "SELECT": "SELECT",
    "RADIO": "SELECT",
    "DATA_SOURCE": "⚠️ 实体 ID",
    "DATA_SOURCE_MULTIPLE": "⚠️ 实体 ID（可多选）",
    "LOCATION": "LOCATION",
    "INPUT_NUMBER": "数字",
    "DATE_TIME": "YYYY-MM-DD",
    "PHONE": "手机/电话",
    "INPUT": "文本",
    "TEXTAREA": "文本",
    "INPUT_MULTIPLE": "文本（多值）",
}

# field-options.md 中的分组配置：(组标题, 匹配字段名列表)
OPTION_GROUPS = [
    ("来源（线索来源 / 客户来源 / 商机来源）", ["线索来源", "客户来源", "来源"]),
    ("线上来源详情", ["线上来源详情"]),
    ("区域", ["区域"]),
    ("行业", ["行业"]),
    ("签约类型（商机）", ["签约类型"]),
    ("客户类型", ["类型"]),
    ("分级", ["分级"]),
    ("是否已拜访（线索）", ["是否已拜访"]),
    ("状态（线索）", ["状态"]),
]


def _load_cache(filename):
    path = CACHE_DIR / filename
    if not path.exists():
        return None
    return json.loads(path.read_text("utf-8"))


def _get_format(field):
    return TYPE_FORMAT_MAP.get(field["type"], "文本")


def _generate_fields_section(fields):
    required_fields = []
    optional_fields = []

    for f in fields:
        if f["type"] in SKIP_TYPES:
            continue
        if f["required"]:
            required_fields.append(f)
        else:
            optional_fields.append(f)

    lines = []
    lines.append("")
    lines.append("| # | 字段 | JSON 键名 | 格式 |")
    lines.append("|---|------|----------|------|")
    for i, f in enumerate(required_fields, 1):
        fmt = _get_format(f)
        lines.append(f"| {i} | {f['name']} | {f['name']} | {fmt} |")

    if optional_fields:
        names = "、".join(f["name"] for f in optional_fields)
        lines.append("")
        lines.append(f"选填：{names}")

    lines.append("")
    return "\n".join(lines)


def _replace_auto_section(filepath, new_content):
    text = filepath.read_text("utf-8")
    start_idx = text.find(MARKER_START)
    end_idx = text.find(MARKER_END)
    if start_idx == -1 or end_idx == -1:
        return False
    before = text[:start_idx + len(MARKER_START)]
    after = text[end_idx:]
    filepath.write_text(before + "\n" + new_content + "\n" + after, "utf-8")
    return True


def update_module_doc(module):
    cache_file = MODULE_CACHE_MAP.get(module)
    if not cache_file:
        return
    data = _load_cache(cache_file)
    if not data:
        return
    fields = data["fields"]
    section = _generate_fields_section(fields)
    md_path = REFERENCES_DIR / f"{module}.md"
    if md_path.exists():
        _replace_auto_section(md_path, section)


def update_field_options():
    all_fields = {}
    for module, cache_file in MODULE_CACHE_MAP.items():
        data = _load_cache(cache_file)
        if not data:
            continue
        for f in data["fields"]:
            if f["type"] in ("SELECT", "RADIO") and f.get("label_to_value"):
                key = f["name"]
                if key not in all_fields:
                    all_fields[key] = list(f["label_to_value"].keys())

    product_data = _load_cache("product_map.json")
    product_names = list(product_data["map"].keys()) if product_data else []

    lines = []
    lines.append("# SELECT 字段可选值")
    lines.append("")
    lines.append("> 传值规则：传中文值即可，支持传简称（如\"非银金融\"）或完整值，CLI 自动做前缀匹配。")
    lines.append("")

    for group_title, field_names in OPTION_GROUPS:
        labels = None
        for name in field_names:
            if name in all_fields:
                labels = all_fields[name]
                break
        if not labels:
            continue
        lines.append(f"## {group_title}")
        lines.append("")
        lines.append(", ".join(labels))
        lines.append("")

    if product_names:
        lines.append("## 产品类型（可多选）")
        lines.append("")
        lines.append(", ".join(product_names))
        lines.append("")

    md_path = REFERENCES_DIR / "field-options.md"
    md_path.write_text("\n".join(lines), "utf-8")


def update_all_docs():
    update_field_options()
    for module in MODULE_CACHE_MAP:
        update_module_doc(module)


if __name__ == "__main__":
    update_all_docs()
    print("references 文档已更新")
