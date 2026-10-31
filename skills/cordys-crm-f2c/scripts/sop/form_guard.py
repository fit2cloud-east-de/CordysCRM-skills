"""通用创建的提交前表单守卫。

Cordys 网页表单在浏览器里计算公式、填默认值、带出关联字段，并在必填项为空时拦截保存；
后端只保存收到的内容，既不计算公式前缀，也不校验必填。所以 CLI 创建必须在最终请求体上
重放这些浏览器步骤，否则记录会悄悄丢掉公式值（如合同编号前缀 ``DQ``），或缺必填项保存成功。

``apply_create_rules`` 按网页表单的顺序执行：

0. 按网页 ``saveForm`` 的规则规整传入值：带 ``businessKey`` 的字段归到顶层，单选数据源/成员/部门
   取单个值，下拉传选项 value，手机号去空白，数字不超过配置的小数位；
1. 空字段填默认值（「默认当前用户」的成员字段和记录 ``owner`` 取当前用户）；
2. 表单联动：下拉联动下拉（``linkProp``，自动填值或限定可选项），选定关联记录后
   填充负责人等字段（``linkFields``）；
3. ``*_ref_*`` 显示字段从所选父记录带出；子表行里的带出列按该行所选记录带出（价格目录按
   「产品/服务」的价格表 ID + 行内 ``price_sub`` 找到价格行）；
4. 先算子表行公式，再算主表 ``FORMULA`` 字段、公式默认值（名称拼接，如
   ``CONCATENATE(签约客户名,"-",合同编码,"-",最终客户名)``）和流水号前缀公式；前缀以
   ``<前缀>${合同编号}`` 提交，由后端生成 ``DQ20261027X001``；
5. 按 ``showControlRules`` 显隐规则校验必填；
6. 执行表单的提交校验规则（``formProp.validationRules``）；
7. 剥离「随关联记录带出」的字段（``resourceFieldId``），网页和后端都不保存它们。

所有问题一次性报出；只要还有问题，就不发任何写请求。
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from pathlib import Path

from payload_io import PayloadTransportError, _json_number


# dataSourceType → API 模块；/{模块}/get/{id} 返回带 ``name`` 的记录。
DATA_SOURCE_MODULES = {
    "CLUE": "lead",
    "CUSTOMER": "account",
    "OPPORTUNITY": "opportunity",
    "CONTACT": "account/contact",
    "CONTRACT": "contract",
    "BUSINESS_TITLE": "contract/business-title",
    "QUOTATION": "opportunity/quotation",
    "ORDER": "order",
    "INVOICE": "invoice",
    "PAYMENT_PLAN": "contract/payment-plan",
    "CONTRACT_PAYMENT_RECORD": "contract/payment-record",
    "PRODUCT": "product",
}
# 报错时告诉调用方这个字段要传哪类记录的 ID。
DATA_SOURCE_LABELS = {
    "CLUE": "线索", "CUSTOMER": "客户", "OPPORTUNITY": "商机", "CONTACT": "联系人", "CONTRACT": "合同",
    "BUSINESS_TITLE": "工商抬头", "QUOTATION": "报价单", "ORDER": "订单", "INVOICE": "发票",
    "PAYMENT_PLAN": "回款计划", "CONTRACT_PAYMENT_RECORD": "回款记录", "PRODUCT": "产品", "PRICE": "价格表",
}

SUBTABLE_TYPES = {"SUB_PRODUCT", "SUB_PRICE"}
# 网页提交时只取单个值的字段（表单内部以数组保存）。
SINGLE_VALUE_TYPES = {"DATA_SOURCE", "MEMBER", "DEPARTMENT"}
SINGLE_OPTION_TYPES = {"SELECT", "RADIO"}
MULTI_OPTION_TYPES = {"SELECT_MULTIPLE", "CHECKBOX"}
# 调用方确认忽略「可忽略」提交校验规则时传的顶层标记，提交前剥离。
CONFIRM_IGNORED_RULES_KEY = "confirmIgnoredRules"
DATA_SOURCE_TYPES = {"DATA_SOURCE", "DATA_SOURCE_MULTIPLE"}
MEMBER_TYPES = {"MEMBER", "MEMBER_MULTIPLE"}
# 不承载用户输入的字段：分割线，以及由后端生成的流水号。
NON_INPUT_TYPES = {"DIVIDER", "SERIAL_NUMBER"}
UTC8 = timezone(timedelta(hours=8))
EXCEL_EPOCH = datetime(1899, 12, 30, tzinfo=UTC8)


class FormGuardError(PayloadTransportError):
    """请求体不符合实时表单；未发送写请求。"""


class FormulaUnsupported(FormGuardError):
    """公式用到了 CLI 无法与网页一致计算的写法。"""


# ── 字段工具 ─────────────────────────────────────────────────────────
def _field_id(field: dict) -> str:
    return str(field.get("id") or field.get("fieldId") or "")


def _label(field: dict) -> str:
    return str(field.get("name") or _field_id(field))


def _is_required(field: dict) -> bool:
    return any(
        isinstance(rule, dict) and rule.get("key") == "required"
        for rule in field.get("rules") or []
    )


def _children(field: dict) -> list[dict]:
    value = field.get("subFields")
    if isinstance(value, dict):
        value = list(value.values())
    return [child for child in value or [] if isinstance(child, dict)]


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _formula_spec(field: dict) -> dict | None:
    raw = field.get("formula")
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FormGuardError(f"字段「{_label(field)}」的公式配置无法解析：{exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("ir"), dict):
        raise FormGuardError(f"字段「{_label(field)}」的公式缺少可执行 IR")
    return raw


def _formula_kind(field: dict) -> str:
    """公式驱动字段返回 ``formula`` / ``default`` / ``serial``，其余返回 ``""``。"""
    field_type = field.get("type")
    if field_type == "FORMULA":
        return "formula"
    if field_type == "SERIAL_NUMBER" and field.get("prefixType") == "formula":
        return "serial" if not field.get("resourceFieldId") else ""
    if field.get("defaultValueType") == "formula" and field.get("formula"):
        return "default"
    return ""


def _single_id(value) -> str:
    if isinstance(value, list):
        value = value[0] if len(value) == 1 else None
    if _is_empty(value) or isinstance(value, (dict, list, bool)):
        return ""
    return str(value).strip()


def _ids(value) -> list[str]:
    if _is_empty(value):
        return []
    values = value if isinstance(value, list) else str(value).split(",")
    return [str(item).strip() for item in values if not _is_empty(item)]


class _Body:
    """按后端的字段映射读写创建请求体。

    带 ``businessKey`` 的非带出字段放在顶层，其余（包括 ``*_ref_*`` 显示字段）放在 ``moduleFields``。
    放错进 ``moduleFields`` 的 businessKey 字段会被归到顶层（后端只认顶层，否则悄悄丢失）。
    """

    def __init__(self, body: dict, by_id: dict[str, dict]) -> None:
        if not isinstance(body, dict):
            raise FormGuardError("create 请求体必须是 JSON 对象")
        items = body.setdefault("moduleFields", [])
        if not isinstance(items, list):
            raise FormGuardError("create 请求体的 moduleFields 必须是数组")
        self.body = body
        self.items: dict[str, dict] = {}
        for item in items:
            if not isinstance(item, dict) or _is_empty(item.get("fieldId")):
                continue
            field_id = str(item["fieldId"])
            if field_id in self.items:
                raise FormGuardError(f"create 请求体字段重复：{field_id}")
            self.items[field_id] = item
        self.moved: list[str] = []
        self.conflicts: list[str] = []
        for field_id, item in list(self.items.items()):
            field = by_id.get(field_id)
            key = self._top_key(field) if field is not None else ""
            if not key:
                continue
            value, current = item.get("fieldValue"), body.get(key)
            if not _is_empty(current) and not _is_empty(value) and _ids(current) != _ids(value):
                self.conflicts.append(
                    f"「{_label(field)}」在顶层 {key} 和 moduleFields 传了不同的值，只能在顶层 {key} 传一次"
                )
                continue
            if _is_empty(current):
                body[key] = value
            items.remove(item)
            del self.items[field_id]
            self.moved.append(f"{_label(field)}→{key}")

    def drop(self, field_ids: set[str]) -> None:
        """从 ``moduleFields`` 移除这些字段。"""
        self.body["moduleFields"][:] = [
            item for item in self.body["moduleFields"]
            if not (isinstance(item, dict) and str(item.get("fieldId")) in field_ids)
        ]
        for field_id in field_ids:
            self.items.pop(field_id, None)

    @staticmethod
    def _top_key(field: dict) -> str:
        key = field.get("businessKey")
        return str(key) if key and not field.get("resourceFieldId") else ""

    def get(self, field: dict):
        key = self._top_key(field)
        if key:
            return self.body.get(key)
        item = self.items.get(_field_id(field))
        return item.get("fieldValue") if item is not None else None

    def set(self, field: dict, value) -> None:
        key = self._top_key(field)
        if key:
            self.body[key] = value
            return
        field_id = _field_id(field)
        item = self.items.get(field_id)
        if item is None:
            item = {"fieldId": field_id}
            self.body["moduleFields"].append(item)
            self.items[field_id] = item
        item["fieldValue"] = value


# ── 数据读取 ──────────────────────────────────────────────────────────
class ApiResolver:
    """规则用到的只读查询（关联记录、表单配置、当前用户），带缓存。"""

    def __init__(self, fetch, post=None) -> None:
        self._fetch = fetch
        self._post = post
        self._records: dict[tuple[str, str], dict] = {}
        self._price_masters: dict[str, dict] = {}
        self._forms: dict[str, dict[str, dict]] = {}
        self._user_id: str | None = None

    def _get(self, path: str, context: str) -> dict:
        text = self._fetch(path)
        try:
            wrapper = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            wrapper = None
        data = wrapper.get("data") if isinstance(wrapper, dict) else None
        if not isinstance(wrapper, dict) or str(wrapper.get("code")) != "100200" or not isinstance(data, dict):
            raise FormGuardError(f"{context}失败，未发送写请求")
        return data

    def record(self, data_source_type: str, record_id: str, context: str) -> dict:
        module = DATA_SOURCE_MODULES.get(str(data_source_type or ""))
        if not module:
            raise FormGuardError(f"{context}：CLI 不支持读取数据源类型 {data_source_type}")
        key = (module, record_id)
        if key not in self._records:
            try:
                data = self._get(f"/{module}/get/{record_id}", f"读取{context}（{record_id}）")
            except FormGuardError as exc:
                label = DATA_SOURCE_LABELS.get(str(data_source_type), module)
                raise FormGuardError(
                    f"{context}要传{label}的 ID，{record_id} 在{label}里查不到，未发送写请求"
                ) from exc
            if str(data.get("id")) != record_id:
                raise FormGuardError(f"读取{context}（{record_id}）返回的记录 ID 不匹配，未发送写请求")
            self._records[key] = data
        return self._records[key]

    def price_row(self, catalog_id: str, price_sub: str, context: str) -> dict:
        """价格目录里的一行：价格表 ``catalog_id`` 下 id 为 ``price_sub`` 的子行（网页选产品时同样按这两个值定位）。"""
        if catalog_id not in self._price_masters:
            if self._post is None:
                raise FormGuardError(f"{context}：当前环境无法读取价格目录")
            text = self._post("/field/source/ref-detail", {"dataSourceType": "PRICE", "sourceIds": [catalog_id]})
            try:
                wrapper = json.loads(text)
            except (TypeError, json.JSONDecodeError):
                wrapper = None
            data = wrapper.get("data") if isinstance(wrapper, dict) else None
            masters = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
            master = next((m for m in masters if isinstance(m, dict) and str(m.get("id")) == catalog_id), None)
            if not isinstance(wrapper, dict) or str(wrapper.get("code")) != "100200" or master is None:
                raise FormGuardError(f"读取{context}的价格表（{catalog_id}）失败，未发送写请求")
            self._price_masters[catalog_id] = master
        master = self._price_masters[catalog_id]
        # 价格行放在价格表的子表数组里，键名随价格表单配置，按行 id 查找。
        for value in master.values():
            for row in value if isinstance(value, list) else []:
                if isinstance(row, dict) and str(row.get("id")) == price_sub:
                    return row
        raise FormGuardError(f"{context}：价格表（{catalog_id}）里没有价格行 {price_sub}，请用 crm price 重新查")

    def form_fields(self, data_source_type: str, context: str) -> dict[str, dict]:
        """数据源模块自身表单的字段（含子表列），按 id 索引。"""
        module = DATA_SOURCE_MODULES.get(str(data_source_type or ""))
        if not module:
            raise FormGuardError(f"{context}：CLI 不支持读取数据源类型 {data_source_type}")
        if module not in self._forms:
            path = "/module/form/config/contact" if module == "account/contact" else f"/{module}/module/form"
            fields = self._get(path, f"读取{context}的表单配置").get("fields")
            if not isinstance(fields, list):
                raise FormGuardError(f"读取{context}的表单配置失败：缺少 fields，未发送写请求")
            found: dict[str, dict] = {}
            pending = [f for f in fields if isinstance(f, dict)]
            while pending:
                item = pending.pop()
                found[_field_id(item)] = item
                pending.extend(_children(item))
            self._forms[module] = found
        return self._forms[module]

    def current_user_id(self) -> str:
        if self._user_id is None:
            data = self._get("/personal/center/info", "读取当前用户")
            user_id = str(data.get("id") or "").strip()
            if not user_id:
                raise FormGuardError("读取当前用户失败：缺少用户 ID，未发送写请求")
            self._user_id = user_id
        return self._user_id


def _record_value(record: dict, target_id: str, business_key: str):
    for item in record.get("moduleFields") or []:
        if isinstance(item, dict) and str(item.get("fieldId")) == target_id:
            return item.get("fieldValue")
    if business_key and business_key in record:
        return record.get(business_key)
    return record.get(target_id)


# ── 公式运行时（移植自网页公式执行器）────────────────────────────────
def _to_decimal(value) -> Decimal | None:
    """按 Excel 规则转数字；不是数字时返回 ``None``。"""
    if isinstance(value, list):
        value = value[0] if value else 0
    if value is None:
        return Decimal(0)
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    if text == "":
        return Decimal(0)
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _to_bool(value) -> bool:
    if isinstance(value, list):
        if not value:
            return False
        value = value[0]
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return value != 0
    text = str(value).strip().lower()
    if text in ("", "false"):
        return False
    return True


def _js_text(value) -> str:
    """``+`` 拼接和公式默认值使用的字符串转换。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, Decimal):
        return _number_text(value)
    if isinstance(value, list):
        return ",".join(_js_text(item) for item in value)
    return str(value)


