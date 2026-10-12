"""Attachment upload and ATTACHMENT-field write helpers.

Cordys stores record attachments in two steps:

1. ``POST /attachment/upload/temp`` (multipart field ``files``) returns temp IDs.
2. Saving a record whose ATTACHMENT ``fieldValue`` lists those IDs makes the
   backend's ``processTemp`` turn them into formal attachments with the same ID.

``processTemp`` deletes every attachment of the record that is missing from
the submitted list, so updates must resend the existing IDs (append mode).
The backend swallows disk/transfer errors and still returns IDs, so only the
readback ``attachmentMap[fieldId]`` proves that a file is attached.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

from payload_io import PayloadTransportError, _load_schema_modules, read_utf8, write_temp_json


ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
DEFAULT_MAX_MB = 50
UPLOAD_PATH = "/attachment/upload/temp"
UPLOAD_TIMEOUT = 120
ATTACHMENT_MODES = ("append", "replace")
SUCCESS_CODE = "100200"


class AttachmentError(RuntimeError):
    """A classified attachment failure; ``to_result`` is safe to print."""

    def __init__(self, category: str, message: str, **details) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.details = details

    def to_result(self) -> dict:
        return {
            "code": 0,
            "errorCategory": self.category,
            "message": self.message,
            "retryAllowed": False,
            **self.details,
        }


# ── 本地文件校验 ──────────────────────────────────────────────────────
def max_size_bytes() -> int:
    raw = str(os.environ.get("CORDYS_ATTACHMENT_MAX_MB") or DEFAULT_MAX_MB).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise AttachmentError("invalid_request", "CORDYS_ATTACHMENT_MAX_MB 必须是数字（MB）") from exc
    if value <= 0 or value > 1024:
        raise AttachmentError("invalid_request", "CORDYS_ATTACHMENT_MAX_MB 必须在 0 到 1024 之间")
    return int(value * 1024 * 1024)


def size_text(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def native_path(raw: str) -> Path:
    """Resolve ``~`` and Git Bash ``/c/...`` paths for the native interpreter."""
    text = str(raw).strip()
    if os.name == "nt":
        match = re.match(r"^/([A-Za-z])(/.*)?$", text)
        if match:
            text = f"{match.group(1)}:{match.group(2) or '/'}"
    return Path(text).expanduser()


def inspect_file(raw_path: str, limit: int) -> dict:
    path = native_path(raw_path)
    name = path.name or str(raw_path)

    def fail(reason: str):
        raise AttachmentError(
            "local_file_invalid", f"{name}：{reason}", file=name, path=str(raw_path)
        )

    if not path.is_file():
        fail("文件不存在或不是普通文件")
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        fail(f"扩展名 {ext or '（无）'} 不允许，只支持 {', '.join(ALLOWED_EXTENSIONS)}")
    size = path.stat().st_size
    if size == 0:
        fail("文件为空")
    if size > limit:
        fail(f"大小 {size_text(size)} 超过上限 {size_text(limit)}")
    try:
        with path.open("rb") as stream:
            stream.read(1)
    except OSError as exc:
        fail(f"文件不可读：{exc}")
    return {"path": str(path), "file": name, "size": size, "sizeText": size_text(size)}


def inspect_files(paths) -> list[dict]:
    """Validate every file; report all failures together, before any request."""
    if not paths:
        raise AttachmentError("invalid_request", "至少需要一个文件路径")
    limit = max_size_bytes()
    files, errors = [], []
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            errors.append({"file": str(raw), "reason": "文件路径必须是非空字符串"})
            continue
        try:
            files.append(inspect_file(raw, limit))
        except AttachmentError as exc:
            errors.append({"file": exc.details.get("file"), "reason": exc.message})
    if errors:
        raise AttachmentError(
            "local_file_invalid",
            "本地文件校验未通过，未发送任何请求：" + "；".join(e["reason"] for e in errors),
            errors=errors,
        )
    return files


# ── multipart 上传 ────────────────────────────────────────────────────
def _disposition_filename(name: str) -> str:
    # 文件名按 UTF-8 原样写入（Cordys 直接保存 getOriginalFilename）；只转义会破坏头部的字符。
    return name.replace("\\", "_").replace('"', "%22").replace("\r", "").replace("\n", "")


def build_multipart(name: str, content: bytes, boundary: str | None = None) -> tuple[bytes, str]:
    boundary = boundary or uuid.uuid4().hex
    mime = ALLOWED_EXTENSIONS.get(Path(name).suffix.lower(), "application/octet-stream")
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{_disposition_filename(name)}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    body = head + content + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, f"multipart/form-data; boundary={boundary}"


def _parse_json(text: str):
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _public_upload(item: dict) -> dict:
    return {key: item[key] for key in ("file", "size", "sizeText", "tempId") if key in item}


def upload_one(transport, item: dict) -> str:
    content = Path(item["path"]).read_bytes()
    body, content_type = build_multipart(item["file"], content)
    result = transport.request("POST", UPLOAD_PATH, raw=body, content_type=content_type)
    value = _parse_json(result.text)
    code = str(value.get("code")) if value else ""
    if result.http_status in (401, 403) or code in ("401", "403"):
        raise AttachmentError(
            "upload_auth_failed",
            f"{item['file']}：上传接口认证失败或无权限（HTTP {result.http_status}）",
            file=item["file"],
        )
    if not value or code != SUCCESS_CODE:
        detail = result.transport_error or (value or {}).get("message") or "响应不是成功 JSON"
        raise AttachmentError(
            "upload_failed",
            f"{item['file']}：上传失败（HTTP {result.http_status}）{detail}",
            file=item["file"],
        )
    data = value.get("data")
    if not (isinstance(data, list) and len(data) == 1 and isinstance(data[0], str) and data[0]):
        raise AttachmentError(
            "upload_failed", f"{item['file']}：上传响应未返回唯一临时附件 ID", file=item["file"]
        )
    return data[0]


def upload_files(transport, files: list[dict]) -> list[dict]:
    """Upload one file per request so a failure names the exact file."""
    uploaded = []
    for item in files:
        try:
            temp_id = upload_one(transport, item)
        except AttachmentError as exc:
            exc.details["uploaded"] = [_public_upload(u) for u in uploaded]
            raise
        uploaded.append({**item, "tempId": temp_id})
    return uploaded


def transport_from_env():
    from order_batch import OrderBatchError, UrllibTransport

    try:
        return UrllibTransport(
            str(os.environ.get("CORDYS_CRM_DOMAIN") or ""),
            str(os.environ.get("CORDYS_ACCESS_KEY") or ""),
            str(os.environ.get("CORDYS_SECRET_KEY") or ""),
            timeout=UPLOAD_TIMEOUT,
        )
    except OrderBatchError as exc:
        raise AttachmentError("invalid_request", str(exc)) from exc


# ── create/update 附件计划 ────────────────────────────────────────────
def _attachment_fields(module: str, schema_path) -> dict[str, dict]:
    schema_module = "contact" if module == "account/contact" else module
    try:
        modules = _load_schema_modules(schema_path)
    except PayloadTransportError as exc:
        raise AttachmentError("invalid_request", str(exc)) from exc
    fields = (modules.get(schema_module) or {}).get("fields") or {}
    return {
        str(field_id): field
        for field_id, field in fields.items()
        if isinstance(field, dict) and field.get("type") == "ATTACHMENT"
    }


def _resolve_field(key: str, candidates: dict[str, dict], module: str) -> tuple[str, str]:
    if key in candidates:
        return key, str(candidates[key].get("label") or key)
    matches = [fid for fid, field in candidates.items() if field.get("label") == key]
    if len(matches) == 1:
        return matches[0], key
    labels = "、".join(str(f.get("label")) for f in candidates.values()) or "（无）"
    reason = "对应多个附件字段" if matches else "不是附件字段"
    raise AttachmentError(
        "invalid_request", f"「{key}」{reason}；{module} 可用附件字段：{labels}"
    )


def plan_attachments(caller: dict, module: str, schema_path, operation: str) -> dict | None:
    """Pop ``attachments``/``attachmentMode`` and validate them locally.

    Mutates ``caller``. Returns ``None`` when the request has no attachments.
    """
    attachments = caller.pop("attachments", None)
    mode = caller.pop("attachmentMode", None)
    if attachments is None:
        if mode is not None:
            raise AttachmentError("invalid_request", "attachmentMode 只能与 attachments 一起使用")
        return None
    if mode is None:
        mode = "append"
    if mode not in ATTACHMENT_MODES:
        raise AttachmentError("invalid_request", "attachmentMode 只支持 append（默认，追加）或 replace（替换）")
    if not isinstance(attachments, dict) or not attachments:
        raise AttachmentError("invalid_request", 'attachments 必须是 {"附件字段标签": ["文件路径", ...]} 对象')
    record_id = str(caller.get("id") or "")
    if operation == "update" and not record_id:
        raise AttachmentError("invalid_request", "update 带附件时 JSON 必须包含 id")

    candidates = _attachment_fields(module, schema_path)
    fields, seen = [], set()
    for key, paths in attachments.items():
        field_id, label = _resolve_field(str(key), candidates, module)
        if field_id in seen:
            raise AttachmentError("invalid_request", f"附件字段「{label}」重复出现")
        seen.add(field_id)
        if not isinstance(paths, list) or not paths:
            raise AttachmentError("invalid_request", f"附件字段「{label}」的值必须是非空文件路径数组")
        fields.append({"label": label, "fieldId": field_id, "paths": paths})

    all_paths = [path for field in fields for path in field["paths"]]
    inspected = iter(inspect_files(all_paths))
    for field in fields:
        field["files"] = [next(inspected) for _ in field.pop("paths")]
    return {
        "module": module,
        "operation": operation,
        "mode": mode,
        "recordId": record_id,
        "fields": fields,
    }


def confirmation_rows(plan: dict) -> list[dict]:
    """Rows for the write confirmation table (file name, size, mode)."""
    mode_text = "替换（已有附件将被删除）" if plan["mode"] == "replace" else "追加（保留已有附件）"
    return [
        {"field": f["label"], "file": item["file"], "size": item["size"],
         "sizeText": item["sizeText"], "mode": mode_text}
        for f in plan["fields"] for item in f["files"]
    ]


def _field_ids(value, label: str) -> list[str]:
    if value in (None, "", []):
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise AttachmentError("invalid_request", f"附件字段「{label}」现有值不是附件 ID 数组，已中止以免误删附件")
    return list(value)


def _set_module_field(body: dict, field_id: str, value: list[str]) -> list[str]:
    """Replace the field's value in ``body.moduleFields``; return the prior IDs."""
    module_fields = body.get("moduleFields")
    if module_fields is None:
        module_fields = body["moduleFields"] = []
    if not isinstance(module_fields, list):
        raise AttachmentError("invalid_request", "moduleFields 必须是数组")
    prior: list[str] = []
    kept = []
    for item in module_fields:
        if isinstance(item, dict) and str(item.get("fieldId")) == field_id:
            prior.extend(v for v in _field_ids(item.get("fieldValue"), field_id) if v not in prior)
        else:
            kept.append(item)
    kept.append({"fieldId": field_id, "fieldValue": value})
    module_fields[:] = kept
    return prior


