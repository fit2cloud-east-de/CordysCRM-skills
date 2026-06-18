#!/usr/bin/env python3
"""
字段一致性校验：防止 DYNAMICS / 排序里出现"幽灵时间字段"。

背景：DYNAMICS 时间规则与字段口径散落在十几个文件里，每次统一字段
（如 signTime→createTime、回款统一 recordEndTime）都容易漏改某些文件，
或在合并他人分支时把过期字段静默带回来。本脚本扫描全部 conditions/排序
里引用的字段名，比对 references/forms/ 里定义的合法字段，报出不存在的。

用法：
  python3 skills/scripts/validate_fields.py          # 从仓库根目录运行
  python3 skills/scripts/validate_fields.py --quiet   # 只在有问题时输出

退出码：0=无问题，1=发现幽灵字段/非法常量。
"""
import os
import re
import sys
import glob

# 脚本位于 skills/scripts/，仓库根是上两级
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")
FORMS_DIR = os.path.join(SKILLS_DIR, "references", "forms")

# 时间常量白名单（权威表见 core/cli-reference.md 动态时间常量表）
TIME_CONSTANTS = {
    "TODAY", "YESTERDAY", "WEEK", "LAST_WEEK", "MONTH", "LAST_MONTH",
    "QUARTER", "LAST_QUARTER", "YEAR", "LAST_YEAR", "LAST_SEVEN", "LAST_THIRTY",
    "CUSTOM",  # 自定义天数 ["CUSTOM", N, "BEFORE_DAY"]
}

# 系统/通用字段：不在 form 字段表里，但属于合法过滤/排序字段
SYSTEM_FIELDS = {
    "ownerId", "owner", "userId", "departmentId",
}

# 已知的展示专用字段：明确"不可用于过滤"，若出现在 DYNAMICS/排序里则是误用
DISPLAY_ONLY_FIELDS = {
    "stageUpdateTime",  # 商机阶段变更时间，仅展示，过滤须用 updateTime
}


def collect_legal_fields():
    """从 references/forms/*.md 的字段表第 2 列收集合法 name 值。"""
    legal = set(SYSTEM_FIELDS)
    # 字段表行形如： | 显示名 | name值 | type | 说明 |
    row = re.compile(r"^\|[^|]*\|\s*([A-Za-z][A-Za-z0-9_]*)\s*\|\s*[A-Z_]+\s*\|")
    for path in glob.glob(os.path.join(FORMS_DIR, "*.md")):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = row.match(line)
                if m:
                    legal.add(m.group(1))
    return legal


def iter_skill_files():
    for dirpath, _, filenames in os.walk(SKILLS_DIR):
        for fn in filenames:
            if fn.endswith((".md", ".sh", ".py")):
                yield os.path.join(dirpath, fn)


def scan_references():
    """扫描 DYNAMICS 的 name/value 与排序字段。返回 (field_refs, const_refs)。
    field_refs: [(field, file, lineno, kind)]
    const_refs: [(value, file, lineno)]
    """
    # DYNAMICS 条件：抓 operator 为 DYNAMICS 的 name 和 value（兼容有无空格）
    dyn = re.compile(
        r'"operator"\s*:\s*"DYNAMICS"[^}]*?"name"\s*:\s*"([A-Za-z][A-Za-z0-9_]*)"'
    )
    dyn_rev = re.compile(
        r'"name"\s*:\s*"([A-Za-z][A-Za-z0-9_]*)"[^}]*?"operator"\s*:\s*"DYNAMICS"'
    )
    dyn_val = re.compile(
        r'"operator"\s*:\s*"DYNAMICS"[^}]*?"value"\s*:\s*"([A-Z_]+)"'
    )
    dyn_val_rev = re.compile(
        r'"value"\s*:\s*"([A-Z_]+)"[^}]*?"operator"\s*:\s*"DYNAMICS"'
    )
    # 排序字段：形如 createTime:desc / recordEndTime:asc（出现在文档表格/示例里）
    sort_re = re.compile(r'`?([A-Za-z][A-Za-z0-9_]*):(?:asc|desc)`?')

    field_refs = []
    const_refs = []
    skip_self = os.path.basename(__file__)
    for path in iter_skill_files():
        if os.path.basename(path) == skip_self:
            continue
        rel = os.path.relpath(path, REPO_ROOT)
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                for rgx in (dyn, dyn_rev):
                    for fld in rgx.findall(line):
                        field_refs.append((fld, rel, i, "DYNAMICS"))
                for rgx in (dyn_val, dyn_val_rev):
                    for val in rgx.findall(line):
                        const_refs.append((val, rel, i))
                for fld in sort_re.findall(line):
                    field_refs.append((fld, rel, i, "sort"))
    return field_refs, const_refs


def main():
    quiet = "--quiet" in sys.argv
    legal = collect_legal_fields()
    field_refs, const_refs = scan_references()

    ghost = []   # 字段不在任何 form 定义里
    display = []  # 用了展示专用字段做过滤/排序
    bad_const = []  # DYNAMICS value 不在常量表

    for fld, f, ln, kind in field_refs:
        if fld in DISPLAY_ONLY_FIELDS:
            display.append((fld, f, ln, kind))
        elif fld not in legal:
            ghost.append((fld, f, ln, kind))

    for val, f, ln in const_refs:
        if val not in TIME_CONSTANTS:
            bad_const.append((val, f, ln))

    problems = len(ghost) + len(display) + len(bad_const)

    if not quiet:
        print(f"合法字段（来自 {os.path.relpath(FORMS_DIR, REPO_ROOT)}/*.md）：{len(legal)} 个")
        print(f"扫描到字段引用 {len(field_refs)} 处，DYNAMICS 常量引用 {len(const_refs)} 处\n")

    if ghost:
        print("❌ 幽灵字段（不在任何 form 字段表中定义）：")
        for fld, f, ln, kind in sorted(set(ghost)):
            print(f"   {f}:{ln}  [{kind}]  {fld}")
        print()
    if display:
        print("❌ 展示专用字段被用于过滤/排序（应改用可过滤字段）：")
        for fld, f, ln, kind in sorted(set(display)):
            print(f"   {f}:{ln}  [{kind}]  {fld}")
        print()
    if bad_const:
        print("❌ 非法 DYNAMICS 时间常量（不在常量表中）：")
        for val, f, ln in sorted(set(bad_const)):
            print(f"   {f}:{ln}  {val}")
        print()

    if problems == 0:
        if not quiet:
            print("✅ 未发现幽灵字段或非法时间常量")
        return 0
    print(f"共发现 {problems} 处问题。")
    return 1


if __name__ == "__main__":
    sys.exit(main())


