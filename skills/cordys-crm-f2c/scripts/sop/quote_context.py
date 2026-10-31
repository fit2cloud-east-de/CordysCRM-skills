#!/usr/bin/env python3
"""One read-only call that returns the Cordys context a quotation needs.

``cordys.sh crm quote-context '{"customer":"…","contact":"…","phone":"…"}'``
replaces the five to eight separate ``search`` / ``acct-sub`` / ``contact`` /
``page`` calls otherwise needed before creating a quotation:

* candidate customers matched by name, plus customers of opportunities whose
  name matched;
* for at most ``MAX_CUSTOMERS`` customers: their opportunities (amount,
  product *names*, closed flag), their contacts and same-name business titles;
* contact and lead candidates for completing a missing contact or phone.

Data scope comes from the current CRM role (``core/role-engine.md`` §2.4):
the identity cache ``Cordys.md`` when it is valid, otherwise ``whoami`` plus
the same role rules (``match_role``).  Nothing is written, and the output is
normalized: no ``optionMap``/``moduleFields``, no credentials.
"""

from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib import request
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from org_tree import OrgTreeError, collect_descendant_ids  # noqa: E402


SUCCESS_CODE = 100200
MAX_CUSTOMERS = 5
CLOSED_STAGES = {"SUCCESS", "FAIL"}
# Fallback labels when a record carries neither stageName nor an optionMap label.
STAGE_LABELS = {"CREATE": "新建", "SUCCESS": "赢单", "FAIL": "输单"}
ROLES = ("sales", "sales-manager", "finance", "executive", "contract-admin")
VIEW_IDS = ("SELF", "ALL", "DEPARTMENT")
INPUT_KEYS = ("customer", "contact", "phone", "viewId")
IDENTITY_MAX_AGE = timedelta(days=7)
BEIJING = timezone(timedelta(hours=8))
REQUEST_TIMEOUT = 15
MAX_WORKERS = 16
PRODUCT_PAGE_SIZE = 500
SKILL_DIR = Path(__file__).resolve().parents[2]

Transport = Callable[[str, str, "dict[str, Any] | None"], "dict[str, Any]"]


class QuoteContextError(RuntimeError):
    """A failure that ends the command; ``category`` goes into ``errorCategory``."""

    def __init__(self, category: str, message: str):
        self.category = category
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------- helpers

def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _key(value: Any) -> str:
    return re.sub(r"\s+", "", _text(value)).casefold()


def name_match(name: Any, query: Any) -> str:
    """``exact``, ``contains`` (either name contains the other) or ``none``."""
    left, right = _key(name), _key(query)
    if not left or not right:
        return "none"
    if left == right:
        return "exact"
    if left in right or right in left:
        return "contains"
    return "none"


def _redact(text: Any, secrets: Iterable[str]) -> str:
    value = _text(text)
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value


def _rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    data = response.get("data")
    if isinstance(data, dict):
        data = data.get("list")
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _option_names(response: dict[str, Any]) -> dict[str, str]:
    """Collect id → name from every optionMap list in a page response."""
    names: dict[str, str] = {}
    data = response.get("data")
    maps = [response.get("optionMap")]
    if isinstance(data, dict):
        maps.append(data.get("optionMap"))
    for option_map in maps:
        if not isinstance(option_map, dict):
            continue
        for options in option_map.values():
            if not isinstance(options, list):
                continue
            for option in options:
                if not isinstance(option, dict):
                    continue
                option_id = _text(option.get("id", option.get("value")))
                label = _text(option.get("name", option.get("label")))
                if option_id and label:
                    names.setdefault(option_id, label)
    return names


def _number(value: Any) -> int | float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _now() -> datetime:
    return datetime.now(BEIJING)


# ---------------------------------------------------------------- transport

