import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "cordys-crm-f2c"
SHELL_CLI = SKILL / "scripts" / "cordys.sh"
PYTHON_CLI = SKILL / "scripts" / "cordys.py"
TRANSFORM_MODULE = SKILL / "scripts" / "sop" / "transform_lead.py"


def _load_transform_module():
    spec = importlib.util.spec_from_file_location("transform_lead_under_test", TRANSFORM_MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Headers:
    @staticmethod
    def get_content_charset():
        return "utf-8"


class _Response:
    def __init__(self, payload):
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def test_legacy_transform_entrypoints_are_hidden_and_blocked():
    shell = SHELL_CLI.read_text(encoding="utf-8")
    python = PYTHON_CLI.read_text(encoding="utf-8")

    assert 'api_write POST "${crm_base}/lead/transform"' not in shell
    assert 'return api("POST", f"{CORDYS_CRM_DOMAIN}/lead/transform"' not in python
    assert "crm transform <JSON>" not in shell
    assert "crm transition <JSON>" not in shell
    assert "crm transform <JSON>" not in python
    assert "crm transition <JSON>" not in python
    assert "transition|transform) legacy_transform_disabled" in shell
    assert 'sub_cmd in ("transition", "transform")' in python
    assert "/lead/transform|/lead/transition/account) legacy_transform_disabled" in shell
    assert 'guarded_path in ("/lead/transform", "/lead/transition/account")' in python

    result = subprocess.run(
        [sys.executable, str(PYTHON_CLI), "crm", "transform", "{}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 1
    assert "cordys_ext.sh transform" in result.stderr

    raw_result = subprocess.run(
        [sys.executable, str(PYTHON_CLI), "raw", "POST", "/lead/transform"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert raw_result.returncode == 1
    assert "cordys_ext.sh transform" in raw_result.stderr

    bash = shutil.which("bash")
    if bash:
        shell_result = subprocess.run(
            [
                bash,
                str(SHELL_CLI.relative_to(ROOT)).replace("\\", "/"),
                "raw",
                "POST",
                "/lead/transform",
                "{}",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert shell_result.returncode == 1
        assert "cordys_ext.sh transform" in shell_result.stderr


def test_transform_preserves_and_completes_opportunity_fields():
    module = _load_transform_module()
    calls = []

    def fake_urlopen(req, timeout=15):
        path = urlparse(req.full_url).path
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        calls.append((req.method, path, body))

        if path == "/lead/transform":
            return _Response({"code": 100200, "data": {"customerId": "customer-1"}})
        if path == "/global/search/opportunity":
            return _Response({
                "code": 100200,
                "data": {"list": [{
                    "id": "opportunity-1",
                    "name": "华星-MK-2026-订阅新购",
                    "owner": "owner-1",
                    "customerId": "customer-1",
                    "contactId": "contact-1",
                    "products": [],
                }]},
            })
        if path == "/opportunity/page":
            return _Response({
                "code": 100200,
                "data": {"list": [{
                    "id": "opportunity-1",
                    "moduleFields": [{"fieldId": "existing-field", "fieldValue": "保留值"}],
                }]},
            })
        if path == "/opportunity/module/form":
            return _Response({
                "code": 100200,
                "data": {"fields": [
                    {
                        "id": "effective-amount",
                        "name": "有效合同额",
                        "internalKey": "",
                        "businessKey": "",
                        "type": "INPUT_NUMBER",
                        "options": [],
                    },
                    {
                        "id": "signing-type",
                        "name": "签约类型",
                        "internalKey": "",
                        "businessKey": "",
                        "type": "SELECT",
                        "options": [{"label": "飞致云直签", "value": "direct-sign"}],
                    },
                    {
                        "id": "final-customer",
                        "name": "最终用户全称（工商可查）",
                        "internalKey": "",
                        "businessKey": "",
                        "type": "INPUT",
                        "options": [],
                    },
                ]},
            })
        if path == "/opportunity/update":
            return _Response({"code": 100200, "data": {"id": "opportunity-1"}})
        raise AssertionError(f"未预期的 API 调用: {req.method} {path} {body}")

    params = {
        "clueId": "lead-1",
        "oppName": "华星-MK-2026-订阅新购",
        "金额": 500000,
        "有效合同额": 480000,
        "结束日期": "2026-09-30",
        "签约类型": "飞致云直签",
        "最终用户全称（工商可查）": "杭州华星科技有限公司",
    }

    with patch.object(module.request, "urlopen", side_effect=fake_urlopen), patch.object(
        module.time, "sleep", return_value=None
    ):
        result = json.loads(module.transform_lead(
            "https://crm.example.test", "access", "secret", json.dumps(params, ensure_ascii=False)
        ))

    assert result["code"] == 100200
    transform_call = next(call for call in calls if call[1] == "/lead/transform")
    assert transform_call[2] == {
        "clueId": "lead-1",
        "oppName": "华星-MK-2026-订阅新购",
        "oppCreated": True,
    }

    update_call = next(call for call in calls if call[1] == "/opportunity/update")
    update_body = update_call[2]
    fields = {item["fieldId"]: item["fieldValue"] for item in update_body["moduleFields"]}

    assert update_body["id"] == "opportunity-1"
    assert update_body["amount"] == 500000
    assert isinstance(update_body["expectedEndTime"], int)
    assert fields == {
        "existing-field": "保留值",
        "effective-amount": 480000.0,
        "signing-type": "direct-sign",
        "final-customer": "杭州华星科技有限公司",
    }


def test_transform_reports_partial_success_when_opportunity_cannot_be_completed():
    module = _load_transform_module()

    def fake_urlopen(req, timeout=15):
        path = urlparse(req.full_url).path
        if path == "/lead/transform":
            return _Response({"code": 100200, "data": {"customerId": "customer-1"}})
        if path == "/global/search/opportunity":
            return _Response({"code": 100200, "data": {"list": []}})
        raise AssertionError(f"未预期的 API 调用: {req.method} {path}")

    params = {
        "clueId": "lead-1",
        "oppName": "华星-MK-2026-订阅新购",
        "金额": 500000,
    }
    with patch.object(module.request, "urlopen", side_effect=fake_urlopen), patch.object(
        module.time, "sleep", return_value=None
    ):
        result = json.loads(module.transform_lead(
            "https://crm.example.test", "access", "secret", json.dumps(params, ensure_ascii=False)
        ))

    assert result["code"] == 0
    assert result["partialSuccess"] is True
    assert result["transformCompleted"] is True
    assert result["retryTransform"] is False
    assert "禁止重复转化" in result["error"]
