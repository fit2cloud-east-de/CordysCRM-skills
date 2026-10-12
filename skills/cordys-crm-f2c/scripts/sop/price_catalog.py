#!/usr/bin/env python3
"""Read and normalize the Cordys PRICE data source.

The price data source is unusual in two ways:

* the business fields of ``products[]`` are identified by the current
  ``/price/module/form`` response, not by stable English JSON keys; and
* ``/field/source/price`` paginates price-list masters while the useful
  records are the nested product rows.

This module is deliberately read-only.  It is used by both CLI entry points
so that ``cordys.sh`` and the fallback ``cordys.py`` expose the same contract.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from urllib import parse, request
from urllib.error import HTTPError, URLError


PAGE_SIZE = 500
SUCCESS_CODE = 100200


class PriceCatalogError(RuntimeError):
    """A user-facing error with a stable diagnostic category."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def _redact(value: Any, access_key: str, secret_key: str) -> str:
    text = str(value or "")
    for token in (access_key, secret_key):
        if token:
            text = text.replace(token, "[REDACTED]")
    return text


def _validate_credentials(domain: str, access_key: str, secret_key: str) -> str:
    domain = (domain or "").rstrip("/")
    if not domain:
        raise PriceCatalogError("PRICE_AUTH_FAILED", "未设置 CORDYS_CRM_DOMAIN")
    parsed = parse.urlparse(domain)
    hostname_ok = bool(
        parsed.hostname
        and re.fullmatch(
            r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)*"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?",
            parsed.hostname,
        )
    )
    if (
        parsed.scheme != "https"
        or not hostname_ok
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in domain)
    ):
        raise PriceCatalogError(
            "PRICE_AUTH_FAILED",
            "CORDYS_CRM_DOMAIN 必须是合法 HTTPS 根地址，不能包含路径、查询参数或凭证",
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise PriceCatalogError(
            "PRICE_AUTH_FAILED", "CORDYS_CRM_DOMAIN 端口必须在 1-65535 之间"
        ) from exc
    if port == 0 or (port is not None and not 1 <= port <= 65535):
        raise PriceCatalogError(
            "PRICE_AUTH_FAILED", "CORDYS_CRM_DOMAIN 端口必须在 1-65535 之间"
        )
    if not access_key:
        raise PriceCatalogError("PRICE_AUTH_FAILED", "未设置 CORDYS_ACCESS_KEY")
    if not secret_key:
        raise PriceCatalogError("PRICE_AUTH_FAILED", "未设置 CORDYS_SECRET_KEY")
    return domain


class _PriceClient:
    def __init__(self, domain: str, access_key: str, secret_key: str, timeout: float = 30):
        self.domain = _validate_credentials(domain, access_key, secret_key)
        self.access_key = access_key
        self.secret_key = secret_key
        self.timeout = timeout
        self.opener = request.build_opener(request.ProxyHandler({}))

    def request_json(self, method: str, path: str, body: dict[str, Any] | None, context: str) -> dict[str, Any]:
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.domain}/{path.lstrip('/')}",
            data=payload,
            method=method.upper(),
            headers={
                "X-Access-Key": self.access_key,
                "X-Secret-Key": self.secret_key,
                "X-Request-Source": "SKILL",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        response_text = ""
        http_status: int | None = None
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                http_status = getattr(response, "status", None)
                charset = response.headers.get_content_charset() or "utf-8"
                response_text = response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            http_status = exc.code
            try:
                response_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                response_text = ""
            parsed_error = _parse_json_object(response_text)
            if parsed_error and str(parsed_error.get("code")) == str(SUCCESS_CODE):
                return parsed_error
            detail = _response_detail(parsed_error, response_text)
            raise PriceCatalogError(
                _error_code_for_context(context, auth=http_status in (401, 403)),
                f"{context}失败（HTTP {http_status}）：{_redact(detail, self.access_key, self.secret_key)}",
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise PriceCatalogError(
                _error_code_for_context(context),
                f"{context}失败（网络或超时）：{_redact(exc, self.access_key, self.secret_key)}",
            ) from exc

        value = _parse_json_object(response_text)
        if value is None:
            raise PriceCatalogError(
                _error_code_for_context(context),
                f"{context}失败：HTTP {http_status or '未知'} 响应不是合法 JSON",
            )
        if str(value.get("code")) != str(SUCCESS_CODE):
            detail = _response_detail(value, response_text)
            raise PriceCatalogError(
                _error_code_for_context(
                    context, auth=str(value.get("code")) in {"401", "403", "40100", "40300"}
                ),
                f"{context}失败（code={value.get('code')}）：{_redact(detail, self.access_key, self.secret_key)}",
            )
        return value


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.lstrip("\ufeff"))
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _response_detail(value: dict[str, Any] | None, raw: str) -> str:
    if isinstance(value, dict):
        for key in ("message", "msg", "error", "detail"):
            if value.get(key) not in (None, ""):
                return str(value[key])
    return raw[:500] if raw else "无错误详情"


def _error_code_for_context(context: str, auth: bool = False) -> str:
    if auth:
        return "PRICE_AUTH_FAILED"
    if "表单" in context:
        return "PRICE_FORM_READ_FAILED"
    if "价格目录" in context or "产品字典" in context:
        return "PRICE_CATALOG_READ_FAILED"
    if "详情" in context:
        return "PRICE_DETAIL_READ_FAILED"
    return "PRICE_QUERY_FAILED"


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "是"}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[\s_\-:：()（）%％]", "", _text(value)).casefold()


