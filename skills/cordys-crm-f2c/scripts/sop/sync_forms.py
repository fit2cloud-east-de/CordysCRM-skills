import hashlib
import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError


MARKER_PREFIX = "===FILE:"
MARKER_SUFFIX = "==="
AUTO_START = "<!-- AUTO-GENERATED-START -->"
AUTO_END = "<!-- AUTO-GENERATED-END -->"
EXPECTED_SYNC_PATHS = {
    "references/forms/lead.md",
    "references/forms/account.md",
    "references/forms/opportunity.md",
    "references/forms/contact.md",
    "references/forms/follow.md",
    "references/forms/follow-plan.md",
    "references/forms/contract.md",
    "references/forms/payment-record.md",
    "references/field-schema.json",
}
EXPECTED_SCHEMA_MODULES = {
    "account",
    "contact",
    "contract",
    "contract/payment-record",
    "follow",
    "follow-plan",
    "lead",
    "opportunity",
}


def sync_forms(domain, access_key, secret_key, params=""):
    """
    Cordys CRM 表单同步工具 — 获取所有模块表单配置和产品列表，生成 references 文档内容。

    返回纯文本，用 ===FILE:path=== 分隔各文件内容，供本地 shell 直接写入。
    同一份结构化表单数据同时生成给 AI 阅读的 Markdown 与给 CLI 校验的 field-schema.json。

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

    default_modules = ["clue", "account", "opportunity", "contact", "follow", "follow-plan",
                       "contract", "payment-record"]
    modules = p.get("modules", default_modules)
    if not isinstance(modules, list) or not modules:
        raise ValueError("sync modules 必须是非空数组")
    if len(modules) != len(default_modules) or set(modules) != set(default_modules):
        raise ValueError("sync 必须全量刷新全部模块，避免 field-schema.json 混入其他时间或实例的旧快照")

    FORM_PATH_MAP = {
        "clue": "/lead/module/form",
        "lead": "/lead/module/form",
        "account": "/account/module/form",
        "opportunity": "/opportunity/module/form",
        "contact": "/module/form/config/contact",
        "follow": "/follow/record/module/form",
        "follow-plan": "/follow/plan/module/form",
        "contract": "/contract/module/form",
        "payment-record": "/contract/payment-record/module/form",
    }

    MODULE_TO_REF = {
        "clue": "lead", "account": "account",
        "opportunity": "opportunity", "contact": "contact",
        "follow": "follow", "follow-plan": "follow-plan",
        "contract": "contract", "payment-record": "payment-record",
    }
    unknown_modules = [module for module in modules if module not in FORM_PATH_MAP]
    if unknown_modules:
        raise ValueError(f"sync 不支持模块：{', '.join(map(str, unknown_modules))}")

    # 样本记录里值为 null 的顶层字段无法靠类型推断发现；这些系统字段是稳定 API 契约，
    # 显式合并可避免 schema 因某条样本恰好为空而漏字段。
    SYSTEM_QUERY_FIELDS = {
        "clue": {
            "stage": "SELECT", "createTime": "DATE_TIME", "updateTime": "DATE_TIME",
            "departmentId": "DEPARTMENT", "owner": "MEMBER", "follower": "MEMBER",
            "followTime": "DATE_TIME", "latestFollowUpTime": "DATE_TIME", "reservedDays": "INPUT_NUMBER",
            "reasonId": "MEMBER",
        },
        "account": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER", "follower": "MEMBER", "followTime": "DATE_TIME",
            "latestFollowUpTime": "DATE_TIME", "reasonId": "MEMBER",
        },
        "opportunity": {
            "stage": "SELECT", "lastStage": "INPUT", "createTime": "DATE_TIME", "updateTime": "DATE_TIME",
            "departmentId": "DEPARTMENT", "owner": "MEMBER", "follower": "MEMBER",
            "followTime": "DATE_TIME", "expectedEndTime": "DATE_TIME", "actualEndTime": "DATE_TIME",
            "stageUpdateTime": "DATE_TIME", "amount": "INPUT_NUMBER",
        },
        "contact": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER",
        },
        "contract": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER", "approvalStatus": "SELECT", "stage": "SELECT",
            "amount": "INPUT_NUMBER", "alreadyPayAmount": "INPUT_NUMBER",
        },
        "payment-record": {
            "createTime": "DATE_TIME", "updateTime": "DATE_TIME", "departmentId": "DEPARTMENT",
            "owner": "MEMBER", "recordEndTime": "DATE_TIME", "recordAmount": "INPUT_NUMBER",
        },
    }
    SYSTEM_QUERY_OPTIONS = {
        "clue": {
            "stage": [("新建", "NEW")],
        },
        "opportunity": {
            "stage": [
                ("新建", "CREATE"), ("需求确认", "CLEAR_REQUIREMENTS"),
                ("方案验证", "SCHEME_VALIDATION"), ("项目方案汇报", "PROJECT_PROPOSAL_REPORT"),
                ("商务采购", "BUSINESS_PROCUREMENT"), ("赢单", "SUCCESS"), ("输单", "FAIL"),
            ],
        },
        "contract": {
            "stage": [("待签署", "PENDING_SIGNING")],
        },
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
            raise RuntimeError(f"同步 {form_key} 表单失败：{resp.get('message') or resp.get('code') or '无响应'}")
        raw = [f for f in resp["data"]["fields"] if f["type"] != "DIVIDER"]

        # 建立 optionValue→label 映射，用于翻译联动规则
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

    # 查询字段参考：combineSearch.conditions 可用的 name/type。模块和跟进共用同一段生成逻辑。
    # skip 可覆盖默认过滤类型：跟进的 owner 是 MEMBER 但可用于查询（查"我的/某人的跟进"），
    # 所以 follow 传更宽松的 skip 保留 MEMBER。
    def gen_query_reference(fields, top_level_fields=None, skip=None):
        skip = SKIP_TYPES if skip is None else skip
        lines = []
        queryable = [f for f in fields if f["type"] not in skip]
        if not queryable and not top_level_fields:
            return lines
        lines.append("\n## 查询字段参考\n")
        lines.append("> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。\n")
        lines.append("> “系统/API”字段可能不显示为自定义表单控件或“表单 SELECT 字段可选值”列表；只要列在本表中，即可作为 conditions 的字段依据。\n")
        lines.append("| 字段 | name（条件用） | type | 来源 |")
        lines.append("|------|--------------|------|------|")
        top_level_names = {name for name, _ in (top_level_fields or [])}
        for name, ftype in (top_level_fields or []):
            lines.append(f"| {name} | {name} | {ftype} | 系统/API |")
        for f in queryable:
            if not str(f.get("name") or "").strip():
                continue
            cond_name = f.get("businessKey") or f.get("id", f["name"])
            # 顶层系统字段优先；表单里可能存在同 businessKey 的公式/展示字段（如 contract.amount）。
            if cond_name in top_level_names:
                continue
            lines.append(f"| {f['name']} | {cond_name} | {f['type']} | 表单 |")
        lines.append("")
        return lines

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
            lines.append("\n## 表单 SELECT 字段可选值\n")
            lines.append("> **创建和查询都传 ID**：标注「传 ID」的字段，中文与 ID 不一致，必须填 `=` 右侧的 ID（填中文会静默失败——创建写空、查询返回空）；未标注的字段中文即 ID，直接传中文即可。")
            lines.append("> 创建时 SELECT 字段放 `moduleFields` 的 `fieldValue`、产品放 `products`；查询时放 `combineSearch.conditions` 的 `value`。\n")
            lines.append("> 本节只列自定义表单字段；系统/API 的 SELECT 字段以“查询字段参考”为准。\n")
            for f in select_fields:
                pairs = f["label_to_value"]
                differ = any(label != value for label, value in pairs.items())
                if differ:
                    mapping = ", ".join(f"{label}={value}" for label, value in pairs.items())
                    lines.append(f"- **{f['name']}**（传 ID）：{mapping}")
                else:
                    lines.append(f"- **{f['name']}**：{', '.join(pairs.keys())}")
            if product_names:
                lines.append(f"- **产品类型（可多选）**（传 ID）：{', '.join(product_names)}")
            lines.append("")

        # 追加查询字段参考（combineSearch.conditions 可用的 name 和 type）
        lines.extend(gen_query_reference(fields, top_level_fields))

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

        # 3) 跟进方式可选值（记录表单 businessKey=followMethod，计划表单 businessKey=method）
        method_fields = [f for f in fields if f.get("businessKey") in ("followMethod", "method") and f.get("label_to_value")]
        if method_fields:
            lines.append("\n## 跟进方式可选值\n")
            for f in method_fields:
                for label, value in f["label_to_value"].items():
                    lines.append(f"- `{value}` = {label}")
            lines.append("")

        # 查询字段参考（与模块共用；跟进查询走 /{module}/follow/record/page，各宿主模块字段一致；
        # 保留 MEMBER 类型的 owner 供"查我的/某人跟进"）
        lines.extend(gen_query_reference(fields, skip={"SERIAL_NUMBER", "DIVIDER"}))

        return "\n".join(lines)

    # Fetch all forms
    all_fields = {}
    for m in modules:
        all_fields[m] = get_form_fields(m)

    # Fetch product list（保留 name=id，供创建时 products 字段直接取 ID，免去每次查 crm product）
    prod_resp = api("POST", "/field/source/product", {"current": 1, "pageSize": 200, "keyword": ""})
    product_names = [f'{item["name"]}={item["id"]}' for item in prod_resp.get("data", {}).get("list", [])] if prod_resp.get("code") == 100200 else []

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
        if key in ("owner", "follower"):
            return "MEMBER"
        if key == "departmentId":
            return "DEPARTMENT"
        if key.endswith("Id"):
            return "DATA_SOURCE"
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
        explicit = SYSTEM_QUERY_FIELDS.get(module_key, {})
        if resp.get("code") != 100200:
            return list(explicit.items())
        items = resp.get("data", {}).get("list", [])
        if not items:
            return list(explicit.items())
        record = items[0]
        # 表单字段的 businessKey 集合（已在表单列表里了，避免重复）
        form_biz_keys = {f.get("businessKey") for f in all_fields.get(module_key, []) if f.get("businessKey")}
        result = dict(explicit)
        for key, value in record.items():
            if key in SKIP_TOP_KEYS or key in form_biz_keys:
                continue
            if any(key.endswith(s) for s in SKIP_TOP_SUFFIXES):
                continue
            if isinstance(value, (list, dict)):
                continue
            ftype = infer_type(key, value)
            if ftype:
                result.setdefault(key, ftype)
        return list(result.items())

    # Build output
    output_parts = []
    field_schema = {"schemaVersion": 1, "modules": {}}

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
        if m in ("follow", "follow-plan"):
            snippet = gen_follow_snippet(all_fields[m])
        else:
            prods = product_names if m in modules_with_products else None
            top_fields = get_top_level_fields(m)
            snippet = gen_module_snippet(all_fields[m], prods, module=m, top_level_fields=top_fields,
                                         query_only=(m in QUERY_ONLY))
        # schema 与 Markdown 共用 all_fields/top_fields，避免反向解析 Markdown。
        # 字段 key 与 conditions.name 完全一致：businessKey 优先，否则用 fieldId。
        schema_fields = {}
        for name, field_type in (top_fields if m not in ("follow", "follow-plan") else []):
            schema_fields[name] = {
                "label": name, "type": field_type, "queryable": field_type not in {"DIVIDER", "PICTURE", "FORMULA", "SUB_PRODUCT", "SUB_PRICE"},
                "options": [
                    {"label": label, "value": value}
                    for label, value in SYSTEM_QUERY_OPTIONS.get(m, {}).get(name, [])
                ],
            }
        for field in all_fields[m]:
            if not str(field.get("name") or "").strip():
                continue
            condition_name = field.get("businessKey") or field.get("id", field["name"])
            # 显式系统字段来自稳定 API 契约，优先于表单中可能重名的公式/展示字段。
            if condition_name in schema_fields:
                continue
            schema_fields[condition_name] = {
                "label": field["name"],
                "type": field["type"],
                "queryable": field["type"] not in {"DIVIDER", "PICTURE", "INDUSTRY", "FORMULA", "SUB_PRODUCT", "SUB_PRICE"},
                "options": [
                    {"label": label, "value": value}
                    for label, value in field.get("label_to_value", {}).items()
                ],
            }
        field_schema["modules"][ref_name if ref_name != "payment-record" else "contract/payment-record"] = {
            "source": FORM_PATH_MAP.get(m, f"/{m}/module/form"),
            "fields": schema_fields,
        }

        output_parts.append(f"===FILE:references/forms/{ref_name}.md===")
        output_parts.append(snippet)

    output_parts.append("===FILE:references/field-schema.json===")
    output_parts.append(json.dumps(field_schema, ensure_ascii=False, indent=2, sort_keys=True))

    return "\n".join(output_parts)


def _parse_sync_sections(content):
    sections = {}
    current = None
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.splitlines():
        if line.startswith(MARKER_PREFIX) and line.endswith(MARKER_SUFFIX):
            relpath = line[len(MARKER_PREFIX):-len(MARKER_SUFFIX)]
            if relpath not in EXPECTED_SYNC_PATHS:
                raise ValueError(f"同步输出包含未授权路径：{relpath}")
            if relpath in sections:
                raise ValueError(f"同步输出包含重复文件段：{relpath}")
            sections[relpath] = []
            current = relpath
            continue
        if current is None:
            if line.strip():
                raise ValueError("同步输出在首个文件标记前包含意外内容")
            continue
        sections[current].append(line)

    actual = set(sections)
    if actual != EXPECTED_SYNC_PATHS:
        missing = sorted(EXPECTED_SYNC_PATHS - actual)
        extra = sorted(actual - EXPECTED_SYNC_PATHS)
        details = []
        if missing:
            details.append(f"缺少：{', '.join(missing)}")
        if extra:
            details.append(f"多出：{', '.join(extra)}")
        raise ValueError(f"同步输出文件集合不完整（{'；'.join(details)}）")
    return {relpath: "\n".join(lines) for relpath, lines in sections.items()}


def _replace_auto_section(original, snippet, relpath):
    if original.count(AUTO_START) != 1 or original.count(AUTO_END) != 1:
        raise ValueError(f"{relpath} 的 AUTO-GENERATED 标记缺失或重复")
    start = original.index(AUTO_START) + len(AUTO_START)
    end = original.index(AUTO_END, start)
    return f"{original[:start]}\n{snippet.strip()}\n{original[end:]}"


def _write_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _sync_lock(project_dir, timeout=30):
    """Serialize only the local commit phase; API fetching can still happen in parallel."""
    lock_id = hashlib.sha256(str(project_dir).encode("utf-8")).hexdigest()[:20]
    lock_path = Path(tempfile.gettempdir()) / f"cordys-crm-sync-{lock_id}.lock"
    lock_file = lock_path.open("a+b")
    deadline = time.monotonic() + timeout
    locked = False
    try:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        while not locked:
            try:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("等待另一个表单同步完成超时")
                time.sleep(0.1)
        yield
    finally:
        if locked:
            try:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        lock_file.close()


def apply_sync_output(project_dir, content):
    """Validate all generated sections, then commit them with rollback on any failure."""
    project_dir = Path(project_dir).resolve()
    references_dir = project_dir / "references"
    forms_dir = references_dir / "forms"
    if not references_dir.is_dir() or not forms_dir.is_dir():
        raise ValueError(f"同步目标目录无效：{project_dir}")

    sections = _parse_sync_sections(content)
    schema = json.loads(sections["references/field-schema.json"])
    if schema.get("schemaVersion") != 1 or not isinstance(schema.get("modules"), dict):
        raise ValueError("field-schema.json 缺少 schemaVersion=1 或 modules 对象")
    actual_modules = set(schema["modules"])
    if actual_modules != EXPECTED_SCHEMA_MODULES:
        missing = sorted(EXPECTED_SCHEMA_MODULES - actual_modules)
        extra = sorted(actual_modules - EXPECTED_SCHEMA_MODULES)
        details = []
        if missing:
            details.append(f"缺少：{', '.join(missing)}")
        if extra:
            details.append(f"多出：{', '.join(extra)}")
        raise ValueError(f"field-schema.json 模块集合不完整（{'；'.join(details)}）")

    with _sync_lock(project_dir):
        rendered = {}
        for relpath, snippet in sections.items():
            target = project_dir / Path(relpath)
            try:
                target.relative_to(project_dir)
            except ValueError as exc:
                raise ValueError(f"同步目标越界：{relpath}") from exc

            if relpath.endswith(".json"):
                rendered[relpath] = (
                    json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                ).encode("utf-8")
                continue

            if not target.is_file():
                raise FileNotFoundError(f"同步目标不存在：{target}")
            original = target.read_text(encoding="utf-8-sig")
            rendered[relpath] = _replace_auto_section(original, snippet, relpath).encode("utf-8")

        stage_dir = Path(tempfile.mkdtemp(prefix=".sync-stage-", dir=str(references_dir)))
        backup_dir = stage_dir / "backups"
        ready_dir = stage_dir / "ready"
        targets = []
        committed = []
        stamp = forms_dir / ".last_sync"
        stamp_backup = None
        stamp_existed = stamp.exists()

        try:
            for relpath in sorted(rendered):
                target = project_dir / Path(relpath)
                ready = ready_dir / Path(relpath)
                backup = backup_dir / Path(relpath)
                _write_bytes(ready, rendered[relpath])
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                targets.append((relpath, target, ready, backup))

            if stamp_existed:
                stamp_backup = backup_dir / "references" / "forms" / ".last_sync"
                stamp_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(stamp, stamp_backup)

            for relpath, target, ready, backup in targets:
                committed.append((relpath, target, backup))
                os.replace(ready, target)

            stamp_ready = ready_dir / "references" / "forms" / ".last_sync"
            _write_bytes(stamp_ready, f"{int(time.time())}\n".encode("ascii"))
            os.replace(stamp_ready, stamp)
        except BaseException as apply_error:
            rollback_errors = []
            for relpath, target, backup in reversed(committed):
                try:
                    os.replace(backup, target)
                except Exception as exc:
                    rollback_errors.append(f"{relpath}: {exc}")
            try:
                if stamp_existed and stamp_backup is not None and stamp_backup.exists():
                    os.replace(stamp_backup, stamp)
                elif not stamp_existed and stamp.exists():
                    stamp.unlink()
            except Exception as exc:
                rollback_errors.append(f".last_sync: {exc}")
            if rollback_errors:
                raise RuntimeError(
                    "同步失败且回滚不完整：" + "；".join(rollback_errors)
                ) from apply_error
            raise
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)
