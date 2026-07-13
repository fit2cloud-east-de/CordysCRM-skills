import json
import re
import time
import unicodedata
from urllib import request
from urllib.error import HTTPError, URLError

from time_boundary import TimeBoundaryError, parse_date_ms


def transform_lead(domain, access_key, secret_key, params=""):
    """
    Cordys CRM 线索转换工具 — 将线索转为客户+联系人，可选同时创建商机并补全商机字段。

    转换后自动补充联系人的电话、电子邮件字段。
    如果 params 中包含商机相关字段（金额、结束日期、签约类型等），转换成功后自动补全商机。

    Args:
        domain: CRM 域名，如 https://www.cordys.cn
        access_key: 用户的 X-Access-Key
        secret_key: 用户的 X-Secret-Key
        params: JSON 字符串，如 {"clueId":"xxx","oppName":"商机名","contactName":"李老师","phone":"13800138000","金额":50000,"结束日期":"2026-08-30","签约类型":"飞致云直签","最终用户工商全称":"xxx公司","报备号/代签方名称":"无"}

    Returns:
        JSON 字符串，包含 code、data 或 error
    """

    try:
        p = json.loads(params) if isinstance(params, str) else params or {}
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "params JSON 解析失败"}, ensure_ascii=False)

    clue_id = p.get("clueId", "")
    if not clue_id:
        return json.dumps({"error": "clueId 为必填参数"}, ensure_ascii=False)

    opp_name = p.get("oppName", "")

    # 商机补全字段（从 params 中提取，不属于 transform API 本身的参数）
    TRANSFORM_KEYS = {
        "clueId", "oppName", "oppCreated", "contactName", "phone", "电话", "电子邮件", "类型"
    }
    opportunity_field_aliases = {
        "最终用户全称（工商可查）": "最终用户工商全称",
    }
    opp_extra = {}
    for key, value in p.items():
        if key in TRANSFORM_KEYS or not value:
            continue
        canonical_key = opportunity_field_aliases.get(key, key)
        # 新字段名优先；旧调用仍可通过别名兼容。
        if canonical_key not in opp_extra or key == canonical_key:
            opp_extra[canonical_key] = value

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
        except HTTPError as e:
            try:
                body = e.read().decode(e.headers.get_content_charset() or "utf-8")
                return json.loads(body)
            except Exception:
                return {"code": 0, "message": f"HTTP {e.code}: {e.reason}"}
        except URLError as e:
            return {"code": 0, "message": str(e)}

    # ── 产品名→ID ──

    def get_product_map():
        r = api("POST", "/field/source/product", {"current": 1, "pageSize": 200, "keyword": ""})
        if r.get("code") != 100200:
            return {}
        return {item["name"]: item["id"] for item in r.get("data", {}).get("list", [])}

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

    # 1. 执行转换
    body = {"clueId": clue_id, "oppName": opp_name, "oppCreated": p.get("oppCreated", bool(opp_name))}
    result = api("POST", "/lead/transform", body)
    if result.get("code") != 100200:
        return json.dumps(result, ensure_ascii=False)

    def opportunity_completion_error(message, detail=None):
        error = {
            "code": 0,
            "error": message,
            "partialSuccess": True,
            "transformCompleted": True,
            "retryTransform": False,
            "transformResult": result,
        }
        if detail is not None:
            error["detail"] = detail
        return json.dumps(error, ensure_ascii=False)

    # 2. 补充联系人字段（电话、电子邮件）
    contact_extra_names = ("电话", "电子邮件")
    contact_extra = {name: p.get(name) for name in contact_extra_names if p.get(name)}

    if contact_extra and p.get("contactName"):
        form_resp = api("GET", "/module/form/config/contact")
        if form_resp.get("code") == 100200:
            field_name_to_id = {}
            for f in form_resp["data"]["fields"]:
                if f["name"] in contact_extra:
                    field_name_to_id[f["name"]] = f["id"]

            extra_fields = [{"fieldId": field_name_to_id[name], "fieldValue": val}
                           for name, val in contact_extra.items() if name in field_name_to_id]

            if extra_fields:
                keyword = p.get("phone") or p.get("contactName")
                resp = api("POST", "/global/search/contact", {"keyword": keyword, "pageSize": 5, "current": 1})
                for c in resp.get("data", {}).get("list", []):
                    if c.get("name") == p["contactName"]:
                        api("POST", "/account/contact/update", {
                            "id": c["id"],
                            "customerId": c.get("customerId", ""),
                            "moduleFields": extra_fields
                        })
                        break

    # 2.5 补全客户"类型"字段
    customer_type = p.get("类型", "最终客户")
    type_map = {"最终客户": "Customer", "合作伙伴": "Partner"}
    type_val = type_map.get(customer_type, customer_type)

    # 通过联系人手机号找到关联客户
    cust_id = ""
    cust_name = ""
    cust_owner = ""
    if p.get("phone"):
        cr = api("POST", "/global/search/contact", {"keyword": p["phone"], "pageSize": 5, "current": 1})
        for c in cr.get("data", {}).get("list", []):
            if c.get("name") == p.get("contactName"):
                cust_id = c.get("customerId", "")
                cust_name = c.get("customerName", "")
                cust_owner = c.get("owner", "")
                break

    if cust_id:
        # 获取已有 moduleFields
        cust_page = api("POST", "/account/page", {"current": 1, "pageSize": 1, "keyword": cust_name, "viewId": "ALL"})
        cust_fields = {}
        for cp in cust_page.get("data", {}).get("list", []):
            if cp.get("id") == cust_id:
                for mf in cp.get("moduleFields", []):
                    cust_fields[mf["fieldId"]] = mf["fieldValue"]
                break
        cust_fields["1751888184000007"] = type_val
        api("POST", "/account/update", {
            "type": "CUSTOMER",
            "id": cust_id,
            "customerId": "",
            "name": cust_name,
            "owner": cust_owner,
            "moduleFields": [{"fieldId": k, "fieldValue": v} for k, v in cust_fields.items()]
        })

    # 3. 补全商机字段（如果有 oppName 且有额外字段）
    if opp_name and opp_extra:
        # 等待商机创建完成后搜索
        opp_item = None
        for attempt in range(3):
            time.sleep(2)
            resp = api("POST", "/global/search/opportunity", {"keyword": opp_name, "pageSize": 5, "current": 1})
            for item in resp.get("data", {}).get("list", []):
                if item.get("name") == opp_name:
                    opp_item = item
                    break
            if opp_item:
                break

        if not opp_item:
            return opportunity_completion_error(
                "线索已转化，但未定位到新商机，商机字段尚未补全；禁止重复转化，请先查询商机后执行更新"
            )

        # 获取当前商机完整 moduleFields（避免更新时清空已有字段）
        page_resp = api("POST", "/opportunity/page", {
            "current": 1, "pageSize": 1, "keyword": opp_name, "viewId": "ALL"
        })
        if page_resp.get("code") != 100200:
            return opportunity_completion_error("线索已转化，但读取新商机完整字段失败", page_resp)

        existing_fields = {}
        page_item_found = False
        for pg_item in page_resp.get("data", {}).get("list", []):
            if pg_item.get("id") == opp_item["id"]:
                page_item_found = True
                for mf in pg_item.get("moduleFields", []):
                    existing_fields[mf["fieldId"]] = mf["fieldValue"]
                break
        if not page_item_found:
            return opportunity_completion_error("线索已转化，但未读取到新商机完整记录，已中止字段更新")

        form_resp = api("GET", "/opportunity/module/form")
        if form_resp.get("code") != 100200:
            return opportunity_completion_error("线索已转化，但读取商机表单失败", form_resp)

        fields = form_resp.get("data", {}).get("fields", [])
        if not fields:
            return opportunity_completion_error("线索已转化，但商机表单未返回字段定义")

        new_values = {}
        matched_keys = set()
        top_level_keys = {"金额", "结束日期"}

        for f in fields:
            if f["type"] == "DIVIDER":
                continue
            bk = f.get("businessKey", "")
            if bk:
                continue
            value = None
            matched_key = None
            for lookup in [f.get("internalKey", ""), f["name"]]:
                if lookup and lookup in opp_extra:
                    value = opp_extra[lookup]
                    matched_key = lookup
                    break
            if value is None:
                continue
            matched_keys.add(matched_key)

            label_to_value = {o["label"]: o["value"] for o in (f.get("options") or [])}
            if label_to_value and isinstance(value, str):
                if value in label_to_value:
                    value = label_to_value[value]
                else:
                    matched = _fuzzy_match(value, label_to_value)
                    if matched:
                        value = matched

            if f["type"] == "INPUT_NUMBER" and value != "":
                try:
                    new_values[f["id"]] = float(value)
                except (ValueError, TypeError):
                    return opportunity_completion_error(
                        f"线索已转化，但商机字段「{matched_key}」不是有效数字"
                    )
            else:
                new_values[f["id"]] = value if not isinstance(value, str) else str(value)

        unmatched_keys = sorted(set(opp_extra) - top_level_keys - matched_keys)
        if unmatched_keys:
            return opportunity_completion_error(
                "线索已转化，但以下商机字段未在表单中匹配，尚未执行商机更新",
                {"unmatchedFields": unmatched_keys},
            )

        # 合并：已有字段 + 新值覆盖
        existing_fields.update(new_values)
        module_fields = [{"fieldId": k, "fieldValue": v} for k, v in existing_fields.items()]

        # products 需要转成 ID
        product_ids = opp_item.get("products", [])
        if product_ids and not all(str(product).isdigit() for product in product_ids):
            pm = get_product_map()
            product_ids = [pm.get(name, name) for name in product_ids]

        update_body = {
            "type": "BUSINESS",
            "id": opp_item["id"],
            "opportunityId": "",
            "name": opp_name,
            "owner": opp_item.get("owner", ""),
            "customerId": opp_item.get("customerId", ""),
            "contactId": opp_item.get("contactId", ""),
            "products": product_ids,
            "possible": "",
            "moduleFields": module_fields
        }
        val = opp_extra.get("结束日期", "")
        if val:
            try:
                update_body["expectedEndTime"] = parse_date_ms(val)
            except (TimeBoundaryError, TypeError):
                return opportunity_completion_error("线索已转化，但商机结束日期格式无效，应为 YYYY-MM-DD")
        val = opp_extra.get("金额", "")
        if val:
            try:
                update_body["amount"] = int(float(val))
            except (ValueError, TypeError):
                return opportunity_completion_error("线索已转化，但商机金额不是有效数字")

        update_result = api("POST", "/opportunity/update", update_body)
        if update_result.get("code") != 100200:
            return opportunity_completion_error("线索已转化，但补全商机字段失败", update_result)

    return json.dumps(result, ensure_ascii=False)
