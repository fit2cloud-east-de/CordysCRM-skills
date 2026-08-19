import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "cordys-crm-f2c"
SHELL_CLI = SKILL / "scripts" / "cordys.sh"
RECORD_ID = "record-1"
FIELD_ID = "178601237855700000"
OLD_VALUE = "178601237855700000"
NEW_VALUE = "178601237855700001"


def _git_bash():
    candidate = Path(r"C:\Program Files\Git\bin\bash.exe")
    bash = str(candidate) if candidate.exists() else shutil.which("bash")
    if not bash:
        pytest.skip("bash unavailable")
    return bash


def _make_skill(tmp_path):
    skill = tmp_path / "cordys-crm-f2c"
    scripts = skill / "scripts"
    sop = scripts / "sop"
    forms = skill / "references" / "forms"
    sop.mkdir(parents=True)
    forms.mkdir(parents=True)
    shutil.copy2(SHELL_CLI, scripts / "cordys.sh")
    shutil.copy2(SKILL / "scripts" / "sop" / "payload_io.py", sop / "payload_io.py")
    shutil.copy2(
        SKILL / "references" / "field-schema.json",
        skill / "references" / "field-schema.json",
    )
    (forms / ".last_sync").write_text(str(int(time.time())), encoding="ascii")
    return skill


def _write_fake_curl(tmp_path):
    fake_curl = tmp_path / "fake_curl.py"
    fake_curl.write_text(
        r'''
import json
import os
import sys
from pathlib import Path


args = sys.argv[1:]
method = args[args.index("-X") + 1] if "-X" in args else "GET"
url = next((item for item in args if item.startswith("https://")), "")
mode = os.environ["CORDYS_FAKE_MODE"]
log_path = Path(os.environ["CORDYS_FAKE_LOG"])
state_path = Path(os.environ["CORDYS_FAKE_STATE"])

with log_path.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"method": method, "url": url, "args": args}) + "\n")

if method == "GET" and url.endswith("/pool/lead/options"):
    sys.stdout.write(json.dumps({"code": 100200, "data": []}))
    raise SystemExit(0)

if method == "POST" and url.endswith("/raw-test"):
    sys.stdout.write(json.dumps({"code": 100200, "data": {}}))
    raise SystemExit(0)

if method == "GET" and "/get/" in url:
    record = json.loads(state_path.read_text(encoding="utf-8"))
    sys.stdout.write(json.dumps({"code": 100200, "data": record}))
    raise SystemExit(0)

if method == "POST" and url.endswith("/update") and not url.endswith("/batch/update"):
    marker = args[args.index("--data-binary") + 1]
    body_path = marker[1:] if marker.startswith("@") else marker
    body = json.loads(Path(body_path).read_text(encoding="utf-8"))
    if mode in {"success_body_exit_1", "timeout_after_commit"}:
        state_path.write_text(json.dumps(body), encoding="utf-8")
    if mode == "success_body_exit_1":
        sys.stdout.write(json.dumps({"code": 100200, "data": {"id": body["id"]}}))
        sys.stdout.write("\n200")
        raise SystemExit(1)
    sys.stdout.write("\n000")
    sys.stderr.write("curl: (28) simulated timeout after request submission\n")
    raise SystemExit(28)

if method == "POST" and url.endswith("/batch/update"):
    sys.stdout.write("\n000")
    sys.stderr.write("curl: (28) simulated batch timeout\n")
    raise SystemExit(28)

sys.stderr.write(f"unexpected fake curl call: {method} {url}\n")
raise SystemExit(2)
'''.lstrip(),
        encoding="utf-8",
        newline="\n",
    )
    return fake_curl


def _initial_record():
    return {
        "id": RECORD_ID,
        "name": "测试客户",
        "owner": "user-1",
        "moduleFields": [{"fieldId": FIELD_ID, "fieldValue": OLD_VALUE}],
    }


def _environment(tmp_path, mode):
    state = tmp_path / "state.json"
    state.write_text(json.dumps(_initial_record()), encoding="utf-8")
    log = tmp_path / "curl.log"
    fake_curl = _write_fake_curl(tmp_path)
    bash_env = tmp_path / "bash_env.sh"
    bash_env.write_text(
        'curl() { "$CORDYS_TEST_PYTHON" -S "$CORDYS_FAKE_CURL" "$@"; }\n',
        encoding="utf-8",
        newline="\n",
    )
    native_temp = tmp_path / "native-temp"
    native_temp.mkdir()
    python_path = Path(sys.executable).as_posix()
    env = os.environ.copy()
    env.update(
        {
            "BASH_ENV": bash_env.as_posix(),
            "CORDYS_TEST_PYTHON": python_path,
            "CORDYS_FAKE_CURL": fake_curl.as_posix(),
            "CORDYS_FAKE_MODE": mode,
            "CORDYS_FAKE_LOG": str(log),
            "CORDYS_FAKE_STATE": str(state),
            "CORDYS_CRM_DOMAIN": "https://crm.example.test",
            "CORDYS_ACCESS_KEY": "access",
            "CORDYS_SECRET_KEY": "secret",
            "CORDYS_PYTHON": python_path,
            "MSYS_NO_PATHCONV": "1",
            "MSYS2_ARG_CONV_EXCL": "*",
            "TEMP": str(native_temp),
            "TMP": str(native_temp),
        }
    )
    return env, log, native_temp


