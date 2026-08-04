import json
import re
import time
import unicodedata
from urllib import request
from urllib.error import HTTPError, URLError

from time_boundary import TimeBoundaryError, parse_datetime_ms


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

    raw_follow_time = p.get("followTime") or p.get("跟进时间") or ""
    parsed_follow_time = None
    if isinstance(raw_follow_time, str) and raw_follow_time:
        try:
            parsed_follow_time = parse_datetime_ms(raw_follow_time)
        except TimeBoundaryError:
            return json.dumps({
                "error": "跟进时间格式无效：请传 YYYY-MM-DD HH:MM、YYYY-MM-DD HH:MM:SS 或毫秒时间戳；未创建跟进记录"
            }, ensure_ascii=False)
    elif isinstance(raw_follow_time, int) and not isinstance(raw_follow_time, bool) and raw_follow_time:
        parsed_follow_time = raw_follow_time
    elif raw_follow_time not in ("", None):
        return json.dumps({"error": "跟进时间格式无效；未创建跟进记录"}, ensure_ascii=False)

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
        body["followTime"] = parsed_follow_time or int(time.time() * 1000)

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


def update_follow_record(domain, access_key, secret_key, params=""):
    """更新一条已存在的跟进记录；更新前读取详情并补齐完整请求体。"""
    return _update_follow_entry("record", domain, access_key, secret_key, params)