def upload_and_inject(plan: dict, body: dict, transport, mirrors=()) -> dict:
    """Upload every planned file, then write the final ID list into ``body``.

    ``body`` already holds the existing IDs (create: caller-supplied; update:
    merged from the readback), so append keeps them and replace drops them.
    ``mirrors`` receive the same final value (update readback verification).
    """
    files = [item for field in plan["fields"] for item in field["files"]]
    uploaded = iter(upload_files(transport, files))
    for field in plan["fields"]:
        field["uploaded"] = [next(uploaded) for _ in field["files"]]
        new_ids = [item["tempId"] for item in field["uploaded"]]
        current = next(
            (item.get("fieldValue") for item in body.get("moduleFields") or []
             if isinstance(item, dict) and str(item.get("fieldId")) == field["fieldId"]),
            None,
        )
        base = [] if plan["mode"] == "replace" else _field_ids(current, field["label"])
        final = base + [i for i in new_ids if i not in base]
        field["preservedIds"] = base
        field["replacedIds"] = [] if plan["mode"] == "append" else _field_ids(current, field["label"])
        _set_module_field(body, field["fieldId"], final)
        for mirror in mirrors:
            _set_module_field(mirror, field["fieldId"], final)
    return plan


# ── 写入后读回核验 ────────────────────────────────────────────────────
def _uploaded_summary(plan: dict) -> list[dict]:
    return [
        {"field": f["label"], "fieldId": f["fieldId"], **_public_upload(item)}
        for f in plan["fields"] for item in f.get("uploaded") or []
    ]


