#!/usr/bin/env python3
"""
Cordys CRM 扩展 CLI — 查重、创建、转换、同步
"""
import json
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import cordys as _cordys


# ── 基础设施 ─────────────────────────────────────────────────────────────

def die(msg):
    _cordys.die(msg)


def api(method, path, data=None):
    url = f"{_cordys.CORDYS_CRM_DOMAIN}{path}"
    if data is not None:
        raw = _cordys.api(method, url,
                          data=json.dumps(data, ensure_ascii=False).encode("utf-8"))
    else:
        raw = _cordys.api(method, url)
    return json.loads(raw)


CACHE_DIR = SCRIPT_DIR / ".cache"
CACHE_TTL = 6 * 3600
REFERENCES_DIR = SCRIPT_DIR.parent / "references"


def _read_cache(cache_file):
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text("utf-8"))
            if time.time() - data.get("_ts", 0) < CACHE_TTL:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _write_cache(cache_file, data):
    CACHE_DIR.mkdir(exist_ok=True)
    data["_ts"] = time.time()
    cache_file.write_text(json.dumps(data, ensure_ascii=False), "utf-8")


# ── 表单配置 ─────────────────────────────────────────────────────────────

FORM_PATH_MAP = {
    "clue": "/lead/module/form",
    "lead": "/lead/module/form",
    "account": "/account/module/form",
    "opportunity": "/opportunity/module/form",
    "contact": "/module/form/config/contact",
}


def _fetch_form_from_api(form_key):
    path = FORM_PATH_MAP.get(form_key, f"/{form_key}/module/form")
    resp = api("GET", path)
    if resp.get("code") != 100200:
        return None
    fields = []
    for f in resp["data"]["fields"]:
        if f["type"] == "DIVIDER":
            continue
        label_to_value = {o["label"]: o["value"] for o in (f.get("options") or [])}
        required = any(r.get("key") == "required" for r in (f.get("rules") or []))
        fields.append({
            "id": f["id"], "name": f["name"],
            "key": f.get("internalKey") or "",
            "businessKey": f.get("businessKey") or "",
            "type": f["type"], "required": required,
            "label_to_value": label_to_value,
        })
    return fields


def get_form_config(form_key, force_refresh=False):
    cache_file = CACHE_DIR / f"form_{form_key}.json"
    if not force_refresh:
        cached = _read_cache(cache_file)
        if cached:
            return cached["fields"]
    fields = _fetch_form_from_api(form_key)
    if fields is None:
        cached = _read_cache(cache_file) if not force_refresh else None
        if cached:
            return cached["fields"]
        die(f"获取表单配置失败且无可用缓存: {form_key}")
    _write_cache(cache_file, {"fields": fields})
    return fields


# ── 产品映射 ─────────────────────────────────────────────────────────────

def get_product_map(force_refresh=False):
    cache_file = CACHE_DIR / "product_map.json"
    if not force_refresh:
        cached = _read_cache(cache_file)
        if cached:
            return cached["map"]
    resp = api("POST", "/field/source/product", {"current": 1, "pageSize": 200, "keyword": ""})
    if resp.get("code") != 100200:
        cached = _read_cache(cache_file) if not force_refresh else None
        return cached["map"] if cached else {}
    product_map = {item["name"]: item["id"] for item in resp["data"].get("list", [])}
    _write_cache(cache_file, {"map": product_map})
    return product_map


def _get_id_to_name():
    return {v: k for k, v in get_product_map().items()}


def resolve_products(products):
    if not products:
        return []
    product_map = get_product_map()
    return [product_map.get(p, p) for p in products]


# ── 标签模糊匹配 ─────────────────────────────────────────────────────────

_ZERO_WIDTH_RE = re.compile(r'[​-‏ - ⁠﻿]')


def _normalize(s):
    return _ZERO_WIDTH_RE.sub('', unicodedata.normalize('NFKC', s)).strip()


def _fuzzy_match_label(value, label_to_value):
    norm_value = _normalize(value)
    for label, mapped in label_to_value.items():
        norm_label = _normalize(label)
        if norm_label == norm_value:
            return mapped
        if norm_label.startswith(norm_value) and len(norm_value) >= 2:
            return mapped
    return None


# ── 创建 ─────────────────────────────────────────────────────────────────

