import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = REPO_ROOT / "tests"
SOP_ROOT = (
    REPO_ROOT
    / "skills"
    / "cordys-crm-f2c"
    / "scripts"
    / "sop"
)
SHELL_CLI = REPO_ROOT / "skills" / "cordys-crm-f2c" / "scripts" / "cordys.sh"
PYTHON_CLI = REPO_ROOT / "skills" / "cordys-crm-f2c" / "scripts" / "cordys.py"
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(SOP_ROOT))

from payload_io import (  # noqa: E402
    PayloadTransportError,
    prepare_order_split_plan,
)
from order_batch import (  # noqa: E402
    ApiResult,
    OrderBatchError,
    execute_order_batch,
)
from test_create_payload import (  # noqa: E402
    ORDER_CONTRACT_CODE,
    ORDER_CONTRACT_ID,
    ORDER_CUSTOMER_ID,
    ORDER_OWNER_ID,
    SCHEMA_PATH,
    complete_order_subtable_row,
    order_formula_form_response,
)


def _schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _parent(module: str, label: str):
    fields = _schema()["modules"][module]["fields"]
    return next(
        (field_id, field)
        for field_id, field in fields.items()
        if field.get("label") == label
        and str(field.get("type") or "").startswith("SUB_")
    )


def _top_field(module: str, label: str):
    fields = _schema()["modules"][module]["fields"]
    return next(
        (field_id, field)
        for field_id, field in fields.items()
        if field.get("label") == label
        and not str(field.get("type") or "").startswith("SUB_")
    )


def _target_value_label(field: dict, value) -> str:
    value_text = str(value)
    for option in field.get("options", []):
        if value_text in {str(option.get("value")), str(option.get("label"))}:
            return str(option["label"])
    raise AssertionError(f"test fixture option not found: {value}")


def _contract_row(
    parent_label: str,
    *,
    selector_id: str,
    product_type_id: str,
    income_label: str,
    price_sub: str,
):
    _, order_parent = _parent("order", parent_label)
    _, contract_parent = _parent("contract", parent_label)
    target = complete_order_subtable_row(
        order_parent, service_value=selector_id
    )
    target_by_label = {
        child["label"]: (child_id, child)
        for child_id, child in order_parent["subFields"].items()
    }
    if "产品" in target_by_label:
        target[target_by_label["产品"][0]] = selector_id
    elif "服务" in target_by_label:
        target[target_by_label["服务"][0]] = selector_id
    target[target_by_label["产品类型"][0]] = product_type_id
    target[target_by_label["收入类型"][0]] = income_label

    source = {}
    for source_id, source_field in contract_parent["subFields"].items():
        if source_field.get("type") == "FORMULA":
            continue
        target_match = target_by_label.get(source_field.get("label"))
        if target_match is None:
            continue
        target_id, target_field = target_match
        if target_id not in target:
            continue
        value = target[target_id]
        if source_field.get("type") in {"SELECT", "RADIO"}:
            label = _target_value_label(target_field, value)
            value = next(
                option["value"]
                for option in source_field.get("options", [])
                if option.get("label") == label
            )
        source[source_id] = value
    source.update(
        {
            "id": f"contract-row-{price_sub}",
            "price_sub": price_sub,
        }
    )
    return source


