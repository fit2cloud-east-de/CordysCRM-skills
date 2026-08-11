"""UTF-8 transport helpers for query and write payloads."""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_DOWN, localcontext
from pathlib import Path


class PayloadTransportError(ValueError):
    """The payload could not be decoded, parsed, or normalized."""


FOLLOW_SOURCE_FIELDS = {
    "lead": "clueId",
    "account": "customerId",
    "opportunity": "opportunityId",
}
FOLLOW_PLAN_STATUSES = {
    "ALL",
    "PREPARED",
    "UNDERWAY",
    "COMPLETED",
    "CANCELLED",
}
ORDER_CREATE_DEFAULTS = (
    ("交付团队", "线下团队"),
    ("交付形式", "远程交付"),
    ("正式license申请状态", "未申请"),
    ("是否专项交付", "否"),
)
ORDER_NAME_SUFFIX = "-${订单编号}"
ORDER_SPLIT_REQUEST_FIELD = "splitByProductIncome"
ORDER_CONTRACT_ONLY_CHILD_LABELS = {"关联订单编号", "拆分规则"}


def read_utf8(stream=None) -> str:
    """Read UTF-8 (optionally BOM-prefixed) text from a binary/text stream."""
    stream = stream or sys.stdin
    binary = getattr(stream, "buffer", None)
    if binary is not None:
        raw = binary.read()
        if isinstance(raw, bytes):
            try:
                return raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise PayloadTransportError(
                    f"stdin 不是合法 UTF-8：{exc}"
                ) from exc
    text = stream.read()
    if isinstance(text, bytes):
        try:
            return text.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise PayloadTransportError(
                f"stdin 不是合法 UTF-8：{exc}"
            ) from exc
    return text.lstrip("\ufeff")


def parse_json(raw: str, *, json_only=False, who="查询") -> dict:
    """Parse a JSON object without treating malformed JSON as a keyword."""
    raw = (raw or "").lstrip("\ufeff").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        if json_only or raw.startswith(("{", "[")):
            raise PayloadTransportError(f"{who} JSON 解析失败: {exc}") from exc
        return {"keyword": raw}
    if not isinstance(value, dict):
        if json_only or raw.startswith(("{", "[")):
            raise PayloadTransportError(f"{who} payload 顶层必须是 JSON 对象")
        return {"keyword": raw}
    return value


def _load_schema_modules(schema_path: str | os.PathLike) -> dict:
    """Load and validate the synchronized module map."""
    try:
        with open(schema_path, encoding="utf-8") as stream:
            schema = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise PayloadTransportError(f"读取本地字段 schema 失败: {exc}") from exc

    modules = schema.get("modules") if isinstance(schema, dict) else None
    if not isinstance(modules, dict):
        raise PayloadTransportError("本地字段 schema 缺少 modules 对象")
    return modules


def module_has_subforms(module: str, schema_path: str | os.PathLike) -> bool:
    """Return whether the synchronized module schema contains child tables."""
    modules = _load_schema_modules(schema_path)

    # account/contact is the public CLI alias of the contact schema. Follow
    # write routes have no child tables and may not have route-shaped keys.
    schema_module = "contact" if module == "account/contact" else module
    module_schema = modules.get(schema_module)
    if not isinstance(module_schema, dict):
        return False
    fields = module_schema.get("fields")
    if not isinstance(fields, dict):
        return False
    return any(
        isinstance(field, dict)
        and (
            bool(field.get("subFields"))
            or str(field.get("type", "")).startswith("SUB_")
        )
        for field in fields.values()
    )


def _form_field_id(field: dict) -> str:
    """Return the stable field identifier used by schema/form variants."""
    if not isinstance(field, dict):
        return ""
    value = field.get("fieldId")
    if value in (None, ""):
        value = field.get("id")
    return "" if value in (None, "") else str(value)


def _form_child_fields(parent: dict) -> list[dict]:
    """Normalize live form subFields from list/dict shapes."""
    value = parent.get("subFields") if isinstance(parent, dict) else None
    if isinstance(value, list):
        return [field for field in value if isinstance(field, dict)]
    if isinstance(value, dict):
        return [field for field in value.values() if isinstance(field, dict)]
    return []


def _decimal_input(value, context: str) -> Decimal:
    """Parse one finite numeric formula input or fail before the write."""
    if (
        value is None
        or value == ""
        or value == []
        or (isinstance(value, str) and not value.strip())
        or isinstance(value, (bool, dict, list))
    ):
        raise PayloadTransportError(f"{context}不能为空，无法计算公式")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise PayloadTransportError(
            f"{context}必须是可计算数字：{value}"
        ) from exc
    if not number.is_finite():
        raise PayloadTransportError(f"{context}必须是有限数字：{value}")
    return number


def _formula_decimal_input(value, field: dict | None, context: str) -> Decimal:
    """Parse a formula operand using the form field's display semantics.

    Cordys stores ``INPUT_NUMBER`` fields configured as ``percent`` as the
    human-facing value (for example, six percent is persisted as ``6``), while
    the browser formula engine evaluates that operand as ``0.06``.  Keep the
    submitted business value untouched and apply the scale only while
    evaluating formulas.
    """
    number = _decimal_input(value, context)
    number_format = (
        str(field.get("numberFormat") or "").strip().lower()
        if isinstance(field, dict)
        else ""
    )
    if number_format == "percent":
        number /= Decimal(100)
    return number


def _json_number(value: Decimal, context: str):
    """Convert a finite Decimal to a JSON number without trailing .0 noise."""
    if value == value.to_integral_value():
        return int(value)
    try:
        number = float(format(value, "f"))
    except (OverflowError, ValueError) as exc:
        raise PayloadTransportError(
            f"{context}超出 JSON 可保存的数字范围"
        ) from exc
    if not math.isfinite(number):
        raise PayloadTransportError(f"{context}超出 JSON 可保存的有限数字范围")
    return number


def _required_identifier(value, context: str) -> str:
    """Normalize one API identifier without accepting structured values."""
    if (
        value is None
        or value == ""
        or value == []
        or isinstance(value, (bool, dict, list))
    ):
        raise PayloadTransportError(f"{context}不能为空且必须传 ID")
    value_text = str(value).strip()
    if not value_text or value_text == "-":
        raise PayloadTransportError(f"{context}不能为空且必须传 ID")
    return value_text


def order_contract_id(raw: str) -> str:
    """Read the contract id needed for the order-create inheritance GET."""
    body = parse_json(raw, json_only=True, who="create")
    return _required_identifier(
        body.get("contractId"),
        "订单创建 contractId（必须取目标合同详情 ID）",
    )


def _parse_order_contract_response(contract_raw: str, expected_id: str) -> dict:
    """Validate the contract detail used to hydrate one order request."""
    try:
        wrapper = json.loads(contract_raw)
    except json.JSONDecodeError as exc:
        raise PayloadTransportError(
            f"订单创建读取合同详情 JSON 失败: {exc}"
        ) from exc
    data = wrapper.get("data") if isinstance(wrapper, dict) else None
    if (
        not isinstance(wrapper, dict)
        or wrapper.get("code") != 100200
        or not isinstance(data, dict)
        or str(data.get("id") or "") != expected_id
        or not isinstance(data.get("moduleFields"), list)
    ):
        raise PayloadTransportError(
            "订单创建无法取得匹配 contractId 的完整合同详情，"
            "不会发送写请求"
        )
    return data


def _value_is_missing(value) -> bool:
    return (
        value is None
        or value == ""
        or value == []
        or (isinstance(value, str) and value.strip() in {"", "-"})
        or isinstance(value, (bool, dict, list))
    )


def _option_maps(field: dict) -> tuple[dict[str, str], dict[str, str]]:
    options = field.get("options") if isinstance(field, dict) else None
    label_to_value = {}
    value_to_label = {}
    if not isinstance(options, list):
        return label_to_value, value_to_label
    for option in options:
        if not isinstance(option, dict):
            continue
        label = option.get("label")
        value = option.get("value")
        if label is None or value is None:
            continue
        label_text = str(label)
        value_text = str(value)
        label_to_value[label_text] = value_text
        value_to_label[value_text] = label_text
    return label_to_value, value_to_label


def _bridge_contract_value(
    source_field: dict,
    target_field: dict,
    value,
    context: str,
):
    """Map contract SELECT/RADIO ids to the order option with the same label."""
    target_type = str(target_field.get("type") or "")
    if target_type not in {"SELECT", "RADIO"}:
        return value

    source_label_to_value, source_value_to_label = _option_maps(source_field)
    target_label_to_value, target_value_to_label = _option_maps(target_field)
    value_text = _required_identifier(value, context)
    if value_text in source_value_to_label:
        label = source_value_to_label[value_text]
    elif value_text in source_label_to_value:
        label = value_text
    elif value_text in target_value_to_label:
        return value_text
    elif value_text in target_label_to_value:
        return target_label_to_value[value_text]
    else:
        raise PayloadTransportError(
            f"{context} 无法从合同选项解析中文标签：{value_text}"
        )
    if label not in target_label_to_value:
        raise PayloadTransportError(
            f"{context} 的合同选项“{label}”在订单目标字段中不存在"
        )
    return target_label_to_value[label]


def _contract_value_matches(
    source_field: dict,
    target_field: dict,
    source_value,
    target_value,
) -> bool:
    """Compare a contract value with an order value after option bridging."""
    try:
        mapped = _bridge_contract_value(
            source_field,
            target_field,
            source_value,
            "订单创建合同子表行匹配",
        )
        target_type = str(target_field.get("type") or "")
        if target_type in {"SELECT", "RADIO"}:
            target_label_to_value, target_value_to_label = _option_maps(
                target_field
            )
            target_text = str(target_value).strip()
            if target_text in target_label_to_value:
                target_text = target_label_to_value[target_text]
            elif target_text not in target_value_to_label:
                return False
            return str(mapped) == target_text
        if target_type == "INPUT_NUMBER":
            return _decimal_input(mapped, "合同子表匹配") == _decimal_input(
                target_value, "订单子表匹配"
            )
        return str(mapped) == str(target_value)
    except PayloadTransportError:
        return False


def order_split_enabled(raw: str) -> bool:
    """Return whether one order create request uses automatic split planning.

    Automatic ``product/service + income type`` splitting is the default.
    ``false`` remains as a narrow compatibility escape hatch for an already
    materialized single-order payload; runtime SOPs must use the default.
    """
    body = parse_json(raw, json_only=True, who="create")
    value = body.get(ORDER_SPLIT_REQUEST_FIELD, True)
    if not isinstance(value, bool):
        raise PayloadTransportError(
            f"订单创建 {ORDER_SPLIT_REQUEST_FIELD} 必须是 true 或 false"
        )
    return value