def _field_id(field: dict[str, Any]) -> str | None:
    value = field.get("id", field.get("fieldId"))
    return None if value is None else str(value)


def _raw_subfields(parent: dict[str, Any]) -> list[dict[str, Any]]:
    raw = parent.get("subFields")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        output: list[dict[str, Any]] = []
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            item = dict(value)
            item.setdefault("id", key)
            output.append(item)
        return output
    return []


def _normalize_option(option: Any) -> dict[str, str] | None:
    if not isinstance(option, dict):
        return None
    value = option.get("value", option.get("id"))
    label = option.get("label", option.get("name", value))
    if value is None or label is None:
        return None
    return {"value": str(value), "label": str(label)}


def _normalize_field(field: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "fieldId": _field_id(field),
        "name": field.get("name", field.get("label")),
        "type": field.get("type"),
        "businessKey": field.get("businessKey"),
        "required": _as_bool(field.get("required", field.get("isRequired", False))),
        "options": [],
    }
    if normalized["name"] is not None:
        normalized["name"] = str(normalized["name"])
    if normalized["type"] is not None:
        normalized["type"] = str(normalized["type"])
    if normalized["businessKey"] is not None:
        normalized["businessKey"] = str(normalized["businessKey"])
    for option in field.get("options") or []:
        item = _normalize_option(option)
        if item:
            normalized["options"].append(item)
    return normalized


_FIELD_ALIASES: dict[str, dict[str, set[str]]] = {
    "product": {
        "businessKey": {"product", "productid"},
        "name": {"产品", "产品名称", "商品"},
    },
    "sku": {
        "businessKey": {"productsku", "sku", "productcode", "productno"},
        "name": {"产品sku", "sku", "产品编码", "产品编号"},
    },
    "description": {
        "businessKey": {"description", "productdescription"},
        "name": {"描述", "产品描述"},
    },
    "product_version": {
        "businessKey": {"productversion", "version"},
        "name": {"产品版本", "版本"},
    },
    "purchase_mode": {
        "businessKey": {"purchasemode", "purchasetype", "purchase_method"},
        "name": {"购买方式", "购买模式"},
    },
    "income_type": {
        "businessKey": {"incometype", "income_type"},
        "name": {"收入类型"},
    },
    "unit": {
        "businessKey": {"unit"},
        "name": {"单位"},
    },
    "service_tier": {
        "businessKey": {"servicetier", "servicelevel"},
        "name": {"服务等级", "服务级别"},
    },
    "currency": {
        "businessKey": {"currency"},
        "name": {"币种", "货币"},
    },
    "standard_price_tax_included": {
        "businessKey": {
            "standardpricetaxincluded",
            "taxincludedprice",
            "standardprice",
            "price",
            "amount",
        },
        "name": {
            "含税成交指导价",
            "含税指导价",
            "含税价格",
            "成交指导价",
            "成交指导价（含税）",
            "标准价格",
            "价格",
        },
    },
    "tax_rate_percent": {
        "businessKey": {"taxrate", "tax_rate", "taxratepercent"},
        "name": {"税率", "税率%"},
    },
    "invoice_item": {
        "businessKey": {"invoiceitem", "invoice_item"},
        "name": {"开票项目", "发票项目"},
    },
    "important_notes": {
        "businessKey": {"importantnotes", "notes", "remark", "important_notes"},
        "name": {"重要说明", "说明", "备注"},
    },
    "catalog_status": {
        "businessKey": {"status", "enable", "enabled"},
        "name": {"状态", "启用状态", "是否启用"},
    },
}