def _fixture():
    training_contract_id, _ = _parent("contract", "培训服务")
    auth_contract_id, _ = _parent("contract", "授权及一体机")
    contract_code_id, _ = _top_field("contract", "合同编码")
    adjustment_id, _ = _top_field("contract", "调整金额")
    split_id, split_field = _top_field("contract", "是否已拆订单")
    split_no = next(
        option["value"]
        for option in split_field["options"]
        if option["label"] == "否"
    )
    split_yes = next(
        option["value"]
        for option in split_field["options"]
        if option["label"] == "是"
    )
    contract_data = {
        "id": ORDER_CONTRACT_ID,
        "owner": ORDER_OWNER_ID,
        "customerId": ORDER_CUSTOMER_ID,
        "moduleFields": [
            {"fieldId": contract_code_id, "fieldValue": ORDER_CONTRACT_CODE},
            {"fieldId": adjustment_id, "fieldValue": 100},
            {"fieldId": split_id, "fieldValue": split_no},
            {
                "fieldId": training_contract_id,
                "fieldValue": [
                    _contract_row(
                        "培训服务",
                        selector_id="service-a",
                        product_type_id="product-a",
                        income_label="培训服务",
                        price_sub="price-a-1",
                    ),
                    _contract_row(
                        "培训服务",
                        selector_id="service-a",
                        product_type_id="product-a",
                        income_label="培训服务",
                        price_sub="price-a-2",
                    ),
                    _contract_row(
                        "培训服务",
                        selector_id="service-a",
                        product_type_id="product-a",
                        income_label="专业服务",
                        price_sub="price-a-3",
                    ),
                ],
            },
            {
                "fieldId": auth_contract_id,
                "fieldValue": [
                    _contract_row(
                        "授权及一体机",
                        selector_id="product-b",
                        product_type_id="product-b",
                        income_label="一体机",
                        price_sub="price-b-1",
                    )
                ],
            },
        ],
    }
    contract_raw = json.dumps(
        {"code": 100200, "data": contract_data}, ensure_ascii=False
    )
    product_raw = json.dumps(
        {
            "code": 100200,
            "data": {
                "list": [
                    {"id": "product-a", "name": "JumpServer 企业版"},
                    {"id": "product-b", "name": "MaxKB 一体机"},
                ],
                "total": 2,
            },
        },
        ensure_ascii=False,
    )
    order_form_raw, _ = order_formula_form_response()
    contract_form_raw = json.dumps(
        {
            "code": 100200,
            "data": {"fields": [], "formProp": {"layout": "contract"}},
        },
        ensure_ascii=False,
    )
    request_raw = json.dumps(
        {"contractId": ORDER_CONTRACT_ID, "moduleFields": []},
        ensure_ascii=False,
    )
    return {
        "request_raw": request_raw,
        "contract_raw": contract_raw,
        "contract_data": contract_data,
        "product_raw": product_raw,
        "order_form_raw": order_form_raw,
        "contract_form_raw": contract_form_raw,
        "split_id": split_id,
        "split_yes": split_yes,
        "adjustment_id": adjustment_id,
    }


def _contract_raw_with_field(fixture, field_id, value):
    contract_data = deepcopy(fixture["contract_data"])
    item = next(
        field
        for field in contract_data["moduleFields"]
        if str(field.get("fieldId")) == str(field_id)
    )
    item["fieldValue"] = value
    return json.dumps(
        {"code": 100200, "data": contract_data}, ensure_ascii=False
    )


def test_split_plan_groups_rows_and_preserves_existing_name_template():
    fixture = _fixture()
    plan = prepare_order_split_plan(
        fixture["request_raw"],
        SCHEMA_PATH,
        fixture["order_form_raw"],
        fixture["contract_raw"],
        fixture["product_raw"],
    )

    assert plan["groupCount"] == 3
    groups = {
        (
            item["groupKey"]["productOrServiceId"],
            item["groupKey"]["incomeType"],
        ): item
        for item in plan["orders"]
    }
    same_group = groups[("service-a", "培训服务")]
    assert same_group["sourceRowCount"] == 2
    assert same_group["amount"] == 13000
    assert same_group["adjustmentAmount"] == 50
    assert same_group["effectiveAmount"] == 12950
    assert same_group["name"] == (
        f"{ORDER_CONTRACT_CODE}-JumpServer 企业版-${{订单编号}}"
    )
    assert "培训服务" not in same_group["name"].removeprefix(
        f"{ORDER_CONTRACT_CODE}-JumpServer 企业版"
    )

    professional = groups[("service-a", "专业服务")]
    appliance = groups[("product-b", "一体机")]
    assert professional["sourceRowCount"] == 1
    assert appliance["sourceRowCount"] == 1
    assert professional["adjustmentAmount"] == 25
    assert appliance["adjustmentAmount"] == 25
    assert appliance["name"] == (
        f"{ORDER_CONTRACT_CODE}-MaxKB 一体机-${{订单编号}}"
    )
    assert sum(item["adjustmentAmount"] for item in plan["orders"]) == 100
    assert all(
        item["body"]["name"] == item["name"] for item in plan["orders"]
    )
    assert all(
        item["body"]["moduleFormConfigDTO"]
        for item in plan["orders"]
    )