def _number_text(value: Decimal) -> str:
    normalized = _normalize_number(value)
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _normalize_number(value: Decimal) -> Decimal:
    """与网页运行时一致，按 15 位有效数字去掉二进制浮点误差。"""
    if value == 0:
        return Decimal(0)
    return Decimal(format(value, ".15g"))


def _round(value: Decimal, digits: int) -> Decimal:
    return _normalize_number(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def _compare_equal(left, right) -> bool:
    if isinstance(left, list):
        left = left[0] if left else Decimal(0)
    if isinstance(right, list):
        right = right[0] if right else Decimal(0)
    left_empty = left is None or left == ""
    right_empty = right is None or right == ""
    if left_empty and right_empty:
        return True
    if isinstance(left, Decimal) and isinstance(right, str):
        number = _to_decimal(right)
        if number is not None:
            return left == number
    if isinstance(left, str) and isinstance(right, Decimal):
        number = _to_decimal(left)
        if number is not None:
            return number == right
    if isinstance(left, bool) or isinstance(right, bool):
        return _to_bool(left) == _to_bool(right)
    return left == right


def _compare(left, right, operator: str) -> bool:
    if operator == "=":
        return _compare_equal(left, right)
    if operator in ("<>", "!="):
        return not _compare_equal(left, right)
    lnum, rnum = _to_decimal(left), _to_decimal(right)
    if lnum is None or rnum is None:
        return False
    return {
        ">": lnum > rnum,
        "<": lnum < rnum,
        ">=": lnum >= rnum,
        "<=": lnum <= rnum,
    }.get(operator, False)


def _sum(values) -> Decimal:
    total = Decimal(0)
    for value in values:
        if isinstance(value, list):
            total += _sum(value)
        elif isinstance(value, Decimal) and not isinstance(value, bool):
            total += value
    return _normalize_number(total)


class _Evaluator:
    """在创建请求体上计算公式 IR。

    取值语义与网页运行时一致：下拉和数据源字段取显示文本/名称（列表形式），空数字为
    ``None``（运算时按 ``0``），流水号取 ``${字段名}`` 占位符，由后端替换。
    """

    def __init__(self, rules: "_FormRules") -> None:
        self.rules = rules

    def evaluate(self, node, row: dict | None, row_fields: dict | None, label: str):
        if not isinstance(node, dict):
            raise FormulaUnsupported(f"公式「{label}」IR 节点无效")
        node_type = node.get("type")
        # 旧版字面量存成 {"type": "number", "value": ...}。
        if node_type in ("number", "string", "boolean"):
            node = {"type": "literal", "valueType": node_type, "value": node.get("value")}
            node_type = "literal"
        if node_type == "literal":
            value = node.get("value")
            if node.get("valueType") == "number":
                return _to_decimal(value) or Decimal(0)
            if node.get("valueType") == "string":
                return "" if value is None else str(value)
            return value
        if node_type == "field":
            return self.rules.field_operand(str(node.get("fieldId") or ""), row, row_fields, label)
        if node_type == "binary":
            left = self.evaluate(node.get("left"), row, row_fields, label)
            right = self.evaluate(node.get("right"), row, row_fields, label)
            operator = node.get("operator")
            if operator == "+":
                numeric = all(
                    value is None or (isinstance(value, Decimal) and not isinstance(value, bool))
                    for value in (left, right)
                )
                if numeric:
                    return (left or Decimal(0)) + (right or Decimal(0))
                return _js_text(left) + _js_text(right)
            lnum, rnum = _to_decimal(left), _to_decimal(right)
            if lnum is None or rnum is None:
                return Decimal(0)
            if operator == "-":
                return lnum - rnum
            if operator == "*":
                return lnum * rnum
            if operator == "/":
                return Decimal(0) if rnum == 0 else lnum / rnum
            raise FormulaUnsupported(f"公式「{label}」包含不支持的运算符：{operator}")
        if node_type == "unary":
            return not _to_bool(self.evaluate(node.get("operand"), row, row_fields, label))
        if node_type == "compare":
            left = self.evaluate(node.get("left"), row, row_fields, label)
            right = self.evaluate(node.get("right"), row, row_fields, label)
            return _compare(left, right, str(node.get("operator") or ""))
        if node_type == "function":
            return self._function(node, row, row_fields, label)
        raise FormulaUnsupported(f"公式「{label}」包含不支持的 IR 类型：{node_type}")

    def _function(self, node: dict, row, row_fields, label: str):
        name = str(node.get("name") or "").upper()
        args = node.get("args") if isinstance(node.get("args"), list) else []

        def value(arg):
            return self.evaluate(arg, row, row_fields, label)

        if name == "IF":
            if len(args) < 2:
                return None
            if _to_bool(value(args[0])):
                return value(args[1])
            return value(args[2]) if len(args) > 2 else None
        if name == "IFS":
            for index in range(0, len(args) - 1, 2):
                if _to_bool(value(args[index])):
                    return value(args[index + 1])
            return None
        if name == "AND":
            return all(_to_bool(value(arg)) for arg in args)
        values = [value(arg) for arg in args]
        if name == "SUM":
            return _sum(values)
        if name == "CONCATENATE":
            out = []
            for item in values:
                if isinstance(item, list):
                    out.extend(_js_text(part) for part in item if part is not None)
                elif item is not None:
                    out.append(_js_text(item))
            return "".join(out)
        if name == "UNION":
            flat = []
            for item in values:
                flat.extend(item if isinstance(item, list) else [item])
            return "".join("" if _is_empty(part) else _js_text(part) for part in flat)
        raise FormulaUnsupported(f"公式「{label}」使用了 CLI 暂不支持的函数 {name or '<empty>'}")


# ── 规则 ───────────────────────────────────────────────────────────────
class _FormRules:
    def __init__(self, body: dict, form: dict, resolver: ApiResolver, attachment_field_ids) -> None:
        fields = form.get("fields") if isinstance(form, dict) else None
        if not isinstance(fields, list):
            raise FormGuardError("实时表单缺少 fields，无法校验")
        self.fields = [f for f in fields if isinstance(f, dict) and _field_id(f)]
        self.by_id = {_field_id(f): f for f in self.fields}
        form_prop = form.get("formProp") if isinstance(form.get("formProp"), dict) else {}
        self.validation_rules = [
            r for r in form_prop.get("validationRules") or [] if isinstance(r, dict) and r.get("enable")
        ]
        self.confirm_ignored = body.pop(CONFIRM_IGNORED_RULES_KEY, False) is True if isinstance(body, dict) else False
        self.data = _Body(body, self.by_id)
        self.resolver = resolver
        self.attachment_ids = {str(item) for item in attachment_field_ids or ()}
        self.evaluator = _Evaluator(self)
        self.top_values: dict[str, object] = {}
        self.top_resolving: set[str] = set()
        self.defaulted: set[str] = set()
        self.notes: list[str] = []
        self.problems: list[str] = list(self.data.conflicts)
        if self.data.moved:
            self.notes.append("已归到顶层的业务字段：" + "、".join(self.data.moved))

    # 操作数 -------------------------------------------------------------
    def field_operand(self, field_id: str, row, row_fields, label: str):
        if not field_id:
            raise FormulaUnsupported(f"公式「{label}」引用了空 fieldId")
        if "." in field_id:
            parent_id, child_id = field_id.split(".", 1)
            parent = self.by_id.get(parent_id)
            if parent is None:
                raise FormulaUnsupported(f"公式「{label}」引用的子表 {parent_id} 不在当前表单")
            child = {_field_id(c): c for c in _children(parent)}.get(child_id)
            rows = self.data.get(parent)
            if not isinstance(rows, list):
                return []
            return [
                self._operand(child or {"id": child_id}, r.get(child_id), label)
                for r in rows if isinstance(r, dict)
            ]
        if row is not None:
            # 子表行内，不带子表前缀的 fieldId 都指向当前行。
            child = (row_fields or {}).get(field_id) or {"id": field_id}
            return self._operand(child, row.get(field_id), label)
        field = self.by_id.get(field_id)
        if field is None:
            raise FormulaUnsupported(f"公式「{label}」引用的字段 {field_id} 不在当前表单")
        if field.get("type") == "SERIAL_NUMBER" and not field.get("resourceFieldId"):
            return "${" + _label(field) + "}"
        if _formula_kind(field) in ("formula", "default"):
            return self._operand(field, self.top_formula(field), label)
        return self._operand(field, self.data.get(field), label)

    def _operand(self, field: dict, raw, label: str):
        field_type = field.get("type")
        if field_type == "SERIAL_NUMBER" and not field.get("resourceFieldId"):
            return "${" + _label(field) + "}"
        if field_type in DATA_SOURCE_TYPES:
            return [self._source_name(field, record_id, label) for record_id in _ids(raw)]
        if field_type in ("SELECT", "SELECT_MULTIPLE"):
            if _is_empty(raw):
                return []
            options = {
                str(o.get("value")): str(o.get("label") if o.get("label") is not None else o.get("name"))
                for o in field.get("options") or [] if isinstance(o, dict)
            }
            values = raw if isinstance(raw, list) else [raw]
            return [options.get(str(v), str(v)) for v in values]
        if _is_empty(raw):
            if field_type in ("INPUT_NUMBER", "FORMULA", "DATE_TIME"):
                return None
            return ""
        if isinstance(raw, list):
            return raw
        if field_type in ("RADIO", "CHECKBOX"):
            return bool(raw)
        if field_type == "DATE_TIME":
            number = _to_decimal(raw)
            if number is None:
                return Decimal(0)
            moment = datetime.fromtimestamp(float(number) / 1000, tz=UTC8)
            return Decimal(str((moment - EXCEL_EPOCH).total_seconds() / 86400))
        is_number = isinstance(raw, (int, float, Decimal)) and not isinstance(raw, bool)
        if field_type in ("INPUT_NUMBER", "FORMULA") or (is_number and field_type not in ("INPUT", "TEXTAREA")):
            # "21,000.00"、"6%" 这类格式化文本也按数字处理。
            number = _to_decimal(raw if is_number else str(raw).replace(",", "").replace("%", ""))
            if number is None:
                return Decimal(0)
            if str(field.get("numberFormat") or "").lower() == "percent":
                number /= Decimal(100)
            return number
        return str(raw)

    def _source_name(self, field: dict, record_id: str, label: str) -> str:
        record = self.resolver.record(field.get("dataSourceType"), record_id, f"公式「{label}」引用的「{_label(field)}」")
        name = str(record.get("name") or "").strip()
        if not name:
            raise FormGuardError(f"「{_label(field)}」（{record_id}）没有名称，无法计算公式「{label}」")
        return name

    # 结果 --------------------------------------------------------------
    @staticmethod
    def _formula_result(field: dict, value):
        """保存前按网页表单的方式规整 ``FORMULA`` 结果。"""
        if field.get("formulaResultFormat") == "number":
            number = _to_decimal(value)
            if number is None:
                return _js_text(value)
            digits = field.get("precision") if field.get("decimalPlaces") else None
            if isinstance(digits, str) and digits.strip().isdigit():
                digits = int(digits)
            number = _round(number, digits) if isinstance(digits, int) and not isinstance(digits, bool) else _normalize_number(number)
            try:
                return _json_number(number, f"公式「{_label(field)}」的结果")
            except PayloadTransportError as exc:
                # 统一成守卫错误，由公式步骤汇总报出，而不是中断整个校验。
                raise FormGuardError(str(exc)) from exc
        return _js_text(value)

    def top_formula(self, field: dict):
        field_id = _field_id(field)
        if _formula_spec(field) is None:
            # 没配公式的 FORMULA 字段与网页一致，保持调用方传入的值。
            return self.data.get(field)
        if field_id in self.top_values:
            return self.top_values[field_id]
        if field_id in self.top_resolving:
            raise FormGuardError(f"公式「{_label(field)}」存在循环引用")
        self.top_resolving.add(field_id)
        try:
            spec = _formula_spec(field)
            value = self.evaluator.evaluate(spec["ir"], None, None, _label(field))
        finally:
            self.top_resolving.discard(field_id)
        if field.get("type") == "FORMULA":
            value = self._formula_result(field, value)
        else:
            value = _js_text(value)
        self.top_values[field_id] = value
        return value

    # 步骤 ----------------------------------------------------------------
    def normalize_values(self) -> None:
        """按网页提交时的转换规整调用方传入的值（transformFieldValue / transformSubFieldsValue）。"""
        for field in self.fields:
            if field.get("resourceFieldId"):
                continue
            if field.get("type") in SUBTABLE_TYPES:
                self._normalize_rows(field)
                continue
            value = self.data.get(field)
            if _is_empty(value):
                continue
            self.data.set(field, self._normalized(field, value, f"「{_label(field)}」", options=True))

    def _normalize_rows(self, parent: dict) -> None:
        rows = self.data.get(parent)
        if not isinstance(rows, list):
            return
        children = [c for c in _children(parent) if not c.get("resourceFieldId")]
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            for child in children:
                # 网页子表行以 businessKey（没有则 id）为键。
                for key in {_field_id(child), str(child.get("businessKey") or "")} - {""}:
                    value = row.get(key)
                    if _is_empty(value):
                        continue
                    where = f"子表「{_label(parent)}」第 {index} 行「{_label(child)}」"
                    # 网页不规整子表行里的下拉值，这里也不校验选项。
                    row[key] = self._normalized(child, value, where, options=False, price_sub=row.get("price_sub"))

    def _normalized(self, field: dict, value, where: str, *, options: bool, price_sub=None):
        """返回规整后的值；无法规整时记录问题并原样返回。"""
        field_type = field.get("type")
        if field_type in SINGLE_VALUE_TYPES and isinstance(value, list):
            # 价格表子表格的数组里带着行号 price_sub，不算选中的值。
            values = [v for v in value if _is_empty(price_sub) or v != price_sub]
            if len(values) > 1:
                self.problems.append(f"{where}只能选一个，收到 {len(values)} 个")
                return value
            return values[0] if values else ""
        if field_type == "PHONE" and isinstance(value, str):
            return re.sub(r"[\s\ufeff\xa0]+", "", value)
        if field_type == "INPUT_NUMBER":
            # 千分位文本（如 "2,500.50"）公式里也按数字处理，这里同样接受。
            number = _to_decimal(value.replace(",", "") if isinstance(value, str) else value)
            if number is None:
                self.problems.append(f"{where}必须是数字，收到「{value}」")
                return value
            digits = field.get("precision")
            if isinstance(digits, int) and not isinstance(digits, bool) and _round(number, digits) != number:
                self.problems.append(f"{where}最多 {digits} 位小数，收到「{value}」")
            return value
        if options and field_type in SINGLE_OPTION_TYPES | MULTI_OPTION_TYPES:
            return self._option_values(field, value, where)
        return value

    def _option_values(self, field: dict, value, where: str):
        """下拉/单选/多选只接受选项 value；唯一匹配的选项文字换成 value，其余报错（网页会提交成空）。"""
        opts = [o for o in field.get("options") or [] if isinstance(o, dict)]
        if not opts:
            return value
        by_value = {str(o.get("value")): o.get("value") for o in opts}
        by_label: dict[str, list] = {}
        for o in opts:
            by_label.setdefault(str(o.get("label")), []).append(o.get("value"))
        multiple = field.get("type") in MULTI_OPTION_TYPES
        if not multiple and isinstance(value, list):
            if len(value) != 1:
                self.problems.append(f"{where}只能选一个")
                return value
            value = value[0]
        out, bad, changed = [], [], False
        for item in value if isinstance(value, list) else [value]:
            if str(item) in by_value:
                out.append(by_value[str(item)])
            elif len(by_label.get(str(item), [])) == 1:
                out.append(by_label[str(item)][0])
                changed = True
            else:
                bad.append(str(item))
        if bad:
            labels = "、".join(str(o.get("label")) for o in opts)
            self.problems.append(f"{where}的值「{'、'.join(bad)}」不在可选项中（可选：{labels}）")
            return value
        if changed:
            self.notes.append(f"{where}按选项文字换成了选项 value")
        return out if multiple else out[0]

    def apply_defaults(self) -> None:
        filled = []
        for field in self.fields:
            field_type = field.get("type")
            if field.get("resourceFieldId") or field_type in NON_INPUT_TYPES or _formula_kind(field):
                continue
            if field_type in SUBTABLE_TYPES:
                self._apply_row_defaults(field)
                continue
            if not _is_empty(self.data.get(field)):
                continue
            value = None
            if field_type in MEMBER_TYPES and (field.get("hasCurrentUser") or field.get("businessKey") == "owner"):
                user_id = self.resolver.current_user_id()
                value = [user_id] if field_type == "MEMBER_MULTIPLE" else user_id
            elif not _is_empty(field.get("defaultValue")) and not isinstance(field.get("defaultValue"), dict):
                value = field.get("defaultValue")
            if value is not None:
                self.data.set(field, value)
                self.defaulted.add(_field_id(field))
                filled.append(_label(field))
        if filled:
            self.notes.append("默认值：" + "、".join(filled))

    def apply_links(self) -> None:
        """重放表单联动：下拉联动下拉（``linkProp``）和选定记录后的字段填充（``linkFields``）。

        网页在源字段变化时填充目标字段；调用方显式传入的值优先，普通默认值会被覆盖。
        """
        filled: list[str] = []
        for field in self.fields:
            value = self.data.get(field)
            if _is_empty(value):
                continue
            link = field.get("linkProp")
            if isinstance(link, dict) and link.get("targetField"):
                self._apply_select_link(field, value, link, filled)
            if field.get("type") in DATA_SOURCE_TYPES and field.get("linkFields"):
                self._apply_record_link(field, value, filled)
        if filled:
            self.notes.append("表单联动填充：" + "、".join(filled))

    def _fillable(self, field: dict) -> bool:
        return _is_empty(self.data.get(field)) or _field_id(field) in self.defaulted

    def _apply_select_link(self, field: dict, value, link: dict, filled: list[str]) -> None:
        target = self.by_id.get(str(link.get("targetField")))
        if target is None:
            return
        for option in link.get("linkOptions") or []:
            if not isinstance(option, dict) or value != option.get("current"):
                continue
            wanted = option.get("target")
            if option.get("method") == "HIDDEN":
                # 网页上只保留列出的选项可选。
                allowed = [str(v) for v in (wanted if isinstance(wanted, list) else [wanted])]
                given = self.data.get(target)
                bad = [str(v) for v in (given if isinstance(given, list) else [given]) if not _is_empty(v) and str(v) not in allowed]
                if bad:
                    labels = {str(o.get("value")): str(o.get("label")) for o in target.get("options") or [] if isinstance(o, dict)}
                    current = self._operand(field, value, _label(field))
                    self.problems.append(
                        f"「{_label(field)}」为「{'、'.join(map(str, current))}」时，「{_label(target)}」只能选："
                        + "、".join(labels.get(v, v) for v in allowed)
                    )
            elif self._fillable(target):
                self.data.set(target, wanted)
                self.defaulted.discard(_field_id(target))
                filled.append(_label(target))
            return

    def _apply_record_link(self, field: dict, value, filled: list[str]) -> None:
        record_id = _single_id(value)
        if not record_id:
            return
        source_type = field.get("dataSourceType")
        context = f"「{_label(field)}」"
        for link in field.get("linkFields") or []:
            if not isinstance(link, dict) or link.get("enable") is False or link.get("method") != "fill":
                continue
            target = self.by_id.get(str(link.get("current") or ""))
            if target is None or not self._fillable(target):
                continue
            link_id = str(link.get("link") or "")
            if link_id in (_field_id(field), str(field.get("businessKey") or "")):
                # 把所选记录本身复制到另一个数据源字段。
                if target.get("dataSourceType") != source_type:
                    continue
                fill = value
            else:
                source = self.resolver.form_fields(source_type, context).get(link_id)
                if source is None or target.get("dataSourceType") != source.get("dataSourceType"):
                    continue
                record = self.resolver.record(source_type, record_id, context)
                fill = _record_value(record, link_id, str(source.get("businessKey") or ""))
            if _is_empty(fill):
                continue
            if target.get("type") in ("DATA_SOURCE", "MEMBER") and isinstance(fill, list) and len(fill) == 1:
                fill = fill[0]
            elif target.get("type") in ("DATA_SOURCE_MULTIPLE", "MEMBER_MULTIPLE") and not isinstance(fill, list):
                fill = [fill]
            self.data.set(target, fill)
            self.defaulted.discard(_field_id(target))
            filled.append(_label(target))

    def _apply_row_defaults(self, parent: dict) -> None:
        rows = self.data.get(parent)
        if not isinstance(rows, list):
            return
        for child in _children(parent):
            default = child.get("defaultValue")
            if (
                child.get("resourceFieldId")
                or _formula_kind(child)
                or _is_empty(default)
                or isinstance(default, dict)
            ):
                continue
            for row in rows:
                if isinstance(row, dict) and _is_empty(row.get(_field_id(child))):
                    row[_field_id(child)] = default

    def apply_references(self) -> None:
        filled = []
        for field in self.fields:
            parent_id = str(field.get("resourceFieldId") or "")
            field_id = _field_id(field)
            if not parent_id or "_ref_" not in field_id or not _is_empty(self.data.get(field)):
                continue
            parent = self.by_id.get(parent_id)
            if parent is None or parent.get("type") not in DATA_SOURCE_TYPES:
                continue
            record_id = _single_id(self.data.get(parent))
            if not record_id or str(parent.get("dataSourceType") or "") not in DATA_SOURCE_MODULES:
                continue
            record = self.resolver.record(parent.get("dataSourceType"), record_id, f"「{_label(parent)}」")
            value = _record_value(record, field_id.split("_ref_", 1)[1], str(field.get("businessKey") or ""))
            if not _is_empty(value):
                self.data.set(field, value)
                filled.append(_label(field))
        if filled:
            self.notes.append("随关联记录带出：" + "、".join(filled))

    def apply_row_references(self) -> None:
        """子表行的带出列：按同一行所选的记录带出，调用方不传（网页上选定产品后自动显示）。"""
        filled: dict[str, int] = {}
        for parent in self.fields:
            if parent.get("type") not in SUBTABLE_TYPES:
                continue
            rows = self.data.get(parent)
            if not isinstance(rows, list):
                continue
            children = {_field_id(c): c for c in _children(parent)}
            refs = [c for c in children.values() if c.get("resourceFieldId") and "_ref_" in _field_id(c)]
            for index, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    continue
                where = f"子表「{_label(parent)}」第 {index} 行"
                for child in refs:
                    child_id = _field_id(child)
                    source = children.get(str(child.get("resourceFieldId")))
                    if source is None or not _is_empty(row.get(child_id)):
                        continue
                    record_id = _single_id(row.get(_field_id(source)))
                    if not record_id:
                        continue
                    try:
                        value = self._row_reference(source, child, row, record_id, f"{where}「{_label(source)}」")
                    except FormGuardError as exc:
                        if str(exc) not in self.problems:
                            self.problems.append(str(exc))
                        continue
                    if not _is_empty(value):
                        row[child_id] = value
                        filled[_label(parent)] = filled.get(_label(parent), 0) + 1
        if filled:
            self.notes.append(
                "子表按所选记录带出：" + "、".join(f"{name} {count} 项" for name, count in filled.items())
            )

    def _row_reference(self, source: dict, child: dict, row: dict, record_id: str, context: str):
        target = _field_id(child).split("_ref_", 1)[1]
        business_key = str(child.get("businessKey") or "")
        if source.get("dataSourceType") == "PRICE":
            price_sub = _single_id(row.get("price_sub"))
            if not price_sub:
                raise FormGuardError(f"{context}选了价格表，还要在行内传 price_sub（价格行 ID，crm price 的 price_row_id）")
            price_row = self.resolver.price_row(record_id, price_sub, context)
            return price_row.get(business_key) if business_key and business_key in price_row else price_row.get(target)
        if str(source.get("dataSourceType") or "") not in DATA_SOURCE_MODULES:
            return None
        return _record_value(self.resolver.record(source.get("dataSourceType"), record_id, context), target, business_key)

    def apply_row_formulas(self) -> None:
        for parent in self.fields:
            if parent.get("type") not in SUBTABLE_TYPES:
                continue
            rows = self.data.get(parent)
            if not isinstance(rows, list) or not rows:
                continue
            row_fields = {_field_id(c): c for c in _children(parent)}
            formulas = [c for c in row_fields.values() if c.get("type") == "FORMULA" and c.get("formula")]
            for index, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    self.problems.append(f"子表「{_label(parent)}」第 {index} 行必须是对象")
                    continue
                done: dict[str, object] = {}

                def resolve(child: dict, stack: tuple[str, ...]):
                    child_id = _field_id(child)
                    if child_id in done:
                        return done[child_id]
                    if child_id in stack:
                        raise FormGuardError(f"子表「{_label(parent)}」公式「{_label(child)}」存在循环引用")
                    # 子表公式可能引用同行的其他公式，先算被引用的。
                    for dep in _field_refs(_formula_spec(child)["ir"]):
                        dep_field = row_fields.get(dep)
                        if dep_field is not None and dep_field.get("type") == "FORMULA" and dep_field.get("formula"):
                            resolve(dep_field, stack + (child_id,))
                    label = f"{_label(parent)}.{_label(child)}"
                    value = self.evaluator.evaluate(_formula_spec(child)["ir"], row, row_fields, label)
                    done[child_id] = row[child_id] = self._formula_result(child, value)
                    return done[child_id]

                for child in formulas:
                    try:
                        resolve(child, ())
                    except FormGuardError as exc:
                        self._formula_problem(child, exc, f"子表「{_label(parent)}」第 {index} 行")

    def apply_top_formulas(self) -> None:
        for field in self.fields:
            kind = _formula_kind(field)
            if not kind:
                continue
            try:
                if kind == "formula" and _formula_spec(field) is None:
                    continue
                value = self.top_formula(field) if kind != "serial" else self._serial_prefix(field)
            except FormGuardError as exc:
                self._formula_problem(field, exc, "")
                continue
            current = self.data.get(field)
            if kind == "formula":
                self.data.set(field, value)
            elif kind == "serial":
                self.data.set(field, f"{value}${{{_label(field)}}}")
                if value:
                    self.notes.append(f"{_label(field)}前缀：{value}")
                else:
                    self.notes.append(f"⚠️ {_label(field)}前缀公式无匹配结果，后端将生成无前缀编号")
            else:
                given = "" if _is_empty(current) else str(current).strip()
                if given and given != value:
                    display = (_formula_spec(field) or {}).get("display") or ""
                    rule = f"（{display}）" if display else ""
                    self.problems.append(
                        f"「{_label(field)}」由表单公式{rule}生成为「{value}」，不能指定为「{given}」；请不传该字段，由 CLI 生成"
                    )
                    continue
                self.data.set(field, value)
                self.notes.append(f"{_label(field)}：{value}")

    def _serial_prefix(self, field: dict) -> str:
        spec = _formula_spec(field)
        if spec is None:
            return ""
        value = self.evaluator.evaluate(spec["ir"], None, None, _label(field))
        if isinstance(value, Decimal):
            return format(_round(value, 2), "f")
        return _js_text(value)

    def _formula_problem(self, field: dict, exc: FormGuardError, where: str) -> None:
        message = f"{where}{exc}" if where else str(exc)
        # 无法计算的选填 FORMULA 保持传入值；名称、编号前缀和必填公式必须算对。
        if field.get("type") == "FORMULA" and not _is_required(field) and isinstance(exc, FormulaUnsupported):
            self.notes.append(f"⚠️ 跳过：{message}")
            return
        if message not in self.problems:
            self.problems.append(message)

    def visible_ids(self) -> set[str]:
        controllers: dict[str, list[tuple[dict, str]]] = {}
        for field in self.fields:
            for rule in field.get("showControlRules") or []:
                if not isinstance(rule, dict):
                    continue
                for target in rule.get("fieldIds") or []:
                    controllers.setdefault(str(target), []).append((field, str(rule.get("value"))))
        memo: dict[str, bool] = {}

        def visible(field_id: str, stack: frozenset) -> bool:
            if field_id in memo:
                return memo[field_id]
            result = field_id not in controllers
            for controller, expected in controllers.get(field_id, []):
                controller_id = _field_id(controller)
                if controller_id in stack or not visible(controller_id, stack | {controller_id}):
                    continue
                current = self.data.get(controller)
                values = current if isinstance(current, list) else [current]
                labels = {
                    str(o.get("value")): str(o.get("label"))
                    for o in controller.get("options") or [] if isinstance(o, dict)
                }
                accepted = {expected, labels.get(expected, expected)}
                if any(not _is_empty(v) and str(v) in accepted for v in values):
                    result = True
                    break
            memo[field_id] = result
            return result

        return {fid for fid in self.by_id if visible(fid, frozenset({fid}))}

    def validate_required(self) -> None:
        visible = self.visible_ids()
        missing = []
        for field in self.fields:
            field_id = _field_id(field)
            field_type = field.get("type")
            if field_id not in visible or field_type in NON_INPUT_TYPES or field.get("readable") is False:
                continue
            value = self.data.get(field)
            if field_type in SUBTABLE_TYPES:
                rows = value if isinstance(value, list) else []
                if _is_required(field) and not rows:
                    missing.append(f"「{_label(field)}」（至少一行）")
                missing.extend(self._missing_row_fields(field, rows))
                continue
            # 公式驱动字段刚算过，失败已在公式步骤报出。
            if not _is_required(field) or _formula_kind(field):
                continue
            if field_type == "ATTACHMENT" and field_id in self.attachment_ids:
                continue
            if _is_empty(value):
                hint = ""
                parent = self.by_id.get(str(field.get("resourceFieldId") or ""))
                if parent is not None:
                    hint = f"（随「{_label(parent)}」带出，请检查该记录或直接提供）"
                elif field_type == "ATTACHMENT":
                    hint = "（请用 attachments 传本地文件）"
                missing.append(f"「{_label(field)}」{hint}")
        if missing:
            self.problems.append("缺少必填字段：" + "、".join(missing))

    def validate_submit_rules(self) -> None:
        """执行表单提交校验规则：结果严格为 false 时拦截；计算出错放行（与网页一致）。

        ``allowIgnore`` 的规则网页上可由用户确认后继续提交；CLI 中需用户确认后在请求体顶层
        传 ``confirmIgnoredRules: true`` 重新提交。
        """
        ignorable = []
        for index, rule in enumerate(self.validation_rules, start=1):
            message = str(rule.get("message") or "").strip() or f"提交校验规则 {index} 未通过"
            try:
                spec = json.loads(rule["formula"]) if isinstance(rule.get("formula"), str) else rule.get("formula")
                ir = spec.get("ir") if isinstance(spec, dict) else None
                if not isinstance(ir, dict):
                    raise FormulaUnsupported("规则缺少可执行 IR")
                passed = self.evaluator.evaluate(ir, None, None, f"提交校验规则 {index}") is not False
            except (FormGuardError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self.notes.append(f"⚠️ 提交校验规则「{message}」无法计算，已按网页规则放行：{exc}")
                continue
            if passed:
                continue
            if rule.get("allowIgnore"):
                ignorable.append(message)
            else:
                self.problems.append(f"提交校验未通过：{message}")
        if ignorable and not self.confirm_ignored:
            self.problems.append(
                "提交校验提醒（可忽略）：" + "；".join(ignorable)
                + f"。用户确认忽略后，在请求体顶层加 \"{CONFIRM_IGNORED_RULES_KEY}\": true 重新提交"
            )
        elif ignorable:
            self.notes.append("用户已确认忽略的提交校验提醒：" + "；".join(ignorable))

    def strip_references(self) -> None:
        """剥离带出字段：网页 saveForm 不提交它们，后端也会跳过；它们只用于公式和必填校验。"""
        self.data.drop({_field_id(f) for f in self.fields if f.get("resourceFieldId")})
        for parent in self.fields:
            if parent.get("type") not in SUBTABLE_TYPES:
                continue
            rows = self.data.get(parent)
            ref_ids = [_field_id(c) for c in _children(parent) if c.get("resourceFieldId")]
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict):
                    for ref_id in ref_ids:
                        row.pop(ref_id, None)

    @staticmethod
    def _missing_row_fields(parent: dict, rows: list) -> list[str]:
        required = [
            c for c in _children(parent)
            if _is_required(c) and c.get("type") not in NON_INPUT_TYPES and c.get("type") != "FORMULA"
        ]
        out = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            by_id = {_field_id(c): c for c in _children(parent)}
            names = [
                _label(c) + (
                    f"（随「{_label(by_id[str(c.get('resourceFieldId'))])}」带出，请检查所选记录）"
                    if str(c.get("resourceFieldId") or "") in by_id else ""
                )
                for c in required if _is_empty(row.get(_field_id(c)))
            ]
            if names:
                out.append(f"子表「{_label(parent)}」第 {index} 行：" + "、".join(names))
        return out


def _field_refs(node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        if node.get("type") == "field" and node.get("fieldId"):
            found.add(str(node["fieldId"]))
        for value in node.values():
            found |= _field_refs(value)
    elif isinstance(node, list):
        for value in node:
            found |= _field_refs(value)
    return found


def apply_create_rules(
    body: dict,
    form: dict,
    resolver: ApiResolver,
    *,
    attachment_field_ids=(),
) -> list[str]:
    """原地补齐并校验一个创建请求体，返回摘要说明。

    请求体不能提交时抛出 ``FormGuardError``，列出全部问题。``attachment_field_ids``
    是校验之后 CLI 会用本地文件上传填充的附件字段。
    """
    rules = _run_rules(body, form, resolver, attachment_field_ids)
    if rules.problems:
        raise FormGuardError("表单校验未通过，未发送写请求：" + "；".join(rules.problems))
    return rules.notes


def check_create_rules(body: dict, form: dict, resolver: ApiResolver, *, attachment_field_ids=()):
    """提交前预检：与 ``apply_create_rules`` 走同样的步骤，但不抛出，返回 ``(notes, problems)``。"""
    try:
        rules = _run_rules(body, form, resolver, attachment_field_ids)
    except FormGuardError as exc:
        return [], [str(exc)]
    return rules.notes, rules.problems


def _run_rules(body: dict, form: dict, resolver: ApiResolver, attachment_field_ids) -> "_FormRules":
    rules = _FormRules(body, form, resolver, attachment_field_ids)
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        rules.normalize_values()
        rules.apply_defaults()
        rules.apply_links()
        rules.apply_references()
        rules.apply_row_references()
        rules.apply_row_formulas()
        rules.apply_top_formulas()
        rules.validate_required()
        rules.validate_submit_rules()
        rules.strip_references()
    return rules


# ── CLI ───────────────────────────────────────────────────────────────
def resolver_from_env() -> ApiResolver:
    from order_batch import OrderBatchError, UrllibTransport

    try:
        transport = UrllibTransport(
            str(os.environ.get("CORDYS_CRM_DOMAIN") or ""),
            str(os.environ.get("CORDYS_ACCESS_KEY") or ""),
            str(os.environ.get("CORDYS_SECRET_KEY") or ""),
        )
    except OrderBatchError as exc:
        raise FormGuardError(str(exc)) from exc
    return ApiResolver(
        lambda path: transport.request("GET", path).text,
        lambda path, body: transport.request("POST", path, body).text,
    )


def load_form(form_raw: str, module: str) -> dict:
    """解析实时表单响应。守卫只用 fields；工商抬头等系统表单的 formProp 为 null，不能当错误。"""
    try:
        wrapper = json.loads(form_raw)
    except json.JSONDecodeError as exc:
        raise FormGuardError(f"{module} 表单配置 JSON 解析失败：{exc}") from exc
    data = wrapper.get("data") if isinstance(wrapper, dict) else None
    if (
        not isinstance(wrapper, dict)
        or wrapper.get("code") != 100200
        or not isinstance(data, dict)
        or not isinstance(data.get("fields"), list)
    ):
        raise FormGuardError(f"{module} 表单配置缺少 code=100200 或 data.fields")
    return data


def _attachment_ids(plan_path: str) -> set[str]:
    if not plan_path:
        return set()
    try:
        plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormGuardError(f"附件计划读取失败：{exc}") from exc
    return {str(f.get("fieldId")) for f in plan.get("fields") or [] if isinstance(f, dict)}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] not in (["create"], ["check"]) or len(args) not in (4, 5):
        print("错误: 用法: form_guard.py create|check <module> <body> <form> [attachment-plan]", file=sys.stderr)
        return 1
    operation, module, body_path, form_path = args[:4]
    plan_path = args[4] if len(args) == 5 else ""
    if operation == "check":
        # 预检：结果以 JSON 输出到 stdout，有问题也返回 0，由调用方据 passed 决定下一步。
        try:
            body = json.loads(Path(body_path).read_text(encoding="utf-8"))
            form = load_form(Path(form_path).read_text(encoding="utf-8"), module)
            notes, problems = check_create_rules(
                body, form, resolver_from_env(), attachment_field_ids=_attachment_ids(plan_path)
            )
        except (PayloadTransportError, OSError, json.JSONDecodeError) as exc:
            notes, problems, body = [], [str(exc)], None
        print(json.dumps({"code": 100200, "data": {
            "dryRun": True, "passed": not problems, "problems": problems, "notes": notes, "body": body,
        }}, ensure_ascii=False))
        return 0
    try:
        body = json.loads(Path(body_path).read_text(encoding="utf-8"))
        form = load_form(Path(form_path).read_text(encoding="utf-8"), module)
        notes = apply_create_rules(
            body, form, resolver_from_env(), attachment_field_ids=_attachment_ids(plan_path)
        )
    except (PayloadTransportError, OSError, json.JSONDecodeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    Path(body_path).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    for note in notes:
        print(f":: 表单规则 {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