def _field_matches(field: dict[str, Any], aliases: dict[str, set[str]]) -> bool:
    return (
        _norm(field.get("businessKey")) in {_norm(value) for value in aliases["businessKey"]}
        or _norm(field.get("name")) in {_norm(value) for value in aliases["name"]}
    )


def _find_field(fields: Iterable[dict[str, Any]], semantic: str) -> dict[str, Any] | None:
    aliases = _FIELD_ALIASES[semantic]
    candidates = [field for field in fields if _field_matches(field, aliases)]
    if not candidates:
        return None
    # Prefer a businessKey match over a translated label when both exist.
    for field in candidates:
        if _norm(field.get("businessKey")) in {_norm(value) for value in aliases["businessKey"]}:
            return field
    return candidates[0]


def _parse_price_form(wrapper: dict[str, Any]) -> dict[str, Any]:
    data = wrapper.get("data")
    fields_raw = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields_raw, list):
        raise PriceCatalogError(
            "PRICE_FORM_READ_FAILED",
            "价格表单读取失败：data.fields 缺失或不是数组",
        )
    main_fields = [_normalize_field(field) for field in fields_raw if isinstance(field, dict)]
    parent_candidates = [
        field
        for field in fields_raw
        if isinstance(field, dict)
        and (
            _norm(field.get("businessKey")) == "products"
            or (
                str(field.get("type") or "") in {"SUB_PRODUCT", "SUB_PRICE"}
                and _norm(field.get("name")) in {"产品", "产品明细", "products"}
            )
        )
    ]
    if len(parent_candidates) != 1:
        raise PriceCatalogError(
            "PRICE_FORM_READ_FAILED",
            "价格表单读取失败：无法唯一定位 businessKey=products 的 products 子表",
        )
    parent_raw = parent_candidates[0]
    child_fields = [_normalize_field(field) for field in _raw_subfields(parent_raw)]
    if not child_fields:
        raise PriceCatalogError(
            "PRICE_FORM_READ_FAILED",
            "价格表单读取失败：products 子表没有 subFields",
        )
    parent = _normalize_field(parent_raw)
    parent["subFields"] = child_fields
    mappings = {
        semantic: _find_field(child_fields, semantic)
        for semantic in _FIELD_ALIASES
        if semantic != "catalog_status"
    }
    mappings["catalog_status"] = _find_field(main_fields, "catalog_status")
    return {
        "fields": main_fields,
        "products": parent,
        "productFields": child_fields,
        "fieldMappings": mappings,
    }


def _record_value(record: Any, field: dict[str, Any] | None) -> Any:
    if not isinstance(record, dict) or not field:
        return None
    candidates = [field.get("fieldId"), field.get("businessKey"), field.get("name")]
    candidates = [str(value) for value in candidates if value not in (None, "")]
    for candidate in candidates:
        if candidate in record:
            return record[candidate]
    for container_name in ("moduleFields", "fields"):
        container = record.get(container_name)
        if not isinstance(container, list):
            continue
        for item in container:
            if not isinstance(item, dict):
                continue
            item_id = item.get("fieldId", item.get("id", item.get("businessKey")))
            if item_id is not None and str(item_id) in candidates:
                return item.get("fieldValue", item.get("value"))
    return None


def _row_value(row: Any, field: dict[str, Any] | None) -> Any:
    return _record_value(row, field)


def _unwrap_scalar(value: Any) -> Any:
    if isinstance(value, list):
        if len(value) == 1:
            return _unwrap_scalar(value[0])
        return value
    if isinstance(value, dict):
        for key in ("value", "id", "sourceId", "label", "name"):
            if value.get(key) is not None:
                return value[key]
    return value


