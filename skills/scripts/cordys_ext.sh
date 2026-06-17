#!/usr/bin/env bash
# Cordys CRM 扩展 CLI（Shell 版）
# 兼容 macOS / Linux / Windows (Git Bash / WSL)

set -eo nounset
set -o pipefail 2>/dev/null || true  # Bash 3.2 (macOS default) doesn't support pipefail in set -e
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${PROJECT_DIR}/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

CORDYS_CRM_DOMAIN="${CORDYS_CRM_DOMAIN:-https://www.cordys.cn}"
MAXKB_DOMAIN="${MAXKB_DOMAIN:-}"
MAXKB_API_KEY="${MAXKB_API_KEY:-}"

die() { echo "错误: $*" >&2; exit 1; }

# ── Python 探测（兼容 macOS / Linux / Windows Git Bash / WSL）────────────
PYTHON_CMD=()
detect_python() {
  if [[ -n "${CORDYS_PYTHON:-}" ]] && "${CORDYS_PYTHON}" -c 'import sys' >/dev/null 2>&1; then
    PYTHON_CMD=("${CORDYS_PYTHON}")
    return
  fi
  local cmd
  for cmd in python3 python python.exe; do
    if command -v "$cmd" >/dev/null 2>&1 && "$cmd" -c 'import sys' >/dev/null 2>&1; then
      PYTHON_CMD=("$cmd")
      return
    fi
  done
  if command -v py >/dev/null 2>&1 && py -3 -c 'import sys' >/dev/null 2>&1; then
    PYTHON_CMD=(py -3)
    return
  fi
  die "未找到可用 Python，请安装 Python 3 或设置 CORDYS_PYTHON"
}

detect_python

# 清除代理环境变量，避免被调用方（如 workbuddy）的代理设置干扰 curl
# 注：所有 curl 调用均已加 --noproxy '*'，此行作为兜底保留

check_keys() {
  [[ -n "${CORDYS_ACCESS_KEY:-}" ]] || die "未设置 CORDYS_ACCESS_KEY"
  [[ -n "${CORDYS_SECRET_KEY:-}" ]] || die "未设置 CORDYS_SECRET_KEY"
}

# ── 远程调用公共函数 ─────────────────────────────────────────────────────

_call_remote() {
  local operation="$1" params="$2"
  [[ -n "$MAXKB_DOMAIN" ]] || die "未设置 MAXKB_DOMAIN"
  [[ -n "$MAXKB_API_KEY" ]] || die "未设置 MAXKB_API_KEY"
  check_keys

  # 获取当前用户名
  local asker=""
  local user_resp
  user_resp=$(curl -s --noproxy '*' --connect-timeout 10 --max-time 15 \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "Content-Type: application/json;charset=UTF-8" \
    "${CORDYS_CRM_DOMAIN}/personal/center/info")
  asker=$(echo "$user_resp" | grep -o '"userName": *"[^"]*"' | grep -o '"[^"]*"$' | tr -d '"')

  # 获取 chat_id
  local chat_id
  chat_id=$(curl -s --noproxy '*' --connect-timeout 10 --max-time 15 \
    -H "Authorization: Bearer ${MAXKB_API_KEY}" \
    "${MAXKB_DOMAIN}/chat/api/open" | grep -o '"data": *"[^"]*"' | grep -o '"[^"]*"$' | tr -d '"')

  [[ -n "$chat_id" ]] || die "获取 chat_id 失败"

  # 构建请求体，通过管道传给 curl 避免中文编码问题。
  # params 本身是 JSON 文本，作为字符串值再嵌入外层 JSON 信封时必须逐字符转义。
  # ⚠️ 顺序关键：反斜杠必须最先转，否则会把后续转义新产生的反斜杠二次破坏。
  # 转义不全会导致信封破损、MaxKB 解析失败，而记录实际已写入 → 写操作"假失败真成功"，
  # AI 据此重试就会产生重复数据（已踩坑）。用 sed 字节级转义，不引入编码问题。
  # 写法说明：s/[\]/&&/g 用字符类匹配单反斜杠、& 重复成双反斜杠（Git Bash sed 对
  # s/\\/.../ 写法会报 unterminated，故用此等价写法）。
  local escaped_params
  escaped_params=$(printf '%s' "$params" | sed -e 's/[\]/&&/g' -e 's/"/\\"/g')

  local resp
  resp=$(printf '{"message":"%s","stream":false,"re_chat":false,"form_data":{"operation":"%s","access_key":"%s","secret_key":"%s","domain":"%s","asker":"%s","params":"%s"}}' \
    "$operation" "$operation" "$CORDYS_ACCESS_KEY" "$CORDYS_SECRET_KEY" "$CORDYS_CRM_DOMAIN" "$asker" "$escaped_params" \
    | curl -s --noproxy '*' --connect-timeout 10 --max-time 120 -X POST \
      -H "Authorization: Bearer ${MAXKB_API_KEY}" \
      -H "Content-Type: application/json;charset=UTF-8" \
      -d @- \
      "${MAXKB_DOMAIN}/chat/api/chat_message/${chat_id}")

  # 提取 content 字段并解码转义（MaxKB 返回为 JSON，content 在 data.content 层级）。
  # 全文正则抓取 "content":"..."，不依赖层级；再还原 \" 和 \\ 转义。
  local content
  content=$(printf '%s' "$resp" | sed -n 's/.*"content": *"\(.*\)", *"operate".*/\1/p' | sed 's/\\"/"/g; s/\\\\/\\/g') || true
  if [[ -z "$content" ]]; then
    content=$(printf '%s' "$resp" | sed -n 's/.*"content": *"\(.*\)", *"is_end".*/\1/p' | sed 's/\\"/"/g; s/\\\\/\\/g') || true
  fi
  printf '%b' "$content"
  echo
}

