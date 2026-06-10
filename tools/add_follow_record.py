import json
import re
import time
import unicodedata
from datetime import datetime
from urllib import request
from urllib.error import HTTPError, URLError


def add_follow_record(domain, access_key, secret_key, params=""):
    """
    Cordys CRM 写跟进记录工具 — 给已存在的线索/客户/商机写一条跟进记录。

    自动完成：跟进方式 label→value 转换、意向产品名称→ID、跟进人姓名→userId、
    表单字段动态发现、moduleFields 自定义字段构建、失败重取表单重试。

    Args:
        domain: CRM 域名，如 https://crm.fit2cloud.com
        access_key: 用户的 X-Access-Key
        secret_key: 用户的 X-Secret-Key
        params: JSON 字符串，例如：
            {"module":"lead","clueId":"384225738486157312","content":"电话沟通了采购需求",
             "跟进方式":"电话","跟进人":"万梓良","意向产品":["MaxKB 企业版"]}
          说明：
            - module 必填：lead / account / opportunity
            - 资源 ID 二选一：传 clueId / customerId / opportunityId 之一；
              商机跟进可同时带 customerId（归属客户）
            - content 跟进内容必填
            - 跟进方式/followMethod：中文或ID均可（到访/电话/微信/邮件/线上会议）
            - 跟进人/owner：姓名或 userId 均可；缺省用当前登录用户
            - 跟进时间/followTime：可缺省（默认当前时间），支持 "YYYY-MM-DD HH:MM" 或毫秒时间戳
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
    RECORD_TYPE = {"lead": "CLUE", "account": "CUSTOMER", "opportunity": "CUSTOMER"}

    id_field = ID_FIELDS[module]
    # 兼容用户把 ID 放在 sourceId / id 里
    source_id = p.get(id_field) or p.get("sourceId") or p.get("id") or ""
    if not source_id:
        return json.dumps({"error": f"缺少资源 ID（{id_field} / sourceId）"}, ensure_ascii=False)

    content = p.get("content") or p.get("跟进内容") or ""
    if not content:
        return json.dumps({"error": "缺少 content 跟进内容"}, ensure_ascii=False)

    add_api = f"/{module}/follow/record/add"

    # ── API helper（与 create_entity 同范式）──
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
            with request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode(resp.headers.get_content_charset() or "utf-8"))
        except (HTTPError, URLError) as e:
            return {"code": 0, "message": str(e)}

    # ── 当前登录用户（用于跟进人缺省 / 姓名→userId）──
    _me = {}

    def get_me():
        if not _me:
            r = api("GET", "/personal/center/info")
            if r.get("code") == 100200:
                _me.update(r.get("data") or {})
        return _me

    # ── 跟进人 owner：姓名→userId ──
    def resolve_owner(value):
        me = get_me()
        if not value:
            return me.get("userId", "")
        # 已是 userId（纯数字长串）直接用
        if str(value).isdigit() and len(str(value)) >= 10:
            return str(value)
        # 匹配当前用户姓名
        if value == me.get("userName"):
            return me.get("userId", "")
        # 否则按成员搜索
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

    # ── SELECT 模糊匹配（与 create_entity 同范式）──
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

    # ── 获取跟进记录表单配置（全局，不分模块）──
    def get_form_fields():
        resp = api("GET", "/follow/record/module/form")
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
            "type": RECORD_TYPE[module],
            id_field: source_id,
            "content": content,
            "moduleFields": [],
        }
        # 商机跟进可带归属客户
        if module == "opportunity" and (p.get("customerId") or p.get("客户ID")):
            body["customerId"] = p.get("customerId") or p.get("客户ID")

        # 跟进人
        owner_in = p.get("owner") or p.get("跟进人") or ""
        body["owner"] = resolve_owner(owner_in)

        # 跟进时间
        ft = p.get("followTime") or p.get("跟进时间") or ""
        if isinstance(ft, str) and ft:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    ft = int(time.mktime(datetime.strptime(ft, fmt).timetuple()) * 1000)
                    break
                except ValueError:
                    continue
        body["followTime"] = ft if isinstance(ft, int) and ft else int(time.time() * 1000)

        # 跟进方式 label→value
        method_in = p.get("followMethod") or p.get("跟进方式") or ""
        if method_in:
            mfield = next((f for f in fields if f["businessKey"] == "followMethod"), None)
            l2v = mfield["label_to_value"] if mfield else {}
            mv = ""
            if str(method_in) in l2v.values():
                mv = str(method_in)  # 已是 value
            else:
                label = METHOD_ALIAS.get(str(method_in), str(method_in))
                mv = l2v.get(label) or _fuzzy_match(label, l2v) or ""
            if mv:
                body["followMethod"] = mv

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

    # 失败时重取表单重试一次（与 create_entity 同范式）
    if result.get("code") != 100200:
        msg = (str(result.get("message", "")) + str(result.get("messageDetail", ""))).lower()
        if "field" in msg or "invalid" in msg or "parameter" in msg:
            fields = get_form_fields() or []
            body = build_body(fields)
            result = api("POST", add_api, body)

    return json.dumps(result, ensure_ascii=False)