TOP_LEVEL_BIZ_KEYS = {"name", "contact", "phone", "owner", "products",
                      "customerId", "contactId", "amount", "expectedEndTime", "possible"}
NUMERIC_BIZ_KEYS = {"amount", "possible"}
TIMESTAMP_BIZ_KEYS = {"expectedEndTime"}

ENTITY_CONFIG = {
    "lead": {"type": "CLUE", "form": "clue", "api": "/lead/add"},
    "account": {"type": "ACCOUNT", "form": "account", "api": "/account/add"},
    "opportunity": {"type": "OPPORTUNITY", "form": "opportunity", "api": "/opportunity/add"},
    "contact": {"type": "CONTACT", "form": "contact", "api": "/account/contact/add"},
}


def _build_body(cfg, fields, params):
    body = {"type": cfg["type"], "id": "", "moduleFields": []}
    for biz_key in TOP_LEVEL_BIZ_KEYS:
        body[biz_key] = ""

    for f in fields:
        bk = f["businessKey"]
        if bk and bk in TOP_LEVEL_BIZ_KEYS:
            value = None
            for lookup in [bk, f["key"], f["name"]]:
                if lookup and lookup in params:
                    value = params[lookup]
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
            if lookup and lookup in params:
                value = params[lookup]
                break
        if value is None:
            value = ""
        if isinstance(value, list):
            value = ",".join(str(v) for v in value)
        if f.get("label_to_value") and str(value) in f["label_to_value"]:
            value = f["label_to_value"][str(value)]
        elif f.get("label_to_value") and str(value):
            value = _fuzzy_match_label(str(value), f["label_to_value"]) or value
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


def create_entity(module, params):
    cfg = ENTITY_CONFIG.get(module)
    if not cfg:
        die(f"不支持的模块: {module}")
    fields = get_form_config(cfg["form"])
    body = _build_body(cfg, fields, params)
    result = api("POST", cfg["api"], body)
    if result.get("code") != 100200:
        msg = str(result.get("message", "")) + str(result.get("messageDetail", ""))
        if "field" in msg.lower() or "invalid" in msg.lower() or "parameter" in msg.lower():
            fields = get_form_config(cfg["form"], force_refresh=True)
            body = _build_body(cfg, fields, params)
            result = api("POST", cfg["api"], body)
    return result


# ── 转换 ─────────────────────────────────────────────────────────────────

def transform_lead(params):
    clue_id = params.get("clueId")
    if not clue_id:
        die("transform 需要 clueId")
    opp_name = params.get("oppName", "")
    body = {"clueId": clue_id, "oppName": opp_name, "oppCreated": params.get("oppCreated", bool(opp_name))}
    result = api("POST", "/lead/transform", body)
    if result.get("code") != 100200:
        return result
    fields = get_form_config("contact")
    field_name_to_id = {f["name"]: f["id"] for f in fields}
    extra_fields = []
    for name in ("电话", "电子邮件"):
        if params.get(name) and name in field_name_to_id:
            extra_fields.append({"fieldId": field_name_to_id[name], "fieldValue": params[name]})
    if extra_fields and params.get("contactName"):
        keyword = params.get("phone") or params.get("contactName")
        resp = api("POST", "/global/search/contact", {"keyword": keyword, "pageSize": 5, "current": 1})
        for c in resp.get("data", {}).get("list", []):
            if c.get("name") == params["contactName"]:
                api("POST", "/account/contact/update", {"id": c["id"], "customerId": c.get("customerId", ""), "moduleFields": extra_fields})
                break
    return result


# ── 查重 ─────────────────────────────────────────────────────────────────

CLOSED_STAGES = {"SUCCESS", "FAIL"}
PROTECTION_DAYS = 365
ZHEJIANG_GANSU_TEAMS = {"销售郝占魁组", "销售吴智胜团队", "销售杨丹璐团队", "销售施芳群团队"}


def _get_current_user():
    try:
        r = api("GET", "/personal/center/info")
        return r.get("data", {}).get("userName", "")
    except SystemExit:
        return ""


def _search(module, keyword):
    if not keyword:
        return []
    try:
        r = api("POST", f"/global/search/{module}", {"keyword": keyword, "pageSize": 100, "current": 1})
        return r.get("data", {}).get("list", [])
    except SystemExit:
        return []