def _source_id_and_label(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, list):
        if not value:
            return None, None
        if len(value) == 1:
            return _source_id_and_label(value[0])
        value = value[0]
    if isinstance(value, dict):
        source_id = value.get("id", value.get("value", value.get("sourceId")))
        label = value.get("label", value.get("name"))
        return (
            None if source_id is None else str(source_id),
            None if label is None else str(label),
        )
    if value in (None, ""):
        return None, None
    return str(value), None


def _number(value: Any, context: str) -> int | float | None:
    value = _unwrap_scalar(value)
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (list, dict)):
        raise PriceCatalogError("PRICE_FIELD_TYPE_INVALID", f"{context}无法解析为数字")
    raw = str(value).strip().replace(",", "")
    if raw.endswith("%"):
        raw = raw[:-1].strip()
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise PriceCatalogError(
            "PRICE_FIELD_TYPE_INVALID", f"{context}无法解析为数字：{value}"
        ) from exc
    return int(number) if number == number.to_integral_value() else float(number)


def _percent(value: Any, context: str) -> int | float | None:
    value = _unwrap_scalar(value)
    if value in (None, "") or isinstance(value, bool):
        return None
    raw = str(value).strip()
    has_percent_sign = raw.endswith("%") or raw.endswith("％")
    number = _number(raw.rstrip("%％").strip(), context)
    if number is None:
        return None
    if not has_percent_sign and 0 < float(number) < 1:
        number = float(number) * 100
    return int(number) if float(number).is_integer() else float(number)


def _option_label(field: dict[str, Any] | None, value: Any) -> Any:
    value = _unwrap_scalar(value)
    if not field or str(field.get("type") or "") not in {"SELECT", "RADIO"}:
        return value
    if isinstance(value, list):
        return [_option_label(field, item) for item in value]
    value_text = _text(value)
    for option in field.get("options") or []:
        if str(option.get("value")) == value_text:
            return option.get("label")
        if str(option.get("label")) == value_text:
            return option.get("label")
    return value


def _products_rows(catalog: dict[str, Any], products_parent: dict[str, Any]) -> list[dict[str, Any]]:
    value = _record_value(catalog, products_parent)
    if value is None and isinstance(catalog, dict):
        value = catalog.get("products")
    if isinstance(value, dict):
        if isinstance(value.get("fieldValue"), list):
            value = value["fieldValue"]
        elif isinstance(value.get("list"), list):
            value = value["list"]
        else:
            value = [value]
    return [item for item in value or [] if isinstance(item, dict)] if isinstance(value, list) else []


def _status_label(value: Any) -> str | None:
    value = _unwrap_scalar(value)
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return "enabled" if value else "disabled"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "enabled" if value == 1 else "disabled" if value == 0 else "unknown"
    text = _text(value).casefold()
    if text in {"1", "true", "yes", "y", "enabled", "enable", "active", "启用", "是"}:
        return "enabled"
    if text in {"0", "false", "no", "n", "disabled", "disable", "inactive", "禁用", "否"}:
        return "disabled"
    return "unknown"


def _catalog_status(catalog: dict[str, Any], status_field: dict[str, Any] | None, status_known: bool) -> str:
    raw = _record_value(catalog, status_field)
    if raw is None and isinstance(catalog, dict):
        for key in ("status", "enable", "enabled"):
            if key in catalog:
                raw = catalog[key]
                break
    result = _status_label(raw)
    if result is None and not status_known:
        # Some PRICE responses omit the status field entirely.  In that case
        # there is no disabled value to filter, so the returned master is the
        # enabled data source exposed by the endpoint.
        return "enabled"
    return result or "unknown"


def _catalog_id(catalog: dict[str, Any]) -> str | None:
    value = catalog.get("id", catalog.get("catalogId"))
    return None if value is None else str(value)


def _catalog_name(catalog: dict[str, Any]) -> str | None:
    value = catalog.get("name", catalog.get("catalogName"))
    return None if value is None else str(value)


def _row_id(row: dict[str, Any]) -> str | None:
    for key in ("id", "price_sub", "priceRowId", "price_row_id"):
        if row.get(key) not in (None, ""):
            return str(row[key])
    return None


def _status_presence(catalogs: list[dict[str, Any]], status_field: dict[str, Any] | None) -> bool:
    if status_field:
        return True
    return any(any(key in catalog for key in ("status", "enable", "enabled")) for catalog in catalogs)