def _update_follow_entry(kind, domain, access_key, secret_key, params=""):
    """跟进记录/计划更新公共实现。更新接口不是 PATCH，必须先取详情再合并。"""
    labels = {
        "record": {
            "name": "跟进记录",
            "time": "followTime",
            "time_aliases": ("followTime", "跟进时间"),
            "method": "followMethod",
            "method_aliases": ("followMethod", "跟进方式"),
            "content_aliases": ("content", "跟进内容"),
            "form": "/follow/record/module/form",
            "id_aliases": ("recordId", "followRecordId", "id"),
        },
        "plan": {
            "name": "跟进计划",
            "time": "estimatedTime",
            "time_aliases": ("estimatedTime", "计划时间", "planTime", "followTime", "跟进时间"),
            "method": "method",
            "method_aliases": ("method", "followMethod", "跟进方式"),
            "content_aliases": ("content", "计划内容", "跟进内容"),
            "form": "/follow/plan/module/form",
            "id_aliases": ("planId", "followPlanId", "id"),
        },
    }
    if kind not in labels:
        return json.dumps({"error": "跟进更新类型无效；未执行更新"}, ensure_ascii=False)
    contract = labels[kind]
    entry_name = contract["name"]

    try:
        raw_params = json.loads(params) if isinstance(params, str) else params or {}
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "params JSON 解析失败；未执行更新"}, ensure_ascii=False)
    if not isinstance(raw_params, dict):
        return json.dumps({"error": "params 必须是 JSON 对象；未执行更新"}, ensure_ascii=False)
    p = dict(raw_params)

    module = str(p.get("module") or "").strip()
    if module not in ("lead", "account", "opportunity"):
        return json.dumps({"error": "module 必须为 lead/account/opportunity；未执行更新"}, ensure_ascii=False)

    def first_present(keys):
        for key in keys:
            if key in p:
                return True, p[key]
        return False, None

    _, raw_entry_id = first_present(contract["id_aliases"])
    entry_id = str(raw_entry_id or "").strip()
    if not entry_id or not re.fullmatch(r"\d+", entry_id):
        aliases = " / ".join(contract["id_aliases"])
        return json.dumps({"error": f"缺少合法的{entry_name} ID（{aliases}）；未执行更新"}, ensure_ascii=False)

    if "status" in p:
        return json.dumps({
            "error": f"{entry_name}状态不属于字段更新接口；本次未执行更新"
        }, ensure_ascii=False)
    if "converted" in p:
        return json.dumps({
            "error": f"converted 是系统状态字段，不允许通过{entry_name}更新命令修改；本次未执行更新"
        }, ensure_ascii=False)

    content_present, raw_content = first_present(contract["content_aliases"])
    time_present, raw_time = first_present(contract["time_aliases"])
    method_present, raw_method = first_present(contract["method_aliases"])
    owner_present, raw_owner = first_present(("owner", "跟进人"))
    contact_present, raw_contact = first_present(("contactId", "联系人ID"))
    products_present, raw_products = first_present(("products", "意向产品", "产品"))
    module_fields_present = "moduleFields" in p

    if products_present and module_fields_present:
        return json.dumps({
            "error": "意向产品与 moduleFields 不能同时更新；请只选择一种写法，本次未执行更新"
        }, ensure_ascii=False)

    identity_keys = ("type", "clueId", "customerId", "opportunityId")
    identity_present = any(key in p for key in identity_keys)
    if not any((content_present, time_present, method_present, owner_present,
                contact_present, products_present, module_fields_present, identity_present)):
        return json.dumps({
            "error": f"未提供可更新的{entry_name}字段；本次未执行更新"
        }, ensure_ascii=False)

    if content_present and (not isinstance(raw_content, str) or not raw_content.strip()):
        return json.dumps({
            "error": f"{entry_name}内容必须是非空文本；本次未执行更新"
        }, ensure_ascii=False)

    def parse_update_time(value):
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
        if not 100_000_000_000 <= parsed <= 9_999_999_999_999:
            return None
        return parsed

    parsed_time = None
    if time_present:
        parsed_time = parse_update_time(raw_time)
        if parsed_time is None:
            return json.dumps({
                "error": f"{entry_name}时间格式无效：请传 YYYY-MM-DD HH:MM、YYYY-MM-DD HH:MM:SS 或毫秒时间戳；本次未执行更新"
            }, ensure_ascii=False)

    if method_present and (raw_method is None or not str(raw_method).strip()):
        return json.dumps({
            "error": f"{entry_name}跟进方式不能为空；本次未执行更新"
        }, ensure_ascii=False)
    if owner_present and (raw_owner is None or not str(raw_owner).strip()):
        return json.dumps({
            "error": f"{entry_name}跟进人不能为空；本次未执行更新"
        }, ensure_ascii=False)
    if module_fields_present and not isinstance(p.get("moduleFields"), list):
        return json.dumps({
            "error": "moduleFields 必须是 JSON 数组；本次未执行更新"
        }, ensure_ascii=False)

    domain = str(domain or "").rstrip("/")

    def api(method, path, data=None):
        url = f"{domain}{path}"
        headers = {
            "X-Access-Key": access_key,
            "X-Secret-Key": secret_key,
            "X-Request-Source": "SKILL",
            "Content-Type": "application/json;charset=UTF-8",
        }
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
        req = request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode(resp.headers.get_content_charset() or "utf-8"))
        except HTTPError as exc:
            try:
                response_body = exc.read().decode(exc.headers.get_content_charset() or "utf-8")
                return json.loads(response_body)
            except Exception:
                return {"code": 0, "message": f"HTTP {exc.code}: {exc.reason}"}
        except (URLError, TimeoutError, OSError) as exc:
            return {"code": 0, "message": str(exc)}

    def unwrap_detail(response):
        if not isinstance(response, dict):
            return None
        if "code" in response:
            if str(response.get("code")) != "100200" or not isinstance(response.get("data"), dict):
                return None
            return response["data"]
        if str(response.get("id") or "") == entry_id:
            return response
        return None

    detail_path = f"/{module}/follow/{kind}/get/{entry_id}"
    update_path = f"/{module}/follow/{kind}/update"
    detail_response = api("GET", detail_path)
    detail = unwrap_detail(detail_response)
    if detail is None:
        return json.dumps({
            "code": detail_response.get("code", 0) if isinstance(detail_response, dict) else 0,
            "error": f"读取{entry_name}详情失败；未执行更新",
            "detailResponse": detail_response,
            "notUpdated": True,
        }, ensure_ascii=False)
    if str(detail.get("id") or "") != entry_id:
        return json.dumps({
            "error": f"{entry_name}详情 ID 与目标 ID 不一致；未执行更新",
            "notUpdated": True,
        }, ensure_ascii=False)

    def clean_module_fields(value):
        cleaned = []
        for item in value or []:
            if not isinstance(item, dict) or not item.get("fieldId"):
                continue
            cleaned.append({"fieldId": str(item["fieldId"]), "fieldValue": item.get("fieldValue")})
        return cleaned

    body_keys = (
        "id", "customerId", "opportunityId", "type", "clueId", "content",
        contract["time"], contract["method"], "owner", "contactId",
    )
    body = {}
    for key in body_keys:
        if key in detail and detail[key] is not None:
            body[key] = detail[key]
    body["id"] = entry_id
    body["moduleFields"] = clean_module_fields(detail.get("moduleFields"))
    if kind == "plan" and isinstance(detail.get("converted"), bool):
        body["converted"] = detail["converted"]

    for key in identity_keys:
        if key not in p:
            continue
        requested = "" if p[key] is None else str(p[key]).strip()
        current = "" if detail.get(key) is None else str(detail.get(key)).strip()
        if requested != current:
            return json.dumps({
                "error": f"{key} 是{entry_name}归属字段，不能在编辑时改绑；本次未执行更新"
            }, ensure_ascii=False)

    form_fields_cache = None

    def get_form_fields():
        nonlocal form_fields_cache
        if form_fields_cache is not None:
            return form_fields_cache
        response = api("GET", contract["form"])
        fields = []
        if str(response.get("code")) == "100200" and isinstance(response.get("data"), dict):
            for field in response["data"].get("fields") or []:
                if field.get("type") == "DIVIDER":
                    continue
                fields.append({
                    "id": str(field.get("id") or ""),
                    "businessKey": field.get("businessKey") or "",
                    "type": field.get("type") or "",
                    "label_to_value": {
                        str(option.get("label")): str(option.get("value"))
                        for option in (field.get("options") or [])
                        if option.get("label") is not None and option.get("value") is not None
                    },
                })
        form_fields_cache = fields
        return form_fields_cache

    zero_width_re = re.compile(r"[​-‏‪-‮⁠﻿]")

    def normalize_text(value):
        return zero_width_re.sub("", unicodedata.normalize("NFKC", str(value))).strip()

    def fuzzy_match(value, label_to_value):
        normalized = normalize_text(value)
        for label, mapped in label_to_value.items():
            normalized_label = normalize_text(label)
            if normalized_label == normalized:
                return mapped
            if normalized_label.startswith(normalized) and len(normalized) >= 2:
                return mapped
        return None

    method_alias = {
        "拜访": "到访", "上门": "到访", "面谈": "到访", "当面": "到访",
        "电话": "电话", "打电话": "电话",
        "微信": "微信", "企业微信": "微信",
        "邮件": "邮件", "邮箱": "邮件", "email": "邮件",
        "线上会议": "线上会议", "视频": "线上会议", "会议": "线上会议", "腾讯会议": "线上会议",
    }

    def resolve_method(value):
        raw_value = str(value).strip()
        fields = get_form_fields()
        method_field = next((field for field in fields if field["businessKey"] == contract["method"]), None)
        label_to_value = method_field["label_to_value"] if method_field else {}
        if raw_value in label_to_value.values():
            return raw_value
        if raw_value.isdigit():
            return raw_value
        label = method_alias.get(raw_value, raw_value)
        return label_to_value.get(label) or fuzzy_match(label, label_to_value)

    me_cache = None

    def get_me():
        nonlocal me_cache
        if me_cache is None:
            response = api("GET", "/personal/center/info")
            me_cache = (
                response.get("data") or {}
                if str(response.get("code")) == "100200"
                else {}
            )
        return me_cache

    def resolve_owner(value):
        raw_value = str(value).strip()
        if raw_value.isdigit() and len(raw_value) >= 10:
            return raw_value
        me = get_me()
        if raw_value in (str(me.get("userName") or ""), str(me.get("name") or "")):
            return str(me.get("userId") or "") or None
        response = api("POST", "/user/list", {"current": 1, "pageSize": 20, "keyword": raw_value})
        if str(response.get("code")) == "100200":
            matches = []
            for user in (response.get("data") or {}).get("list") or []:
                if raw_value in (str(user.get("name") or ""), str(user.get("userName") or "")):
                    user_id = user.get("userId") or user.get("id")
                    if user_id:
                        matches.append(str(user_id))
            if len(set(matches)) == 1:
                return matches[0]
        return None

    def resolve_products(value):
        if value is None:
            values = []
        elif isinstance(value, str):
            values = [value] if value.strip() else []
        elif isinstance(value, list):
            values = value
        else:
            return None, ["意向产品必须是字符串或数组"]
        if not any(str(item).strip() for item in values):
            return [], []
        response = api("POST", "/field/source/product", {"current": 1, "pageSize": 200, "keyword": ""})
        if str(response.get("code")) != "100200":
            return None, ["无法读取产品目录"]
        product_map = {
            str(item.get("name")): str(item.get("id"))
            for item in (response.get("data") or {}).get("list") or []
            if item.get("name") is not None and item.get("id") is not None
        }
        resolved = []
        unknown = []
        for value_item in values:
            normalized = str(value_item).strip()
            if not normalized:
                continue
            if normalized.isdigit():
                resolved.append(normalized)
            elif normalized in product_map:
                resolved.append(product_map[normalized])
            else:
                unknown.append(normalized)
        return resolved, unknown

    expected_changes = {}
    if content_present:
        body["content"] = raw_content.strip()
        expected_changes["content"] = body["content"]
    if time_present:
        body[contract["time"]] = parsed_time
        expected_changes[contract["time"]] = parsed_time
    if method_present:
        resolved_method = resolve_method(raw_method)
        if not resolved_method:
            return json.dumps({
                "error": f"无法识别{entry_name}跟进方式；请使用表单中的中文标签或选项 ID，本次未执行更新"
            }, ensure_ascii=False)
        body[contract["method"]] = resolved_method
        expected_changes[contract["method"]] = resolved_method
    if owner_present:
        resolved_owner = resolve_owner(raw_owner)
        if not resolved_owner:
            return json.dumps({
                "error": f"无法把跟进人精确解析为唯一 userId；本次未执行{entry_name}更新"
            }, ensure_ascii=False)
        body["owner"] = resolved_owner
        expected_changes["owner"] = resolved_owner
    if contact_present:
        body["contactId"] = "" if raw_contact is None else str(raw_contact).strip()
        expected_changes["contactId"] = body["contactId"]
    if module_fields_present:
        body["moduleFields"] = clean_module_fields(p.get("moduleFields"))
        expected_changes["moduleFields"] = body["moduleFields"]
    elif products_present:
        fields = get_form_fields()
        product_field = next((field for field in fields if field["type"] == "DATA_SOURCE_MULTIPLE" and field["id"]), None)
        if product_field is None:
            return json.dumps({
                "error": f"{entry_name}表单中未找到意向产品字段；本次未执行更新"
            }, ensure_ascii=False)
        product_ids, unknown_products = resolve_products(raw_products)
        if product_ids is None or unknown_products:
            reason = "、".join(unknown_products or ["无法读取产品目录"])
            return json.dumps({
                "error": f"无法解析意向产品：{reason}；本次未执行更新"
            }, ensure_ascii=False)
        module_field_map = {
            item["fieldId"]: item.get("fieldValue") for item in clean_module_fields(body.get("moduleFields"))
        }
        module_field_map[product_field["id"]] = product_ids
        body["moduleFields"] = [
            {"fieldId": field_id, "fieldValue": field_value}
            for field_id, field_value in module_field_map.items()
        ]
        expected_changes["moduleFields"] = body["moduleFields"]

    required = ("id", "content", contract["method"], "owner", "type")
    missing_required = [key for key in required if body.get(key) in (None, "")]
    if missing_required:
        return json.dumps({
            "error": f"{entry_name}详情缺少更新接口必填字段：{', '.join(missing_required)}；未执行更新",
            "notUpdated": True,
        }, ensure_ascii=False)

    def normalize_value(key, value):
        if key == "moduleFields":
            normalized = {}
            for item in clean_module_fields(value):
                field_value = item.get("fieldValue")
                if isinstance(field_value, list):
                    field_value = sorted(str(part) for part in field_value)
                normalized[item["fieldId"]] = field_value
            return normalized
        if key in ("followTime", "estimatedTime"):
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
        if value is None:
            return ""
        return str(value) if not isinstance(value, bool) else value

    def changes_match(current):
        return all(
            normalize_value(key, current.get(key)) == normalize_value(key, expected)
            for key, expected in expected_changes.items()
        )

    if changes_match(detail):
        return json.dumps({
            "code": 100200,
            "data": detail,
            "noOp": True,
            "message": f"{entry_name}目标字段已经是请求值，未重复提交更新",
        }, ensure_ascii=False)

    result = api("POST", update_path, body)
    if isinstance(result, dict) and str(result.get("code")) == "100200":
        return json.dumps(result, ensure_ascii=False)

    verification_response = api("GET", detail_path)
    verified_detail = unwrap_detail(verification_response)
    if verified_detail is not None and changes_match(verified_detail):
        return json.dumps({
            "code": 100200,
            "data": verified_detail,
            "verifiedAfterFailure": True,
            "message": f"{entry_name}更新响应异常，但回读确认目标字段已更新",
            "originalResponse": result,
        }, ensure_ascii=False)

    failed = dict(result) if isinstance(result, dict) else {"code": 0, "message": str(result)}
    failed["verification"] = f"更新后回读未确认{entry_name}目标字段全部生效"
    failed["retryAllowed"] = False
    failed["messageHint"] = "禁止自动重试；请先向用户展示原始错误与回读结果"
    return json.dumps(failed, ensure_ascii=False)
