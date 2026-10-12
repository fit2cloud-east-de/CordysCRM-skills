"""Formula-driven quotation name (报价单名称) for create and update.

The live quotation form defines the name (``businessKey=name``) as a formula,
currently ``CONCATENATE(客户工商抬头, "-", 报价编号)``. The formula is only
evaluated in the browser; the backend just replaces the literal placeholder
``${<流水号字段名>}`` with the serial number it generates on create.

So the CLI renders the name from the live formula:

- create: data-source parts are resolved to the record name, serial parts are
  sent as the literal ``${报价编号}`` placeholder for the backend to fill in;
- update: the serial is not regenerated, so serial parts use the record's
  existing serial value.

A caller-supplied name is accepted only when it equals the rendered value.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from payload_io import PayloadTransportError, extract_form_config


# dataSourceType → API module whose /get/{id} returns ``data.name``.
DATA_SOURCE_MODULES = {
    "BUSINESS_TITLE": "contract/business-title",
    "CUSTOMER": "account",
    "OPPORTUNITY": "opportunity",
    "CONTACT": "account/contact",
    "CONTRACT": "contract",
}


class QuotationNameError(PayloadTransportError):
    """The quotation name cannot be rendered or the caller name conflicts."""


def name_template(form_data: dict) -> dict | None:
    """Parse the name formula; ``None`` when the name is not formula-driven."""
    fields = form_data.get("fields") if isinstance(form_data, dict) else None
    if not isinstance(fields, list):
        return None
    by_id = {
        str(field.get("id") or field.get("fieldId")): field
        for field in fields
        if isinstance(field, dict)
    }
    name_field = next(
        (f for f in fields if isinstance(f, dict) and f.get("businessKey") == "name"),
        None,
    )
    if (
        not name_field
        or name_field.get("defaultValueType") != "formula"
        or not name_field.get("formula")
    ):
        return None
    formula = name_field["formula"]
    if isinstance(formula, str):
        try:
            formula = json.loads(formula)
        except json.JSONDecodeError as exc:
            raise QuotationNameError(f"报价单名称公式无法解析：{exc}") from exc
    ir = formula.get("ir") if isinstance(formula, dict) else None
    if (
        not isinstance(ir, dict)
        or ir.get("type") != "function"
        or ir.get("name") != "CONCATENATE"
    ):
        raise QuotationNameError("报价单名称公式不是 CONCATENATE，CLI 无法生成名称，已中止")

    parts = []
    for arg in ir.get("args") or []:
        kind = arg.get("type") if isinstance(arg, dict) else None
        if kind == "literal":
            parts.append({"kind": "literal", "value": str(arg.get("value") or "")})
            continue
        if kind != "field":
            raise QuotationNameError("报价单名称公式含不支持的参数类型，已中止")
        field_id = str(arg.get("fieldId") or "")
        field = by_id.get(field_id) or {}
        field_type = field.get("type") or arg.get("fieldType")
        label = str(field.get("name") or arg.get("name") or field_id)
        if field_type == "SERIAL_NUMBER":
            parts.append({"kind": "serial", "fieldId": field_id, "label": label})
        elif field_type == "DATA_SOURCE" and field.get("dataSourceType") in DATA_SOURCE_MODULES:
            parts.append({
                "kind": "source",
                "fieldId": field_id,
                "label": label,
                "module": DATA_SOURCE_MODULES[field["dataSourceType"]],
            })
        else:
            raise QuotationNameError(
                f"报价单名称公式引用了 CLI 不支持的字段「{label}」（{field_type}），已中止"
            )
    if not parts:
        raise QuotationNameError("报价单名称公式为空，已中止")
    display = (formula.get("display") if isinstance(formula, dict) else "") or ""
    return {"parts": parts, "display": str(display)}


def _module_value(record: dict, field_id: str):
    for item in record.get("moduleFields") or []:
        if isinstance(item, dict) and str(item.get("fieldId")) == field_id:
            return item.get("fieldValue")
    return None


def _single_id(value) -> str:
    if isinstance(value, list):
        value = value[0] if len(value) == 1 else None
    if value in (None, "") or isinstance(value, (dict, list, bool)):
        return ""
    return str(value).strip()


def _source_name(fetch, part: dict, record_id: str) -> str:
    text = fetch(f"/{part['module']}/get/{record_id}")
    try:
        wrapper = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        wrapper = None
    data = (
        wrapper.get("data")
        if isinstance(wrapper, dict) and str(wrapper.get("code")) == "100200"
        else None
    )
    name = str(data.get("name") or "").strip() if isinstance(data, dict) else ""
    if not name or str(data.get("id")) != record_id:
        raise QuotationNameError(
            f"读取{part['label']}（{record_id}）失败，无法生成报价单名称，未发送写请求"
        )
    return name


def render(template: dict, body: dict, fetch, serial_values: dict[str, str]) -> str:
    out = []
    for part in template["parts"]:
        if part["kind"] == "literal":
            out.append(part["value"])
        elif part["kind"] == "serial":
            out.append(serial_values[part["fieldId"]])
        else:
            record_id = _single_id(_module_value(body, part["fieldId"]))
            if not record_id:
                raise QuotationNameError(
                    f"报价单名称按公式生成，必须先填写「{part['label']}」"
                )
            out.append(_source_name(fetch, part, record_id))
    return "".join(out)


def _given_name(caller: dict) -> str:
    value = caller.get("name")
    return "" if value in (None, "") else str(value).strip()


def _conflict(expected: str, given: str, template: dict) -> QuotationNameError:
    rule = f"（{template['display']}）" if template["display"] else ""
    return QuotationNameError(
        f"报价单名称由表单公式{rule}生成为「{expected}」，不能指定为「{given}」；"
        "请不传 name，由 CLI 生成"
    )


def apply_create_name(body: dict, form_data: dict, fetch) -> dict | None:
    """Set ``body['name']`` to the formula value with the serial placeholder."""
    template = name_template(form_data)
    if template is None:
        return None
    serials = {
        p["fieldId"]: "${" + p["label"] + "}"
        for p in template["parts"] if p["kind"] == "serial"
    }
    expected = render(template, body, fetch, serials)
    given = _given_name(body)
    if given and given != expected:
        raise _conflict(expected, given, template)
    body["name"] = expected
    return {"name": expected}


def apply_update_name(
    body: dict, existing: dict, caller: dict, form_data: dict, fetch
) -> dict | None:
    """Keep the update name equal to the formula value of the merged record."""
    template = name_template(form_data)
    if template is None:
        return None
    previous = str(existing.get("name") or "")
    given = _given_name(caller)
    serials = {}
    for part in template["parts"]:
        if part["kind"] == "serial":
            value = str(_module_value(existing, part["fieldId"]) or "").strip()
            if not value:
                # 早期记录没有流水号，名称无法按公式生成：保持原名，禁止改名。
                if given and given != previous:
                    raise QuotationNameError(
                        f"该报价单没有「{part['label']}」，名称无法按公式生成，不能修改报价单名称"
                    )
                body["name"] = previous
                return {"name": previous, "previous": previous, "changed": False}
            serials[part["fieldId"]] = value
    expected = render(template, body, fetch, serials)
    if given and given != expected:
        raise _conflict(expected, given, template)
    body["name"] = expected
    return {"name": expected, "previous": previous, "changed": expected != previous}


# ── CLI ───────────────────────────────────────────────────────────────
def _read_json(path: str, who: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuotationNameError(f"{who}读取失败：{exc}") from exc
    if not isinstance(value, dict):
        raise QuotationNameError(f"{who}必须是 JSON 对象")
    return value


def _record(wrapper: dict) -> dict:
    data = wrapper.get("data")
    if str(wrapper.get("code")) != "100200" or not isinstance(data, dict) or not data.get("id"):
        raise QuotationNameError("现有报价单读取失败，无法核对报价单名称")
    return data


def _fetch_from_env():
    from order_batch import OrderBatchError, UrllibTransport

    try:
        transport = UrllibTransport(
            str(os.environ.get("CORDYS_CRM_DOMAIN") or ""),
            str(os.environ.get("CORDYS_ACCESS_KEY") or ""),
            str(os.environ.get("CORDYS_SECRET_KEY") or ""),
        )
    except OrderBatchError as exc:
        raise QuotationNameError(str(exc)) from exc
    return lambda path: transport.request("GET", path).text


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    usage = (
        "用法: quotation_name.py create <body> <form> | "
        "update <body> <form> <existing> <caller>"
    )
    try:
        if args[:1] == ["create"] and len(args) == 3:
            body = _read_json(args[1], "写请求体")
            form = extract_form_config(Path(args[2]).read_text(encoding="utf-8"), "报价单")
            result = apply_create_name(body, form, _fetch_from_env())
        elif args[:1] == ["update"] and len(args) == 5:
            body = _read_json(args[1], "写请求体")
            form = extract_form_config(Path(args[2]).read_text(encoding="utf-8"), "报价单")
            existing = _record(_read_json(args[3], "现有报价单"))
            caller = _read_json(args[4], "调用方请求")
            result = apply_update_name(body, existing, caller, form, _fetch_from_env())
        else:
            raise QuotationNameError(usage)
    except (PayloadTransportError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    if result is not None:
        Path(args[1]).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        if result.get("changed"):
            print(f":: 报价单名称按表单公式校正：{result['previous']} → {result['name']}", file=sys.stderr)
        else:
            print(f":: 报价单名称：{result['name']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