def _product_name_from_row(row: dict[str, Any], product_field: dict[str, Any] | None) -> tuple[str | None, str | None]:
    raw = _row_value(row, product_field)
    product_id, product_name = _source_id_and_label(raw)
    if product_name is None:
        for key in ("productName", "product_name", "产品名称"):
            if row.get(key) not in (None, ""):
                product_name = str(row[key])
                break
    return product_id, product_name


def _fetch_products(client: _PriceClient) -> dict[str, str]:
    result: dict[str, str] = {}
    current = 1
    total: int | None = None
    fetched = 0
    while True:
        body = {
            "current": current,
            "pageSize": PAGE_SIZE,
            "keyword": "",
        }
        wrapper = client.request_json("POST", "/field/source/product", body, "产品字典读取")
        data = wrapper.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise PriceCatalogError(
                "PRICE_CATALOG_READ_FAILED", "产品字典读取失败：data.list 缺失或不是数组"
            )
        page = [item for item in data["list"] if isinstance(item, dict)]
        if "total" not in data:
            raise PriceCatalogError(
                "PRICE_PAGINATION_INCOMPLETE", "产品字典读取失败：data.total 缺失"
            )
        page_total = data.get("total")
        try:
            page_total_int = int(page_total)
        except (TypeError, ValueError) as exc:
            raise PriceCatalogError(
                "PRICE_CATALOG_READ_FAILED", "产品字典读取失败：data.total 不是整数"
            ) from exc
        if page_total_int < 0:
            raise PriceCatalogError("PRICE_CATALOG_READ_FAILED", "产品字典读取失败：data.total 为负数")
        if total is None:
            total = page_total_int
        elif total != page_total_int:
            raise PriceCatalogError("PRICE_PAGINATION_INCOMPLETE", "产品字典分页期间 total 发生变化")
        for item in page:
            item_id = item.get("id", item.get("value"))
            item_name = item.get("name", item.get("label"))
            if item_id not in (None, "") and item_name not in (None, ""):
                result[str(item_id)] = str(item_name)
        fetched += len(page)
        if fetched > (total or 0):
            raise PriceCatalogError(
                "PRICE_PAGINATION_INCOMPLETE",
                f"产品字典第 {current} 页已读取 {fetched} 条，超过 total={total}",
            )
        if fetched >= (total or 0):
            return result
        if not page:
            raise PriceCatalogError(
                "PRICE_PAGINATION_INCOMPLETE",
                f"产品字典第 {current} 页为空，但 total={total}、已读取={fetched}",
            )
        current += 1


def _fetch_price_catalogs(client: _PriceClient) -> tuple[list[dict[str, Any]], int, int]:
    catalogs: list[dict[str, Any]] = []
    current = 1
    total: int | None = None
    page_count = 0
    fetched = 0
    while True:
        body = {
            "current": current,
            "pageSize": PAGE_SIZE,
            "sort": {},
            "combineSearch": {"searchMode": "AND", "conditions": []},
            "keyword": "",
            "viewId": "ALL",
            "filters": [],
        }
        wrapper = client.request_json("POST", "/field/source/price", body, "价格目录读取")
        data = wrapper.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise PriceCatalogError(
                "PRICE_CATALOG_READ_FAILED", "价格目录读取失败：data.list 缺失或不是数组"
            )
        page = [item for item in data["list"] if isinstance(item, dict)]
        if "total" not in data:
            raise PriceCatalogError(
                "PRICE_PAGINATION_INCOMPLETE", "价格目录读取失败：data.total 缺失"
            )
        page_total = data.get("total")
        try:
            page_total_int = int(page_total)
        except (TypeError, ValueError) as exc:
            raise PriceCatalogError(
                "PRICE_CATALOG_READ_FAILED", "价格目录读取失败：data.total 不是整数"
            ) from exc
        if page_total_int < 0:
            raise PriceCatalogError("PRICE_CATALOG_READ_FAILED", "价格目录读取失败：data.total 为负数")
        if total is None:
            total = page_total_int
        elif total != page_total_int:
            raise PriceCatalogError(
                "PRICE_PAGINATION_INCOMPLETE",
                f"价格目录分页期间 total 从 {total} 变为 {page_total_int}",
            )
        catalogs.extend(page)
        fetched += len(page)
        page_count = current
        if fetched > (total or 0):
            raise PriceCatalogError(
                "PRICE_PAGINATION_INCOMPLETE",
                f"价格目录第 {current} 页已读取 {fetched} 条，超过 total={total}",
            )
        if fetched >= (total or 0):
            return catalogs, total or 0, page_count
        if not page:
            raise PriceCatalogError(
                "PRICE_PAGINATION_INCOMPLETE",
                f"价格目录第 {current} 页为空，但 total={total}、已读取={fetched}",
            )
        current += 1