def _schema_field_by_label(
    fields: dict,
    label: str,
    context: str,
    *,
    field_type_prefix: str = "",
) -> tuple[str, dict]:
    matches = [
        (str(field_id), field)
        for field_id, field in fields.items()
        if isinstance(field, dict)
        and str(field.get("label") or "") == label
        and (
            not field_type_prefix
            or str(field.get("type") or "").startswith(field_type_prefix)
        )
    ]
    if len(matches) != 1:
        raise PayloadTransportError(f"{context}无法唯一定位字段：{label}")
    return matches[0]


def _module_field_values(record: dict, context: str) -> dict[str, object]:
    values = {}
    module_fields = record.get("moduleFields")
    if not isinstance(module_fields, list):
        raise PayloadTransportError(f"{context}缺少 moduleFields 数组")
    for item in module_fields:
        if not isinstance(item, dict) or item.get("fieldId") in (None, ""):
            continue
        field_id = str(item["fieldId"])
        if field_id in values:
            raise PayloadTransportError(
                f"{context} moduleFields 字段重复：{field_id}"
            )
        values[field_id] = item.get("fieldValue")
    return values


def _option_label(field: dict, value, context: str) -> str:
    label_to_value, value_to_label = _option_maps(field)
    value_text = _required_identifier(value, context)
    if value_text in value_to_label:
        return value_to_label[value_text]
    if value_text in label_to_value:
        return value_text
    allowed = "、".join(label_to_value)
    raise PayloadTransportError(
        f"{context}的值无效：{value_text}；允许：{allowed}"
    )


def _parse_product_catalog(product_raw: str) -> dict[str, str]:
    try:
        wrapper = json.loads(product_raw)
    except json.JSONDecodeError as exc:
        raise PayloadTransportError(
            f"订单拆单读取产品目录 JSON 失败: {exc}"
        ) from exc
    data = wrapper.get("data") if isinstance(wrapper, dict) else None
    rows = data.get("list") if isinstance(data, dict) else None
    if (
        not isinstance(wrapper, dict)
        or wrapper.get("code") != 100200
        or not isinstance(rows, list)
    ):
        raise PayloadTransportError(
            "订单拆单无法取得完整产品目录（需要 code=100200 和 data.list）"
        )
    total = data.get("total")
    if isinstance(total, int) and total > len(rows):
        raise PayloadTransportError(
            f"订单拆单产品目录未取全：返回 {len(rows)} / {total} 条"
        )
    catalog = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        product_id = row.get("id")
        name = row.get("name")
        if product_id in (None, "") or name in (None, ""):
            continue
        product_id = str(product_id).strip()
        name = str(name).strip()
        if not product_id or not name:
            continue
        previous = catalog.get(product_id)
        if previous is not None and previous != name:
            raise PayloadTransportError(
                f"订单拆单产品目录 ID 重复且名称冲突：{product_id}"
            )
        catalog[product_id] = name
    if not catalog:
        raise PayloadTransportError("订单拆单产品目录为空")
    return catalog


def _mapped_order_row(
    source_row: dict,
    source_parent: dict,
    target_parent: dict,
    parent_label: str,
    row_index: int,
) -> dict:
    """Map one exact contract row into the matching order child schema."""
    source_children = source_parent.get("subFields")
    target_children = target_parent.get("subFields")
    if not isinstance(source_children, dict) or not isinstance(
        target_children, dict
    ):
        raise PayloadTransportError(
            f"合同/订单子表 {parent_label} 缺少本地子字段 schema"
        )

    target_by_label = {}
    for target_id, target_field in target_children.items():
        if not isinstance(target_field, dict):
            continue
        label = str(target_field.get("label") or "")
        if label:
            target_by_label.setdefault(label, []).append(
                (str(target_id), target_field)
            )

    mapped = {}
    for source_id, source_field in source_children.items():
        if not isinstance(source_field, dict):
            continue
        label = str(source_field.get("label") or "")
        if not label or source_field.get("type") == "FORMULA":
            continue
        value = source_row.get(str(source_id))
        if _value_is_missing(value):
            continue
        matches = target_by_label.get(label) or []
        if not matches:
            if label in ORDER_CONTRACT_ONLY_CHILD_LABELS:
                continue
            raise PayloadTransportError(
                f"合同子表 {parent_label} 第 {row_index} 行字段 {label} "
                "在订单同名子表中没有映射；不会静默丢弃"
            )
        if len(matches) != 1:
            raise PayloadTransportError(
                f"订单子表 {parent_label} 无法唯一定位子字段：{label}"
            )
        target_id, target_field = matches[0]
        if target_field.get("type") == "FORMULA":
            continue
        mapped[target_id] = _bridge_contract_value(
            source_field,
            target_field,
            value,
            f"订单子表 {parent_label} 第 {row_index} 行字段 {label}",
        )

    source_price_sub = source_row.get("price_sub")
    if not _value_is_missing(source_price_sub):
        mapped["price_sub"] = str(source_price_sub).strip()
    return mapped


def _hydrate_order_from_contract(
    body: dict,
    modules: dict,
    order_fields: dict,
    contract_data: dict | None,
) -> None:
    """Hydrate every active order child row from its exact contract source row.

    The synchronized contract/order schemas provide the stable
    ``parent-label + child-label`` bridge.  ``price_sub`` is deliberately
    preserved: it identifies the selected PRICE sub-row and is what lets
    Cordys resolve the read-only ``*_ref_*`` projection columns after create.
    Contract row ``id`` is never copied because the order receives a new row
    id of its own.
    """
    if contract_data is None:
        return

    contract_id = _required_identifier(
        body.get("contractId"),
        "订单创建 contractId（必须取目标合同详情 ID）",
    )
    body["contractId"] = contract_id

    for key, label in (("owner", "负责人"), ("customerId", "客户")):
        inherited = _required_identifier(
            contract_data.get(key), f"合同详情 {label}"
        )
        supplied = body.get(key)
        if _value_is_missing(supplied):
            body[key] = inherited
        elif str(supplied).strip() != inherited:
            raise PayloadTransportError(
                f"订单创建 {key} 必须与合同详情保持一致：{inherited}"
            )
        else:
            body[key] = inherited

    contract_schema = modules.get("contract")
    contract_fields = (
        contract_schema.get("fields")
        if isinstance(contract_schema, dict)
        else None
    )
    if not isinstance(contract_fields, dict):
        raise PayloadTransportError("订单创建无法读取本地 contract 字段 schema")

    contract_values = {}
    for item in contract_data.get("moduleFields") or []:
        if not isinstance(item, dict) or item.get("fieldId") in (None, ""):
            continue
        field_id = str(item["fieldId"])
        if field_id in contract_values:
            raise PayloadTransportError(
                f"合同详情 moduleFields 字段重复：{field_id}"
            )
        contract_values[field_id] = item.get("fieldValue")

    module_fields = body.get("moduleFields")
    if not isinstance(module_fields, list):
        return
    for item in module_fields:
        if not isinstance(item, dict) or item.get("fieldId") in (None, ""):
            continue
        target_parent_id = str(item["fieldId"])
        target_parent = order_fields.get(target_parent_id)
        if not isinstance(target_parent, dict) or not str(
            target_parent.get("type") or ""
        ).startswith("SUB_"):
            continue
        target_rows = item.get("fieldValue")
        if target_rows in (None, "", []):
            continue
        if not isinstance(target_rows, list):
            continue

        parent_label = str(
            target_parent.get("label") or target_parent_id
        )
        source_parent_matches = [
            (str(field_id), field)
            for field_id, field in contract_fields.items()
            if isinstance(field, dict)
            and str(field.get("type") or "").startswith("SUB_")
            and str(field.get("label") or "") == parent_label
        ]
        if len(source_parent_matches) != 1:
            raise PayloadTransportError(
                f"订单子表 {parent_label} 无法在本地合同 form 中唯一定位同名源子表"
            )
        source_parent_id, source_parent = source_parent_matches[0]
        source_rows = contract_values.get(source_parent_id)
        if not isinstance(source_rows, list) or not source_rows:
            raise PayloadTransportError(
                f"合同详情子表 {parent_label} 没有可继承的源行"
            )
        source_rows = [row for row in source_rows if isinstance(row, dict)]
        if not source_rows:
            raise PayloadTransportError(
                f"合同详情子表 {parent_label} 没有合法对象行"
            )

        target_children = target_parent.get("subFields")
        source_children = source_parent.get("subFields")
        if not isinstance(target_children, dict) or not isinstance(
            source_children, dict
        ):
            raise PayloadTransportError(
                f"订单/合同子表 {parent_label} 缺少本地子字段 schema"
            )

        source_by_label = {}
        for source_id, source_field in source_children.items():
            if not isinstance(source_field, dict):
                continue
            label = str(source_field.get("label") or "")
            if not label:
                continue
            source_by_label.setdefault(label, []).append(
                (str(source_id), source_field)
            )
        common_children = []
        for target_id, target_field in target_children.items():
            if not isinstance(target_field, dict):
                continue
            label = str(target_field.get("label") or "")
            matches = source_by_label.get(label) or []
            if len(matches) == 1:
                source_id, source_field = matches[0]
                common_children.append(
                    (
                        str(target_id),
                        target_field,
                        source_id,
                        source_field,
                    )
                )

        for row_index, target_row in enumerate(target_rows, start=1):
            if not isinstance(target_row, dict):
                continue
            # A contract child id belongs to another table and must never be
            # reused as the new order child id.
            target_row.pop("id", None)
            candidates = list(source_rows)
            supplied_price_sub = target_row.get("price_sub")
            if not _value_is_missing(supplied_price_sub):
                candidates = [
                    row
                    for row in candidates
                    if str(row.get("price_sub") or "")
                    == str(supplied_price_sub).strip()
                ]

            selector_pairs = [
                pair
                for pair in common_children
                if pair[1].get("type") == "DATA_SOURCE"
                and not pair[1].get("resourceFieldId")
                and not _value_is_missing(target_row.get(pair[0]))
            ]
            selector_pairs.sort(
                key=lambda pair: 0
                if str(pair[1].get("label") or "") in {"产品", "服务"}
                else 1
            )
            for target_id, target_field, source_id, source_field in selector_pairs:
                candidates = [
                    row
                    for row in candidates
                    if not _value_is_missing(row.get(source_id))
                    and _contract_value_matches(
                        source_field,
                        target_field,
                        row.get(source_id),
                        target_row.get(target_id),
                    )
                ]
                if len(candidates) <= 1:
                    break

            # If a parent has no product/service selector, use other supplied
            # same-label values only to disambiguate; never override an
            # explicit split value merely for matching.
            if len(candidates) > 1:
                for target_id, target_field, source_id, source_field in common_children:
                    target_value = target_row.get(target_id)
                    if _value_is_missing(target_value):
                        continue
                    narrowed = [
                        row
                        for row in candidates
                        if not _value_is_missing(row.get(source_id))
                        and _contract_value_matches(
                            source_field,
                            target_field,
                            row.get(source_id),
                            target_value,
                        )
                    ]
                    if narrowed:
                        candidates = narrowed
                    if len(candidates) == 1:
                        break

            if len(candidates) != 1:
                raise PayloadTransportError(
                    f"订单子表 {parent_label} 第 {row_index} 行无法唯一匹配合同源行；"
                    "同一服务存在多行时必须携带合同源行 price_sub"
                )
            source_row = candidates[0]

            for target_id, target_field, source_id, source_field in common_children:
                if target_field.get("type") == "FORMULA":
                    continue
                source_value = source_row.get(source_id)
                if _value_is_missing(source_value):
                    continue
                is_projection = bool(target_field.get("resourceFieldId"))
                if not is_projection and not _value_is_missing(
                    target_row.get(target_id)
                ):
                    continue
                target_row[target_id] = _bridge_contract_value(
                    source_field,
                    target_field,
                    source_value,
                    f"订单子表 {parent_label} 第 {row_index} 行字段 "
                    f"{target_field.get('label') or target_id}",
                )

            has_price_projection = any(
                isinstance(field, dict) and field.get("resourceFieldId")
                for field in target_children.values()
            )
            source_price_sub = source_row.get("price_sub")
            if has_price_projection and _value_is_missing(source_price_sub):
                raise PayloadTransportError(
                    f"合同子表 {parent_label} 匹配源行缺少 price_sub，"
                    "无法建立价格子行关联"
                )
            if not _value_is_missing(source_price_sub):
                if (
                    not _value_is_missing(supplied_price_sub)
                    and str(supplied_price_sub).strip()
                    != str(source_price_sub).strip()
                ):
                    raise PayloadTransportError(
                        f"订单子表 {parent_label} 第 {row_index} 行 price_sub "
                        "与合同源行不一致"
                    )
                target_row["price_sub"] = str(source_price_sub).strip()


