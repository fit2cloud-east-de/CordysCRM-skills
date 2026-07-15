"""全量分页公共逻辑，供 crm pageall 使用。"""
import json
import os
import sys
import urllib.error
import urllib.request


PAGE_SIZE = 500


def _make_api_post(domain, access_key, secret_key):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api_post(path, body):
        request = urllib.request.Request(
            f"{domain}{path}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "X-Access-Key": access_key,
                "X-Secret-Key": secret_key,
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with opener.open(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8-sig"))
        except urllib.error.HTTPError as error:
            try:
                return json.loads(error.read().decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                print(f"分页 HTTP 错误响应不是合法 UTF-8 JSON: {exc}", file=sys.stderr)
                raise SystemExit(1) from exc
        except urllib.error.URLError as error:
            print(f"分页请求失败: {error}", file=sys.stderr)
            raise SystemExit(1) from error

    return api_post


def _parse_payload(payload_raw, has_payload, who):
    """解析传入条件；传了空或非法 JSON 时绝不退化为全量查询。"""
    payload = {}
    raw = (payload_raw or "").lstrip("\ufeff").strip()
    if has_payload:
        if not raw:
            print(json.dumps({"error": f"{who} 收到空 payload，已中止以避免误查全库"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            print(json.dumps({"error": f"{who} payload 不是合法 JSON: {error}"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
    if not isinstance(payload, dict):
        print(json.dumps({"error": f"{who} payload 顶层必须是 JSON 对象"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    if "combineSearch" not in payload:
        payload["combineSearch"] = {"searchMode": "AND", "conditions": []}
    return payload


def fetch_all(prefix, who):
    """按环境变量查询全部页，返回 (records, total, pages)。"""
    env = os.environ
    domain = env[f"{prefix}_DOMAIN"]
    module = env[f"{prefix}_MODULE"]
    api_post = _make_api_post(domain, env[f"{prefix}_KEY"], env[f"{prefix}_SECRET"])
    payload = _parse_payload(
        env.get(f"{prefix}_PAYLOAD", ""),
        env.get(f"{prefix}_HAS_PAYLOAD", "0") == "1",
        who,
    )
    try:
        from query_contract import validate_payload, validate_query_semantics

        schema_module = env.get(f"{prefix}_SCHEMA_MODULE", module)
        payload = validate_payload(schema_module, payload, env.get(f"{prefix}_SCHEMA"))
        payload = validate_query_semantics(
            schema_module, payload, env.get(f"{prefix}_QUERY_MODE", "pageall")
        )
    except ValueError as error:
        print(json.dumps({"error": f"{who} 查询条件无效: {error}"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    payload.setdefault("viewId", "ALL")

    records = []
    total = 0
    current = 1
    while True:
        payload["current"] = current
        payload["pageSize"] = PAGE_SIZE
        response = api_post(f"/{module}/page", payload)
        if response.get("code") != 100200:
            print(json.dumps(response, ensure_ascii=False))
            sys.exit(1)
        data = response.get("data") or {}
        page_records = data.get("list") or []
        records.extend(page_records)
        total = data.get("total", 0) or 0
        if len(records) >= total:
            return records, total, current
        if not page_records:
            print(json.dumps({"error": f"{who} 第 {current} 页为空，但 total={total} 且仅取得 {len(records)} 条"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        current += 1