def _normalize_rows(
    catalogs: list[dict[str, Any]],
    form: dict[str, Any],
    queried_at: str,
    include_disabled: bool,
    client: _PriceClient,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    fields = form["fieldMappings"]
    product_parent = form["products"]
    child_fields = form["productFields"]
    status_field = fields.get("catalog_status")
    status_known = _status_presence(catalogs, status_field)

    pending_product_ids: set[str] = set()
    product_names: dict[str, str] = {}
    row_contexts: list[tuple[dict[str, Any], dict[str, Any], str, str, str | None, str | None]] = []
    issues: list[dict[str, Any]] = []
    included_catalogs = 0
    for catalog in catalogs:
        status = _catalog_status(catalog, status_field, status_known)
        if not include_disabled and status != "enabled":
            continue
        included_catalogs += 1
        catalog_id = _catalog_id(catalog)
        catalog_name = _catalog_name(catalog)
        if catalog_id is None or catalog_name is None:
            issues.append(
                {
                    "type": "catalog_incomplete",
                    "catalog_id": catalog_id,
                    "message": "价格主表缺少 id 或 name",
                }
            )
        rows = _products_rows(catalog, product_parent)
        if not rows:
            issues.append(
                {
                    "type": "products_empty",
                    "catalog_id": catalog_id,
                    "message": "价格主表没有 products 子行",
                }
            )
        for row in rows:
            product_id, product_name = _product_name_from_row(row, fields.get("product"))
            if product_id and product_name:
                product_names[product_id] = product_name
            elif product_id:
                pending_product_ids.add(product_id)
            row_contexts.append((catalog, row, status, catalog_id or "", product_id, product_name))

    if pending_product_ids:
        dictionary = _fetch_products(client)
        for product_id in pending_product_ids:
            if product_id in dictionary:
                product_names[product_id] = dictionary[product_id]

    rows_out: list[dict[str, Any]] = []
    for catalog, row, status, catalog_id, product_id, product_name in row_contexts:
        if product_name is None and product_id:
            product_name = product_names.get(product_id)
        price_row_id = _row_id(row)
        if price_row_id is None:
            issues.append(
                {
                    "type": "price_row_incomplete",
                    "catalog_id": catalog_id or None,
                    "message": "价格子行缺少 id/price_sub",
                }
            )

        def child_value(semantic: str) -> Any:
            return _row_value(row, fields.get(semantic))

        try:
            normalized = {
                "catalog_id": catalog_id or None,
                "catalog_name": _catalog_name(catalog),
                "catalog_status": status,
                "price_row_id": price_row_id,
                "product_id": product_id,
                "product_name": product_name,
                "sku": _unwrap_scalar(child_value("sku")),
                "description": _unwrap_scalar(child_value("description")),
                "product_version": _unwrap_scalar(child_value("product_version")),
                "purchase_mode": _option_label(fields.get("purchase_mode"), child_value("purchase_mode")),
                "income_type": _option_label(fields.get("income_type"), child_value("income_type")),
                "unit": _option_label(fields.get("unit"), child_value("unit")),
                "service_tier": _option_label(fields.get("service_tier"), child_value("service_tier")),
                "currency": _option_label(fields.get("currency"), child_value("currency")),
                "standard_price_tax_included": _number(
                    child_value("standard_price_tax_included"), "含税成交指导价"
                ),
                "tax_rate_percent": _percent(child_value("tax_rate_percent"), "税率"),
                "invoice_item": _option_label(fields.get("invoice_item"), child_value("invoice_item")),
                "important_notes": _unwrap_scalar(child_value("important_notes")),
                "queried_at": queried_at,
            }
        except PriceCatalogError:
            raise
        if normalized["product_id"] is None:
            issues.append(
                {
                    "type": "price_row_incomplete",
                    "catalog_id": catalog_id or None,
                    "price_row_id": price_row_id,
                    "message": "价格子行缺少产品字段或产品 ID",
                }
            )
        rows_out.append(normalized)
    return rows_out, issues, included_catalogs


def _match_text(value: Any, expected: str) -> bool:
    if value in (None, ""):
        return False
    actual = str(value).strip().casefold()
    wanted = str(expected).strip().casefold()
    return actual == wanted or wanted in actual


def _filter_rows(rows: list[dict[str, Any]], filters: dict[str, str | None]) -> list[dict[str, Any]]:
    output = rows
    for field in ("product_name", "purchase_mode", "income_type", "catalog_name"):
        wanted = filters.get(field)
        if wanted:
            output = [row for row in output if _match_text(row.get(field), wanted)]
    sku = filters.get("sku")
    if sku:
        wanted = sku.strip().casefold()
        output = [row for row in output if str(row.get("sku") or "").strip().casefold() == wanted]
    return output


def _queried_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _price_form_result(client: _PriceClient) -> dict[str, Any]:
    form = _parse_price_form(client.request_json("GET", "/price/module/form", None, "价格表单读取"))
    form["queriedAt"] = _queried_at()
    return {"code": SUCCESS_CODE, "data": form}


def _price_result(
    client: _PriceClient,
    *,
    filters: dict[str, str | None],
    include_disabled: bool,
) -> dict[str, Any]:
    queried_at = _queried_at()
    form = _parse_price_form(client.request_json("GET", "/price/module/form", None, "价格表单读取"))
    catalogs, source_total, page_count = _fetch_price_catalogs(client)
    rows, issues, included_catalogs = _normalize_rows(
        catalogs, form, queried_at, include_disabled, client
    )
    filtered = _filter_rows(rows, filters)
    if filters.get("sku") and not filtered:
        raise PriceCatalogError(
            "PRICE_SKU_NOT_FOUND",
            f"SKU 未命中：{filters['sku']}（已完成价格主表分页读取和 products 子行筛选）",
        )
    return {
        "code": SUCCESS_CODE,
        "data": {
            "list": filtered,
            "total": len(filtered),
            "catalogTotal": included_catalogs,
            "sourceTotal": source_total,
            "pageCount": page_count,
            "queriedAt": queried_at,
            "filters": {key: value for key, value in filters.items() if value},
            "issues": issues,
        },
    }


def _detail_masters(wrapper: dict[str, Any]) -> list[dict[str, Any]]:
    data = wrapper.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("list"), list):
            return [item for item in data["list"] if isinstance(item, dict)]
        if data.get("id") is not None:
            return [data]
    return []