def populate_order_subtable_formulas(
    rows: list,
    parent_id: str,
    parent_label: str,
    parent_schema: dict,
    form_config: dict,
) -> None:
    """Evaluate every current live-form formula for every active order row."""
    schema_children = parent_schema.get("subFields")
    if not isinstance(schema_children, dict):
        raise PayloadTransportError(
            f"订单子表 {parent_label} 缺少本地子字段 schema"
        )
    schema_formulas = [
        (str(field_id), field)
        for field_id, field in schema_children.items()
        if isinstance(field, dict) and field.get("type") == "FORMULA"
    ]

    live_fields = form_config.get("fields") if isinstance(form_config, dict) else None
    if not isinstance(live_fields, list):
        raise PayloadTransportError("订单实时表单缺少 fields，无法计算子表公式")
    parent_matches = [
        field
        for field in live_fields
        if isinstance(field, dict) and _form_field_id(field) == parent_id
    ]
    if len(parent_matches) != 1:
        raise PayloadTransportError(
            f"订单实时表单无法唯一定位子表 {parent_label} ({parent_id})，"
            "无法计算公式"
        )
    live_children = _form_child_fields(parent_matches[0])
    unnamed_formulas = [
        field
        for field in live_children
        if field.get("type") == "FORMULA" and not _form_field_id(field)
    ]
    if unnamed_formulas:
        raise PayloadTransportError(
            f"订单实时表单子表 {parent_label} 存在无 fieldId 的公式字段"
        )
    live_child_map = {}
    for field in live_children:
        field_id = _form_field_id(field)
        if not field_id:
            continue
        if field_id in live_child_map:
            raise PayloadTransportError(
                f"订单实时表单子表 {parent_label} 子字段 ID 重复：{field_id}"
            )
        live_child_map[field_id] = field
    formula_defs = {
        field_id: field
        for field_id, field in live_child_map.items()
        if field.get("type") == "FORMULA"
    }
    missing_formula_ids = [
        field_id
        for field_id, _ in schema_formulas
        if field_id not in formula_defs
    ]
    if missing_formula_ids:
        missing_names = "、".join(
            str(schema_children[field_id].get("label") or field_id)
            for field_id in missing_formula_ids
        )
        raise PayloadTransportError(
            f"订单实时表单子表 {parent_label} 缺少公式定义：{missing_names}"
        )
    if not formula_defs:
        return

    child_names = {
        str(field_id): str(field.get("label") or field_id)
        for field_id, field in schema_children.items()
        if isinstance(field, dict)
    }
    child_names.update(
        {
            field_id: str(field.get("name") or field.get("label") or field_id)
            for field_id, field in live_child_map.items()
        }
    )

    parsed_formulas = {}
    formula_precisions = {}
    for field_id, definition in formula_defs.items():
        raw_formula = definition.get("formula")
        if isinstance(raw_formula, str):
            try:
                spec = json.loads(raw_formula)
            except json.JSONDecodeError as exc:
                raise PayloadTransportError(
                    f"订单子表 {parent_label} 公式 "
                    f"{child_names.get(field_id, field_id)} 配置无法解析"
                ) from exc
        elif isinstance(raw_formula, dict):
            spec = raw_formula
        else:
            spec = None
        if not isinstance(spec, dict) or not isinstance(spec.get("ir"), dict):
            raise PayloadTransportError(
                f"订单子表 {parent_label} 公式 "
                f"{child_names.get(field_id, field_id)} 缺少可执行 IR"
            )
        parsed_formulas[field_id] = spec["ir"]
        precision = definition.get("precision", spec.get("precision"))
        if precision is None:
            precision = 2
        elif (
            isinstance(precision, str)
            and precision.strip().isdigit()
        ):
            precision = int(precision.strip())
        if isinstance(precision, bool) or not isinstance(precision, int):
            raise PayloadTransportError(
                f"订单子表 {parent_label} 公式 "
                f"{child_names.get(field_id, field_id)} 精度无效：{precision}"
            )
        if precision < 0 or precision > 12:
            raise PayloadTransportError(
                f"订单子表 {parent_label} 公式 "
                f"{child_names.get(field_id, field_id)} 精度无效：{precision}"
            )
        formula_precisions[field_id] = precision

    for row_index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise PayloadTransportError(
                f"订单子表 {parent_label} 第 {row_index} 行必须是对象"
            )
        computed: dict[str, Decimal] = {}
        resolving: set[str] = set()

        def resolve_field(field_id: str, formula_name: str) -> Decimal:
            if field_id in computed:
                return computed[field_id]
            if field_id in parsed_formulas:
                if field_id in resolving:
                    raise PayloadTransportError(
                        f"订单子表 {parent_label} 第 {row_index} 行公式循环引用："
                        f"{child_names.get(field_id, field_id)}"
                    )
                resolving.add(field_id)
                try:
                    value = evaluate_ir(
                        parsed_formulas[field_id],
                        child_names.get(field_id, field_id),
                    )
                finally:
                    resolving.remove(field_id)
                precision = formula_precisions[field_id]
                quantum = Decimal(1).scaleb(-precision)
                try:
                    value = value.quantize(quantum, rounding=ROUND_DOWN)
                except InvalidOperation as exc:
                    raise PayloadTransportError(
                        f"订单子表 {parent_label} 第 {row_index} 行公式 "
                        f"{child_names.get(field_id, field_id)} 结果无法按 "
                        f"{precision} 位小数保存"
                    ) from exc
                computed[field_id] = value
                return value
            source_name = child_names.get(field_id, field_id)
            source_field = live_child_map.get(field_id)
            if not isinstance(source_field, dict):
                source_field = schema_children.get(field_id)
            return _formula_decimal_input(
                row.get(field_id),
                source_field,
                f"订单子表 {parent_label} 第 {row_index} 行公式 "
                f"{formula_name} 的源字段 {source_name} ({field_id})",
            )

        def evaluate_ir(node: dict, formula_name: str) -> Decimal:
            if not isinstance(node, dict):
                raise PayloadTransportError(
                    f"订单子表 {parent_label} 公式 {formula_name} IR 节点无效"
                )
            node_type = node.get("type")
            if node_type == "literal":
                return _decimal_input(
                    node.get("value"),
                    f"订单子表 {parent_label} 公式 {formula_name} 的常量",
                )
            if node_type == "field":
                field_id = str(node.get("fieldId") or "")
                if not field_id:
                    raise PayloadTransportError(
                        f"订单子表 {parent_label} 公式 {formula_name} "
                        "引用了空 fieldId"
                    )
                return resolve_field(field_id, formula_name)
            if node_type != "binary":
                raise PayloadTransportError(
                    f"订单子表 {parent_label} 公式 {formula_name} "
                    f"包含不支持的 IR 类型：{node_type}"
                )
            left = evaluate_ir(node.get("left"), formula_name)
            right = evaluate_ir(node.get("right"), formula_name)
            operator = node.get("operator")
            if operator == "+":
                return left + right
            if operator == "-":
                return left - right
            if operator == "*":
                return left * right
            if operator == "/":
                if right == 0:
                    raise PayloadTransportError(
                        f"订单子表 {parent_label} 第 {row_index} 行公式 "
                        f"{formula_name} 的除数不能为 0"
                    )
                return left / right
            raise PayloadTransportError(
                f"订单子表 {parent_label} 公式 {formula_name} "
                f"包含不支持的运算符：{operator}"
            )

        with localcontext() as decimal_context:
            decimal_context.prec = 50
            failures = []
            for formula_id in formula_defs:
                try:
                    resolve_field(
                        formula_id, child_names.get(formula_id, formula_id)
                    )
                except PayloadTransportError as exc:
                    message = str(exc)
                    if message not in failures:
                        failures.append(message)
            if failures:
                raise PayloadTransportError("；".join(failures))
            for formula_id in formula_defs:
                formula_name = child_names.get(formula_id, formula_id)
                row[formula_id] = _json_number(
                    computed[formula_id],
                    f"订单子表 {parent_label} 第 {row_index} 行公式 "
                    f"{formula_name} 的结果",
                )


