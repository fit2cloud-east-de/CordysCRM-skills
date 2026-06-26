import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib import request
from urllib.error import HTTPError, URLError


def check_duplicate(domain, access_key, secret_key, params=""):
    """
    Cordys CRM 查重工具 — 查询系统中是否存在重复记录并返回冲突判断。

    Args:
        domain: CRM 域名，如 https://www.cordys.cn
        access_key: 用户的 X-Access-Key
        secret_key: 用户的 X-Secret-Key
        params: JSON 字符串，如 {"客户名":"东北证券","手机":"13800138000","产品":["MaxKB 专业版"]}

    Returns:
        JSON 字符串，包含 display_order、info、judgment
    """

    CLOSED_STAGES = {"SUCCESS", "FAIL"}

    try:
        p = json.loads(params) if isinstance(params, str) else params or {}
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "params JSON 解析失败"}, ensure_ascii=False)

    customer_name = p.get("客户名", "")
    phone = p.get("手机", "")
    products = p.get("产品", [])
    products_list = [x.strip() for x in products.split(",") if x.strip()] if isinstance(products, str) else products or []

    if not customer_name and not phone:
        return json.dumps({"error": "客户名称和手机号至少需要填写一个"}, ensure_ascii=False)

    # ── API 调用 ──

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
                return {}
        except URLError:
            return {}

    def search(module, keyword):
        if not keyword:
            return []
        r = api("POST", f"/global/search/{module}", {"keyword": keyword, "pageSize": 100, "current": 1})
        return r.get("data", {}).get("list", [])

    def get_current_user():
        r = api("GET", "/personal/center/info")
        return r.get("data", {}).get("userName", "")

    def get_product_id_to_name():
        r = api("POST", "/field/source/product", {"current": 1, "pageSize": 200, "keyword": ""})
        if r.get("code") != 100200:
            return {}
        return {item["id"]: item["name"] for item in r.get("data", {}).get("list", [])}

    def merge(list_a, list_b):
        ids = {x["id"] for x in list_a if "id" in x}
        return list_a + [x for x in list_b if "id" in x and x["id"] not in ids]

    def ts(ms):
        if not ms:
            return None
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")

    # ── 并行搜索 ──

    executor = ThreadPoolExecutor(max_workers=3)

    futures = []
    futures.append(executor.submit(get_current_user))
    futures.append(executor.submit(search, "lead", customer_name))
    futures.append(executor.submit(search, "lead", phone))
    futures.append(executor.submit(search, "opportunity", customer_name))
    futures.append(executor.submit(search, "opportunity", phone))
    futures.append(executor.submit(search, "account", customer_name))
    futures.append(executor.submit(search, "contact", phone))
    futures.append(executor.submit(search, "contact", customer_name))
    futures.append(executor.submit(search, "clue_pool", customer_name))
    futures.append(executor.submit(search, "clue_pool", phone))
    futures.append(executor.submit(search, "customer_pool", customer_name))

    r = [f.result() for f in futures]

    current_user = r[0]
    leads = merge(r[1], r[2])
    opportunities = merge(r[3], r[4])
    accounts = r[5]
    contacts = merge(r[6], r[7])
    pool_leads_name = r[8]
    pool_leads_phone = r[9]
    pool_accounts = r[10]

    id_to_name = get_product_id_to_name()
    conflicts, warnings = [], []

    # ── 规则 1：产品冲突 ──

    if products_list:
        prod_set = set(products_list)
        for item in leads:
            if item.get("ownerName") == current_user:
                continue
            overlap = prod_set & set(item.get("products") or [])
            if overlap:
                conflicts.append({"rule": 1, "message": f"{item.get('ownerName')}（{item.get('departmentName')}）的线索'{item.get('name')}'存在产品重复，重复产品：{'、'.join(overlap)}"})
        for item in opportunities:
            if item.get("stage") in CLOSED_STAGES or item.get("ownerName") == current_user:
                continue
            overlap = prod_set & set(item.get("products") or [])
            if overlap:
                conflicts.append({"rule": 1, "message": f"{item.get('ownerName')}（{item.get('departmentName')}）的商机'{item.get('name')}'存在产品重复，重复产品：{'、'.join(overlap)}"})

    # ── 规则 3：线索池/公海 ──

    phone_ids = {x["id"] for x in pool_leads_phone}
    for item in pool_leads_phone:
        conflicts.append({"rule": 3, "message": f"线索池中存在手机号相同的线索'{item.get('name')}'，请捞回而非新建"})
    for item in pool_leads_name:
        if item.get("id") not in phone_ids:
            warnings.append({"rule": 3, "message": f"线索池中存在同名线索'{item.get('name')}'"})
    for item in pool_accounts:
        conflicts.append({"rule": 3, "message": f"公海中存在客户'{item.get('name')}'，建议捞回后新建联系人"})

    # ── 规则 4：联系人手机重复 ──

    if not (leads or [x for x in opportunities if x.get("stage") not in CLOSED_STAGES]) and accounts and phone:
        for item in contacts:
            if item.get("ownerName") == current_user:
                continue
            if phone in str(item.get("phone", "")):
                warnings.append({"rule": 4, "message": f"存在联系人手机号重复：{item.get('name')}（{item.get('customerName')}），请跟销售运营确认商机情况"})

    # ── 规则 5：手机号唯一性（系统硬限制，不跳过本人） ──

    if phone:
        for item in leads:
            if item.get("phone") == phone:
                conflicts.append({"rule": 5, "message": f"手机号{phone}已存在于线索'{item.get('name')}'中（{item.get('ownerName')}），系统不允许重复"})

    # ── 构建 info ──

    def rp(ids):
        return [id_to_name.get(pid, pid) for pid in (ids or [])]

    pool_all = list({x["id"]: x for x in (pool_leads_name + pool_leads_phone) if "id" in x}.values())
    info = {
        "线索": [{"name": x.get("name"), "owner": x.get("ownerName"), "department": x.get("departmentName"), "products": rp(x.get("products")), "phone": x.get("phone"), "followTime": ts(x.get("followTime"))} for x in leads],
        "线索池": [{"name": x.get("name"), "products": rp(x.get("products")), "phone": x.get("phone"), "pool": x.get("poolName")} for x in pool_all],
        "客户": [{"name": x.get("name"), "owner": x.get("ownerName"), "department": x.get("departmentName"), "createTime": ts(x.get("createTime")), "followTime": ts(x.get("followTime"))} for x in accounts],
        "公海": [{"name": x.get("name")} for x in pool_accounts],
        "商机": [{"name": x.get("name"), "owner": x.get("ownerName"), "department": x.get("departmentName"), "products": rp(x.get("products")), "stage": x.get("stageName") or x.get("stage"), "createTime": ts(x.get("createTime")), "followTime": ts(x.get("followTime"))} for x in opportunities],
        "联系人": [{"name": x.get("name"), "customer": x.get("customerName"), "owner": x.get("ownerName"), "phone": x.get("phone")} for x in contacts],
    }

    return json.dumps({
        "display_order": ["线索", "线索池", "客户", "公海", "商机", "联系人"],
        "info": info,
        "judgment": {"conflicts": conflicts, "warnings": warnings}
    }, ensure_ascii=False)