def test_split_plan_rejects_manually_materialized_group_fields():
    fixture = _fixture()
    order_parent_id, _ = _parent("order", "培训服务")
    manual_request = json.dumps(
        {
            "contractId": ORDER_CONTRACT_ID,
            "moduleFields": [
                {"fieldId": order_parent_id, "fieldValue": [{"manual": True}]}
            ],
        },
        ensure_ascii=False,
    )

    with pytest.raises(PayloadTransportError, match="只接受交付团队"):
        prepare_order_split_plan(
            manual_request,
            SCHEMA_PATH,
            fixture["order_form_raw"],
            fixture["contract_raw"],
            fixture["product_raw"],
        )


class FakeTransport:
    def __init__(
        self,
        fixture,
        order_results,
        *,
        contract_reads=None,
        contract_update_result=None,
    ):
        self.fixture = fixture
        self.order_results = list(order_results)
        self.contract_reads = list(contract_reads or [])
        self.contract_update_result = contract_update_result
        self.calls = []
        self.contract_update_body = None

    def request(self, method, path, body=None):
        self.calls.append((method, path, deepcopy(body)))
        if method == "GET" and path == "/order/module/form":
            return ApiResult(self.fixture["order_form_raw"], 200)
        if method == "GET" and path == f"/contract/get/{ORDER_CONTRACT_ID}":
            if self.contract_reads:
                return ApiResult(self.contract_reads.pop(0), 200)
            return ApiResult(self.fixture["contract_raw"], 200)
        if method == "POST" and path == "/field/source/product":
            return ApiResult(self.fixture["product_raw"], 200)
        if method == "GET" and path == "/contract/module/form":
            return ApiResult(self.fixture["contract_form_raw"], 200)
        if method == "POST" and path == "/order/add":
            return self.order_results.pop(0)
        if method == "POST" and path == "/contract/update":
            self.contract_update_body = deepcopy(body)
            if self.contract_update_result is not None:
                return self.contract_update_result
            return ApiResult(
                json.dumps({"code": 100200, "data": {"id": ORDER_CONTRACT_ID}}),
                200,
            )
        raise AssertionError(f"unexpected transport call: {method} {path}")


def _success(order_id, *, http_status=200, transport_error=""):
    return ApiResult(
        json.dumps({"code": 100200, "data": {"id": order_id}}),
        http_status,
        transport_error,
    )


def test_batch_accepts_false_http_failure_and_updates_contract_only_last():
    fixture = _fixture()
    transport = FakeTransport(
        fixture,
        [
            _success("order-1", http_status=500, transport_error="HTTP 500"),
            _success("order-2"),
            _success("order-3"),
        ],
    )
    result, status = execute_order_batch(
        fixture["request_raw"], SCHEMA_PATH, transport=transport
    )

    assert status == 0
    assert result["code"] == 100200
    assert result["writeState"] == "complete"
    assert [
        item["orderId"] for item in result["data"]["createdOrders"]
    ] == ["order-1", "order-2", "order-3"]
    write_paths = [
        path for method, path, _ in transport.calls if method == "POST"
    ]
    assert write_paths[-4:] == [
        "/order/add",
        "/order/add",
        "/order/add",
        "/contract/update",
    ]
    split_values = {
        str(item["fieldId"]): item["fieldValue"]
        for item in transport.contract_update_body["moduleFields"]
    }
    assert fixture["split_id"] in split_values
    assert transport.contract_update_body["moduleFormConfigDTO"]["formProp"]


def test_batch_stops_after_partial_success_and_forbids_whole_retry():
    fixture = _fixture()
    transport = FakeTransport(
        fixture,
        [
            _success("order-1"),
            ApiResult("", None, "timed out"),
            _success("must-not-be-used"),
        ],
    )
    result, status = execute_order_batch(
        fixture["request_raw"], SCHEMA_PATH, transport=transport
    )

    assert status == 1
    assert result["code"] == 0
    assert result["writeState"] == "partial"
    assert result["retryAllowed"] is False
    assert [
        item["orderId"] for item in result["data"]["createdOrders"]
    ] == ["order-1"]
    assert len(result["data"]["remainingGroups"]) == 1
    assert result["data"]["contractSplitUpdated"] is False
    assert sum(
        1
        for method, path, _ in transport.calls
        if method == "POST" and path == "/order/add"
    ) == 2
    assert not any(
        method == "POST" and path == "/contract/update"
        for method, path, _ in transport.calls
    )


