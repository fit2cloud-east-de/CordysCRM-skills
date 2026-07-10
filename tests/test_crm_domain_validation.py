import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "cordys-crm-f2c"
SHELL_CLI = SKILL / "scripts" / "cordys.sh"
EXT_SHELL_CLI = SKILL / "scripts" / "cordys_ext.sh"
PYTHON_CLI = SKILL / "scripts" / "cordys.py"


def _load_cordys_module():
    spec = importlib.util.spec_from_file_location("cordys_domain_under_test", PYTHON_CLI)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CrmDomainValidationTest(unittest.TestCase):
    def test_no_cli_contains_public_domain_fallback(self):
        for path in (SHELL_CLI, EXT_SHELL_CLI, PYTHON_CLI):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("https://www.cordys.cn", text)

    def test_python_rejects_missing_or_unsafe_domain_before_request(self):
        cordys = _load_cordys_module()
        unsafe_domains = (
            "",
            "http://crm.example.com",
            "https://crm.example.com/api",
            "https://user:pass@crm.example.com",
            "https://crm.example.com?next=evil",
            "https://crm.example.com:70000",
            "https://crm..example.com",
            "https://crm_example.com",
        )
        for domain in unsafe_domains:
            with self.subTest(domain=domain):
                with patch.object(cordys, "CORDYS_CRM_DOMAIN", domain), patch.object(
                    cordys, "CORDYS_ACCESS_KEY", "access"
                ), patch.object(cordys, "CORDYS_SECRET_KEY", "secret"):
                    with self.assertRaises(SystemExit):
                        cordys.api_request("GET", f"{domain}/personal/center/info", "application/json")

    def test_python_accepts_https_root_and_strips_trailing_slash(self):
        cordys = _load_cordys_module()
        with patch.object(cordys, "CORDYS_CRM_DOMAIN", "https://crm.example.com:8443/"), patch.object(
            cordys, "CORDYS_ACCESS_KEY", "access"
        ), patch.object(cordys, "CORDYS_SECRET_KEY", "secret"):
            cordys.check_keys()
            self.assertEqual(cordys.CORDYS_CRM_DOMAIN, "https://crm.example.com:8443")

    def test_shell_clis_normalize_domain_before_building_urls(self):
        for path in (SHELL_CLI, EXT_SHELL_CLI):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn('CORDYS_CRM_DOMAIN="${CORDYS_CRM_DOMAIN%/}"', text)

    def test_shell_clis_reject_missing_domain_before_network(self):
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        bash = str(git_bash) if git_bash.exists() else shutil.which("bash")
        if not bash:
            self.skipTest("bash unavailable")

        for source, args in (
            (SHELL_CLI, ("crm", "verify")),
            (EXT_SHELL_CLI, ("form", "lead")),
        ):
            with self.subTest(source=source.name), tempfile.TemporaryDirectory() as tmp:
                skill = Path(tmp) / "skill"
                scripts = skill / "scripts"
                scripts.mkdir(parents=True)
                copied = scripts / source.name
                shutil.copy2(source, copied)
                env = os.environ.copy()
                env.update({
                    "CORDYS_CRM_DOMAIN": "",
                    "CORDYS_ACCESS_KEY": "access",
                    "CORDYS_SECRET_KEY": "secret",
                })
                script_path = str(copied)
                if Path(bash).name.lower() == "bash.exe" and "system32" in str(Path(bash).parent).lower():
                    script_path = f"/mnt/{copied.drive[0].lower()}{copied.as_posix()[2:]}"
                result = subprocess.run(
                    [bash, script_path, *args],
                    cwd=skill,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                self.assertEqual(result.returncode, 1)
                output = result.stdout + result.stderr
                self.assertIn("未设置 CORDYS_CRM_DOMAIN", output)


if __name__ == "__main__":
    unittest.main()