def _merge(list_a, list_b):
    ids = {x["id"] for x in list_a if "id" in x}
    return list_a + [x for x in list_b if "id" in x and x["id"] not in ids]


def _rule1(leads, opportunities, products, current_user, blocks):
    if not products:
        return
    prod_set = set(products)
    for item in leads:
        if item.get("ownerName") == current_user:
            continue
        overlap = prod_set & set(item.get("products") or [])
        if overlap:
            blocks.append({"rule": 1, "type": "product_conflict",
                "message": f"{item.get('ownerName')}（{item.get('departmentName')}）的线索'{item.get('name')}'存在产品重复，重复产品：{'、'.join(overlap)}"})
    for item in opportunities:
        if item.get("stage") in CLOSED_STAGES or item.get("ownerName") == current_user:
            continue
        overlap = prod_set & set(item.get("products") or [])
        if overlap:
            blocks.append({"rule": 1, "type": "product_conflict",
                "message": f"{item.get('ownerName')}（{item.get('departmentName')}）的商机'{item.get('name')}'存在产品重复，重复产品：{'、'.join(overlap)}"})


def _search_success_opps(customer_name):
    if not customer_name:
        return []
    try:
        r = api("POST", "/opportunity/page", {
            "current": 1, "pageSize": 100, "keyword": customer_name, "viewId": "ALL",
            "combineSearch": {"searchMode": "AND", "conditions": [
                {"value": ["SUCCESS"], "operator": "IN", "name": "stage", "multipleValue": False, "type": "SELECT"}
            ]}})
        return r.get("data", {}).get("list", [])
    except SystemExit:
        return []


def _rule2(success_opps, products, current_user, blocks, warnings):
    win_times = {}
    id_to_name = _get_id_to_name()
    now_ms = time.time() * 1000
    for item in success_opps:
        win_times[item["id"]] = item.get("actualEndTime")
        if item.get("ownerName") == current_user:
            continue
        actual_end = item.get("actualEndTime")
        if not actual_end:
            continue
        protection_end = actual_end + PROTECTION_DAYS * 24 * 3600 * 1000
        if now_ms > protection_end:
            continue
        dept = item.get("departmentName", "")
        end_date = datetime.fromtimestamp(protection_end / 1000).strftime("%Y-%m-%d")
        if dept in ZHEJIANG_GANSU_TEAMS:
            item_product_names = {id_to_name.get(pid, pid) for pid in (item.get("products") or [])}
            if products:
                overlap = set(products) & item_product_names
                if overlap:
                    blocks.append({"rule": 2, "type": "protection_period",
                        "message": f"该客户在{item.get('ownerName')}（{dept}）名下有成单商机'{item.get('name')}'，保护期至{end_date}，保护范围：仅{'/'.join(overlap)}"})
            else:
                prods = '/'.join(item_product_names) if item_product_names else '未知'
                warnings.append({"rule": 2, "type": "protection_period",
                    "message": f"该客户在{item.get('ownerName')}（{dept}）名下有成单商机'{item.get('name')}'，保护期至{end_date}，保护产品：{prods}（浙赣团队仅保护成单产品）"})
        else:
            blocks.append({"rule": 2, "type": "protection_period",
                "message": f"该客户在{item.get('ownerName')}（{dept}）名下有成单商机'{item.get('name')}'，保护期至{end_date}，保护范围：全产品"})
    return win_times


def _rule3_judge(pool_leads_name, pool_leads_phone, pool_accounts, blocks, warnings):
    phone_ids = {x["id"] for x in pool_leads_phone}
    for item in pool_leads_phone:
        blocks.append({"rule": 3, "type": "pool_lead_phone",
            "message": f"线索池中存在手机号相同的线索'{item.get('name')}'，请捞回而非新建"})
    for item in pool_leads_name:
        if item["id"] not in phone_ids:
            warnings.append({"rule": 3, "type": "pool_lead_name",
                "message": f"线索池中存在'{item.get('name')}'，如需要可自行捞回"})
    for item in pool_accounts:
        warnings.append({"rule": 3, "type": "pool_account",
            "message": f"公海中存在客户'{item.get('name')}'，建议捞回后新建联系人"})


