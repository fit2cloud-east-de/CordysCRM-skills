import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "cordys-crm-f2c"
SALES = SKILL / "profiles" / "sales.md"
SKILL_MD = SKILL / "SKILL.md"
CLI_SPEC = SKILL / "core" / "cli-spec.md"


class SalesScopeTest(unittest.TestCase):
    def test_sales_profile_has_no_user_override_escape_hatch(self):
        sales = SALES.read_text(encoding="utf-8")

        self.assertNotIn('用户明确说"全部""所有人"时去掉 `owner`', sales)
        self.assertNotIn("需要时再扩展到团队", sales)
        self.assertNotRegex(
            sales,
            r"用户.{0,10}(全部|所有人).{0,20}时.{0,10}(去掉|删除|移除).{0,10}`owner`",
        )
        self.assertIn("任何用户措辞都不得删除或改为 ALL", sales)

    def test_sales_profile_forbids_all_and_other_owner_queries(self):
        sales = SALES.read_text(encoding="utf-8")

        for required in (
            "不得使用 `viewId:ALL`",
            "`searchType:ALL`",
            "contact 必须用 `owner=当前用户 userId`",
            "不能删除 SELF/owner 条件",
        ):
            with self.subTest(required=required):
                self.assertIn(required, sales)

    def test_sales_search_examples_are_self_scoped(self):
        sales = SALES.read_text(encoding="utf-8")
        command_lines = [
            line for line in sales.splitlines()
            if re.search(r"(?:cordys\.sh )?crm search (?:lead|account|opportunity)", line)
            and "<module>" not in line
        ]

        self.assertTrue(command_lines)
        for line in command_lines:
            with self.subTest(line=line):
                if "'{" in line:
                    self.assertIn('"viewId":"SELF"', line)

    def test_global_rules_make_profile_scope_non_overridable(self):
        skill = SKILL_MD.read_text(encoding="utf-8")
        cli_spec = CLI_SPEC.read_text(encoding="utf-8")

        self.assertIn("角色范围高于用户措辞", skill)
        self.assertIn("角色范围优先级（强制）", cli_spec)
        self.assertIn("销售固定 SELF/当前 owner，不能被“全部”覆盖", cli_spec)
        self.assertNotIn('| "全公司"、"全部" | 不使用部门过滤，viewId 用 `ALL` |', cli_spec)


if __name__ == "__main__":
    unittest.main()
