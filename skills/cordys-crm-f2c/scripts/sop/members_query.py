#!/usr/bin/env python3
"""Cordys CRM 成员查询：单进程构造请求、补全部门范围并输出结果。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional, Sequence
from urllib import request
from urllib.error import HTTPError, URLError


DEFAULT_PAGE_SIZE = 500
CACHE_TTL_SECONDS = 6 * 60 * 60
Transport = Callable[[str, str, Optional[dict]], str]
ACTIVE_STATUS_CONDITION = {
    "value": True,
    "operator": "IN",
    "name": "status",
    "multipleValue": False,
    "type": "SELECT",
}


class MembersQueryError(RuntimeError):
    """成员查询无法安全继续。"""


class MembersResponseError(MembersQueryError):
    """后端返回 HTTP 或业务错误，并保留原始响应作为诊断证据。"""

    def __init__(self, message: str, response: str = "") -> None:
        super().__init__(message)
        self.response = response


def parse_members_cli_args(
    args: Sequence[str],
) -> tuple[str, str, bool, bool, bool]:
    """解析公开 CLI 参数，兼容 JSON 在 flags 前后出现。"""
    payload = ""
    name = ""
    compact = False
    active = False
    exact_departments = False
    payload_seen = False
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--name":
            if index + 1 >= len(args) or not args[index + 1]:
                raise MembersQueryError("--name 需要非空姓名")
            name = args[index + 1]
            index += 2
            continue
        if token == "--compact":
            compact = True
            index += 1
            continue
        if token == "--active":
            active = True
            index += 1
            continue
        if token == "--exact-departments":
            exact_departments = True
            index += 1
            continue
        if token.startswith("--"):
            raise MembersQueryError(f"未知 members 参数: {token}")
        if payload_seen:
            raise MembersQueryError("members 只接受一个 JSON/关键词参数")
        payload = token
        payload_seen = True
        index += 1
    return payload, name, compact, active, exact_departments


def build_members_payload(raw: str = "", name: str = "", active: bool = False) -> dict:
    """构造 /user/list 专用 body，不复用会注入 viewId=ALL 的通用分页 body。"""
    user: dict
    raw = (raw or "").lstrip("\ufeff")
    if not raw or not raw.strip():
        user = {}
    else:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            if raw.lstrip().startswith(("{", "[")):
                raise MembersQueryError(f"成员查询 JSON 解析失败: {exc}") from exc
            user = {"keyword": raw}
        else:
            # 手机号、工号等纯数字关键词会被 json.loads 解析为标量；仍按原字符串搜索。
            user = parsed if isinstance(parsed, dict) else {"keyword": raw}

    # /user/list 会静默忽略这些直觉上很像正确参数的字段。尤其 departmentId
    # 被忽略后，后续逻辑会误以为调用方没有限定部门并自动扩大到全部可见部门。
    # 必须在联网前失败关闭，不能把“参数无效”伪装成全公司查询成功。
    if "departmentId" in user:
        raise MembersQueryError(
            "成员查询不接受单数 departmentId；请先用 crm org ids 展开部门，"
            "再传 departmentIds 数组"
        )
    if "enable" in user:
        raise MembersQueryError(
            "enable 是成员响应字段，不是查询参数；仅查在职成员请使用 --active"
        )
    if "status" in user:
        raise MembersQueryError(
            "status 不能放在成员查询顶层；仅查在职成员请使用 --active，"
            "其他状态请放入 combineSearch.conditions"
        )

    merged = {
        "current": 1,
        "pageSize": DEFAULT_PAGE_SIZE,
        "combineSearch": {"searchMode": "AND", "conditions": []},
        **user,
    }
    # /user/list 带 viewId=ALL 会触发高代价全量视图扫描；成员查询一律不用它。
    merged.pop("viewId", None)

    if type(merged.get("current")) is not int or merged["current"] < 1:
        merged["current"] = 1
    if type(merged.get("pageSize")) is not int or merged["pageSize"] < 1:
        merged["pageSize"] = DEFAULT_PAGE_SIZE

    if "departmentIds" in merged and not isinstance(merged["departmentIds"], list):
        raise MembersQueryError("departmentIds 必须是 JSON 数组")
    department_ids = merged.get("departmentIds")
    if isinstance(department_ids, list):
        merged["departmentIds"] = [
            str(value) for value in department_ids if value is not None and str(value)
        ]
        if not merged["departmentIds"]:
            raise MembersQueryError(
                "departmentIds 显式为空，禁止自动扩大为全部可见部门"
            )

    combine_search = merged.get("combineSearch")
    if not isinstance(combine_search, dict):
        raise MembersQueryError("combineSearch 必须是 JSON 对象")
    conditions = combine_search.get("conditions", [])
    if not isinstance(conditions, list):
        raise MembersQueryError("combineSearch.conditions 必须是 JSON 数组")
    combine_search = {**combine_search, "conditions": conditions}
    combine_search.setdefault("searchMode", "AND")

    if name and not any(
        isinstance(condition, dict) and condition.get("name") == "userName"
        for condition in conditions
    ):
        conditions.append(
            {
                "operator": "CONTAINS",
                "name": "userName",
                "value": name,
                "type": "INPUT",
            }
        )
    status_conditions = [
        condition
        for condition in conditions
        if isinstance(condition, dict) and condition.get("name") == "status"
    ]
    if active:
        if status_conditions:
            if len(status_conditions) != 1 or status_conditions[0] != ACTIVE_STATUS_CONDITION:
                raise MembersQueryError(
                    "--active 与已有 status 条件冲突；请删除自定义 status 条件，"
                    "或去掉 --active"
                )
        else:
            conditions.append(dict(ACTIVE_STATUS_CONDITION))
    merged["combineSearch"] = combine_search
    return merged


def _parse_json_response(raw: str, context: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MembersQueryError(f"{context}返回非 JSON，禁止按空结果处理") from exc


def _require_success(raw: str, context: str, *, code_required: bool) -> object:
    document = _parse_json_response(raw, context)
    code = document.get("code") if isinstance(document, dict) else None
    if (code_required and str(code) != "100200") or (
        code is not None and str(code) != "100200"
    ):
        raise MembersResponseError(f"{context}失败，code={code}", raw)
    return document


def validate_members_document(document: object) -> None:
    """成功码之外还要求稳定的数据形状，避免畸形响应被误当空名单。"""
    if not isinstance(document, dict) or not isinstance(document.get("data"), dict):
        raise MembersQueryError("成员查询成功响应缺少 data 对象")
    data = document["data"]
    if not isinstance(data.get("list"), list):
        raise MembersQueryError("成员查询成功响应缺少 data.list 数组")
    if "total" not in data or type(data["total"]) is not int or data["total"] < 0:
        raise MembersQueryError("成员查询成功响应缺少合法 data.total")


def validate_active_members(document: object) -> None:
    """确认服务端实际执行了 --active，避免把被忽略的过滤条件当成成功。"""
    validate_members_document(document)
    invalid = [
        member
        for member in document["data"]["list"]
        if not isinstance(member, dict) or member.get("enable") is not True
    ]
    if invalid:
        raise MembersQueryError(
            "成员接口未落实 --active：响应仍包含停用成员或缺少 enable=true；"
            "已停止，禁止本地静默过滤后继续"
        )


def collect_department_ids(tree_response: object) -> list[str]:
    """兼容 data 包装、单根节点和根节点数组，递归收集部门 ID。"""
    tree = (
        tree_response.get("data", tree_response)
        if isinstance(tree_response, dict)
        else tree_response
    )
    nodes = tree if isinstance(tree, list) else [tree] if isinstance(tree, dict) else []
    result: list[str] = []

    def collect(items: list[object]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            value = item.get("id")
            if value is not None and str(value):
                result.append(str(value))
            children = item.get("children")
            if isinstance(children, list):
                collect(children)

    collect(nodes)
    return list(dict.fromkeys(result))


def expand_department_ids(
    tree_response: object, requested_ids: Sequence[str]
) -> list[str]:
    """Expand each requested department to itself plus every descendant.

    Input root order and tree preorder are preserved.  Unknown ids fail
    closed instead of silently returning only whichever departments happened
    to match.
    """
    tree = (
        tree_response.get("data", tree_response)
        if isinstance(tree_response, dict)
        else tree_response
    )
    roots = tree if isinstance(tree, list) else [tree] if isinstance(tree, dict) else []
    children_by_id: dict[str, list[str]] = {}

    def index_nodes(items: list[object], ancestors: frozenset[str]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            if raw_id is None or not str(raw_id):
                continue
            department_id = str(raw_id)
            if department_id in ancestors:
                raise MembersQueryError(
                    f"部门树存在循环引用：{department_id}"
                )
            raw_children = item.get("children")
            child_nodes = raw_children if isinstance(raw_children, list) else []
            child_ids = [
                str(child.get("id"))
                for child in child_nodes
                if isinstance(child, dict)
                and child.get("id") is not None
                and str(child.get("id"))
            ]
            previous = children_by_id.get(department_id)
            if previous is not None and previous != child_ids:
                raise MembersQueryError(
                    f"部门树 ID 重复且子节点冲突：{department_id}"
                )
            children_by_id[department_id] = child_ids
            index_nodes(child_nodes, ancestors | {department_id})

    index_nodes(roots, frozenset())
    requested = list(dict.fromkeys(str(value) for value in requested_ids))
    missing = [value for value in requested if value not in children_by_id]
    if missing:
        raise MembersQueryError(
            "departmentIds 中的部门不在当前可见组织树："
            + "、".join(missing)
        )

    expanded: list[str] = []
    seen: set[str] = set()

    def append_subtree(department_id: str) -> None:
        if department_id in seen:
            return
        seen.add(department_id)
        expanded.append(department_id)
        for child_id in children_by_id.get(department_id, []):
            append_subtree(child_id)

    for department_id in requested:
        append_subtree(department_id)
    return expanded


def _default_cache_file(domain: str, access_key: str) -> Path:
    # 同一台机器可能切换 CRM 实例或账号；缓存必须按可见范围隔离，否则会拿旧部门 ID 查错。
    scope = hashlib.sha256(
        f"{domain.rstrip('/')}\0{access_key}".encode("utf-8")
    ).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"cordys_dept_ids_{scope}.json"


def _read_cached_ids(cache_file: Path, now: float) -> list[str] | None:
    try:
        if now - cache_file.stat().st_mtime >= CACHE_TTL_SECONDS:
            return None
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if isinstance(cached, list) and cached:
            return [str(value) for value in cached if value is not None and str(value)]
    except (OSError, ValueError, TypeError):
        return None
    return None


def _write_cached_ids(cache_file: Path, department_ids: list[str]) -> None:
    temporary = cache_file.with_name(f"{cache_file.name}.{os.getpid()}.tmp")
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(department_ids, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(temporary, cache_file)
    except OSError:
        # 缓存不可写不应阻断本次已经拿到部门范围的查询。
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def make_http_transport(
    domain: str, access_key: str, secret_key: str, timeout: int = 20
) -> Transport:
    """创建无系统代理、无自动重试的 urllib transport。"""
    if not domain or not access_key or not secret_key:
        raise MembersQueryError("未设置 CORDYS_CRM_DOMAIN/ACCESS_KEY/SECRET_KEY")
    opener = request.build_opener(request.ProxyHandler({}))
    root = domain.rstrip("/")

    def call(method: str, path: str, body: Optional[dict] = None) -> str:
        data = (
            json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None
            else None
        )
        req = request.Request(
            root + path,
            data=data,
            method=method,
            headers={
                "X-Access-Key": access_key,
                "X-Secret-Key": secret_key,
                "X-Request-Source": "SKILL",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with opener.open(req, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            raise MembersResponseError(f"请求失败: HTTP {exc.code}", detail) from exc
        except URLError as exc:
            raise MembersQueryError(f"请求失败: {exc}") from exc

    return call


def compact_members_response(document: object) -> str:
    validate_members_document(document)
    data = document["data"]
    members = data.get("list")
    compact_list = [
        {
            "userName": member.get("userName"),
            "userId": member.get("userId"),
            "departmentId": member.get("departmentId"),
            "departmentName": member.get("departmentName"),
            "enable": member.get("enable"),
        }
        for member in members
        if isinstance(member, dict)
    ]
    result = {
        "code": document.get("code"),
        "data": {"list": compact_list, "total": data.get("total", len(compact_list))},
    }
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def redact_sensitive(text: str, secrets: Sequence[str]) -> str:
    """在任何错误体进入 stdout 前去除当前请求凭证。"""
    safe = text
    for secret in secrets:
        if secret:
            safe = safe.replace(secret, "***REDACTED***")
    return safe


def query_members(
    payload: str = "",
    name: str = "",
    compact: bool = False,
    active: bool = False,
    exact_departments: bool = False,
    *,
    domain: str = "",
    access_key: str = "",
    secret_key: str = "",
    cache_file: Optional[Path] = None,
    now: Optional[float] = None,
    transport: Optional[Transport] = None,
) -> str:
    """执行至多一次部门树请求和恰好一次 /user/list 请求，不做自动重试。"""
    body = build_members_payload(payload, name, active)
    department_ids = body.get("departmentIds")
    if exact_departments and not (
        isinstance(department_ids, list) and department_ids
    ):
        raise MembersQueryError(
            "--exact-departments 只能与显式 departmentIds 数组一起使用"
        )
    call = transport or make_http_transport(domain, access_key, secret_key)
    if isinstance(department_ids, list) and department_ids:
        if not exact_departments:
            tree_raw = call("GET", "/department/tree", None)
            tree_document = _require_success(
                tree_raw, "部门树查询", code_required=False
            )
            body["departmentIds"] = expand_department_ids(
                tree_document, department_ids
            )
    else:
        cache_path = cache_file or _default_cache_file(domain, access_key)
        ids = _read_cached_ids(cache_path, time.time() if now is None else now)
        if not ids:
            tree_raw = call("GET", "/department/tree", None)
            tree_document = _require_success(
                tree_raw, "部门树查询", code_required=False
            )
            ids = collect_department_ids(tree_document)
            if not ids:
                raise MembersQueryError(
                    "部门树未返回任何部门 ID，禁止发起无范围成员查询"
                )
            _write_cached_ids(cache_path, ids)
        body["departmentIds"] = ids

    raw_response = call("POST", "/user/list", body)
    document = _require_success(raw_response, "成员查询", code_required=True)
    validate_members_document(document)
    if active:
        validate_active_members(document)
    return compact_members_response(document) if compact else raw_response


def main(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    # cordys.sh 通过环境变量传参，直接调用 helper；独立/备用入口才从 argv 解析。
    use_environment = os.environ.get("CORDYS_MEMBERS_FROM_ENV", "") == "1"
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if use_environment:
            payload = os.environ.get("CORDYS_MEMBERS_PAYLOAD", "")
            name = os.environ.get("CORDYS_FILTER_NAME", "")
            compact = os.environ.get("CORDYS_MEMBERS_COMPACT", "") == "1"
            active = os.environ.get("CORDYS_MEMBERS_ACTIVE", "") == "1"
        else:
            payload, name, compact, active, exact_departments = (
                parse_members_cli_args(args)
            )
        if use_environment:
            exact_departments = (
                os.environ.get("CORDYS_MEMBERS_EXACT_DEPARTMENTS", "") == "1"
            )
        output = query_members(
            payload,
            name,
            compact,
            active,
            exact_departments,
            domain=os.environ.get("CORDYS_CRM_DOMAIN", ""),
            access_key=os.environ.get("CORDYS_ACCESS_KEY", ""),
            secret_key=os.environ.get("CORDYS_SECRET_KEY", ""),
        )
    except MembersResponseError as exc:
        if exc.response:
            safe_response = redact_sensitive(
                exc.response,
                (
                    os.environ.get("CORDYS_ACCESS_KEY", ""),
                    os.environ.get("CORDYS_SECRET_KEY", ""),
                ),
            )
            sys.stdout.write(safe_response)
            if not safe_response.endswith("\n"):
                sys.stdout.write("\n")
        sys.stderr.write(f"成员查询失败: {exc}\n")
        return 1
    except MembersQueryError as exc:
        sys.stderr.write(f"成员查询失败: {exc}\n")
        return 1
    sys.stdout.write(output)
    if not output.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
