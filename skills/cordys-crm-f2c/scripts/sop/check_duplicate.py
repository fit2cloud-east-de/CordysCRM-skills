import json
from concurrent.futures import ThreadPoolExecutor
from urllib import request
from urllib.error import HTTPError, URLError

from time_boundary import format_date_ms


def check_duplicate(domain, access_key, secret_key, params=""):
    """
    Cordys CRM 查重工具 — 搜索相关记录并返回可能冲突提醒。

    Args:
        domain: CRM 域名，如 https://www.cordys.cn
        access_key: 用户的 X-Access-Key
        secret_key: 用户的 X-Secret-Key
        params: JSON 字符串，如 {"客户名":"东北证券","手机":"13800138000"}

    Returns:
        JSON 字符串，包含 display_order、info、judgment
    """

    try:
        p = json.loads(params) if isinstance(params, str) else params or {}
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "params JSON 解析失败"}, ensure_ascii=False)

    # 接受中英文 key 别名：模型常自然地传 phone/customer_name/name，不该因 key 名不符而回退重试
    customer_name = p.get("客户名") or p.get("customer_name") or p.get("客户") or p.get("name") or ""
    phone = p.get("手机") or p.get("phone") or p.get("mobile") or p.get("电话") or p.get("tel") or ""

    if not customer_name and not phone:
        return json.dumps({"error": "客户名称和手机号至少需要填写一个（key 用「客户名」/「手机」，也接受 customer_name/phone）"}, ensure_ascii=False)

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

    search_errors = []

    def search(module, keyword):
        if not keyword:
            return []
        r = api("POST", f"/global/search/{module}", {"keyword": keyword, "pageSize": 100, "current": 1})
        if r.get("code") != 100200 or not isinstance(r.get("data", {}).get("list"), list):
            search_errors.append({"module": module, "keyword": keyword})
            return []
        return r.get("data", {}).get("list", [])

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
        return format_date_ms(ms)

    # ── 并行搜索 ──

    executor = ThreadPoolExecutor(max_workers=3)

    futures = []
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

    if search_errors:
        failed_modules = "、".join(sorted({item["module"] for item in search_errors}))
        return json.dumps({
            "error": f"查重失败：以下分类查询未成功：{failed_modules}，不得将结果视为无冲突，请稍后重试"
        }, ensure_ascii=False)

    leads = merge(r[0], r[1])
    opportunities = merge(r[2], r[3])
    accounts = r[4]
    contacts = merge(r[5], r[6])
    pool_leads_name = r[7]
    pool_leads_phone = r[8]
    pool_accounts = r[9]

    id_to_name = get_product_id_to_name()

    # ── 构建 info ──

    def rp(ids):
        return [id_to_name.get(pid, pid) for pid in (ids or [])]

    pool_all = list({x["id"]: x for x in (pool_leads_name + pool_leads_phone) if "id" in x}.values())
    # 每条带 id + ownerId：供后续写入（follow/follow-plan/update 等）直接取用，避免二次查询。
    # id 是记录主键（客户→customerId、线索→clueId、商机→opportunityId、联系人→contactId）。
    info = {
        "线索": [{"id": x.get("id"), "name": x.get("name"), "owner": x.get("ownerName"), "ownerId": x.get("owner"), "department": x.get("departmentName"), "products": rp(x.get("products")), "phone": x.get("phone"), "followTime": ts(x.get("followTime"))} for x in leads],
        "线索池": [{"id": x.get("id"), "name": x.get("name"), "products": rp(x.get("products")), "phone": x.get("phone"), "pool": x.get("poolName")} for x in pool_all],
        "客户": [{"id": x.get("id"), "name": x.get("name"), "owner": x.get("ownerName"), "ownerId": x.get("owner"), "department": x.get("departmentName"), "createTime": ts(x.get("createTime")), "followTime": ts(x.get("followTime"))} for x in accounts],
        "公海": [{"id": x.get("id"), "name": x.get("name")} for x in pool_accounts],
        "商机": [{"id": x.get("id"), "name": x.get("name"), "owner": x.get("ownerName"), "ownerId": x.get("owner"), "department": x.get("departmentName"), "products": rp(x.get("products")), "stage": x.get("stageName") or x.get("stage"), "createTime": ts(x.get("createTime")), "followTime": ts(x.get("followTime")), "customerId": x.get("accountId") or x.get("customerId")} for x in opportunities],
        "联系人": [{"id": x.get("id"), "name": x.get("name"), "customer": x.get("customerName"), "customerId": x.get("customerId") or x.get("accountId"), "owner": x.get("ownerName"), "phone": x.get("phone")} for x in contacts],
    }
    has_matches = any(info.values())
    judgment_message = (
        "查到相关记录，可能存在冲突，请核对"
        if has_matches
        else "未查到相关记录"
    )

    render_instruction = (
        "【展示格式：强制，不得改写为摘要/叙述/自定义表格，不得追加总结或评价段落】\n"
        "严格按以下 Markdown 模板输出，字段缺失填 -，分类无记录写「无」，顺序不可变：\n"
        "\n"
        "## {客户名} 查重结果\n"
        "\n"
        "📊 线索 {n} 条 | 线索池 {n} 条 | 客户 {n} 条 | 公海 {n} 条 | 商机 {n} 条 | 联系人 {n} 条\n"
        "\n"
        "### 判断结果\n"
        "（hasMatches 为 true 时，用 ⚠️ 前缀逐字输出 judgment.message；为 false 时逐字输出 judgment.message）\n"
        "\n"
        "### 线索（{n}条）\n"
        "| 名称 | 负责人 | 部门 | 产品 | 手机 | 最近跟进 |\n"
        "### 线索池（{n}条）\n"
        "| 名称 | 产品 | 手机 | 所属池 |\n"
        "### 客户（{n}条）\n"
        "| 名称 | 负责人 | 部门 | 创建时间 | 最近跟进 |\n"
        "### 公海（{n}条）\n"
        "| 名称 |\n"
        "### 商机（{n}条）\n"
        "| 名称 | 负责人 | 部门 | 产品 | 阶段 | 创建时间 | 最近跟进 | 赢单时间 |\n"
        "### 联系人（{n}条）\n"
        "| 姓名 | 所属客户 | 负责人 | 手机 |\n"
        "\n"
        "6 个分类全部展示（空的写「无」），不要在模板之外添加任何总结、背景介绍或个人判断"
        "（如「是老客户了」「关系稳得很」「不是你的客户」等一律不写）。\n"
        "\n"
        "【ID 复用，重要】info 每条记录都带 id（及商机/联系人的 customerId、记录的 ownerId），"
        "这些 ID 供你后续写入直接使用，不要展示在表格里。用户接着要跟进/建计划/更新时，"
        "直接从上面 check 结果取对应 id（客户→customerId、线索→clueId、商机→opportunityId+customerId、"
        "联系人→contactId），严禁再调 search 或裸 Python 二次查 ID，更严禁在命令里硬编码 AccessKey/SecretKey。"
    )

    return json.dumps({
        "render_instruction": render_instruction,
        "display_order": ["线索", "线索池", "客户", "公海", "商机", "联系人"],
        "info": info,
        "judgment": {
            "hasMatches": has_matches,
            "message": judgment_message,
        },
    }, ensure_ascii=False)