def _run_update(skill, env):
    payload = {
        "id": RECORD_ID,
        "moduleFields": [{"fieldId": FIELD_ID, "fieldValue": NEW_VALUE}],
    }
    return subprocess.run(
        [_git_bash(), "scripts/cordys.sh", "crm", "update", "account", "@-"],
        cwd=skill,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=env,
        check=False,
        timeout=30,
    )


def _run_raw(skill, env, *args):
    return subprocess.run(
        [_git_bash(), "scripts/cordys.sh", *args],
        cwd=skill,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=env,
        check=False,
        timeout=30,
    )


def _calls(log):
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _assert_one_update_post(calls):
    posts = [call for call in calls if call["method"] == "POST"]
    assert len(posts) == 1
    assert posts[0]["url"].endswith("/account/update")


@pytest.mark.parametrize("prefix", [("raw",), ("crm", "raw")])
def test_raw_get_without_body_avoids_empty_array_expansion(tmp_path, prefix):
    skill = _make_skill(tmp_path)
    env, log, _ = _environment(tmp_path, "raw_get")

    result = _run_raw(skill, env, *prefix, "GET", "/pool/lead/options")

    assert result.returncode == 0, result.stderr
    calls = _calls(log)
    assert len(calls) == 1
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/pool/lead/options")
    assert "--data-binary" not in calls[0]["args"]


def test_raw_with_body_preserves_data_argument(tmp_path):
    skill = _make_skill(tmp_path)
    env, log, _ = _environment(tmp_path, "raw_body")

    result = _run_raw(skill, env, "raw", "POST", "/raw-test", "{}")

    assert result.returncode == 0, result.stderr
    call = _calls(log)[0]
    marker = call["args"].index("--data-binary")
    assert call["args"][marker + 1] == "{}"


def test_raw_implementation_has_no_optional_empty_argument_array():
    text = SHELL_CLI.read_text(encoding="utf-8")
    start = text.index("raw_api() {")
    end = text.index("\n}\n", start) + 3
    function = text[start:end]

    assert "raw_args" not in function
    assert 'api "$method" "$request_url"' in function


def test_update_accepts_success_body_even_when_curl_exits_nonzero(tmp_path):
    skill = _make_skill(tmp_path)
    env, log, native_temp = _environment(tmp_path, "success_body_exit_1")

    result = _run_update(skill, env)

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["code"] == 100200
    assert "verifiedAfterTransportError" not in response
    calls = _calls(log)
    _assert_one_update_post(calls)
    assert sum(call["method"] == "GET" for call in calls) == 1
    assert not list(native_temp.glob("cordys_*.json"))


def test_update_timeout_after_commit_is_verified_by_one_readback(tmp_path):
    skill = _make_skill(tmp_path)
    env, log, native_temp = _environment(tmp_path, "timeout_after_commit")

    result = _run_update(skill, env)

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["code"] == 100200
    assert response["verifiedAfterTransportError"] is True
    assert response["retryAllowed"] is False
    assert response["verification"]["moduleFieldIds"] == [FIELD_ID]
    calls = _calls(log)
    _assert_one_update_post(calls)
    assert sum(call["method"] == "GET" for call in calls) == 2
    assert not list(native_temp.glob("cordys_*.json"))


def test_update_timeout_without_matching_readback_stays_unknown(tmp_path):
    skill = _make_skill(tmp_path)
    env, log, native_temp = _environment(tmp_path, "timeout_without_commit")

    result = _run_update(skill, env)

    assert result.returncode != 0
    response = json.loads(result.stdout)
    assert response["code"] == 0
    assert response["writeState"] == "unknown"
    assert response["retryAllowed"] is False
    assert response["verification"]["mismatchedModuleFieldIds"] == [FIELD_ID]
    calls = _calls(log)
    _assert_one_update_post(calls)
    assert sum(call["method"] == "GET" for call in calls) == 2
    assert not list(native_temp.glob("cordys_*.json"))


def test_batch_update_timeout_is_structured_and_cleans_payload(tmp_path):
    skill = _make_skill(tmp_path)
    env, log, native_temp = _environment(tmp_path, "batch_timeout")
    payload = json.dumps(
        {"ids": [RECORD_ID], "fieldId": FIELD_ID, "fieldValue": NEW_VALUE}
    )

    result = subprocess.run(
        [
            _git_bash(),
            "scripts/cordys.sh",
            "crm",
            "batch-update",
            "account",
            payload,
        ],
        cwd=skill,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=env,
        check=False,
        timeout=30,
    )

    assert result.returncode != 0
    assert result.stdout.strip(), result.stderr
    response = json.loads(result.stdout)
    assert response["code"] == 0
    assert response["writeState"] == "unknown"
    assert response["retryAllowed"] is False
    calls = _calls(log)
    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/account/batch/update")
    assert not list(native_temp.glob("cordys_*.json"))