def _ts(ms):
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def _build_info(accounts, leads, opportunities, pool_leads_name, pool_leads_phone, pool_accounts, contacts, win_times):
    pool_all = list({x["id"]: x for x in (pool_leads_name + pool_leads_phone) if "id" in x}.values())
    id_to_name = _get_id_to_name()
    def _rp(ids): return [id_to_name.get(pid, pid) for pid in (ids or [])]

    opp_list = [{"name": x.get("name"), "owner": x.get("ownerName"), "department": x.get("departmentName"),
        "products": _rp(x.get("products")), "stage": x.get("stageName") or x.get("stage"),
        "createTime": _ts(x.get("createTime")), "followTime": _ts(x.get("followTime")),
        "winTime": _ts(win_times.get(x["id"])) if x.get("stage") == "SUCCESS" else None} for x in opportunities]
    return {
        "线索": [{"name": x.get("name"), "owner": x.get("ownerName"), "department": x.get("departmentName"), "products": _rp(x.get("products")), "phone": x.get("phone"), "followTime": _ts(x.get("followTime"))} for x in leads],
        "线索池": [{"name": x.get("name"), "products": _rp(x.get("products")), "phone": x.get("phone"), "pool": x.get("poolName")} for x in pool_all],
        "客户": [{"name": x.get("name"), "owner": x.get("ownerName"), "department": x.get("departmentName"), "createTime": _ts(x.get("createTime")), "followTime": _ts(x.get("followTime"))} for x in accounts],
        "公海": [{"name": x.get("name")} for x in pool_accounts],
        "商机": opp_list,
        "联系人": [{"name": x.get("name"), "customer": x.get("customerName"), "owner": x.get("ownerName"), "phone": x.get("phone")} for x in contacts],
    }


def check_duplicate(params):
    customer_name = params.get("客户名", "")
    phone = params.get("手机", "")
    products = params.get("产品", [])
    current_user = params.get("currentUser", "") or _get_current_user()
    mode = params.get("场景", "查重")
    blocks, warnings = [], []

    with ThreadPoolExecutor(max_workers=11) as ex:
        f_lead_name = ex.submit(_search, "lead", customer_name)
        f_lead_phone = ex.submit(_search, "lead", phone)
        f_opp_name = ex.submit(_search, "opportunity", customer_name)
        f_opp_phone = ex.submit(_search, "opportunity", phone)
        f_accounts = ex.submit(_search, "account", customer_name)
        f_contact_phone = ex.submit(_search, "contact", phone)
        f_contact_name = ex.submit(_search, "contact", customer_name)
        f_pool_lead_name = ex.submit(_search, "clue_pool", customer_name)
        f_pool_lead_phone = ex.submit(_search, "clue_pool", phone)
        f_pool_accounts = ex.submit(_search, "customer_pool", customer_name)
        f_success_opps = ex.submit(_search_success_opps, customer_name)

    leads = _merge(f_lead_name.result(), f_lead_phone.result())
    opportunities = _merge(f_opp_name.result(), f_opp_phone.result())
    accounts = f_accounts.result()
    contacts = _merge(f_contact_phone.result(), f_contact_name.result())
    pool_leads_name, pool_leads_phone = f_pool_lead_name.result(), f_pool_lead_phone.result()
    pool_accounts = f_pool_accounts.result()
    success_opps = f_success_opps.result()

    _rule1(leads, opportunities, products, current_user, blocks)
    win_times = _rule2(success_opps, products, current_user, blocks, warnings)
    _rule3_judge(pool_leads_name, pool_leads_phone, pool_accounts, blocks, warnings)

    if not (leads or [x for x in opportunities if x.get("stage") not in CLOSED_STAGES]) and accounts and phone:
        for item in contacts:
            if phone in str(item.get("phone", "")):
                warnings.append({"rule": 4, "type": "contact_phone", "message": f"存在联系人手机号重复：{item.get('name')}（{item.get('customerName')}），请跟销售运营确认商机情况"})
    if phone:
        for item in leads:
            if item.get("phone") == phone:
                blocks.append({"rule": 5, "type": "phone_duplicate", "message": f"手机号{phone}已存在于线索'{item.get('name')}'中（{item.get('ownerName')}），系统不允许重复"})

    info = _build_info(accounts, leads, opportunities, pool_leads_name, pool_leads_phone, pool_accounts, contacts, win_times)
    display_order = ["线索", "线索池", "客户", "公海", "商机", "联系人"]

    if mode == "创建":
        return {"display_order": display_order, "info": info, "judgment": {"pass": len(blocks) == 0, "blocks": blocks, "warnings": warnings, "note": "以上判断仅供参考，请结合实际情况决定"}}

    findings = []
    other_leads = [x for x in leads if x.get("ownerName") != current_user]
    other_open_opps = [x for x in opportunities if x.get("stage") not in CLOSED_STAGES and x.get("ownerName") != current_user]
    if products:
        prod_set = set(products)
        for item in other_leads:
            overlap = prod_set & set(item.get("products") or [])
            if overlap:
                findings.append(f"与{item.get('ownerName')}（{item.get('departmentName')}）的线索'{item.get('name')}'存在产品重复：{'、'.join(overlap)}")
        for item in other_open_opps:
            overlap = prod_set & set(item.get("products") or [])
            if overlap:
                findings.append(f"与{item.get('ownerName')}（{item.get('departmentName')}）的商机'{item.get('name')}'存在产品重复：{'、'.join(overlap)}")
    else:
        id_to_name = _get_id_to_name()
        for item in other_leads:
            prods = '、'.join(id_to_name.get(p, p) for p in (item.get("products") or [])) or '未知'
            findings.append(f"{item.get('ownerName')}（{item.get('departmentName')}）名下有线索'{item.get('name')}'，产品：{prods}")
        for item in other_open_opps:
            prods = '、'.join(id_to_name.get(p, p) for p in (item.get("products") or [])) or '未知'
            findings.append(f"{item.get('ownerName')}（{item.get('departmentName')}）名下有开放商机'{item.get('name')}'，产品：{prods}")

    for b in blocks:
        if b["rule"] == 2: findings.append(b["message"])
    for w in warnings:
        if w["rule"] == 2: findings.append(w["message"])
    notices = [w["message"] for w in warnings if w["rule"] in (3, 4)]
    return {"display_order": display_order, "info": info, "judgment": {"has_duplicate": len(findings) > 0, "findings": findings, "notices": notices}}


