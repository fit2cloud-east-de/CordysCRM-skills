#!/usr/bin/env python3
"""Validate Cordys department trees and expose safe descendant/outline views."""

from __future__ import annotations

import json
import sys
from typing import Optional, Sequence


class OrgTreeError(ValueError):
    """The department-tree response cannot be consumed safely."""


def _normalized_name(value: object) -> str:
    return "".join(str(value or "").split()).casefold()


def _tree_roots(document: object) -> list[dict]:
    if isinstance(document, dict):
        code = document.get("code")
        if code is not None and str(code) != "100200":
            message = document.get("message") or document.get("msg") or ""
            detail = f"：{message}" if message else ""
            raise OrgTreeError(f"部门树查询失败，code={code}{detail}")
        tree = document.get("data", document)
    else:
        tree = document

    if isinstance(tree, list):
        roots = tree
    elif isinstance(tree, dict):
        roots = [tree]
    else:
        raise OrgTreeError("部门树响应缺少 data 对象或数组")

    if not roots:
        raise OrgTreeError("部门树为空，禁止按空部门范围继续查询")
    if not all(isinstance(node, dict) for node in roots):
        raise OrgTreeError("部门树根节点必须是 JSON 对象")
    return roots


def _flatten_departments(document: object) -> list[dict]:
    departments: list[dict] = []
    seen_ids: set[str] = set()

    def visit(
        node: dict,
        parents: list[str],
        parent_id: Optional[str],
        depth: int,
    ) -> None:
        department_id = str(node.get("id") or "").strip()
        if not department_id:
            raise OrgTreeError("部门树节点缺少非空 id")
        if department_id in seen_ids:
            raise OrgTreeError(f"部门树包含重复 id：{department_id}")
        seen_ids.add(department_id)

        name = str(node.get("name") or "").strip()
        label = name or department_id
        path = [*parents, label]
        children = node.get("children")
        if children is None:
            children = []
        if not isinstance(children, list) or not all(
            isinstance(child, dict) for child in children
        ):
            raise OrgTreeError(f"部门「{label}」的 children 必须是对象数组")

        departments.append(
            {
                "id": department_id,
                "name": name,
                "normalizedName": _normalized_name(name),
                "parentId": parent_id,
                "path": " / ".join(path),
                "depth": depth,
                "node": node,
            }
        )
        for child in children:
            visit(child, path, department_id, depth + 1)

    for root in _tree_roots(document):
        visit(root, [], None, 0)
    return departments


def collect_department_ids(document: object) -> list[str]:
    """Return every visible department ID in tree order."""
    return [item["id"] for item in _flatten_departments(document)]


def _ambiguous(target: str, matches: list[dict]) -> OrgTreeError:
    candidates = "；".join(
        f"{item['path']}（id={item['id']}）" for item in matches[:10]
    )
    if len(matches) > 10:
        candidates += f"；另有 {len(matches) - 10} 个候选"
    return OrgTreeError(
        f"部门名称「{target}」匹配到多个部门：{candidates}。请改用部门 ID"
    )


def resolve_department(document: object, target: str) -> dict:
    """Resolve an exact ID, normalized exact name, or unique partial name."""
    departments = _flatten_departments(document)
    target = str(target or "").strip()
    if not target:
        raise OrgTreeError("部门名称或 ID 不能为空")

    id_matches = [item for item in departments if item["id"] == target]
    if id_matches:
        return id_matches[0]

    normalized_target = _normalized_name(target)
    exact_matches = [
        item
        for item in departments
        if item["normalizedName"] == normalized_target
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise _ambiguous(target, exact_matches)

    partial_matches = [
        item
        for item in departments
        if normalized_target and normalized_target in item["normalizedName"]
    ]
    if len(partial_matches) == 1:
        return partial_matches[0]
    if len(partial_matches) > 1:
        raise _ambiguous(target, partial_matches)
    raise OrgTreeError(f"未找到部门「{target}」")


def collect_descendant_ids(document: object, target: str = "") -> list[str]:
    """Return all IDs, or one resolved department and all of its descendants."""
    if not str(target or "").strip():
        return collect_department_ids(document)

    selected = resolve_department(document, target)
    result: list[str] = []

    def visit(node: dict) -> None:
        result.append(str(node["id"]))
        for child in node.get("children") or []:
            visit(child)

    visit(selected["node"])
    return result


def collect_department_outline(document: object, target: str = "") -> list[dict]:
    """Return a joinable flat hierarchy, optionally rooted at one department."""
    departments = _flatten_departments(document)
    selected_id: Optional[str] = None
    selected_depth = 0
    allowed_ids: Optional[set[str]] = None

    if str(target or "").strip():
        selected = resolve_department(document, target)
        selected_id = selected["id"]
        selected_depth = selected["depth"]
        allowed_ids = set()

        def collect(node: dict) -> None:
            allowed_ids.add(str(node["id"]))
            for child in node.get("children") or []:
                collect(child)

        collect(selected["node"])

    result = []
    for item in departments:
        if allowed_ids is not None and item["id"] not in allowed_ids:
            continue
        result.append(
            {
                "id": item["id"],
                "name": item["name"],
                # 指定子树时让输出自包含：目标根节点的父级不在结果里，因此置空。
                "parentId": (
                    None if item["id"] == selected_id else item["parentId"]
                ),
                "path": item["path"],
                "depth": item["depth"] - selected_depth,
            }
        )
    if not result:
        raise OrgTreeError("部门树未返回任何可输出节点")
    return result


def render_descendant_ids(raw_response: str, target: str = "") -> str:
    try:
        document = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise OrgTreeError(f"部门树接口返回非 JSON：{exc}") from exc
    ids = collect_descendant_ids(document, target)
    if not ids:
        raise OrgTreeError("部门树未返回任何部门 ID")
    return json.dumps(ids, ensure_ascii=False, separators=(",", ":"))


def render_department_outline(raw_response: str, target: str = "") -> str:
    try:
        document = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise OrgTreeError(f"部门树接口返回非 JSON：{exc}") from exc
    outline = collect_department_outline(document, target)
    return json.dumps(outline, ensure_ascii=False, separators=(",", ":"))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ("ids", "outline") or len(args) > 2:
        print(
            "错误: 用法: org_tree.py <ids|outline> [部门名称或ID]",
            file=sys.stderr,
        )
        return 1
    raw_response = sys.stdin.read()
    try:
        target = args[1] if len(args) == 2 else ""
        if args[0] == "ids":
            output = render_descendant_ids(raw_response, target)
        else:
            output = render_department_outline(raw_response, target)
    except OrgTreeError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