def populate_order_top_level_formulas(
    body: dict,
    order_fields: dict,
    form_config: dict,
) -> None:
    """Evaluate every current live-form order formula after child formulas."""
    live_fields = form_config.get("fields") if isinstance(form_config, dict) else None
    if not isinstance(live_fields, list):
        raise PayloadTransportError("订单实时表单缺少 fields，无法计算主表公式")

    unnamed_formulas = [
        field
        for field in live_fields
        if isinstance(field, dict)
        and field.get("type") == "FORMULA"
        and not _form_field_id(field)
    ]
    if unnamed_formulas:
        raise PayloadTransportError("订单实时表单存在无 fieldId 的主表公式")

    live_field_map = {}
    live_subfield_map = {}
    for field in live_fields:
        if not isinstance(field, dict):
            continue
        field_id = _form_field_id(field)
        if not field_id:
            continue
        if field_id in live_field_map:
            raise PayloadTransportError(
                f"订单实时表单主字段 ID 重复：{field_id}"
            )
        live_field_map[field_id] = field
        children = _form_child_fields(field)
        if children:
            live_subfield_map[field_id] = {
                _form_field_id(child): child
                for child in children
                if _form_field_id(child)
            }
    formula_defs = {
        field_id: field
        for field_id, field in live_field_map.items()
        if field.get("type") == "FORMULA"
    }
    schema_formula_ids = [
        str(field_id)
        for field_id, field in order_fields.items()
        if isinstance(field, dict) and field.get("type") == "FORMULA"
    ]
    missing_formula_ids = [
        field_id
        for field_id in schema_formula_ids
        if field_id not in formula_defs
    ]
    if missing_formula_ids:
        missing_names = "、".join(
            str(order_fields[field_id].get("label") or field_id)
            for field_id in missing_formula_ids
        )
        raise PayloadTransportError(
            f"订单实时表单缺少主表公式定义：{missing_names}"
        )
    if not formula_defs:
        return

    field_names = {
        str(field_id): str(field.get("label") or field_id)
        for field_id, field in order_fields.items()
        if isinstance(field, dict)
    }
    field_names.update(
        {
            field_id: str(field.get("name") or field.get("label") or field_id)
            for field_id, field in live_field_map.items()
        }
    )

    parsed_formulas = {}
    formula_precisions = {}
    formula_business_keys = {}
    for field_id, definition in formula_defs.items():
        formula_name = field_names.get(field_id, field_id)
        raw_formula = definition.get("formula")
        if isinstance(raw_formula, str):
            try:
                spec = json.loads(raw_formula)
            except json.JSONDecodeError as exc:
                raise PayloadTransportError(
                    f"订单主表公式 {formula_name} 配置无法解析"
                ) from exc
        elif isinstance(raw_formula, dict):
            spec = raw_formula
        else:
            spec = None
        if not isinstance(spec, dict) or not isinstance(spec.get("ir"), dict):
            raise PayloadTransportError(
                f"订单主表公式 {formula_name} 缺少可执行 IR"
            )
        parsed_formulas[field_id] = spec["ir"]
        precision = definition.get("precision", spec.get("precision"))
        if precision is None:
            precision = 2
        elif isinstance(precision, str) and precision.strip().isdigit():
            precision = int(precision.strip())
        if isinstance(precision, bool) or not isinstance(precision, int):
            raise PayloadTransportError(
                f"订单主表公式 {formula_name} 精度无效：{precision}"
            )
        if precision < 0 or precision > 12:
            raise PayloadTransportError(
                f"订单主表公式 {formula_name} 精度无效：{precision}"
            )
        formula_precisions[field_id] = precision
        schema_definition = order_fields.get(field_id)
        business_key = definition.get("businessKey")
        if not business_key and isinstance(schema_definition, dict):
            business_key = schema_definition.get("businessKey")
        formula_business_keys[field_id] = str(business_key or "").strip()

    module_fields = body.get("moduleFields")
    if not isinstance(module_fields, list):
        raise PayloadTransportError("订单创建的 moduleFields 必须是数组")
    submitted = {}
    for item in module_fields:
        if not isinstance(item, dict) or item.get("fieldId") in (None, ""):
            continue
        field_id = str(item["fieldId"])
        if field_id in submitted:
            raise PayloadTransportError(
                f"订单创建字段重复：{field_names.get(field_id, field_id)} "
                f"({field_id})"
            )
        submitted[field_id] = item

    computed: dict[str, Decimal] = {}
    resolving: set[str] = set()

    def scalar(value, context: str) -> Decimal:
        if isinstance(value, list):
            raise PayloadTransportError(
                f"{context}是子表多行值，必须放在 SUM 中聚合"
            )
        return value

    def resolve_formula(field_id: str) -> Decimal:
        if field_id in computed:
            return computed[field_id]
        formula_name = field_names.get(field_id, field_id)
        if field_id in resolving:
            raise PayloadTransportError(
                f"订单主表公式循环引用：{formula_name}"
            )
        resolving.add(field_id)
        try:
            value = scalar(
                evaluate_ir(parsed_formulas[field_id], formula_name),
                f"订单主表公式 {formula_name} 的结果",
            )
        finally:
            resolving.remove(field_id)
        precision = formula_precisions[field_id]
        quantum = Decimal(1).scaleb(-precision)
        try:
            value = value.quantize(quantum, rounding=ROUND_DOWN)
        except InvalidOperation as exc:
            raise PayloadTransportError(
                f"订单主表公式 {formula_name} 结果无法按 "
                f"{precision} 位小数保存"
            ) from exc
        computed[field_id] = value
        return value

    def resolve_field(
        field_id: str,
        formula_name: str,
        source_name: str = "",
    ):
        if field_id in parsed_formulas:
            return resolve_formula(field_id)
        source_name = source_name or field_names.get(field_id, field_id)
        if "." in field_id:
            parent_id, child_id = field_id.split(".", 1)
            parent_item = submitted.get(parent_id)
            if parent_item is None or parent_item.get("fieldValue") in (
                None,
                "",
                [],
            ):
                # A SUM over an inactive child table contributes zero.
                return []
            rows = parent_item.get("fieldValue")
            if not isinstance(rows, list):
                raise PayloadTransportError(
                    f"订单主表公式 {formula_name} 的聚合源子表 "
                    f"{source_name} ({parent_id}) 必须是行数组"
                )
            values = []
            for row_index, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    raise PayloadTransportError(
                        f"订单主表公式 {formula_name} 的聚合源子表 "
                        f"{source_name} 第 {row_index} 行必须是对象"
                    )
                values.append(
                    _formula_decimal_input(
                        row.get(child_id),
                        (live_subfield_map.get(parent_id) or {}).get(child_id),
                        f"订单主表公式 {formula_name} 的源字段 "
                        f"{source_name} ({field_id}) 第 {row_index} 行",
                    )
                )
            return values
        item = submitted.get(field_id)
        value = item.get("fieldValue") if item is not None else body.get(field_id)
        return _formula_decimal_input(
            value,
            live_field_map.get(field_id),
            f"订单主表公式 {formula_name} 的源字段 "
            f"{source_name} ({field_id})",
        )

    def evaluate_ir(node: dict, formula_name: str):
        if not isinstance(node, dict):
            raise PayloadTransportError(
                f"订单主表公式 {formula_name} IR 节点无效"
            )
        node_type = node.get("type")
        if node_type == "literal":
            return _decimal_input(
                node.get("value"),
                f"订单主表公式 {formula_name} 的常量",
            )
        if node_type == "field":
            field_id = str(node.get("fieldId") or "")
            if not field_id:
                raise PayloadTransportError(
                    f"订单主表公式 {formula_name} 引用了空 fieldId"
                )
            return resolve_field(
                field_id,
                formula_name,
                str(node.get("name") or ""),
            )
        if node_type == "function":
            function_name = str(node.get("name") or "").upper()
            if function_name != "SUM":
                raise PayloadTransportError(
                    f"订单主表公式 {formula_name} 包含不支持的函数："
                    f"{function_name or '<empty>'}"
                )
            args = node.get("args")
            if not isinstance(args, list):
                raise PayloadTransportError(
                    f"订单主表公式 {formula_name} 的 SUM 参数必须是数组"
                )
            total = Decimal(0)
            for arg in args:
                value = evaluate_ir(arg, formula_name)
                if isinstance(value, list):
                    total += sum(value, Decimal(0))
                else:
                    total += value
            return total
        if node_type != "binary":
            raise PayloadTransportError(
                f"订单主表公式 {formula_name} 包含不支持的 IR 类型："
                f"{node_type}"
            )
        left = scalar(
            evaluate_ir(node.get("left"), formula_name),
            f"订单主表公式 {formula_name} 的左操作数",
        )
        right = scalar(
            evaluate_ir(node.get("right"), formula_name),
            f"订单主表公式 {formula_name} 的右操作数",
        )
        operator = node.get("operator")
        if operator == "+":
            return left + right
        if operator == "-":
            return left - right
        if operator == "*":
            return left * right
        if operator == "/":
            if right == 0:
                raise PayloadTransportError(
                    f"订单主表公式 {formula_name} 的除数不能为 0"
                )
            return left / right
        raise PayloadTransportError(
            f"订单主表公式 {formula_name} 包含不支持的运算符：{operator}"
        )

    with localcontext() as decimal_context:
        decimal_context.prec = 50
        failures = []
        for formula_id in formula_defs:
            try:
                resolve_formula(formula_id)
            except PayloadTransportError as exc:
                message = str(exc)
                if message not in failures:
                    failures.append(message)
        if failures:
            raise PayloadTransportError("；".join(failures))
        for formula_id in formula_defs:
            formula_name = field_names.get(formula_id, formula_id)
            result = _json_number(
                computed[formula_id],
                f"订单主表公式 {formula_name} 的结果",
            )
            item = submitted.get(formula_id)
            business_key = formula_business_keys.get(formula_id, "")
            if business_key:
                body[business_key] = result
                if item is not None:
                    module_fields.remove(item)
                    submitted.pop(formula_id, None)
            elif item is None:
                item = {"fieldId": formula_id, "fieldValue": result}
                module_fields.append(item)
                submitted[formula_id] = item
            else:
                item["fieldValue"] = result


