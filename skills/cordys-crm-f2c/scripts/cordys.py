#!/usr/bin/env python3
"""
CORDYS CRM CLI 工具
使用 X-Access-Key / X-Secret-Key 进行鉴权
"""

import os
import sys
import json
import re
import time
from pathlib import Path
from typing import Dict, Any
from urllib import parse, request
from urllib.error import HTTPError, URLError

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

try:
    from dotenv import load_dotenv
except ImportError:
    # 如果没有 python-dotenv，提供简单的 .env 加载实现
    def load_dotenv(dotenv_path=None):
        if dotenv_path and os.path.exists(dotenv_path):
            with open(dotenv_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip().strip(
                            '"').strip("'")


# ── 路径配置 ──────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ENV_FILE = SKILL_DIR / ".env"
FIELD_SCHEMA = SKILL_DIR / "references" / "field-schema.json"
sys.path.insert(0, str(SCRIPT_DIR / "sop"))
from query_contract import (  # noqa: E402
    QueryContractError,
    validate_payload,
    validate_pool_query_scope,
    validate_query_semantics,
)
from payload_io import (  # noqa: E402
    FOLLOW_SOURCE_FIELDS,
    PayloadTransportError,
    extract_form_config,
    module_has_subforms,
    normalize_follow,
    order_contract_id,
    order_split_enabled,
    prepare_create_payload,
    read_utf8,
)
from order_batch import OrderBatchError, execute_order_batch  # noqa: E402
from time_boundary import (  # noqa: E402
    TimeBoundaryError,
    date_range,
    timestamp_value,
)
from members_query import (  # noqa: E402
    MembersQueryError,
    MembersResponseError,
    parse_members_cli_args,
    query_members,
    redact_sensitive,
)
from org_tree import (  # noqa: E402
    OrgTreeError,
    render_department_outline,
    render_descendant_ids,
)

# 加载环境变量
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

CORDYS_CRM_DOMAIN = os.environ.get("CORDYS_CRM_DOMAIN", "").rstrip("/")
CORDYS_ACCESS_KEY = os.environ.get("CORDYS_ACCESS_KEY", "")
CORDYS_SECRET_KEY = os.environ.get("CORDYS_SECRET_KEY", "")

# 签约后（L2C）家族通常无全局搜索、且按父 id 取数；报价单 search 单独复用 page。
# page 仅在出现 customerId/accountId 条件时拦（contractId 条件合法，放行）。
POST_SIGNING_MODULES = {
    "contract", "invoice", "order",
    "contract/payment-record", "contract/payment-plan",
    "contract/business-title", "opportunity/quotation",
}
WRITE_MODULES = (
    "lead", "account", "opportunity", "contact", "account/contact",
    "lead/follow/record", "lead/follow/plan",
    "account/follow/record", "account/follow/plan",
    "opportunity/follow/record", "opportunity/follow/plan",
    "contract", "contract/payment-plan", "contract/payment-record",
    "invoice", "contract/business-title", "opportunity/quotation", "order",
)
BATCH_UPDATE_MODULES = (
    "lead", "account", "opportunity", "contact", "account/contact",
    "contract", "order",
)
SYNC_INTERVAL = 21600


# ── 辅助函数 ───────────────────────────────────────────────────────────
def die(message: str) -> None:
    """打印错误信息并退出"""
    print(f"错误: {message}", file=sys.stderr)
    sys.exit(1)


def read_payload_marker(value: str) -> str:
    """Resolve ``-``/``@-`` from UTF-8 stdin without using argv for JSON."""
    if value not in ("-", "@-"):
        return value
    try:
        return read_utf8()
    except PayloadTransportError as exc:
        die(str(exc))
    return ""  # die() always exits; keeps type checkers satisfied.


def info(message: str) -> None:
    """打印信息"""
    print(f":: {message}", file=sys.stderr)


def check_keys() -> None:
    """检查 CRM 根地址和必需的 API 密钥"""
    global CORDYS_CRM_DOMAIN
    if not CORDYS_CRM_DOMAIN:
        die("未设置 CORDYS_CRM_DOMAIN")
    parsed = parse.urlparse(CORDYS_CRM_DOMAIN)
    try:
        port = parsed.port
    except ValueError:
        die("CORDYS_CRM_DOMAIN 端口必须在 1-65535 之间")
    hostname_valid = bool(
        parsed.hostname
        and re.fullmatch(
            r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)*"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?",
            parsed.hostname,
        )
    )
    if (
        parsed.scheme != "https"
        or not hostname_valid
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in CORDYS_CRM_DOMAIN)
        or port == 0
    ):
        die(
            "CORDYS_CRM_DOMAIN 必须是合法 HTTPS 根地址（如 https://crm.example.com），"
            "不能包含路径、查询参数或凭证"
        )
    CORDYS_CRM_DOMAIN = CORDYS_CRM_DOMAIN.rstrip("/")
    if not CORDYS_ACCESS_KEY:
        die("未设置 CORDYS_ACCESS_KEY")
    if not CORDYS_SECRET_KEY:
        die("未设置 CORDYS_SECRET_KEY")

def warn(message: str) -> None:
    """打印警告信息"""
    print(f"⚠️  警告: {message}", file=sys.stderr)

def validate_url(url: str) -> bool:
    """验证URL是否指向可信的Cordys CRM域名"""
    from urllib.parse import urlparse
    
    # 解析URL
    parsed = urlparse(url)
    if not parsed.netloc:
        return True  # 不是完整URL，可能是相对路径
    
    # 从配置的CORDYS_CRM_DOMAIN中提取可信域名
    trusted_parsed = urlparse(CORDYS_CRM_DOMAIN)
    trusted_domain = trusted_parsed.netloc or CORDYS_CRM_DOMAIN
    
    # 检查域名是否匹配（支持子域名）
    request_domain = parsed.netloc
    
    if request_domain != trusted_domain and not request_domain.endswith(f".{trusted_domain}"):
        warn(f"目标域名 '{request_domain}' 与配置的Cordys CRM域名 '{trusted_domain}' 不匹配")
        warn("这可能会泄露您的API凭证！")
        return False
    
    return True


def page_payload(keyword: str = "") -> Dict[str, Any]:
    """生成分页请求的标准 payload"""
    return {
        "current": 1,
        "pageSize": 30,
        "sort": {},
        "combineSearch": {
            "searchMode": "AND",
            "conditions": []
        },
        "keyword": keyword,
        "viewId": "ALL",
        "filters": []
    }


def crm_api_module(module: str) -> str:
    """Map the public contact alias to Cordys' nested API module."""
    return "account/contact" if module == "contact" else module


