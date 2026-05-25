#!/usr/bin/env python3
"""
查重逻辑 — 4 层规则判断，返回结构化 JSON 结果
"""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from cordys_ext import api

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
    ids = {x["id"] for x in list_a}
    return list_a + [x for x in list_b if x["id"] not in ids]


def _get_id_to_name():
    from cordys_ext import get_product_map
    pm = get_product_map()
    return {v: k for k, v in pm.items()}


# ── 规则 1 ──────────────────────────────────────────────────────────────

def _rule1(leads, opportunities, products, current_user, blocks):
    if not products:
        return
    prod_set = set(products)
    for item in leads:
        if item.get("ownerName") == current_user:
            continue
        item_products = item.get("products") or []
        overlap = prod_set & set(item_products)
        if overlap:
            blocks.append({
                "rule": 1, "type": "product_conflict",
                "message": f"{item.get('ownerName')}（{item.get('departmentName')}）的线索'{item.get('name')}'存在产品重复，重复产品：{'、'.join(overlap)}"
            })
    for item in opportunities:
        if item.get("stage") in CLOSED_STAGES or item.get("ownerName") == current_user:
            continue
        item_products = item.get("products") or []
        overlap = prod_set & set(item_products)
        if overlap:
            blocks.append({
                "rule": 1, "type": "product_conflict",
                "message": f"{item.get('ownerName')}（{item.get('departmentName')}）的商机'{item.get('name')}'存在产品重复，重复产品：{'、'.join(overlap)}"
            })


# ── 规则 2 ──────────────────────────────────────────────────────────────

def _search_success_opps(customer_name):
    """搜索成单商机（需要 actualEndTime 字段，全局搜索不返回此字段）"""
    if not customer_name:
        return []
    try:
        r = api("POST", "/opportunity/page", {
            "current": 1, "pageSize": 100, "keyword": customer_name, "viewId": "ALL",
            "combineSearch": {"searchMode": "AND", "conditions": [
                {"value": ["SUCCESS"], "operator": "IN", "name": "stage", "multipleValue": False, "type": "SELECT"}
            ]}
        })
        return r.get("data", {}).get("list", [])
    except SystemExit:
        return []


def _rule2(success_opps, products, current_user, blocks, warnings):
    """从成单商机判断保护期，返回 {opp_id: actualEndTime}"""
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
            item_product_ids = item.get("products") or []
            item_product_names = {id_to_name.get(pid, pid) for pid in item_product_ids}
            if products:
                overlap = set(products) & item_product_names
                if overlap:
                    blocks.append({
                        "rule": 2, "type": "protection_period",
                        "message": f"该客户在{item.get('ownerName')}（{dept}）名下有成单商机'{item.get('name')}'，保护期至{end_date}，保护范围：仅{'/'.join(overlap)}"
                    })
            else:
                prods = '/'.join(item_product_names) if item_product_names else '未知'
                warnings.append({
                    "rule": 2, "type": "protection_period",
                    "message": f"该客户在{item.get('ownerName')}（{dept}）名下有成单商机'{item.get('name')}'，保护期至{end_date}，保护产品：{prods}（浙赣团队仅保护成单产品）"
                })
        else:
            blocks.append({
                "rule": 2, "type": "protection_period",
                "message": f"该客户在{item.get('ownerName')}（{dept}）名下有成单商机'{item.get('name')}'，保护期至{end_date}，保护范围：全产品"
            })

    return win_times


# ── 规则 3 ──────────────────────────────────────────────────────────────

def _rule3_judge(pool_leads_name, pool_leads_phone, pool_accounts, blocks, warnings):
    phone_ids = {x["id"] for x in pool_leads_phone}
    for item in pool_leads_phone:
        blocks.append({
            "rule": 3, "type": "pool_lead_phone",
            "message": f"线索池中存在手机号相同的线索'{item.get('name')}'，请捞回而非新建"
        })
    for item in pool_leads_name:
        if item["id"] not in phone_ids:
            warnings.append({
                "rule": 3, "type": "pool_lead_name",
                "message": f"线索池中存在'{item.get('name')}'，如需要可自行捞回"
            })
    for item in pool_accounts:
        warnings.append({
            "rule": 3, "type": "pool_account",
            "message": f"公海中存在客户'{item.get('name')}'，建议捞回后新建联系人"
        })


# ── 信息汇总 ────────────────────────────────────────────────────────────

