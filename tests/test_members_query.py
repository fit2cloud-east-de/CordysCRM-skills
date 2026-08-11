import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "cordys-crm-f2c"
SCRIPT = SKILL / "scripts" / "sop" / "members_query.py"
SHELL_CLI = SKILL / "scripts" / "cordys.sh"
PYTHON_CLI = SKILL / "scripts" / "cordys.py"


def _load_members_module():
    spec = importlib.util.spec_from_file_location("members_query_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def success_response(members=None):
    members = members or []
    return json.dumps(
        {"code": 100200, "data": {"list": members, "total": len(members)}},
        ensure_ascii=False,
    )


class MembersQueryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.members = _load_members_module()

    def test_exact_department_flag_keeps_one_post_and_no_tree_read(self):
        transport = FakeTransport([success_response()])
        raw = self.members.query_members(
            '{"departmentIds":["d1"],"viewId":"ALL"}',
            "张三",
            exact_departments=True,
            transport=transport,
        )
        self.assertEqual(json.loads(raw)["code"], 100200)
        self.assertEqual(len(transport.calls), 1)
        method, path, body = transport.calls[0]
        self.assertEqual((method, path), ("POST", "/user/list"))
        self.assertEqual(body["departmentIds"], ["d1"])
        self.assertNotIn("viewId", body)
        name_conditions = [
            condition
            for condition in body["combineSearch"]["conditions"]
            if condition.get("name") == "userName"
        ]
        self.assertEqual(len(name_conditions), 1)
        self.assertEqual(name_conditions[0]["value"], "张三")
        self.assertEqual(body["pageSize"], 500)

    def test_explicit_parent_departments_expand_to_all_descendants_by_default(self):
        tree = json.dumps(
            {
                "code": 100200,
                "data": [
                    {
                        "id": "sales-1",
                        "children": [
                            {
                                "id": "group-1",
                                "children": [{"id": "team-1", "children": []}],
                            }
                        ],
                    },
                    {
                        "id": "sales-2",
                        "children": [{"id": "group-2", "children": []}],
                    },
                    {"id": "sales-3", "children": []},
                ],
            }
        )
        transport = FakeTransport([tree, success_response()])
        self.members.query_members(
            '{"departmentIds":["sales-1","sales-2","sales-3"]}',
            active=False,
            transport=transport,
        )
        self.assertEqual(
            [(method, path) for method, path, _ in transport.calls],
            [("GET", "/department/tree"), ("POST", "/user/list")],
        )
        self.assertEqual(
            transport.calls[1][2]["departmentIds"],
            ["sales-1", "group-1", "team-1", "sales-2", "group-2", "sales-3"],
        )

    def test_unknown_explicit_department_stops_before_member_post(self):
        tree = json.dumps(
            {"code": 100200, "data": [{"id": "visible", "children": []}]}
        )
        transport = FakeTransport([tree])
        with self.assertRaisesRegex(
            self.members.MembersQueryError, "不在当前可见组织树"
        ):
            self.members.query_members(
                '{"departmentIds":["missing"]}', transport=transport
            )
        self.assertEqual(
            [(method, path) for method, path, _ in transport.calls],
            [("GET", "/department/tree")],
        )

    def test_explicit_empty_department_ids_fail_closed(self):
        transport = FakeTransport([success_response()])
        with self.assertRaises(self.members.MembersQueryError):
            self.members.query_members('{"departmentIds":[]}', transport=transport)
        self.assertEqual(transport.calls, [])

    def test_mistyped_scope_and_top_level_status_fields_fail_before_transport(self):
        cases = (
            ('{"departmentId":"d1"}', "departmentIds"),
            ('{"enable":true}', "--active"),
            ('{"status":true}', "combineSearch.conditions"),
        )
        for payload, message in cases:
            with self.subTest(payload=payload):
                transport = FakeTransport([success_response()])
                with self.assertRaisesRegex(self.members.MembersQueryError, message):
                    self.members.query_members(payload, transport=transport)
                self.assertEqual(transport.calls, [])

    def test_missing_department_ids_fetches_tree_then_members(self):
        tree = json.dumps(
            {
                "code": 100200,
                "data": [{"id": "d1", "children": [{"id": "d2", "children": []}]}],
            }
        )
        transport = FakeTransport([tree, success_response()])
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "dept.json"
            self.members.query_members(
                name="张三", transport=transport, cache_file=cache, now=1000
            )
            self.assertEqual(
                [(call[0], call[1]) for call in transport.calls],
                [("GET", "/department/tree"), ("POST", "/user/list")],
            )
            self.assertEqual(transport.calls[1][2]["departmentIds"], ["d1", "d2"])
            self.assertEqual(
                json.loads(cache.read_text(encoding="utf-8")), ["d1", "d2"]
            )

    def test_fresh_cache_skips_department_tree(self):
        transport = FakeTransport([success_response()])
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "dept.json"
            cache.write_text('["cached-1","cached-2"]', encoding="utf-8")
            now = cache.stat().st_mtime + 60
            self.members.query_members(transport=transport, cache_file=cache, now=now)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0][1], "/user/list")
        self.assertEqual(
            transport.calls[0][2]["departmentIds"], ["cached-1", "cached-2"]
        )

    def test_stale_or_broken_cache_fetches_tree_and_refreshes(self):
        tree = json.dumps({"code": 100200, "data": [{"id": "new-id"}]})
        for stale_content in ('["old-id"]', "not-json"):
            with (
                self.subTest(stale_content=stale_content),
                tempfile.TemporaryDirectory() as tmp,
            ):
                cache = Path(tmp) / "dept.json"
                cache.write_text(stale_content, encoding="utf-8")
                if stale_content.startswith("["):
                    old = time.time() - self.members.CACHE_TTL_SECONDS - 60
                    os.utime(cache, (old, old))
                transport = FakeTransport([tree, success_response()])
                self.members.query_members(
                    transport=transport, cache_file=cache, now=time.time()
                )
                self.assertEqual(transport.calls[0][1], "/department/tree")
                self.assertEqual(
                    json.loads(cache.read_text(encoding="utf-8")), ["new-id"]
                )

    def test_default_cache_isolated_by_domain_and_account(self):
        first = self.members._default_cache_file("https://crm-a.example.com", "ak-1")
        same = self.members._default_cache_file("https://crm-a.example.com/", "ak-1")
        other_domain = self.members._default_cache_file(
            "https://crm-b.example.com", "ak-1"
        )
        other_account = self.members._default_cache_file(
            "https://crm-a.example.com", "ak-2"
        )
        self.assertEqual(first, same)
        self.assertNotEqual(first, other_domain)
        self.assertNotEqual(first, other_account)

    def test_existing_name_condition_is_not_duplicated_or_overwritten(self):
        payload = json.dumps(
            {
                "departmentIds": ["d1"],
                "combineSearch": {
                    "searchMode": "AND",
                    "conditions": [
                        {
                            "operator": "EQUALS",
                            "name": "userName",
                            "value": "原条件",
                            "type": "INPUT",
                        }
                    ],
                },
            },
            ensure_ascii=False,
        )
        body = self.members.build_members_payload(payload, "新参数")
        conditions = body["combineSearch"]["conditions"]
        self.assertEqual(len(conditions), 1)
        self.assertEqual(conditions[0]["value"], "原条件")

    def test_active_flag_injects_one_status_condition_and_one_post(self):
        member = {
            "userName": "张三",
            "userId": "u1",
            "departmentId": "d1",
            "departmentName": "销售一部",
            "enable": True,
        }
        transport = FakeTransport([success_response([member])])

        self.members.query_members(
            '{"departmentIds":["d1"]}',
            active=True,
            exact_departments=True,
            transport=transport,
        )

        self.assertEqual(len(transport.calls), 1)
        conditions = transport.calls[0][2]["combineSearch"]["conditions"]
        status_conditions = [
            condition for condition in conditions if condition.get("name") == "status"
        ]
        self.assertEqual(status_conditions, [self.members.ACTIVE_STATUS_CONDITION])

    def test_active_flag_accepts_identical_status_and_rejects_conflicts(self):
        active_payload = json.dumps(
            {
                "departmentIds": ["d1"],
                "combineSearch": {
                    "searchMode": "AND",
                    "conditions": [self.members.ACTIVE_STATUS_CONDITION],
                },
            }
        )
        active_member = {
            "userName": "张三",
            "userId": "u1",
            "departmentId": "d1",
            "departmentName": "销售一部",
            "enable": True,
        }
        transport = FakeTransport([success_response([active_member])])
        self.members.query_members(
            active_payload,
            active=True,
            exact_departments=True,
            transport=transport,
        )
        conditions = transport.calls[0][2]["combineSearch"]["conditions"]
        self.assertEqual(conditions, [self.members.ACTIVE_STATUS_CONDITION])

        conflict_payload = json.dumps(
            {
                "departmentIds": ["d1"],
                "combineSearch": {
                    "conditions": [
                        {
                            "value": False,
                            "operator": "IN",
                            "name": "status",
                            "multipleValue": False,
                            "type": "SELECT",
                        }
                    ]
                },
            }
        )
        conflict_transport = FakeTransport([success_response()])
        with self.assertRaisesRegex(self.members.MembersQueryError, "冲突"):
            self.members.query_members(
                conflict_payload,
                active=True,
                exact_departments=True,
                transport=conflict_transport,
            )
        self.assertEqual(conflict_transport.calls, [])

    def test_active_flag_fails_if_backend_still_returns_disabled_member(self):
        disabled = {
            "userName": "离职成员",
            "userId": "u2",
            "departmentId": "d1",
            "departmentName": "销售一部",
            "enable": False,
        }
        transport = FakeTransport([success_response([disabled])])
        with self.assertRaisesRegex(self.members.MembersQueryError, "未落实 --active"):
            self.members.query_members(
                '{"departmentIds":["d1"]}',
                active=True,
                exact_departments=True,
                transport=transport,
            )
        self.assertEqual(len(transport.calls), 1)

    def test_compact_outputs_only_consumable_member_fields_and_total(self):
        raw_member = {
            "id": "internal",
            "userName": "张三",
            "userId": "u1",
            "departmentId": "d1",
            "departmentName": "销售三部",
            "enable": True,
            "phone": "secret",
        }
        transport = FakeTransport([success_response([raw_member])])
        result = json.loads(
            self.members.query_members(
                '{"departmentIds":["d1"]}',
                compact=True,
                exact_departments=True,
                transport=transport,
            )
        )
        self.assertEqual(result["data"]["total"], 1)
        self.assertEqual(
            result["data"]["list"],
            [
                {
                    "userName": "张三",
                    "userId": "u1",
                    "departmentId": "d1",
                    "departmentName": "销售三部",
                    "enable": True,
                }
            ],
        )

    def test_business_failure_is_not_treated_as_empty_list(self):
        response = '{"code":500001,"message":"boom"}'
        transport = FakeTransport([response])
        with self.assertRaises(self.members.MembersResponseError) as raised:
            self.members.query_members(
                '{"departmentIds":["d1"]}',
                exact_departments=True,
                transport=transport,
            )
        self.assertEqual(raised.exception.response, response)

    def test_malformed_success_is_not_treated_as_empty_list(self):
        transport = FakeTransport(['{"code":100200,"data":{}}'])
        with self.assertRaises(self.members.MembersQueryError):
            self.members.query_members(
                '{"departmentIds":["d1"]}',
                exact_departments=True,
                transport=transport,
            )

    def test_department_tree_failure_stops_before_member_post(self):
        response = '{"code":500001,"message":"tree failed"}'
        transport = FakeTransport([response])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(self.members.MembersResponseError):
                self.members.query_members(
                    transport=transport,
                    cache_file=Path(tmp) / "missing.json",
                    now=1000,
                )
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0][1], "/department/tree")

    def test_numeric_keyword_remains_a_string(self):
        body = self.members.build_members_payload("13800138000")
        self.assertEqual(body["keyword"], "13800138000")

    def test_cli_parser_supports_flags_on_either_side(self):
        first = self.members.parse_members_cli_args(
            [
                '{"departmentIds":["d1"]}',
                "--name",
                "张三",
                "--compact",
                "--active",
                "--exact-departments",
            ]
        )
        second = self.members.parse_members_cli_args(
            [
                "--active",
                "--exact-departments",
                "--compact",
                "--name",
                "张三",
                '{"departmentIds":["d1"]}',
            ]
        )
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            ('{"departmentIds":["d1"]}', "张三", True, True, True),
        )

    def test_exact_departments_requires_explicit_scope_before_credentials(self):
        with self.assertRaisesRegex(
            self.members.MembersQueryError,
            "只能与显式 departmentIds 数组一起使用",
        ):
            self.members.query_members(exact_departments=True)

    def test_transport_maps_http_and_network_errors_without_retry(self):
        class FakeOpener:
            def __init__(self, error):
                self.error = error
                self.calls = 0

            def open(self, request, timeout):
                self.calls += 1
                raise self.error

        errors = (
            HTTPError("https://crm.example.com/user/list", 500, "boom", {}, None),
            URLError("offline"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                opener = FakeOpener(error)
                with patch.object(
                    self.members.request, "build_opener", return_value=opener
                ):
                    transport = self.members.make_http_transport(
                        "https://crm.example.com", "ak", "sk"
                    )
                    with self.assertRaises(self.members.MembersQueryError):
                        transport("POST", "/user/list", {"departmentIds": ["d1"]})
                self.assertEqual(opener.calls, 1)

    def test_helper_main_failure_exits_nonzero_and_preserves_error_body(self):
        response = '{"code":500001,"message":"secret-key leaked"}'
        error = self.members.MembersResponseError("成员查询失败", response)
        with (
            patch.dict(os.environ, {"CORDYS_SECRET_KEY": "secret-key"}),
            patch.object(self.members, "query_members", side_effect=error),
            patch("sys.stdout") as stdout,
            patch("sys.stderr") as stderr,
        ):
            exit_code = self.members.main(['{"departmentIds":["d1"]}'])
        self.assertEqual(exit_code, 1)
        stdout.write.assert_any_call(
            '{"code":500001,"message":"***REDACTED*** leaked"}'
        )
        self.assertTrue(stderr.write.called)

    def test_helper_main_reads_shell_environment_explicitly(self):
        compact_response = success_response()
        with (
            patch.dict(
                os.environ,
                {
                    "CORDYS_MEMBERS_FROM_ENV": "1",
                    "CORDYS_MEMBERS_PAYLOAD": '{"departmentIds":["d1"]}',
                    "CORDYS_FILTER_NAME": "张三",
                    "CORDYS_MEMBERS_COMPACT": "1",
                    "CORDYS_MEMBERS_ACTIVE": "1",
                    "CORDYS_MEMBERS_EXACT_DEPARTMENTS": "1",
                },
            ),
            patch.object(
                self.members, "query_members", return_value=compact_response
            ) as query,
            patch("sys.stdout"),
            patch("sys.stderr"),
        ):
            exit_code = self.members.main([])
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            query.call_args.args[:5],
            ('{"departmentIds":["d1"]}', "张三", True, True, True),
        )

    def test_shell_has_no_members_tempfile_or_legacy_curl_branch(self):
        text = SHELL_CLI.read_text(encoding="utf-8")
        start = text.index("crm_members() {")
        end = text.index("\n}\n", start) + 3
        function = text[start:end]
        self.assertNotIn("members_payload", text)
        self.assertNotIn("rm -f", function)
        self.assertNotIn("api POST", function)
        self.assertIn("members_query.py", function)

    def test_both_cli_help_surfaces_document_compact_and_active(self):
        for path in (SHELL_CLI, PYTHON_CLI):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("--compact", text)
                self.assertIn("--active", text)
                self.assertIn("--exact-departments", text)

    def test_shell_cli_validates_args_before_credentials_or_network(self):
        bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        bash_cmd = str(bash) if bash.exists() else shutil.which("bash")
        if not bash_cmd:
            self.skipTest("bash unavailable")
        env = os.environ.copy()
        env.update(
            {
                "CORDYS_CRM_DOMAIN": "",
                "CORDYS_ACCESS_KEY": "",
                "CORDYS_SECRET_KEY": "",
            }
        )
        result = subprocess.run(
            [bash_cmd, str(SHELL_CLI), "crm", "members", "--name"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("--name 需要非空姓名", result.stderr)


if __name__ == "__main__":
    unittest.main()
