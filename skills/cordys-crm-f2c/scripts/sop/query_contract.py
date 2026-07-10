"""Cordys CRM 查询条件的确定性契约校验。

本模块只验证技术事实：字段、字段类型、操作符和值形状是否与表单元数据一致。
它不猜测“本周回款”“进行中商机”等业务语义，也不自动改写用户意图。
"""

from __future__ import annotations

import json
from pathlib import Path
import sys


class QueryContractError(ValueError):
    """查询在联网前即可确定为非法。"""


TYPE_OPERATORS = {
    "INPUT": {"EQUALS", "NOT_EQUALS", "CONTAINS", "NOT_CONTAINS", "EMPTY", "NOT_EMPTY"},
    "TEXTAREA": {"EQUALS", "NOT_EQUALS", "CONTAINS", "NOT_CONTAINS", "EMPTY", "NOT_EMPTY"},
    "PHONE": {"EQUALS", "NOT_EQUALS", "CONTAINS", "NOT_CONTAINS", "EMPTY", "NOT_EMPTY"},
    "LINK": {"EQUALS", "NOT_EQUALS", "CONTAINS", "NOT_CONTAINS", "EMPTY", "NOT_EMPTY"},
    "SERIAL_NUMBER": {"EQUALS", "NOT_EQUALS", "CONTAINS", "NOT_CONTAINS", "EMPTY", "NOT_EMPTY"},
    "INPUT_NUMBER": {"EQUALS", "NOT_EQUALS", "GT", "LT", "GE", "LE"},
    "ATTACHMENT": {"CONTAINS", "NOT_CONTAINS", "EMPTY", "NOT_EMPTY"},
    "DATE_TIME": {"BETWEEN", "GT", "LT", "EMPTY", "NOT_EMPTY", "DYNAMICS"},
    "TIME_RANGE_PICKER": {"DYNAMICS"},
    "INPUT_MULTIPLE": {"COUNT_LT", "COUNT_GT", "CONTAINS", "NOT_CONTAINS", "EMPTY", "NOT_EMPTY"},
    "RADIO": {"IN", "NOT_IN", "EMPTY", "NOT_EMPTY"},
    "SELECT": {"IN", "NOT_IN", "EMPTY", "NOT_EMPTY"},
    "CHECKBOX": {"IN", "NOT_IN", "EMPTY", "NOT_EMPTY"},
    "MEMBER": {"IN", "NOT_IN", "EMPTY", "NOT_EMPTY"},
    "DEPARTMENT": {"IN", "NOT_IN", "EMPTY", "NOT_EMPTY"},
    "TREE_SELECT": {"IN", "NOT_IN", "EMPTY", "NOT_EMPTY"},
    "DATA_SOURCE": {"IN", "NOT_IN", "EMPTY", "NOT_EMPTY"},
    "SELECT_MULTIPLE": {"IN", "NOT_IN", "EMPTY", "NOT_EMPTY"},
    "MEMBER_MULTIPLE": {"IN", "NOT_IN", "EMPTY", "NOT_EMPTY"},
    "DEPARTMENT_MULTIPLE": {"IN", "NOT_IN", "EMPTY", "NOT_EMPTY"},
    "DATA_SOURCE_MULTIPLE": {"IN", "NOT_IN", "EMPTY", "NOT_EMPTY"},
    "LOCATION": {"IN", "NOT_IN", "EMPTY", "NOT_EMPTY"},
}

ENUM_TYPES = {
    "RADIO", "SELECT", "CHECKBOX", "MEMBER", "DEPARTMENT", "TREE_SELECT",
    "DATA_SOURCE", "SELECT_MULTIPLE", "MEMBER_MULTIPLE", "DEPARTMENT_MULTIPLE",
    "DATA_SOURCE_MULTIPLE", "LOCATION",
}

STATIC_OPTION_TYPES = {"RADIO", "SELECT", "CHECKBOX", "SELECT_MULTIPLE"}

DYNAMIC_VALUES = {
    "TODAY", "YESTERDAY", "WEEK", "LAST_WEEK", "MONTH", "LAST_MONTH",
    "QUARTER", "LAST_QUARTER", "YEAR", "LAST_YEAR", "LAST_SEVEN", "LAST_THIRTY",
}

NON_QUERYABLE_TYPES = {"DIVIDER", "PICTURE", "INDUSTRY", "FORMULA", "SUB_PRODUCT", "SUB_PRICE"}

