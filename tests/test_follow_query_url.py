import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "cordys-crm-f2c"
SHELL_CLI = SKILL / "scripts" / "cordys.sh"
PYTHON_CLI = SKILL / "scripts" / "cordys.py"


def _load_cordys_module():
    spec = importlib.util.spec_from_file_location("cordys_under_test", PYTHON_CLI)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FollowQueryUrlTest(unittest.TestCase):
    def test_python_follow_query_uses_module_in_url(self):
        cases = [
            ("record", "lead", "/lead/follow/record/page"),
            ("plan", "account", "/account/follow/plan/page"),
            ("record", "opportunity", "/opportunity/follow/record/page"),
        ]
        for kind, module, expected_path in cases:
            with self.subTest(kind=kind, module=module):
                cordys = _load_cordys_module()
                calls = []

                def fake_api(method, url, data=None):
                    calls.append((method, url, json.loads(data)))
                    return '{"code":100200}'

                with patch.object(cordys, "api", side_effect=fake_api):
                    result = cordys.crm_follow_page(kind, module, '{"sourceId":"source-1"}')

                self.assertEqual(result, '{"code":100200}')
                self.assertEqual(calls[0][0], "POST")
                self.assertTrue(calls[0][1].endswith(expected_path))
                self.assertEqual(calls[0][2]["sourceId"], "source-1")

    def test_shell_follow_query_uses_module_in_url(self):
        shell = SHELL_CLI.read_text(encoding="utf-8")

        self.assertIn('api POST "${crm_base}/${module}/follow/${kind}/page"', shell)
        self.assertNotIn('api POST "${crm_base}/follow/${kind}/page"', shell)

    def test_follow_query_docs_do_not_expose_unprefixed_page_endpoint(self):
        api_doc = (SKILL / "references" / "crm-api.md").read_text(encoding="utf-8")
        sync_script = (SKILL / "scripts" / "sop" / "sync_forms.py").read_text(encoding="utf-8")

        self.assertIn("`/{module}/follow/plan/page`", api_doc)
        self.assertIn("`/{module}/follow/record/page`", api_doc)
        self.assertNotIn("crm raw POST /follow/", api_doc)
        self.assertNotIn("全局端点 /follow/record/page", sync_script)


if __name__ == "__main__":
    unittest.main()