def _ts(ms):
    """毫秒时间戳转日期字符串"""
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def _build_info(accounts, leads, opportunities, pool_leads_name, pool_leads_phone, pool_accounts, contacts, win_times):
    pool_all = list({x["id"]: x for x in (pool_leads_name + pool_leads_phone)}.values())
    id_to_name = _get_id_to_name()

    def _resolve_products(ids):
        return [id_to_name.get(pid, pid) for pid in (ids or [])]

    opp_list = []
    for x in opportunities:
        opp_list.append({
            "name": x.get("name"),
            "owner": x.get("ownerName"),
            "department": x.get("departmentName"),
            "products": _resolve_products(x.get("products")),
            "stage": x.get("stageName") or x.get("stage"),
            "createTime": _ts(x.get("createTime")),
            "followTime": _ts(x.get("followTime")),
            "winTime": _ts(win_times.get(x["id"])) if x.get("stage") == "SUCCESS" else None,
        })

    return {
        "线索": [{"name": x.get("name"), "owner": x.get("ownerName"), "department": x.get("departmentName"), "products": _resolve_products(x.get("products")), "phone": x.get("phone"), "followTime": _ts(x.get("followTime"))} for x in leads],
        "线索池": [{"name": x.get("name"), "products": _resolve_products(x.get("products")), "phone": x.get("phone"), "pool": x.get("poolName")} for x in pool_all],
        "客户": [{"name": x.get("name"), "owner": x.get("ownerName"), "department": x.get("departmentName"), "createTime": _ts(x.get("createTime")), "followTime": _ts(x.get("followTime"))} for x in accounts],
        "公海": [{"name": x.get("name")} for x in pool_accounts],
        "商机": opp_list,
        "联系人": [{"name": x.get("name"), "customer": x.get("customerName"), "owner": x.get("ownerName"), "phone": x.get("phone")} for x in contacts],
    }


# ── 主入口 ──────────────────────────────────────────────────────────────

def check_duplicate(params):
    customer_name = params.get("客户名", "")
    phone = params.get("手机", "")
    products = params.get("产品", [])
    current_user = params.get("currentUser", "") or _get_current_user()
    mode = params.get("场景", "查重")  # "查重" or "创建"

    blocks = []
    warnings = []

    # 并行搜索
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
    pool_leads_name = f_pool_lead_name.result()
    pool_leads_phone = f_pool_lead_phone.result()
    pool_accounts = f_pool_accounts.result()
    success_opps = f_success_opps.result()

    # 规则判断
    _rule1(leads, opportunities, products, current_user, blocks)
    win_times = _rule2(success_opps, products, current_user, blocks, warnings)
    _rule3_judge(pool_leads_name, pool_leads_phone, pool_accounts, blocks, warnings)

    # 规则4：无线索无商机，但有客户+联系人手机重复 → 提醒
    has_leads_or_opps = bool(leads) or bool([x for x in opportunities if x.get("stage") not in CLOSED_STAGES])
    if not has_leads_or_opps and accounts and phone:
        for item in contacts:
            if phone in str(item.get("phone", "")):
                warnings.append({"rule": 4, "type": "contact_phone", "message": f"存在联系人手机号重复：{item.get('name')}（{item.get('customerName')}），请跟销售运营确认商机情况"})

    # 规则5：手机号唯一性（线索后端拒绝重复手机号）
    if phone:
        for item in leads:
            if item.get("phone") == phone:
                blocks.append({"rule": 5, "type": "phone_duplicate", "message": f"手机号{phone}已存在于线索'{item.get('name')}'中（{item.get('ownerName')}），系统不允许重复"})

    info = _build_info(accounts, leads, opportunities, pool_leads_name, pool_leads_phone, pool_accounts, contacts, win_times)
    display_order = ["线索", "线索池", "客户", "公海", "商机", "联系人"]

    if mode == "创建":
        return {
            "display_order": display_order,
            "info": info,
            "judgment": {
                "pass": len(blocks) == 0,
                "blocks": blocks,
                "warnings": warnings,
                "note": "以上判断仅供参考，请结合实际情况决定"
            }
        }

    # 主动查重模式：不说阻断，只判断是否存在重复
    findings = []
    other_leads = [x for x in leads if x.get("ownerName") != current_user]
    other_open_opps = [x for x in opportunities if x.get("stage") not in CLOSED_STAGES and x.get("ownerName") != current_user]

    if products:
        # 有产品：精确判断
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
        # 无产品：粗略判断
        id_to_name = _get_id_to_name()
        for item in other_leads:
            prods = '、'.join(id_to_name.get(p, p) for p in (item.get("products") or [])) or '未知'
            findings.append(f"{item.get('ownerName')}（{item.get('departmentName')}）名下有线索'{item.get('name')}'，产品：{prods}")
        for item in other_open_opps:
            prods = '、'.join(id_to_name.get(p, p) for p in (item.get("products") or [])) or '未知'
            findings.append(f"{item.get('ownerName')}（{item.get('departmentName')}）名下有开放商机'{item.get('name')}'，产品：{prods}")

    # 保护期也纳入 findings
    for b in blocks:
        if b["rule"] == 2:
            findings.append(b["message"])
    for w in warnings:
        if w["rule"] == 2:
            findings.append(w["message"])

    # 线索池/公海/联系人提醒
    notices = [w["message"] for w in warnings if w["rule"] in (3, 4)]

    return {
        "display_order": display_order,
        "info": info,
        "judgment": {
            "has_duplicate": len(findings) > 0,
            "findings": findings,
            "notices": notices,
        }
    }
