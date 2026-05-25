#!/usr/bin/env python3
"""
Cordys CRM 扩展 CLI
封装官方 CLI 不支持的写入类操作（创建线索、客户、商机、联系人）
"""
import json
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import cordys as _cordys


def die(msg):
    _cordys.die(msg)


def api(method, path, data=None):
    """调用 API 并返回解析后的 dict"""
    url = f"{_cordys.CORDYS_CRM_DOMAIN}{path}"
    if data is not None:
        raw = _cordys.api(method, url,
                          data=json.dumps(data, ensure_ascii=False).encode("utf-8"))
    else:
        raw = _cordys.api(method, url)
    return json.loads(raw)

CACHE_DIR = SCRIPT_DIR / ".cache"
CACHE_TTL = 6 * 3600  # 6 小时

FORM_PATH_MAP = {
    "clue": "/lead/module/form",
    "lead": "/lead/module/form",
    "account": "/account/module/form",
    "opportunity": "/opportunity/module/form",
    "contact": "/module/form/config/contact",
}


def _read_cache(cache_file):
    """读取缓存文件，过期返回 None"""
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text("utf-8"))
            if time.time() - data.get("_ts", 0) < CACHE_TTL:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _write_cache(cache_file, data):
    """写入缓存文件"""
    CACHE_DIR.mkdir(exist_ok=True)
    data["_ts"] = time.time()
    cache_file.write_text(json.dumps(data, ensure_ascii=False), "utf-8")


def _fetch_form_from_api(form_key):
    """从 API 拉取表单配置"""
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
            "id": f["id"],
            "name": f["name"],
            "key": f.get("internalKey") or "",
            "businessKey": f.get("businessKey") or "",
            "type": f["type"],
            "required": required,
            "label_to_value": label_to_value,
        })
    return fields


def get_form_config(form_key, force_refresh=False):
    """获取表单配置（带文件缓存，6 小时 TTL）"""
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


# ── 产品名称→ID 转换 ─────────────────────────────────────────────────

def get_product_map(force_refresh=False):
    """获取产品名称→ID 映射（带文件缓存）"""
    cache_file = CACHE_DIR / "product_map.json"

    if not force_refresh:
        cached = _read_cache(cache_file)
        if cached:
            return cached["map"]

    resp = api("POST", "/field/source/product", {
        "current": 1, "pageSize": 200, "keyword": ""
    })
    if resp.get("code") != 100200:
        cached = _read_cache(cache_file) if not force_refresh else None
        if cached:
            return cached["map"]
        return {}

    product_map = {item["name"]: item["id"] for item in resp["data"].get("list", [])}
    _write_cache(cache_file, {"map": product_map})
    return product_map


def resolve_products(products):
    """将产品名称列表转换为 ID 列表，已经是 ID 的保持不变"""
    if not products:
        return []
    product_map = get_product_map()
    result = []
    for p in products:
        if p in product_map:
            result.append(product_map[p])
        else:
            result.append(p)
    return result


# ── 标签模糊匹配 ─────────────────────────────────────────────────────

_ZERO_WIDTH_RE = re.compile(r'[​-‏ - ⁠﻿]')


def _normalize(s):
    """去除零宽字符、统一全半角"""
    return _ZERO_WIDTH_RE.sub('', unicodedata.normalize('NFKC', s)).strip()


def _fuzzy_match_label(value, label_to_value):
    """模糊匹配：前缀匹配 + 去零宽字符"""
    norm_value = _normalize(value)
    for label, mapped in label_to_value.items():
        norm_label = _normalize(label)
        if norm_label == norm_value:
            return mapped
        if norm_label.startswith(norm_value) and len(norm_value) >= 2:
            return mapped
    return None


# ── 通用创建 ─────────────────────────────────────────────────────────

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
    """根据字段配置和参数构建请求 body"""
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
                        dt = datetime.strptime(value, "%Y-%m-%d")
                        value = int(time.mktime(dt.timetuple()) * 1000)
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

    unused_keys = {k for k in body if body[k] == "" and k not in ("type", "id", "moduleFields")}
    for k in unused_keys:
        del body[k]

    return body


def create_entity(module, params):
    """通用创建函数，含容错重试机制。"""
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


