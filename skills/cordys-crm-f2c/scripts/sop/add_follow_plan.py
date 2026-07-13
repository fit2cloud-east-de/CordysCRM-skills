import json
import re
import time
import unicodedata
from urllib import request
from urllib.error import HTTPError, URLError

from time_boundary import TimeBoundaryError, parse_datetime_ms


def add_follow_plan(domain, access_key, secret_key, params=""):
    """
    Cordys CRM 写跟进计划工具 — 给已存在的线索/客户/商机排一条后续跟进计划。

    与跟进记录（add_follow_record）平行，但字段契约不同（均为实测）：
      - 端点：POST /{module}/follow/plan/add（记录是 .../follow/record/add）
      - 必填：type + method（记录只必填 type）
      - 跟进方式字段名是 method（记录是 followMethod）
      - 计划时间字段名是 estimatedTime（记录是 followTime）
      - 跟进方式选项 ID 取自 /follow/plan/module/form，与记录表单的 ID 不同，不可混用
      - status 缺省由后端置 PREPARED

    自动完成：跟进方式 label→value 转换、意向产品名称→ID、跟进人姓名→userId、
    表单字段动态发现、moduleFields 自定义字段构建、失败重取表单重试。

    Args:
        domain: CRM 域名，如 https://crm.fit2cloud.com
        access_key: 用户的 X-Access-Key
        secret_key: 用户的 X-Secret-Key
        params: JSON 字符串，例如：
            {"module":"lead","clueId":"384225738486157312","content":"下周电话回访采购进度",
             "跟进方式":"电话","跟进人":"万梓良","计划时间":"2026-07-15 10:00","意向产品":["MaxKB 企业版"]}
          说明：
            - module 必填：lead / account / opportunity
            - 资源 ID 二选一：传 clueId / customerId / opportunityId 之一；
              商机计划可同时带 customerId（归属客户）
            - content 计划内容必填（预计沟通内容）
            - 跟进方式/method：中文或ID均可（到访/电话/微信/邮件/线上会议），必填
            - 跟进人/owner：姓名或 userId 均可；缺省用当前登录用户
            - 计划时间/estimatedTime：可缺省（默认当前时间），支持 "YYYY-MM-DD HH:MM"、
              JSON 整数毫秒时间戳或纯数字字符串毫秒时间戳
            - 意向产品/products：名称数组，自动转 ID 写入 moduleFields

    Returns:
        JSON 字符串，包含 code、data 或 error
    """

    try:
        p = json.loads(params) if isinstance(params, str) else params or {}
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "params JSON 解析失败"}, ensure_ascii=False)

    module = p.pop("module", "")
    if module not in ("lead", "account", "opportunity"):
        return json.dumps({"error": "module 必须为 lead/account/opportunity"}, ensure_ascii=False)

    # 资源 ID 字段映射
    ID_FIELDS = {"lead": "clueId", "account": "customerId", "opportunity": "opportunityId"}
    PLAN_TYPE = {"lead": "CLUE", "account": "CUSTOMER", "opportunity": "CUSTOMER"}

    id_field = ID_FIELDS[module]
    # 兼容用户把 ID 放在 sourceId / id 里
    source_id = p.get(id_field) or p.get("sourceId") or p.get("id") or ""
    if not source_id:
        return json.dumps({"error": f"缺少资源 ID（{id_field} / sourceId）"}, ensure_ascii=False)

    content = p.get("content") or p.get("计划内容") or p.get("跟进内容") or ""
    if not content:
        return json.dumps({"error": "缺少 content 计划内容"}, ensure_ascii=False)

    # 计划时间必须在任何联网/写入前完成解析。显式传入非法值时禁止静默回退当前时间，
    # 否则 /follow/plan/add 会创建一条时间错误但 code=100200 的真实计划。
    time_keys = ("estimatedTime", "计划时间", "planTime", "followTime", "跟进时间")
    time_supplied = False
    raw_estimated_time = None
    for key in time_keys:
        if key in p:
            time_supplied = True
            raw_estimated_time = p[key]
            break

    def parse_estimated_time(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            parsed = value
        elif isinstance(value, str):
            normalized = value.strip()
            if re.fullmatch(r"\d+", normalized):
                parsed = int(normalized)
            else:
                try:
                    parsed = parse_datetime_ms(normalized)
                except TimeBoundaryError:
                    return None
        else:
            return None

        # 拦截常见的秒级时间戳和不合理值；接口契约要求毫秒。
        if not 100_000_000_000 <= parsed <= 9_999_999_999_999:
            return None
        return parsed

    if time_supplied:
        estimated_time = parse_estimated_time(raw_estimated_time)
        if estimated_time is None:
            return json.dumps({
                "error": "计划时间格式无效：请传 YYYY-MM-DD HH:MM、JSON 整数毫秒时间戳或纯数字字符串毫秒时间戳；未创建跟进计划"
            }, ensure_ascii=False)
    else:
        estimated_time = int(time.time() * 1000)

    add_api = f"/{module}/follow/plan/add"

    # ── API helper（与 add_follow_record 同范式）──
    def api(method, path, data=None):
        url = f"{domain}{path}"
        headers = {
            "X-Access-Key": access_key,
            "X-Secret-Key": secret_key,
            "Content-Type": "application/json;charset=UTF-8",
        }
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
        req = request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode(resp.headers.get_content_charset() or "utf-8"))
        except HTTPError as e:
            try:
                body = e.read().decode(e.headers.get_content_charset() or "utf-8")
                return json.loads(body)
            except Exception:
                return {"code": 0, "message": f"HTTP {e.code}: {e.reason}"}
        except (URLError, TimeoutError, OSError) as e:
            return {"code": 0, "message": str(e)}

    # ── 当前登录用户（用于跟进人缺省 / 姓名→userId）──
    _me = {}
    _me_loaded = False

    def get_me():
        nonlocal _me_loaded
        if not _me_loaded:
            _me_loaded = True
            r = api("GET", "/personal/center/info")
            if r.get("code") == 100200:
                _me.update(r.get("data") or {})
        return _me

    # ── 跟进人 owner：姓名→userId ──
    def resolve_owner(value):
        # 已是 userId：不调 whoami，避免 /personal/center/info 超时拖垮整单
        if value and str(value).isdigit() and len(str(value)) >= 10:
            return str(value)
        if not value:
            # whoami 失败则交后端默认当前用户，不阻断写入
            return get_me().get("userId", "") or ""
        me = get_me()
        if value == me.get("userName") or value == me.get("name"):
            return me.get("userId", "") or str(value)
        r = api("POST", "/user/list", {"current": 1, "pageSize": 20, "keyword": str(value)})
        if r.get("code") == 100200:
            for u in (r.get("data", {}).get("list") or []):
                if u.get("name") == value or u.get("userName") == value:
                    return u.get("userId") or u.get("id") or ""
        return str(value)

    # ── 意向产品名→ID ──
    def get_product_map():
        r = api("POST", "/field/source/product", {"current": 1, "pageSize": 200, "keyword": ""})
        if r.get("code") != 100200:
            return {}
        return {item["name"]: item["id"] for item in r.get("data", {}).get("list", [])}

    def resolve_products(products):
        if isinstance(products, str):
            products = [products] if products else []
        if not products:
            return []
        pm = get_product_map()
        return [pm.get(name, name) for name in products]

    # ── SELECT 模糊匹配（与 add_follow_record 同范式）──
    _ZERO_WIDTH_RE = re.compile(r"[​-‏‪-‮⁠﻿]")

    def _normalize(s):
        return _ZERO_WIDTH_RE.sub("", unicodedata.normalize("NFKC", str(s))).strip()

    def _fuzzy_match(value, label_to_value):
        nv = _normalize(value)
        for label, mapped in label_to_value.items():
            nl = _normalize(label)
            if nl == nv:
                return mapped
            if nl.startswith(nv) and len(nv) >= 2:
                return mapped
        return None

    # ── 获取跟进计划表单配置（全局，不分模块）──
    # 注意：用跟进计划自己的表单，跟进方式选项 ID 与跟进记录表单不同，不可复用。
    def get_form_fields():
        resp = api("GET", "/follow/plan/module/form")
        if resp.get("code") != 100200:
            return None
        fields = []
        for f in resp["data"]["fields"]:
            if f["type"] == "DIVIDER":
                continue
            label_to_value = {o["label"]: o["value"] for o in (f.get("options") or [])}
            fields.append({
                "id": f["id"],
                "name": f["name"],
                "key": f.get("internalKey") or "",
                "businessKey": f.get("businessKey") or "",
                "type": f["type"],
                "label_to_value": label_to_value,
            })
        return fields

    # 跟进方式可能的中文别名 → 表单 label
    METHOD_ALIAS = {
        "拜访": "到访", "上门": "到访", "面谈": "到访", "当面": "到访",
        "电话": "电话", "打电话": "电话",
        "微信": "微信", "企业微信": "微信",
        "邮件": "邮件", "邮箱": "邮件", "email": "邮件",
        "线上会议": "线上会议", "视频": "线上会议", "会议": "线上会议", "腾讯会议": "线上会议",
    }

    # ── 构建请求体 ──
    def build_body(fields):
        body = {
            "type": PLAN_TYPE[module],
            id_field: source_id,
            "content": content,
            "moduleFields": [],
        }
        # 商机计划可带归属客户
        if module == "opportunity" and (p.get("customerId") or p.get("客户ID")):
            body["customerId"] = p.get("customerId") or p.get("客户ID")

        # 跟进人
        owner_in = p.get("owner") or p.get("跟进人") or ""
        body["owner"] = resolve_owner(owner_in)

        # 已在任何 API 调用前完成严格解析；失败重建 body 时也复用同一时间值。
        body["estimatedTime"] = estimated_time

        # 跟进方式 label→value（计划的字段名是 method，必填）
        method_in = p.get("method") or p.get("followMethod") or p.get("跟进方式") or ""
        mfield = next((f for f in fields if f["businessKey"] == "method"), None)
        l2v = mfield["label_to_value"] if mfield else {}
        mv = ""
        if method_in:
            if str(method_in) in l2v.values():
                mv = str(method_in)  # 已是 value
            else:
                label = METHOD_ALIAS.get(str(method_in), str(method_in))
                mv = l2v.get(label) or _fuzzy_match(label, l2v) or ""
        # method 必填：用户没给或没匹配上时兜底为「电话」(2)
        if not mv:
            mv = l2v.get("电话") or "2"
        body["method"] = mv

        # 联系人 ID（如已解析）
        if p.get("contactId"):
            body["contactId"] = p["contactId"]

        # 意向产品 → moduleFields
        products = p.get("products") or p.get("意向产品") or p.get("产品") or []
        prod_ids = resolve_products(products)
        if prod_ids:
            pfield = next((f for f in fields if f["type"] == "DATA_SOURCE_MULTIPLE"), None)
            if pfield:
                body["moduleFields"].append({"fieldId": pfield["id"], "fieldValue": prod_ids})

        return body

    # ── 执行 ──
    fields = get_form_fields()
    if fields is None:
        # 表单拿不到也能写：用最小字段集兜底
        fields = []
    body = build_body(fields)
    result = api("POST", add_api, body)
    # 新增接口非幂等：任何非成功响应都原样返回，由调用方先查询确认是否已落库，禁止自动重试。
    return json.dumps(result, ensure_ascii=False)