def finalize_write(
    plan: dict, write_text: str, transport, api_module: str, transport_ok: bool = True
) -> tuple[dict, int]:
    """Attach the attachment outcome to the write response (one readback GET).

    ``transport_ok`` is False when the write had a transport/HTTP failure: a
    non-success body then means "state unknown", not "definitely not written".
    """
    response = _parse_json(write_text)
    if not response or str(response.get("code")) != SUCCESS_CODE:
        result = dict(response) if response else {
            "code": 0, "writeState": "unknown", "response": (write_text or "")[:2000],
        }
        unknown = not response or not transport_ok or result.get("writeState") == "unknown"
        if unknown:
            result["writeState"] = "unknown"
        result.update({
            "retryAllowed": False,
            "attachmentState": "unknown" if unknown else "not_attached",
            "attachments": _uploaded_summary(plan),
            "attachmentMessage": (
                "写请求结果未知：附件已上传为临时文件，记录及附件状态都未确认；禁止自动重试，先读回核验"
                if unknown else
                "记录未写入，附件未挂到记录；已上传的临时文件留在服务器上，无需处理"
            ),
        })
        return result, 1

    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    record_id = plan.get("recordId") or str(data.get("id") or "")
    result = {**response, "retryAllowed": False, "attachments": _uploaded_summary(plan)}
    record = None
    if record_id:
        readback = transport.request("GET", f"/{api_module}/get/{record_id}")
        wrapper = _parse_json(readback.text)
        candidate = wrapper.get("data") if wrapper and str(wrapper.get("code")) == SUCCESS_CODE else None
        if isinstance(candidate, dict) and str(candidate.get("id")) == record_id:
            record = candidate
    if record is None:
        result["attachmentState"] = "unconfirmed"
        result["attachmentMessage"] = "记录已写入，但读回失败，附件未确认；不要报告附件已上传"
        return result, 0

    attachment_map = record.get("attachmentMap") or {}
    field_attachments, problems = {}, []
    for field in plan["fields"]:
        entries = [e for e in attachment_map.get(field["fieldId"]) or [] if isinstance(e, dict)]
        by_id = {str(e.get("id")): e for e in entries}
        field_attachments[field["label"]] = [
            {"id": e.get("id"), "name": e.get("name"), "size": e.get("size")} for e in entries
        ]
        for item in result["attachments"]:
            if item["fieldId"] != field["fieldId"]:
                continue
            found = by_id.get(item["tempId"])
            item["attachmentId"] = item["tempId"] if found else None
            item["readbackName"] = found.get("name") if found else None
            item["confirmed"] = bool(found) and found.get("name") == _disposition_filename(item["file"])
            if not item["confirmed"]:
                problems.append(item["file"])
        lost = [i for i in field.get("preservedIds") or [] if i not in by_id]
        if lost:
            result.setdefault("lostExistingAttachmentIds", []).extend(lost)
            problems.append(f"{field['label']} 原有附件 {len(lost)} 个")
    result["fieldAttachments"] = field_attachments
    if problems:
        result["attachmentState"] = "missing"
        result["attachmentMessage"] = (
            "记录已写入，但读回未确认全部附件（" + "、".join(problems)
            + "）；不要报告附件已上传，交由用户决定是否补传"
        )
    else:
        result["attachmentState"] = "confirmed"
        result["attachmentMessage"] = "附件已挂到记录（读回 attachmentMap 确认文件名与 ID）"
    return result, 0