def apply_order_create_rules(
    body: dict,
    schema_path: str | os.PathLike,
    form_config: dict,
    contract_data: dict | None = None,
) -> dict:
    """Apply deterministic order-create rules before the first write request."""
    modules = _load_schema_modules(schema_path)
    order_schema = modules.get("order")
    fields = order_schema.get("fields") if isinstance(order_schema, dict) else None
    if not isinstance(fields, dict):
        raise PayloadTransportError("订单创建无法读取本地 order 字段 schema")

    module_fields = body.get("moduleFields")
    if module_fields is None:
        module_fields = []
        body["moduleFields"] = module_fields
    if not isinstance(module_fields, list):
        raise PayloadTransportError("订单创建的 moduleFields 必须是数组")

    body["contractId"] = _required_identifier(
        body.get("contractId"),
        "订单创建 contractId（必须取目标合同详情 ID）",
    )
    _hydrate_order_from_contract(
        body,
        modules,
        fields,
        contract_data,
    )

    def schema_field(field_label: str) -> tuple[str, dict]:
        matches = [
            (str(field_id), field)
            for field_id, field in fields.items()
            if isinstance(field, dict) and field.get("label") == field_label
        ]
        if len(matches) != 1:
            raise PayloadTransportError(
                f"订单创建无法唯一定位字段：{field_label}"
            )
        return matches[0]

    def submitted_field(field_id: str, field_label: str) -> dict | None:
        matches = [
            item
            for item in module_fields
            if isinstance(item, dict)
            and str(item.get("fieldId", "")) == field_id
        ]
        if len(matches) > 1:
            raise PayloadTransportError(
                f"订单创建字段重复：{field_label} ({field_id})"
            )
        return matches[0] if matches else None

    def required_scalar(value, context: str) -> str:
        if (
            value is None
            or value == ""
            or value == []
            or isinstance(value, (bool, dict, list))
        ):
            raise PayloadTransportError(f"{context}不能为空且必须传 ID")
        value_text = str(value).strip()
        if not value_text or value_text == "-":
            raise PayloadTransportError(f"{context}不能为空且必须传 ID")
        return value_text

    def value_is_missing(value) -> bool:
        return _value_is_missing(value)

    def normalize_select(field: dict, value, context: str) -> tuple[str, str]:
        options = field.get("options")
        if not isinstance(options, list):
            raise PayloadTransportError(f"{context}缺少当前 schema 选项")
        label_to_value = {
            str(option.get("label")): str(option.get("value"))
            for option in options
            if isinstance(option, dict)
            and option.get("label") is not None
            and option.get("value") is not None
        }
        value_to_label = {
            option_value: option_label
            for option_label, option_value in label_to_value.items()
        }
        value_text = required_scalar(value, context)
        if value_text in label_to_value:
            return label_to_value[value_text], value_text
        if value_text in value_to_label:
            return value_text, value_to_label[value_text]
        allowed = "、".join(label_to_value)
        raise PayloadTransportError(
            f"{context}的值无效：{value_text}；允许：{allowed}"
        )

    contract_code_id, _ = schema_field("合同编码")
    product_type_id, _ = schema_field("产品类型")
    contract_code_item = submitted_field(contract_code_id, "合同编码")
    product_type_item = submitted_field(product_type_id, "产品类型")
    contract_code = (
        str(contract_code_item.get("fieldValue", "")).strip()
        if contract_code_item
        else ""
    )
    product_type_value = (
        str(product_type_item.get("fieldValue", "")).strip()
        if product_type_item
        else ""
    )
    if not contract_code:
        raise PayloadTransportError("订单创建必须在 moduleFields 中提供合同编码")
    if not product_type_value:
        raise PayloadTransportError("订单创建必须在 moduleFields 中提供产品类型")

    owner = required_scalar(
        body.get("owner"),
        "订单创建 owner（必须取合同详情的负责人 userId）",
    )
    body["owner"] = owner

    name = body.get("name")
    if name in (None, "") and body.get("订单名") not in (None, ""):
        name = body.get("订单名")
    body.pop("订单名", None)
    if not isinstance(name, str) or not name.strip():
        raise PayloadTransportError(
            "订单创建 name 不能为空，格式为："
            "合同编码-产品类型中文标签-${订单编号}"
        )
    name = name.strip()
    expected_prefix = f"{contract_code}-"
    if not name.startswith(expected_prefix) or not name.endswith(
        ORDER_NAME_SUFFIX
    ):
        raise PayloadTransportError(
            "订单创建 name 格式错误，应为："
            "合同编码-产品类型中文标签-${订单编号}；"
            "第三段必须按字面量固定传入"
        )
    product_type_label = name[
        len(expected_prefix) : -len(ORDER_NAME_SUFFIX)
    ].strip()
    if not product_type_label or product_type_label == product_type_value:
        raise PayloadTransportError(
            "订单创建 name 第二段必须是产品类型中文标签，不能留空或传产品 ID"
        )
    body["name"] = (
        f"{contract_code}-{product_type_label}{ORDER_NAME_SUFFIX}"
    )

    income_type_id, income_type_field = schema_field("收入类型")
    income_type_item = submitted_field(income_type_id, "收入类型")
    if income_type_item is None:
        raise PayloadTransportError(
            "订单创建必须根据合同目标子表行提供顶层收入类型"
        )
    income_type_value, income_type_label = normalize_select(
        income_type_field,
        income_type_item.get("fieldValue"),
        "订单顶层收入类型",
    )
    income_type_item["fieldValue"] = income_type_value

    for item in module_fields:
        if not isinstance(item, dict):
            continue
        parent_id = str(item.get("fieldId", ""))
        parent = fields.get(parent_id)
        if not isinstance(parent, dict) or not str(
            parent.get("type", "")
        ).startswith("SUB_"):
            continue
        rows = item.get("fieldValue")
        if rows in (None, "", []):
            continue
        parent_label = str(parent.get("label") or parent_id)
        if not isinstance(rows, list):
            raise PayloadTransportError(
                f"订单子表 {parent_label} 的 fieldValue 必须是行数组"
            )
        local_sub_fields = parent.get("subFields")
        if not isinstance(local_sub_fields, dict):
            raise PayloadTransportError(
                f"订单子表 {parent_label} 缺少本地子字段 schema"
            )
        live_fields = (
            form_config.get("fields")
            if isinstance(form_config, dict)
            else None
        )
        if not isinstance(live_fields, list):
            raise PayloadTransportError(
                f"订单实时表单缺少 fields，无法校验子表 {parent_label}"
            )
        live_parent_matches = [
            field
            for field in live_fields
            if isinstance(field, dict)
            and _form_field_id(field) == parent_id
        ]
        if len(live_parent_matches) != 1:
            raise PayloadTransportError(
                f"订单实时表单无法唯一定位子表 {parent_label} ({parent_id})"
            )
        live_children = _form_child_fields(live_parent_matches[0])
        sub_fields = {}
        for live_child in live_children:
            child_id = _form_field_id(live_child)
            if not child_id:
                continue
            if child_id in sub_fields:
                raise PayloadTransportError(
                    f"订单实时表单子表 {parent_label} 子字段 ID 重复："
                    f"{child_id}"
                )
            local_child = local_sub_fields.get(child_id)
            merged_child = (
                dict(local_child) if isinstance(local_child, dict) else {}
            )
            merged_child.update(live_child)
            merged_child["label"] = str(
                live_child.get("name")
                or live_child.get("label")
                or merged_child.get("label")
                or child_id
            )
            rules = live_child.get("rules")
            if isinstance(rules, list):
                merged_child["required"] = any(
                    isinstance(rule, dict) and rule.get("key") == "required"
                    for rule in rules
                )
            elif "required" in live_child:
                merged_child["required"] = live_child.get("required") is True
            raw_options = live_child.get("options")
            if isinstance(raw_options, list):
                merged_child["options"] = [
                    {
                        "label": option.get("label") or option.get("name"),
                        "value": option.get("value") or option.get("id"),
                    }
                    for option in raw_options
                    if isinstance(option, dict)
                    and (option.get("label") or option.get("name")) is not None
                    and (option.get("value") or option.get("id")) is not None
                ]
            sub_fields[child_id] = merged_child
        income_matches = [
            (str(field_id), field)
            for field_id, field in sub_fields.items()
            if isinstance(field, dict) and field.get("label") == "收入类型"
        ]
        if len(income_matches) != 1:
            raise PayloadTransportError(
                f"订单子表 {parent_label} 无法唯一定位收入类型字段"
            )
        service_matches = [
            (str(field_id), field)
            for field_id, field in sub_fields.items()
            if isinstance(field, dict) and field.get("label") == "服务"
        ]
        if len(service_matches) > 1:
            raise PayloadTransportError(
                f"订单子表 {parent_label} 无法唯一定位服务字段"
            )
        child_income_id, child_income_field = income_matches[0]
        service_id = service_matches[0][0] if service_matches else ""
        derived_field_ids = {
            str(field_id)
            for field_id, field in sub_fields.items()
            if isinstance(field, dict) and field.get("resourceFieldId")
        }
        for row_index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise PayloadTransportError(
                    f"订单子表 {parent_label} 第 {row_index} 行必须是对象"
                )
            child_income_value, child_income_label = normalize_select(
                child_income_field,
                row.get(child_income_id),
                f"订单子表 {parent_label} 第 {row_index} 行收入类型",
            )
            if child_income_label != income_type_label:
                raise PayloadTransportError(
                    f"订单顶层收入类型 {income_type_label} 与子表 "
                    f"{parent_label} 第 {row_index} 行收入类型 "
                    f"{child_income_label} 不一致；不得猜测拆单或覆盖"
                )
            row[child_income_id] = child_income_value
            if service_id:
                row[service_id] = required_scalar(
                    row.get(service_id),
                    f"订单子表 {parent_label} 第 {row_index} 行服务"
                    "（必须取合同对应子表行的服务 ID）",
                )
            if derived_field_ids:
                row["price_sub"] = required_scalar(
                    row.get("price_sub"),
                    f"订单子表 {parent_label} 第 {row_index} 行 price_sub"
                    "（必须取合同同一价格源行，不能在创建后生成）",
                )
            missing_required = [
                str(child.get("label") or child_id)
                for child_id, child in sub_fields.items()
                if isinstance(child, dict)
                and child.get("type") != "FORMULA"
                and child.get("required") is True
                and value_is_missing(row.get(str(child_id)))
            ]
            if missing_required:
                raise PayloadTransportError(
                    f"订单子表 {parent_label} 第 {row_index} 行缺少必填业务字段："
                    f"{'、'.join(missing_required)}；必须从合同同一子表行按字段标签"
                    "完整映射，不能只传公式所需的最小字段集"
                )
            for child_id, child in sub_fields.items():
                if not isinstance(child, dict) or child.get("type") == "FORMULA":
                    continue
                child_id = str(child_id)
                value = row.get(child_id)
                if value_is_missing(value):
                    continue
                child_label = str(child.get("label") or child_id)
                context = (
                    f"订单子表 {parent_label} 第 {row_index} 行字段 "
                    f"{child_label}"
                )
                field_type = str(child.get("type") or "")
                if field_type in {"SELECT", "RADIO"}:
                    normalized_value, _ = normalize_select(
                        child, value, context
                    )
                    row[child_id] = normalized_value
                elif field_type == "INPUT_NUMBER":
                    _decimal_input(value, context)
                elif field_type == "DATA_SOURCE" and child.get("required") is True:
                    row[child_id] = required_scalar(value, context)
        populate_order_subtable_formulas(
            rows,
            parent_id,
            parent_label,
            parent,
            form_config,
        )
        # PRICE 引用投影列由 Cordys 根据服务 ID + price_sub 解析。真实
        # Web update body 不提交这些 *_ref_* 列；在本地公式完成后剥离，
        # 避免后端把显式投影值重置成 null。
        if derived_field_ids:
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for field_id in derived_field_ids:
                    row.pop(field_id, None)

    for field_label, default_label in ORDER_CREATE_DEFAULTS:
        field_id, field = schema_field(field_label)
        options = field.get("options")
        if not isinstance(options, list):
            raise PayloadTransportError(
                f"订单创建字段缺少选项：{field_label}"
            )
        default_matches = [
            option
            for option in options
            if isinstance(option, dict) and option.get("label") == default_label
        ]
        if len(default_matches) != 1 or not default_matches[0].get("value"):
            raise PayloadTransportError(
                f"订单创建字段 {field_label} 缺少默认选项：{default_label}"
            )
        default_value = str(default_matches[0]["value"])
        option_labels = {
            str(option.get("label")): str(option.get("value"))
            for option in options
            if isinstance(option, dict)
            and option.get("label") is not None
            and option.get("value") is not None
        }
        option_values = set(option_labels.values())

        item = submitted_field(field_id, field_label)
        if item is None:
            module_fields.append(
                {"fieldId": field_id, "fieldValue": default_value}
            )
            continue

        value = item.get("fieldValue")
        if value in (None, "") or value == []:
            item["fieldValue"] = default_value
            continue
        value_text = str(value)
        if value_text in option_labels:
            item["fieldValue"] = option_labels[value_text]
        elif value_text not in option_values:
            allowed = "、".join(option_labels)
            raise PayloadTransportError(
                f"订单创建字段 {field_label} 的值无效：{value_text}；"
                f"允许：{allowed}"
            )
    populate_order_top_level_formulas(body, fields, form_config)
    return body