def create_lead(params):
    return create_entity("lead", params)


def create_account(params):
    return create_entity("account", params)


def create_opportunity(params):
    return create_entity("opportunity", params)


def create_contact(params):
    return create_entity("contact", params)


# ── 线索转换 ─────────────────────────────────────────────────────────

def transform_lead(params):
    """线索转客户（+商机），转换后补全联系人缺失字段。"""
    clue_id = params.get("clueId")
    if not clue_id:
        die("transform 需要 clueId")

    opp_name = params.get("oppName", "")
    opp_created = params.get("oppCreated", bool(opp_name))

    body = {"clueId": clue_id, "oppName": opp_name, "oppCreated": opp_created}
    result = api("POST", "/lead/transform", body)

    if result.get("code") != 100200:
        return result

    # 转换后补全联系人的电话和邮件（转换 API 不带这两个字段）
    fields = get_form_config("contact")
    field_name_to_id = {f["name"]: f["id"] for f in fields}

    extra_fields = []
    for name in ("电话", "电子邮件"):
        if params.get(name) and name in field_name_to_id:
            extra_fields.append({"fieldId": field_name_to_id[name], "fieldValue": params[name]})

    if extra_fields and params.get("contactName"):
        keyword = params.get("phone") or params.get("contactName")
        resp = api("POST", "/global/search/contact", {
            "keyword": keyword, "pageSize": 5, "current": 1
        })
        contacts = resp.get("data", {}).get("list", [])
        for c in contacts:
            if c.get("name") == params["contactName"]:
                api("POST", "/account/contact/update", {
                    "id": c["id"],
                    "customerId": c.get("customerId", ""),
                    "moduleFields": extra_fields,
                })
                break

    return result


# ── 同步命令 ─────────────────────────────────────────────────────────

def sync_forms(modules=None):
    """强制刷新表单缓存"""
    if modules is None:
        modules = ["clue", "account", "opportunity", "contact"]
    for m in modules:
        fields = get_form_config(m, force_refresh=True)
        print(f"已同步 {m}: {len(fields)} 个字段", file=sys.stderr)
    get_product_map(force_refresh=True)
    print("已同步产品列表", file=sys.stderr)

    from sync_docs import update_all_docs
    update_all_docs()
    print("已同步 references 文档", file=sys.stderr)


# ── CLI 入口 ─────────────────────────────────────────────────────────

USAGE = """cordys-ext — Cordys CRM 扩展 CLI

用法:
  cordys-ext check <JSON>                      查重（返回结构化结果）
  cordys-ext form <module>                     获取表单配置（含必填标记）
  cordys-ext create lead <JSON>                创建线索
  cordys-ext create account <JSON>             创建客户
  cordys-ext create opportunity <JSON>         创建商机
  cordys-ext create contact <JSON>             创建联系人
  cordys-ext transform <JSON>                  线索转客户（+商机）
  cordys-ext sync [module]                     强制刷新表单缓存
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
        from check import check_duplicate
        result = check_duplicate(params)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "form":
        if len(sys.argv) < 3:
            die("form 需要指定 formKey（如 clue、account、opportunity、contact）")
        form_key = sys.argv[2]
        fields = get_form_config(form_key)
        print(json.dumps(fields, ensure_ascii=False, indent=2))

    elif cmd == "create":
        if len(sys.argv) < 4:
            die("create 需要指定模块和 JSON 参数")
        module = sys.argv[2]
        payload = sys.argv[3]
        try:
            params = json.loads(payload)
        except json.JSONDecodeError as e:
            die(f"JSON 解析失败: {e}")

        if module in ENTITY_CONFIG:
            result = create_entity(module, params)
        else:
            die(f"不支持的模块: {module}")

        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "transform":
        if len(sys.argv) < 3:
            die("transform 需要 JSON 参数（含 clueId）")
        try:
            params = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            die(f"JSON 解析失败: {e}")
        result = transform_lead(params)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "sync":
        modules = [sys.argv[2]] if len(sys.argv) > 2 else None
        sync_forms(modules)
        print(json.dumps({"status": "ok"}, ensure_ascii=False))

    else:
        die(f"未知命令: {cmd}（尝试 cordys-ext help）")


if __name__ == "__main__":
    main()
