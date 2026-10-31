import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError

from form_guard import DATA_SOURCE_LABELS


MARKER_PREFIX = "===FILE:"
MARKER_SUFFIX = "==="
AUTO_START = "<!-- AUTO-GENERATED-START -->"
AUTO_END = "<!-- AUTO-GENERATED-END -->"
SCHEMA_PATH = "references/field-schema.json"
FORM_PATH_TO_SCHEMA_MODULE = {
    "references/forms/lead.md": "lead",
    "references/forms/account.md": "account",
    "references/forms/opportunity.md": "opportunity",
    "references/forms/contact.md": "contact",
    "references/forms/follow.md": "follow",
    "references/forms/follow-plan.md": "follow-plan",
    "references/forms/contract.md": "contract",
    "references/forms/payment-record.md": "contract/payment-record",
    "references/forms/payment-plan.md": "contract/payment-plan",
    "references/forms/invoice.md": "invoice",
    "references/forms/business-title.md": "contract/business-title",
    "references/forms/quotation.md": "opportunity/quotation",
    "references/forms/order.md": "order",
}
EXPECTED_SYNC_PATHS = set(FORM_PATH_TO_SCHEMA_MODULE) | {SCHEMA_PATH}
EXPECTED_SCHEMA_MODULES = set(FORM_PATH_TO_SCHEMA_MODULE.values())