# ── 同步文档 ─────────────────────────────────────────────────────────────

_SYNC_MARKER_START = "<!-- AUTO-GENERATED-START -->"
_SYNC_MARKER_END = "<!-- AUTO-GENERATED-END -->"
_MODULE_CACHE_MAP = {"lead": "form_clue.json", "customer": "form_account.json", "opportunity": "form_opportunity.json", "contact": "form_contact.json"}
_SKIP_TYPES = {"MEMBER", "SERIAL_NUMBER", "DIVIDER"}
_TYPE_FORMAT = {"SELECT": "SELECT", "RADIO": "SELECT", "DATA_SOURCE": "⚠️ 实体 ID", "DATA_SOURCE_MULTIPLE": "⚠️ 实体 ID（可多选）",
    "LOCATION": "LOCATION", "INPUT_NUMBER": "数字", "DATE_TIME": "YYYY-MM-DD", "PHONE": "手机/电话", "INPUT": "文本", "TEXTAREA": "文本", "INPUT_MULTIPLE": "文本（多值）"}
_OPTION_GROUPS = [("来源（线索来源 / 客户来源 / 商机来源）", ["线索来源", "客户来源", "来源"]), ("线上来源详情", ["线上来源详情"]),
    ("区域", ["区域"]), ("行业", ["行业"]), ("签约类型（商机）", ["签约类型"]), ("客户类型", ["类型"]), ("分级", ["分级"]),
    ("是否已拜访（线索）", ["是否已拜访"]), ("状态（线索）", ["状态"])]


def _sync_module_doc(module):
    cache_file = _MODULE_CACHE_MAP.get(module)
    if not cache_file:
        return
    path = CACHE_DIR / cache_file
    if not path.exists():
        return
    fields = json.loads(path.read_text("utf-8"))["fields"]
    required = [f for f in fields if f["type"] not in _SKIP_TYPES and f["required"]]
    optional = [f for f in fields if f["type"] not in _SKIP_TYPES and not f["required"]]
    lines = ["\n| # | 字段 | JSON 键名 | 格式 |", "|---|------|----------|------|"]
    for i, f in enumerate(required, 1):
        lines.append(f"| {i} | {f['name']} | {f['name']} | {_TYPE_FORMAT.get(f['type'], '文本')} |")
    if optional:
        lines.append(f"\n选填：{'、'.join(f['name'] for f in optional)}\n")
    md_path = REFERENCES_DIR / f"{module}.md"
    if not md_path.exists():
        return
    text = md_path.read_text("utf-8")
    s, e = text.find(_SYNC_MARKER_START), text.find(_SYNC_MARKER_END)
    if s == -1 or e == -1:
        return
    md_path.write_text(text[:s + len(_SYNC_MARKER_START)] + "\n" + "\n".join(lines) + "\n" + text[e:], "utf-8")