# ── 自动同步 ─────────────────────────────────────────────────────────────

SYNC_STAMP="${PROJECT_DIR}/references/forms/.last_sync"
SYNC_INTERVAL=21600  # 6 hours

_needs_sync() {
  [[ ! -f "$SYNC_STAMP" ]] && return 0
  local last now diff
  last=$(cat "$SYNC_STAMP" 2>/dev/null || echo 0)
  now=$(date +%s)
  diff=$((now - last))
  [[ $diff -ge $SYNC_INTERVAL ]]
}

_mark_synced() {
  date +%s > "$SYNC_STAMP"
}

_auto_sync() {
  if _needs_sync; then
    cmd_sync >/dev/null 2>&1 && _mark_synced
  fi
}

# ── 命令 ─────────────────────────────────────────────────────────────────

cmd_check() {
  _call_remote "check_repeat" "${1:?用法: cordys-ext check '<JSON>'}"
}

cmd_create() {
  _auto_sync
  local module="${1:?用法: cordys-ext create <module> '<JSON>'}"
  local raw_params="${2:?用法: cordys-ext create <module> '<JSON>'}"

  # 注入 module 到 params
  local params
  params=$(echo "$raw_params" | sed 's/^{/{"module":"'"$module"'",/')

  local result
  result=$(_call_remote "create" "$params")
  echo "$result"

  # 创建失败时触发同步
  if echo "$result" | grep -q '"error"'; then
    cmd_sync >/dev/null 2>&1 && _mark_synced
  fi
}

cmd_follow() {
  _auto_sync
  local result
  result=$(_call_remote "add_follow_record" "${1:?用法: cordys-ext follow '<JSON>'}")
  echo "$result"

  if echo "$result" | grep -q '"error"'; then
    cmd_sync >/dev/null 2>&1 && _mark_synced
  fi
}

cmd_transform() {
  _auto_sync
  _call_remote "transform_lead" "${1:?用法: cordys-ext transform '<JSON>'}"
}

cmd_form() {
  _auto_sync
  _call_remote "get_form" "{\"module\":\"${1:?用法: cordys-ext form <module>}\"}"
}

