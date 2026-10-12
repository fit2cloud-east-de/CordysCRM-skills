import json
import sys
from pathlib import Path

import pytest


SKILL = Path(__file__).resolve().parents[1] / "skills" / "cordys-crm-f2c"
SOP = SKILL / "scripts" / "sop"
sys.path.insert(0, str(SOP))

import price_catalog  # noqa: E402


def _form_response():
    def child(field_id, name, field_type="INPUT", business_key=None, options=None):
        value = {
            "id": field_id,
            "name": name,
            "type": field_type,
            "required": False,
        }
        if business_key:
            value["businessKey"] = business_key
        if options is not None:
            value["options"] = options
        return value

    return {
        "code": 100200,
        "data": {
            "fields": [
                {"id": "catalog-status", "name": "状态", "type": "RADIO", "businessKey": "status", "options": [
                    {"value": "1", "label": "启用"},
                    {"value": "0", "label": "禁用"},
                ]},
                {
                    "id": "products",
                    "name": "产品明细",
                    "type": "SUB_PRODUCT",
                    "businessKey": "products",
                    "subFields": [
                        child("product-field", "产品", "DATA_SOURCE", "product"),
                        child("sku-field", "产品SKU", "INPUT", "productSku"),
                        child("description-field", "描述", "TEXTAREA", "description"),
                        child("version-field", "产品版本", "INPUT", "productVersion"),
                        child("purchase-field", "购买方式", "SELECT", "purchaseMode", [
                            {"value": "purchase-software", "label": "软件授权"},
                            {"value": "purchase-year", "label": "按年订阅"},
                        ]),
                        child("income-field", "收入类型", "SELECT", "incomeType", [
                            {"value": "income-software", "label": "软件授权"},
                            {"value": "income-subscription", "label": "软件订阅"},
                        ]),
                        child("unit-field", "单位", "SELECT", "unit", [
                            {"value": "unit-set", "label": "套"},
                        ]),
                        child("tier-field", "服务等级", "RADIO", "serviceTier", [
                            {"value": "tier-pro", "label": "专业版"},
                        ]),
                        child("currency-field", "币种", "SELECT", "currency", [
                            {"value": "CNY", "label": "人民币"},
                        ]),
                        child("price-field", "成交指导价（含税）", "INPUT_NUMBER", "amount"),
                        child("tax-field", "税率", "INPUT_NUMBER", "taxRate"),
                        child("invoice-field", "开票项目", "INPUT", "invoiceItem"),
                        child("notes-field", "重要说明", "TEXTAREA", "importantNotes"),
                    ],
                },
            ]
        },
    }


def _catalog(catalog_id, name, status, row_id, sku, product_id="product-1", price=90000, tax=0.13):
    return {
        "id": catalog_id,
        "name": name,
        "status": status,
        "products": [
            {
                "id": row_id,
                "product-field": product_id,
                "sku-field": sku,
                "description-field": "标准授权",
                "version-field": "V1",
                "purchase-field": "purchase-software",
                "income-field": "income-software",
                "unit-field": "unit-set",
                "tier-field": "tier-pro",
                "currency-field": "CNY",
                "price-field": f"{price:,}",
                "tax-field": tax,
                "invoice-field": "软件",
                "notes-field": "维保按授权金额的 10% 计算",
            }
        ],
    }


class FakePriceClient:
    catalogs = [
        _catalog("catalog-enabled", "销售目录（2026v1） - 授权及一体机", 1, "row-std", "2026v1-JS-STD-SW"),
        _catalog("catalog-disabled", "旧版目录", 0, "row-disabled", "2026v1-JS-STD-SW", price=80000),
    ]

    def __init__(self, domain, access_key, secret_key):
        assert domain == "https://crm.example.com"
        assert access_key == "access"
        assert secret_key == "secret"
        self.calls = []

    def request_json(self, method, path, body, context):
        self.calls.append((method, path, body, context))
        if path == "/price/module/form":
            return _form_response()
        if path == "/field/source/price":
            page = body["current"]
            if page == 1:
                return {"code": 100200, "data": {"total": 2, "list": [self.catalogs[0]]}}
            return {"code": 100200, "data": {"total": 2, "list": [self.catalogs[1]]}}
        if path == "/field/source/product":
            return {"code": 100200, "data": {"total": 1, "list": [{"id": "product-1", "name": "JumpServer"}]}}
        raise AssertionError(f"unexpected request: {method} {path}")


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    monkeypatch.setattr(price_catalog, "_PriceClient", FakePriceClient)


def _run(*args):
    return json.loads(
        price_catalog.execute_price_command(
            list(args),
            domain="https://crm.example.com",
            access_key="access",
            secret_key="secret",
        )
    )


def test_price_form_returns_dynamic_main_and_products_fields():
    result = _run("price-form")
    data = result["data"]

    assert result["code"] == 100200
    assert data["products"]["fieldId"] == "products"
    assert {field["fieldId"] for field in data["productFields"]} >= {
        "sku-field",
        "price-field",
        "tax-field",
    }
    assert data["fieldMappings"]["purchase_mode"]["fieldId"] == "purchase-field"
    assert data["fieldMappings"]["standard_price_tax_included"]["fieldId"] == "price-field"
    assert data["fieldMappings"]["catalog_status"]["fieldId"] == "catalog-status"
    assert {tuple(option.values()) for option in data["fieldMappings"]["purchase_mode"]["options"]} == {
        ("purchase-software", "软件授权"),
        ("purchase-year", "按年订阅"),
    }


def test_price_sku_reads_all_master_pages_filters_disabled_and_normalizes_row():
    result = _run("price-sku", "2026v1-JS-STD-SW")
    data = result["data"]

    assert data["sourceTotal"] == 2
    assert data["pageCount"] == 2
    assert data["total"] == 1
    row = data["list"][0]
    assert row["catalog_id"] == "catalog-enabled"
    assert row["price_row_id"] == "row-std"
    assert row["product_id"] == "product-1"
    assert row["product_name"] == "JumpServer"
    assert row["sku"] == "2026v1-JS-STD-SW"
    assert row["purchase_mode"] == "软件授权"
    assert row["income_type"] == "软件授权"
    assert row["standard_price_tax_included"] == 90000
    assert row["tax_rate_percent"] == 13
    assert row["important_notes"] == "维保按授权金额的 10% 计算"


def test_price_filters_are_applied_after_products_are_read():
    result = _run("price", "--product", "JumpServer", "--purchase-mode", "软件授权", "--income-type", "软件授权")
    assert result["data"]["total"] == 1
    assert result["data"]["list"][0]["catalog_status"] == "enabled"


def test_price_sku_miss_is_a_distinct_error():
    with pytest.raises(price_catalog.PriceCatalogError) as error:
        _run("price-sku", "does-not-exist")
    assert error.value.code == "PRICE_SKU_NOT_FOUND"
    assert "SKU 未命中" in str(error.value)