def _sync_field_options():
    all_fields = {}
    for module, cache_file in _MODULE_CACHE_MAP.items():
        path = CACHE_DIR / cache_file
        if not path.exists():
            continue
        for f in json.loads(path.read_text("utf-8"))["fields"]:
            if f["type"] in ("SELECT", "RADIO") and f.get("label_to_value"):
                all_fields.setdefault(f["name"], list(f["label_to_value"].keys()))
    product_data = _read_cache(CACHE_DIR / "product_map.json")
    product_names = list(product_data["map"].keys()) if product_data else []
    lines = ["# SELECT 字段可选值\n", "> 传值规则：传中文值即可，支持传简称（如\"非银金融\"）或完整值，CLI 自动做前缀匹配。\n"]
    for title, field_names in _OPTION_GROUPS:
        labels = next((all_fields[n] for n in field_names if n in all_fields), None)
        if labels:
            lines.extend([f"## {title}\n", ", ".join(labels) + "\n"])
    if product_names:
        lines.extend(["## 产品类型（可多选）\n", ", ".join(product_names) + "\n"])
    (REFERENCES_DIR / "field-options.md").write_text("\n".join(lines), "utf-8")


def sync_forms(modules=None):
    if modules is None:
        modules = ["clue", "account", "opportunity", "contact"]
    for m in modules:
        fields = get_form_config(m, force_refresh=True)
        print(f"已同步 {m}: {len(fields)} 个字段", file=sys.stderr)
    get_product_map(force_refresh=True)
    print("已同步产品列表", file=sys.stderr)
    _sync_field_options()
    for module in _MODULE_CACHE_MAP:
        _sync_module_doc(module)
    print("已同步 references 文档", file=sys.stderr)


# ── CLI 入口 ─────────────────────────────────────────────────────────────

USAGE = """cordys-ext — Cordys CRM 扩展 CLI

用法:
  cordys-ext check <JSON>                      查重
  cordys-ext form <module>                     获取表单配置
  cordys-ext create <module> <JSON>            创建记录
  cordys-ext transform <JSON>                  线索转客户
  cordys-ext sync [module]                     刷新缓存并同步文档
  cordys-ext help                              显示帮助
"""


def main():
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)
    cmd = sys.argv[1]

    if cmd in ("help", "-h", "--help"):
        print(USAGE)
    elif cmd == "check":
        if len(sys.argv) < 3:
            die("check 需要 JSON 参数")
        try:
            params = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            die(f"JSON 解析失败: {e}")
        print(json.dumps(check_duplicate(params), ensure_ascii=False, indent=2))
    elif cmd == "form":
        if len(sys.argv) < 3:
            die("form 需要指定 formKey")
        print(json.dumps(get_form_config(sys.argv[2]), ensure_ascii=False, indent=2))
    elif cmd == "create":
        if len(sys.argv) < 4:
            die("create 需要指定模块和 JSON 参数")
        try:
            params = json.loads(sys.argv[3])
        except json.JSONDecodeError as e:
            die(f"JSON 解析失败: {e}")
        print(json.dumps(create_entity(sys.argv[2], params), ensure_ascii=False, indent=2))
    elif cmd == "transform":
        if len(sys.argv) < 3:
            die("transform 需要 JSON 参数")
        try:
            params = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            die(f"JSON 解析失败: {e}")
        print(json.dumps(transform_lead(params), ensure_ascii=False, indent=2))
    elif cmd == "sync":
        modules = [sys.argv[2]] if len(sys.argv) > 2 else None
        sync_forms(modules)
        print(json.dumps({"status": "ok"}, ensure_ascii=False))
    else:
        die(f"未知命令: {cmd}（尝试 cordys-ext help）")


if __name__ == "__main__":
    main()