cmd_update() {
  local module="${1:?用法: cordys-ext update <module> <id> '<JSON>'}"
  local id="${2:?用法: cordys-ext update <module> <id> '<JSON>'}"
  local raw_params="${3:?用法: cordys-ext update <module> <id> '<JSON>'}"
  check_keys

  # 获取当前记录
  local current
  current=$(curl -s --noproxy '*' --connect-timeout 10 --max-time 15 \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "X-Request-Source: SKILL" \
    -H "Content-Type: application/json;charset=UTF-8" \
    "${CORDYS_CRM_DOMAIN}/${module}/get/${id}")

  # 获取表单配置
  local form_path
  case "$module" in
    contact) form_path="/module/form/config/contact" ;;
    *)       form_path="/${module}/module/form" ;;
  esac
  local form_config
  form_config=$(curl -s --noproxy '*' --connect-timeout 10 --max-time 15 \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "X-Request-Source: SKILL" \
    -H "Content-Type: application/json;charset=UTF-8" \
    "${CORDYS_CRM_DOMAIN}${form_path}")

  # 获取产品列表（用于名称→ID转换）
  local product_list
  product_list=$(curl -s --noproxy '*' --connect-timeout 10 --max-time 15 \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "X-Request-Source: SKILL" \
    -H "Content-Type: application/json;charset=UTF-8" \
    -X POST -d '{"current":1,"pageSize":200,"keyword":""}' \
    "${CORDYS_CRM_DOMAIN}/field/source/product")

  # Python 合并逻辑：字段转换 + 构建 update body，输出临时文件路径或 JSON 错误
  local py_output
  py_output=$(CORDYS_UPD_MODULE="$module" \
  CORDYS_UPD_ID="$id" \
  CORDYS_UPD_PARAMS="$raw_params" \
  CORDYS_UPD_CURRENT="$current" \
  CORDYS_UPD_FORM="$form_config" \
  CORDYS_UPD_PRODUCTS="$product_list" \
  "${PYTHON_CMD[@]}" <<'PY'
import json, os, sys, re, unicodedata, time, tempfile
from datetime import datetime

module = os.environ['CORDYS_UPD_MODULE']
record_id = os.environ['CORDYS_UPD_ID']
raw_params = os.environ['CORDYS_UPD_PARAMS']
current_json = os.environ['CORDYS_UPD_CURRENT']
form_json = os.environ['CORDYS_UPD_FORM']
product_json = os.environ['CORDYS_UPD_PRODUCTS']

# ── 解析输入 ──
try:
    params = json.loads(raw_params)
except json.JSONDecodeError as e:
    print(json.dumps({"error": f"params JSON 解析失败: {e}"}, ensure_ascii=False))
    sys.exit(0)

try:
    current_resp = json.loads(current_json)
except json.JSONDecodeError:
    print(json.dumps({"error": "获取当前记录失败：响应解析错误"}, ensure_ascii=False))
    sys.exit(0)

if current_resp.get("code") != 100200:
    msg = current_resp.get("message", "") or ""
    print(json.dumps({"error": f"获取当前记录失败: {msg}"}, ensure_ascii=False))
    sys.exit(0)

record = current_resp.get("data")
if not record:
    print(json.dumps({"error": "记录不存在或无权访问"}, ensure_ascii=False))
    sys.exit(0)

try:
    form_resp = json.loads(form_json)
except json.JSONDecodeError:
    print(json.dumps({"error": "获取表单配置失败：响应解析错误"}, ensure_ascii=False))
    sys.exit(0)

if form_resp.get("code") != 100200:
    print(json.dumps({"error": "获取表单配置失败"}, ensure_ascii=False))
    sys.exit(0)

# ── 产品映射 ──
product_map = {}
try:
    prod_resp = json.loads(product_json)
    if prod_resp.get("code") == 100200:
        for item in prod_resp.get("data", {}).get("list", []):
            product_map[item["name"]] = item["id"]
except (json.JSONDecodeError, KeyError):
    pass

# ── 表单字段解析 ──
TOP_LEVEL_BIZ_KEYS = {"name", "contact", "phone", "owner", "products",
                      "customerId", "contactId", "amount", "expectedEndTime", "possible"}
NUMERIC_BIZ_KEYS = {"amount", "possible"}
TIMESTAMP_BIZ_KEYS = {"expectedEndTime"}

fields = []
for f in form_resp["data"]["fields"]:
    if f["type"] == "DIVIDER":
        continue
    label_to_value = {o["label"]: o["value"] for o in (f.get("options") or [])}
    fields.append({
        "id": f["id"], "name": f["name"],
        "key": f.get("internalKey") or "",
        "businessKey": f.get("businessKey") or "",
        "type": f["type"],
        "label_to_value": label_to_value,
    })

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

# ── 构建字段查找索引 ──
field_by_name = {}
field_by_key = {}
field_by_bk = {}
for f in fields:
    if f["name"]:
        field_by_name[f["name"]] = f
        # 去括号前缀也索引
        prefix = f["name"].split("(")[0].split("（")[0]
        if prefix != f["name"]:
            field_by_name[prefix] = f
    if f["key"]:
        field_by_key[f["key"]] = f
    if f["businessKey"]:
        field_by_bk[f["businessKey"]] = f

def find_field(param_key):
    """根据用户传入的键名找到对应的表单字段"""
    if param_key in field_by_bk:
        return field_by_bk[param_key]
    if param_key in field_by_key:
        return field_by_key[param_key]
    if param_key in field_by_name:
        return field_by_name[param_key]
    # 前缀模糊
    for name, f in field_by_name.items():
        if name.startswith(param_key) and len(param_key) >= 2:
            return f
    return None

# ── 构建 update body ──
# 从现有记录继承基础结构
body = {"id": record_id, "moduleFields": []}

# 继承现有顶层业务字段
for bk in TOP_LEVEL_BIZ_KEYS:
    if bk in record:
        body[bk] = record[bk]

# 现有 moduleFields 转为 dict 方便合并
existing_mf = {}
for mf in record.get("moduleFields", []):
    existing_mf[mf["fieldId"]] = mf["fieldValue"]

# 处理用户传入的更新字段
for param_key, param_value in params.items():
    field = find_field(param_key)
    if field is None:
        # 可能是顶层字段直接传
        if param_key in TOP_LEVEL_BIZ_KEYS:
            if param_key == "products":
                if isinstance(param_value, str):
                    param_value = [param_value]
                body[param_key] = [product_map.get(p, p) for p in param_value]
            elif param_key in TIMESTAMP_BIZ_KEYS:
                if isinstance(param_value, str) and param_value:
                    try:
                        param_value = int(time.mktime(datetime.strptime(param_value, "%Y-%m-%d").timetuple()) * 1000)
                    except ValueError:
                        pass
                body[param_key] = param_value
            elif param_key in NUMERIC_BIZ_KEYS:
                if isinstance(param_value, str):
                    try:
                        param_value = float(param_value)
                    except ValueError:
                        pass
                body[param_key] = param_value
            else:
                body[param_key] = param_value
        continue

    bk = field["businessKey"]
    # 顶层业务字段
    if bk and bk in TOP_LEVEL_BIZ_KEYS:
        if bk == "products":
            if isinstance(param_value, str):
                param_value = [param_value]
            body[bk] = [product_map.get(p, p) for p in param_value]
        elif bk in TIMESTAMP_BIZ_KEYS:
            if isinstance(param_value, str) and param_value:
                try:
                    param_value = int(time.mktime(datetime.strptime(param_value, "%Y-%m-%d").timetuple()) * 1000)
                except ValueError:
                    pass
            body[bk] = param_value
        elif bk in NUMERIC_BIZ_KEYS:
            if isinstance(param_value, str):
                try:
                    param_value = float(param_value)
                except ValueError:
                    pass
            body[bk] = param_value
        else:
            body[bk] = param_value
    else:
        # moduleFields 字段
        value = param_value
        if isinstance(value, list):
            value = ",".join(str(v) for v in value)
        # 产品类型字段：名称→ID 转换
        if "产品" in field["name"] and field["type"] == "DATA_SOURCE" and str(value):
            parts = [v.strip() for v in str(value).split(",")]
            resolved = [product_map.get(name, name) for name in parts]
            value = ",".join(resolved)
        elif field.get("label_to_value") and str(value) in field["label_to_value"]:
            value = field["label_to_value"][str(value)]
        elif field.get("label_to_value") and str(value):
            matched = _fuzzy_match(str(value), field["label_to_value"])
            if matched:
                value = matched
        if field["type"] == "INPUT_NUMBER" and value != "":
            try:
                value = float(value)
            except (ValueError, TypeError):
                pass
        existing_mf[field["id"]] = value if not isinstance(value, str) else str(value)

# 将合并后的 moduleFields 写入 body
body["moduleFields"] = [{"fieldId": fid, "fieldValue": fval} for fid, fval in existing_mf.items()]

# 清理空值顶层字段（保留 id 和 moduleFields）
for k in list(body.keys()):
    if k in ("id", "moduleFields"):
        continue
    if body[k] is None or body[k] == "":
        del body[k]

import tempfile
tmpfile = os.path.join(tempfile.gettempdir(), f'cordys_update_{os.getpid()}.json')
with open(tmpfile, 'w', encoding='utf-8') as f:
    json.dump(body, f, ensure_ascii=False)
print(tmpfile)
PY
  )

  # 检查 python 输出是错误 JSON 还是临时文件路径
  if [[ "$py_output" == \{* ]]; then
    echo "$py_output"
    return 1
  fi

  local body_file="$py_output"
  [[ -f "$body_file" ]] || die "构建更新请求失败"

  # 调用 update API
  local result
  result=$(curl -s --noproxy '*' --connect-timeout 10 --max-time 30 \
    -X POST \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "X-Request-Source: SKILL" \
    -H "Content-Type: application/json;charset=UTF-8" \
    --data-binary "@${body_file}" \
    "${CORDYS_CRM_DOMAIN}/${module}/update")

  rm -f "$body_file"
  echo "$result"
}