def execute_write(plan: dict, body: dict, transport, api_module: str, action: str) -> tuple[dict, int]:
    """Upload, inject, POST once, then verify; used by the Python fallback CLI."""
    upload_and_inject(plan, body, transport)
    result = transport.request("POST", f"/{api_module}/{action}", body)
    return finalize_write(
        plan, result.text, transport, api_module, transport_ok=not result.transport_error
    )


# ── CLI ───────────────────────────────────────────────────────────────
def _emit(value: dict) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _read_json_file(path: str, who: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AttachmentError("invalid_request", f"{who}读取失败：{exc}") from exc
    if not isinstance(value, dict):
        raise AttachmentError("invalid_request", f"{who}必须是 JSON 对象")
    return value


def _write_json_file(path: str, value: dict) -> None:
    Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _cli_check(args) -> int:
    files = inspect_files(args)
    _emit({"code": 100200, "data": [{k: f[k] for k in ("file", "size", "sizeText")} for f in files]})
    return 0


def _cli_upload(args) -> int:
    files = inspect_files(args)
    uploaded = upload_files(transport_from_env(), files)
    _emit({"code": 100200, "data": [_public_upload(u) for u in uploaded]})
    return 0


def _cli_plan(args) -> int:
    # stdin: caller JSON. 无 attachments 时不输出；有则输出两行：剥离后的调用方文件、计划文件。
    if len(args) != 3:
        raise AttachmentError("invalid_request", "用法: attachment_upload.py plan <module> <schema> <create|update>")
    module, schema_path, operation = args
    try:
        caller = json.loads(read_utf8() or "null")
    except (json.JSONDecodeError, PayloadTransportError) as exc:
        raise AttachmentError("invalid_request", f"请求 JSON 解析失败：{exc}") from exc
    if not isinstance(caller, dict):
        raise AttachmentError("invalid_request", "请求 JSON 顶层必须是对象")
    plan = plan_attachments(caller, module, schema_path, operation)
    if plan is None:
        return 0
    caller_path = write_temp_json(caller, prefix="cordys_caller_")
    plan_path = write_temp_json(plan, prefix="cordys_attach_")
    sys.stdout.write(f"{caller_path}\n{plan_path}\n")
    return 0


def _cli_upload_inject(args) -> int:
    if len(args) not in (2, 3):
        raise AttachmentError("invalid_request", "用法: attachment_upload.py upload-inject <plan> <body> [caller]")
    plan = _read_json_file(args[0], "附件计划")
    body = _read_json_file(args[1], "写请求体")
    mirrors = [_read_json_file(args[2], "调用方请求")] if len(args) == 3 else []
    upload_and_inject(plan, body, transport_from_env(), mirrors)
    _write_json_file(args[1], body)
    if mirrors:
        _write_json_file(args[2], mirrors[0])
    _write_json_file(args[0], plan)
    return 0


def _cli_finalize(args) -> int:
    if len(args) != 3:
        raise AttachmentError(
            "invalid_request",
            "用法: attachment_upload.py finalize <api-module> <plan> <write-exit-status> < write-output",
        )
    api_module, plan_path, write_status = args
    plan = _read_json_file(plan_path, "附件计划")
    result, status = finalize_write(
        plan, read_utf8(), transport_from_env(), api_module, transport_ok=write_status == "0"
    )
    _emit(result)
    return status


COMMANDS = {
    "check": _cli_check,
    "upload": _cli_upload,
    "plan": _cli_plan,
    "upload-inject": _cli_upload_inject,
    "finalize": _cli_finalize,
}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    handler = COMMANDS.get(args[0]) if args else None
    if handler is None:
        _emit({"code": 0, "errorCategory": "invalid_request",
               "message": "用法: attachment_upload.py <check|upload|plan|upload-inject|finalize> ..."})
        return 1
    try:
        return handler(args[1:])
    except AttachmentError as exc:
        _emit(exc.to_result())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