def ensure_local_snapshot(context: str = "操作") -> None:
    """按 6 小时 TTL 尝试刷新本地表单快照，失败时保留旧快照。"""
    stamp = SKILL_DIR / "references" / "forms" / ".last_sync"
    try:
        last_sync = int(stamp.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        last_sync = 0
    if int(time.time()) - last_sync < SYNC_INTERVAL:
        return
    check_keys()
    try:
        from sync_forms import apply_sync_output, sync_forms

        output = sync_forms(
            CORDYS_CRM_DOMAIN,
            CORDYS_ACCESS_KEY,
            CORDYS_SECRET_KEY,
        )
        summary = apply_sync_output(SKILL_DIR, output)
        if summary["retainedModules"]:
            warn(
                f"表单同步仅更新 {len(summary['updatedModules'])} 个模块；"
                f"其余 {len(summary['retainedModules'])} 个模块保留本地旧快照。"
            )
    except Exception as exc:
        warn(
            f"{context}前表单/视图同步异常，已保留本地快照并继续{context}："
            f"{type(exc).__name__}: {exc}"
        )


def merge_payload(
    user_json: str = "",
    module: str = "",
    json_only: bool = False,
    query_mode: str = "",
) -> Dict[str, Any]:
    """合并用户 JSON 到默认 payload，确保 current 和 pageSize 始终存在"""
    default = page_payload()

    def apply_contract(value: Dict[str, Any]) -> Dict[str, Any]:
        if not module:
            return value
        try:
            value = validate_pool_query_scope(module, value, query_mode)
            value = validate_payload(module, value, FIELD_SCHEMA)
            return validate_query_semantics(module, value, query_mode)
        except QueryContractError as exc:
            die(f"查询条件无效: {exc}")

    if not user_json or not user_json.strip():
        if module in {"contact", "account/contact"}:
            default["viewId"] = "SELF"
        return apply_contract(default)
    try:
        user = json.loads(user_json)
    except json.JSONDecodeError as exc:
        if json_only or user_json.lstrip().startswith(("{", "[")):
            die(f"查询 JSON 解析失败: {exc}")
        default["keyword"] = user_json
        return apply_contract(default)
    if not isinstance(user, dict):
        if json_only or user_json.lstrip().startswith(("{", "[")):
            die("查询 payload 顶层必须是 JSON 对象")
        default["keyword"] = user_json
        return apply_contract(default)
    merged = {**default, **user}
    if module in {"contact", "account/contact"} and "viewId" not in user:
        merged["viewId"] = "SELF"
    # 确保 current 和 pageSize 有值（即使用户传了无效值）
    if not isinstance(merged.get("current"), int) or merged["current"] < 1:
        merged["current"] = 1
    if not isinstance(merged.get("pageSize"), int) or merged["pageSize"] < 1:
        merged["pageSize"] = 30
    return apply_contract(merged)


def parent_payload(field: str, parent_id: str, module: str, user_json: str = "") -> Dict[str, Any]:
    """父维度取数 payload：把父 id 注入 body 顶层。客户维度 field=customerId，
    合同维度 field=contractId。acct-sub / contract-sub 共用。"""
    merged = merge_payload(user_json, module)
    merged[field] = parent_id
    return merged


# ── API 封装（Header Key 鉴权）────────────────────────────────────────
def api_request(method: str, url: str, content_type: str, **kwargs) -> str:
    """执行 API 请求"""
    check_keys()

    headers = {
        "X-Access-Key": CORDYS_ACCESS_KEY,
        "X-Secret-Key": CORDYS_SECRET_KEY,
        "X-Request-Source": "SKILL",
        "Content-Type": f"{content_type}; charset=utf-8"
    }

    # 合并用户提供的 headers（如果有）
    if 'headers' in kwargs:
        headers.update(kwargs.pop('headers'))

    params = kwargs.pop("params", None)
    data = kwargs.pop("data", None)

    if params:
        if isinstance(params, dict):
            query = parse.urlencode(params)
        else:
            query = str(params).lstrip("?")
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{query}"

    data_bytes = None
    if data is not None:
        if isinstance(data, bytes):
            data_bytes = data
        elif isinstance(data, dict):
            data_bytes = parse.urlencode(data).encode("utf-8")
        else:
            data_bytes = str(data).encode("utf-8")

    try:
        req = request.Request(
            url=url,
            data=data_bytes,
            headers=headers,
            method=method.upper()
        )
        with request.urlopen(req) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(e)
        die(f"请求失败: HTTP {e.code} {detail}")
    except URLError as e:
        die(f"请求失败: {e}")


def api(method: str, url: str, **kwargs) -> str:
    """执行 JSON API 请求"""
    return api_request(method, url, "application/json", **kwargs)


def api_form(method: str, url: str, **kwargs) -> str:
    """执行表单 API 请求"""
    return api_request(
        method, url, "application/x-www-form-urlencoded", **kwargs)


# ── CRM 辅助函数 ──────────────────────────────────────────────────────
def crm_view(module: str, opts: str = "") -> str:
    """列出视图定义（不返回业务数据，仅 viewId 列表；查记录用 crm page）"""
    if opts:
        die("view 只接受模块名，不接受额外参数")
    if module == "contract/business-title":
        return json.dumps({"code": 100200, "data": []}, ensure_ascii=False)
    api_module = {
        "follow": "follow/record",
        "follow-plan": "follow/plan",
    }.get(module, crm_api_module(module))
    return api("GET", f"{CORDYS_CRM_DOMAIN}/{api_module}/view/list")


def crm_get(module: str, id: str) -> str:
    """获取单条记录详情"""
    return api("GET", f"{CORDYS_CRM_DOMAIN}/{crm_api_module(module)}/get/{id}")


def crm_contact(module: str, id: str) -> str:
    """获取联系人列表"""
    return api("GET", f"{CORDYS_CRM_DOMAIN}/{module}/contact/list/{id}")


def crm_page(module: str, payload_or_keyword: str = "") -> str:
    """列表分页记录"""
    body = json.dumps(
        merge_payload(payload_or_keyword, module, query_mode="page"),
        ensure_ascii=False,
    )

    # 防呆：签约后家族不手搓 /page body，走维度取数器（父 id 位置坑藏在命令里）。
    # customerId/accountId 出现在 body 任何位置（顶层键或 conditions）都拦——顶层 customerId
    # 在这些 /page 上被静默忽略、返回全表。contractId 只拦 conditions：顶层 contractId 是
    # payment-record/payment-plan 的合法过滤（contract-sub 内部即如此），放行。
    if module in POST_SIGNING_MODULES:
        if re.search(r'"(customerId|accountId)"', body):
            die(f"客户名下的 {module} 走 cordys.py crm acct-sub <子资源> <客户ID>（自动带 customerId）；"
                f"在 /page body 里带 customerId/accountId（顶层或条件）会静默返回全表或报错。见 core/cli-spec.md §14。")
        if re.search(r'"name"\s*:\s*"contractId"', body):
            die("合同名下的回款/回款计划走 cordys.py crm contract-sub payment-record|payment-plan <合同ID>"
                "（自动把 contractId 放对位置），不要放进 combineSearch.conditions。见 core/cli-spec.md §14。")

    path_module = "account/contact" if module == "contact" else module
    path = f"{path_module}/page"
    return api("POST", f"{CORDYS_CRM_DOMAIN}/{path}", data=body)


def crm_search(module: str, json_data: str = "") -> str:
    """全局搜索记录"""
    if module == "opportunity/quotation":
        return crm_page(module, json_data)
    # 防呆：签约后家族无全局搜索端点（/global/search/{module} 不存在 → 静默返回空），按父维度取数。
    if module in POST_SIGNING_MODULES:
        die(f"{module} 无全局搜索，按父维度取数：客户名下用 cordys.py crm acct-sub <子资源> <客户ID>；"
            f"合同名下用 cordys.py crm contract-sub payment-record|payment-plan|invoice-stat <合同ID>；"
            f"只有名称关键词用 cordys.py crm page {module} '{{\"keyword\":\"关键词\"}}'。见 core/cli-spec.md §14。")
    merged = merge_payload(json_data, module, query_mode="search")
    body = json.dumps(merged, ensure_ascii=False)
    if module in {"contact", "account/contact"}:
        return api("POST", f"{CORDYS_CRM_DOMAIN}/account/contact/page", data=body)
    search_module = {
        "pool/lead": "clue_pool",
        "pool/account": "customer_pool",
    }.get(module, module)
    path = f"global/search/{search_module}"
    return api("POST", f"{CORDYS_CRM_DOMAIN}/{path}", data=body)


def crm_follow_page(
    kind: str, payload: str = "", legacy_payload=None
) -> str:
    """查询统一跟进计划或跟进记录列表。

    标准调用是 ``crm_follow_page(kind, payload)``。为避免旧调用切换到全局
    端点后扩大范围，也兼容 ``crm_follow_page(kind, module, payload)``，但会把
    旧 payload 的 sourceId 转为明确的资源字段 condition。
    """
    legacy_module = ""
    if payload in FOLLOW_SOURCE_FIELDS:
        legacy_module = payload
        payload = legacy_payload or ""
    elif legacy_payload is not None:
        die("follow 新版用法只接受一个 JSON；旧版三参数调用的模块必须为 lead/account/opportunity")

    try:
        merged = normalize_follow(
            payload,
            kind,
            legacy_module,
            str(SCRIPT_DIR / "sop"),
            str(FIELD_SCHEMA),
        )
    except PayloadTransportError as exc:
        die(str(exc))
    body = json.dumps(merged, ensure_ascii=False)
    return api("POST", f"{CORDYS_CRM_DOMAIN}/follow/{kind}/page", data=body)


def crm_follow_get(kind: str, module: str, entry_id: str) -> str:
    """获取单条跟进计划或跟进记录详情。"""
    if kind not in ("plan", "record"):
        die("follow-get 只支持 plan/record")
    if module not in ("lead", "account", "opportunity"):
        die(f"follow-get {kind} 的模块必须为 lead/account/opportunity")
    if not str(entry_id).isdigit():
        die(f"follow-get {kind} 需要合法的数字 ID")
    return api("GET", f"{CORDYS_CRM_DOMAIN}/{module}/follow/{kind}/get/{entry_id}")


# ── 审批相关 ──────────────────────────────────────────────────────────
def crm_approval_todo(kind: str, payload: str = "") -> str:
    """审批代办列表"""
    merged = merge_payload(payload)
    body = json.dumps(merged, ensure_ascii=False)
    kind_map = {
        "pending":   f"{CORDYS_CRM_DOMAIN}/approval-todo/pending/page",
        "processed": f"{CORDYS_CRM_DOMAIN}/approval-todo/processed/page",
        "initiated": f"{CORDYS_CRM_DOMAIN}/approval-todo/initiated/page",
        "cc":        f"{CORDYS_CRM_DOMAIN}/approval-todo/cc/page",
    }
    if kind == "count":
        return api("GET", f"{CORDYS_CRM_DOMAIN}/approval-todo/pending/count")
    if kind not in kind_map:
        die(f"未知的审批代办类型: {kind}。支持: pending, processed, initiated, cc, count")
    return api("POST", kind_map[kind], data=body)


def crm_approval_action(action: str, payload: str = "") -> str:
    """审批操作（同意/驳回/退回/加签/撤回/批量）"""
    if not payload or not payload.strip().startswith("{"):
        die(f"{action} 需要 JSON body")
    action_map = {
        "approve":       f"{CORDYS_CRM_DOMAIN}/approval-action/approve",
        "reject":        f"{CORDYS_CRM_DOMAIN}/approval-action/reject",
        "back":          f"{CORDYS_CRM_DOMAIN}/approval-action/back",
        "sign":          f"{CORDYS_CRM_DOMAIN}/approval-action/sign",
        "revoke":        f"{CORDYS_CRM_DOMAIN}/approval-action/revoke",
        "batch-approve": f"{CORDYS_CRM_DOMAIN}/approval-action/batch-approve",
        "batch-reject":  f"{CORDYS_CRM_DOMAIN}/approval-action/batch-reject",
    }
    if action not in action_map:
        die(f"未知的审批操作: {action}。支持: approve, reject, back, sign, revoke, batch-approve, batch-reject")
    return api("POST", action_map[action], data=payload)


def crm_approval_resource(action: str, arg: str = "") -> str:
    """审批资源（提审/撤销/详情）"""
    if action == "push":
        return api("POST", f"{CORDYS_CRM_DOMAIN}/approval-resource/push", data=arg)
    elif action == "revoke":
        return api("POST", f"{CORDYS_CRM_DOMAIN}/approval-resource/revoke", data=arg)
    elif action == "simple-detail":
        return api("GET", f"{CORDYS_CRM_DOMAIN}/approval-resource/simple-detail/{arg}")
    elif action == "detail":
        return api("GET", f"{CORDYS_CRM_DOMAIN}/approval-resource/detail/{arg}")
    else:
        die(f"未知的审批资源操作: {action}。支持: push, revoke, simple-detail, detail")


def crm_approval_flow(action: str, arg: str = "") -> str:
    """审批流管理"""
    base = CORDYS_CRM_DOMAIN
    if action == "list":
        body = json.dumps(merge_payload(arg), ensure_ascii=False)
        return api("POST", f"{base}/approval-flow/page", data=body)
    elif action == "get":
        return api("GET", f"{base}/approval-flow/get/{arg}")
    elif action == "add":
        return api("POST", f"{base}/approval-flow/add", data=arg)
    elif action == "update":
        return api("POST", f"{base}/approval-flow/update", data=arg)
    elif action == "enable":
        return api("GET", f"{base}/approval-flow/enable/{arg}?enable=true")
    elif action == "disable":
        return api("GET", f"{base}/approval-flow/enable/{arg}?enable=false")
    elif action == "by-form":
        return api("GET", f"{base}/approval-flow/get-by-form-type/{arg}")
    elif action == "setting":
        return api("GET", f"{base}/approval-flow/status-permission/setting/{arg}")
    elif action == "webhook-test":
        return api("POST", f"{base}/approval-flow/webhook/test", data=arg)
    else:
        die(f"未知的审批流操作: {action}")


def crm_product(keyword: str = "") -> str:
    """查询产品"""
    if keyword.startswith("{"):
        body = keyword
    else:
        body = json.dumps(page_payload(keyword), ensure_ascii=False)

    return api("POST", f"{CORDYS_CRM_DOMAIN}/field/source/product", data=body)


def crm_whoami() -> str:
    """获取当前登录用户信息"""
    return api("GET", f"{CORDYS_CRM_DOMAIN}/personal/center/info")


def crm_verify() -> str:
    """验证 API 密钥是否有效，返回用户信息"""
    return crm_whoami()


def crm_org(mode: str = "tree", target: str = "") -> str:
    """获取完整组织树、递归 ID，或可直接关联的扁平层级。"""
    if mode not in ("tree", "ids", "outline"):
        die(
            f"未知的 crm org 模式: {mode}。支持: tree, ids [部门名称或ID], "
            "outline [部门名称或ID]"
        )
    if mode == "tree" and target:
        die("crm org tree 不接受额外参数")
    raw_response = api("GET", f"{CORDYS_CRM_DOMAIN}/department/tree")
    if mode == "tree":
        return raw_response
    try:
        if mode == "ids":
            return render_descendant_ids(raw_response, target)
        return render_department_outline(raw_response, target)
    except OrgTreeError as exc:
        die(str(exc))
    return ""


def crm_members(
    json_data: str = "",
    name: str = "",
    compact: bool = False,
    active: bool = False,
    exact_departments: bool = False,
) -> str:
    """单进程查询成员；显式部门默认递归展开全部子部门。"""
    check_keys()
    try:
        return query_members(
            json_data,
            name,
            compact,
            active,
            exact_departments,
            domain=CORDYS_CRM_DOMAIN,
            access_key=CORDYS_ACCESS_KEY,
            secret_key=CORDYS_SECRET_KEY,
        )
    except MembersResponseError as exc:
        if exc.response:
            print(
                redact_sensitive(
                    exc.response, (CORDYS_ACCESS_KEY, CORDYS_SECRET_KEY)
                )
            )
        die(f"成员查询失败: {exc}")
    except MembersQueryError as exc:
        die(f"成员查询失败: {exc}")


# ── 原始 API 调用 ─────────────────────────────────────────────────────
def crm_stat(module: str, payload: str = "") -> str:
    """Server-side amount statistics."""
    body = json.dumps(
        merge_payload(payload, module, json_only=True, query_mode="stat"),
        ensure_ascii=False,
    )
    module_map = {
        "contract": f"{CORDYS_CRM_DOMAIN}/contract/statistic",
        "contract/payment-record": f"{CORDYS_CRM_DOMAIN}/contract/payment-record/statistic",
        "opportunity": f"{CORDYS_CRM_DOMAIN}/opportunity/statistic",
        "order": f"{CORDYS_CRM_DOMAIN}/order/statistic",
    }
    if module not in module_map:
        die(f"unsupported stat module: {module}. supported: contract, contract/payment-record, opportunity, order")
    return api("POST", module_map[module], data=body)


def crm_stat_home(kind: str, payload: str = "") -> str:
    """Server-side home statistics."""
    if payload and payload.strip().startswith("{"):
        body = payload
    else:
        body = json.dumps({
            "searchType": "SELF",
            "timeField": "CREATE_TIME",
            "userField": "OWNER",
            "priorPeriodEnable": True,
        }, ensure_ascii=False)
    kind_map = {
        "lead": f"{CORDYS_CRM_DOMAIN}/home/statistic/lead",
        "opportunity": f"{CORDYS_CRM_DOMAIN}/home/statistic/opportunity",
        "opportunity/success": f"{CORDYS_CRM_DOMAIN}/home/statistic/opportunity/success",
        "opportunity/underway": f"{CORDYS_CRM_DOMAIN}/home/statistic/opportunity/underway",
    }
    if kind == "dept-tree":
        return api("GET", f"{CORDYS_CRM_DOMAIN}/home/statistic/department/tree")
    if kind not in kind_map:
        die(f"unsupported home stat type: {kind}. supported: lead, opportunity, opportunity/success, opportunity/underway, dept-tree")
    return api("POST", kind_map[kind], data=body)


def crm_glocount(keyword: str) -> str:
    """Global search module counts."""
    from urllib.parse import quote
    if not keyword:
        die("glocount requires keyword")
    return api("POST", f"{CORDYS_CRM_DOMAIN}/global/search/module/count?keyword={quote(keyword, safe='')}")


def crm_acct_sub(sub: str, acct_id: str, payload: str = "") -> str:
    """Account child resources and statistics."""
    if not sub or not acct_id:
        die("acct-sub requires sub resource and account ID")
    if sub == "contract-stat":
        return api("GET", f"{CORDYS_CRM_DOMAIN}/account/contract/statistic/{acct_id}")
    if sub == "payment-plan-stat":
        return api("GET", f"{CORDYS_CRM_DOMAIN}/account/contract/payment-plan/statistic/{acct_id}")
    if sub == "payment-record-stat":
        return api("GET", f"{CORDYS_CRM_DOMAIN}/account/contract/payment-record/statistic/{acct_id}")
    if sub == "invoice-stat":
        return api("GET", f"{CORDYS_CRM_DOMAIN}/account/invoice/statistic/{acct_id}")

    schema_module = {
        "contract": "contract",
        "opportunity": "opportunity",
        "payment-record": "contract/payment-record",
        "payment-plan": "contract/payment-plan",
    }.get(sub, sub)
    body = json.dumps(parent_payload("customerId", acct_id, schema_module, payload), ensure_ascii=False)
    sub_map = {
        "contract": f"{CORDYS_CRM_DOMAIN}/account/contract/page",
        "opportunity": f"{CORDYS_CRM_DOMAIN}/account/opportunity/page",
        "order": f"{CORDYS_CRM_DOMAIN}/account/order/page",
        "payment-plan": f"{CORDYS_CRM_DOMAIN}/account/contract/payment-plan/page",
        "payment-record": f"{CORDYS_CRM_DOMAIN}/account/contract/payment-record/page",
        "invoice": f"{CORDYS_CRM_DOMAIN}/account/invoice/page",
    }
    if sub not in sub_map:
        die(f"unsupported account sub resource: {sub}")
    return api("POST", sub_map[sub], data=body)


def crm_contract_sub(sub: str, contract_id: str, payload: str = "") -> str:
    """合同维度取数器：acct-sub 的镜像。回款/回款计划走 /contract/{sub}/page 顶层 contractId，
    contractId 位置坑藏在命令内部。"""
    if not sub or not contract_id:
        die("contract-sub requires sub resource and contract ID")
    if sub == "invoice-stat":
        return api("GET", f"{CORDYS_CRM_DOMAIN}/contract/invoice/statistic/{contract_id}")
    if sub in ("invoice", "order"):
        die(f"合同名下的发票/订单查不了明细列表（/page 不按 contractId 过滤），只能取统计："
            f"cordys.py crm contract-sub invoice-stat <合同ID>。客户名下明细走 cordys.py crm acct-sub {sub} <客户ID>。")
    sub_map = {
        "payment-record": f"{CORDYS_CRM_DOMAIN}/contract/payment-record/page",
        "payment-plan": f"{CORDYS_CRM_DOMAIN}/contract/payment-plan/page",
    }
    if sub not in sub_map:
        die(f"unsupported contract sub resource: {sub}. supported: payment-record, payment-plan, invoice-stat")
    schema_module = f"contract/{sub}"
    body = json.dumps(parent_payload("contractId", contract_id, schema_module, payload), ensure_ascii=False)
    return api("POST", sub_map[sub], data=body)


# ── 写入操作（创建/更新/转化）─────────────────────────────────────────
def validate_write_module(module: str, operation: str) -> None:
    """限制写入命令只能访问当前 Skill 声明的表单模块。"""
    if module not in WRITE_MODULES:
        supported = ", ".join(WRITE_MODULES)
        die(f"{operation} 不支持的写入模块: {module}。支持: {supported}")


def validate_batch_update_module(module: str) -> None:
    """批量编辑只允许后端已开放 batch-update 的模块。"""
    if module not in BATCH_UPDATE_MODULES:
        supported = ", ".join(BATCH_UPDATE_MODULES)
        die(f"batch-update 不支持的模块: {module}。仅支持: {supported}")


UPDATE_DENY_FIELDS = {
    "attachmentMap", "optionMap", "contactName", "customerName", "departmentName", "ownerName",
    "createUser", "updateUser", "createUserName", "updateUserName", "createTime", "updateTime",
    "followerName", "follower", "followTime", "stage", "stageName", "stageUpdateTime", "lastStage",
    "inCustomerPool", "poolId", "possible", "reservedDays", "failureReason", "organizationId",
    "departmentId",
}


def merge_update_body(existing_raw: str, caller: dict, form_raw: str = "") -> dict:
    """保全现有可写字段和 moduleFields，再覆盖调用方明确修改的值。"""
    try:
        wrapper = json.loads(existing_raw)
    except json.JSONDecodeError as exc:
        die(f"读回合并：现有记录解析失败: {exc}")
    existing = wrapper.get("data") if isinstance(wrapper, dict) else None
    if not isinstance(existing, dict) or not existing.get("id"):
        die("读回合并：GET 未取到现有记录（id 不存在或已删除），中止以免清空字段")

    body = {
        key: value
        for key, value in existing.items()
        if key != "moduleFields" and key not in UPDATE_DENY_FIELDS and value is not None
    }
    module_fields = {
        item.get("fieldId"): item.get("fieldValue")
        for item in (existing.get("moduleFields") or [])
        if isinstance(item, dict) and item.get("fieldId") is not None
    }
    body.update({key: value for key, value in caller.items() if key != "moduleFields"})
    for item in caller.get("moduleFields") or []:
        if isinstance(item, dict) and item.get("fieldId") is not None:
            module_fields[item["fieldId"]] = item.get("fieldValue")
    body["moduleFields"] = [
        {"fieldId": field_id, "fieldValue": value}
        for field_id, value in module_fields.items()
    ]
    if form_raw:
        try:
            body["moduleFormConfigDTO"] = extract_form_config(
                form_raw, "子表模块"
            )
        except PayloadTransportError as exc:
            die(f"读回合并：{exc}")
    return body


def crm_form(module: str) -> str:
    """获取模块表单定义"""
    validate_write_module(module, "form")
    ensure_local_snapshot("写入")
    return api("GET", f"{CORDYS_CRM_DOMAIN}/{crm_api_module(module)}/module/form")


def crm_add(module: str, payload: str = "") -> str:
    """创建记录"""
    validate_write_module(module, "create")
    try:
        ensure_local_snapshot("写入")
        api_module = crm_api_module(module)
        if module == "order" and order_split_enabled(payload):
            result, status = execute_order_batch(
                payload,
                FIELD_SCHEMA,
                domain=CORDYS_CRM_DOMAIN,
                access_key=CORDYS_ACCESS_KEY,
                secret_key=CORDYS_SECRET_KEY,
            )
            serialized = json.dumps(
                result, ensure_ascii=False, separators=(",", ":")
            )
            if status:
                print(serialized)
                raise SystemExit(status)
            return serialized
        form_raw = ""
        if module_has_subforms(module, FIELD_SCHEMA):
            form_raw = api(
                "GET",
                f"{CORDYS_CRM_DOMAIN}/{api_module}/module/form",
            )
        contract_raw = ""
        if module == "order":
            contract_id = order_contract_id(payload)
            contract_raw = api(
                "GET",
                f"{CORDYS_CRM_DOMAIN}/contract/get/{contract_id}",
            )
        body = prepare_create_payload(
            payload,
            module,
            FIELD_SCHEMA,
            form_raw,
            contract_raw,
        )
    except (PayloadTransportError, OrderBatchError) as exc:
        die(str(exc))
    return api(
        "POST",
        f"{CORDYS_CRM_DOMAIN}/{api_module}/add",
        data=json.dumps(body, ensure_ascii=False),
    )


def crm_update(module: str, payload: str = "") -> str:
    """更新记录（JSON 须包含 id）"""
    validate_write_module(module, "update")
    if not payload or not payload.strip().startswith("{"):
        die("update 需要 JSON body（须包含 id）")
    try:
        caller = json.loads(payload)
    except json.JSONDecodeError as exc:
        die(f"update JSON 解析失败: {exc}")
    if not isinstance(caller, dict) or not caller.get("id"):
        die("update 的 JSON body 必须包含 id")
    ensure_local_snapshot("写入")
    api_module = crm_api_module(module)
    existing = api("GET", f"{CORDYS_CRM_DOMAIN}/{api_module}/get/{caller['id']}")
    form_config = ""
    try:
        needs_form_config = module_has_subforms(module, FIELD_SCHEMA)
    except PayloadTransportError as exc:
        die(str(exc))
    if needs_form_config:
        form_config = api("GET", f"{CORDYS_CRM_DOMAIN}/{api_module}/module/form")
    body = merge_update_body(existing, caller, form_config)
    return api(
        "POST",
        f"{CORDYS_CRM_DOMAIN}/{api_module}/update",
        data=json.dumps(body, ensure_ascii=False),
    )


def crm_batch_update(module: str, payload: str = "") -> str:
    """按字段批量更新（须包含 ids, fieldId, fieldValue）"""
    validate_batch_update_module(module)
    if not payload or not payload.strip().startswith("{"):
        die("batch-update 需要 JSON body（须包含 ids, fieldId, fieldValue）")
    try:
        body = json.loads(payload)
    except json.JSONDecodeError as exc:
        die(f"batch-update JSON 解析失败: {exc}")
    if not isinstance(body, dict):
        die("batch-update body 必须是 JSON 对象")
    ensure_local_snapshot("写入")
    return api("POST", f"{CORDYS_CRM_DOMAIN}/{crm_api_module(module)}/batch/update", data=payload)


# ── 原始 API 调用 ─────────────────────────────────────────────────────
def raw_api(method: str, path: str, *args) -> str:
    """执行原始 API 调用"""
    if len(args) > 1:
        die("raw 只接受一个可选 JSON body")
    body = args[0] if args else ""
    if body and not body.strip().startswith(("{", "[")):
        die("raw body 必须是 JSON 对象或数组")
    if body:
        try:
            json.loads(body)
        except json.JSONDecodeError as exc:
            die(f"raw JSON 解析失败: {exc}")
    guarded_path = parse.urlparse(path).path if path.startswith("http") else path
    if guarded_path in ("/lead/transform", "/lead/transition/account"):
        die(
            "raw 转化端点已禁用：裸端点会静默丢失商机字段。"
            "请改用 scripts/cordys_ext.sh transform '<JSON>'"
        )
    if guarded_path in ("/pool/lead/page", "/pool/account/page"):
        module = guarded_path.removeprefix("/pool/").removesuffix("/page")
        die(
            f"raw 池分页已禁用：请改用 cordys.py crm page pool/{module}，"
            "由查询契约在联网前强制校验 payload 顶层 poolId。"
            f"先执行 cordys.py raw GET /pool/{module}/options 获取 id"
        )
    if "/follow/" in guarded_path or "/follow/page" in guarded_path:
        if not re.fullmatch(r"/follow/(plan|record)/page", guarded_path):
            die("invalid follow path: expected /follow/<plan|record>/page")
        if method.upper() != "POST":
            die("跟进列表接口只支持 POST")

    if path.startswith("http"):
        # 验证URL域名
        if not validate_url(path):
            print("❌ 拒绝请求：目标域名与配置的Cordys CRM域名不匹配", file=sys.stderr)
            print(f"   配置的域名: {CORDYS_CRM_DOMAIN}", file=sys.stderr)
            print("   如需强制发送，请设置环境变量 CORDYS_ALLOW_UNTRUSTED=1", file=sys.stderr)
            
            if os.environ.get("CORDYS_ALLOW_UNTRUSTED", "0") != "1":
                sys.exit(1)
            else:
                warn("已启用不受信任域名模式，继续发送请求...")
        
        url = path
    else:
        url = f"{CORDYS_CRM_DOMAIN}{path}"

    return api(method, url, **({"data": body} if body else {}))


# ── CLI 处理 ──────────────────────────────────────────────────────────
def print_usage():
    """打印使用帮助"""
    usage_text = """
cordys — CORDYS CRM CLI 工具（X-Access-Key 模式）

使用方法:
  cordys <命令> [参数...]

CRM 操作:
  crm view <模块>                    列出视图定义（不返回业务数据，仅 viewId 列表；查记录用 crm page）
  crm get <模块> <ID>               获取单条记录详情
  crm search <模块> [关键词|JSON|-]  全局搜索记录（- 或 @- 从 UTF-8 stdin 读 JSON）
  crm page <模块> [关键词|JSON|-]    列表分页记录 /<module>/page（- 或 @- 从 UTF-8 stdin 读 JSON）
  crm whoami                       获取当前登录用户信息
  crm verify                       验证 API 密钥是否有效
  crm org [tree]                   获取完整组织架构树
  crm org ids [部门名称或ID]        展开部门及所有子部门ID（不传部门=全部可见部门）
  crm org outline [部门名称或ID]    输出 id/name/parentId/path/depth 层级
  crm members [JSON] [--name 姓名] [--active] [--compact] [--exact-departments]  获取成员；部门默认递归，exact 仅直属范围
  crm follow <plan|record> [关键词|JSON|-]  查询统一跟进计划或跟进记录列表
  crm follow-get <plan|record> <模块> <ID> 获取跟进计划或跟进记录详情
  crm product [关键词|JSON]          查询产品列表
  crm contact <模块> <ID>           获取联系人列表

统计与 L2C:
  crm stat <模块> [JSON]             模块金额统计（contract/opportunity/order/contract/payment-record）
  crm stat-home <类型> [JSON]        首页统计（lead/opportunity/opportunity/success/opportunity/underway/dept-tree）
写入操作（创建/更新）:
  crm form <模块>                   获取可写模块表单定义
  crm create <模块> <JSON|->        创建记录（- 或 @- 读 UTF-8 stdin；子表模块自动附加当前表单配置）
  订单创建外层只传 contractId 和可选公共默认字段；CLI 按具体产品/服务+收入类型自动分组，同组多行合并、名称模板不变、逐单计算公式并分摊调整金额，全部成功后回写合同拆单标记；见 sop/order-create-flow.md
  crm update <模块> <JSON|->        更新记录（JSON 须包含 id；- 或 @- 从 UTF-8 stdin 读取）
  crm batch-update <模块> <JSON>    按字段批量更新（lead/account/opportunity/contact/contract/order）
  线索转化请使用 cordys_ext.sh transform（多步补全联系人、客户和商机字段）

统计与管道:
  crm stat <模块> [JSON]             模块金额统计（contract/opportunity/order/payment-record）
  crm stat-home <类型> [JSON]        首页统计（lead/opportunity/success/underway/dept-tree）
  crm glocount <关键词>              全局搜索各模块命中计数
  crm acct-sub <子资源> <客户ID> [JSON] 客户子资源/统计（contract/opportunity/order/payment-plan/payment-record/invoice）
  crm contract-sub <子资源> <合同ID> [JSON]  合同子资源（payment-record/payment-plan 明细、invoice-stat 统计）

支持的 CRM 一级模块:
 [lead（线索）, pool/lead（线索池/线索公海）, account（客户）, pool/account（客户公海）, opportunity（商机）, contact（联系人）, contract（合同）]

列表查询示例:
  cordys raw GET /pool/lead/options
  cordys raw GET /pool/account/options
  cordys crm page pool/lead '{"poolId":"<线索池ID>","current":1,"pageSize":5,"sort":{"createTime":"desc"}}'
  cordys crm page pool/account '{"poolId":"<客户公海ID>","current":1,"pageSize":5,"sort":{"createTime":"desc"}}'
  注：具体池 page 的 poolId 必须是 payload 顶层非空字符串；跨池 search 不传 poolId，但必须传 keyword
  cordys crm view lead
  cordys crm page lead
  cordys crm page lead "测试"
  cordys crm page lead '{"current":1,"pageSize":30,"sort":{},"combineSearch":{"searchMode":"AND","conditions":[]},"keyword":"","viewId":"ALL","filters":[]}'
  cordys crm page contract/payment-plan '{"current":1,"pageSize":30,"sort":{},"combineSearch":{"searchMode":"AND","conditions":[]},"keyword":"","viewId":"ALL","filters":[]}'
  cordys crm search account '{"current":1,"pageSize":30,"combineSearch":{"searchMode":"AND","conditions":[]},"keyword":"xyz","viewId":"ALL","filters":[]}'
  cordys crm org
  cordys crm org ids "销售三部"
  cordys crm org outline "东区"
  cordys crm members '{"departmentIds":["销售一部ID","销售二部ID"]}' --active --compact
  cordys crm members --name 张三 --compact
  cordys crm follow plan '{"current":1,"pageSize":10,"keyword":"","status":"ALL","viewId":"ALL"}'
  cordys crm follow record '{"current":1,"pageSize":10,"keyword":"","viewId":"ALL"}'
  cordys crm follow record '{"combineSearch":{"searchMode":"AND","conditions":[{"value":["1751888184018919"],"operator":"IN","name":"customerId","type":"DATA_SOURCE"}]}}'
  cordys crm follow-get record account '500000000000000001'
  cordys crm product "测试"
  cordys crm contact account '927627065163785'

支持的 CRM 二级模块 :
  [contract/payment-plan(回款计划), invoice（发票）,contract/business-title(工商抬头）,contract/payment-record(回款记录), opportunity/quotation(报价单)]

列表查询示例：
  cordys crm page contract/payment-plan
  cordys crm page contract/business-title

写入示例:
  cordys crm form lead
  cordys crm create lead '{"name":"张三","phone":"13800138000","products":["p1"]}'
  cordys crm create account '{"name":"华星科技"}'
  cordys crm create opportunity '{"name":"项目","customerId":"xxx","contactId":"yyy","amount":120000,"products":["p1"]}'
  cordys crm create account/contact '{"customerId":"xxx","name":"张三"}'
  cordys crm update contact '{"id":"xxx","moduleFields":[{"fieldId":"1751888184000051","fieldValue":"采购总监"}]}'
  cordys crm update lead '{"id":"xxx","name":"新名称"}'
  cordys crm batch-update lead '{"ids":["id1"],"fieldId":"635449004900383","fieldValue":"admin"}'

原始 API:
  raw <方法> <路径> [JSON body]
  cordys raw GET /settings/fields?module=account

审批操作:
  cordys crm approval todo pending ['{"current":1,"pageSize":30}']
  cordys crm approval todo pending '{"resourceType":"CONTRACT"}'
  cordys crm approval todo count
  cordys crm approval action approve '{"resourceId":"xxx","remark":"同意"}'
  cordys crm approval action reject '{"resourceId":"xxx","remark":"驳回原因"}'
  cordys crm approval resource push '{"resourceId":"xxx"}'
  cordys crm approval resource detail RESOURCE_ID
  cordys crm approval flow list '{"current":1,"pageSize":30}'
  cordys crm stat contract '{"viewId":"ALL","combineSearch":{"conditions":[]}}'
  cordys crm stat-home lead '{"searchType":"SELF","timeField":"CREATE_TIME","userField":"OWNER","priorPeriodEnable":true}'
  cordys crm glocount 华星科技
  cordys crm acct-sub payment-record-stat ACCOUNT_ID
  cordys crm contract-sub payment-record CONTRACT_ID
  cordys crm contract-sub invoice-stat CONTRACT_ID
  cordys crm date-ms "2026-07-01 00:00"
  cordys crm date-range 2026-07-01 2026-07-31

审批 todo 类型: pending, processed, initiated, cc, count
审批 action 操作: approve, reject, back, sign, revoke, batch-approve, batch-reject
审批 resource 操作: push, revoke, simple-detail, detail
审批 flow 操作: list, get, add, update, enable, disable, by-form, setting, webhook-test

环境变量要求:
  CORDYS_ACCESS_KEY
  CORDYS_SECRET_KEY
  CORDYS_CRM_DOMAIN

"""
    print(usage_text)


def handle_crm_command(args: list) -> None:
    """处理 CRM 命令"""
    if not args:
        die("crm 需要子命令")

    sub_cmd = args[0]
    rest_args = args[1:]

    if sub_cmd == "view":
        if not rest_args:
            die("view 需要指定模块")
        module = rest_args[0]
        opts = rest_args[1] if len(rest_args) > 1 else ""
        print(crm_view(module, opts))

    elif sub_cmd == "get":
        if len(rest_args) < 2:
            die("get 需要 <模块> <ID>")
        print(crm_get(rest_args[0], rest_args[1]))

    elif sub_cmd == "search":
        if not rest_args:
            die("search 需要指定模块")
        module = rest_args[0]
        json_data = rest_args[1] if len(rest_args) > 1 else ""
        json_data = read_payload_marker(json_data)
        print(crm_search(module, json_data))

    elif sub_cmd == "page":
        if not rest_args:
            die("page 需要指定模块")
        module = rest_args[0]
        payload = rest_args[1] if len(rest_args) > 1 else ""
        payload = read_payload_marker(payload)
        print(crm_page(module, payload))

    elif sub_cmd == "org":
        if len(rest_args) > 2:
            die("crm org 用法: crm org [tree|ids|outline [部门名称或ID]]")
        print(crm_org(*rest_args))

    elif sub_cmd == "product":
        keyword = rest_args[0] if rest_args else ""
        print(crm_product(keyword))

    elif sub_cmd == "date-ms":
        if len(rest_args) != 1:
            die("date-ms 用法: cordys.py crm date-ms '<YYYY-MM-DD[ HH:MM[:SS]]>'")
        try:
            result = timestamp_value(rest_args[0])
        except TimeBoundaryError as exc:
            die(str(exc))
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

    elif sub_cmd == "date-range":
        if len(rest_args) != 2:
            die("date-range 用法: cordys.py crm date-range <开始日期> <结束日期>（两端都包含）")
        try:
            result = date_range(rest_args[0], rest_args[1])
        except TimeBoundaryError as exc:
            die(str(exc))
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

    elif sub_cmd == "stat":
        module = rest_args[0] if rest_args else ""
        payload = rest_args[1] if len(rest_args) > 1 else ""
        payload = read_payload_marker(payload)
        print(crm_stat(module, payload))

    elif sub_cmd == "stat-home":
        kind = rest_args[0] if rest_args else ""
        payload = rest_args[1] if len(rest_args) > 1 else ""
        payload = read_payload_marker(payload)
        print(crm_stat_home(kind, payload))

    elif sub_cmd == "glocount":
        keyword = rest_args[0] if rest_args else ""
        print(crm_glocount(keyword))

    elif sub_cmd == "acct-sub":
        if len(rest_args) < 2:
            die("acct-sub requires <sub> <accountId> [JSON]")
        sub = rest_args[0]
        acct_id = rest_args[1]
        payload = rest_args[2] if len(rest_args) > 2 else ""
        payload = read_payload_marker(payload)
        print(crm_acct_sub(sub, acct_id, payload))

    elif sub_cmd == "contract-sub":
        if len(rest_args) < 2:
            die("contract-sub requires <sub> <contractId>")
        payload = rest_args[2] if len(rest_args) > 2 else ""
        payload = read_payload_marker(payload)
        print(crm_contract_sub(rest_args[0], rest_args[1], payload))

    elif sub_cmd == "whoami":
        print(crm_whoami())

    elif sub_cmd == "verify":
        print(crm_verify())

    elif sub_cmd == "members":
        try:
            payload, name, compact, active, exact_departments = (
                parse_members_cli_args(rest_args)
            )
        except MembersQueryError as exc:
            die(str(exc))
        payload = read_payload_marker(payload)
        print(
            crm_members(
                payload, name, compact, active, exact_departments
            )
        )

    elif sub_cmd == "contact":
        if len(rest_args) < 2:
            die("contact 需要 <模块> <ID>")
        print(crm_contact(rest_args[0], rest_args[1]))

    elif sub_cmd == "form":
        if not rest_args:
            die("form 需要指定模块")
        print(crm_form(rest_args[0]))

    elif sub_cmd in ("add", "create"):
        if not rest_args:
            die("add 需要指定模块")
        if len(rest_args) > 2:
            die("create 只接受模块和一个 JSON body")
        module = rest_args[0]
        payload = rest_args[1] if len(rest_args) > 1 else ""
        payload = read_payload_marker(payload)
        print(crm_add(module, payload))

    elif sub_cmd == "update":
        if not rest_args:
            die("update 需要指定模块")
        module = rest_args[0]
        payload = rest_args[1] if len(rest_args) > 1 else ""
        payload = read_payload_marker(payload)
        print(crm_update(module, payload))

    elif sub_cmd == "batch-update":
        if not rest_args:
            die("batch-update 需要指定模块")
        module = rest_args[0]
        payload = rest_args[1] if len(rest_args) > 1 else ""
        print(crm_batch_update(module, payload))

    elif sub_cmd in ("transition", "transform"):
        die(
            "crm transform/transition 已禁用：裸端点会静默丢失商机字段。"
            "请改用 scripts/cordys_ext.sh transform '<JSON>'"
        )

    elif sub_cmd == "follow":
        if not rest_args:
            die("follow 需要 plan 或 record")
        kind = rest_args[0]
        if kind not in ["plan", "record"]:
            die("follow 只支持 plan 或 record")
        follow_args = rest_args[1:]
        if len(follow_args) > 2:
            die("follow 用法: crm follow <plan|record> [JSON|-]")
        if follow_args and follow_args[0] in FOLLOW_SOURCE_FIELDS:
            module = follow_args[0]
            legacy_payload = follow_args[1] if len(follow_args) > 1 else ""
            legacy_payload = read_payload_marker(legacy_payload)
            print(crm_follow_page(kind, module, legacy_payload))
        else:
            if len(follow_args) > 1:
                die("follow 新版用法只接受一个关键词、JSON 或 stdin 标记")
            payload = read_payload_marker(follow_args[0]) if follow_args else ""
            print(crm_follow_page(kind, payload))

    elif sub_cmd == "follow-get":
        if len(rest_args) != 3:
            die("follow-get 需要 <plan|record> <module> <ID>")
        print(crm_follow_get(rest_args[0], rest_args[1], rest_args[2]))

    elif sub_cmd == "approval":
        if not rest_args:
            die("approval 需要子命令")
        sub2 = rest_args[0]
        rest = rest_args[1:]
        if sub2 == "todo":
            kind = rest[0] if rest else ""
            payload = rest[1] if len(rest) > 1 else ""
            print(crm_approval_todo(kind, payload))
        elif sub2 == "action":
            action = rest[0] if rest else ""
            payload = rest[1] if len(rest) > 1 else ""
            print(crm_approval_action(action, payload))
        elif sub2 == "resource":
            action = rest[0] if rest else ""
            arg = rest[1] if len(rest) > 1 else ""
            print(crm_approval_resource(action, arg))
        elif sub2 == "flow":
            action = rest[0] if rest else ""
            arg = rest[1] if len(rest) > 1 else ""
            print(crm_approval_flow(action, arg))
        else:
            die(f"未知的 approval 子命令: {sub2}。支持: todo, action, resource, flow")

    else:
        die(f"未知的 crm 子命令: {sub_cmd}")


def handle_raw_command(args: list) -> None:
    """处理原始 API 命令"""
    if len(args) < 2:
        die("raw 需要 HTTP 方法和路径")

    method = args[0]
    path = args[1]
    body = args[2] if len(args) > 2 else ""
    if len(args) > 3:
        die("raw 只接受 METHOD、PATH 和一个可选 JSON body")
    print(raw_api(method, path, body) if body else raw_api(method, path))


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "crm":
        handle_crm_command(args)
    elif cmd == "raw":
        handle_raw_command(args)
    elif cmd in ["help", "-h", "--help"]:
        print_usage()
    else:
        die(f"未知命令: {cmd}（尝试 cordys.py help）")


if __name__ == "__main__":
    main()