cmd_batch_update() {
  local module="${1:?用法: cordys-ext batch-update <module> <fieldId> <fieldValue> <id1,id2,...>}"
  local field_id="${2:?用法: cordys-ext batch-update <module> <fieldId> <fieldValue> <id1,id2,...>}"
  local field_value="${3:?用法: cordys-ext batch-update <module> <fieldId> <fieldValue> <id1,id2,...>}"
  local ids_csv="${4:?用法: cordys-ext batch-update <module> <fieldId> <fieldValue> <id1,id2,...>}"
  check_keys

  # 将逗号分隔的 ID 转为 JSON 数组
  local ids_json
  ids_json=$(printf '%s' "$ids_csv" | "${PYTHON_CMD[@]}" -c "
import sys, json
ids = [i.strip() for i in sys.stdin.read().split(',') if i.strip()]
print(json.dumps(ids))
")

  local body
  body=$(printf '{"ids":%s,"fieldId":"%s","fieldValue":"%s"}' "$ids_json" "$field_id" "$field_value")

  local result
  result=$(curl -s --noproxy '*' --connect-timeout 10 --max-time 30 \
    -X POST \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "X-Request-Source: SKILL" \
    -H "Content-Type: application/json;charset=UTF-8" \
    -d "$body" \
    "${CORDYS_CRM_DOMAIN}/${module}/batch/update")

  echo "$result"
}

# ── 公海/线索池操作（领取/分配/移入池，纯 shell+curl）─────────────────────

# 公共：POST JSON body 到指定路径，回显响应
_pool_post() {
  local path="$1" body="$2"
  curl -s --noproxy '*' --connect-timeout 10 --max-time 30 \
    -X POST \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "X-Request-Source: SKILL" \
    -H "Content-Type: application/json;charset=UTF-8" \
    -d "$body" \
    "${CORDYS_CRM_DOMAIN}${path}"
}

# 逗号分隔 ID → JSON 数组
_csv_to_json_array() {
  printf '%s' "$1" | "${PYTHON_CMD[@]}" -c "
import sys, json
print(json.dumps([i.strip() for i in sys.stdin.read().split(',') if i.strip()]))
"
}

# PLACEHOLDER_POOL

cmd_pool() {
  local action="${1:-}"; shift || die "pool 需要指定动作（pick/assign/to-pool/options/page）"
  local module="${1:-}"; shift || die "pool ${action} 需要指定模块（lead/account）"
  case "$module" in
    lead|account) ;;
    *) die "不支持的模块: ${module}（仅 lead/account）" ;;
  esac
  check_keys

  # 模块 → 各操作的路径前缀与 ID 字段名
  local id_key pool_get_prefix to_pool_path batch_to_pool_path
  if [[ "$module" == "lead" ]]; then
    id_key="clueId"
    to_pool_path="/lead/to-pool"
    batch_to_pool_path="/lead/batch/to-pool"
  else
    id_key="customerId"
    to_pool_path="/account/to-pool"
    batch_to_pool_path="/account/batch/to-pool"
  fi

  case "$action" in
    options)
      # 获取当前用户可见的池子选项（拿 poolId）
      curl -s --noproxy '*' --connect-timeout 10 --max-time 15 \
        -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
        -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
        -H "X-Request-Source: SKILL" \
        -H "Content-Type: application/json;charset=UTF-8" \
        "${CORDYS_CRM_DOMAIN}/pool/${module}/options"
      ;;
    page)
      # 池子记录分页，body 透传（默认空查询）
      _pool_post "/pool/${module}/page" "${1:-{\"current\":1,\"pageSize\":20\}}"
      ;;
    pick)
      # 领取（领到自己名下）：<id> <poolId>
      local rid="${1:?用法: pool pick ${module} <id> <poolId>}"
      local pool_id="${2:?用法: pool pick ${module} <id> <poolId>}"
      _pool_post "/pool/${module}/pick" \
        "$(printf '{"%s":"%s","poolId":"%s"}' "$id_key" "$rid" "$pool_id")"
      ;;
    batch-pick)
      # 批量领取：<id1,id2,...> <poolId>
      local ids_csv="${1:?用法: pool batch-pick ${module} <id1,id2,...> <poolId>}"
      local pool_id="${2:?用法: pool batch-pick ${module} <id1,id2,...> <poolId>}"
      local ids_json; ids_json=$(_csv_to_json_array "$ids_csv")
      _pool_post "/pool/${module}/batch-pick" \
        "$(printf '{"batchIds":%s,"poolId":"%s"}' "$ids_json" "$pool_id")"
      ;;
    assign)
      # 分配（指派给他人）：<id> <assignUserId>
      local rid="${1:?用法: pool assign ${module} <id> <assignUserId>}"
      local uid="${2:?用法: pool assign ${module} <id> <assignUserId>}"
      _pool_post "/pool/${module}/assign" \
        "$(printf '{"%s":"%s","assignUserId":"%s"}' "$id_key" "$rid" "$uid")"
      ;;
    batch-assign)
      # 批量分配：<id1,id2,...> <assignUserId>
      local ids_csv="${1:?用法: pool batch-assign ${module} <id1,id2,...> <assignUserId>}"
      local uid="${2:?用法: pool batch-assign ${module} <id1,id2,...> <assignUserId>}"
      local ids_json; ids_json=$(_csv_to_json_array "$ids_csv")
      _pool_post "/pool/${module}/batch-assign" \
        "$(printf '{"batchIds":%s,"assignUserId":"%s"}' "$ids_json" "$uid")"
      ;;
    to-pool)
      # 移入池/退回：<id> [reasonId]
      local rid="${1:?用法: pool to-pool ${module} <id> [reasonId]}"
      local reason="${2:-}"
      if [[ -n "$reason" ]]; then
        _pool_post "$to_pool_path" "$(printf '{"id":"%s","reasonId":"%s"}' "$rid" "$reason")"
      else
        _pool_post "$to_pool_path" "$(printf '{"id":"%s"}' "$rid")"
      fi
      ;;
    batch-to-pool)
      # 批量移入池：<id1,id2,...> [reasonId]
      local ids_csv="${1:?用法: pool batch-to-pool ${module} <id1,id2,...> [reasonId]}"
      local reason="${2:-}"
      local ids_json; ids_json=$(_csv_to_json_array "$ids_csv")
      if [[ -n "$reason" ]]; then
        _pool_post "$batch_to_pool_path" "$(printf '{"ids":%s,"reasonId":"%s"}' "$ids_json" "$reason")"
      else
        _pool_post "$batch_to_pool_path" "$(printf '{"ids":%s}' "$ids_json")"
      fi
      ;;
    *)
      die "未知 pool 动作: ${action}（pick/batch-pick/assign/batch-assign/to-pool/batch-to-pool/options/page）"
      ;;
  esac
}