MODULE_ALIASES = {
    "clue": "lead",
    "account/contact": "contact",
    "payment-record": "contract/payment-record",
    "pool/lead": "lead",
    "pool/account": "account",
}

POST_SIGNING_MODULES = {
    "contract", "invoice", "order", "contract/payment-record", "contract/payment-plan",
    "contract/business-title", "opportunity/quotation",
}

# 已知存在但暂未同步表单 schema 的只读二级模块；只允许无 conditions 的关键词/分页请求。
STRUCTURE_ONLY_MODULES = {
    "invoice", "order", "contract/payment-plan", "contract/business-title",
    "opportunity/quotation",
}


def _load_schema(schema_path):
    if not schema_path:
        return {}
    path = Path(schema_path)
    if not path.is_file():
        raise QueryContractError(f"字段 schema 不存在：{path}；请重新部署技能或执行 cordys_ext.sh sync")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueryContractError(f"字段 schema 无法读取：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("modules"), dict):
        raise QueryContractError("字段 schema 格式无效：缺少 modules 对象")
    return data


def _warn(message):
    print(f"⚠️ 查询契约提示：{message}", file=sys.stderr)


def _module_schema(schema, module):
    canonical = MODULE_ALIASES.get(module, module)
    value = (schema.get("modules") or {}).get(canonical)
    return value if isinstance(value, dict) else None


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_millisecond(value, allow_zero=False):
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    if allow_zero and value == 0:
        return True
    return 100_000_000_000 <= value <= 9_999_999_999_999


def _expected_request_types(field_type, operator):
    if field_type == "DATE_TIME" and operator == "DYNAMICS":
        return {"TIME_RANGE_PICKER"}
    if field_type in {"DEPARTMENT", "DEPARTMENT_MULTIPLE"}:
        return {field_type, "TREE_SELECT"}
    return {field_type}


def _validate_value(condition, prefix, canonical_type):
    operator = condition["operator"]
    has_value = "value" in condition
    value = condition.get("value")

    if operator in {"EMPTY", "NOT_EMPTY"}:
        if has_value and value not in (None, ""):
            raise QueryContractError(f"{prefix}.{operator} 不应携带非 null 的 value")
        condition.pop("value", None)
        return
    if not has_value:
        raise QueryContractError(f"{prefix}.value 必填")

    if operator in {"IN", "NOT_IN"}:
        if not isinstance(value, list) or not value:
            raise QueryContractError(f"{prefix}.{operator} 的 value 必须是非空 JSON 数组")
        if any(isinstance(item, (dict, list)) or item is None for item in value):
            raise QueryContractError(f"{prefix}.{operator} 的数组元素必须是标量")
        if any(isinstance(item, bool) or item == "" for item in value):
            raise QueryContractError(f"{prefix}.{operator} 的数组元素不能是布尔值或空字符串")
    elif operator == "BETWEEN":
        if not isinstance(value, list) or len(value) != 2:
            raise QueryContractError(f"{prefix}.BETWEEN 的 value 必须是两个毫秒时间戳")
        if not all(_is_millisecond(item, allow_zero=True) for item in value):
            raise QueryContractError(f"{prefix}.BETWEEN 只接受 JSON 整数毫秒时间戳，不能传日期字符串或秒级时间戳")
        if value[0] > value[1]:
            raise QueryContractError(f"{prefix}.BETWEEN 起始时间不能晚于结束时间")
    elif operator == "DYNAMICS":
        if not isinstance(value, str) or value not in DYNAMIC_VALUES:
            allowed = ",".join(sorted(DYNAMIC_VALUES))
            raise QueryContractError(f"{prefix}.DYNAMICS 只接受时间常量字符串：{allowed}")
    elif canonical_type == "DATE_TIME" and operator in {"GT", "LT"}:
        if not _is_millisecond(value, allow_zero=True):
            raise QueryContractError(f"{prefix}.{operator} 的日期值必须是 JSON 整数毫秒时间戳")
    elif canonical_type == "INPUT_NUMBER" and not _is_number(value):
        raise QueryContractError(f"{prefix}.{operator} 的数值字段 value 必须是 JSON 数字")
    elif canonical_type == "INPUT_MULTIPLE" and operator in {"COUNT_GT", "COUNT_LT"}:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise QueryContractError(f"{prefix}.{operator} 的数量必须是非负 JSON 整数")
    elif operator in {"CONTAINS", "NOT_CONTAINS"} and not isinstance(value, str):
        raise QueryContractError(f"{prefix}.{operator} 的 value 必须是字符串")
    elif canonical_type in {"INPUT", "TEXTAREA", "PHONE", "LINK", "SERIAL_NUMBER"}:
        if not isinstance(value, str):
            raise QueryContractError(f"{prefix}.{operator} 的文本字段 value 必须是字符串")


def _validate_options(condition, field_meta, prefix):
    options = field_meta.get("options")
    if not isinstance(options, list) or not options:
        return
    allowed = {item.get("value") for item in options if isinstance(item, dict) and "value" in item}
    labels = {
        item.get("label"): item.get("value")
        for item in options
        if isinstance(item, dict) and item.get("label") is not None and "value" in item
    }
    values = condition.get("value") if isinstance(condition.get("value"), list) else []
    invalid = [value for value in values if value not in allowed]
    if not invalid:
        return
    suggestions = [f"{value}→{labels[value]}" for value in invalid if value in labels]
    suffix = f"；应传选项 value：{', '.join(suggestions)}" if suggestions else ""
    raise QueryContractError(f"{prefix}.value 含未知选项 {invalid}{suffix}")


def validate_payload(module, payload, schema_path=None):
    """校验并返回可发送的 payload；只做无歧义的结构归一化。"""
    if not isinstance(payload, dict):
        raise QueryContractError("查询 payload 顶层必须是 JSON 对象")

    if module in POST_SIGNING_MODULES and any(key in payload for key in ("customerId", "accountId")):
        raise QueryContractError(
            f"{module} 的 customerId/accountId 顶层过滤会被后端静默忽略；"
            "请改用 crm acct-sub 按客户维度查询"
        )

    filters = payload.get("filters", [])
    if filters is None:
        payload["filters"] = []
    elif not isinstance(filters, list):
        raise QueryContractError("filters 必须是数组")
    elif filters:
        raise QueryContractError(
            "filters 无字段类型契约，可能绕过查询校验；请改用 combineSearch.conditions"
        )

    combine_search = payload.get("combineSearch")
    if combine_search is None:
        combine_search = {"searchMode": "AND", "conditions": []}
        payload["combineSearch"] = combine_search
    if not isinstance(combine_search, dict):
        raise QueryContractError("combineSearch 必须是 JSON 对象")
    combine_search.setdefault("searchMode", "AND")
    if combine_search["searchMode"] not in {"AND", "OR"}:
        raise QueryContractError("combineSearch.searchMode 只允许 AND 或 OR")
    conditions = combine_search.setdefault("conditions", [])
    if not isinstance(conditions, list):
        raise QueryContractError("combineSearch.conditions 必须是数组")

    schema = _load_schema(schema_path)
    module_meta = _module_schema(schema, module)
    fields = module_meta.get("fields", {}) if module_meta else {}
    if schema and not module_meta:
        if module not in STRUCTURE_ONLY_MODULES:
            raise QueryContractError(
                f"未知查询模块 {module}；禁止调用未确认的 /{module}/page 端点，"
                "请核对 core/cli-spec.md 的模块列表"
            )
        if conditions:
            raise QueryContractError(
                f"模块 {module} 尚未纳入字段 schema，不能验证非空 conditions；"
                "请先执行 cordys_ext.sh sync 或改用已支持模块"
            )
        _warn(f"模块 {module} 尚未纳入字段 schema；当前无 conditions，仅执行通用结构校验")

    for index, condition in enumerate(conditions):
        prefix = f"combineSearch.conditions[{index}]"
        if not isinstance(condition, dict):
            raise QueryContractError(f"{prefix} 必须是 JSON 对象")
        if "field" in condition:
            field = condition.get("field")
            name = condition.get("name")
            if name not in (None, "") and name != field:
                raise QueryContractError(f"{prefix}.field 与 name 冲突，请只保留 name")
            condition["name"] = field
            condition.pop("field", None)
        for key in ("name", "operator", "type"):
            if not isinstance(condition.get(key), str) or not condition[key].strip():
                raise QueryContractError(f"{prefix}.{key} 必填且必须是非空字符串")

        name = condition["name"]
        operator = condition["operator"]
        request_type = condition["type"]
        if operator != operator.upper():
            raise QueryContractError(f"{prefix}.operator 必须使用大写枚举值")
        if request_type not in TYPE_OPERATORS:
            raise QueryContractError(f"{prefix}.type={request_type} 不是可查询字段类型")

        field_meta = fields.get(name) if isinstance(fields, dict) else None
        if module_meta and not field_meta:
            raise QueryContractError(
                f"{prefix}.name={name} 不在 {module} schema 中；"
                "请核对字段名或先执行 cordys_ext.sh sync"
            )
        canonical_type = field_meta.get("type") if field_meta else request_type
        if canonical_type in NON_QUERYABLE_TYPES or (field_meta and field_meta.get("queryable") is False):
            raise QueryContractError(f"{prefix}.name={name} 是不可查询字段")
        expected_types = _expected_request_types(canonical_type, operator)
        if request_type not in expected_types:
            expected = "/".join(sorted(expected_types))
            raise QueryContractError(
                f"{prefix}.type={request_type} 与字段 {name} 的真实类型 {canonical_type} 不匹配；应使用 {expected}"
            )
        if name == "departmentId" and operator != "IN":
            raise QueryContractError(f"{prefix} departmentId 只允许 operator=IN")
        if operator not in TYPE_OPERATORS.get(canonical_type, set()):
            allowed = ",".join(sorted(TYPE_OPERATORS.get(canonical_type, set())))
            raise QueryContractError(
                f"{prefix}.{name} 是 {canonical_type}，不支持 {operator}；可用：{allowed}"
            )

        _validate_value(condition, prefix, canonical_type)
        if field_meta and canonical_type in ENUM_TYPES and operator in {"IN", "NOT_IN"}:
            if canonical_type in STATIC_OPTION_TYPES and not field_meta.get("options"):
                _warn(f"字段 {name} 的 schema 暂无选项快照，仅验证值形状；建议执行 cordys_ext.sh sync")
            _validate_options(condition, field_meta, prefix)
        if name == "departmentId" and operator in {"IN", "NOT_IN"}:
            condition["multipleValue"] = False

    return payload


def validate_distribution_field(module, field, values=None, schema_path=None):
    """验证 dist 的分桶字段确实是枚举字段，并校验显式桶值。"""
    schema = _load_schema(schema_path)
    module_meta = _module_schema(schema, module)
    if not module_meta:
        raise QueryContractError(f"模块 {module} 尚未纳入字段 schema，无法验证 dist 字段")
    field_meta = (module_meta.get("fields") or {}).get(field)
    if not field_meta:
        raise QueryContractError(f"dist 字段 {field} 不在 {module} schema 中")
    field_type = field_meta.get("type")
    if field_type not in ENUM_TYPES:
        raise QueryContractError(f"dist 仅支持枚举字段；{field} 的真实类型是 {field_type}")
    if field_type in STATIC_OPTION_TYPES and not field_meta.get("options"):
        raise QueryContractError(
            f"dist 字段 {field} 的 schema 暂无选项快照；请先执行 cordys_ext.sh sync，"
            "不能在未知桶值上继续统计"
        )
    if values:
        _validate_options({"value": list(values)}, field_meta, "dist")
    if field_type in {"DEPARTMENT", "DEPARTMENT_MULTIPLE"}:
        return "TREE_SELECT"
    return field_type


def validate_aggregate(module, field, operator, group_by=None, schema_path=None):
    """校验本地聚合描述，阻止未知操作符静默退化为 sum。"""
    allowed_ops = {"sum", "avg", "count", "max", "min"}
    if operator not in allowed_ops:
        raise QueryContractError(
            f"aggregate op={operator} 不支持；可用：{','.join(sorted(allowed_ops))}"
        )
    if not isinstance(field, str) or not field:
        raise QueryContractError("aggregate 字段不能为空")

    schema = _load_schema(schema_path)
    module_meta = _module_schema(schema, module)
    if not module_meta:
        raise QueryContractError(f"模块 {module} 尚未纳入字段 schema，无法验证 aggregate 字段")
    field_meta = (module_meta.get("fields") or {}).get(field)
    if not field_meta:
        raise QueryContractError(
            f"aggregate 字段 {field} 不在 {module} schema 中；请核对字段名或先执行 cordys_ext.sh sync"
        )
    elif operator != "count" and field_meta.get("type") != "INPUT_NUMBER":
        raise QueryContractError(
            f"aggregate {operator} 需要数值字段；{field} 的真实类型是 {field_meta.get('type')}"
        )

    if group_by:
        display_fields = {"ownerName", "departmentName", "customerName", "stageName", "name"}
        if group_by not in display_fields and group_by not in (module_meta.get("fields") or {}):
            raise QueryContractError(
                f"aggregate 分组字段 {group_by} 不在 {module} schema 中；请核对字段名"
            )


__all__ = [
    "QueryContractError", "validate_payload", "validate_distribution_field", "validate_aggregate",
]
