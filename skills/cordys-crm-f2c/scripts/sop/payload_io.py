"""UTF-8 transport helpers for query payloads."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


class PayloadTransportError(ValueError):
    """The payload could not be decoded, parsed, or normalized."""


def read_utf8(stream=None) -> str:
    """Read UTF-8 (optionally BOM-prefixed) text from a binary/text stream."""
    stream = stream or sys.stdin
    binary = getattr(stream, "buffer", None)
    if binary is not None:
        raw = binary.read()
        if isinstance(raw, bytes):
            try:
                return raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise PayloadTransportError(
                    f"stdin 不是合法 UTF-8：{exc}"
                ) from exc
    text = stream.read()
    if isinstance(text, bytes):
        try:
            return text.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise PayloadTransportError(
                f"stdin 不是合法 UTF-8：{exc}"
            ) from exc
    return text.lstrip("\ufeff")


def parse_json(raw: str, *, json_only=False, who="查询") -> dict:
    """Parse a JSON object without treating malformed JSON as a keyword."""
    raw = (raw or "").lstrip("\ufeff").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        if json_only or raw.startswith(("{", "[")):
            raise PayloadTransportError(f"{who} JSON 解析失败: {exc}") from exc
        return {"keyword": raw}
    if not isinstance(value, dict):
        if json_only or raw.startswith(("{", "[")):
            raise PayloadTransportError(f"{who} payload 顶层必须是 JSON 对象")
        return {"keyword": raw}
    return value


def normalize_query(
    raw, module="", sop_dir="", schema_path="", json_mode="", query_mode=""
):
    """Apply the shared query defaults and schema contract."""
    default = {
        "current": 1,
        "pageSize": 30,
        "sort": {},
        "combineSearch": {"searchMode": "AND", "conditions": []},
        "keyword": "",
        "viewId": "ALL",
        "filters": [],
    }
    user = parse_json(
        raw,
        json_only=json_mode == "json-only",
        who="查询",
    )
    merged = {**default, **user}
    # 联系人列表端点按可见范围查询；销售默认只能看本人联系人。
    # 显式传入 viewId（例如经理允许的 ALL）时保留调用方范围。
    if module in {"contact", "account/contact"} and "viewId" not in user:
        merged["viewId"] = "SELF"
    if module:
        try:
            if sop_dir:
                sys.path.insert(0, sop_dir)
            from query_contract import validate_payload, validate_query_semantics

            merged = validate_payload(module, merged, schema_path or None)
            merged = validate_query_semantics(module, merged, query_mode)
        except ValueError as exc:
            raise PayloadTransportError(f"查询条件无效: {exc}") from exc
    if not isinstance(merged.get("current"), int) or merged["current"] < 1:
        merged["current"] = 1
    if not isinstance(merged.get("pageSize"), int) or merged["pageSize"] < 1:
        merged["pageSize"] = 30
    return merged


def write_temp_json(value, prefix="cordys_") -> str:
    """Write a UTF-8 JSON temp file and return its native path."""
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False)
    except BaseException:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return path


def _normalize_query_cli(args):
    if len(args) != 5:
        raise PayloadTransportError(
            "用法: payload_io.py normalize-query <module> <sop_dir> <schema> <json-mode> <query-mode>"
        )
    module, sop_dir, schema_path, json_mode, query_mode = args
    body = normalize_query(
        read_utf8(), module, sop_dir, schema_path, json_mode, query_mode
    )
    print(write_temp_json(body), flush=True)


def _normalize_parent_cli(args):
    if len(args) != 5:
        raise PayloadTransportError(
            "用法: payload_io.py normalize-parent <field> <parent-id> <module> <sop-dir> <schema>"
        )
    field, parent_id, module, sop_dir, schema_path = args
    body = normalize_query(read_utf8(), module, sop_dir, schema_path)
    body[field] = parent_id
    print(write_temp_json(body), flush=True)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args and args[0] == "normalize-query":
            _normalize_query_cli(args[1:])
        elif args and args[0] == "normalize-parent":
            _normalize_parent_cli(args[1:])
        else:
            raise PayloadTransportError("未知 payload 传输命令")
    except PayloadTransportError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