def make_transport(domain: str, access_key: str, secret_key: str) -> Transport:
    """urllib transport without system proxies or retries; returns parsed success bodies."""
    domain = (domain or "").rstrip("/")
    if not domain.startswith("https://"):
        raise QuoteContextError("auth_failed", "未设置合法的 CORDYS_CRM_DOMAIN（必须是 HTTPS 根地址）")
    if not access_key:
        raise QuoteContextError("auth_failed", "未设置 CORDYS_ACCESS_KEY")
    if not secret_key:
        raise QuoteContextError("auth_failed", "未设置 CORDYS_SECRET_KEY")
    opener = request.build_opener(request.ProxyHandler({}))
    secrets = (access_key, secret_key)

    def call(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        req = request.Request(
            f"{domain}/{path.lstrip('/')}",
            data=None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method=method,
            headers={
                "X-Access-Key": access_key,
                "X-Secret-Key": secret_key,
                "X-Request-Source": "SKILL",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with opener.open(req, timeout=REQUEST_TIMEOUT) as response:
                raw = response.read().decode("utf-8-sig", errors="replace")
        except HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8-sig", errors="replace")
            except OSError:
                raw = ""
            if not raw.strip().startswith("{"):
                category = "auth_failed" if exc.code in (401, 403) else "request_failed"
                raise QuoteContextError(category, f"HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise QuoteContextError("request_failed", f"网络或超时：{_redact(exc, secrets)}") from None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise QuoteContextError("request_failed", "响应不是合法 JSON") from None
        if not isinstance(value, dict):
            raise QuoteContextError("request_failed", "响应不是 JSON 对象")
        if str(value.get("code")) != str(SUCCESS_CODE):
            detail = value.get("message") or value.get("msg") or f"code={value.get('code')}"
            raise QuoteContextError("request_failed", _redact(detail, secrets))
        return value

    return call


# ---------------------------------------------------------------- identity and scope

def match_role(info: dict[str, Any], role_map_raw: str = "") -> str:
    """Role rules of core/role-engine.md §2.1–2.3; keep both in step when either changes."""
    position = _text(info.get("position"))
    custom: dict[str, str] = {}
    for entry in (role_map_raw or "").split(","):
        if "=" not in entry:
            continue
        keywords, role_id = entry.strip().rsplit("=", 1)
        role_id = role_id.strip()
        if role_id not in ROLES:
            continue
        for keyword in keywords.split("|"):
            if keyword.strip():
                custom[keyword.strip()] = role_id
    for keyword in sorted(custom, key=len, reverse=True):
        if keyword in position:
            return custom[keyword]

    def has(*keywords: str) -> bool:
        return any(keyword in position for keyword in keywords)

    if _text(info.get("id")) == "admin" or "admin" in _text(info.get("roles")):
        return "sales-manager"
    if has("总经理", "副总裁", "VP", "CEO", "COO", "CFO", "总裁", "合伙人", "董事长"):
        return "executive"
    if has("财务", "会计", "出纳"):
        return "finance"
    if has("商务", "合同管理", "合同专员", "法务", "合规"):
        return "contract-admin"
    if has("客户经理", "大客户经理"):
        return "sales"
    if has("经理", "总监", "主管", "负责人", "leader", "部长", "主任"):
        return "sales-manager"
    return "sales"


_FETCHED = re.compile(r"自动获取[:：]\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})")
_PLACEHOLDER = re.compile(r"^[（(].*[）)]$")


def read_identity_cache(path: Path, now: datetime) -> dict[str, Any] | None:
    """Parse Cordys.md (core/role-engine.md §3); None when missing, malformed or older than 7 days."""
    try:
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    fetched = _FETCHED.search(content)
    if not fetched:
        return None
    fetched_at = datetime.strptime(fetched.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING)
    if now - fetched_at > IDENTITY_MAX_AGE or fetched_at - now > timedelta(days=1):
        return None
    cells: dict[str, str] = {}
    for line in content.splitlines():
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) == 2 and parts[0] and not set(parts[0]) <= {"-", ":"}:
            value = "" if _PLACEHOLDER.match(parts[1]) else parts[1]
            cells.setdefault(parts[0], value)

    def cell(prefix: str) -> str:
        return next((value for label, value in cells.items() if label.startswith(prefix)), "")

    user_id, role = cell("用户ID"), cell("角色ID")
    if not user_id or role not in ROLES:
        return None
    department_ids = None
    section = content.split("## 部门范围", 1)
    if len(section) == 2:
        for line in section[1].splitlines():
            if line.strip().startswith("["):
                try:
                    parsed = json.loads(line.strip())
                except json.JSONDecodeError:
                    break
                if isinstance(parsed, list) and parsed and all(isinstance(i, str) and i for i in parsed):
                    department_ids = parsed
                break
    return {
        "user_id": user_id,
        "role": role,
        "department_id": cell("部门ID"),
        "department_ids": department_ids,
        "source": "cache",
    }


def whoami_identity(transport: Transport, role_map_raw: str) -> dict[str, Any]:
    try:
        info = transport("GET", "/personal/center/info", None).get("data")
    except QuoteContextError as exc:
        raise QuoteContextError("identity_failed", f"获取当前用户身份失败：{exc.message}") from None
    # 内置 admin 账号的 userId 为空，用户 ID 就是 id（core/role-engine.md §3 示例）。
    user_id = _text(info.get("userId")) or _text(info.get("id")) if isinstance(info, dict) else ""
    if not user_id:
        raise QuoteContextError("identity_failed", "获取当前用户身份失败：响应缺少 userId")
    return {
        "user_id": user_id,
        "role": match_role(info, role_map_raw),
        "department_id": _text(info.get("departmentId")),
        "department_ids": None,
        "source": "whoami",
    }


def department_scope(transport: Transport, department_id: str) -> list[str]:
    """Own department plus all descendants."""
    try:
        tree = transport("GET", "/department/tree", None)
        ids = collect_descendant_ids(tree, department_id)
    except QuoteContextError as exc:
        raise QuoteContextError("identity_failed", f"展开部门范围失败：{exc.message}") from None
    except OrgTreeError as exc:
        raise QuoteContextError("identity_failed", f"展开部门范围失败：{exc}") from None
    if not ids:
        raise QuoteContextError("identity_failed", "展开部门范围失败：部门范围为空")
    return ids


class Scope:
    """Role-based scope for lead/account/opportunity/contact queries."""

    def __init__(self, identity: dict[str, Any], view_id: str, department_ids: list[str] | None, note: str):
        self.role = identity["role"]
        self.user_id = identity["user_id"]
        self.source = identity["source"]
        self.view_id = view_id
        self.department_ids = department_ids
        self.note = note

    def conditions(self) -> list[dict[str, Any]]:
        if not self.department_ids:
            return []
        return [{
            "value": list(self.department_ids), "operator": "IN", "name": "departmentId",
            "multipleValue": False, "type": "TREE_SELECT",
        }]

    def allows(self, row: dict[str, Any]) -> bool:
        """Local guard so a backend that ignores viewId cannot widen the scope."""
        if self.view_id == "SELF":
            owner = _text(row.get("owner"))
            return not owner or owner == self.user_id
        if self.department_ids:
            department = _text(row.get("departmentId"))
            return not department or department in self.department_ids
        return True

    def describe(self) -> dict[str, Any]:
        value: dict[str, Any] = {"role": self.role, "viewId": self.view_id, "source": self.source}
        if self.department_ids:
            value["department_count"] = len(self.department_ids)
        if self.note:
            value["note"] = self.note
        return value


def resolve_scope(
    transport: Transport, requested_view: str, *, cache_path: Path, role_map_raw: str, now: datetime,
) -> Scope:
    identity = read_identity_cache(cache_path, now) or whoami_identity(transport, role_map_raw)
    role = identity["role"]
    requested = requested_view.upper()
    note = ""
    if role == "sales":
        if requested and requested != "SELF":
            note = "销售角色只能查询本人名下的数据，已按 SELF 查询"
        return Scope(identity, "SELF", None, note)
    if requested == "SELF":
        return Scope(identity, "SELF", None, note)
    wants_department = requested == "DEPARTMENT" or (not requested and role == "sales-manager")
    if not wants_department:
        return Scope(identity, "ALL", None, note)
    department_ids = identity["department_ids"]
    if not department_ids:
        if not identity["department_id"]:
            # 无所属部门的账号（如内置 admin）名下记录的 departmentId 也为空，部门条件会把它们全部排除。
            return Scope(identity, "ALL", None, "当前账号没有所属部门，未加部门条件，按全部可见数据查询")
        department_ids = department_scope(transport, identity["department_id"])
    return Scope(identity, "ALL", department_ids, note)


# ---------------------------------------------------------------- queries

def _page_body(keyword: str, view_id: str, page_size: int, conditions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "current": 1,
        "pageSize": page_size,
        "sort": {},
        "combineSearch": {"searchMode": "AND", "conditions": conditions},
        "keyword": keyword,
        "viewId": view_id,
        "filters": [],
    }


def _scoped_body(keyword: str, scope: Scope, page_size: int) -> dict[str, Any]:
    return _page_body(keyword, scope.view_id, page_size, scope.conditions())


def _run_parallel(jobs: dict[str, Callable[[], Any]]) -> dict[str, Any]:
    """Run jobs concurrently; each value is the job result or the QuoteContextError it raised."""
    if not jobs:
        return {}
    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(jobs))) as pool:
        futures = {name: pool.submit(job) for name, job in jobs.items()}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except QuoteContextError as exc:
                results[name] = exc
    return results


def _fetch_product_names(transport: Transport) -> dict[str, str]:
    names: dict[str, str] = {}
    current = 1
    while True:
        body = _page_body("", "ALL", PRODUCT_PAGE_SIZE, [])
        body["current"] = current
        response = transport("POST", "/field/source/product", body)
        rows = _rows(response)
        for row in rows:
            if _text(row.get("id")) and _text(row.get("name")):
                names.setdefault(_text(row.get("id")), _text(row.get("name")))
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        total = _number(data.get("total")) or 0
        if not rows or current * PRODUCT_PAGE_SIZE >= total:
            return names
        current += 1


def _opportunity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge one opportunity's rows; rows from the customer sub-list come first (they carry amount)."""
    def first(*keys: str) -> str:
        for row in rows:
            for key in keys:
                if _text(row.get(key)):
                    return _text(row.get(key))
        return ""

    amount = next((_number(row.get("amount")) for row in rows if _number(row.get("amount")) is not None), None)
    products: list[str] = []
    for row in rows:
        values = row.get("products")
        if isinstance(values, list) and any(_text(value) for value in values):
            products = [_text(value) for value in values if _text(value)]
            break
    stage = first("stage")
    return {
        "id": first("id"),
        "name": first("name"),
        "stage": stage,
        "stage_name": first("stageName"),
        "closed": stage in CLOSED_STAGES,
        "amount": amount,
        "owner_name": first("ownerName"),
        "products": products,
        "contact_id": first("contactId"),
        "contact_name": first("contactName"),
    }


def build_context(
    query: dict[str, str],
    transport: Transport,
    *,
    cache_path: Path = SKILL_DIR / "Cordys.md",
    role_map_raw: str = "",
    now: Callable[[], datetime] = _now,
) -> dict[str, Any]:
    customer, contact, phone = query["customer"], query["contact"], query["phone"]
    scope = resolve_scope(transport, query["viewId"], cache_path=cache_path, role_map_raw=role_map_raw, now=now())
    errors: list[dict[str, Any]] = []
    option_names: dict[str, str] = {}

    def scoped(path: str, keyword: str, page_size: int) -> Callable[[], dict[str, Any]]:
        return lambda: transport("POST", path, _scoped_body(keyword, scope, page_size))

    first_round = {
        "accounts": scoped("/global/search/account", customer, 50),
        "opportunities": scoped("/global/search/opportunity", customer, 100),
        "leads": scoped("/global/search/lead", customer, 20),
    }
    if contact or phone:
        first_round["contact_matches"] = scoped("/account/contact/page", contact or phone, 20)
    found = _run_parallel(first_round)
    for part, label in (("accounts", "客户"), ("opportunities", "商机")):
        if isinstance(found[part], QuoteContextError):
            raise QuoteContextError("search_failed", f"按“{customer}”搜索{label}失败：{found[part].message}")
        option_names.update(_option_names(found[part]))

    account_rows = [row for row in _rows(found["accounts"]) if scope.allows(row)]
    searched_opportunities = [row for row in _rows(found["opportunities"]) if scope.allows(row)]
    candidates: dict[str, dict[str, Any]] = {}
    for row in account_rows:
        customer_id = _text(row.get("id"))
        if customer_id and customer_id not in candidates:
            candidates[customer_id] = {
                "id": customer_id, "name": _text(row.get("name")), "owner_name": _text(row.get("ownerName")),
            }
    for row in searched_opportunities:
        customer_id = _text(row.get("customerId"))
        if customer_id and customer_id not in candidates:
            candidates[customer_id] = {"id": customer_id, "name": _text(row.get("customerName")), "owner_name": ""}
    order = {"exact": 0, "contains": 1, "none": 2}
    customers = sorted(
        ({**item, "name_match": name_match(item["name"], customer)} for item in candidates.values()),
        key=lambda item: order[item["name_match"]],
    )
    truncated = len(customers) > MAX_CUSTOMERS

    if not truncated and customers:
        title_names = list(dict.fromkeys(item["name"] for item in customers if item["name"]))
        second_round: dict[str, Callable[[], Any]] = {}
        for item in customers:
            customer_id = item["id"]
            body = _scoped_body("", scope, 100)
            body["customerId"] = customer_id
            second_round[f"opportunities:{customer_id}"] = (
                lambda body=body: transport("POST", "/account/opportunity/page", body))
            second_round[f"contacts:{customer_id}"] = (
                lambda customer_id=customer_id: transport("GET", f"/account/contact/list/{customer_id}", None))
        for name in title_names:
            # Business titles are shared master data, not a role-limited module: query them company-wide.
            second_round[f"titles:{name}"] = (
                lambda name=name: transport("POST", "/contract/business-title/page", _page_body(name, "ALL", 20, [])))
        details = _run_parallel(second_round)

        for item in customers:
            customer_id = item["id"]
            sub = details[f"opportunities:{customer_id}"]
            sub_rows: list[dict[str, Any]] = []
            if isinstance(sub, QuoteContextError):
                errors.append({"part": "opportunities", "customer_id": customer_id, "message": sub.message})
            else:
                option_names.update(_option_names(sub))
                sub_rows = [row for row in _rows(sub) if scope.allows(row)]
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in sub_rows + [r for r in searched_opportunities if _text(r.get("customerId")) == customer_id]:
                if _text(row.get("id")):
                    grouped.setdefault(_text(row.get("id")), []).append(row)
            opportunities = [_opportunity(rows) for rows in grouped.values()]
            item["opportunities"] = sorted(opportunities, key=lambda opp: opp["closed"])

            contacts = details[f"contacts:{customer_id}"]
            if isinstance(contacts, QuoteContextError):
                errors.append({"part": "contacts", "customer_id": customer_id, "message": contacts.message})
                item["contacts"] = []
            else:
                item["contacts"] = [
                    {"id": _text(row.get("id")), "name": _text(row.get("name")), "phone": _text(row.get("phone"))}
                    for row in _rows(contacts) if _text(row.get("id"))
                ]

            titles = details.get(f"titles:{item['name']}")
            if isinstance(titles, QuoteContextError):
                errors.append({"part": "business_titles", "customer_id": customer_id, "message": titles.message})
                item["business_titles"] = []
            else:
                matched = []
                for row in _rows(titles or {}):
                    match = name_match(row.get("name"), item["name"])
                    if _text(row.get("id")) and match != "none":
                        matched.append({
                            "id": _text(row.get("id")), "name": _text(row.get("name")),
                            "approval_status": _text(row.get("approvalStatus")), "name_match": match,
                        })
                item["business_titles"] = sorted(matched, key=lambda title: title["name_match"] != "exact")

        _name_products(customers, option_names, transport, errors)
    elif truncated:
        customers = [
            {key: item[key] for key in ("id", "name", "owner_name", "name_match")} for item in customers
        ]

    result: dict[str, Any] = {
        "query": {"customer": customer, "contact": contact, "phone": phone},
        "scope": scope.describe(),
        "truncated": truncated,
        "customers": customers,
    }
    if contact or phone:
        matches = found["contact_matches"]
        if isinstance(matches, QuoteContextError):
            errors.append({"part": "contact_matches", "message": matches.message})
            result["contact_matches"] = []
        else:
            result["contact_matches"] = [
                {
                    "id": _text(row.get("id")), "name": _text(row.get("name")), "phone": _text(row.get("phone")),
                    "customer_id": _text(row.get("customerId")), "customer_name": _text(row.get("customerName")),
                }
                for row in _rows(matches)
                if _text(row.get("id")) and scope.allows(row)
                and name_match(row.get("customerName"), customer) != "none"
            ]
    leads = found["leads"]
    if isinstance(leads, QuoteContextError):
        errors.append({"part": "leads", "message": leads.message})
        result["leads"] = []
    else:
        result["leads"] = [
            {"id": _text(row.get("id")), "name": _text(row.get("name")),
             "contact": _text(row.get("contact")), "phone": _text(row.get("phone"))}
            for row in _rows(leads)
            if _text(row.get("id")) and scope.allows(row) and name_match(row.get("name"), customer) != "none"
        ]
    result["errors"] = errors
    result["queried_at"] = now().isoformat(timespec="seconds")
    return {"code": SUCCESS_CODE, "data": result}


def _name_products(
    customers: list[dict[str, Any]], option_names: dict[str, str], transport: Transport, errors: list[dict[str, Any]],
) -> None:
    """Replace product IDs with names; IDs that cannot be named are dropped and reported."""
    opportunities = [opp for item in customers for opp in item.get("opportunities", [])]
    unknown = {value for opp in opportunities for value in opp["products"]
               if value not in option_names and value.isdigit()}
    names = dict(option_names)
    if unknown:
        try:
            names.update(_fetch_product_names(transport))
        except QuoteContextError as exc:
            errors.append({"part": "products", "message": f"读取产品名称失败：{exc.message}"})
    unnamed: list[str] = []
    for opp in opportunities:
        named = []
        for value in opp["products"]:
            if value in names:
                named.append(names[value])
            elif value.isdigit():
                unnamed.append(opp["id"])
            else:
                named.append(value)
        opp["products"] = list(dict.fromkeys(named))
        if not opp["stage_name"]:
            opp["stage_name"] = names.get(opp["stage"]) or STAGE_LABELS.get(opp["stage"], opp["stage"])
    if unnamed and not any(error["part"] == "products" for error in errors):
        errors.append({
            "part": "products",
            "message": "以下商机有产品无法转换为名称，已从 products 中省略：" + "、".join(dict.fromkeys(unnamed)),
        })


# ---------------------------------------------------------------- CLI

def parse_query(raw: str) -> dict[str, str]:
    try:
        value = json.loads((raw or "").lstrip("﻿"))
    except json.JSONDecodeError as exc:
        raise QuoteContextError("invalid_request", f"参数不是合法 JSON：{exc}") from None
    if not isinstance(value, dict):
        raise QuoteContextError("invalid_request", "参数必须是 JSON 对象")
    unknown = [key for key in value if key not in INPUT_KEYS]
    if unknown:
        raise QuoteContextError(
            "invalid_request", f"不支持的参数：{'、'.join(unknown)}；只接受 {'、'.join(INPUT_KEYS)}")
    query: dict[str, str] = {}
    for key in INPUT_KEYS:
        item = value.get(key, "")
        if item is None:
            item = ""
        if not isinstance(item, str):
            raise QuoteContextError("invalid_request", f"{key} 必须是字符串")
        query[key] = item.strip()
    if not query["customer"]:
        raise QuoteContextError("invalid_request", "customer（客户名称）必填")
    if query["viewId"] and query["viewId"].upper() not in VIEW_IDS:
        raise QuoteContextError("invalid_request", f"viewId 只接受 {'、'.join(VIEW_IDS)}")
    return query


def execute(raw: str, *, domain: str, access_key: str, secret_key: str, role_map_raw: str = "") -> tuple[dict[str, Any], int]:
    """Run the command; returns the JSON document for stdout and the exit status."""
    try:
        query = parse_query(raw)
        transport = make_transport(domain, access_key, secret_key)
        return build_context(query, transport, role_map_raw=role_map_raw), 0
    except QuoteContextError as exc:
        message = _redact(exc.message, (access_key, secret_key))
        return {"code": 0, "errorCategory": exc.category, "message": message}, 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(json.dumps({"code": 0, "errorCategory": "invalid_request",
                          "message": "用法: quote_context.py '<JSON>'（- 从 stdin 读取）"}, ensure_ascii=False))
        return 1
    raw = sys.stdin.read() if args[0] in ("-", "@-") else args[0]
    document, status = execute(
        raw,
        domain=os.environ.get("CORDYS_CRM_DOMAIN", ""),
        access_key=os.environ.get("CORDYS_ACCESS_KEY", ""),
        secret_key=os.environ.get("CORDYS_SECRET_KEY", ""),
        role_map_raw=os.environ.get("ROLE_MAP", ""),
    )
    print(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    if status:
        print(f"错误: {document['message']}", file=sys.stderr)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