def test_adjustment_rounding_residual_is_absorbed_by_last_group():
    fixture = _fixture()
    fixture["contract_raw"] = _contract_raw_with_field(
        fixture, fixture["adjustment_id"], 0.01
    )

    plan = prepare_order_split_plan(
        fixture["request_raw"],
        SCHEMA_PATH,
        fixture["order_form_raw"],
        fixture["contract_raw"],
        fixture["product_raw"],
    )

    assert [item["adjustmentAmount"] for item in plan["orders"]] == [
        0,
        0,
        0.01,
    ]
    assert sum(item["adjustmentAmount"] for item in plan["orders"]) == 0.01


def test_contract_update_transport_error_is_accepted_only_after_readback():
    fixture = _fixture()
    split_applied_raw = _contract_raw_with_field(
        fixture, fixture["split_id"], fixture["split_yes"]
    )
    transport = FakeTransport(
        fixture,
        [_success("order-1"), _success("order-2"), _success("order-3")],
        contract_reads=[
            fixture["contract_raw"],
            fixture["contract_raw"],
            split_applied_raw,
        ],
        contract_update_result=ApiResult("", None, "timed out"),
    )

    result, status = execute_order_batch(
        fixture["request_raw"], SCHEMA_PATH, transport=transport
    )

    assert status == 0
    assert result["writeState"] == "complete"
    assert result["data"]["contractSplitUpdated"] is True
    assert (
        result["data"]["contractSplitUpdateState"]
        == "verified_after_transport_error"
    )
    assert sum(
        1
        for method, path, _ in transport.calls
        if method == "POST" and path == "/contract/update"
    ) == 1


def test_contract_update_unconfirmed_never_recreates_orders_or_retries_update():
    fixture = _fixture()
    transport = FakeTransport(
        fixture,
        [_success("order-1"), _success("order-2"), _success("order-3")],
        contract_reads=[
            fixture["contract_raw"],
            fixture["contract_raw"],
            fixture["contract_raw"],
        ],
        contract_update_result=ApiResult("", None, "timed out"),
    )

    result, status = execute_order_batch(
        fixture["request_raw"], SCHEMA_PATH, transport=transport
    )

    assert status == 1
    assert result["writeState"] == "orders_created_contract_update_unknown"
    assert result["retryAllowed"] is False
    assert len(result["data"]["createdOrders"]) == 3
    assert result["data"]["contractSplitUpdated"] is False
    assert sum(
        1
        for method, path, _ in transport.calls
        if method == "POST" and path == "/order/add"
    ) == 3
    assert sum(
        1
        for method, path, _ in transport.calls
        if method == "POST" and path == "/contract/update"
    ) == 1


def test_contract_already_split_blocks_every_order_post():
    fixture = _fixture()
    fixture["contract_raw"] = _contract_raw_with_field(
        fixture, fixture["split_id"], fixture["split_yes"]
    )
    transport = FakeTransport(fixture, [])

    with pytest.raises(OrderBatchError, match="是否已拆订单=是"):
        execute_order_batch(
            fixture["request_raw"], SCHEMA_PATH, transport=transport
        )

    assert not any(
        method == "POST" and path in {"/order/add", "/contract/update"}
        for method, path, _ in transport.calls
    )


def test_both_cli_entrypoints_default_order_create_to_batch_orchestrator():
    shell_text = SHELL_CLI.read_text(encoding="utf-8")
    python_text = PYTHON_CLI.read_text(encoding="utf-8")

    assert "order-split-enabled" in shell_text
    assert '"${SOP_DIR}/order_batch.py"' in shell_text
    assert "order_split_enabled(payload)" in python_text
    assert "execute_order_batch(" in python_text
