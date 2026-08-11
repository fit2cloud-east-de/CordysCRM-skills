import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "cordys-crm-f2c"
ORG_TREE = SKILL / "scripts" / "sop" / "org_tree.py"
SHELL_CLI = SKILL / "scripts" / "cordys.sh"
EXT_CLI = SKILL / "scripts" / "cordys_ext.sh"
PYTHON_CLI = SKILL / "scripts" / "cordys.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def org_tree():
    return _load(ORG_TREE, "org_tree_under_test")


@pytest.fixture()
def tree_document():
    return {
        "code": 100200,
        "data": [
            {
                "id": "root",
                "name": "总部",
                "children": [
                    {
                        "id": "east",
                        "name": "东区",
                        "children": [
                            {
                                "id": "sales-3",
                                "name": "销售 三部",
                                "children": [
                                    {
                                        "id": "sales-3-a",
                                        "name": "销售三部 A 组",
                                        "children": [],
                                    }
                                ],
                            }
                        ],
                    },
                    {"id": "north", "name": "北区", "children": []},
                ],
            }
        ],
    }


def test_collects_all_ids_in_tree_order(org_tree, tree_document):
    assert org_tree.collect_descendant_ids(tree_document) == [
        "root",
        "east",
        "sales-3",
        "sales-3-a",
        "north",
    ]


def test_resolves_id_exact_name_and_unique_partial(org_tree, tree_document):
    expected = ["sales-3", "sales-3-a"]
    assert org_tree.collect_descendant_ids(tree_document, "sales-3") == expected
    assert org_tree.collect_descendant_ids(tree_document, "销售三部") == expected
    assert org_tree.collect_descendant_ids(tree_document, "北") == ["north"]


def test_outline_preserves_joinable_hierarchy_and_uses_relative_depth(
    org_tree, tree_document
):
    assert org_tree.collect_department_outline(tree_document, "销售三部") == [
        {
            "id": "sales-3",
            "name": "销售 三部",
            "parentId": None,
            "path": "总部 / 东区 / 销售 三部",
            "depth": 0,
        },
        {
            "id": "sales-3-a",
            "name": "销售三部 A 组",
            "parentId": "sales-3",
            "path": "总部 / 东区 / 销售 三部 / 销售三部 A 组",
            "depth": 1,
        },
    ]


def test_full_outline_keeps_absolute_depth_and_parent_ids(org_tree, tree_document):
    outline = org_tree.collect_department_outline(tree_document)
    by_id = {item["id"]: item for item in outline}
    assert by_id["root"]["parentId"] is None
    assert by_id["root"]["depth"] == 0
    assert by_id["sales-3"]["parentId"] == "east"
    assert by_id["sales-3"]["depth"] == 2


def test_ambiguous_name_fails_instead_of_selecting_first(org_tree):
    document = {
        "code": 100200,
        "data": [
            {
                "id": "root",
                "name": "总部",
                "children": [
                    {"id": "east-sales", "name": "销售部", "children": []},
                    {"id": "north-sales", "name": "销售 部", "children": []},
                ],
            }
        ],
    }
    with pytest.raises(org_tree.OrgTreeError, match="匹配到多个部门") as raised:
        org_tree.collect_descendant_ids(document, "销售部")
    assert "east-sales" in str(raised.value)
    assert "north-sales" in str(raised.value)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ('{"code":500001,"message":"forbidden"}', "code=500001"),
        ('{"code":100200,"data":[]}', "部门树为空"),
        ("not-json", "返回非 JSON"),
    ],
)
def test_invalid_or_failed_responses_fail_closed(org_tree, raw, message):
    with pytest.raises(org_tree.OrgTreeError, match=message):
        org_tree.render_descendant_ids(raw)


def test_python_cli_uses_same_org_tree_resolver(monkeypatch, tree_document):
    cordys = _load(PYTHON_CLI, "cordys_org_under_test")
    raw = json.dumps(tree_document, ensure_ascii=False)
    monkeypatch.setattr(cordys, "api", lambda *_args, **_kwargs: raw)
    assert json.loads(cordys.crm_org("ids", "销售三部")) == [
        "sales-3",
        "sales-3-a",
    ]
    outline = json.loads(cordys.crm_org("outline", "销售三部"))
    assert [item["id"] for item in outline] == ["sales-3", "sales-3-a"]
    assert outline[1]["parentId"] == "sales-3"
    assert cordys.crm_org() == raw


def test_shell_org_views_share_one_validated_tree_endpoint(tmp_path, tree_document):
    bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    bash_cmd = str(bash) if bash.exists() else shutil.which("bash")
    if not bash_cmd:
        pytest.skip("bash unavailable")

    skill = tmp_path / "skill"
    scripts = skill / "scripts"
    sop = scripts / "sop"
    sop.mkdir(parents=True)
    shell_copy = scripts / "cordys.sh"
    shutil.copy2(SHELL_CLI, shell_copy)
    shutil.copy2(ORG_TREE, sop / "org_tree.py")
    shell_text = shell_copy.read_text(encoding="utf-8")
    api_start = shell_text.index("api_request() {")
    api_end = shell_text.index("\n}\n", api_start) + 3
    shell_copy.write_text(
        shell_text[:api_start]
        + "api_request() { check_keys; printf '%s' \"$ORG_TREE_RESPONSE\"; }\n"
        + shell_text[api_end:],
        encoding="utf-8",
        newline="\n",
    )

    env = os.environ.copy()
    env.update(
        {
            "CORDYS_PYTHON": Path(sys.executable).as_posix(),
            "CORDYS_CRM_DOMAIN": "https://crm.example.test",
            "CORDYS_ACCESS_KEY": "access",
            "CORDYS_SECRET_KEY": "secret",
            "ORG_TREE_RESPONSE": json.dumps(tree_document, ensure_ascii=False),
            "MSYS_NO_PATHCONV": "1",
            "MSYS2_ARG_CONV_EXCL": "*",
        }
    )
    command = [bash_cmd, (scripts / "cordys.sh").as_posix(), "crm", "org"]

    raw = subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    ids = subprocess.run(
        [*command, "ids", "销售三部"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    outline = subprocess.run(
        [*command, "outline", "销售三部"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )

    assert raw.returncode == 0, raw.stderr
    assert json.loads(raw.stdout) == tree_document
    assert ids.returncode == 0, ids.stderr
    assert json.loads(ids.stdout) == ["sales-3", "sales-3-a"]
    assert outline.returncode == 0, outline.stderr
    outline_data = json.loads(outline.stdout)
    assert [item["depth"] for item in outline_data] == [0, 1]
    assert outline_data[1]["parentId"] == "sales-3"


def test_old_dept_children_command_is_removed():
    ext_text = EXT_CLI.read_text(encoding="utf-8")
    assert "dept-children" not in ext_text
    assert "/department/tree" not in ext_text
    shell_text = SHELL_CLI.read_text(encoding="utf-8")
    assert 'org)     crm_org "$@"' in shell_text
    assert "crm org ids" in shell_text
    assert "crm org outline" in shell_text