def _detail_result(client: _PriceClient, identifier: str, include_disabled: bool) -> dict[str, Any]:
    if not identifier.strip():
        raise PriceCatalogError("PRICE_USAGE", "price-detail 需要价格表 ID 或价格行 ID")
    form = _parse_price_form(client.request_json("GET", "/price/module/form", None, "价格表单读取"))
    try:
        wrapper = client.request_json(
            "POST",
            "/field/source/ref-detail",
            {"dataSourceType": "PRICE", "sourceIds": [identifier]},
            "价格详情读取",
        )
        masters = _detail_masters(wrapper)
    except PriceCatalogError as exc:
        # Older CRM versions accept only master IDs here.  A row ID is still
        # a valid price-detail input, so fall back to the safe read-only full
        # page path for a detail endpoint failure; authentication failures
        # must remain fatal and must never be hidden by that fallback.
        if exc.code == "PRICE_AUTH_FAILED":
            raise
        masters = []
    known = any(
        str(master.get("id") or "") == identifier
        or any(str(row.get("id") or row.get("price_sub") or "") == identifier for row in _products_rows(master, form["products"]))
        for master in masters
    )
    if not masters or not known:
        all_masters, source_total, page_count = _fetch_price_catalogs(client)
        masters = all_masters
    else:
        source_total = len(masters)
        page_count = 1

    rows, issues, included_catalogs = _normalize_rows(
        masters, form, _queried_at(), include_disabled, client
    )
    detail_rows = [
        row
        for row in rows
        if row.get("catalog_id") == identifier or row.get("price_row_id") == identifier
    ]
    # ref-detail implementations differ between CRM releases: some return
    # only the master id/name and omit products[].  A known master without
    # rows therefore needs one safe read-only fallback to the paginated
    # source before it can be reported as not found.
    if not detail_rows and known:
        all_masters, source_total, page_count = _fetch_price_catalogs(client)
        rows, issues, included_catalogs = _normalize_rows(
            all_masters, form, _queried_at(), include_disabled, client
        )
        detail_rows = [
            row
            for row in rows
            if row.get("catalog_id") == identifier or row.get("price_row_id") == identifier
        ]
    if not detail_rows:
        raise PriceCatalogError("PRICE_DETAIL_NOT_FOUND", f"价格表或价格行未命中：{identifier}")
    return {
        "code": SUCCESS_CODE,
        "data": {
            "list": detail_rows,
            "total": len(detail_rows),
            "catalogTotal": included_catalogs,
            "sourceTotal": source_total,
            "pageCount": page_count,
            "queriedAt": _queried_at(),
            "identifier": identifier,
            "issues": issues,
        },
    }