def prepare_order_split_plan(
    raw: str,
    schema_path: str | os.PathLike,
    form_raw: str,
    contract_raw: str,
    product_raw: str,
) -> dict:
    """Build every order for one contract before any write is attempted.

    Contract child rows are grouped by the concrete product/service id plus
    the normalized income-type label.  The function is pure with respect to
    CRM state: it only parses already-fetched responses and returns a complete
    deterministic plan whose order bodies have all formulas precomputed.
    """
    request_body = parse_json(raw, json_only=True, who="create")
    split_value = request_body.get(ORDER_SPLIT_REQUEST_FIELD, True)
    if split_value is not True:
        raise PayloadTransportError(
            "自动拆单计划只接受 splitByProductIncome=true；"
            "false 仅供旧版单订单兼容链路使用"
        )
    allowed_request_keys = {
        "contractId",
        "owner",
        "customerId",
        "moduleFields",
        ORDER_SPLIT_REQUEST_FIELD,
    }
    unsupported_request_keys = sorted(set(request_body) - allowed_request_keys)
    if unsupported_request_keys:
        raise PayloadTransportError(
            "订单自动拆单外层只接受 contractId、可选匹配的 owner/customerId、"
            "公共默认字段 moduleFields 和 splitByProductIncome=true；"
            "不得手传分组派生字段："
            + "、".join(unsupported_request_keys)
        )
    contract_id = _required_identifier(
        request_body.get("contractId"),
        "订单创建 contractId（必须取目标合同详情 ID）",
    )
    contract_data = _parse_order_contract_response(contract_raw, contract_id)
    form_config = extract_form_config(form_raw, "order")
    product_catalog = _parse_product_catalog(product_raw)

    modules = _load_schema_modules(schema_path)
    contract_schema = modules.get("contract")
    order_schema = modules.get("order")
    contract_fields = (
        contract_schema.get("fields")
        if isinstance(contract_schema, dict)
        else None
    )
    order_fields = (
        order_schema.get("fields") if isinstance(order_schema, dict) else None
    )
    if not isinstance(contract_fields, dict) or not isinstance(
        order_fields, dict
    ):
        raise PayloadTransportError(
            "订单拆单无法读取本地 contract/order 字段 schema"
        )
    contract_values = _module_field_values(contract_data, "合同详情")

    contract_code_id, _ = _schema_field_by_label(
        contract_fields, "合同编码", "订单拆单合同"
    )
    contract_adjustment_id, _ = _schema_field_by_label(
        contract_fields, "调整金额", "订单拆单合同"
    )
    split_flag_id, split_flag_field = _schema_field_by_label(
        contract_fields, "是否已拆订单", "订单拆单合同"
    )
    order_contract_code_id, _ = _schema_field_by_label(
        order_fields, "合同编码", "订单拆单订单"
    )
    order_product_id, _ = _schema_field_by_label(
        order_fields, "产品类型", "订单拆单订单"
    )
    order_income_id, order_income_field = _schema_field_by_label(
        order_fields, "收入类型", "订单拆单订单"
    )
    order_adjustment_id, _ = _schema_field_by_label(
        order_fields, "调整金额", "订单拆单订单"
    )
    effective_amount_id, _ = _schema_field_by_label(
        order_fields, "有效订单金额", "订单拆单订单"
    )
    common_field_ids = {
        _schema_field_by_label(
            order_fields, field_label, "订单拆单公共默认字段"
        )[0]
        for field_label, _ in ORDER_CREATE_DEFAULTS
    }

    contract_code = _required_identifier(
        contract_values.get(contract_code_id), "合同详情 合同编码"
    )
    raw_adjustment = contract_values.get(contract_adjustment_id)
    contract_adjustment = (
        Decimal(0)
        if _value_is_missing(raw_adjustment)
        else _decimal_input(raw_adjustment, "合同详情 调整金额")
    )
    currency_quantum = Decimal("0.01")
    if contract_adjustment.quantize(
        currency_quantum, rounding=ROUND_DOWN
    ) != contract_adjustment:
        raise PayloadTransportError(
            "合同调整金额最多保留两位小数，无法安全按订单分摊"
        )

    split_label_to_value, split_value_to_label = _option_maps(split_flag_field)
    split_yes_value = split_label_to_value.get("是")
    if not split_yes_value:
        raise PayloadTransportError(
            "合同是否已拆订单字段缺少“是”选项"
        )
    current_split = contract_values.get(split_flag_id)
    current_split_text = (
        "" if current_split in (None, "") else str(current_split).strip()
    )
    if (
        current_split_text == "是"
        or split_value_to_label.get(current_split_text) == "是"
    ):
        raise PayloadTransportError(
            "合同已标记为“是否已拆订单=是”，禁止再次创建以免产生重复订单"
        )

    owner = _required_identifier(contract_data.get("owner"), "合同详情 负责人")
    customer_id = _required_identifier(
        contract_data.get("customerId"), "合同详情 客户"
    )
    for key, inherited in (("owner", owner), ("customerId", customer_id)):
        supplied = request_body.get(key)
        if not _value_is_missing(supplied) and str(supplied).strip() != inherited:
            raise PayloadTransportError(
                f"订单拆单请求 {key} 必须与合同详情一致：{inherited}"
            )

    submitted_items = request_body.get("moduleFields") or []
    if not isinstance(submitted_items, list):
        raise PayloadTransportError("订单拆单请求 moduleFields 必须是数组")
    submitted = {}
    for item in submitted_items:
        if not isinstance(item, dict) or item.get("fieldId") in (None, ""):
            raise PayloadTransportError(
                "订单拆单请求 moduleFields 每项都必须包含 fieldId"
            )
        field_id = str(item["fieldId"])
        if field_id in submitted:
            raise PayloadTransportError(
                f"订单拆单请求字段重复：{field_id}"
            )
        submitted[field_id] = item.get("fieldValue")
    unsupported_field_ids = sorted(set(submitted) - common_field_ids)
    if unsupported_field_ids:
        labels = []
        for field_id in unsupported_field_ids:
            field = order_fields.get(field_id)
            label = (
                str(field.get("label") or field_id)
                if isinstance(field, dict)
                else field_id
            )
            labels.append(f"{label}({field_id})")
        raise PayloadTransportError(
            "订单自动拆单 moduleFields 只接受交付团队、交付形式、"
            "正式license申请状态、是否专项交付四个公共默认字段；"
            "name、合同继承字段、产品、收入类型、调整金额、子表和公式"
            "均由 CLI 按组生成。收到："
            + "、".join(labels)
        )
    common_module_fields = deepcopy(submitted_items)

    base_body = {
        key: deepcopy(value)
        for key, value in request_body.items()
        if key
        not in {
            "id",
            "name",
            "订单名",
            "owner",
            "customerId",
            "contractId",
            "amount",
            "moduleFields",
            "moduleFormConfigDTO",
            ORDER_SPLIT_REQUEST_FIELD,
        }
    }
    base_body.update(
        {
            "owner": owner,
            "customerId": customer_id,
            "contractId": contract_id,
        }
    )

    groups = {}
    ignored_parent_labels = {"产品表格"}
    for source_parent_id, source_parent in contract_fields.items():
        if not isinstance(source_parent, dict) or not str(
            source_parent.get("type") or ""
        ).startswith("SUB_"):
            continue
        parent_label = str(source_parent.get("label") or source_parent_id)
        source_rows = contract_values.get(str(source_parent_id))
        if source_rows in (None, "", []):
            continue
        if not isinstance(source_rows, list):
            raise PayloadTransportError(
                f"合同详情子表 {parent_label} 必须是行数组"
            )
        target_parent_matches = [
            (str(field_id), field)
            for field_id, field in order_fields.items()
            if isinstance(field, dict)
            and str(field.get("type") or "").startswith("SUB_")
            and str(field.get("label") or "") == parent_label
        ]
        if not target_parent_matches:
            if parent_label in ignored_parent_labels:
                continue
            raise PayloadTransportError(
                f"合同子表 {parent_label} 有数据，但订单 form 没有同名目标子表"
            )
        if len(target_parent_matches) != 1:
            raise PayloadTransportError(
                f"订单 form 无法唯一定位同名子表：{parent_label}"
            )
        target_parent_id, target_parent = target_parent_matches[0]
        source_children = source_parent.get("subFields")
        if not isinstance(source_children, dict):
            raise PayloadTransportError(
                f"合同子表 {parent_label} 缺少本地子字段 schema"
            )

        def child_matches(label: str) -> list[tuple[str, dict]]:
            return [
                (str(field_id), field)
                for field_id, field in source_children.items()
                if isinstance(field, dict)
                and str(field.get("label") or "") == label
            ]

        selector_matches = [
            (str(field_id), field)
            for field_id, field in source_children.items()
            if isinstance(field, dict)
            and field.get("type") == "DATA_SOURCE"
            and not field.get("resourceFieldId")
            and str(field.get("label") or "") in {"产品", "服务"}
        ]
        if not selector_matches:
            selector_matches = [
                pair
                for pair in child_matches("产品类型")
                if pair[1].get("type") == "DATA_SOURCE"
                and not pair[1].get("resourceFieldId")
            ]
        product_type_matches = child_matches("产品类型")
        income_matches = child_matches("收入类型")
        if len(selector_matches) != 1:
            raise PayloadTransportError(
                f"合同子表 {parent_label} 无法唯一定位具体产品/服务字段"
            )
        if len(product_type_matches) != 1:
            raise PayloadTransportError(
                f"合同子表 {parent_label} 无法唯一定位产品类型字段"
            )
        if len(income_matches) != 1:
            raise PayloadTransportError(
                f"合同子表 {parent_label} 无法唯一定位收入类型字段"
            )
        selector_id, _ = selector_matches[0]
        product_type_source_id, _ = product_type_matches[0]
        income_source_id, income_source_field = income_matches[0]

        for row_index, source_row in enumerate(source_rows, start=1):
            if not isinstance(source_row, dict):
                raise PayloadTransportError(
                    f"合同子表 {parent_label} 第 {row_index} 行必须是对象"
                )
            meaningful = any(
                isinstance(field, dict)
                and field.get("type") != "FORMULA"
                and str(field.get("label") or "")
                not in ORDER_CONTRACT_ONLY_CHILD_LABELS
                and not _value_is_missing(source_row.get(str(field_id)))
                for field_id, field in source_children.items()
            )
            if not meaningful:
                continue
            selector_value = _required_identifier(
                source_row.get(selector_id),
                f"合同子表 {parent_label} 第 {row_index} 行具体产品/服务",
            )
            product_type_value = _required_identifier(
                source_row.get(product_type_source_id),
                f"合同子表 {parent_label} 第 {row_index} 行产品类型",
            )
            income_source_value = source_row.get(income_source_id)
            income_label = _option_label(
                income_source_field,
                income_source_value,
                f"合同子表 {parent_label} 第 {row_index} 行收入类型",
            )
            order_income_value = _bridge_contract_value(
                income_source_field,
                order_income_field,
                income_source_value,
                f"合同子表 {parent_label} 第 {row_index} 行收入类型",
            )
            target_row = _mapped_order_row(
                source_row,
                source_parent,
                target_parent,
                parent_label,
                row_index,
            )
            group_key = (selector_value, income_label)
            group = groups.setdefault(
                group_key,
                {
                    "productOrServiceId": selector_value,
                    "productTypeId": product_type_value,
                    "incomeType": income_label,
                    "incomeTypeValue": order_income_value,
                    "parents": {},
                    "sources": [],
                },
            )
            if group["productTypeId"] != product_type_value:
                raise PayloadTransportError(
                    f"拆单组合 {selector_value} + {income_label} 对应多个产品类型，"
                    "无法生成唯一订单名称"
                )
            if group["incomeTypeValue"] != order_income_value:
                raise PayloadTransportError(
                    f"拆单组合 {selector_value} + {income_label} 的订单收入类型映射不一致"
                )
            group["parents"].setdefault(target_parent_id, []).append(target_row)
            source_meta = {
                "parentId": str(source_parent_id),
                "parentLabel": parent_label,
                "rowIndex": row_index,
            }
            if not _value_is_missing(source_row.get("price_sub")):
                source_meta["price_sub"] = str(source_row["price_sub"]).strip()
            group["sources"].append(source_meta)

    if not groups:
        raise PayloadTransportError(
            "合同详情没有可按产品+收入类型生成订单的有效子表行"
        )

    planned = []
    for group in groups.values():
        product_type_id = group["productTypeId"]
        product_label = product_catalog.get(product_type_id)
        if not product_label:
            raise PayloadTransportError(
                f"产品目录找不到产品类型 ID：{product_type_id}，无法生成订单名称"
            )
        body = deepcopy(base_body)
        body["name"] = f"{contract_code}-{product_label}{ORDER_NAME_SUFFIX}"
        body["moduleFields"] = [
            *deepcopy(common_module_fields),
            {
                "fieldId": order_contract_code_id,
                "fieldValue": contract_code,
            },
            {
                "fieldId": order_product_id,
                "fieldValue": product_type_id,
            },
            {
                "fieldId": order_income_id,
                "fieldValue": group["incomeTypeValue"],
            },
            {"fieldId": order_adjustment_id, "fieldValue": 0},
            *[
                {
                    "fieldId": parent_id,
                    "fieldValue": deepcopy(rows),
                }
                for parent_id, rows in group["parents"].items()
            ],
        ]
        prepared_zero = apply_order_create_rules(
            deepcopy(body), schema_path, form_config, None
        )
        raw_amount = _decimal_input(
            prepared_zero.get("amount"),
            f"拆单组合 {group['productOrServiceId']} + "
            f"{group['incomeType']} 累计原始订单金额",
        )
        planned.append(
            {
                "group": group,
                "productTypeLabel": product_label,
                "rawBody": body,
                "rawAmount": raw_amount,
            }
        )

    if contract_adjustment == 0:
        allocations = [Decimal(0) for _ in planned]
    else:
        if any(item["rawAmount"] < 0 for item in planned):
            raise PayloadTransportError(
                "存在负的分组原始订单金额，无法按比例分摊合同调整金额"
            )
        total_amount = sum(
            (item["rawAmount"] for item in planned), Decimal(0)
        )
        if total_amount == 0:
            raise PayloadTransportError(
                "合同调整金额非 0，但全部分组原始订单金额合计为 0，无法按比例分摊"
            )
        allocations = []
        allocated = Decimal(0)
        for index, item in enumerate(planned):
            if index == len(planned) - 1:
                share = contract_adjustment - allocated
            else:
                share = (
                    contract_adjustment
                    * item["rawAmount"]
                    / total_amount
                ).quantize(currency_quantum, rounding=ROUND_DOWN)
                allocated += share
            allocations.append(share)

    plan_orders = []
    for index, (item, adjustment) in enumerate(
        zip(planned, allocations), start=1
    ):
        body = deepcopy(item["rawBody"])
        adjustment_item = next(
            field
            for field in body["moduleFields"]
            if str(field.get("fieldId")) == order_adjustment_id
        )
        adjustment_item["fieldValue"] = _json_number(
            adjustment, "订单分摊调整金额"
        )
        body = apply_order_create_rules(body, schema_path, form_config, None)
        body["moduleFormConfigDTO"] = deepcopy(form_config)
        submitted_final = {
            str(field.get("fieldId")): field.get("fieldValue")
            for field in body.get("moduleFields") or []
            if isinstance(field, dict) and field.get("fieldId") is not None
        }
        effective_amount = _decimal_input(
            submitted_final.get(effective_amount_id),
            f"第 {index} 张订单有效订单金额",
        )
        group = item["group"]
        plan_orders.append(
            {
                "groupKey": {
                    "productOrServiceId": group["productOrServiceId"],
                    "incomeType": group["incomeType"],
                },
                "productTypeId": group["productTypeId"],
                "productTypeLabel": item["productTypeLabel"],
                "sourceRows": deepcopy(group["sources"]),
                "sourceRowCount": len(group["sources"]),
                "name": body["name"],
                "amount": _json_number(item["rawAmount"], "订单原始金额"),
                "adjustmentAmount": _json_number(
                    adjustment, "订单分摊调整金额"
                ),
                "effectiveAmount": _json_number(
                    effective_amount, "订单有效金额"
                ),
                "body": body,
            }
        )

    return {
        "contractId": contract_id,
        "customerId": customer_id,
        "owner": owner,
        "contractCode": contract_code,
        "groupCount": len(plan_orders),
        "contractAdjustmentAmount": _json_number(
            contract_adjustment, "合同调整金额"
        ),
        "contractSplitUpdate": {
            "id": contract_id,
            "fieldId": split_flag_id,
            "fieldValue": split_yes_value,
        },
        "orders": plan_orders,
        "retryAllowed": False,
    }


