"""Cordys CRM 查询条件的确定性契约校验。

本模块优先验证技术事实：字段、字段类型、操作符和值形状是否与表单元数据一致。
对已经实测会产生静默错数的统计口径，额外提供显式 query_mode 语义门禁；
列表查询仍允许按用户明确要求使用录入时间等非默认业务口径。
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

POOL_QUERY_MODULES = {
    "pool/lead": ("线索池/线索公海", "/pool/lead/options"),
    "pool/account": ("客户公海", "/pool/account/options"),
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


def _describe_value_shape(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "JSON 布尔值"
    if isinstance(value, list):
        if not value:
            return "空 JSON 数组"
        if len(value) == 1:
            return f"单元素 JSON 数组（元素为{_describe_value_shape(value[0])}）"
        return f"含 {len(value)} 项的 JSON 数组"
    if isinstance(value, dict):
        return "JSON 对象"
    if isinstance(value, str):
        if value == "":
            return "空 JSON 字符串"
        if not value.strip():
            return "仅含空白的 JSON 字符串"
        return "非空 JSON 字符串"
    if isinstance(value, int):
        return "JSON 整数"
    if isinstance(value, float):
        return "JSON 数字"
    return type(value).__name__


def _pool_id_fix_hint(module):
    label, options_path = POOL_QUERY_MODULES[module]
    return (
        f"先执行 cordys.sh raw GET {options_path}，只在已锁定的{label}模块中按池名取 id；"
        f"然后使用 cordys.sh crm page {module} "
        "'{\"poolId\":\"<options 返回的 id>\",\"current\":1,\"pageSize\":30}'。"
        "poolId 必须位于 payload 顶层，不能放进 combineSearch 或 conditions，也不能改查另一池模块"
    )


def validate_pool_query_scope(module, payload, query_mode=""):
    """在联网前校验池查询的 poolId/keyword 入口契约。"""
    if not isinstance(payload, dict):
        raise QueryContractError("查询 payload 顶层必须是 JSON 对象")
    mode = query_mode or "page"
    is_pool_search = module in POOL_QUERY_MODULES and mode == "search"

    wrong_case_keys = [
        key for key in payload
        if isinstance(key, str) and key.lower() == "poolid" and key != "poolId"
    ]
    if wrong_case_keys:
        if is_pool_search:
            raise QueryContractError(
                f"crm search {module} 不使用 poolId：当前还写成了错误字段名 {wrong_case_keys[0]}；"
                "跨池搜索的目标形状是 payload 顶层非空字符串 keyword，且不携带任何 poolId。"
                f"若要查具体池，改用 crm page {module}。" + _pool_id_fix_hint(module)
            )
        suffix = _pool_id_fix_hint(module) if module in POOL_QUERY_MODULES else ""
        raise QueryContractError(
            f"poolId 字段名大小写错误：当前 payload 顶层字段名为 {wrong_case_keys[0]}；"
            "目标是 payload 顶层非空字符串 poolId，字段名必须精确写成 poolId。" + suffix
        )

    combine_search = payload.get("combineSearch")
    if isinstance(combine_search, dict):
        if "poolId" in combine_search:
            if is_pool_search:
                raise QueryContractError(
                    f"crm search {module} 不使用 poolId：当前 poolId 错放在 combineSearch.poolId；"
                    "跨池搜索的目标形状是 payload 顶层非空字符串 keyword，且不携带任何 poolId。"
                    f"若要查具体池，改用 crm page {module}。" + _pool_id_fix_hint(module)
                )
            suffix = _pool_id_fix_hint(module) if module in POOL_QUERY_MODULES else ""
            raise QueryContractError(
                "poolId 当前位置错误：当前在 combineSearch.poolId；"
                "目标位置是查询 payload 顶层 poolId。" + suffix
            )
        conditions = combine_search.get("conditions")
        if isinstance(conditions, list):
            for index, condition in enumerate(conditions):
                if isinstance(condition, dict) and condition.get("name") == "poolId":
                    if is_pool_search:
                        raise QueryContractError(
                            f"crm search {module} 不使用 poolId：当前 poolId 错放在 "
                            f"combineSearch.conditions[{index}]；跨池搜索的目标形状是 payload 顶层非空字符串 "
                            f"keyword，且不携带任何 poolId。若要查具体池，改用 crm page {module}。"
                            + _pool_id_fix_hint(module)
                        )
                    suffix = _pool_id_fix_hint(module) if module in POOL_QUERY_MODULES else ""
                    raise QueryContractError(
                        f"poolId 当前位置错误：当前在 combineSearch.conditions[{index}]；"
                        "poolId 不是字段 condition，目标位置是查询 payload 顶层 poolId。" + suffix
                    )

    if module not in POOL_QUERY_MODULES:
        if "poolId" in payload:
            raise QueryContractError(
                f"模块 {module} 不接受顶层 poolId；poolId 只用于 pool/lead（线索池/线索公海）"
                "或 pool/account（客户公海）的具体池 page 查询"
            )
        return payload

    label, _ = POOL_QUERY_MODULES[module]
    if mode == "search":
        if "poolId" in payload:
            raise QueryContractError(
                f"crm search {module} 是跨{label}关键词搜索，端点不使用 poolId；"
                f"当前却携带了顶层 poolId（{_describe_value_shape(payload.get('poolId'))}）。"
                "跨池搜索的目标形状是 payload 顶层非空字符串 keyword，且不携带任何 poolId。"
                f"若要查某个具体池，请改用 crm page {module}。" + _pool_id_fix_hint(module)
            )
        keyword = payload.get("keyword")
        if not isinstance(keyword, str) or not keyword.strip():
            raise QueryContractError(
                f"crm search {module} 仅用于跨{label}关键词搜索，必须提供非空字符串 keyword；"
                f"当前 keyword 是{_describe_value_shape(keyword)}。"
                f"若要列出某个具体池，请改用 crm page {module}；" + _pool_id_fix_hint(module)
            )
        payload["keyword"] = keyword.strip()
        return payload

    if mode not in {"page", "page-summary"}:
        raise QueryContractError(f"池模块 {module} 不支持查询模式 {mode or '(空)'}")

    if "poolId" not in payload:
        raise QueryContractError(
            f"{label}具体池查询缺少 poolId：当前 payload 顶层没有 poolId；"
            "目标是 payload 顶层非空字符串 poolId。" + _pool_id_fix_hint(module)
        )
    pool_id = payload.get("poolId")
    if not isinstance(pool_id, str) or not pool_id.strip():
        raise QueryContractError(
            f"{label}具体池查询的 poolId 形状错误：当前是{_describe_value_shape(pool_id)}；"
            "目标是 payload 顶层非空 JSON 字符串。数字类型不得自动转字符串，以免大整数精度已经丢失。"
            + _pool_id_fix_hint(module)
        )
    payload["poolId"] = pool_id.strip()
    return payload


def _normalize_date_comparison_value(condition, prefix):
    operator = condition["operator"]
    value = condition.get("value")
    issues = []

    if isinstance(value, list) and len(value) == 1:
        candidate = value[0]
        if _is_millisecond(candidate, allow_zero=True):
            value = candidate
            issues.append("value 是单元素数组")
        elif isinstance(candidate, str) and candidate.isascii() and candidate.isdigit():
            parsed = int(candidate)
            if _is_millisecond(parsed, allow_zero=True):
                value = parsed
                issues.extend(("value 是单元素数组", "数组元素是数字字符串"))
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        parsed = int(value)
        if _is_millisecond(parsed, allow_zero=True):
            value = parsed
            issues.append("value 是数字字符串")

    if issues:
        condition["value"] = value
        _warn(
            f"{prefix}.{operator} 的 {'、'.join(issues)}，已自动归一化；"
            f"{operator} 需要单个 JSON 整数毫秒时间戳；无需重试"
        )
    return value


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
        if has_value and (value in (None, "") or value == []):
            condition.pop("value", None)
            _warn(
                f"{prefix}.{operator} 携带了占位 value，已自动删除；"
                "该操作符不接受 value 字段；无需重试"
            )
            return
        if has_value:
            shape = _describe_value_shape(value)
            raise QueryContractError(
                f"{prefix}.{operator} 不接受 value；当前 value 是{shape}，请删除 value 字段"
            )
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
            raise QueryContractError(
                f"{prefix}.BETWEEN 只接受 JSON 整数毫秒时间戳，不能传日期字符串或秒级时间戳；"
                "自然日区间先运行 cordys.sh crm date-range"
            )
        if value[0] > value[1]:
            raise QueryContractError(f"{prefix}.BETWEEN 起始时间不能晚于结束时间")
    elif operator == "DYNAMICS":
        if not isinstance(value, str) or value not in DYNAMIC_VALUES:
            allowed = ",".join(sorted(DYNAMIC_VALUES))
            raise QueryContractError(f"{prefix}.DYNAMICS 只接受时间常量字符串：{allowed}")
    elif canonical_type == "DATE_TIME" and operator in {"GT", "LT"}:
        value = _normalize_date_comparison_value(condition, prefix)
        if not _is_millisecond(value, allow_zero=True):
            shape = _describe_value_shape(value)
            interval_hint = "；多边界时间范围应改用 BETWEEN" if isinstance(value, list) else ""
            raise QueryContractError(
                f"{prefix}.{operator}.value 当前是{shape}；"
                f"{operator} 只接受单个 JSON 整数毫秒时间戳{interval_hint}；"
                "日期文本先运行 cordys.sh crm date-ms"
            )
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
            detail = ""
            if canonical_type == "SELECT" and request_type == "SELECT_MULTIPLE":
                detail = (
                    "；即使 value 是多个选项，字段真实类型仍是 SELECT，"
                    "只有字段本身为 SELECT_MULTIPLE 才能使用 SELECT_MULTIPLE"
                )
            raise QueryContractError(
                f"{prefix}.type={request_type} 与字段 {name} 的真实类型 {canonical_type} 不匹配；"
                f"应使用 {expected}{detail}"
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


def validate_query_semantics(module, payload, query_mode=""):
    """阻止技术合法、但在统计场景中已知会静默错数的业务口径。"""
    payload = validate_pool_query_scope(module, payload, query_mode)
    canonical_module = MODULE_ALIASES.get(module, module)
    if canonical_module != "contract/payment-record":
        return payload
    if query_mode not in {"stat", "dist", "aggregate", "page-summary"}:
        return payload

    conditions = ((payload.get("combineSearch") or {}).get("conditions") or [])
    wrong_time_fields = []
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        name = condition.get("name")
        if name in {"createTime", "updateTime"}:
            wrong_time_fields.append(name)
    if wrong_time_fields:
        fields = ",".join(dict.fromkeys(wrong_time_fields))
        raise QueryContractError(
            f"实际回款统计不能使用 {fields}；本月/本周/区间回款必须按 "
            "recordEndTime（实际回款日期）过滤。createTime/updateTime 只表示回款记录的录入/更新时间；"
            "若用户明确查询’本月录入的回款记录’，请改用 crm page 明细查询，不要使用 page-summary 作为实际回款业绩口径"
        )
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


__all__ = [
    "QueryContractError", "validate_payload", "validate_query_semantics",
    "validate_distribution_field", "validate_pool_query_scope",
]
