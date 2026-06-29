"""翻页拉全量的公共逻辑，供 cordys.sh 的 aggregate / pageall 复用。

为什么独立成库：两条命令都要「读 total 逐页翻页 + payload 校验 + 读 HTTPError body」，
内联会各抄一份（已踩坑：50 行重复，改翻页逻辑要改两处）。这里集中一份，
aggregate 拿到全量 list 后本地聚合，pageall 直接吐 list。

约定经环境变量读凭证/参数（同 cordys.sh 既有风格，规避 /tmp 路径转换坑）：
  <PREFIX>_DOMAIN / _KEY / _SECRET / _MODULE / _PAYLOAD / _HAS_PAYLOAD
"""
import json
import os
import sys
import urllib.request
import urllib.error

PAGE_SIZE = 200


def _make_api_post(domain, access_key, secret_key):
    def api_post(path, body):
        url = f"{domain}{path}"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "X-Access-Key": access_key,
            "X-Secret-Key": secret_key,
            "Content-Type": "application/json; charset=utf-8",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Cordys 即使 HTTP 5xx 也把业务结果放在 body，必须读出来。
            return json.loads(e.read().decode("utf-8"))
    return api_post


def _parse_payload(payload_raw, has_payload, who):
    """解析 payload。传了却解析不出来必须 die，绝不静默用空 conditions 查全租户
    （会返回貌似合理的全库结果，已踩坑）。"""
    payload = {}
    raw = (payload_raw or "").strip()
    if has_payload:
        if not raw:
            print(json.dumps({"error": f"{who} 收到空 payload（has_payload=1 但内容为空），已中止以避免误查全库"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"{who} payload 不是合法 JSON: {e}", "raw_head": raw[:120]}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
    if "combineSearch" not in payload:
        payload["combineSearch"] = {"searchMode": "AND", "conditions": []}
    return payload


def fetch_all(prefix, who):
    """按环境变量拉全量，返回 (records, total, api_post)。
    接口非 100200 时打印原始响应并退出（与既有行为一致）。"""
    env = os.environ
    domain = env[f"{prefix}_DOMAIN"]
    module = env[f"{prefix}_MODULE"]
    api_post = _make_api_post(domain, env[f"{prefix}_KEY"], env[f"{prefix}_SECRET"])
    payload = _parse_payload(env.get(f"{prefix}_PAYLOAD", ""),
                             env.get(f"{prefix}_HAS_PAYLOAD", "0") == "1", who)

    records = []
    total = 0
    current = 1
    while True:
        payload["current"] = current
        payload["pageSize"] = PAGE_SIZE
        resp = api_post(f"/{module}/page", payload)
        if resp.get("code") != 100200:
            print(json.dumps(resp, ensure_ascii=False))
            sys.exit(1)
        data = resp.get("data", {})
        records.extend(data.get("list", []))
        total = data.get("total", 0)
        if current * PAGE_SIZE >= total:
            break
        current += 1
    return records, total, api_post
