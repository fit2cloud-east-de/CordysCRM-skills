"""Safe multi-order creation orchestrator.

One invocation plans every ``product/service + income type`` group before the
first write, creates orders sequentially, and updates the contract split flag
only after every order has a confirmed ``data.id``.  No write is retried.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from payload_io import (
    PayloadTransportError,
    extract_form_config,
    prepare_order_split_plan,
)


UPDATE_DENY_FIELDS = {
    "attachmentMap",
    "optionMap",
    "contactName",
    "customerName",
    "departmentName",
    "ownerName",
    "createUser",
    "updateUser",
    "createUserName",
    "updateUserName",
    "createTime",
    "updateTime",
    "followerName",
    "follower",
    "followTime",
    "stage",
    "stageName",
    "stageUpdateTime",
    "lastStage",
    "inCustomerPool",
    "poolId",
    "possible",
    "reservedDays",
    "failureReason",
    "organizationId",
    "departmentId",
}


@dataclass(frozen=True)
class ApiResult:
    text: str
    http_status: int | None = None
    transport_error: str = ""


class OrderBatchError(RuntimeError):
    """The batch could not be planned or safely started."""


class UrllibTransport:
    """Small no-retry JSON transport used by the order batch workflow."""

    def __init__(
        self,
        domain: str,
        access_key: str,
        secret_key: str,
        *,
        timeout: float = 30,
    ) -> None:
        parsed = urlparse(domain)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise OrderBatchError(
                "CORDYS_CRM_DOMAIN 必须是合法 HTTPS 根地址，不能包含路径、查询参数或凭证"
            )
        if not access_key:
            raise OrderBatchError("未设置 CORDYS_ACCESS_KEY")
        if not secret_key:
            raise OrderBatchError("未设置 CORDYS_SECRET_KEY")
        self.domain = domain.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "X-Access-Key": access_key,
            "X-Secret-Key": secret_key,
            "X-Request-Source": "SKILL",
            "Content-Type": "application/json; charset=utf-8",
        }
        # Match cordys.sh's --noproxy '*' behavior; CRM credentials must not
        # be sent through an ambient system proxy.
        self.opener = request.build_opener(request.ProxyHandler({}))

    def request(self, method: str, path: str, body: dict | None = None) -> ApiResult:
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url=f"{self.domain}/{path.lstrip('/')}",
            data=payload,
            headers=self.headers,
            method=method.upper(),
        )
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                text = response.read().decode(charset, errors="replace")
                return ApiResult(text=text, http_status=response.status)
        except HTTPError as exc:
            try:
                text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                text = ""
            return ApiResult(
                text=text,
                http_status=exc.code,
                transport_error=f"HTTP {exc.code}",
            )
        except (URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
            return ApiResult(text="", transport_error=str(exc))


def _parse_response(result: ApiResult) -> dict | None:
    try:
        value = json.loads(result.text)
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _is_business_success(value: dict | None) -> bool:
    return isinstance(value, dict) and str(value.get("code")) == "100200"


def _require_business_response(result: ApiResult, context: str) -> dict:
    value = _parse_response(result)
    if _is_business_success(value):
        return value
    status = (
        f"HTTP {result.http_status}"
        if result.http_status is not None
        else "无 HTTP 状态"
    )
    detail = result.transport_error or (
        str(value.get("message") or "") if isinstance(value, dict) else "响应不是 JSON"
    )
    raise OrderBatchError(f"{context}失败：{status} {detail}".strip())


def _record_data(wrapper: dict, expected_id: str, context: str) -> dict:
    data = wrapper.get("data") if isinstance(wrapper, dict) else None
    if (
        not isinstance(data, dict)
        or str(data.get("id") or "") != expected_id
        or not isinstance(data.get("moduleFields"), list)
    ):
        raise OrderBatchError(f"{context}未返回匹配 ID 的完整记录")
    return data


def _module_field_value(record: dict, field_id: str):
    matches = [
        item.get("fieldValue")
        for item in record.get("moduleFields") or []
        if isinstance(item, dict)
        and str(item.get("fieldId") or "") == str(field_id)
    ]
    if len(matches) > 1:
        raise OrderBatchError(f"合同详情字段重复：{field_id}")
    return matches[0] if matches else None


def _contract_split_is_applied(record: dict, update: dict) -> bool:
    current = _module_field_value(record, str(update["fieldId"]))
    return str(current or "").strip() == str(update["fieldValue"])


def _merge_contract_update_body(
    record: dict,
    form_raw: str,
    update: dict,
) -> dict:
    if str(record.get("id") or "") != str(update["id"]):
        raise OrderBatchError("合同回写前读回 ID 不一致")
    body = {
        key: value
        for key, value in record.items()
        if key != "moduleFields"
        and key not in UPDATE_DENY_FIELDS
        and value is not None
    }
    module_fields = {}
    for item in record.get("moduleFields") or []:
        if not isinstance(item, dict) or item.get("fieldId") is None:
            continue
        module_fields[str(item["fieldId"])] = item.get("fieldValue")
    module_fields[str(update["fieldId"])] = update["fieldValue"]
    body["moduleFields"] = [
        {"fieldId": field_id, "fieldValue": value}
        for field_id, value in module_fields.items()
    ]
    body["moduleFormConfigDTO"] = extract_form_config(form_raw, "contract")
    return body


def _public_plan_order(item: dict) -> dict:
    return {
        key: item[key]
        for key in (
            "groupKey",
            "productTypeId",
            "productTypeLabel",
            "sourceRows",
            "sourceRowCount",
            "name",
            "amount",
            "adjustmentAmount",
            "effectiveAmount",
        )
    }


def _base_result_data(plan: dict, created: list[dict]) -> dict:
    return {
        "contractId": plan["contractId"],
        "contractCode": plan["contractCode"],
        "plannedOrderCount": plan["groupCount"],
        "contractAdjustmentAmount": plan["contractAdjustmentAmount"],
        "createdOrders": created,
        "contractSplitUpdated": False,
    }


def _safe_failure_detail(result: ApiResult):
    parsed = _parse_response(result)
    if parsed is not None:
        return parsed
    text = (result.text or "").strip()
    return {
        "httpStatus": result.http_status,
        "transportError": result.transport_error,
        "response": text[:2000],
    }


def _order_failure(
    plan: dict,
    created: list[dict],
    failed_index: int,
    result: ApiResult,
) -> dict:
    failed = plan["orders"][failed_index]
    remaining = plan["orders"][failed_index + 1 :]
    unknown = bool(result.transport_error) or not result.text.strip()
    return {
        "code": 0,
        "message": (
            "订单批次状态不明，已停止后续创建且禁止整批重试"
            if unknown
            else "订单创建未成功，已停止后续创建且禁止整批重试"
        ),
        "writeState": "partial" if created else ("unknown" if unknown else "failed"),
        "retryAllowed": False,
        "data": {
            **_base_result_data(plan, created),
            "failedGroup": _public_plan_order(failed),
            "remainingGroups": [_public_plan_order(item) for item in remaining],
            "failure": _safe_failure_detail(result),
        },
    }


def _contract_update_failure(
    plan: dict,
    created: list[dict],
    result: ApiResult,
) -> dict:
    return {
        "code": 0,
        "message": (
            "全部订单已创建，但合同“是否已拆订单”未确认回写成功；"
            "禁止重新创建订单，只能查证后单独处理合同标记"
        ),
        "writeState": "orders_created_contract_update_unknown",
        "retryAllowed": False,
        "data": {
            **_base_result_data(plan, created),
            "failedOperation": "contractSplitUpdate",
            "failure": _safe_failure_detail(result),
        },
    }


def _created_order(item: dict, order_id: str) -> dict:
    return {**_public_plan_order(item), "orderId": order_id}


def execute_order_batch(
    raw: str,
    schema_path: str | os.PathLike,
    *,
    transport=None,
    domain: str = "",
    access_key: str = "",
    secret_key: str = "",
    timeout: float = 30,
) -> tuple[dict, int]:
    """Plan and execute one contract's orders without retrying any write."""
    if transport is None:
        transport = UrllibTransport(
            domain, access_key, secret_key, timeout=timeout
        )

    # Parse contractId locally before any network call.
    try:
        caller = json.loads((raw or "").lstrip("\ufeff"))
    except json.JSONDecodeError as exc:
        raise OrderBatchError(f"订单拆单 create JSON 解析失败: {exc}") from exc
    if not isinstance(caller, dict):
        raise OrderBatchError("订单拆单 create payload 顶层必须是 JSON 对象")
    contract_id = str(caller.get("contractId") or "").strip()
    if not contract_id:
        raise OrderBatchError("订单拆单 create 必须提供 contractId")

    # All required reads complete before the first order POST.  A missing
    # schema/form/catalog therefore produces zero writes.
    order_form_result = transport.request("GET", "/order/module/form")
    _require_business_response(order_form_result, "获取订单表单配置")
    contract_result = transport.request(
        "GET", f"/contract/get/{contract_id}"
    )
    contract_wrapper = _require_business_response(
        contract_result, "获取订单源合同详情"
    )
    _record_data(contract_wrapper, contract_id, "订单源合同详情")
    product_result = transport.request(
        "POST",
        "/field/source/product",
        {
            "current": 1,
            "pageSize": 500,
            "sort": {},
            "combineSearch": {"searchMode": "AND", "conditions": []},
            "keyword": "",
            "viewId": "ALL",
            "filters": [],
        },
    )
    _require_business_response(product_result, "获取订单产品目录")
    contract_form_result = transport.request("GET", "/contract/module/form")
    _require_business_response(contract_form_result, "获取合同表单配置")

    try:
        plan = prepare_order_split_plan(
            raw,
            schema_path,
            order_form_result.text,
            contract_result.text,
            product_result.text,
        )
    except PayloadTransportError as exc:
        raise OrderBatchError(str(exc)) from exc

    created = []
    for index, item in enumerate(plan["orders"]):
        result = transport.request("POST", "/order/add", item["body"])
        value = _parse_response(result)
        data = value.get("data") if isinstance(value, dict) else None
        order_id = (
            str(data.get("id") or "").strip()
            if isinstance(data, dict)
            else ""
        )
        # A code=100200 body is authoritative even when the HTTP layer says
        # 500; this is Cordys' known "false failure, real success" behavior.
        if not _is_business_success(value) or not order_id:
            return _order_failure(plan, created, index, result), 1
        created.append(_created_order(item, order_id))

    split_update = plan["contractSplitUpdate"]
    latest_result = transport.request(
        "GET", f"/contract/get/{contract_id}"
    )
    try:
        latest_wrapper = _require_business_response(
            latest_result, "合同拆单标记回写前读回"
        )
        latest_record = _record_data(
            latest_wrapper, contract_id, "合同拆单标记回写前读回"
        )
    except OrderBatchError:
        return _contract_update_failure(plan, created, latest_result), 1

    update_state = "updated"
    if not _contract_split_is_applied(latest_record, split_update):
        try:
            update_body = _merge_contract_update_body(
                latest_record, contract_form_result.text, split_update
            )
        except (OrderBatchError, PayloadTransportError) as exc:
            synthetic = ApiResult(text="", transport_error=str(exc))
            return _contract_update_failure(plan, created, synthetic), 1
        update_result = transport.request(
            "POST", "/contract/update", update_body
        )
        update_value = _parse_response(update_result)
        if not _is_business_success(update_value):
            # The update POST is never resent.  One GET checks the requested
            # field only; if it landed despite the error, accept that terminal
            # state, otherwise report unknown and stop.
            verify_result = transport.request(
                "GET", f"/contract/get/{contract_id}"
            )
            verified = False
            try:
                verify_wrapper = _require_business_response(
                    verify_result, "合同拆单标记写后核验"
                )
                verify_record = _record_data(
                    verify_wrapper, contract_id, "合同拆单标记写后核验"
                )
                verified = _contract_split_is_applied(
                    verify_record, split_update
                )
            except OrderBatchError:
                verified = False
            if not verified:
                return _contract_update_failure(
                    plan, created, update_result
                ), 1
            update_state = "verified_after_transport_error"
    else:
        update_state = "already_applied"

    return (
        {
            "code": 100200,
            "message": (
                f"已按产品+收入类型创建 {len(created)} 张订单，"
                "并将合同是否已拆订单更新为是"
            ),
            "writeState": "complete",
            "retryAllowed": False,
            "data": {
                **_base_result_data(plan, created),
                "contractSplitUpdated": True,
                "contractSplitUpdateState": update_state,
            },
        },
        0,
    )


def _timeout_from_env() -> float:
    raw = str(os.environ.get("CORDYS_HTTP_TIMEOUT") or "30").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise OrderBatchError("CORDYS_HTTP_TIMEOUT 必须是秒数") from exc
    if value <= 0 or value > 300:
        raise OrderBatchError("CORDYS_HTTP_TIMEOUT 必须在 0 到 300 秒之间")
    return value


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("错误: 用法: order_batch.py <field-schema.json> < create.json", file=sys.stderr)
        return 1
    schema_path = Path(args[0])
    raw = sys.stdin.buffer.read().decode("utf-8-sig")
    try:
        result, status = execute_order_batch(
            raw,
            schema_path,
            domain=str(os.environ.get("CORDYS_CRM_DOMAIN") or ""),
            access_key=str(os.environ.get("CORDYS_ACCESS_KEY") or ""),
            secret_key=str(os.environ.get("CORDYS_SECRET_KEY") or ""),
            timeout=_timeout_from_env(),
        )
    except (OrderBatchError, PayloadTransportError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