def extract_form_config(form_raw: str, module: str = "模块") -> dict:
    """Validate a live ``/{module}/module/form`` response and return data."""
    try:
        wrapper = json.loads(form_raw)
    except json.JSONDecodeError as exc:
        raise PayloadTransportError(
            f"{module} 表单配置 JSON 解析失败: {exc}"
        ) from exc
    data = wrapper.get("data") if isinstance(wrapper, dict) else None
    if (
        not isinstance(wrapper, dict)
        or wrapper.get("code") != 100200
        or not isinstance(data, dict)
        or not isinstance(data.get("fields"), list)
        or not isinstance(data.get("formProp"), dict)
    ):
        raise PayloadTransportError(
            f"{module} 表单配置缺少 code=100200、data.fields 或 data.formProp"
        )
    return data


def prepare_create_payload(
    raw: str,
    module: str,
    schema_path: str | os.PathLike,
    form_raw: str = "",
    contract_raw: str = "",
) -> dict:
    """Build one create body, apply module rules, and inject live config."""
    if not (raw or "").lstrip("\ufeff").strip():
        raise PayloadTransportError("create 需要 JSON body")
    body = parse_json(raw, json_only=True, who="create")
    form_config = None
    if module_has_subforms(module, schema_path):
        if not form_raw:
            raise PayloadTransportError(
                f"{module} 含子表，创建前必须获取当前 module/form 配置"
            )
        form_config = extract_form_config(form_raw, module)
    if module == "order":
        body.pop(ORDER_SPLIT_REQUEST_FIELD, None)
        expected_contract_id = _required_identifier(
            body.get("contractId"),
            "订单创建 contractId（必须取目标合同详情 ID）",
        )
        contract_data = (
            _parse_order_contract_response(
                contract_raw,
                expected_contract_id,
            )
            if contract_raw
            else None
        )
        body = apply_order_create_rules(
            body,
            schema_path,
            form_config,
            contract_data,
        )
    else:
        body.pop("owner", None)
    if form_config is not None:
        # Always replace caller-supplied config with the current server value.
        # Stale hand-copied configs are large and can mismatch the active form.
        body["moduleFormConfigDTO"] = form_config
    return body