def sync_forms(domain, access_key, secret_key, params=""):
    """
    Cordys CRM 表单同步工具 — 获取所有模块表单配置和产品列表，生成 references 文档内容。

    返回纯文本，用 ===FILE:path=== 分隔各文件内容，供本地 shell 直接写入。
    同一份结构化表单数据同时生成给 AI 阅读的 Markdown 与给 CLI 校验的 field-schema.json。

    Args:
        domain: CRM 域名，如 https://www.cordys.cn
        access_key: 用户的 X-Access-Key
        secret_key: 用户的 X-Secret-Key
        params: JSON 字符串（可选），如 {"modules":["clue","account"]}，不传则同步全部

    Returns:
        纯文本，格式为 ===FILE:references/xxx.md=== 分隔的多文件内容
    """

    try:
        p = json.loads(params) if isinstance(params, str) and params else {}
    except (json.JSONDecodeError, TypeError):
        p = {}

    default_modules = [
        "clue", "account", "opportunity", "contact", "follow", "follow-plan",
        "contract", "payment-record", "contract/payment-plan", "invoice",
        "contract/business-title", "opportunity/quotation", "order",
    ]
    modules = p.get("modules", default_modules)
    if not isinstance(modules, list) or not modules:
        raise ValueError("sync modules 必须是非空数组")
    if len(modules) != len(default_modules) or set(modules) != set(default_modules):
        raise ValueError("sync 必须全量刷新全部模块，避免 field-schema.json 混入其他时间或实例的旧快照")

    FORM_PATH_MAP = {
        "clue": "/lead/module/form",
        "lead": "/lead/module/form",
        "account": "/account/module/form",
        "opportunity": "/opportunity/module/form",
        "contact": "/module/form/config/contact",
        "follow": "/follow/record/module/form",
        "follow-plan": "/follow/plan/module/form",
        "contract": "/contract/module/form",
        "payment-record": "/contract/payment-record/module/form",
        "contract/payment-plan": "/contract/payment-plan/module/form",
        "invoice": "/invoice/module/form",
        "contract/business-title": "/contract/business-title/module/form",
        "opportunity/quotation": "/opportunity/quotation/module/form",
        "order": "/order/module/form",
    }

    MODULE_TO_REF = {
        "clue": "lead", "account": "account",
        "opportunity": "opportunity", "contact": "contact",
        "follow": "follow", "follow-plan": "follow-plan",
        "contract": "contract", "payment-record": "payment-record",
        "contract/payment-plan": "payment-plan", "invoice": "invoice",
        "contract/business-title": "business-title", "opportunity/quotation": "quotation",
        "order": "order",
    }
    VIEW_PATH_MAP = {
        "clue": "/lead/view",
        "account": "/account/view",
        "opportunity": "/opportunity/view",
        "contact": "/account/contact/view",
        "follow": "/follow/record/view",
        "follow-plan": "/follow/plan/view",
        "contract": "/contract/view",
        "payment-record": "/contract/payment-record/view",
        "contract/payment-plan": "/contract/payment-plan/view",
        "invoice": "/invoice/view",
        "contract/business-title": None,
        "opportunity/quotation": "/opportunity/quotation/view",
        "order": "/order/view",
    }
    # Cordys 前端内置视图不会由 /view/list 返回；这里按模块维护稳定 ID 与官方显示名。
    # /view/list 只补充当前实例、当前用户可见的自定义视图。
    BUILTIN_VIEWS = {
        "clue": [
            ("全部线索", "ALL"),
            ("我的线索", "SELF"),
            ("部门线索", "DEPARTMENT"),
        ],
        "account": [
            ("所有客户", "ALL"),
            ("我的客户", "SELF"),
            ("部门客户", "DEPARTMENT"),
            ("协作客户", "CUSTOMER_COLLABORATION"),
        ],
        "opportunity": [
            ("全部商机", "ALL"),
            ("我的商机", "SELF"),
            ("部门商机", "DEPARTMENT"),
            ("成交商机", "OPPORTUNITY_SUCCESS"),
        ],
        "contact": [
            ("全部联系人", "ALL"),
            ("我的联系人", "SELF"),
            ("部门联系人", "DEPARTMENT"),
        ],
        "follow": [
            ("所有记录", "ALL"),
            ("我的记录", "SELF"),
            ("部门记录", "DEPARTMENT"),
        ],
        "follow-plan": [
            ("所有计划", "ALL"),
            ("我的计划", "SELF"),
            ("部门计划", "DEPARTMENT"),
        ],
        "contract": [
            ("所有合同", "ALL"),
            ("我的合同", "SELF"),
            ("部门合同", "DEPARTMENT"),
        ],
        "payment-record": [
            ("所有记录", "ALL"),
            ("我的记录", "SELF"),
            ("部门记录", "DEPARTMENT"),
        ],
        "contract/payment-plan": [
            ("所有计划", "ALL"),
            ("我的计划", "SELF"),
            ("部门计划", "DEPARTMENT"),
        ],
        "invoice": [
            ("所有发票", "ALL"),
            ("我的发票", "SELF"),
            ("部门发票", "DEPARTMENT"),
        ],
        "contract/business-title": [
            ("所有工商抬头", "ALL"),
            ("我的工商抬头", "SELF"),
            ("部门工商抬头", "DEPARTMENT"),
        ],
        "opportunity/quotation": [
            ("所有报价单", "ALL"),
            ("我的报价单", "SELF"),
            ("部门报价单", "DEPARTMENT"),
        ],
        "order": [
            ("所有订单", "ALL"),
            ("我的订单", "SELF"),
            ("部门订单", "DEPARTMENT"),
        ],
    }
    unknown_modules = [module for module in modules if module not in FORM_PATH_MAP]
    if unknown_modules:
        raise ValueError(f"sync 不支持模块：{', '.join(map(str, unknown_modules))}")

    # 样本记录里值为 null 的顶层字段无法靠类型推断发现；这些系统字段是稳定 API 契约，
    # 显式合并可避免 schema 因某条样本恰好为空而漏字段。
    SYSTEM_QUERY_FIELDS = {
        "clue": {
            "stage": "SELECT", "createTime": "DATE_TIME", "updateTime": "DATE_TIME",
            "departmentId": "DEPARTMENT", "owner": "MEMBER", "follower": "MEMBER",
            "followTime": "DATE_TIME", "latestFollowUpTime": "DATE_TIME", "reservedDays": "INPUT_NUMBER",
            "reasonId": "MEMBER",
        },
        "account": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER", "follower": "MEMBER", "followTime": "DATE_TIME",
            "latestFollowUpTime": "DATE_TIME", "reasonId": "MEMBER",
        },
        "opportunity": {
            "stage": "SELECT", "lastStage": "INPUT", "createTime": "DATE_TIME", "updateTime": "DATE_TIME",
            "departmentId": "DEPARTMENT", "owner": "MEMBER", "follower": "MEMBER",
            "followTime": "DATE_TIME", "expectedEndTime": "DATE_TIME", "actualEndTime": "DATE_TIME",
            "stageUpdateTime": "DATE_TIME", "amount": "INPUT_NUMBER",
        },
        "contact": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER",
        },
        "contract": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER", "approvalStatus": "SELECT", "stage": "SELECT",
            "amount": "INPUT_NUMBER", "alreadyPayAmount": "INPUT_NUMBER",
        },
        "payment-record": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER", "recordEndTime": "DATE_TIME", "recordAmount": "INPUT_NUMBER",
        },
        "contract/payment-plan": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER", "planStatus": "SELECT", "planEndTime": "DATE_TIME",
            "planAmount": "INPUT_NUMBER",
        },
        "invoice": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER", "approvalStatus": "SELECT",
        },
        "contract/business-title": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER",
        },
        "opportunity/quotation": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER", "approvalStatus": "SELECT", "amount": "INPUT_NUMBER",
            "untilTime": "DATE_TIME", "opportunityId": "DATA_SOURCE",
        },
        "order": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER", "approvalStatus": "SELECT", "amount": "INPUT_NUMBER",
        },
    }
    SYSTEM_QUERY_OPTIONS = {
        "clue": {
            "stage": [("新建", "NEW")],
        },
        "opportunity": {
            "stage": [
                ("新建", "CREATE"), ("需求确认", "CLEAR_REQUIREMENTS"),
                ("方案验证", "SCHEME_VALIDATION"), ("项目方案汇报", "PROJECT_PROPOSAL_REPORT"),
                ("商务采购", "BUSINESS_PROCUREMENT"), ("赢单", "SUCCESS"), ("输单", "FAIL"),
            ],
        },
        "contract": {
            "stage": [("待签署", "PENDING_SIGNING")],
        },
    }

    SKIP_TYPES = {"MEMBER", "SERIAL_NUMBER", "DIVIDER"}
    NON_QUERYABLE_TYPES = {
        "DIVIDER", "PICTURE", "INDUSTRY", "FORMULA", "SUB_PRODUCT", "SUB_PRICE",
    }
    PARENT_SCOPE_FIELDS = {"customerId", "accountId", "contractId"}
    PARENT_SCOPE_MODULES = {
        "contract", "payment-record", "contract/payment-plan", "invoice",
        "contract/business-title", "opportunity/quotation", "order",
    }
    TYPE_FORMAT = {
        "SELECT": "SELECT", "RADIO": "SELECT",
        "DATA_SOURCE": "⚠️ 实体 ID", "DATA_SOURCE_MULTIPLE": "⚠️ 实体 ID（可多选）",
        "LOCATION": "LOCATION", "INPUT_NUMBER": "数字", "DATE_TIME": "YYYY-MM-DD",
        "PHONE": "手机/电话", "INPUT": "文本", "TEXTAREA": "文本", "INPUT_MULTIPLE": "文本（多值）",
        "ATTACHMENT": "本地文件",
    }

    # 数据源字段的格式列写明要传哪类记录的 ID（如签约客户名要的是工商抬头，不是客户）。
    def field_format(f):
        if f["type"] in ("DATA_SOURCE", "DATA_SOURCE_MULTIPLE"):
            label = DATA_SOURCE_LABELS.get(f.get("dataSourceType") or "", "自定义表单记录")
            many = "（可多选）" if f["type"] == "DATA_SOURCE_MULTIPLE" else ""
            return f"⚠️ {label} ID{many}"
        return TYPE_FORMAT.get(f["type"], "文本")

    def api(method, path, data=None):
        url = f"{domain}{path}"
        headers = {
            "X-Access-Key": access_key,
            "X-Secret-Key": secret_key,
            "X-Request-Source": "SKILL",
            "Content-Type": "application/json;charset=UTF-8",
        }
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
        req = request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode(resp.headers.get_content_charset() or "utf-8")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {"code": 0, "message": f"HTTP {resp.status} 返回非 JSON 响应"}
        except HTTPError as e:
            try:
                body = e.read().decode(e.headers.get_content_charset() or "utf-8")
                return json.loads(body)
            except Exception:
                return {"code": 0}
        except (URLError, TimeoutError, OSError) as exc:
            return {"code": 0, "message": str(exc) or type(exc).__name__}

    # 各模块启用的提交校验规则（formProp.validationRules），写进表单文档。
    submit_rules = {}

    def get_form_fields(form_key):
        path = FORM_PATH_MAP.get(form_key, f"/{form_key}/module/form")
        resp = api("GET", path)
        if resp.get("code") != 100200:
            raise RuntimeError(f"同步 {form_key} 表单失败：{resp.get('message') or resp.get('code') or '无响应'}")
        data = resp.get("data")
        raw_fields = data.get("fields") if isinstance(data, dict) else None
        if not isinstance(raw_fields, list):
            raise RuntimeError(f"同步 {form_key} 表单失败：data.fields 不是数组")
        form_prop = data.get("formProp") if isinstance(data.get("formProp"), dict) else {}
        submit_rules[form_key] = [
            {
                "display": formula_display(rule.get("formula")),
                "message": str(rule.get("message") or "").strip(),
                "allowIgnore": bool(rule.get("allowIgnore")),
            }
            for rule in form_prop.get("validationRules") or []
            if isinstance(rule, dict) and rule.get("enable")
        ]

        def normalize_scope(scope_fields, scope_name):
            """Normalize one field scope while retaining nested subtable ownership."""
            if not isinstance(scope_fields, list):
                raise RuntimeError(f"同步 {form_key} 表单失败：{scope_name} 不是数组")
            raw = [
                field for field in scope_fields
                if isinstance(field, dict) and field.get("type") != "DIVIDER"
            ]

            # 联动规则只在当前字段作用域内解析。不同子表可以有同名、不同 ID 的字段，
            # 不能把所有 subFields 扁平化后再建立映射。
            value_to_label = {}
            for field in raw:
                for option in (field.get("options") or []):
                    if isinstance(option, dict) and "value" in option and "label" in option:
                        value_to_label[option["value"]] = option["label"]

            controlled_by = {}
            for field in raw:
                for rule in (field.get("showControlRules") or []):
                    trigger = value_to_label.get(rule.get("value"), rule.get("value"))
                    for field_id in (rule.get("fieldIds") or []):
                        controlled_by.setdefault(field_id, {}).setdefault(field.get("name") or "", [])
                        if trigger not in controlled_by[field_id][field.get("name") or ""]:
                            controlled_by[field_id][field.get("name") or ""].append(trigger)

            normalized = []
            for field in raw:
                field_id = field.get("id")
                field_name = field.get("name") or ""
                field_type = field.get("type") or ""
                if not field_id or not field_type:
                    raise RuntimeError(
                        f"同步 {form_key} 表单失败：{scope_name} 中字段缺少 id/type"
                    )
                label_to_value = {
                    option["label"]: option["value"]
                    for option in (field.get("options") or [])
                    if isinstance(option, dict) and "label" in option and "value" in option
                }
                required = any(
                    isinstance(rule, dict) and rule.get("key") == "required"
                    for rule in (field.get("rules") or [])
                )
                # 表单默认值：SELECT/RADIO 显示选项标签，供“必填项有默认值直接使用”。
                value_to_option = {value: label for label, value in label_to_value.items()}
                default_value = field.get("defaultValue")
                if isinstance(default_value, list):
                    default_text = "、".join(
                        str(value_to_option.get(item, item))
                        for item in default_value if item not in (None, "")
                    )
                elif default_value not in (None, "") and not isinstance(default_value, dict):
                    default_text = str(value_to_option.get(default_value, default_value))
                else:
                    default_text = "当前用户" if field.get("hasCurrentUser") else ""
                condition = ""
                if required and field_id in controlled_by:
                    parts = []
                    for control_name, triggers in controlled_by[field_id].items():
                        parts.append(f"{control_name}={' / '.join(map(str, triggers))}")
                    condition = "；".join(parts)

                raw_sub_fields = field.get("subFields") or []
                if raw_sub_fields and not isinstance(raw_sub_fields, list):
                    raise RuntimeError(
                        f"同步 {form_key} 表单失败：子表 {field_name or field_id}.subFields 不是数组"
                    )
                # 公式/流水号前缀/带出字段由 CLI（form_guard.py）在提交前生成，文档中单列。
                auto = ""
                if field_type == "FORMULA":
                    auto = "formula"
                elif field_type == "SERIAL_NUMBER" and field.get("prefixType") == "formula":
                    auto = "serial"
                elif field.get("defaultValueType") == "formula" and field.get("formula"):
                    auto = "default"
                elif field.get("resourceFieldId") and "_ref_" in str(field_id):
                    auto = "reference"
                normalized.append({
                    "id": str(field_id),
                    "name": field_name,
                    "auto": auto,
                    "formulaDisplay": formula_display(field.get("formula")) if auto in ("formula", "serial", "default") else "",
                    "resourceName": "",
                    "linkProp": field.get("linkProp") if isinstance(field.get("linkProp"), dict) else None,
                    "linkFields": [
                        link for link in field.get("linkFields") or []
                        if isinstance(link, dict) and link.get("enable") is not False and link.get("method") == "fill"
                    ],
                    "linkNotes": [],
                    "internalKey": field.get("internalKey") or "",
                    "type": field_type,
                    "dataSourceType": str(field.get("dataSourceType") or ""),
                    "businessKey": field.get("businessKey") or "",
                    "resourceFieldId": str(field.get("resourceFieldId") or ""),
                    "subTableFieldId": str(field.get("subTableFieldId") or ""),
                    "required": required,
                    "label_to_value": label_to_value,
                    "condition": condition,
                    "default": default_text,
                    "subFields": normalize_scope(
                        raw_sub_fields, f"子表 {field_name or field_id}.subFields"
                    ) if raw_sub_fields else [],
                })
            names = {item["id"]: item["name"] for item in normalized}
            by_id = {item["id"]: item for item in normalized}
            for item in normalized:
                if item["auto"] == "reference":
                    item["resourceName"] = names.get(item["resourceFieldId"], "")
                item["linkNotes"] = link_notes(item, by_id)
            return normalized

        return normalize_scope(raw_fields, "data.fields")

    def formula_display(raw):
        """公式配置里给人看的写法（display）；解析不了时返回空串。"""
        try:
            spec = json.loads(raw) if isinstance(raw, str) else raw
            return str((spec or {}).get("display") or "")
        except (TypeError, ValueError, AttributeError):
            return ""

    def placement(f):
        """创建请求里这个字段怎么传，规则同网页 saveForm：带出字段不传，有 businessKey 放顶层，其余进 moduleFields。"""
        if f.get("resourceFieldId"):
            parent = f.get("resourceName")
            return f"带出，不传（选定「{parent}」后自动带出）" if parent else "带出，不传"
        if f["type"] == "ATTACHMENT":
            return f"`attachments` 键「{f['name']}」传本地文件"
        if f.get("businessKey"):
            return f"顶层 `{f['businessKey']}`"
        if f["type"] in ("SUB_PRODUCT", "SUB_PRICE"):
            return f"`moduleFields` `{f['id']}`，行数组见子表字段参考"
        return f"`moduleFields` `{f['id']}`"

    def gen_submit_rules(module):
        """表单提交校验规则：CLI 提交前按网页规则计算，未通过不发写请求。"""
        rules = submit_rules.get(module) or []
        if not rules:
            return []
        lines = [
            "",
            "## 提交校验规则",
            "",
            "> 网页提交前逐条计算，结果为假时拦截并提示；`crm create` 同样在发写请求前计算，未通过时列出提示语、不发请求。"
            "「可忽略」的规则须先把提示告诉用户，用户同意后在请求体顶层加 `\"confirmIgnoredRules\": true` 重新提交。",
            "",
        ]
        for rule in rules:
            kind = "可忽略" if rule["allowIgnore"] else "不可忽略"
            formula = f"`{markdown_cell(rule['display'])}`" if rule["display"] else "（无公式说明）"
            lines.append(f"- {formula}，{kind}：{markdown_cell(rule['message'] or '未配置提示语')}")
        lines.append("")
        return lines

    def link_notes(item, by_id):
        """描述网页表单的字段联动（form_guard.py 会在提交前重放）。"""
        notes = []
        link = item.get("linkProp") or {}
        target = by_id.get(str(link.get("targetField") or ""))
        if target:
            labels = {v: k for k, v in item["label_to_value"].items()}
            target_labels = {v: k for k, v in target["label_to_value"].items()}
            auto, ranges = {}, []
            for option in link.get("linkOptions") or []:
                if not isinstance(option, dict):
                    continue
                current = labels.get(option.get("current"), option.get("current"))
                wanted = option.get("target")
                if option.get("method") == "HIDDEN":
                    allowed = wanted if isinstance(wanted, list) else [wanted]
                    ranges.append(
                        f"「{item['name']}」选「{current}」时「{target['name']}」只能选："
                        + "、".join(str(target_labels.get(v, v)) for v in allowed)
                    )
                else:
                    auto.setdefault(str(target_labels.get(wanted, wanted)), []).append(str(current))
            for value, currents in auto.items():
                notes.append(
                    f"「{item['name']}」选「{' / '.join(currents)}」时自动填「{target['name']}」=「{value}」"
                )
            notes.extend(ranges)
        filled = [by_id[str(l.get("current"))]["name"] for l in item.get("linkFields") or [] if str(l.get("current")) in by_id]
        if filled:
            notes.append(f"选定「{item['name']}」后自动填充：{'、'.join(filled)}（未传时从该记录读取）")
        return notes

    def get_custom_views(module):
        path = VIEW_PATH_MAP[module]
        if not path:
            return []
        resp = api("GET", f"{path}/list")
        if resp.get("code") != 100200:
            raise RuntimeError(
                f"同步 {module} 自定义视图失败："
                f"{resp.get('message') or resp.get('code') or '无响应'}"
            )
        data = resp.get("data")
        if not isinstance(data, list):
            raise RuntimeError(f"同步 {module} 自定义视图失败：data 不是数组")
        views = []
        for item in data:
            if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
                raise RuntimeError(f"同步 {module} 自定义视图失败：视图条目缺少 id/name")
            views.append({
                "id": str(item["id"]),
                "name": str(item["name"]),
                "enable": bool(item.get("enable", True)),
                "fixed": bool(item.get("fixed", False)),
            })
        return views

    def markdown_cell(value):
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    def gen_view_catalog(module, custom_views):
        custom_view_note = (
            "实例自定义视图由 `sync` 从对应 `/view/list` 自动刷新。"
            if VIEW_PATH_MAP[module]
            else "当前模块没有可用的 `/view/list`，不生成实例自定义视图。"
        )
        lines = [
            "\n## 视图目录\n",
            f"> `viewId` 按模块选择。官方内置视图由 Cordys 前端定义；{custom_view_note}",
            "> 自定义视图路由：用户明确引用视图，或去掉“看下/查看/查询/列出”等纯查询外壳后与唯一、已启用的视图名称完全一致时，直接使用该 `viewId`；精确命中后不从名称重复构造部门、时间条件。模糊相似仍按字段条件查询。视图不能扩大当前角色的数据范围。\n",
            "### 官方内置视图\n",
            "| 视图名称 | viewId |",
            "|----------|--------|",
        ]
        for name, view_id in BUILTIN_VIEWS[module]:
            lines.append(f"| {name} | `{view_id}` |")

        lines.extend([
            "\n### 实例自定义视图（自动同步）\n",
            "| 视图名称 | viewId | 启用 | 固定 |",
            "|----------|--------|------|------|",
        ])
        if custom_views:
            for view in custom_views:
                lines.append(
                    f"| {markdown_cell(view['name'])} | `{markdown_cell(view['id'])}` | "
                    f"{'是' if view['enable'] else '否'} | {'是' if view['fixed'] else '否'} |"
                )
        else:
            lines.append("| — | — | — | — |")
        lines.append("")
        return "\n".join(lines)

    # 查询字段参考：combineSearch.conditions 可用的 name/type。模块和跟进共用同一段生成逻辑。
    # skip 可覆盖默认过滤类型：跟进的 owner 是 MEMBER 但可用于查询（查"我的/某人的跟进"），
    # 所以 follow 传更宽松的 skip 保留 MEMBER。
    def gen_query_reference(fields, top_level_fields=None, skip=None, excluded_names=None):
        skip = SKIP_TYPES if skip is None else skip
        excluded_names = excluded_names or set()
        lines = []
        queryable = [
            f for f in fields
            if f["type"] not in skip
            and (f.get("businessKey") or f.get("id", f["name"])) not in excluded_names
        ]
        top_level_fields = [
            (name, field_type) for name, field_type in (top_level_fields or [])
            if name not in excluded_names
        ]
        if not queryable and not top_level_fields:
            return lines
        lines.append("\n## 查询字段参考\n")
        lines.append("> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。\n")
        lines.append("> “系统/API”字段可能不显示为自定义表单控件或“表单 SELECT 字段可选值”列表；只要列在本表中，即可作为 conditions 的字段依据。\n")
        lines.append("| 字段 | name（条件用） | type | 来源 |")
        lines.append("|------|--------------|------|------|")
        top_level_names = {name for name, _ in (top_level_fields or [])}
        for name, ftype in (top_level_fields or []):
            lines.append(f"| {name} | {name} | {ftype} | 系统/API |")
        for f in queryable:
            if not str(f.get("name") or "").strip():
                continue
            cond_name = f.get("businessKey") or f.get("id", f["name"])
            # 顶层系统字段优先；表单里可能存在同 businessKey 的公式/展示字段（如 contract.amount）。
            if cond_name in top_level_names:
                continue
            lines.append(f"| {f['name']} | {cond_name} | {f['type']} | 表单 |")
        lines.append("")
        return lines

    def gen_subtable_reference(fields):
        subtables = [
            field for field in fields
            if field["type"] in {"SUB_PRODUCT", "SUB_PRICE"} and field.get("subFields")
        ]
        if not subtables:
            return []

        lines = [
            "\n## 子表字段参考\n",
            "> 子表按父 fieldId 保留层级；不同父子表中的同名字段不是同一个字段，禁止只按名称猜 fieldId。",
            "> 子表字段不能直接放入 `combineSearch.conditions`。更新时外层 `moduleFields.fieldId` 使用父 fieldId，`fieldValue` 传完整行数组；行内保留 `id` 和未修改字段，目标子字段使用下表 fieldId，SELECT/RADIO 使用选项 value。",
            "> 新建时按各子表「新建一行怎么写」构造行，结构以本节为准，**不要读取已有记录来模仿写法**。\n",
        ]
        for parent in subtables:
            parent_name = markdown_cell(parent["name"] or parent["id"])
            parent_id = markdown_cell(parent["id"])
            lines.extend([
                f"### {parent_name}（父 fieldId：`{parent_id}`）\n",
                "| 子字段 | fieldId | businessKey | type | 必填 |",
                "|--------|---------|-------------|------|------|",
            ])
            for child in parent["subFields"]:
                lines.append(
                    f"| {markdown_cell(child['name'] or '—')} | `{markdown_cell(child['id'])}` | "
                    f"{markdown_cell(child.get('businessKey') or '—')} | {markdown_cell(child['type'])} | "
                    f"{'是' if child.get('required') else '否'} |"
                )

            lines.extend(gen_row_recipe(parent))

            select_children = [
                child for child in parent["subFields"]
                if child["type"] in {"SELECT", "RADIO"} and child.get("label_to_value")
            ]
            if select_children:
                lines.append("\nSELECT/RADIO 可选值：")
                for child in select_children:
                    mapping = ", ".join(
                        f"{markdown_cell(label)}=`{markdown_cell(value)}`"
                        for label, value in child["label_to_value"].items()
                    )
                    lines.append(
                        f"- **{markdown_cell(child['name'] or child['id'])}** "
                        f"(`{markdown_cell(child['id'])}`)：{mapping}"
                    )
            lines.append("")
        return lines

    def gen_row_recipe(parent):
        """新建时一行要写哪些键：从子字段配置推出，规则同 form_guard（带出列、公式列由 CLI 生成）。"""
        children = parent["subFields"]
        by_id = {child["id"]: child for child in children}
        refs = {}
        for child in children:
            source = by_id.get(child.get("resourceFieldId") or "")
            if source is not None:
                refs.setdefault(source["id"], []).append(child["name"])
        formulas = [c["name"] for c in children if c["type"] == "FORMULA"]
        to_fill = [
            c for c in children
            if c["required"] and not c.get("resourceFieldId") and c["type"] not in ("FORMULA", "SERIAL_NUMBER")
        ]
        lines = ["", "**新建一行怎么写**（行对象的键用下表 fieldId）："]
        for child in children:
            if child.get("dataSourceType") == "PRICE":
                lines.append(
                    f"- 「{markdown_cell(child['name'])}」`{markdown_cell(child['id'])}`：传价格表 ID（`crm price` 结果的 `catalog_id`），"
                    "同一行再加 `\"price_sub\": \"<price_row_id>\"` 指定价格行。"
                )
        for source_id, names in refs.items():
            lines.append(
                f"- 选定「{markdown_cell(by_id[source_id]['name'])}」后带出，不传：{markdown_cell('、'.join(names))}"
            )
        if to_fill:
            lines.append(
                "- 需要填写：" + markdown_cell("、".join(
                    f"{c['name']}（{'选项 value' if c['type'] in ('SELECT', 'RADIO') else TYPE_FORMAT.get(c['type'], '文本')}）"
                    for c in to_fill
                ))
            )
        if formulas:
            lines.append(f"- 公式列由 CLI 计算，不传：{markdown_cell('、'.join(formulas))}")
        return lines

    def gen_auto_fields(fields):
        """列出 CLI 在提交前自动填充的字段，调用方不传也不向用户索取。"""
        computed = [f for f in fields if f.get("auto") in ("formula", "serial", "default")]
        references = [f for f in fields if f.get("auto") == "reference" and f.get("resourceName")]
        links = [note for f in fields for note in f.get("linkNotes") or []]
        if not computed and not references and not links:
            return []
        lines = [
            "",
            "## CLI 自动生成的字段",
            "",
            "> `crm create` 在发写请求前按实时表单自动补齐下列字段（同网页表单），调用方**不传、也不向用户索取**；"
            "名称类字段若传入且与公式结果不同会被拒绝。公式引用的字段按上方必填表填写：必填的要给，选填的用户没提就留空、不追问。"
            "负责人/所有人未指定时取当前用户。提交前还会按表单校验全部必填项（含条件必填），缺项一次列出、不发请求。",
            "",
        ]
        for f in computed:
            rule = f"：`{markdown_cell(f['formulaDisplay'])}`" if f.get("formulaDisplay") else ""
            if f["auto"] == "serial":
                lines.append(f"- **{markdown_cell(f['name'])}**（编号前缀公式，后端按前缀生成流水号）{rule}")
            elif f["auto"] == "default":
                lines.append(f"- **{markdown_cell(f['name'])}**（按公式拼接）{rule}")
            else:
                lines.append(f"- **{markdown_cell(f['name'])}**（计算公式）{rule}")
        if references:
            grouped = {}
            for f in references:
                grouped.setdefault(f["resourceName"], []).append(f["name"])
            for parent, names in grouped.items():
                lines.append(
                    f"- 选定「{markdown_cell(parent)}」后自动带出：{markdown_cell('、'.join(names))}（未传时从该记录读取）"
                )
        if links:
            lines.append("")
            lines.append("**表单联动**（未传时由 CLI 按联动填充，传入值优先；可选范围不符会被拒绝）：")
            lines.append("")
            lines.extend(f"- {markdown_cell(note)}" for note in links)
        lines.append("")
        return lines

    def gen_module_snippet(fields, product_names=None, module="", top_level_fields=None):
        auto_ids = {f["id"] for f in fields if f.get("auto") in ("formula", "serial", "default")}
        required = [f for f in fields if f["type"] not in SKIP_TYPES and f["required"] and f["id"] not in auto_ids]
        optional = [f for f in fields if f["type"] not in SKIP_TYPES and not f["required"] and f["id"] not in auto_ids]
        has_cond = any(f.get("condition") for f in required)
        has_default = any(f.get("default") for f in required)
        header = ["#", "字段", "怎么传", "格式"]
        rule = ["---", "------", "----------", "------"]
        if has_cond:
            header.append("条件必填")
            rule.append("---------")
        if has_default:
            header.append("表单默认值")
            rule.append("-------")
        lines = ["", f"| {' | '.join(header)} |", f"|{'|'.join(rule)}|"]
        for i, f in enumerate(required, 1):
            cells = [str(i), markdown_cell(f["name"]), markdown_cell(placement(f)), field_format(f)]
            if has_cond:
                cells.append(f.get("condition") or "—")
            if has_default:
                cells.append(f.get("default") or "—")
            lines.append(f"| {' | '.join(cells)} |")
        if optional:
            listed = "、".join(f"{f['name']}（{placement(f)}）" for f in optional)
            lines.append(f"\n选填：{markdown_cell(listed)}\n")
        lines.append(
            "\n> 「怎么传」同网页提交：有 businessKey 的字段放请求体顶层，其余放 `moduleFields`（`fieldId` + `fieldValue`）；"
            "随关联记录带出的字段只用于计算和校验，不提交。单选数据源/成员传单个 ID，多选传数组；下拉传选项 value。\n"
        )
        if has_cond:
            lines.append("\n> 「条件必填」列非「—」的字段，仅当满足条件时才必填；不满足时可留空。\n")
        if has_default:
            lines.append("\n> 「表单默认值」取自实时表单配置；创建时用户未指定的字段直接写入该默认值，并在确认表中列出、可改。\n")
        lines.extend(gen_auto_fields(fields))
        lines.extend(gen_submit_rules(module))

        # 追加 SELECT 字段可选值
        select_fields = [f for f in fields if f["type"] in ("SELECT", "RADIO") and f.get("label_to_value")]
        if select_fields or product_names:
            lines.append("\n## 表单 SELECT 字段可选值\n")
            lines.append("> **创建和查询都传 ID**：标注「传 ID」的字段，中文与 ID 不一致，必须填 `=` 右侧的 ID（填中文会静默失败——创建写空、查询返回空）；未标注的字段中文即 ID，直接传中文即可。")
            lines.append("> 创建时 SELECT 字段按上表「怎么传」放置（多数在 `moduleFields` 的 `fieldValue`）、产品放 `products`；查询时放 `combineSearch.conditions` 的 `value`。\n")
            lines.append("> 本节只列自定义表单字段；系统/API 的 SELECT 字段以“查询字段参考”为准。\n")
            for f in select_fields:
                pairs = f["label_to_value"]
                differ = any(label != value for label, value in pairs.items())
                if differ:
                    mapping = ", ".join(f"{label}={value}" for label, value in pairs.items())
                    lines.append(f"- **{f['name']}**（传 ID）：{mapping}")
                else:
                    lines.append(f"- **{f['name']}**：{', '.join(pairs.keys())}")
            if product_names:
                lines.append(f"- **产品类型（可多选）**（传 ID）：{', '.join(product_names)}")
            lines.append("")

        # 子表必须保留父子关系；不能把同名子字段混入顶层 SELECT 或查询字段表。
        lines.extend(gen_subtable_reference(fields))

        # 追加查询字段参考（combineSearch.conditions 可用的 name 和 type）
        excluded_names = PARENT_SCOPE_FIELDS if module in PARENT_SCOPE_MODULES else set()
        lines.extend(gen_query_reference(fields, top_level_fields, excluded_names=excluded_names))

        return "\n".join(lines)

    def gen_follow_snippet(fields):
        # 跟进表单结构视图：自动同步整张表单字段表（名称/businessKey/类型/必填）。
        # ⚠️ 这是「表单字段」结构，与写入 API 参数不一一对应（写入端有 module 注入、
        # 记录 ID 按模块取 clueId/customerId/opportunityId 等语义），写入参数视图由
        # follow.md 中手写的「必填字段清单」维护，sync 不覆盖。
        # 注：不套用 SKIP_TYPES——owner 是 MEMBER 类型但属跟进必填写入字段，需保留；
        # 仅过滤无展示意义的 SERIAL_NUMBER / DIVIDER。
        FOLLOW_SKIP = {"SERIAL_NUMBER", "DIVIDER"}
        real = [f for f in fields if f["type"] not in FOLLOW_SKIP]

        # 1) 全量表单字段表
        lines = ["", "| 字段 | businessKey | 类型 | 必填 |", "|------|------------|------|------|"]
        for f in real:
            bk = f.get("businessKey") or "—"
            req = "是" if f.get("required") else "否"
            lines.append(f"| {f['name']} | {bk} | {f['type']} | {req} |")

        # 2) 选填自定义字段（无 businessKey 的字段，如意向产品）——给出写入键名与格式
        custom = [f for f in real if not f.get("businessKey")]
        if custom:
            lines.append("\n## 选填自定义字段\n")
            lines.append("| 字段 | JSON 键名 | 格式 | 说明 |")
            lines.append("|------|----------|------|------|")
            for f in custom:
                lines.append(f"| {f['name']} | {f['name']} | {TYPE_FORMAT.get(f['type'], '文本')} | |")

        # 3) 跟进方式可选值（记录表单 businessKey=followMethod，计划表单 businessKey=method）
        method_fields = [f for f in fields if f.get("businessKey") in ("followMethod", "method") and f.get("label_to_value")]
        if method_fields:
            lines.append("\n## 跟进方式可选值\n")
            for f in method_fields:
                for label, value in f["label_to_value"].items():
                    lines.append(f"- `{value}` = {label}")
            lines.append("")

        # 查询字段参考（跟进列表走全局 /follow/{record|plan}/page；
        # 保留资源 DATA_SOURCE 字段及 MEMBER 类型 owner 供范围筛选）
        lines.extend(gen_query_reference(fields, skip={"SERIAL_NUMBER", "DIVIDER"}))

        return "\n".join(lines)

    # Fetch all forms. A module is one independent snapshot unit: if either its
    # form or custom-view endpoint fails, retain that module's last local
    # snapshot while continuing to fetch and generate every other module.
    all_fields = {}
    all_custom_views = {}
    failed_modules = {}
    for m in modules:
        try:
            fields = get_form_fields(m)
            custom_views = get_custom_views(m)
        except Exception as exc:
            failed_modules[m] = f"{type(exc).__name__}: {exc}"
            print(
                f"警告: {m} 表单/视图同步失败，保留本地旧快照并继续："
                f"{failed_modules[m]}",
                file=sys.stderr,
            )
            continue
        all_fields[m] = fields
        all_custom_views[m] = custom_views

    successful_modules = [m for m in modules if m in all_fields]
    if not successful_modules:
        first_module = modules[0]
        raise RuntimeError(
            "全部模块表单/视图同步失败，未生成空快照；"
            f"首个错误：{failed_modules.get(first_module, '未知错误')}"
        )
    if failed_modules:
        print(
            f"警告: 本次同步成功 {len(successful_modules)} 个模块，"
            f"失败 {len(failed_modules)} 个模块；失败模块不会覆盖本地旧快照。",
            file=sys.stderr,
        )

    # Fetch product list（保留 name=id，供创建时 products 字段直接取 ID，免去每次查 crm product）
    prod_resp = api("POST", "/field/source/product", {"current": 1, "pageSize": 200, "keyword": ""})
    product_names = [f'{item["name"]}={item["id"]}' for item in prod_resp.get("data", {}).get("list", [])] if prod_resp.get("code") == 100200 else []

    # Fetch top-level API fields for each module (from one sample record)
    PAGE_PATH_MAP = {
        "clue": "lead", "account": "account", "opportunity": "opportunity",
        "contact": "account/contact", "contract": "contract",
        "payment-record": "contract/payment-record", "contract/payment-plan": "contract/payment-plan",
        "invoice": "invoice", "contract/business-title": "contract/business-title",
        "opportunity/quotation": "opportunity/quotation", "order": "order",
    }
    SKIP_TOP_KEYS = {"id", "organizationId", "moduleFields", "inCustomerPool", "poolId",
                     "customerId", "accountId", "contractId",
                     "inSharedPool", "collectionTime", "transitionType", "transitionId"}
    # 展示用字段（不能用于 condition 过滤）
    SKIP_TOP_SUFFIXES = ("Name", "User")

    ENUM_KEY_NAMES = {"stage", "status", "type", "approvalStatus"}

    def infer_type(key, value):
        # 按字段名规则优先判定
        if key in ENUM_KEY_NAMES:
            return "SELECT"
        if key in ("owner", "follower"):
            return "MEMBER"
        if key == "departmentId":
            return "DEPARTMENT"
        if key.endswith("Id"):
            return "DATA_SOURCE"
        if "Time" in key or "Date" in key or "time" in key:
            return "DATE_TIME"
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            if value > 1e12:
                return "DATE_TIME"
            return "INPUT_NUMBER"
        if isinstance(value, str):
            return "INPUT"
        return None

    def get_top_level_fields(module_key):
        page_module = PAGE_PATH_MAP.get(module_key, module_key)
        resp = api("POST", f"/{page_module}/page", {"current": 1, "pageSize": 1, "viewId": "ALL"})
        explicit = SYSTEM_QUERY_FIELDS.get(module_key, {})
        if resp.get("code") != 100200:
            return list(explicit.items())
        items = resp.get("data", {}).get("list", [])
        if not items:
            return list(explicit.items())
        record = items[0]
        # 表单字段的 businessKey 集合（已在表单列表里了，避免重复）
        form_biz_keys = {f.get("businessKey") for f in all_fields.get(module_key, []) if f.get("businessKey")}
        result = dict(explicit)
        for key, value in record.items():
            if key in SKIP_TOP_KEYS or key in form_biz_keys:
                continue
            if any(key.endswith(s) for s in SKIP_TOP_SUFFIXES):
                continue
            if isinstance(value, (list, dict)):
                continue
            ftype = infer_type(key, value)
            if ftype:
                result.setdefault(key, ftype)
        return list(result.items())

    # Build output
    output_parts = []
    field_schema = {"schemaVersion": 1, "modules": {}}

    # Module reference snippets (with SELECT options and products inlined)
    # 判断哪些模块有产品字段
    modules_with_products = set()
    for m in successful_modules:
        for f in all_fields[m]:
            if "产品" in f["name"] and f["type"] in ("DATA_SOURCE", "DATA_SOURCE_MULTIPLE"):
                modules_with_products.add(m)
                break

    for m in successful_modules:
        ref_name = MODULE_TO_REF.get(m, m)
        if m in ("follow", "follow-plan"):
            snippet = gen_follow_snippet(all_fields[m])
        else:
            prods = product_names if m in modules_with_products else None
            top_fields = get_top_level_fields(m)
            snippet = gen_module_snippet(all_fields[m], prods, module=m, top_level_fields=top_fields)
        snippet = f"{snippet.rstrip()}\n{gen_view_catalog(m, all_custom_views[m]).rstrip()}\n"
        # schema 与 Markdown 共用 all_fields/top_fields，避免反向解析 Markdown。
        # 字段 key 与 conditions.name 完全一致：businessKey 优先，否则用 fieldId。
        schema_fields = {}
        excluded_names = PARENT_SCOPE_FIELDS if m in PARENT_SCOPE_MODULES else set()
        for name, field_type in (top_fields if m not in ("follow", "follow-plan") else []):
            if name in excluded_names:
                continue
            schema_fields[name] = {
                "label": name, "type": field_type, "queryable": field_type not in NON_QUERYABLE_TYPES,
                "options": [
                    {"label": label, "value": value}
                    for label, value in SYSTEM_QUERY_OPTIONS.get(m, {}).get(name, [])
                ],
            }
        for field in all_fields[m]:
            if not str(field.get("name") or "").strip():
                continue
            condition_name = field.get("businessKey") or field.get("id", field["name"])
            if condition_name in excluded_names:
                continue
            # 显式系统字段来自稳定 API 契约，优先于表单中可能重名的公式/展示字段。
            if condition_name in schema_fields:
                continue
            field_entry = {
                "label": field["name"],
                "type": field["type"],
                "queryable": field["type"] not in NON_QUERYABLE_TYPES,
                "options": [
                    {"label": label, "value": value}
                    for label, value in field.get("label_to_value", {}).items()
                ],
            }
            if field.get("subFields"):
                field_entry["subFields"] = {
                    child["id"]: {
                        "fieldId": child["id"],
                        "label": child["name"],
                        "internalKey": child.get("internalKey") or "",
                        "businessKey": child.get("businessKey") or "",
                        "resourceFieldId": child.get("resourceFieldId") or "",
                        "subTableFieldId": child.get("subTableFieldId") or "",
                        "type": child["type"],
                        "required": bool(child.get("required")),
                        "queryable": False,
                        "options": [
                            {"label": label, "value": value}
                            for label, value in child.get("label_to_value", {}).items()
                        ],
                    }
                    for child in field["subFields"]
                }
            schema_fields[condition_name] = field_entry
        schema_module = {"clue": "lead", "payment-record": "contract/payment-record"}.get(m, m)
        field_schema["modules"][schema_module] = {
            "source": FORM_PATH_MAP.get(m, f"/{m}/module/form"),
            "fields": schema_fields,
        }

        output_parts.append(f"===FILE:references/forms/{ref_name}.md===")
        output_parts.append(snippet)

    output_parts.append("===FILE:references/field-schema.json===")
    output_parts.append(json.dumps(field_schema, ensure_ascii=False, indent=2, sort_keys=True))

    return "\n".join(output_parts)


