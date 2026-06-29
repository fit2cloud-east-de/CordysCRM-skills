import json
from urllib import request
from urllib.error import HTTPError, URLError


def sync_forms(domain, access_key, secret_key, params=""):
    """
    Cordys CRM 表单同步工具 — 获取所有模块表单配置和产品列表，生成 references 文档内容。

    返回纯文本，用 ===FILE:path=== 分隔各文件内容，供本地 shell 直接写入。

    Args:
        domain: CRM 域名，如 https://www.cordys.cn
        access_key: 用户的 X-Access-Key
        secret_key: 用户的 X-Secret-Key
        params: JSON 字符串（可选），如 {"modules":["clue","account"]}，不传则同步全部

    Returns:
        纯文本，格式为 ===FILE:references/xxx.md=== 分隔的多文件内容
    """

    try:
        p = json.loads(params) if isinstance(params, str) and params else {}
    except (json.JSONDecodeError, TypeError):
        p = {}

    modules = p.get("modules", ["clue", "account", "opportunity", "contact", "follow",
                                 "contract", "payment-record"])

    FORM_PATH_MAP = {
        "clue": "/lead/module/form",
        "lead": "/lead/module/form",
        "account": "/account/module/form",
        "opportunity": "/opportunity/module/form",
        "contact": "/module/form/config/contact",
        "follow": "/follow/record/module/form",
        "contract": "/contract/module/form",
        "payment-record": "/contract/payment-record/module/form",
    }

    MODULE_TO_REF = {
        "clue": "lead", "account": "account",
        "opportunity": "opportunity", "contact": "contact",
        "follow": "follow",
        "contract": "contract", "payment-record": "payment-record",
    }

    SKIP_TYPES = {"MEMBER", "SERIAL_NUMBER", "DIVIDER"}
    TYPE_FORMAT = {
        "SELECT": "SELECT", "RADIO": "SELECT",
        "DATA_SOURCE": "⚠️ 实体 ID", "DATA_SOURCE_MULTIPLE": "⚠️ 实体 ID（可多选）",
        "LOCATION": "LOCATION", "INPUT_NUMBER": "数字", "DATE_TIME": "YYYY-MM-DD",
        "PHONE": "手机/电话", "INPUT": "文本", "TEXTAREA": "文本", "INPUT_MULTIPLE": "文本（多值）",
    }

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
                return {"code": 0}
        except URLError:
            return {"code": 0}

    def get_form_fields(form_key):
        path = FORM_PATH_MAP.get(form_key, f"/{form_key}/module/form")
        resp = api("GET", path)
        if resp.get("code") != 100200:
            return []
        raw = [f for f in resp["data"]["fields"] if f["type"] != "DIVIDER"]

        # 建立 fieldId→字段名、optionValue→label 映射，用于翻译联动规则
        id_to_name = {f["id"]: f["name"] for f in raw}
        value_to_label = {}
        for f in raw:
            for o in (f.get("options") or []):
                value_to_label[o["value"]] = o["label"]

        # 反向收集：被哪个字段的哪些取值"控制显示"（即条件必填依赖）
        # showControlRules 在“控制字段”上，形如 [{"value":选项值,"fieldIds":[被控字段id,...]}]
        controlled_by = {}  # 被控字段id -> {控制字段名: [触发的中文取值,...]}
        for f in raw:
            for rule in (f.get("showControlRules") or []):
                trigger = value_to_label.get(rule.get("value"), rule.get("value"))
                for fid in (rule.get("fieldIds") or []):
                    controlled_by.setdefault(fid, {}).setdefault(f["name"], [])
                    if trigger not in controlled_by[fid][f["name"]]:
                        controlled_by[fid][f["name"]].append(trigger)

        fields = []
        for f in raw:
            label_to_value = {o["label"]: o["value"] for o in (f.get("options") or [])}
            required = any(r.get("key") == "required" for r in (f.get("rules") or []))
            # 条件必填：字段 required 且默认隐藏（被其他字段的取值控制显示）
            condition = ""
            if required and f["id"] in controlled_by:
                parts = []
                for ctrl_name, triggers in controlled_by[f["id"]].items():
                    parts.append(f"{ctrl_name}={' / '.join(triggers)}")
                condition = "；".join(parts)
            fields.append({
                "id": f["id"], "name": f["name"], "type": f["type"],
                "businessKey": f.get("businessKey") or "",
                "required": required, "label_to_value": label_to_value,
                "condition": condition,
            })
        return fields

    def gen_module_snippet(fields, product_names=None, module="", top_level_fields=None, query_only=False):
        required = [f for f in fields if f["type"] not in SKIP_TYPES and f["required"]]
        optional = [f for f in fields if f["type"] not in SKIP_TYPES and not f["required"]]
        has_cond = any(f.get("condition") for f in required)
        if query_only:
            # 查询-only 模块（如 contract / payment-record）：不生成创建字段表（避免误导模型去创建），
            # 只保留 SELECT 可选值 + 查询字段参考。
            lines = [""]
        elif has_cond:
            lines = ["", "| # | 字段 | JSON 键名 | 格式 | 条件必填 |", "|---|------|----------|------|---------|"]
            for i, f in enumerate(required, 1):
                cond = f.get("condition") or "—"
                lines.append(f"| {i} | {f['name']} | {f['name']} | {TYPE_FORMAT.get(f['type'], '文本')} | {cond} |")
        else:
            lines = ["", "| # | 字段 | JSON 键名 | 格式 |", "|---|------|----------|------|"]
            for i, f in enumerate(required, 1):
                lines.append(f"| {i} | {f['name']} | {f['name']} | {TYPE_FORMAT.get(f['type'], '文本')} |")
        if not query_only and optional:
            lines.append(f"\n选填：{'、'.join(f['name'] for f in optional)}\n")
        if not query_only and has_cond:
            lines.append("\n> 「条件必填」列非「—」的字段，仅当满足条件时才必填；不满足时可留空。\n")

        # 追加 SELECT 字段可选值
        select_fields = [f for f in fields if f["type"] in ("SELECT", "RADIO") and f.get("label_to_value")]
        if select_fields or product_names:
            lines.append("\n## SELECT 字段可选值\n")
            lines.append("> **创建时传中文标签**（支持简称，CLI 自动前缀匹配）。")
            lines.append("> **查询时（`combineSearch.conditions` 的 `value`）传选项 ID**：标注「查询用 ID」的字段，中文与 ID 不一致，查询必须填 `=` 右侧的 ID（填中文会静默返回空）；未标注的字段中文即 ID，查询直接传中文即可。\n")
            for f in select_fields:
                pairs = f["label_to_value"]
                differ = any(label != value for label, value in pairs.items())
                if differ:
                    mapping = ", ".join(f"{label}={value}" for label, value in pairs.items())
                    lines.append(f"- **{f['name']}**（查询用 ID）：{mapping}")
                else:
                    lines.append(f"- **{f['name']}**：{', '.join(pairs.keys())}")
            if product_names:
                lines.append(f"- **产品类型（可多选）**：{', '.join(product_names)}")
            lines.append("")

        # 追加查询字段参考（combineSearch.conditions 可用的 name 和 type）
        queryable = [f for f in fields if f["type"] not in SKIP_TYPES]
        if queryable:
            lines.append("\n## 查询字段参考\n")
            lines.append("> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。\n")
            lines.append("| 字段 | name（条件用） | type |")
            lines.append("|------|--------------|------|")
            for name, ftype in (top_level_fields or []):
                lines.append(f"| {name} | {name} | {ftype} |")
            for f in queryable:
                cond_name = f.get("businessKey") or f.get("id", f["name"])
                lines.append(f"| {f['name']} | {cond_name} | {f['type']} |")
            lines.append("")

        return "\n".join(lines)

    def gen_follow_snippet(fields):
        # 跟进表单结构视图：自动同步整张表单字段表（名称/businessKey/类型/必填）。
        # ⚠️ 这是「表单字段」结构，与写入 API 参数不一一对应（写入端有 module 注入、
        # 记录 ID 按模块取 clueId/customerId/opportunityId 等语义），写入参数视图由
        # follow.md 中手写的「必填字段清单」维护，sync 不覆盖。
        # 注：不套用 SKIP_TYPES——owner 是 MEMBER 类型但属跟进必填写入字段，需保留；
        # 仅过滤无展示意义的 SERIAL_NUMBER / DIVIDER。
        FOLLOW_SKIP = {"SERIAL_NUMBER", "DIVIDER"}
        real = [f for f in fields if f["type"] not in FOLLOW_SKIP]

        # 1) 全量表单字段表
        lines = ["", "| 字段 | businessKey | 类型 | 必填 |", "|------|------------|------|------|"]
        for f in real:
            bk = f.get("businessKey") or "—"
            req = "是" if f.get("required") else "否"
            lines.append(f"| {f['name']} | {bk} | {f['type']} | {req} |")

        # 2) 选填自定义字段（无 businessKey 的字段，如意向产品）——给出写入键名与格式
        custom = [f for f in real if not f.get("businessKey")]
        if custom:
            lines.append("\n## 选填自定义字段\n")
            lines.append("| 字段 | JSON 键名 | 格式 | 说明 |")
            lines.append("|------|----------|------|------|")
            for f in custom:
                lines.append(f"| {f['name']} | {f['name']} | {TYPE_FORMAT.get(f['type'], '文本')} | |")

        # 3) 跟进方式可选值（仅 followMethod 字段）
        method_fields = [f for f in fields if f.get("businessKey") == "followMethod" and f.get("label_to_value")]
        if method_fields:
            lines.append("\n## 跟进方式可选值\n")
            for f in method_fields:
                for label, value in f["label_to_value"].items():
                    lines.append(f"- `{value}` = {label}")
            lines.append("")

        return "\n".join(lines)

    # Fetch all forms
    all_fields = {}
    for m in modules:
        all_fields[m] = get_form_fields(m)

    # Fetch product list
    prod_resp = api("POST", "/field/source/product", {"current": 1, "pageSize": 200, "keyword": ""})
    product_names = [item["name"] for item in prod_resp.get("data", {}).get("list", [])] if prod_resp.get("code") == 100200 else []

    # Fetch top-level API fields for each module (from one sample record)
    PAGE_PATH_MAP = {"clue": "lead", "account": "account", "opportunity": "opportunity", "contact": "account/contact",
                     "contract": "contract", "payment-record": "contract/payment-record"}
    SKIP_TOP_KEYS = {"id", "organizationId", "moduleFields", "inCustomerPool", "poolId",
                     "inSharedPool", "collectionTime", "transitionType", "transitionId"}
    # 展示用字段（不能用于 condition 过滤）
    SKIP_TOP_SUFFIXES = ("Name", "User")

    ENUM_KEY_NAMES = {"stage", "status", "type", "approvalStatus"}

    def infer_type(key, value):
        # 按字段名规则优先判定
        if key in ENUM_KEY_NAMES:
            return "SELECT"
        if key.endswith("Id") or key == "owner" or key == "follower":
            if "department" in key.lower():
                return "DEPARTMENT"
            return "MEMBER"
        if "Time" in key or "Date" in key or "time" in key:
            return "DATE_TIME"
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            if value > 1e12:
                return "DATE_TIME"
            return "INPUT_NUMBER"
        if isinstance(value, str):
            return "INPUT"
        return None

    def get_top_level_fields(module_key):
        page_module = PAGE_PATH_MAP.get(module_key, module_key)
        resp = api("POST", f"/{page_module}/page", {"current": 1, "pageSize": 1, "viewId": "ALL"})
        if resp.get("code") != 100200:
            return []
        items = resp.get("data", {}).get("list", [])
        if not items:
            return []
        record = items[0]
        # 表单字段的 businessKey 集合（已在表单列表里了，避免重复）
        form_biz_keys = {f.get("businessKey") for f in all_fields.get(module_key, []) if f.get("businessKey")}
        result = []
        for key, value in record.items():
            if key in SKIP_TOP_KEYS or key in form_biz_keys:
                continue
            if any(key.endswith(s) for s in SKIP_TOP_SUFFIXES):
                continue
            if isinstance(value, (list, dict)):
                continue
            ftype = infer_type(key, value)
            if ftype:
                result.append((key, ftype))
        return result

    # Build output
    output_parts = []

    # Module reference snippets (with SELECT options and products inlined)
    # 判断哪些模块有产品字段
    modules_with_products = set()
    for m in modules:
        for f in all_fields[m]:
            if "产品" in f["name"] and f["type"] in ("DATA_SOURCE", "DATA_SOURCE_MULTIPLE"):
                modules_with_products.add(m)
                break

    # 查询-only 模块：不支持通过助手创建，sync 只生成 SELECT 可选值 + 查询字段参考。
    QUERY_ONLY = {"contract", "payment-record"}

    for m in modules:
        ref_name = MODULE_TO_REF.get(m, m)
        if m == "follow":
            snippet = gen_follow_snippet(all_fields[m])
        else:
            prods = product_names if m in modules_with_products else None
            top_fields = get_top_level_fields(m)
            snippet = gen_module_snippet(all_fields[m], prods, module=m, top_level_fields=top_fields,
                                         query_only=(m in QUERY_ONLY))
        output_parts.append(f"===FILE:references/forms/{ref_name}.md===")
        output_parts.append(snippet)

    return "\n".join(output_parts)