def normalize_query(
    raw, module="", sop_dir="", schema_path="", json_mode="", query_mode=""
):
    """Apply the shared query defaults and schema contract."""
    default = {
        "current": 1,
        "pageSize": 30,
        "sort": {},
        "combineSearch": {"searchMode": "AND", "conditions": []},
        "keyword": "",
        "viewId": "ALL",
        "filters": [],
    }
    user = parse_json(
        raw,
        json_only=json_mode == "json-only",
        who="查询",
    )
    merged = {**default, **user}
    # 联系人列表端点按可见范围查询；销售默认只能看本人联系人。
    # 显式传入 viewId（例如经理允许的 ALL）时保留调用方范围。
    if module in {"contact", "account/contact"} and "viewId" not in user:
        merged["viewId"] = "SELF"
    if module:
        try:
            if sop_dir:
                sys.path.insert(0, sop_dir)
            from query_contract import (
                validate_payload,
                validate_pool_query_scope,
                validate_query_semantics,
            )

            merged = validate_pool_query_scope(module, merged, query_mode)
            merged = validate_payload(module, merged, schema_path or None)
            merged = validate_query_semantics(module, merged, query_mode)
        except ValueError as exc:
            raise PayloadTransportError(f"查询条件无效: {exc}") from exc
    if not isinstance(merged.get("current"), int) or merged["current"] < 1:
        merged["current"] = 1
    if not isinstance(merged.get("pageSize"), int) or merged["pageSize"] < 1:
        merged["pageSize"] = 30
    return merged


def normalize_follow(raw, kind, legacy_module="", sop_dir="", schema_path=""):
    """Normalize the unified follow page request and migrate the old route syntax.

    The current list controllers are global (``/follow/{kind}/page``).  Older
    callers supplied a parent module plus a top-level ``sourceId`` because the
    URL itself was parent-scoped.  Convert that pair into an explicit, validated
    DATA_SOURCE condition so moving to the global endpoint cannot broaden the
    result set silently.
    """
    if kind not in {"record", "plan"}:
        raise PayloadTransportError("follow 子命令只支持 record/plan")
    if legacy_module and legacy_module not in FOLLOW_SOURCE_FIELDS:
        raise PayloadTransportError(
            "旧版 follow 模块参数只支持 lead/account/opportunity"
        )

    user = parse_json(raw, who="跟进查询")
    if not isinstance(user, dict):  # parse_json currently always returns a dict
        raise PayloadTransportError("跟进查询 payload 顶层必须是 JSON 对象")

    source_present = "sourceId" in user
    source_id = user.pop("sourceId", None)
    if legacy_module:
        if isinstance(source_id, int) and not isinstance(source_id, bool):
            source_id = str(source_id)
        if not isinstance(source_id, str) or not source_id.strip():
            raise PayloadTransportError(
                "旧版 crm follow <kind> <module> 用法必须在 JSON 顶层提供非空 "
                "sourceId；推荐改用 crm follow <kind> <JSON>，并在 "
                "combineSearch.conditions 中按 clueId/customerId/opportunityId 过滤"
            )
        source_id = source_id.strip()
        source_field = FOLLOW_SOURCE_FIELDS[legacy_module]
        combine_search = user.setdefault(
            "combineSearch", {"searchMode": "AND", "conditions": []}
        )
        if not isinstance(combine_search, dict):
            raise PayloadTransportError("combineSearch 必须是 JSON 对象")
        conditions = combine_search.setdefault("conditions", [])
        if not isinstance(conditions, list):
            raise PayloadTransportError("combineSearch.conditions 必须是数组")
        search_mode = combine_search.setdefault("searchMode", "AND")
        if conditions and search_mode != "AND":
            raise PayloadTransportError(
                "旧版 sourceId 兼容转换不能与 OR 条件混用；请改用新版 JSON，"
                f"把 {source_field} 作为明确条件"
            )
        combine_search["searchMode"] = "AND"
        if any(
            isinstance(condition, dict)
            and condition.get("name") == source_field
            for condition in conditions
        ):
            raise PayloadTransportError(
                f"sourceId 与已有 {source_field} 条件重复；请只保留一种范围表达"
            )
        conditions.append(
            {
                "value": [source_id],
                "operator": "IN",
                "name": source_field,
                "type": "DATA_SOURCE",
            }
        )
    elif source_present:
        raise PayloadTransportError(
            "全局跟进分页不识别顶层 sourceId；请在 combineSearch.conditions 中"
            "使用 clueId、customerId 或 opportunityId（DATA_SOURCE + IN）"
        )

    ignored_scope_fields = [
        field
        for field in FOLLOW_SOURCE_FIELDS.values()
        if field in user
    ]
    if ignored_scope_fields:
        raise PayloadTransportError(
            "全局跟进分页不会把这些顶层字段作为筛选条件："
            f"{', '.join(ignored_scope_fields)}；请移入 combineSearch.conditions"
        )

    if "myPlan" in user:
        my_plan = user.pop("myPlan")
        if not isinstance(my_plan, bool):
            raise PayloadTransportError("myPlan 必须是 JSON 布尔值")
        if my_plan:
            explicit_view = user.get("viewId")
            if explicit_view not in (None, "", "SELF"):
                raise PayloadTransportError(
                    "myPlan:true 与非 SELF 的 viewId 冲突；全局接口请直接使用 "
                    'viewId:"SELF"'
                )
            user["viewId"] = "SELF"

    if kind == "plan":
        status = user.get("status")
        if status in (None, ""):
            user["status"] = "ALL"
        elif not isinstance(status, str) or status not in FOLLOW_PLAN_STATUSES:
            allowed = ", ".join(sorted(FOLLOW_PLAN_STATUSES))
            raise PayloadTransportError(f"跟进计划 status 只允许：{allowed}")
    elif "status" in user:
        raise PayloadTransportError("status 只适用于跟进计划查询，不适用于跟进记录")

    schema_module = "follow-plan" if kind == "plan" else "follow"
    return normalize_query(
        json.dumps(user, ensure_ascii=False),
        schema_module,
        sop_dir,
        schema_path,
        "json-only",
        "follow",
    )


def write_temp_json(value, prefix="cordys_") -> str:
    """Write a UTF-8 JSON temp file and return its native path."""
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False)
    except BaseException:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return path


def _normalize_query_cli(args):
    if len(args) != 5:
        raise PayloadTransportError(
            "用法: payload_io.py normalize-query <module> <sop_dir> <schema> <json-mode> <query-mode>"
        )
    module, sop_dir, schema_path, json_mode, query_mode = args
    body = normalize_query(
        read_utf8(), module, sop_dir, schema_path, json_mode, query_mode
    )
    print(write_temp_json(body), flush=True)


def _normalize_follow_cli(args):
    if len(args) != 4:
        raise PayloadTransportError(
            "用法: payload_io.py normalize-follow <record|plan> <legacy-module> "
            "<sop-dir> <schema>"
        )
    kind, legacy_module, sop_dir, schema_path = args
    body = normalize_follow(
        read_utf8(), kind, legacy_module, sop_dir, schema_path
    )
    print(write_temp_json(body, prefix="cordys_follow_"), flush=True)


def _normalize_parent_cli(args):
    if len(args) != 5:
        raise PayloadTransportError(
            "用法: payload_io.py normalize-parent <field> <parent-id> <module> <sop-dir> <schema>"
        )
    field, parent_id, module, sop_dir, schema_path = args
    body = normalize_query(read_utf8(), module, sop_dir, schema_path)
    body[field] = parent_id
    print(write_temp_json(body), flush=True)


def _needs_form_config_cli(args):
    if len(args) != 2:
        raise PayloadTransportError(
            "用法: payload_io.py needs-form-config <module> <schema>"
        )
    module, schema_path = args
    print(
        "true" if module_has_subforms(module, schema_path) else "false",
        flush=True,
    )


def _prepare_create_cli(args):
    if len(args) not in {3, 4}:
        raise PayloadTransportError(
            "用法: payload_io.py prepare-create <module> <schema> "
            "<form-response-file> [contract-response-file]"
        )
    module, schema_path, form_path = args[:3]
    contract_path = args[3] if len(args) == 4 else ""
    form_raw = ""
    if form_path:
        try:
            form_raw = Path(form_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise PayloadTransportError(
                f"读取 {module} 表单配置文件失败: {exc}"
            ) from exc
    contract_raw = ""
    if contract_path:
        try:
            contract_raw = Path(contract_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise PayloadTransportError(
                f"读取订单合同详情文件失败: {exc}"
            ) from exc
    body = prepare_create_payload(
        read_utf8(), module, schema_path, form_raw, contract_raw
    )
    print(write_temp_json(body, prefix="cordys_create_"), flush=True)


def _order_contract_id_cli(args):
    if args:
        raise PayloadTransportError(
            "用法: payload_io.py order-contract-id < create-body.json"
        )
    print(order_contract_id(read_utf8()), flush=True)


def _order_split_enabled_cli(args):
    if args:
        raise PayloadTransportError(
            "用法: payload_io.py order-split-enabled < create-body.json"
        )
    print("true" if order_split_enabled(read_utf8()) else "false", flush=True)


def _validate_pool_scope_cli(args):
    if len(args) != 3:
        raise PayloadTransportError(
            "用法: payload_io.py validate-pool-scope <module> <query-mode> <sop-dir>"
        )
    module, query_mode, sop_dir = args
    payload = parse_json(read_utf8(), who="池查询")
    try:
        if sop_dir:
            sys.path.insert(0, sop_dir)
        from query_contract import validate_pool_query_scope

        validate_pool_query_scope(module, payload, query_mode)
    except ValueError as exc:
        raise PayloadTransportError(f"查询条件无效: {exc}") from exc


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args and args[0] == "normalize-query":
            _normalize_query_cli(args[1:])
        elif args and args[0] == "normalize-follow":
            _normalize_follow_cli(args[1:])
        elif args and args[0] == "normalize-parent":
            _normalize_parent_cli(args[1:])
        elif args and args[0] == "order-contract-id":
            _order_contract_id_cli(args[1:])
        elif args and args[0] == "order-split-enabled":
            _order_split_enabled_cli(args[1:])
        elif args and args[0] == "needs-form-config":
            _needs_form_config_cli(args[1:])
        elif args and args[0] == "prepare-create":
            _prepare_create_cli(args[1:])
        elif args and args[0] == "validate-pool-scope":
            _validate_pool_scope_cli(args[1:])
        else:
            raise PayloadTransportError("未知 payload 传输命令")
    except PayloadTransportError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