def _parse_sync_sections(content):
    sections = {}
    current = None
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.splitlines():
        if line.startswith(MARKER_PREFIX) and line.endswith(MARKER_SUFFIX):
            relpath = line[len(MARKER_PREFIX):-len(MARKER_SUFFIX)]
            if relpath not in EXPECTED_SYNC_PATHS:
                raise ValueError(f"同步输出包含未授权路径：{relpath}")
            if relpath in sections:
                raise ValueError(f"同步输出包含重复文件段：{relpath}")
            sections[relpath] = []
            current = relpath
            continue
        if current is None:
            if line.strip():
                raise ValueError("同步输出在首个文件标记前包含意外内容")
            continue
        sections[current].append(line)

    if SCHEMA_PATH not in sections:
        raise ValueError(f"同步输出缺少必需文件段：{SCHEMA_PATH}")
    return {relpath: "\n".join(lines) for relpath, lines in sections.items()}


def _replace_auto_section(original, snippet, relpath):
    if original.count(AUTO_START) != 1 or original.count(AUTO_END) != 1:
        raise ValueError(f"{relpath} 的 AUTO-GENERATED 标记缺失或重复")
    start = original.index(AUTO_START) + len(AUTO_START)
    end = original.index(AUTO_END, start)
    return f"{original[:start]}\n{snippet.strip()}\n{original[end:]}"


