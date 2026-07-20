"""全量分页与本地聚合公共逻辑，供 page-summary 使用。"""
import json
import os
import sys
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path


PAGE_SIZE = 500
MAX_GROUP_FIELDS = 5
MAX_SUM_FIELDS = 10
MAX_TOP_N = 100
GROUP_FIELD_TYPES = {
    "RADIO", "SELECT", "CHECKBOX", "MEMBER", "DEPARTMENT", "TREE_SELECT",
    "DATA_SOURCE", "SELECT_MULTIPLE", "MEMBER_MULTIPLE", "DEPARTMENT_MULTIPLE",
    "DATA_SOURCE_MULTIPLE", "LOCATION",
}


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


def iter_pages(prefix, who):
    """按环境变量逐页查询并产出 ``(records, total, page)``。

    本函数不保存历史页，适合在本地进程中做流式统计，避免完整明细进入
    CLI stdout 和模型上下文。调用方必须完整消费迭代器，才能确认已取完全部页。
    """
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
        from query_contract import (
            validate_payload,
            validate_pool_query_scope,
            validate_query_semantics,
        )

        payload = validate_pool_query_scope(
            module,
            payload,
            env.get(f"{prefix}_QUERY_MODE", "page-summary"),
        )
        payload = validate_payload(module, payload, env.get(f"{prefix}_SCHEMA"))
        payload = validate_query_semantics(
            module, payload, env.get(f"{prefix}_QUERY_MODE", "page-summary")
        )
    except ValueError as error:
        print(json.dumps({"error": f"{who} 查询条件无效: {error}"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    payload.setdefault("viewId", "SELF" if module in {"contact", "account/contact"} else "ALL")

    fetched = 0
    total = 0
    current = 1
    while True:
        payload["current"] = current
        payload["pageSize"] = PAGE_SIZE
        response = api_post(f"/{module}/page", payload)
        if response.get("code") != 100200:
            print(json.dumps(response, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        data = response.get("data") or {}
        if not isinstance(data, dict):
            print(json.dumps({"error": f"{who} 第 {current} 页 data 不是对象"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        page_records = data.get("list") or []
        if not isinstance(page_records, list):
            print(json.dumps({"error": f"{who} 第 {current} 页 data.list 不是数组"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        page_total = data.get("total", 0) or 0
        if not isinstance(page_total, int) or isinstance(page_total, bool) or page_total < 0:
            print(json.dumps({"error": f"{who} 第 {current} 页 total 不是非负整数"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        if current > 1 and page_total != total:
            print(json.dumps({"error": f"{who} 分页期间 total 从 {total} 变为 {page_total}，已中止以避免不一致统计"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        total = page_total
        fetched += len(page_records)
        yield page_records, total, current
        if fetched >= total:
            return
        if not page_records:
            print(json.dumps({"error": f"{who} 第 {current} 页为空，但 total={total} 且仅取得 {fetched} 条"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        current += 1


def _field_value(record, field):
    if field in record:
        return record.get(field)
    for item in record.get("moduleFields") or []:
        if isinstance(item, dict) and item.get("fieldId") == field:
            return item.get("fieldValue")
    return None


def _label_value(record, field, value):
    candidates = {
        "owner": ("ownerName",),
        "stage": ("stageName",),
        "departmentId": ("departmentName",),
    }.get(field, (f"{field}Name",))
    for candidate in candidates:
        label = record.get(candidate)
        if label not in (None, ""):
            return str(label)
    return "(空)" if value is None else str(value)


def _group_key(value):
    if value in (None, ""):
        return "__EMPTY__"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _decimal(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _json_number(value):
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _load_summary_fields(schema_path, module):
    aliases = {
        "account/contact": "contact",
        "payment-record": "contract/payment-record",
        "pool/lead": "lead",
        "pool/account": "account",
    }
    data = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    canonical = aliases.get(module, module)
    module_meta = (data.get("modules") or {}).get(canonical) or {}
    return module_meta.get("fields") or {}


def validate_summary_spec(spec, module, schema_path):
    """校验 page-summary 配置与字段 schema。"""
    if not isinstance(spec, dict):
        raise ValueError("summary JSON 顶层必须是对象")
    allowed = {"sum", "groupBy", "topN", "orderBy"}
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValueError(f"summary JSON 含未知字段: {','.join(unknown)}")

    sums = spec.get("sum") or []
    groups = spec.get("groupBy") or []
    if isinstance(sums, str):
        sums = [sums]
    if isinstance(groups, str):
        groups = [groups]
    if not isinstance(sums, list) or not all(isinstance(x, str) and x for x in sums):
        raise ValueError("sum 必须是字段名字符串数组")
    if not isinstance(groups, list) or not all(isinstance(x, str) and x for x in groups):
        raise ValueError("groupBy 必须是字段名字符串数组")
    sums = list(dict.fromkeys(sums))
    groups = list(dict.fromkeys(groups))
    if len(sums) > MAX_SUM_FIELDS or len(groups) > MAX_GROUP_FIELDS:
        raise ValueError(f"sum 最多 {MAX_SUM_FIELDS} 个字段，groupBy 最多 {MAX_GROUP_FIELDS} 个字段")

    top_n = spec.get("topN", 20)
    if not isinstance(top_n, int) or isinstance(top_n, bool) or not 1 <= top_n <= MAX_TOP_N:
        raise ValueError(f"topN 必须是 1-{MAX_TOP_N} 的整数")
    order_by = spec.get("orderBy", "count")
    if order_by != "count" and not (isinstance(order_by, str) and order_by.startswith("sum:")):
        raise ValueError("orderBy 只支持 count 或 sum:<字段名>")
    if order_by.startswith("sum:") and order_by[4:] not in sums:
        raise ValueError("orderBy 的求和字段必须同时出现在 sum 中")

    fields = _load_summary_fields(schema_path, module)
    for field in sums + groups:
        if field not in fields:
            raise ValueError(f"字段 {field} 不在 {module} schema 中；请核对 forms 或先执行 sync")
    for field in sums:
        if (fields.get(field) or {}).get("type") != "INPUT_NUMBER":
            raise ValueError(f"sum 字段 {field} 不是 INPUT_NUMBER")
    for field in groups:
        field_type = (fields.get(field) or {}).get("type")
        if field_type not in GROUP_FIELD_TYPES:
            raise ValueError(
                f"groupBy 字段 {field} 的类型是 {field_type}；仅允许枚举、成员、部门、数据源或地区等有限维度，"
                "避免按名称/备注等高基数字段聚合耗尽本地内存"
            )
    return {"sum": sums, "groupBy": groups, "topN": top_n, "orderBy": order_by}


def summarize_pages(pages, spec):
    """流式消费分页结果并返回有限摘要；不保存完整记录。"""
    sums = {field: Decimal(0) for field in spec["sum"]}
    numeric_counts = {field: 0 for field in spec["sum"]}
    invalid = {field: 0 for field in spec["sum"]}
    groups = {field: {} for field in spec["groupBy"]}
    count = 0
    reported_total = 0
    page_count = 0

    for records, reported_total, page_count in pages:
        for record in records:
            count += 1
            numeric = {}
            for field in spec["sum"]:
                raw = _field_value(record, field)
                number = _decimal(raw)
                numeric[field] = number
                if number is None:
                    if raw not in (None, ""):
                        invalid[field] += 1
                else:
                    sums[field] += number
                    numeric_counts[field] += 1
            for field in spec["groupBy"]:
                raw = _field_value(record, field)
                key = _group_key(raw)
                bucket = groups[field].setdefault(key, {
                    "key": None if key == "__EMPTY__" else raw,
                    "label": _label_value(record, field, raw),
                    "count": 0,
                    "sums": {sum_field: Decimal(0) for sum_field in spec["sum"]},
                })
                bucket["count"] += 1
                for sum_field, number in numeric.items():
                    if number is not None:
                        bucket["sums"][sum_field] += number

    order_by = spec["orderBy"]
    output_groups = {}
    truncated = {}
    for field, buckets in groups.items():
        values = list(buckets.values())
        if order_by == "count":
            values.sort(key=lambda item: (-item["count"], item["label"]))
        else:
            sum_field = order_by[4:]
            values.sort(key=lambda item: (-item["sums"][sum_field], item["label"]))
        truncated[field] = len(values) > spec["topN"]
        values = values[:spec["topN"]]
        for item in values:
            item["sums"] = {name: _json_number(value) for name, value in item["sums"].items()}
        output_groups[field] = values

    if count != reported_total:
        raise ValueError(f"分页完整性校验失败: 实际消费 {count} 条，服务端 total={reported_total}")
    bad_fields = {field: value for field, value in invalid.items() if value}
    if bad_fields:
        raise ValueError(f"数字字段含无法解析的非空值: {bad_fields}")
    averages = {
        field: (_json_number(sums[field] / numeric_counts[field]) if numeric_counts[field] else None)
        for field in spec["sum"]
    }
    return {
        "count": count,
        "reportedTotal": reported_total,
        "pages": page_count,
        "sums": {field: _json_number(value) for field, value in sums.items()},
        "numericCounts": numeric_counts,
        "averages": averages,
        "invalidNumeric": invalid,
        "groups": output_groups,
        "truncatedGroups": truncated,
    }
