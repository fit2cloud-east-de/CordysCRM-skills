#!/usr/bin/env bash
# Cordys CRM 扩展 CLI（Shell 版）

set -eo nounset
set -o pipefail 2>/dev/null || true
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# Git for Windows 的 /tmp 等目录不是简单的 /<盘符>/... 映射；优先使用
# Bash 自带的 pwd -W 取得真实 Windows 路径，其他 Bash 再回退到 POSIX 路径。
# 目录拆分使用 Bash 参数展开，避免无意义的 dirname 外部进程。
_SCRIPT_SOURCE="${BASH_SOURCE[0]//\\//}"
_SCRIPT_PARENT="${_SCRIPT_SOURCE%/*}"
[[ "$_SCRIPT_PARENT" == "$_SCRIPT_SOURCE" ]] && _SCRIPT_PARENT="."
[[ -n "$_SCRIPT_PARENT" ]] || _SCRIPT_PARENT="/"
SCRIPT_DIR="$(cd "$_SCRIPT_PARENT" && { pwd -W 2>/dev/null || pwd; })"
PROJECT_DIR="${SCRIPT_DIR%/*}"
[[ -n "$PROJECT_DIR" ]] || PROJECT_DIR="/"
unset _SCRIPT_SOURCE _SCRIPT_PARENT
ENV_FILE="${PROJECT_DIR}/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi

CORDYS_CRM_DOMAIN="${CORDYS_CRM_DOMAIN:-}"
CORDYS_CRM_DOMAIN="${CORDYS_CRM_DOMAIN%/}"

die() { echo "错误: $*" >&2; exit 1; }
warn() { echo "⚠️  警告: $*" >&2; }

# ── Python 探测 ──────────────────────────────────────────────────────
PYTHON_CMD=()
missing_python() {
  die "未找到可用 Python，请安装 Python 3 或设置 CORDYS_PYTHON"
}

detect_python() {
  # 只选择解释器，不在每条 CLI 命令前额外启动 Python 做探测。
  # -S 跳过未使用的 site 初始化；本技能的 sop 工具仅依赖标准库。
  if [[ -n "${CORDYS_PYTHON:-}" ]]; then
    PYTHON_CMD=("${CORDYS_PYTHON}" -S)
    return
  fi
  local cmd
  for cmd in python3 python python.exe; do
    if command -v "$cmd" >/dev/null 2>&1; then
      PYTHON_CMD=("$cmd" -S)
      return
    fi
  done
  if command -v py >/dev/null 2>&1; then
    PYTHON_CMD=(py -3 -S)
    return
  fi
  # 至少允许在 Python 缺失时查看 help；业务命令调用到 Python 时再明确报错。
  PYTHON_CMD=(missing_python)
}

detect_python