cmd_sync() {
  local content
  content=$(_call_remote "sync_forms" "${1:-{\}}")

  local current_file=""

  while IFS= read -r line; do
    if [[ "$line" == ===FILE:references/*.md=== ]]; then
      local relpath="${line#===FILE:}"
      relpath="${relpath%===}"
      current_file="${PROJECT_DIR}/${relpath}"
      continue
    fi
    if [[ -z "$current_file" ]]; then
      continue
    fi
    echo "$line" >> "${current_file}.snippet"
  done <<< "$content"

  # Replace AUTO-GENERATED sections in module docs
  while IFS= read -r snippet_file; do
    [[ -f "$snippet_file" ]] || continue
    local target="${snippet_file%.snippet}"
    if [[ -f "$target" ]]; then
      local marker_start="<!-- AUTO-GENERATED-START -->"
      local marker_end="<!-- AUTO-GENERATED-END -->"
      local before after snippet
      before=$(sed -n "1,/${marker_start}/p" "$target")
      after=$(sed -n "/${marker_end}/,\$p" "$target")
      snippet=$(cat "$snippet_file")
      printf '%s\n%s\n%s\n' "$before" "$snippet" "$after" > "$target"
    fi
    rm -f "$snippet_file"
  done < <(find "${PROJECT_DIR}/references" -name '*.snippet')

  echo "同步完成" >&2
}

# ── 省市行政代码查询（纯本地，不走 MaxKB）────────────────────────────────

cmd_loc() {
  local name="${1:?用法: cordys-ext loc <城市/区名称>}"
  local json="${PROJECT_DIR}/references/mappings/location_codes.json"
  [[ -f "$json" ]] || die "未找到 location_codes.json: $json"

  # 提取所有 "键": "值" 对，按名称子串过滤
  local matches
  matches=$(grep -o '"[^"]*'"$name"'[^"]*": *"[0-9]*"' "$json" || true)

  if [[ -z "$matches" ]]; then
    echo "未找到「${name}」对应的行政代码，请确认名称或换用更精确的市/区名" >&2
    return 1
  fi

  local count
  count=$(echo "$matches" | wc -l | tr -d ' ')

  if [[ "$count" == "1" ]]; then
    # 唯一命中：直接输出传值格式 <代码>-
    echo "$matches" | sed 's/.*": *"\([0-9]*\)"/\1-/'
  else
    # 多个命中：列出 名称 = <代码>- 供选择
    echo "匹配到多个，请按需选择（传值格式为代码后加 -）：" >&2
    echo "$matches" | sed 's/"\([^"]*\)": *"\([0-9]*\)"/\1 = \2-/'
  fi
}

# ── 部门子树展开（本地递归，调 crm org 接口）─────────────────────────────

cmd_dept_children() {
  local target="${1:-}"
  check_keys

  # 调 org 接口获取部门树
  local tree_json
  tree_json=$(curl -s --noproxy '*' --connect-timeout 10 --max-time 15 \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "Content-Type: application/json;charset=UTF-8" \
    "${CORDYS_CRM_DOMAIN}/department/tree")

  # 用 python 递归展开（通过命令行参数传递 JSON，避免 heredoc+herestring 冲突）
  "${PYTHON_CMD[@]}" - "$target" "$tree_json" <<'PY'
import json, sys

target = sys.argv[1]
tree_json = sys.argv[2]

try:
    resp = json.loads(tree_json)
except json.JSONDecodeError:
    print(f"错误: 无法解析组织架构响应", file=sys.stderr)
    sys.exit(1)

tree = resp.get("data", resp) if isinstance(resp, dict) else resp

def find_node(nodes, target):
    """按 ID 精确匹配，或名称包含匹配"""
    for node in nodes:
        if str(node.get("id", "")) == target or target in node.get("name", ""):
            return node
        children = node.get("children") or []
        result = find_node(children, target)
        if result:
            return result
    return None

def collect_ids(node):
    """递归收集节点及所有子孙的 ID"""
    ids = [str(node["id"])]
    for child in (node.get("children") or []):
        ids.extend(collect_ids(child))
    return ids

def collect_all_ids(nodes):
    """递归收集所有节点的 ID（不传参数时用）"""
    ids = []
    for node in nodes:
        ids.extend(collect_ids(node))
    return ids

# 支持传入的是列表（某些 API 直接返回数组）
if isinstance(tree, list):
    nodes = tree
elif isinstance(tree, dict) and "children" in tree:
    nodes = [tree]
else:
    nodes = tree if isinstance(tree, list) else []

# 不传参数时展开整棵树
if not target:
    ids = collect_all_ids(nodes)
    print(json.dumps(ids, ensure_ascii=False))
    sys.exit(0)

node = find_node(nodes, target)
if not node:
    print(f"错误: 未找到部门「{target}」", file=sys.stderr)
    sys.exit(1)

ids = collect_ids(node)
print(json.dumps(ids, ensure_ascii=False))
PY
}

# ── 主入口 ────────────────────────────────────────────────────────────

usage() {
  cat <<'EOF'
cordys-ext — Cordys CRM 扩展 CLI

用法:
  cordys-ext check '<JSON>'                      查重
  cordys-ext create <module> '<JSON>'            创建（lead/account/opportunity/contact）
  cordys-ext update <module> <id> '<JSON>'       更新（lead/account/opportunity/contact）
  cordys-ext batch-update <module> <fieldId> <fieldValue> <id1,id2,...>  批量更新同一字段
  cordys-ext pool <action> <lead|account> ...    公海/线索池操作（领取/分配/移入池）
  cordys-ext follow '<JSON>'                     新增跟进记录
  cordys-ext transform '<JSON>'                  线索转客户
  cordys-ext form <module>                       获取表单配置
  cordys-ext loc <城市/区名称>                    查省市行政代码（本地查询，返回传值格式 代码-）
  cordys-ext dept-children [部门名称或ID]          展开部门及所有子部门ID（不传参数=全公司）
  cordys-ext sync                                同步表单文档到 references/
  cordys-ext help                                显示帮助

示例:
  cordys-ext check '{"客户名":"东北证券","手机":"13800138000","产品":["MaxKB 专业版"]}'
  cordys-ext create lead '{"公司":"千里眼科技","姓名":"李老师","手机":"13777788888","线索来源":"线上","线上来源详情":"400电话","区域":"东区","行业":"高科技和互联网","产品类型（可多选）":["MeterSphere 企业版"],"是否已拜访":"否","省市":"3301-"}'
  cordys-ext update lead 394648017795821568 '{"手机":"13900001111","是否已拜访":"是"}'
  cordys-ext batch-update lead field_abc123 "是" "id1,id2,id3"
  cordys-ext pool options lead                   → 查可用线索池，拿 poolId
  cordys-ext pool pick lead <线索ID> <poolId>     → 领取线索到自己名下
  cordys-ext pool assign account <客户ID> <用户ID> → 把客户分配给指定成员
  cordys-ext pool to-pool lead <线索ID> [原因ID]   → 把线索退回线索池
  cordys-ext pool batch-pick account "id1,id2" <poolId>  → 批量领取客户
  cordys-ext follow '{"module":"lead","type":"CLUE","clueId":"384225738486157312","content":"线下拜访，聊了产品需求","followMethod":"1","followTime":1717400000000,"owner":"1131998760411284","moduleFields":[]}'
  cordys-ext transform '{"clueId":"370025374014730240","oppName":"商机名","contactName":"李老师","phone":"13777788888","电话":"010-12345678"}'
  cordys-ext loc 杭州                             → 3301-
  cordys-ext dept-children 郝碧纯组               → ["1131998760411186","8150336099852288","8151710489387008"]

EOF
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  check)
    cmd_check "$@"
    ;;
  create)
    module="${1:-}"; shift || die "create 需要指定模块"
    case "$module" in
      lead|account|opportunity|contact)
        cmd_create "$module" "$@"
        ;;
      *) die "不支持的模块: ${module}" ;;
    esac
    ;;
  update)
    module="${1:-}"; shift || die "update 需要指定模块"
    case "$module" in
      lead|account|opportunity|contact)
        cmd_update "$module" "$@"
        ;;
      *) die "不支持的模块: ${module}" ;;
    esac
    ;;
  batch-update)
    module="${1:-}"; shift || die "batch-update 需要指定模块"
    case "$module" in
      lead|account|opportunity|contact)
        cmd_batch_update "$module" "$@"
        ;;
      *) die "不支持的模块: ${module}" ;;
    esac
    ;;
  pool)
    cmd_pool "$@"
    ;;
  follow)
    cmd_follow "$@"
    ;;
  transform)
    cmd_transform "$@"
    ;;
  form)
    cmd_form "$@"
    ;;
  loc)
    cmd_loc "$@"
    ;;
  dept-children)
    cmd_dept_children "$@"
    ;;
  sync)
    cmd_sync "$@"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    die "未知命令: $cmd（尝试 cordys-ext help）"
    ;;
esac
