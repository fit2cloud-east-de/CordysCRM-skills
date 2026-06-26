import json
import re
import time
import unicodedata
from datetime import datetime
from urllib import request
from urllib.error import HTTPError, URLError


def create_entity(domain, access_key, secret_key, params=""):
    """
    Cordys CRM 创建工具 — 支持创建线索、客户、商机、联系人。

    自动完成：产品名称→ID转换、SELECT字段label→value转换、表单配置获取、请求体构建。

    Args:
        domain: CRM 域名，如 https://www.cordys.cn
        access_key: 用户的 X-Access-Key
        secret_key: 用户的 X-Secret-Key
        params: JSON 字符串，如 {"module":"lead","公司":"千里眼科技","姓名":"李老师","手机":"13777788888","产品类型（可多选）":["MeterSphere 企业版"],"区域":"东区","行业":"高科技和互联网","线索来源":"线上","线上来源详情":"400电话","是否已拜访":"否","省市":"3301-"}
            注：省市为 LOCATION 字段，传行政代码（省-市-区，缺级留空），如杭州市为 "3301-"；名称→代码用 `cordys_ext.sh loc <名称>` 查询。工具不做名称转换，须传代码。

    Returns:
        JSON 字符串，包含 code、data 或 error
    """

    try:
        p = json.loads(params) if isinstance(params, str) else params or {}
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "params JSON 解析失败"}, ensure_ascii=False)

    module = p.pop("module", "")
    if module not in ("lead", "account", "opportunity", "contact"):
        return json.dumps({"error": "module 必须为 lead/account/opportunity/contact"}, ensure_ascii=False)

    ENTITY_CONFIG = {
        "lead": {"type": "CLUE", "form_path": "/lead/module/form", "api": "/lead/add"},
        "account": {"type": "ACCOUNT", "form_path": "/account/module/form", "api": "/account/add"},
        "opportunity": {"type": "OPPORTUNITY", "form_path": "/opportunity/module/form", "api": "/opportunity/add"},
        "contact": {"type": "CONTACT", "form_path": "/module/form/config/contact", "api": "/account/contact/add"},
    }

    TOP_LEVEL_BIZ_KEYS = {"name", "contact", "phone", "owner", "products",
                          "customerId", "contactId", "amount", "expectedEndTime", "possible"}
    NUMERIC_BIZ_KEYS = {"amount", "possible"}
    TIMESTAMP_BIZ_KEYS = {"expectedEndTime"}

    cfg = ENTITY_CONFIG[module]

    # ── API helpers ──

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

    # ── 产品名→ID ──

    def get_product_map():
        r = api("POST", "/field/source/product", {"current": 1, "pageSize": 200, "keyword": ""})
        if r.get("code") != 100200:
            return {}
        return {item["name"]: item["id"] for item in r.get("data", {}).get("list", [])}

    def resolve_products(products):
        if not products:
            return []
        pm = get_product_map()
        return [pm.get(name, name) for name in products]

    # ── SELECT 模糊匹配 ──

    _ZERO_WIDTH_RE = re.compile(r'[​-‏ - ⁠﻿]')

    def _normalize(s):
        return _ZERO_WIDTH_RE.sub('', unicodedata.normalize('NFKC', s)).strip()

    def _fuzzy_match(value, label_to_value):
        nv = _normalize(value)
        for label, mapped in label_to_value.items():
            nl = _normalize(label)
            if nl == nv:
                return mapped
            if nl.startswith(nv) and len(nv) >= 2:
                return mapped
        return None

    # ── 获取表单配置 ──

    def get_form_fields():
        resp = api("GET", cfg["form_path"])
        if resp.get("code") != 100200:
            return None
        fields = []
        for f in resp["data"]["fields"]:
            if f["type"] == "DIVIDER":
                continue
            label_to_value = {o["label"]: o["value"] for o in (f.get("options") or [])}
            is_unique = any(r.get("key") == "unique" for r in (f.get("rules") or []))
            fields.append({
                "id": f["id"], "name": f["name"],
                "key": f.get("internalKey") or "",
                "businessKey": f.get("businessKey") or "",
                "type": f["type"],
                "label_to_value": label_to_value,
                "unique": is_unique,
            })
        return fields

    # ── 构建请求体 ──

    def build_body(fields):
        body = {"type": cfg["type"], "id": "", "moduleFields": []}
        for bk in TOP_LEVEL_BIZ_KEYS:
            body[bk] = ""

        for f in fields:
            bk = f["businessKey"]
            if bk and bk in TOP_LEVEL_BIZ_KEYS:
                value = None
                for lookup in [bk, f["key"], f["name"]]:
                    if lookup and lookup in p:
                        value = p[lookup]
                        break
                # fallback: 括号全角/半角不一致时，按字段名前缀模糊匹配
                if value is None and f["name"]:
                    prefix = f["name"].split("(")[0].split("（")[0]
                    for pk in p:
                        if pk.startswith(prefix) and pk != "module":
                            value = p[pk]
                            break
                if value is None:
                    value = ""
                if bk == "products":
                    if isinstance(value, str) and value:
                        value = [value]
                    elif not isinstance(value, list):
                        value = []
                    body[bk] = resolve_products(value)
                elif bk in TIMESTAMP_BIZ_KEYS:
                    if isinstance(value, str) and value:
                        try:
                            value = int(time.mktime(datetime.strptime(value, "%Y-%m-%d").timetuple()) * 1000)
                        except ValueError:
                            pass
                    body[bk] = value if value != "" else None
                elif bk in NUMERIC_BIZ_KEYS:
                    if isinstance(value, str) and value:
                        try:
                            value = int(float(value))
                        except ValueError:
                            pass
                    body[bk] = value if value != "" else None
                elif isinstance(value, list):
                    body[bk] = value
                else:
                    body[bk] = str(value) if value != "" else ""

        for f in fields:
            if f["businessKey"] in TOP_LEVEL_BIZ_KEYS:
                continue
            value = None
            for lookup in [f["key"], f["name"]]:
                if lookup and lookup in p:
                    value = p[lookup]
                    break
            # fallback: 括号全角/半角不一致时，按字段名前缀模糊匹配
            if value is None and f["name"]:
                prefix = f["name"].split("(")[0].split("（")[0]
                for pk in p:
                    if pk.startswith(prefix) and pk != "module":
                        value = p[pk]
                        break
            if value is None:
                value = ""
            if isinstance(value, list):
                value = ",".join(str(v) for v in value)
            # 产品类型字段：名称→ID 转换
            if "产品" in f["name"] and f["type"] == "DATA_SOURCE" and str(value):
                pm = get_product_map()
                parts = [v.strip() for v in str(value).split(",")]
                resolved = [pm.get(name, name) for name in parts]
                value = ",".join(resolved)
            elif f.get("label_to_value") and str(value) in f["label_to_value"]:
                value = f["label_to_value"][str(value)]
            elif f.get("label_to_value") and str(value):
                value = _fuzzy_match(str(value), f["label_to_value"]) or value
            if f["type"] in ("INPUT_NUMBER", "DATE_TIME") and value == "":
                continue
            if f["type"] == "INPUT_NUMBER" and value != "":
                try:
                    body["moduleFields"].append({"fieldId": f["id"], "fieldValue": float(value)})
                except (ValueError, TypeError):
                    body["moduleFields"].append({"fieldId": f["id"], "fieldValue": str(value)})
            else:
                body["moduleFields"].append({"fieldId": f["id"], "fieldValue": str(value)})

        for k in [k for k in body if body[k] == "" and k not in ("type", "id", "moduleFields")]:
            del body[k]
        return body

    # ── 执行 ──

    fields = get_form_fields()
    if fields is None:
        return json.dumps({"error": "获取表单配置失败"}, ensure_ascii=False)

    # ── 字段唯一性查重 ──

    FORM_KEY_MAP = {"lead": "clue", "account": "customer", "opportunity": "business", "contact": "contact"}
    form_key = FORM_KEY_MAP.get(module, module)
    for f in fields:
        if not f["unique"]:
            continue
        value = None
        for lookup in [f["businessKey"], f["key"], f["name"]]:
            if lookup and lookup in p:
                value = p[lookup]
                break
        if not value:
            continue
        check_resp = api("POST", "/field/check/repeat", {"id": f["id"], "value": value, "formKey": form_key})
        if check_resp.get("code") == 100200 and check_resp.get("data", {}).get("repeat"):
            dup_name = check_resp["data"].get("name", "")
            return json.dumps({"error": f"字段「{f['name']}」值「{value}」已存在（重复记录：{dup_name}），无法创建"}, ensure_ascii=False)

    body = build_body(fields)
    result = api("POST", cfg["api"], body)

    if result.get("code") != 100200:
        msg = str(result.get("message", "")) + str(result.get("messageDetail", ""))
        if "field" in msg.lower() or "invalid" in msg.lower() or "parameter" in msg.lower():
            fields = get_form_fields()
            if fields:
                body = build_body(fields)
                result = api("POST", cfg["api"], body)

    return json.dumps(result, ensure_ascii=False)