# 把 Bash 路径转换为所选 Python 能直接访问的原生路径。使用 Bash/cygpath
# 而不是启动 Python 做转换，避免每条扩展命令都有一次无业务价值的冷启动。
_python_native_path() {
  local raw_path="$1" normalized shell_name drive rest windows_paths=0
  normalized="${raw_path//\\//}"
  [[ "$normalized" =~ ^[A-Za-z]:/ ]] && { printf '%s\n' "$normalized"; return; }

  shell_name="${OSTYPE:-}:${MSYSTEM:-}"
  case "$shell_name" in
    *[Mm][Ss][Yy][Ss]*|*[Mm][Ii][Nn][Gg][Ww]*|*[Cc][Yy][Gg][Ww][Ii][Nn]*) windows_paths=1 ;;
  esac
  case "${PYTHON_CMD[0]:-}" in
    *.[Ee][Xx][Ee]) windows_paths=1 ;;
  esac
  if (( ! windows_paths )); then
    printf '%s\n' "$normalized"
    return
  fi

  if command -v cygpath >/dev/null 2>&1; then
    cygpath -am "$normalized"
    return
  fi
  case "$normalized" in
    /cygdrive/[A-Za-z]|/cygdrive/[A-Za-z]/*)
      rest="${normalized#/cygdrive/}"; drive="${rest%%/*}"; rest="${rest#"$drive"}"; rest="${rest#/}"
      printf '%s:/%s\n' "$drive" "$rest" ;;
    /mnt/[A-Za-z]|/mnt/[A-Za-z]/*)
      rest="${normalized#/mnt/}"; drive="${rest%%/*}"; rest="${rest#"$drive"}"; rest="${rest#/}"
      printf '%s:/%s\n' "$drive" "$rest" ;;
    /[A-Za-z]|/[A-Za-z]/*)
      rest="${normalized#/}"; drive="${rest%%/*}"; rest="${rest#"$drive"}"; rest="${rest#/}"
      printf '%s:/%s\n' "$drive" "$rest" ;;
    *) printf '%s\n' "$normalized" ;;
  esac
}

# 在 set -e 下安全跑 Python sop：合并 stderr；异常也打印 JSON，避免「exit 1 + 空输出」静默失败
# 用法：_py_sop_json $'python 源码\n须 print 一行 JSON'
_py_sop_json() {
  local code="$1"
  local out rc indented wrapped
  # try 块内必须缩进，否则 IndentationError
  indented=$(printf '%s\n' "$code" | sed 's/^/    /')
  wrapped="import json, sys
try:
${indented}
except Exception as e:
    print(json.dumps({'error': type(e).__name__ + ': ' + str(e), 'python': sys.executable}, ensure_ascii=False))
"
  set +e
  out=$("${PYTHON_CMD[@]}" -c "$wrapped" 2>&1)
  rc=$?
  set -e
  if [[ -z "${out//[$'\t\r\n ']/}" ]]; then
    die "Python 工具无输出 (exit=${rc})。PYTHON=${PYTHON_CMD[*]} TOOLS_DIR=${CORDYS_TOOLS_DIR:-?}。请设置 CORDYS_PYTHON 或检查 scripts/sop"
  fi
  printf '%s\n' "$out"
  return 0
}

# sop/ 目录（写入工具的 Python 实现）。由 Python 自行转换路径，不依赖 cygpath/PATH。
if ! TOOLS_DIR=$(_python_native_path "${SCRIPT_DIR}/sop"); then
  die "无法把 scripts/sop 转换为 Python 可用路径。PYTHON=${PYTHON_CMD[*]}"
fi
export CORDYS_TOOLS_DIR="$TOOLS_DIR"

# 注：所有 curl 调用均已加 --noproxy '*'，避免调用方代理干扰

check_keys() {
  [[ -n "$CORDYS_CRM_DOMAIN" ]] || die "未设置 CORDYS_CRM_DOMAIN"
  [[ "$CORDYS_CRM_DOMAIN" =~ ^https://([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.)*[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(:[0-9]{1,5})?/?$ ]] ||
    die "CORDYS_CRM_DOMAIN 必须是合法 HTTPS 根地址（如 https://crm.example.com），不能包含路径、查询参数或凭证"
  local domain_port=""
  if [[ "$CORDYS_CRM_DOMAIN" =~ :([0-9]{1,5})/?$ ]]; then
    domain_port="${BASH_REMATCH[1]}"
    (( domain_port >= 1 && domain_port <= 65535 )) || die "CORDYS_CRM_DOMAIN 端口必须在 1-65535 之间"
  fi
  CORDYS_CRM_DOMAIN="${CORDYS_CRM_DOMAIN%/}"
  [[ -n "${CORDYS_ACCESS_KEY:-}" ]] || die "未设置 CORDYS_ACCESS_KEY"
  [[ -n "${CORDYS_SECRET_KEY:-}" ]] || die "未设置 CORDYS_SECRET_KEY"
}

# ── 自动同步 ─────────────────────────────────────────────────────────────

SYNC_STAMP="${PROJECT_DIR}/references/forms/.last_sync"
SYNC_INTERVAL=21600  # 6 hours

_needs_sync() {
  [[ ! -f "$SYNC_STAMP" ]] && return 0
  local last="" now=""
  IFS= read -r last < "$SYNC_STAMP" || true
  [[ "$last" =~ ^[0-9]+$ ]] || return 0
  now=$(date +%s) || return 0
  (( now - last >= SYNC_INTERVAL ))
}

_auto_sync() {
  if _needs_sync; then
    if ! (cmd_sync >/dev/null); then
      warn "自动表单同步异常，已保留本地快照并继续后续任务；可单独执行 cordys-ext sync 查看错误。"
    fi
  fi
  return 0
}

# ── 命令 ─────────────────────────────────────────────────────────────────

cmd_check() {
  check_keys
  [[ $# -eq 1 ]] || die '用法: cordys-ext check '\''{"客户名":"公司名"}'\''（也兼容单个裸公司名或手机号）'
  local params="$1"

  CORDYS_DOMAIN="$CORDYS_CRM_DOMAIN" \
  CORDYS_ACCESS_KEY="$CORDYS_ACCESS_KEY" \
  CORDYS_SECRET_KEY="$CORDYS_SECRET_KEY" \
  CORDYS_CHECK_PARAMS="$params" \
  "${PYTHON_CMD[@]}" -c "
import os, sys, json
sys.path.insert(0, os.environ['CORDYS_TOOLS_DIR'])
from check_duplicate import check_duplicate
result = check_duplicate(
    os.environ['CORDYS_DOMAIN'],
    os.environ['CORDYS_ACCESS_KEY'],
    os.environ['CORDYS_SECRET_KEY'],
    os.environ['CORDYS_CHECK_PARAMS']
)
print(result)
try:
    payload = json.loads(result)
except (json.JSONDecodeError, TypeError):
    sys.exit(1)
if isinstance(payload, dict) and payload.get('error'):
    sys.exit(1)
"
}

# [已废弃] 改用 cordys.sh crm create（body 用 fieldId 双层结构）。旧实现保留可运行，勿用于新代码。
cmd_create() {
  check_keys
  _auto_sync
  local module="${1:?用法: cordys-ext create <module> '<JSON>'}"
  local raw_params="${2:?用法: cordys-ext create <module> '<JSON>'}"

  # 注入 module 到 params
  local params
  params=$(echo "$raw_params" | sed 's/^{/{"module":"'"$module"'",/')

  local result
  result=$(CORDYS_DOMAIN="$CORDYS_CRM_DOMAIN" \
    CORDYS_ACCESS_KEY="$CORDYS_ACCESS_KEY" \
    CORDYS_SECRET_KEY="$CORDYS_SECRET_KEY" \
    CORDYS_CREATE_PARAMS="$params" \
    "${PYTHON_CMD[@]}" -c "
import os, sys
sys.path.insert(0, os.environ['CORDYS_TOOLS_DIR'])
from create_entity import create_entity
result = create_entity(
    os.environ['CORDYS_DOMAIN'],
    os.environ['CORDYS_ACCESS_KEY'],
    os.environ['CORDYS_SECRET_KEY'],
    os.environ['CORDYS_CREATE_PARAMS']
)
print(result)
"
  )
  echo "$result"

  # 创建失败时触发同步
  if echo "$result" | grep -q '"error"'; then
    cmd_sync >/dev/null || true
  fi
}

cmd_follow() {
  check_keys
  _auto_sync
  local params="${1:?用法: cordys-ext follow '<JSON>'}"

  local result
  result=$(
    CORDYS_DOMAIN="$CORDYS_CRM_DOMAIN" \
    CORDYS_ACCESS_KEY="$CORDYS_ACCESS_KEY" \
    CORDYS_SECRET_KEY="$CORDYS_SECRET_KEY" \
    CORDYS_FOLLOW_PARAMS="$params" \
    _py_sop_json '
import os, sys
sys.path.insert(0, os.environ["CORDYS_TOOLS_DIR"])
from add_follow_record import add_follow_record
print(add_follow_record(
    os.environ["CORDYS_DOMAIN"],
    os.environ["CORDYS_ACCESS_KEY"],
    os.environ["CORDYS_SECRET_KEY"],
    os.environ["CORDYS_FOLLOW_PARAMS"],
))
'
  )
  echo "$result"

  if echo "$result" | grep -q '"error"'; then
    cmd_sync >/dev/null || true
  fi
}

# 更新已存在的跟进记录：先读取详情补齐完整请求体，再单次调用 update。
cmd_follow_update() {
  check_keys
  _auto_sync
  local params="${1:?用法: cordys-ext follow-update '<JSON>'}"

  local result
  result=$(
    CORDYS_DOMAIN="$CORDYS_CRM_DOMAIN" \
    CORDYS_ACCESS_KEY="$CORDYS_ACCESS_KEY" \
    CORDYS_SECRET_KEY="$CORDYS_SECRET_KEY" \
    CORDYS_FOLLOW_PARAMS="$params" \
    _py_sop_json '
import os, sys
sys.path.insert(0, os.environ["CORDYS_TOOLS_DIR"])
from add_follow_record import update_follow_record
print(update_follow_record(
    os.environ["CORDYS_DOMAIN"],
    os.environ["CORDYS_ACCESS_KEY"],
    os.environ["CORDYS_SECRET_KEY"],
    os.environ["CORDYS_FOLLOW_PARAMS"],
))
'
  )
  echo "$result"
}

# 新增跟进计划：给已存在的线索/客户/商机排一条后续跟进计划。
# 与 cmd_follow（跟进记录）平行，但走 add_follow_plan（端点/字段契约不同）。
cmd_follow_plan() {
  check_keys
  _auto_sync
  local params="${1:?用法: cordys-ext follow-plan '<JSON>'}"

  local result
  result=$(
    CORDYS_DOMAIN="$CORDYS_CRM_DOMAIN" \
    CORDYS_ACCESS_KEY="$CORDYS_ACCESS_KEY" \
    CORDYS_SECRET_KEY="$CORDYS_SECRET_KEY" \
    CORDYS_FOLLOW_PARAMS="$params" \
    _py_sop_json '
import os, sys
sys.path.insert(0, os.environ["CORDYS_TOOLS_DIR"])
from add_follow_plan import add_follow_plan
print(add_follow_plan(
    os.environ["CORDYS_DOMAIN"],
    os.environ["CORDYS_ACCESS_KEY"],
    os.environ["CORDYS_SECRET_KEY"],
    os.environ["CORDYS_FOLLOW_PARAMS"],
))
'
  )
  echo "$result"

  if echo "$result" | grep -q '"error"'; then
    cmd_sync >/dev/null || true
  fi
}

# 更新已存在的跟进计划：字段契约与跟进记录不同，走 plan/update。
cmd_follow_plan_update() {
  check_keys
  _auto_sync
  local params="${1:?用法: cordys-ext follow-plan-update '<JSON>'}"

  local result
  result=$(
    CORDYS_DOMAIN="$CORDYS_CRM_DOMAIN" \
    CORDYS_ACCESS_KEY="$CORDYS_ACCESS_KEY" \
    CORDYS_SECRET_KEY="$CORDYS_SECRET_KEY" \
    CORDYS_FOLLOW_PARAMS="$params" \
    _py_sop_json '
import os, sys
sys.path.insert(0, os.environ["CORDYS_TOOLS_DIR"])
from add_follow_plan import update_follow_plan
print(update_follow_plan(
    os.environ["CORDYS_DOMAIN"],
    os.environ["CORDYS_ACCESS_KEY"],
    os.environ["CORDYS_SECRET_KEY"],
    os.environ["CORDYS_FOLLOW_PARAMS"],
))
'
  )
  echo "$result"
}

# 线索转化（客户+联系人+可选商机）：多步事务，转化后自动补全联系人/客户类型/商机字段。
# 转化统一走这里（不是 cordys.sh crm transform——裸端点只建空壳、不补字段）。
cmd_transform() {
  check_keys
  _auto_sync
  local params="${1:?用法: cordys-ext transform '<JSON>'}"

  CORDYS_DOMAIN="$CORDYS_CRM_DOMAIN" \
  CORDYS_ACCESS_KEY="$CORDYS_ACCESS_KEY" \
  CORDYS_SECRET_KEY="$CORDYS_SECRET_KEY" \
  CORDYS_TRANSFORM_PARAMS="$params" \
  "${PYTHON_CMD[@]}" -c "
import os, sys
sys.path.insert(0, os.environ['CORDYS_TOOLS_DIR'])
from transform_lead import transform_lead
result = transform_lead(
    os.environ['CORDYS_DOMAIN'],
    os.environ['CORDYS_ACCESS_KEY'],
    os.environ['CORDYS_SECRET_KEY'],
    os.environ['CORDYS_TRANSFORM_PARAMS']
)
print(result)
"
}

cmd_form() {
  check_keys
  _auto_sync
  local module="${1:?用法: cordys-ext form <module>}"

  # 获取表单配置（直接调用Cordys API，不依赖Python工具）
  local form_path
  case "$module" in
    lead|clue) form_path="/lead/module/form" ;;
    account) form_path="/account/module/form" ;;
    opportunity) form_path="/opportunity/module/form" ;;
    contact) form_path="/module/form/config/contact" ;;
    follow) form_path="/follow/record/module/form" ;;
    follow-plan) form_path="/follow/plan/module/form" ;;
    contract) form_path="/contract/module/form" ;;
    payment-record) form_path="/contract/payment-record/module/form" ;;
    *) die "不支持的模块: $module" ;;
  esac

  curl -s --noproxy '*' --connect-timeout 10 --max-time 15 \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "X-Request-Source: SKILL" \
    -H "Content-Type: application/json;charset=UTF-8" \
    "${CORDYS_CRM_DOMAIN}${form_path}"
}

# 兼容入口：统一委托给 cordys.sh crm update，避免维护第二套全量更新实现。
# 支持旧签名 update <module> <id> <JSON>，也支持用 - / @- 从 UTF-8 stdin 读取大 JSON。
cmd_update() {
  local module="${1:?用法: cordys-ext update <module> <id> '<JSON|@->'}"
  local id="${2:?用法: cordys-ext update <module> <id> '<JSON|@->'}"
  local raw_params="${3:?用法: cordys-ext update <module> <id> '<JSON|@->'}"
  local cordys_cli="${SCRIPT_DIR}/cordys.sh"
  local inject_id_python='import json, os, sys
try:
    body = json.load(sys.stdin)
except (UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"update JSON 解析失败: {exc}")
if not isinstance(body, dict):
    raise SystemExit("update JSON 必须是对象")
record_id = os.environ["CORDYS_UPDATE_ID"]
provided_id = body.get("id")
if provided_id not in (None, "", record_id):
    raise SystemExit("update JSON 中的 id 与命令参数 id 不一致")
body["id"] = record_id
json.dump(body, sys.stdout, ensure_ascii=False)'

  [[ -f "$cordys_cli" ]] || die "未找到统一更新入口: ${cordys_cli}"
  {
    case "$raw_params" in
      -|@-) cat ;;
      *) printf '%s' "$raw_params" ;;
    esac
  } | CORDYS_UPDATE_ID="$id" "${PYTHON_CMD[@]}" -c "$inject_id_python" |
    bash "$cordys_cli" crm update "$module" @-
  return

  # 以下旧实现已不可达，仅在本轮迁移确认前保留；实际更新只走上面的统一入口。
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
import json, os, sys, re, unicodedata, tempfile
sys.path.insert(0, os.environ['CORDYS_TOOLS_DIR'])
from time_boundary import TimeBoundaryError, parse_date_ms

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
                        param_value = parse_date_ms(param_value)
                    except TimeBoundaryError:
                        print(json.dumps({"error": "结束日期格式无效，应为 YYYY-MM-DD；未更新记录"}, ensure_ascii=False))
                        sys.exit(0)
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
                    param_value = parse_date_ms(param_value)
                except TimeBoundaryError:
                    print(json.dumps({"error": "结束日期格式无效，应为 YYYY-MM-DD；未更新记录"}, ensure_ascii=False))
                    sys.exit(0)
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

# [已废弃] 改用 cordys.sh crm batch-update（JSON body {"ids":[],"fieldId":,"fieldValue":}）。旧实现保留可运行，勿用于新代码。
cmd_batch_update() {
  local module="${1:?用法: cordys-ext batch-update <module> <fieldId> <fieldValue> <id1,id2,...>}"
  local field_id="${2:?用法: cordys-ext batch-update <module> <fieldId> <fieldValue> <id1,id2,...>}"
  local field_value="${3:?用法: cordys-ext batch-update <module> <fieldId> <fieldValue> <id1,id2,...>}"
  local ids_csv="${4:?用法: cordys-ext batch-update <module> <fieldId> <fieldValue> <id1,id2,...>}"
  check_keys

  # 经环境变量传参，并用 json.dumps 统一处理 UTF-8 和 JSON 转义。
  local body
  body=$(CORDYS_BU_FIELD_ID="$field_id" \
  CORDYS_BU_FIELD_VALUE="$field_value" \
  CORDYS_BU_IDS="$ids_csv" \
  "${PYTHON_CMD[@]}" -c "
import os, json
ids = [i.strip() for i in os.environ['CORDYS_BU_IDS'].split(',') if i.strip()]
print(json.dumps({
    'ids': ids,
    'fieldId': os.environ['CORDYS_BU_FIELD_ID'],
    'fieldValue': os.environ['CORDYS_BU_FIELD_VALUE'],
}, ensure_ascii=False))
")

  local result
  result=$(printf '%s' "$body" | curl -s --noproxy '*' --connect-timeout 10 --max-time 30 \
    -X POST \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "X-Request-Source: SKILL" \
    -H "Content-Type: application/json;charset=UTF-8" \
    -d @- \
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
  local action="${1:-}"; shift || die "pool 需要指定动作（pick/assign/to-pool 写类；查询/拿 poolId 用 cordys.sh）"
  local module="${1:-}"; shift || die "pool ${action} 需要指定模块（lead/account）"
  case "$module" in
    lead|account) ;;
    *) die "不支持的模块: ${module}（仅 lead/account）" ;;
  esac
  check_keys

  # 模块 → 各操作的路径前缀与 ID 字段名
  local id_key to_pool_path batch_to_pool_path
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
    pick)
      # 领取（领到自己名下）：<id> <poolId>
      local rid="${1:?用法: pool pick ${module} <id> <poolId>}"
      local pool_id="${2:?用法: pool pick ${module} <id> <poolId>}"
      [[ $# -eq 2 ]] || die "pool pick ${module} 只接受 2 个参数 <id> <poolId>，收到 $# 个：${*}"
      _pool_post "/pool/${module}/pick" \
        "$(printf '{"%s":"%s","poolId":"%s"}' "$id_key" "$rid" "$pool_id")"
      ;;
    batch-pick)
      # 批量领取：<id1,id2,...> <poolId>
      local ids_csv="${1:?用法: pool batch-pick ${module} <id1,id2,...> <poolId>}"
      local pool_id="${2:?用法: pool batch-pick ${module} <id1,id2,...> <poolId>}"
      [[ $# -eq 2 ]] || die "pool batch-pick ${module} 只接受 2 个参数 <id1,id2,...> <poolId>，收到 $# 个：${*}"
      local ids_json
      ids_json=$(_csv_to_json_array "$ids_csv")
      _pool_post "/pool/${module}/batch-pick" \
        "$(printf '{"batchIds":%s,"poolId":"%s"}' "$ids_json" "$pool_id")"
      ;;
    assign)
      # 分配（指派给他人）：<id> <assignUserId>　※不需要 poolId
      local rid="${1:?用法: pool assign ${module} <id> <assignUserId>（不需要 poolId）}"
      local uid="${2:?用法: pool assign ${module} <id> <assignUserId>（不需要 poolId）}"
      [[ $# -eq 2 ]] || die "pool assign ${module} 只接受 2 个参数 <id> <assignUserId>（不需要 poolId），收到 $# 个：${*}"
      _pool_post "/pool/${module}/assign" \
        "$(printf '{"%s":"%s","assignUserId":"%s"}' "$id_key" "$rid" "$uid")"
      ;;
    batch-assign)
      # 批量分配：<id1,id2,...> <assignUserId>　※不需要 poolId
      local ids_csv="${1:?用法: pool batch-assign ${module} <id1,id2,...> <assignUserId>（不需要 poolId）}"
      local uid="${2:?用法: pool batch-assign ${module} <id1,id2,...> <assignUserId>（不需要 poolId）}"
      [[ $# -eq 2 ]] || die "pool batch-assign ${module} 只接受 2 个参数 <id1,id2,...> <assignUserId>（不需要 poolId），收到 $# 个：${*}"
      local ids_json
      ids_json=$(_csv_to_json_array "$ids_csv")
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
      local ids_json
      ids_json=$(_csv_to_json_array "$ids_csv")
      if [[ -n "$reason" ]]; then
        _pool_post "$batch_to_pool_path" "$(printf '{"ids":%s,"reasonId":"%s"}' "$ids_json" "$reason")"
      else
        _pool_post "$batch_to_pool_path" "$(printf '{"ids":%s}' "$ids_json")"
      fi
      ;;
    *)
      die "未知 pool 动作: ${action}（pick/batch-pick/assign/batch-assign/to-pool/batch-to-pool；查询/拿 poolId 用 cordys.sh crm page pool/{lead,account} 与 cordys.sh raw GET /pool/{module}/options）"
      ;;
  esac
}

cmd_sync() {
  check_keys
  local params="${1:-{}}"

  if ! CORDYS_SYNC_TOOL="${TOOLS_DIR}/sync_forms.py" "${PYTHON_CMD[@]}" -c \
    'import os, sys; sys.exit(0 if os.path.isfile(os.environ["CORDYS_SYNC_TOOL"]) else 1)'; then
    die "Python 无法访问 sync_forms.py。TOOLS_DIR=${TOOLS_DIR} PYTHON=${PYTHON_CMD[*]}"
  fi

  CORDYS_DOMAIN="$CORDYS_CRM_DOMAIN" \
    CORDYS_ACCESS_KEY="$CORDYS_ACCESS_KEY" \
    CORDYS_SECRET_KEY="$CORDYS_SECRET_KEY" \
    CORDYS_SYNC_PARAMS="$params" \
    "${PYTHON_CMD[@]}" -c "
import os, sys
sys.path.insert(0, os.environ['CORDYS_TOOLS_DIR'])
from pathlib import Path
from sync_forms import apply_sync_output, sync_forms
try:
    result = sync_forms(
        os.environ['CORDYS_DOMAIN'],
        os.environ['CORDYS_ACCESS_KEY'],
        os.environ['CORDYS_SECRET_KEY'],
        os.environ['CORDYS_SYNC_PARAMS']
    )
    project_dir = Path(os.environ['CORDYS_TOOLS_DIR']).resolve().parents[1]
    summary = apply_sync_output(project_dir, result)
    updated = len(summary['updatedModules'])
    retained = len(summary['retainedModules'])
    if retained:
        print(f'表单同步完成：更新 {updated} 个模块，保留 {retained} 个模块的本地旧快照。', file=sys.stderr)
    else:
        print(f'表单同步完成：更新全部 {updated} 个模块。', file=sys.stderr)
except Exception as exc:
    print(f'错误: 表单同步失败：{type(exc).__name__}: {exc}', file=sys.stderr)
    raise SystemExit(1)
" || return $?
}

# ── 省市行政代码查询（纯本地，不走 MaxKB）────────────────────────────────

cmd_loc() {
  local name="${1:?用法: cordys-ext loc <城市/区名称>}"
  local json="${PROJECT_DIR}/references/mappings/location_codes.json"
  [[ -f "$json" ]] || die "未找到 location_codes.json: $json"

  # 直辖市 guard：直辖市在行政库里只有区级、没有市级键，传市名必然查不到。
  # 直接指路到区名，避免返回干巴巴的"未找到"（见 inference-rules.md §省市格式）。
  case "$name" in
    上海|上海市) echo "「${name}」是直辖市，LOCATION 需精确到区级。请改用区名查询，未指定区时默认 浦东新区（loc 浦东新区 → 310115-）。详见 inference-rules.md §省市格式" >&2; return 1 ;;
    北京|北京市) echo "「${name}」是直辖市，LOCATION 需精确到区级。请改用区名查询，未指定区时默认 朝阳区（loc 朝阳区 → 110105-）。详见 inference-rules.md §省市格式" >&2; return 1 ;;
    天津|天津市) echo "「${name}」是直辖市，LOCATION 需精确到区级。请改用区名查询，未指定区时默认 滨海新区（loc 滨海新区 → 120116-）。详见 inference-rules.md §省市格式" >&2; return 1 ;;
    重庆|重庆市) echo "「${name}」是直辖市，LOCATION 需精确到区级。请改用区名查询，未指定区时默认 渝北区（loc 渝北区 → 500112-）。详见 inference-rules.md §省市格式" >&2; return 1 ;;
  esac

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

# ── 主入口 ────────────────────────────────────────────────────────────

usage() {
  cat <<'EOF'
cordys-ext — Cordys CRM 扩展 CLI

用法:
  cordys-ext check '<JSON>'                      查重（推荐 JSON；兼容单个裸公司名或手机号）
  cordys-ext transform '<JSON>'                  线索转客户（+可选商机），多步事务、自动补全字段（传中文字段名）
  cordys-ext pool <action> <lead|account> ...    线索池/线索公海、客户公海写操作（领取/分配/移入池）；查询与拿 poolId 用 cordys.sh
  cordys-ext follow '<JSON>'                     新增跟进记录
  cordys-ext follow-update '<JSON>'              更新跟进记录（必传 module + 记录 id；更新前自动读取详情）
  cordys-ext follow-plan '<JSON>'                新增跟进计划（后续要做的跟进；记录是已发生的）
  cordys-ext follow-plan-update '<JSON>'         更新跟进计划（必传 module + 计划 id；更新前自动读取详情）
  cordys-ext form <module>                       获取表单配置
  cordys-ext loc <城市/区名称>                    查省市行政代码（本地查询，返回传值格式 代码-）
  cordys-ext sync-if-needed                      无同步戳或超过 6 小时时同步表单
  cordys-ext sync                                同步表单文档到 references/
  cordys-ext help                                显示帮助

兼容入口（新代码仍优先使用 cordys.sh crm，body 用 fieldId 双层结构，见 core/write-engine.md）:
  cordys-ext update <module> <id> <JSON|@->  → 自动注入 id 并委托 cordys.sh crm update
  cordys-ext create/batch-update             → 旧实现；新代码改用 cordys.sh crm create/batch-update
  （update 与正式入口共享读回合并、合同/订单表单配置和 UTF-8 文件传输保护。）
  注：transform 例外，仍走 cordys-ext（转化是多步事务，cordys.sh 裸端点只建空壳、不补字段）。

示例:
  cordys-ext check '{"客户名":"东北证券","手机":"13800138000"}'
  cordys-ext transform '{"clueId":"370025374014730240","oppName":"华星-MK-2026-订阅新购","contactName":"王总","phone":"13812345678","金额":500000,"结束日期":"2026-09-30","签约类型":"飞致云直签","类型":"最终客户"}'
  cordys.sh raw GET /pool/lead/options          → 查可用线索池，拿 poolId（读操作走 cordys.sh）
  cordys-ext pool pick lead <线索ID> <poolId>     → 领取线索到自己名下
  cordys-ext pool assign account <客户ID> <用户ID> → 把客户分配给指定成员
  cordys-ext pool to-pool lead <线索ID> [原因ID]   → 把线索退回线索池
  cordys-ext pool batch-pick account "id1,id2" <poolId>  → 批量领取客户
  cordys-ext follow '{"module":"lead","type":"CLUE","clueId":"384225738486157312","content":"线下拜访，聊了产品需求","followMethod":"1","followTime":1717400000000,"owner":"1131998760411284","moduleFields":[]}'
  cordys-ext follow-update '{"module":"lead","id":"<跟进记录ID>","跟进内容":"【AI打卡】跟进\n补充沟通结果","跟进方式":"微信"}'
  cordys-ext follow-plan '{"module":"lead","clueId":"384225738486157312","content":"下周电话回访采购进度","跟进方式":"电话","计划时间":"2026-07-15 10:00"}'
  cordys-ext follow-plan-update '{"module":"lead","id":"<跟进计划ID>","计划时间":"2026-08-10 10:00","跟进方式":"电话"}'
  cordys-ext loc 杭州                             → 3301-

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
    cmd_update "$module" "$@"
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
  follow-update)
    cmd_follow_update "$@"
    ;;
  follow-plan)
    cmd_follow_plan "$@"
    ;;
  follow-plan-update)
    cmd_follow_plan_update "$@"
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
  sync)
    cmd_sync "$@"
    ;;
  sync-if-needed)
    _auto_sync
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    die "未知命令: $cmd（尝试 cordys-ext help）"
    ;;
esac