def _write_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _sync_lock(project_dir, timeout=30):
    """Serialize only the local commit phase; API fetching can still happen in parallel."""
    lock_id = hashlib.sha256(str(project_dir).encode("utf-8")).hexdigest()[:20]
    lock_path = Path(tempfile.gettempdir()) / f"cordys-crm-sync-{lock_id}.lock"
    lock_file = lock_path.open("a+b")
    deadline = time.monotonic() + timeout
    locked = False
    try:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        while not locked:
            try:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("等待另一个表单同步完成超时")
                time.sleep(0.1)
        yield
    finally:
        if locked:
            try:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        lock_file.close()


def apply_sync_output(project_dir, content):
    """Merge successful module snapshots and atomically retain failed modules."""
    project_dir = Path(project_dir).resolve()
    references_dir = project_dir / "references"
    forms_dir = references_dir / "forms"
    if not references_dir.is_dir() or not forms_dir.is_dir():
        raise ValueError(f"同步目标目录无效：{project_dir}")

    sections = _parse_sync_sections(content)
    incoming_schema = json.loads(sections[SCHEMA_PATH])
    if incoming_schema.get("schemaVersion") != 1 or not isinstance(incoming_schema.get("modules"), dict):
        raise ValueError("field-schema.json 缺少 schemaVersion=1 或 modules 对象")
    actual_modules = set(incoming_schema["modules"])
    generated_form_paths = set(sections) - {SCHEMA_PATH}
    expected_modules = {
        FORM_PATH_TO_SCHEMA_MODULE[relpath] for relpath in generated_form_paths
    }
    if actual_modules != expected_modules:
        raise ValueError(
            "field-schema.json 模块集合不完整或与本次成功表单不一致："
            f"表单={sorted(expected_modules)}；schema={sorted(actual_modules)}"
        )

    with _sync_lock(project_dir):
        rendered = {}
        effective_modules = set()
        for relpath in sorted(generated_form_paths):
            snippet = sections[relpath]
            target = project_dir / Path(relpath)
            try:
                target.relative_to(project_dir)
            except ValueError as exc:
                raise ValueError(f"同步目标越界：{relpath}") from exc

            module_name = FORM_PATH_TO_SCHEMA_MODULE[relpath]
            try:
                if not target.is_file():
                    raise FileNotFoundError(f"同步目标不存在：{target}")
                original = target.read_text(encoding="utf-8-sig")
                rendered[relpath] = _replace_auto_section(
                    original, snippet, relpath
                ).encode("utf-8")
            except (OSError, UnicodeError, ValueError) as exc:
                print(
                    f"警告: {module_name} 本地表单无法更新，保留其旧 schema "
                    f"并继续其他模块：{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue
            effective_modules.add(module_name)

        schema_target = project_dir / SCHEMA_PATH
        try:
            local_schema = json.loads(schema_target.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"无法读取本地 field-schema.json：{exc}") from exc
        if local_schema.get("schemaVersion") != 1 or not isinstance(local_schema.get("modules"), dict):
            raise ValueError("本地 field-schema.json 缺少 schemaVersion=1 或 modules 对象")
        merged_schema = dict(local_schema)
        merged_modules = dict(local_schema["modules"])
        merged_modules.update(
            {
                module_name: incoming_schema["modules"][module_name]
                for module_name in effective_modules
            }
        )
        merged_schema["schemaVersion"] = 1
        merged_schema["modules"] = merged_modules
        rendered[SCHEMA_PATH] = (
            json.dumps(merged_schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

        stage_dir = Path(tempfile.mkdtemp(prefix=".sync-stage-", dir=str(references_dir)))
        backup_dir = stage_dir / "backups"
        ready_dir = stage_dir / "ready"
        targets = []
        committed = []
        stamp = forms_dir / ".last_sync"
        stamp_backup = None
        stamp_existed = stamp.exists()

        try:
            for relpath in sorted(rendered):
                target = project_dir / Path(relpath)
                ready = ready_dir / Path(relpath)
                backup = backup_dir / Path(relpath)
                _write_bytes(ready, rendered[relpath])
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                targets.append((relpath, target, ready, backup))

            if stamp_existed:
                stamp_backup = backup_dir / "references" / "forms" / ".last_sync"
                stamp_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(stamp, stamp_backup)

            for relpath, target, ready, backup in targets:
                committed.append((relpath, target, backup))
                os.replace(ready, target)

            stamp_ready = ready_dir / "references" / "forms" / ".last_sync"
            _write_bytes(stamp_ready, f"{int(time.time())}\n".encode("ascii"))
            os.replace(stamp_ready, stamp)
        except BaseException as apply_error:
            rollback_errors = []
            for relpath, target, backup in reversed(committed):
                try:
                    os.replace(backup, target)
                except Exception as exc:
                    rollback_errors.append(f"{relpath}: {exc}")
            try:
                if stamp_existed and stamp_backup is not None and stamp_backup.exists():
                    os.replace(stamp_backup, stamp)
                elif not stamp_existed and stamp.exists():
                    stamp.unlink()
            except Exception as exc:
                rollback_errors.append(f".last_sync: {exc}")
            if rollback_errors:
                raise RuntimeError(
                    "同步失败且回滚不完整：" + "；".join(rollback_errors)
                ) from apply_error
            raise
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)

    return {
        "updatedModules": sorted(effective_modules),
        "retainedModules": sorted(EXPECTED_SCHEMA_MODULES - effective_modules),
    }
