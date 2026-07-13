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


class MembersQueryError(RuntimeError):
    """成员查询无法安全继续。"""


class MembersResponseError(MembersQueryError):
    """后端返回 HTTP 或业务错误，并保留原始响应作为诊断证据。"""

    def __init__(self, message: str, response: str = "") -> None:
        super().__init__(message)
        self.response = response


def parse_members_cli_args(args: Sequence[str]) -> tuple[str, str, bool]:
    """解析公开 CLI 参数，兼容 JSON 在 flags 前后出现。"""
    payload = ""
    name = ""
    compact = False
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
        if token.startswith("--"):
            raise MembersQueryError(f"未知 members 参数: {token}")
        if payload_seen:
            raise MembersQueryError("members 只接受一个 JSON/关键词参数")
        payload = token
        payload_seen = True
        index += 1
    return payload, name, compact


def build_members_payload(raw: str = "", name: str = "") -> dict:
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
    *,
    domain: str = "",
    access_key: str = "",
    secret_key: str = "",
    cache_file: Optional[Path] = None,
    now: Optional[float] = None,
    transport: Optional[Transport] = None,
) -> str:
    """执行至多一次部门树请求和恰好一次 /user/list 请求，不做自动重试。"""
    body = build_members_payload(payload, name)
    call = transport or make_http_transport(domain, access_key, secret_key)
    department_ids = body.get("departmentIds")
    if not isinstance(department_ids, list) or not department_ids:
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
        else:
            payload, name, compact = parse_members_cli_args(args)
        output = query_members(
            payload,
            name,
            compact,
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