def _parser_for_price() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--sku")
    parser.add_argument("--product")
    parser.add_argument("--purchase-mode")
    parser.add_argument("--income-type")
    parser.add_argument("--catalog")
    parser.add_argument("--include-disabled", action="store_true")
    return parser


def _parse_price_args(args: list[str]) -> tuple[dict[str, str | None], bool]:
    parser = _parser_for_price()
    try:
        parsed, unknown = parser.parse_known_args(args)
    except SystemExit as exc:
        raise PriceCatalogError("PRICE_USAGE", "crm price 参数格式不正确") from exc
    if unknown:
        raise PriceCatalogError("PRICE_USAGE", f"crm price 不支持参数：{' '.join(unknown)}")
    return (
        {
            "sku": parsed.sku,
            "product_name": parsed.product,
            "purchase_mode": parsed.purchase_mode,
            "income_type": parsed.income_type,
            "catalog_name": parsed.catalog,
        },
        bool(parsed.include_disabled),
    )


def _parse_detail_args(args: list[str]) -> tuple[str, bool]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("identifier", nargs="?")
    parser.add_argument("--include-disabled", action="store_true")
    try:
        parsed, unknown = parser.parse_known_args(args)
    except SystemExit as exc:
        raise PriceCatalogError("PRICE_USAGE", "price-detail 用法：price-detail <价格表ID或价格行ID>") from exc
    if unknown or not parsed.identifier:
        raise PriceCatalogError("PRICE_USAGE", "price-detail 用法：price-detail <价格表ID或价格行ID>")
    return parsed.identifier, bool(parsed.include_disabled)


def execute_price_command(
    args: list[str],
    *,
    domain: str,
    access_key: str,
    secret_key: str,
) -> str:
    """Execute one price command and return JSON for the CLI stdout."""
    if not args:
        raise PriceCatalogError("PRICE_USAGE", "需要 price-form、price、price-sku 或 price-detail")
    command = args[0]
    client = _PriceClient(domain, access_key, secret_key)
    if command == "price-form":
        if len(args) != 1:
            raise PriceCatalogError("PRICE_USAGE", "price-form 不接受额外参数")
        result = _price_form_result(client)
    elif command == "price":
        filters, include_disabled = _parse_price_args(args[1:])
        result = _price_result(client, filters=filters, include_disabled=include_disabled)
    elif command == "price-sku":
        if len(args) != 2 or not args[1].strip():
            raise PriceCatalogError("PRICE_USAGE", "price-sku 用法：price-sku <SKU>")
        result = _price_result(
            client,
            filters={
                "sku": args[1],
                "product_name": None,
                "purchase_mode": None,
                "income_type": None,
                "catalog_name": None,
            },
            include_disabled=False,
        )
    elif command == "price-detail":
        identifier, include_disabled = _parse_detail_args(args[1:])
        result = _detail_result(client, identifier, include_disabled)
    else:
        raise PriceCatalogError("PRICE_USAGE", f"未知价格命令：{command}")
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        output = execute_price_command(
            argv,
            domain=os.environ.get("CORDYS_CRM_DOMAIN", ""),
            access_key=os.environ.get("CORDYS_ACCESS_KEY", ""),
            secret_key=os.environ.get("CORDYS_SECRET_KEY", ""),
        )
    except PriceCatalogError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
