#!/usr/bin/env bash
# CORDYS CRM CLI 工具
# 使用 X-Access-Key / X-Secret-Key 进行鉴权
set -eo nounset
set -o pipefail 2>/dev/null || true

export PYTHONUTF8=1
if [[ -z "${PYTHONIOENCODING:-}" ]]; then
  export PYTHONIOENCODING=utf-8
fi

# 优先使用 Git for Windows Bash 自带的 pwd -W，正确解析 /tmp 等虚拟挂载；
# 非 MSYS Bash 不支持该选项时回退到普通 POSIX 路径。dirname 用参数展开完成，
# 避免每条命令为两个静态目录再创建两个外部进程。
_SCRIPT_SOURCE="${BASH_SOURCE[0]//\\//}"
_SCRIPT_PARENT="${_SCRIPT_SOURCE%/*}"
[[ "$_SCRIPT_PARENT" == "$_SCRIPT_SOURCE" ]] && _SCRIPT_PARENT="."
[[ -n "$_SCRIPT_PARENT" ]] || _SCRIPT_PARENT="/"
SCRIPT_DIR="$(cd "$_SCRIPT_PARENT" && { pwd -W 2>/dev/null || pwd; })"
SKILL_DIR="${SCRIPT_DIR%/*}"
[[ -n "$SKILL_DIR" ]] || SKILL_DIR="/"
unset _SCRIPT_SOURCE _SCRIPT_PARENT
ENV_FILE="${SKILL_DIR}/.env"

# sop/ 公共库目录。选定 Python 后再转换为它能直接访问的原生路径。
SOP_DIR="${SCRIPT_DIR}/sop"
QUERY_SCHEMA="${SKILL_DIR}/references/field-schema.json"

# ── 加载环境变量 ──────────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi

CORDYS_CRM_DOMAIN="${CORDYS_CRM_DOMAIN:-}"
CORDYS_CRM_DOMAIN="${CORDYS_CRM_DOMAIN%/}"

# ── 辅助函数 ───────────────────────────────────────────────────────────
die()  { echo "错误: $*" >&2; exit 1; }
info() { echo ":: $*" >&2; }
warn() { echo "⚠️  警告: $*" >&2; }

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

# 查询与写入共用本实例的 field-schema/forms/视图快照。每次进入依赖快照的入口时
# 先在当前 Bash 进程内做 6 小时 TTL 检查；未过期时不要再启动 cordys_ext.sh。
# 这条热路径会被每次 page/search/view 调用，嵌套 CLI 会平白再启动 Bash 和 Python。
SYNC_STAMP="${SKILL_DIR}/references/forms/.last_sync"
SYNC_INTERVAL=21600

snapshot_needs_sync() {
  [[ -f "$SYNC_STAMP" ]] || return 0
  local last="" now=""
  IFS= read -r last < "$SYNC_STAMP" || true
  [[ "$last" =~ ^[0-9]+$ ]] || return 0
  # Bash 4.2+ 可直接取 epoch，不创建 date 子进程；老 Bash 再回退。
  if ! printf -v now '%(%s)T' -1 2>/dev/null || [[ ! "$now" =~ ^[0-9]+$ ]]; then
    now=$(date +%s) || return 0
  fi
  (( now - last >= SYNC_INTERVAL ))
}

snapshot_sync_if_needed() {
  local context="${1:-操作}"
  snapshot_needs_sync || return 0
  local sync_cli="${SCRIPT_DIR}/cordys_ext.sh"
  if [[ ! -f "$sync_cli" ]]; then
    warn "${context}前无法执行自动同步：未找到 ${sync_cli}；继续使用本地表单快照。"
    return 0
  fi
  if ! bash "$sync_cli" sync-if-needed; then
    warn "${context}前表单/视图同步异常；已保留本地快照并继续${context}。可单独执行 cordys_ext.sh sync 查看直接错误。"
  fi
  return 0
}

query_sync_if_needed() { snapshot_sync_if_needed "查询"; }
write_sync_if_needed() { snapshot_sync_if_needed "写入"; }

# pool page/search 的关键入口参数不依赖表单 schema，先于 sync 与联网校验，
# 让缺失、错位或类型错误的 poolId 直接返回可一次修复的诊断。
pool_query_preflight() {
  local module="${1:-}" raw="${2:-}" query_mode="${3:-}"
  case "$module" in
    pool/lead|pool/account) ;;
    *) return 0 ;;
  esac
  printf '%s' "$raw" |
    "${PYTHON_CMD[@]}" "${SOP_DIR}/payload_io.py" validate-pool-scope \
      "$module" "$query_mode" "$SOP_DIR"
}

PYTHON_CMD=()
missing_python() {
  die "未找到可用 Python，请安装 Python 3 或设置 CORDYS_PYTHON"
}

detect_python() {
  # 这里只选解释器，不再为了“验证”额外冷启动一次。真正需要 Python 的命令
  # 会自然给出启动/语法错误，而 help、raw GET 等纯 Shell 路径保持零 Python 启动。
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
  # help/raw GET 等纯 Shell 命令仍应可用；只有真正进入 Python 路径时才报错。
  PYTHON_CMD=(missing_python)
}

detect_python

# MSYS 不会可靠转换环境变量中的 /c/... 路径，且 WorkBuddy 的 Bash 运行时
# 不保证提供 cygpath。这里用 Bash 原生转换，避免为两个静态路径各冷启动一次 Python。
_python_native_path() {
  local raw_path="$1" normalized shell_name drive rest windows_paths=0
  normalized="${raw_path//\\//}"
  [[ "$normalized" =~ ^[A-Za-z]:/ ]] && { printf '%s\n' "$normalized"; return; }

  shell_name="${OSTYPE:-}:${MSYSTEM:-}"
  case "${shell_name,,}" in
    *msys*|*mingw*|*cygwin*) windows_paths=1 ;;
  esac
  [[ "${PYTHON_CMD[0],,}" == *.exe ]] && windows_paths=1
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
      printf '%s:/%s\n' "${drive^^}" "$rest" ;;
    /mnt/[A-Za-z]|/mnt/[A-Za-z]/*)
      rest="${normalized#/mnt/}"; drive="${rest%%/*}"; rest="${rest#"$drive"}"; rest="${rest#/}"
      printf '%s:/%s\n' "${drive^^}" "$rest" ;;
    /[A-Za-z]|/[A-Za-z]/*)
      rest="${normalized#/}"; drive="${rest%%/*}"; rest="${rest#"$drive"}"; rest="${rest#/}"
      printf '%s:/%s\n' "${drive^^}" "$rest" ;;
    *) printf '%s\n' "$normalized" ;;
  esac
}

if ! SOP_DIR=$(_python_native_path "$SOP_DIR"); then
  die "无法把 scripts/sop 转换为 Python 可用路径。PYTHON=${PYTHON_CMD[*]}"
fi
if ! QUERY_SCHEMA=$(_python_native_path "$QUERY_SCHEMA"); then
  die "无法把 field-schema.json 转换为 Python 可用路径。PYTHON=${PYTHON_CMD[*]}"
fi

# ── 本地业务日期换算（不联网、不需要 CRM 凭证）────────────────────
crm_date_boundary() {
  local action="${1:-}"
  shift || true
  case "$action" in
    date-ms)
      [[ $# -eq 1 ]] || die "date-ms 用法: cordys crm date-ms '<YYYY-MM-DD[ HH:MM[:SS]]>'"
      ;;
    date-range)
      [[ $# -eq 2 ]] || die "date-range 用法: cordys crm date-range <开始日期> <结束日期>（两端都包含）"
      ;;
    *) die "未知的日期换算命令: $action" ;;
  esac
  "${PYTHON_CMD[@]}" "${SOP_DIR}/time_boundary.py" "$action" "$@"
}

# 验证URL是否指向可信的Cordys CRM域名
validate_url() {
  local url="$1"

  local domain
  if [[ "$url" =~ ^https?://([^/]+) ]]; then
    domain="${BASH_REMATCH[1]}"
  else
    return 0
  fi

  local trusted_domain
  if [[ "$CORDYS_CRM_DOMAIN" =~ ^https?://([^/]+) ]]; then
    trusted_domain="${BASH_REMATCH[1]}"
  else
    trusted_domain="$CORDYS_CRM_DOMAIN"
  fi

  if [[ "$domain" != "$trusted_domain" ]] && [[ "$domain" != *".$trusted_domain" ]]; then
    warn "目标域名 '$domain' 与配置的Cordys CRM域名 '$trusted_domain' 不匹配"
    warn "这可能会泄露您的API凭证！"
    return 1
  fi
  return 0
}

page_payload() {
  local keyword="${1:-}"
  "${PYTHON_CMD[@]}" - "$keyword" <<'PY'
import json, sys, tempfile, os
keyword = sys.argv[1] if len(sys.argv) > 1 else ""
payload = {
  "current": 1,
  "pageSize": 30,
  "sort": {},
  "combineSearch": {"searchMode": "AND", "conditions": []},
  "keyword": keyword,
  "viewId": "ALL",
  "filters": []
}
tmpfile = os.path.join(tempfile.gettempdir(), f'cordys_{os.getpid()}.json')
with open(tmpfile, 'w', encoding='utf-8') as f:
  json.dump(payload, f, ensure_ascii=False)
print(tmpfile)
PY
}

# 合并用户 JSON 到默认 payload，确保 current 和 pageSize 始终存在
merge_payload() {
  local user_json="${1:-}" module="${2:-}" json_mode="${3:-}" query_mode="${4:-}"
  # 通过 stdin 传输 JSON，避免命令行长度和编码歧义。
  printf '%s' "$user_json" |
    "${PYTHON_CMD[@]}" "${SOP_DIR}/payload_io.py" normalize-query \
      "$module" "$SOP_DIR" "$QUERY_SCHEMA" "$json_mode" "$query_mode"
}

# 写入 payload 助手：把用户 JSON 落盘为 UTF-8 临时文件，返回路径供 --data-binary @file。
# 与 merge_payload 同模式，但不注入分页默认值。
# 第二参数传 "strip" 时剥离 owner（通用 create 交后端按 hasCurrentUser 设为当前用户，
# 避免误传 id 导致记录静默归错人）。订单 create 由 prepare-create 走 SOP 例外并保留合同 owner；
# update 不传 strip，保留 owner——update 全量覆盖，剥了会清空负责人。
write_payload() {
  local user_json="${1:-}" strip_owner="${2:-}"
  "${PYTHON_CMD[@]}" - "$user_json" "$strip_owner" <<'PY'
import json, sys, tempfile, os

raw = sys.argv[1] if len(sys.argv) > 1 else ""
strip_owner = sys.argv[2] if len(sys.argv) > 2 else ""
try:
  body = json.loads(raw) if raw and raw.strip() else {}
except json.JSONDecodeError as e:
  sys.stderr.write(f"写入 JSON 解析失败: {e}\n")
  sys.exit(1)
if not isinstance(body, dict):
  sys.stderr.write("写入 body 必须是 JSON 对象\n")
  sys.exit(1)

if strip_owner == "strip":
  body.pop("owner", None)

tmpfile = os.path.join(tempfile.gettempdir(), f'cordys_write_{os.getpid()}.json')
with open(tmpfile, 'w', encoding='utf-8') as f:
  json.dump(body, f, ensure_ascii=False)
print(tmpfile)
PY
}

# 把 stdin 中的 JSON 验证后写入原生 Python 临时目录。用于详情/表单等大 JSON，
# 避免把完整响应放进 Windows 进程命令行触发长度上限。
json_stdin_file() {
  local label="${1:-JSON}"
  "${PYTHON_CMD[@]}" -c '
import json, os, sys, tempfile
label = sys.argv[1] if len(sys.argv) > 1 else "JSON"
raw = sys.stdin.read()
try:
    value = json.loads(raw)
except json.JSONDecodeError as exc:
    sys.stderr.write(f"{label} 解析失败: {exc}\n")
    sys.exit(1)
path = os.path.join(tempfile.gettempdir(), f"cordys_json_{os.getpid()}.json")
with open(path, "w", encoding="utf-8") as stream:
    json.dump(value, stream, ensure_ascii=False)
print(path)
' "$label"
}

# 更新读回合并助手：把「现有记录(GET 返回)」与「调用方要改的字段」合并成 update body。
# /{module}/update 是全量覆盖——body 没带的可写字段和 moduleFields 会被清空。这里先保全
# 现有全部可写字段，再用调用方的新值覆盖，避免只传变更字段导致其余字段丢失（曾丢结束日期）。
# 只读/展示/审计/派生字段（*Name、createTime、optionMap、stage 等）不回发：它们要么被后端
# 忽略、要么会报错；实测 update 也不会清空这类派生字段（departmentId/stage 不发也保留）。
merge_update_payload() {
  local existing_file="$1" caller_file="$2" form_file="${3:-}"
  "${PYTHON_CMD[@]}" - "$existing_file" "$caller_file" "$form_file" <<'PY'
import json, sys, tempfile, os

existing_file = sys.argv[1] if len(sys.argv) > 1 else ""
caller_file = sys.argv[2] if len(sys.argv) > 2 else ""
form_file = sys.argv[3] if len(sys.argv) > 3 else ""
try:
  with open(existing_file, encoding="utf-8") as stream:
    ex_wrap = json.load(stream)
except (OSError, json.JSONDecodeError) as e:
  sys.stderr.write(f"读回合并：现有记录解析失败: {e}\n"); sys.exit(1)
ex = ex_wrap.get("data") if isinstance(ex_wrap, dict) else None
if not isinstance(ex, dict) or not ex.get("id"):
  sys.stderr.write("读回合并：GET 未取到现有记录（id 不存在或已删除），中止以免清空字段\n"); sys.exit(1)
try:
  with open(caller_file, encoding="utf-8") as stream:
    caller = json.load(stream)
except (OSError, json.JSONDecodeError) as e:
  sys.stderr.write(f"读回合并：调用方 JSON 解析失败: {e}\n"); sys.exit(1)
if not isinstance(caller, dict):
  sys.stderr.write("读回合并：调用方 JSON 必须是对象\n"); sys.exit(1)

module_form_config = None
if form_file:
  try:
    with open(form_file, encoding="utf-8") as stream:
      form_wrap = json.load(stream)
  except (OSError, json.JSONDecodeError) as e:
    sys.stderr.write(f"读回合并：表单配置解析失败: {e}\n"); sys.exit(1)
  form_data = form_wrap.get("data") if isinstance(form_wrap, dict) else None
  if (not isinstance(form_wrap, dict) or form_wrap.get("code") != 100200
      or not isinstance(form_data, dict)
      or not isinstance(form_data.get("fields"), list)
      or not isinstance(form_data.get("formProp"), dict)):
    sys.stderr.write("读回合并：子表模块配置缺少 data.fields/formProp，中止更新\n")
    sys.exit(1)
  module_form_config = form_data

# 只读/展示/审计/派生字段：不回发（回发会被拒或无意义；实测不发也不会被清空）
DENY = {
  "attachmentMap","optionMap","contactName","customerName","departmentName","ownerName",
  "createUser","updateUser","createUserName","updateUserName","createTime","updateTime",
  "followerName","follower","followTime","stage","stageName","stageUpdateTime","lastStage",
  "inCustomerPool","poolId","possible","reservedDays","failureReason","organizationId","departmentId",
}

body = {}
for k, v in ex.items():
  if k == "moduleFields" or k in DENY or v is None:
    continue
  body[k] = v
# moduleFields：先取现有全部（归一为 fieldId->fieldValue），再用调用方覆盖
mf = {}
for m in ex.get("moduleFields", []) or []:
  fid = m.get("fieldId")
  if fid is not None:
    mf[fid] = m.get("fieldValue")
# 调用方的顶层变更覆盖现有值（含显式置空）
for k, v in caller.items():
  if k == "moduleFields":
    continue
  body[k] = v
for m in caller.get("moduleFields", []) or []:
  fid = m.get("fieldId")
  if fid is not None:
    mf[fid] = m.get("fieldValue")
body["moduleFields"] = [{"fieldId": k, "fieldValue": v} for k, v in mf.items()]
if module_form_config is not None:
  body["moduleFormConfigDTO"] = module_form_config

tmpfile = os.path.join(tempfile.gettempdir(), f'cordys_update_{os.getpid()}.json')
with open(tmpfile, 'w', encoding='utf-8') as f:
  json.dump(body, f, ensure_ascii=False)
print(tmpfile)
PY
}

# 写请求在传输层报错后，读取一次当前详情，并且只核对调用方明确要求修改的字段。
# stdout 始终是一条 JSON：全部目标值已落库时 code=100200/exit 0；否则
# writeState=unknown/retryAllowed=false/exit 1。此函数只读，不会重发写请求。
verify_update_after_transport_error() {
  local caller_file="$1" verify_file="${2:-}" expected_id="$3"
  "${PYTHON_CMD[@]}" - "$caller_file" "$verify_file" "$expected_id" <<'PY'
import json, os, sys

caller_file, verify_file, expected_id = sys.argv[1:4]

def emit_unknown(message, *, top_fields=None, module_field_ids=None,
                 mismatched_top=None, mismatched_module=None):
    result = {
        "code": 0,
        "data": {"id": expected_id},
        "writeState": "unknown",
        "retryAllowed": False,
        "message": message,
        "verification": {
            "topLevelFields": top_fields or [],
            "moduleFieldIds": module_field_ids or [],
            "mismatchedTopLevelFields": mismatched_top or [],
            "mismatchedModuleFieldIds": mismatched_module or [],
        },
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    raise SystemExit(1)

try:
    with open(caller_file, encoding="utf-8") as stream:
        caller = json.load(stream)
except (OSError, json.JSONDecodeError) as error:
    emit_unknown(f"写请求状态未知，且无法读取原始变更用于核验：{error}；禁止自动重试")

if not isinstance(caller, dict):
    emit_unknown("写请求状态未知，原始变更不是 JSON 对象；禁止自动重试")

if not verify_file or not os.path.isfile(verify_file):
    emit_unknown("写请求状态未知，更新后详情读取失败；禁止自动重试")

try:
    with open(verify_file, encoding="utf-8") as stream:
        wrapper = json.load(stream)
except (OSError, json.JSONDecodeError) as error:
    emit_unknown(f"写请求状态未知，更新后详情无法解析：{error}；禁止自动重试")

record = wrapper.get("data") if isinstance(wrapper, dict) else None
if (not isinstance(wrapper, dict) or str(wrapper.get("code")) != "100200"
        or not isinstance(record, dict)
        or str(record.get("id", "")) != str(expected_id)):
    emit_unknown("写请求状态未知，更新后详情响应无效或记录 ID 不一致；禁止自动重试")

ignored_top = {"id", "moduleFields", "moduleFormConfigDTO"}
expected_top = {
    key: value for key, value in caller.items() if key not in ignored_top
}
expected_module = {}
raw_module_fields = caller.get("moduleFields") or []
if not isinstance(raw_module_fields, list):
    emit_unknown("写请求状态未知，原始 moduleFields 不是数组；禁止自动重试")
for item in raw_module_fields:
    if not isinstance(item, dict) or item.get("fieldId") is None:
        emit_unknown("写请求状态未知，原始 moduleFields 含无效字段；禁止自动重试")
    expected_module[str(item["fieldId"])] = item.get("fieldValue")

top_fields = list(expected_top)
module_field_ids = list(expected_module)
if not top_fields and not module_field_ids:
    emit_unknown("写请求状态未知，调用方没有可读回核验的变更字段；禁止自动重试")

mismatched_top = [
    key for key, value in expected_top.items() if record.get(key) != value
]
actual_module = {
    str(item.get("fieldId")): item.get("fieldValue")
    for item in (record.get("moduleFields") or [])
    if isinstance(item, dict) and item.get("fieldId") is not None
}
mismatched_module = [
    field_id
    for field_id, value in expected_module.items()
    if field_id not in actual_module or actual_module[field_id] != value
]

if mismatched_top or mismatched_module:
    emit_unknown(
        "写请求状态未知，读回结果未确认全部目标字段；禁止自动重试",
        top_fields=top_fields,
        module_field_ids=module_field_ids,
        mismatched_top=mismatched_top,
        mismatched_module=mismatched_module,
    )

result = {
    "code": 100200,
    "data": {"id": expected_id},
    "verifiedAfterTransportError": True,
    "retryAllowed": False,
    "message": "写请求传输异常，但读回核验确认目标字段已更新；无需且禁止重试",
    "verification": {
        "topLevelFields": top_fields,
        "moduleFieldIds": module_field_ids,
    },
}
print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
PY
}

# 父维度取数的 body 构造器：把父 id 注入 body 顶层（客户维度 field=customerId，
# 合同维度 field=contractId），合并分页默认值后写临时文件。acct-sub / contract-sub 共用。
parent_payload() {
  local field="$1" parent_id="$2" schema_module="$3" user_json="${4:-}"
  printf '%s' "$user_json" |
    "${PYTHON_CMD[@]}" "${SOP_DIR}/payload_io.py" normalize-parent \
      "$field" "$parent_id" "$schema_module" "$SOP_DIR" "$QUERY_SCHEMA"
}

# 本地同步 schema 是子表事实来源。返回 true/false，供 create/update 在首次写入前
# 判断是否必须获取实时 module/form 并注入 moduleFormConfigDTO。
module_needs_form_config() {
  local module="$1"
  if [[ ! -f "${SOP_DIR}/payload_io.py" || ! -f "$QUERY_SCHEMA" ]]; then
    case "$module" in
      contract|invoice|opportunity/quotation|order)
        return 1
        ;;
      *)
        printf '%s\n' 'false'
        return 0
        ;;
    esac
  fi
  "${PYTHON_CMD[@]}" "${SOP_DIR}/payload_io.py" needs-form-config \
    "$module" "$QUERY_SCHEMA"
}

# 从 UTF-8 stdin 读取调用方 create JSON；通用模块剥离 owner，订单保留并校验合同 owner。
# 子表模块同时从 form_file 注入当前 moduleFormConfigDTO。最终 body 落原生临时文件，不进入 Windows argv。
prepare_create_payload() {
  local module="$1" form_file="${2:-}" contract_file="${3:-}"
  "${PYTHON_CMD[@]}" "${SOP_DIR}/payload_io.py" prepare-create \
    "$module" "$QUERY_SCHEMA" "$form_file" "$contract_file"
}

# ── API 封装（Header Key 鉴权）────────────────────────────────────────
json_body_file() {
  local raw="${1:-}"
  [[ -n "$raw" && "$raw" == \{* ]] || die "JSON body required"
  "${PYTHON_CMD[@]}" - "$raw" <<'PY'
import json, sys, tempfile, os

raw = sys.argv[1]
try:
  json.loads(raw)
except json.JSONDecodeError as exc:
  print(f"invalid JSON body: {exc}", file=sys.stderr)
  sys.exit(1)

tmpfile = os.path.join(tempfile.gettempdir(), f'cordys_{os.getpid()}.json')
with open(tmpfile, 'w', encoding='utf-8') as f:
  f.write(raw)
print(tmpfile)
PY
}

api_request() {
  local method="$1" url="$2" content_type="$3"
  shift 3
  check_keys
  # -S 保留网络/DNS/TLS 诊断；-s 单独使用会把 curl 失败变成空 stdout + exit 1。
  curl -sS --noproxy '*' -X "$method" "$url" \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "X-Request-Source: SKILL" \
    -H "Content-Type: $content_type; charset=utf-8" \
    "$@"
}

api() {
  api_request "$1" "$2" "application/json" "${@:3}"
}

api_form() {
  api_request "$1" "$2" "application/x-www-form-urlencoded" "${@:3}"
}

# Send a temporary JSON body and always remove it, including when curl fails.
# Without this wrapper, `set -e` exits before the old `rm` line and leaves a
# stale payload while the caller only sees an opaque non-zero status.
api_body_file() {
  local method="$1" url="$2" body_file="$3"
  shift 3
  local status=0
  api "$method" "$url" --data-binary "@${body_file}" "$@" || status=$?
  rm -f "$body_file" 2>/dev/null || true
  return "$status"
}

# 临时文件由原生 Windows Python 创建时可能是 C:\... 路径。清理属于收尾动作，
# 失败不得覆盖已经完成的 API 请求状态；rm 失败时再由同一 Python 运行时兜底。
cleanup_temp_file() {
  local path="${1:-}"
  [[ -n "$path" ]] || return 0
  if rm -f "$path" 2>/dev/null; then
    return 0
  fi
  "${PYTHON_CMD[@]}" - "$path" <<'PY' >/dev/null 2>&1 || true
import os, sys
try:
    os.remove(sys.argv[1])
except FileNotFoundError:
    pass
PY
  return 0
}

# 写操作专用：带"假失败真成功"检测。Cordys 后端偶发 HTTP 500/超时，但记录
# 可能已写入成功（body 里 code=100200）。这里用 curl -w 抓 http_code，非 2xx
# 时不直接判失败，而是把 response body 交给上层解析——只要 body 含 code=100200
# 即为成功。避免因盲目重试建出重复数据。
api_write() {
  local method="$1" url="$2"
  shift 2
  check_keys
  local resp http_code body curl_status=0 failure_status
  # 必须显式接住 curl 非零状态。若让 set -e 处理，POST 可能已在后端提交，
  # 但 Shell 会在赋值语句处直接退出，既没有响应 JSON，也没有读回核验机会。
  resp=$(curl -sS --noproxy '*' -w $'\n%{http_code}' -X "$method" "$url" \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "X-Request-Source: SKILL" \
    -H "Content-Type: application/json; charset=utf-8" \
    "$@") || curl_status=$?
  http_code="${resp##*$'\n'}"
  body="${resp%$'\n'*}"
  # Windows 原生进程/测试替身可能把 -w 的分隔换行写成 CRLF。空响应此时
  # 会被拆成单个 \r；若不剥离，就会误走“有 body”分支并只输出一个空行。
  http_code="${http_code%$'\r'}"
  body="${body%$'\r'}"

  if [[ -n "$body" ]]; then
    printf '%s\n' "$body"
    # HTTP/传输状态异常但业务响应明确成功，按成功终态返回；这是 Cordys
    # "假失败真成功"的可判定分支。JSON 无法解析或 code 非成功时继续交给
    # update 的单次读回核验，create/batch 则保留非零状态并禁止盲重试。
    if printf '%s' "$body" | "${PYTHON_CMD[@]}" -c \
      'import json,sys
try: value=json.load(sys.stdin)
except Exception: raise SystemExit(1)
raise SystemExit(0 if isinstance(value,dict) and str(value.get("code"))=="100200" else 1)'; then
      return 0
    fi
    if (( curl_status != 0 )) || [[ ! "$http_code" =~ ^2[0-9][0-9]$ ]]; then
      failure_status="$curl_status"
      (( failure_status != 0 )) || failure_status=1
      return "$failure_status"
    fi
    # 保持既有契约：HTTP 2xx 的业务错误体原样输出，由调用方按 code 判断。
    return 0
  fi

  failure_status="$curl_status"
  (( failure_status != 0 )) || failure_status=1
  printf '{"code":0,"message":"写请求无响应体，状态未知；禁止自动重试","http_code":"%s","curl_exit":%d,"writeState":"unknown","retryAllowed":false}\n' \
    "$http_code" "$failure_status"
  return "$failure_status"
}

# ── CRM 辅助函数 ──────────────────────────────────────────────────────
crm_base="${CORDYS_CRM_DOMAIN}"

crm_api_module() {
  case "${1:-}" in
    contact) printf '%s' 'account/contact' ;;
    *) printf '%s' "${1:-}" ;;
  esac
}

validate_write_module() {
  local module="${1:-}"
  case "${module}" in
    lead|account|opportunity|contact|account/contact|lead/follow/record|lead/follow/plan|account/follow/record|account/follow/plan|opportunity/follow/record|opportunity/follow/plan|contract|contract/payment-plan|contract/payment-record|invoice|contract/business-title|opportunity/quotation|order)
      ;;
    *)
      die "不支持的写入模块: ${module}"
      ;;
  esac
}

validate_batch_update_module() {
  local module="${1:-}"
  case "${module}" in
    lead|account|opportunity|contact|account/contact|contract|order)
      ;;
    *)
      die "batch-update 不支持的模块: ${module}。仅支持: lead, account, opportunity, contact, account/contact, contract, order"
      ;;
  esac
}

crm_view() {
  local module="${1:-}" opts="${2:-}"
  [[ -z "$opts" ]] || die "view 只接受模块名，不接受额外参数"
  local api_module
  case "$module" in
    follow) api_module="follow/record" ;;
    follow-plan) api_module="follow/plan" ;;
    *) api_module=$(crm_api_module "$module") ;;
  esac
  query_sync_if_needed
  if [[ "$module" == "contract/business-title" ]]; then
    printf '{"code":100200,"data":[]}\n'
    return
  fi
  api GET "${crm_base}/${api_module}/view/list"
}

crm_get() {
  local module="${1:-}" id="${2:-}"
  local api_module
  api_module=$(crm_api_module "$module")
  api GET "${crm_base}/${api_module}/get/${id}"
}

crm_contact() {
  local module="${1:-}" id="${2:-}"
  [[ "$module" == "opportunity" || "$module" == "account" ]] || die "contact 仅支持 opportunity 和 account 模块"
  api GET "${crm_base}/${module}/contact/list/${id}"
}

crm_page() {
  local module="${1:-}"
  shift
  # 防呆：member/user/org 不是 page 模块。这些端点不存在，后端会静默返回空，
  # 诱导上层反复猜端点。这里响亮报错并指向正确命令。
  case "${module}" in
    member|members|user|users|staff|employee|personnel)
      die "查用户不走 'crm page ${module}'（该端点不存在，会静默返回空）。查人取 userId 用：cordys.sh crm members --name 姓名（服务端按姓名过滤，自动补全公司部门范围）。详见 core/cli-spec.md §2.4。" ;;
    org|organization|dept|department)
      die "组织/部门不走 'crm page ${module}'。查完整部门树用 cordys.sh crm org；展开子部门ID用 crm org ids <部门>；做层级汇总用 crm org outline <部门>。详见 core/cli-spec.md §2.4/§10。" ;;
    follow|follows|followup|follow-up|followrecord|record|records)
      die "跟进记录不走 'crm page ${module}'（它会请求不存在的 /follow/page）。请使用全局列表命令：cordys.sh crm follow record '{...}'；字段条件放 combineSearch.conditions，按负责人用 owner、按时间用 followTime。" ;;
  esac
  local first="${1:-}"
  # 支持 stdin：first 为 - 或 @- 时从标准输入读 JSON。
  # 不加这条时，管道喂入的 JSON 会落到 else 分支被当成 keyword，静默返回空（已踩坑：@- → total=0）。
  if [[ "$first" == "-" || "$first" == "@-" ]]; then
    first=$(cat)
  fi
  # 防呆：签约后家族按父维度筛选走 acct-sub/contract-sub，别手搓 /page body。
  # customerId/accountId 出现在 body 任何位置（顶层键或 conditions）都拦——顶层 customerId 在
  # 这些 /page 上被静默忽略、返回全表（已实测：page contract 带顶层 customerId 仍返回 10315 全量）。
  # contractId 只拦 conditions 形式：顶层 contractId 是 payment-record/payment-plan 的合法过滤（contract-sub 内部即如此），放行。
  case "${module}" in
    contract|invoice|order|contract/payment-record|contract/payment-plan|contract/business-title|opportunity/quotation)
      if [[ "$first" =~ \"(customerId|accountId)\" ]]; then
        die "客户名下的 ${module} 走 cordys.sh crm acct-sub <子资源> <客户ID>（自动带 customerId）；在 /page body 里带 customerId/accountId（顶层或条件）会静默返回全表或报错。见 core/cli-spec.md §14。"
      fi
      if [[ "$first" =~ \"name\"[[:space:]]*:[[:space:]]*\"contractId\" ]]; then
        die "合同名下的回款/回款计划走 cordys.sh crm contract-sub payment-record|payment-plan <合同ID>（自动把 contractId 放对位置），不要放进 combineSearch.conditions。见 core/cli-spec.md §14。"
      fi ;;
  esac
  pool_query_preflight "$module" "$first" "page"
  query_sync_if_needed
  local body_file
  body_file=$(merge_payload "$first" "$module" "" "page")
  local path_module="$module"
  # 联系人实际列表端点挂在 account/contact 下；保留 contact 作为查询 CLI 别名。
  [[ "$module" == "contact" ]] && path_module="account/contact"
  local path="${path_module}/page"
  api_body_file POST "${CORDYS_CRM_DOMAIN}/${path}" "$body_file"
}

# 基于 page 端点逐页拉取并在本地进程内聚合；stdout 只返回固定大小摘要。
crm_page_summary() {
  local module="${1:-}" summary_raw="${2:-}"
  shift 2 2>/dev/null || true
  [[ -n "$module" && -n "$summary_raw" ]] || die "page-summary 用法: cordys.sh crm page-summary <module> <summaryJSON> [queryJSON|-]"
  local query_raw="${1:-}"
  [[ $# -le 1 ]] || die "page-summary 只接受 summary JSON 和一个可选查询 JSON"
  [[ "$summary_raw" == \{* ]] || die "page-summary 的 summaryJSON 必须是 JSON 对象"
  case "${module}" in
    member|members|user|users|staff|employee|personnel|org|organization|dept|department)
      die "${module} 不支持 page-summary；成员统计使用 crm members 的 total/compact 结果。" ;;
    follow|follows|followup|follow-up|followrecord|record|records)
      die "跟进记录不支持 page-summary；使用 crm follow record 的分页结果。" ;;
  esac
  check_keys

  local has_payload=0 payload_content=""
  if [[ "$query_raw" == "-" || "$query_raw" == "@-" ]]; then
    payload_content="$(cat)"
    has_payload=1
  elif [[ -n "$query_raw" ]]; then
    payload_content="$query_raw"
    has_payload=1
  fi

  pool_query_preflight "$module" "$payload_content" "page-summary"
  query_sync_if_needed

  local schema_module="$module" api_module="$module"
  case "$module" in
    contact|account/contact) schema_module="contact"; api_module="account/contact" ;;
    pool/lead) schema_module="lead" ;;
    pool/account) schema_module="account" ;;
  esac
  CORDYS_PS_DOMAIN="$CORDYS_CRM_DOMAIN" \
  CORDYS_PS_KEY="$CORDYS_ACCESS_KEY" \
  CORDYS_PS_SECRET="$CORDYS_SECRET_KEY" \
  CORDYS_PS_MODULE="$api_module" \
  CORDYS_PS_SCHEMA_MODULE="$schema_module" \
  CORDYS_PS_SCHEMA="$QUERY_SCHEMA" \
  CORDYS_PS_PAYLOAD="$payload_content" \
  CORDYS_PS_HAS_PAYLOAD="$has_payload" \
  CORDYS_PS_QUERY_MODE="page-summary" \
  CORDYS_PS_SUMMARY="$summary_raw" \
  CORDYS_SOP_DIR="$SOP_DIR" \
  "${PYTHON_CMD[@]}" <<'PY'
import json, os, sys

sys.path.insert(0, os.environ['CORDYS_SOP_DIR'])
from paginate import PAGE_SIZE, iter_pages, summarize_pages, validate_summary_spec

try:
    raw_spec = json.loads(os.environ['CORDYS_PS_SUMMARY'])
    spec = validate_summary_spec(raw_spec, os.environ['CORDYS_PS_SCHEMA_MODULE'], os.environ['CORDYS_PS_SCHEMA'])
except (OSError, ValueError, json.JSONDecodeError) as error:
    print(json.dumps({"error": f"page-summary 配置无效: {error}"}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)

try:
    data = summarize_pages(iter_pages('CORDYS_PS', 'page-summary'), spec)
except ValueError as error:
    print(json.dumps({"error": f"page-summary 聚合失败: {error}"}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)
data["pageSize"] = PAGE_SIZE
print(json.dumps({"code": 100200, "data": data}, ensure_ascii=False))
PY
}

crm_search() {
  local module="${1:-}" json="${2:-}"
  if [[ "${module}" == "opportunity/quotation" ]]; then
    crm_page "${module}" "${json}"
    return
  fi
  case "${module}" in
    member|members|user|users|staff|employee|personnel|org|organization|dept|department)
      die "查用户/组织不走 'crm search ${module}'（端点不存在，静默返回空）。查用户用 cordys.sh crm members（见 core/cli-spec.md §2.4）；查完整部门树用 crm org，展开ID用 crm org ids <部门>，层级汇总用 crm org outline <部门>。" ;;
    contract|invoice|order|contract/payment-record|contract/payment-plan|contract/business-title|opportunity/quotation)
      die "${module} 无全局搜索，按父维度取数：客户名下用 cordys.sh crm acct-sub <子资源> <客户ID>；合同名下用 cordys.sh crm contract-sub payment-record|payment-plan|invoice-stat <合同ID>；只有名称关键词用 cordys.sh crm page ${module} '{\"keyword\":\"关键词\"}'。见 core/cli-spec.md §14。" ;;
    follow|follows|followup|follow-up|followrecord|record|records)
      die "跟进记录不走 'crm search ${module}'。请使用全局列表命令：cordys.sh crm follow record '{\"keyword\":\"关键词\"}'；结构化字段条件放 combineSearch.conditions。" ;;
  esac
  # 支持 stdin：- 或 @- 时从标准输入读 JSON，否则管道 JSON 会被当 keyword 静默返回空。
  if [[ "$json" == "-" || "$json" == "@-" ]]; then
    json=$(cat)
  fi
  pool_query_preflight "$module" "$json" "search"
  query_sync_if_needed
  local body_file
  body_file=$(merge_payload "$json" "$module" "" "search")
  # 联系人按姓名/关键词走其真实列表端点；/global/search/contact 对姓名命中不可靠。
  if [[ "$module" == "contact" || "$module" == "account/contact" ]]; then
    local path="account/contact/page"
    api_body_file POST "${CORDYS_CRM_DOMAIN}/${path}" "$body_file"
    return
  fi
  # 池模块全局搜索端点命名与 page 不同：pool/lead → clue_pool，pool/account → customer_pool
  local search_module="${module}"
  case "${module}" in
    pool/lead)    search_module="clue_pool" ;;
    pool/account) search_module="customer_pool" ;;
  esac
  local path="global/search/${search_module}"
  api_body_file POST "${CORDYS_CRM_DOMAIN}/${path}" "$body_file"
}

crm_follow_page() {
  local kind="${1:-}" first="${2:-}" second="${3:-}"
  local legacy_module="" payload=""
  [[ "${kind}" == "plan" || "${kind}" == "record" ]] || die "follow 子命令只支持 plan/record"
  [[ $# -le 3 ]] || die "follow 用法: cordys.sh crm follow <plan|record> [JSON|-]"
  case "$first" in
    lead|account|opportunity)
      legacy_module="$first"
      payload="$second"
      ;;
    *)
      [[ -z "$second" ]] || die "follow 新版用法只接受一个关键词、JSON 或 stdin 标记"
      payload="$first"
      ;;
  esac
  if [[ "$payload" == "-" || "$payload" == "@-" ]]; then
    payload=$(cat)
  fi
  query_sync_if_needed
  local body_file
  body_file=$(printf '%s' "$payload" |
    "${PYTHON_CMD[@]}" "${SOP_DIR}/payload_io.py" normalize-follow \
      "$kind" "$legacy_module" "$SOP_DIR" "$QUERY_SCHEMA") ||
    die "跟进查询参数归一化失败"
  api_body_file POST "${crm_base}/follow/${kind}/page" "$body_file"
}

crm_follow_get() {
  local kind="${1:-}" module="${2:-}" id="${3:-}"
  [[ "${kind}" == "plan" || "${kind}" == "record" ]] || die "follow-get 只支持 plan/record"
  [[ "${module}" == "lead" || "${module}" == "account" || "${module}" == "opportunity" ]] ||
    die "follow-get ${kind} 的模块必须为 lead/account/opportunity"
  [[ "${id}" =~ ^[0-9]+$ ]] || die "follow-get ${kind} 需要合法的数字 ID"
  query_sync_if_needed
  api GET "${crm_base}/${module}/follow/${kind}/get/${id}"
}

# ── 写入操作（创建/更新/转化）─────────────────────────────────────────

# 获取模块表单定义
# 用法: crm_form <模块>            → GET /{module}/module/form
#       crm_form account/contact   → GET /account/contact/module/form
crm_form() {
  local module="${1:-}"
  validate_write_module "${module}"
  write_sync_if_needed
  local api_module
  api_module=$(crm_api_module "$module")
  api GET "${crm_base}/${api_module}/module/form"
}

# 创建记录
# 用法: crm_add <模块> <JSON|->
# 调用方 JSON 和实时表单配置全走 stdin/临时文件；含子表模块自动附加
# moduleFormConfigDTO，再由 api_write 做假失败检测。只发一次写请求，禁止失败后盲重试。
crm_add() {
  local module="${1:-}" payload_arg="${2:-}"
  [[ $# -le 2 ]] || die "create 只接受模块和一个 JSON body"
  validate_write_module "${module}"
  [[ -n "${payload_arg}" ]] || die "add 需要 JSON body（- 或 @- 从 UTF-8 stdin 读取）"
  write_sync_if_needed
  local api_module needs_form form_file="" contract_file="" caller_file=""
  local contract_id="" body_file="" status=0 split_enabled="false"
  api_module=$(crm_api_module "$module")

  # 先把调用方 JSON 固定到 UTF-8 文件。订单默认进入一次性批次编排：
  # 所有读请求和全部 payload 都会在首个 POST 前完成，随后逐组顺序创建。
  if [[ -f "${SOP_DIR}/payload_io.py" ]]; then
    case "${payload_arg}" in
      -|@-)
        caller_file=$(json_stdin_file "${module} create 请求")
        ;;
      *)
        caller_file=$(printf '%s' "$payload_arg" |
          json_stdin_file "${module} create 请求")
        ;;
    esac || die "读取 create 请求体失败"
    if [[ "$module" == "order" ]]; then
      split_enabled=$("${PYTHON_CMD[@]}" "${SOP_DIR}/payload_io.py" \
        order-split-enabled < "$caller_file") || {
          cleanup_temp_file "$caller_file"
          die "读取订单拆单模式失败"
        }
      if [[ "$split_enabled" == "true" ]]; then
        [[ -f "${SOP_DIR}/order_batch.py" ]] || {
          cleanup_temp_file "$caller_file"
          die "当前技能副本缺少 order_batch.py，无法安全执行自动拆单"
        }
        check_keys
        "${PYTHON_CMD[@]}" "${SOP_DIR}/order_batch.py" \
          "$QUERY_SCHEMA" < "$caller_file" || status=$?
        cleanup_temp_file "$caller_file"
        return "$status"
      fi
    fi
  fi

  needs_form=$(module_needs_form_config "$module") || {
    cleanup_temp_file "$caller_file"
    die "判断 ${module} 是否含子表失败"
  }
  if [[ "$needs_form" == "true" ]]; then
    form_file=$(api GET "${crm_base}/${api_module}/module/form" |
      json_stdin_file "${module} 表单配置响应") || {
        cleanup_temp_file "$caller_file"
        die "获取 ${module} 表单配置失败"
      }
  fi
  if [[ -f "${SOP_DIR}/payload_io.py" ]]; then
    if [[ "$module" == "order" ]]; then
      contract_id=$("${PYTHON_CMD[@]}" "${SOP_DIR}/payload_io.py" \
        order-contract-id < "$caller_file") || {
          cleanup_temp_file "$caller_file"
          cleanup_temp_file "$form_file"
          die "订单 create 缺少合法 contractId"
        }
      contract_file=$(api GET "${crm_base}/contract/get/${contract_id}" |
        json_stdin_file "订单合同详情响应") || {
          cleanup_temp_file "$caller_file"
          cleanup_temp_file "$form_file"
          die "获取订单源合同详情失败"
        }
    fi
    body_file=$(prepare_create_payload \
      "$module" "$form_file" "$contract_file" < "$caller_file")
  else
    # 兼容只复制单个 cordys.sh 的旧测试/诊断夹具；正式技能包始终包含
    # payload_io.py。子表模块已在 module_needs_form_config 阶段 fail closed。
    case "${payload_arg}" in
      -|@-) die "当前技能副本缺少 payload_io.py，无法从 stdin 创建" ;;
      *) body_file=$(write_payload "$payload_arg" strip) ;;
    esac
  fi || {
    cleanup_temp_file "$caller_file"
    cleanup_temp_file "$contract_file"
    cleanup_temp_file "$form_file"
    die "构建 create 请求体失败"
  }
  cleanup_temp_file "$caller_file"
  cleanup_temp_file "$contract_file"
  cleanup_temp_file "$form_file"
  api_write POST "${crm_base}/${api_module}/add" \
    --data-binary "@${body_file}" || status=$?
  cleanup_temp_file "$body_file"
  return "$status"
}

# 更新记录
# 用法: crm_update <模块> <JSON>   → JSON 中必须包含 id 字段
# 读回合并：先 GET 现有记录，把调用方要改的字段覆盖上去再整体发。调用方只需传 id + 要改的
# 字段，其余（结束日期、owner、所有 moduleField）由脚本自动保全，不受 /update 全量覆盖影响。
crm_update() {
  local module="${1:-}" payload_arg="${2:-}" payload
  validate_write_module "${module}"
  case "${payload_arg}" in
    -|@-) payload=$(cat) ;;
    *) payload="${payload_arg}" ;;
  esac
  [[ -n "${payload}" && "${payload}" == \{* ]] || die "update 需要 JSON body（须包含 id）"
  local id
  id=$(printf '%s' "$payload" | "${PYTHON_CMD[@]}" -c 'import sys,json;
try: d=json.load(sys.stdin)
except Exception: d={}
print((d or {}).get("id","") if isinstance(d,dict) else "")')
  [[ -n "$id" ]] || die "update 的 JSON body 必须包含 id"
  write_sync_if_needed
  local api_module
  api_module=$(crm_api_module "$module")
  local caller_file existing_file form_file="" body_file
  caller_file=$(printf '%s' "$payload" | json_stdin_file "调用方更新 JSON") ||
    die "构建调用方更新请求失败"
  existing_file=$(api GET "${crm_base}/${api_module}/get/${id}" |
    json_stdin_file "现有记录响应") || {
      cleanup_temp_file "$caller_file"
      die "获取现有记录失败"
    }
  local needs_form
  needs_form=$(module_needs_form_config "$module") || {
    cleanup_temp_file "$caller_file"
    cleanup_temp_file "$existing_file"
    die "判断 ${module} 是否含子表失败"
  }
  if [[ "$needs_form" == "true" ]]; then
    form_file=$(api GET "${crm_base}/${api_module}/module/form" |
      json_stdin_file "${module} 表单配置响应") || {
        cleanup_temp_file "$caller_file"
        cleanup_temp_file "$existing_file"
        die "获取 ${module} 表单配置失败"
      }
  fi
  body_file=$(merge_update_payload "$existing_file" "$caller_file" "$form_file") || {
    cleanup_temp_file "$caller_file"
    cleanup_temp_file "$existing_file"
    cleanup_temp_file "$form_file"
    die "读回合并失败（GET 未取到记录、JSON 解析失败或表单配置不完整）"
  }
  cleanup_temp_file "$existing_file"
  cleanup_temp_file "$form_file"
  local write_output="" write_status=0 verify_file="" verify_fetch_status=0
  local verification_output="" verification_status=0
  write_output=$(api_write POST "${crm_base}/${api_module}/update" \
    --data-binary "@${body_file}") || write_status=$?
  cleanup_temp_file "$body_file"
  if (( write_status == 0 )); then
    cleanup_temp_file "$caller_file"
    printf '%s\n' "$write_output"
    return 0
  fi

  # 写请求只发上面一次。传输层或 HTTP 状态异常时，仅 GET 一次当前详情，
  # 对调用方明确修改的字段做读回核验，绝不自动重发 POST。
  verify_file=$(api GET "${crm_base}/${api_module}/get/${id}" |
    json_stdin_file "更新后读回核验响应") || verify_fetch_status=$?
  if (( verify_fetch_status != 0 )); then
    cleanup_temp_file "$verify_file"
    verify_file=""
  fi
  verification_output=$(verify_update_after_transport_error \
    "$caller_file" "$verify_file" "$id") || verification_status=$?
  cleanup_temp_file "$caller_file"
  cleanup_temp_file "$verify_file"
  if [[ -n "$write_output" ]]; then
    printf ':: 写请求传输结果（已停止重试并执行一次读回核验）: %s\n' \
      "$write_output" >&2
  fi
  printf '%s\n' "$verification_output"
  if (( verification_status == 0 )); then
    return 0
  fi
  return "$write_status"
}

# 批量更新（按字段批量修改多条记录的同一字段值）
# 用法: crm_batch_update <模块> '{"ids":["id1","id2"],"fieldId":"字段key","fieldValue":"新值"}'
crm_batch_update() {
  local module="${1:-}" payload="${2:-}"
  validate_batch_update_module "${module}"
  [[ -n "${payload}" && "${payload}" == \{* ]] || die "batch-update 需要 JSON body（须包含 ids, fieldId, fieldValue）"
  write_sync_if_needed
  local body_file
  body_file=$(write_payload "$payload") || die "构建请求体失败"
  local api_module
  api_module=$(crm_api_module "$module")
  local status=0
  api_write POST "${crm_base}/${api_module}/batch/update" \
    --data-binary "@${body_file}" || status=$?
  cleanup_temp_file "$body_file"
  return "$status"
}

legacy_transform_disabled() {
  die "crm transform/transition 已禁用：裸端点会静默丢失商机字段。请改用 scripts/cordys_ext.sh transform '<JSON>'"
}

# ── 审批相关 ──────────────────────────────────────────────────────────

crm_approval_todo() {
  local kind="${1:-}" payload="${2:-}"
  local body_file
  if [[ "${payload}" == \{* ]]; then
    body_file=$(merge_payload "${payload}")
  else
    body_file=$(page_payload "${payload}")
  fi
  case "${kind}" in
    pending)   api POST "${crm_base}/approval-todo/pending/page" --data-binary "@${body_file}" ;;
    processed) api POST "${crm_base}/approval-todo/processed/page" --data-binary "@${body_file}" ;;
    initiated) api POST "${crm_base}/approval-todo/initiated/page" --data-binary "@${body_file}" ;;
    cc)        api POST "${crm_base}/approval-todo/cc/page" --data-binary "@${body_file}" ;;
    count)     rm -f "$body_file"; api GET "${crm_base}/approval-todo/pending/count"; return ;;
    *) rm -f "$body_file"; die "未知的审批代办类型: ${kind}。支持: pending, processed, initiated, cc, count" ;;
  esac
  rm -f "$body_file"
}

crm_approval_action() {
  local action="${1:-}" payload="${2:-}"
  [[ -n "${payload}" && "${payload}" == \{* ]] || die "${action} 需要 JSON body"
  local body_file
  body_file=$(json_body_file "$payload")
  case "${action}" in
    approve)       api POST "${crm_base}/approval-action/approve" --data-binary "@${body_file}" ;;
    reject)        api POST "${crm_base}/approval-action/reject" --data-binary "@${body_file}" ;;
    back)          api POST "${crm_base}/approval-action/back" --data-binary "@${body_file}" ;;
    sign)          api POST "${crm_base}/approval-action/sign" --data-binary "@${body_file}" ;;
    revoke)        api POST "${crm_base}/approval-action/revoke" --data-binary "@${body_file}" ;;
    batch-approve) api POST "${crm_base}/approval-action/batch-approve" --data-binary "@${body_file}" ;;
    batch-reject)  api POST "${crm_base}/approval-action/batch-reject" --data-binary "@${body_file}" ;;
    *) rm -f "$body_file"; die "未知的审批操作: ${action}。支持: approve, reject, back, sign, revoke, batch-approve, batch-reject" ;;
  esac
  rm -f "$body_file"
}

crm_approval_resource() {
  local action="${1:-}"
  shift
  # nounset 下未绑定的 $1 会直接崩，统一取可空的 arg，缺 resourceId/JSON 时清晰报错。
  local arg="${1:-}" bf
  case "${action}" in
    push)          bf=$(json_body_file "$arg"); api POST "${crm_base}/approval-resource/push" --data-binary "@${bf}"; rm -f "$bf" ;;
    revoke)        bf=$(json_body_file "$arg"); api POST "${crm_base}/approval-resource/revoke" --data-binary "@${bf}"; rm -f "$bf" ;;
    simple-detail) [[ -n "$arg" ]] || die "resource simple-detail 需要 resourceId"; api GET "${crm_base}/approval-resource/simple-detail/${arg}" ;;
    detail)        [[ -n "$arg" ]] || die "resource detail 需要 resourceId"; api GET "${crm_base}/approval-resource/detail/${arg}" ;;
    *) die "未知的审批资源操作: ${action}。支持: push, revoke, simple-detail, detail" ;;
  esac
}

crm_approval_flow() {
  local action="${1:-}"
  shift
  # nounset 下未绑定的 $1 会直接崩，统一取可空的 arg；list 允许空（查全部），其余需要 ID/JSON 时清晰报错。
  local arg="${1:-}" bf
  case "${action}" in
    list)         bf=$(merge_payload "$arg"); api POST "${crm_base}/approval-flow/page" --data-binary "@${bf}"; rm -f "$bf" ;;
    get)          [[ -n "$arg" ]] || die "flow get 需要审批流 ID"; api GET "${crm_base}/approval-flow/get/${arg}" ;;
    add)          [[ -n "$arg" ]] || die "flow add 需要 JSON body"; api POST "${crm_base}/approval-flow/add" --data-binary "$arg" ;;
    update)       [[ -n "$arg" ]] || die "flow update 需要 JSON body"; api POST "${crm_base}/approval-flow/update" --data-binary "$arg" ;;
    enable)       [[ -n "$arg" ]] || die "flow enable 需要审批流 ID"; api GET "${crm_base}/approval-flow/enable/${arg}?enable=true" ;;
    disable)      [[ -n "$arg" ]] || die "flow disable 需要审批流 ID"; api GET "${crm_base}/approval-flow/enable/${arg}?enable=false" ;;
    by-form)      [[ -n "$arg" ]] || die "flow by-form 需要表单类型（contract/quotation/invoice/order）"; api GET "${crm_base}/approval-flow/get-by-form-type/${arg}" ;;
    setting)      [[ -n "$arg" ]] || die "flow setting 需要审批流 ID"; api GET "${crm_base}/approval-flow/status-permission/setting/${arg}" ;;
    webhook-test) bf=$(json_body_file "$arg"); api POST "${crm_base}/approval-flow/webhook/test" --data-binary "@${bf}"; rm -f "$bf" ;;
    *) die "未知的审批流操作: ${action}" ;;
  esac
}

# ── 产品 ──────────────────────────────────────────────────────────────
crm_product() {
  local keyword="${1:-}"
  if [[ "$keyword" == "-" || "$keyword" == "@-" ]]; then
    keyword=$(cat)
  fi
  local body_file
  if [[ "$keyword" == \{* ]]; then
    body_file=$(merge_payload "$keyword")
  else
    body_file=$(page_payload "${keyword}")
  fi
  api_body_file POST "${CORDYS_CRM_DOMAIN}/field/source/product" "$body_file"
}


# ── 枚举字段分布 ──────────────────────────────────────────────────────
# 按枚举字段逐桶统计；每个桶只取 pageSize:1 的 total，不拉取全量明细。
# 用法: cordys.sh crm dist <module> <field> [baseJSON|-] [values]
#   field   枚举字段名（stage，或 fieldId 如 1751888184000030）
#   baseJSON 范围/时间/部门条件，传一次（省略=全量）
#   values  逗号分隔值列表，仅当字段不在 optionMap（如 stage）时需要
crm_dist() {
  local module="${1:-}" field="${2:-}" payload="${3:-}" values="${4:-}"
  [[ -n "$module" && -n "$field" ]] || die "dist 用法: cordys.sh crm dist <module> <field> [baseJSON|-] [values]"
  check_keys

  local has_payload=0 payload_content=""
  if [[ "$payload" == "-" || "$payload" == "@-" ]]; then
    payload_content="$(cat)"
    has_payload=1
  elif [[ -n "$payload" ]]; then
    payload_content="$payload"
    has_payload=1
  fi

  CORDYS_DIST_DOMAIN="$CORDYS_CRM_DOMAIN" \
  CORDYS_DIST_KEY="$CORDYS_ACCESS_KEY" \
  CORDYS_DIST_SECRET="$CORDYS_SECRET_KEY" \
  CORDYS_DIST_MODULE="$module" \
  CORDYS_DIST_SCHEMA="$QUERY_SCHEMA" \
  CORDYS_SOP_DIR="$SOP_DIR" \
  CORDYS_DIST_FIELD="$field" \
  CORDYS_DIST_VALUES="$values" \
  CORDYS_DIST_PAYLOAD="$payload_content" \
  CORDYS_DIST_HAS_PAYLOAD="$has_payload" \
  "${PYTHON_CMD[@]}" <<'PY'
import copy, json, os, sys, urllib.error, urllib.request

sys.path.insert(0, os.environ['CORDYS_SOP_DIR'])
from query_contract import (QueryContractError, validate_distribution_field,
                            validate_payload, validate_query_semantics)

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8')
    except Exception:
        pass

domain = os.environ['CORDYS_DIST_DOMAIN']
access_key = os.environ['CORDYS_DIST_KEY']
secret_key = os.environ['CORDYS_DIST_SECRET']
module = os.environ['CORDYS_DIST_MODULE']
field = os.environ['CORDYS_DIST_FIELD']
values_arg = os.environ.get('CORDYS_DIST_VALUES', '').strip()
payload_raw = os.environ.get('CORDYS_DIST_PAYLOAD', '')
has_payload = os.environ.get('CORDYS_DIST_HAS_PAYLOAD', '0') == '1'
schema_path = os.environ.get('CORDYS_DIST_SCHEMA')
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def api_post(path, body):
    request = urllib.request.Request(
        f"{domain}{path}",
        data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
        method='POST',
        headers={
            'X-Access-Key': access_key,
            'X-Secret-Key': secret_key,
            'Content-Type': 'application/json; charset=utf-8',
        },
    )
    try:
        with opener.open(request, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        return json.loads(error.read().decode('utf-8'))

def fail(message):
    print(json.dumps({'code': 40000, 'message': message}, ensure_ascii=False))
    sys.exit(1)

base = {}
raw = (payload_raw or '').lstrip('\ufeff').strip()
if has_payload:
    if not raw:
        fail('dist: 收到空 baseJSON，已中止以避免误查全量')
    try:
        base = json.loads(raw)
    except json.JSONDecodeError as error:
        fail(f'dist: baseJSON 不是合法 JSON: {error}')
if not isinstance(base, dict):
    fail('dist: baseJSON 顶层必须是对象')
if 'combineSearch' not in base:
    for key in list(base.keys()):
        if isinstance(key, str) and key.lower() == 'combinesearch':
            base['combineSearch'] = base.pop(key)
            break
cs = base.get('combineSearch') or {'searchMode': 'AND', 'conditions': []}
cs.setdefault('searchMode', 'AND')
cs.setdefault('conditions', [])
try:
    base = validate_payload(module, base, schema_path)
    base = validate_query_semantics(module, base, 'dist')
    cs = base['combineSearch']
    base_conditions = cs['conditions']
    explicit_values = [value.strip() for value in values_arg.split(',') if value.strip()]
    bucket_type = validate_distribution_field(module, field, explicit_values, schema_path)
except QueryContractError as error:
    fail(f'dist 查询条件无效: {error}')

probe = copy.deepcopy(base)
probe['combineSearch'] = {'searchMode': cs['searchMode'], 'conditions': base_conditions}
probe['current'] = 1
probe['pageSize'] = 1
probe.setdefault('viewId', 'ALL')
probe_response = api_post(f'/{module}/page', probe)
if probe_response.get('code') != 100200:
    print(json.dumps(probe_response, ensure_ascii=False))
    sys.exit(1)
option_map = (probe_response.get('data') or {}).get('optionMap', {}) or {}

buckets = []
if values_arg:
    buckets = [(value.strip(), None) for value in values_arg.split(',') if value.strip()]
elif field in option_map:
    buckets = [(option.get('id'), option.get('name')) for option in option_map[field]]
else:
    fail(f"dist: 字段 {field} 不在 optionMap（仅含 {', '.join(option_map.keys())}）；"
         '系统码值字段（如 stage）请用第 4 参数传值列表，如 CREATE,SUCCESS,FAIL')

stat_path = {
    'opportunity': '/opportunity/statistic',
    'contract': '/contract/statistic',
    'contract/payment-record': '/contract/payment-record/statistic',
    'order': '/order/statistic',
}.get(module)
results = []
total_count = 0
total_amount = 0.0
for value, label in buckets:
    body = copy.deepcopy(base)
    body['combineSearch'] = {
        'searchMode': cs['searchMode'],
        'conditions': list(base_conditions) + [
            {'operator': 'IN', 'name': field, 'value': [value], 'type': bucket_type}
        ],
    }
    try:
        body = validate_payload(module, body, schema_path)
    except QueryContractError as error:
        fail(f'dist 自动分桶条件无效: {error}')
    body.setdefault('viewId', 'ALL')

    count_body = copy.deepcopy(body)
    count_body['current'] = 1
    count_body['pageSize'] = 1
    count_response = api_post(f'/{module}/page', count_body)
    if count_response.get('code') != 100200:
        print(json.dumps(count_response, ensure_ascii=False))
        sys.exit(1)
    data = count_response.get('data') or {}
    count = data.get('total', 0) or 0
    if label is None:
        record = (data.get('list') or [None])[0]
        label = record.get(field + 'Name') if isinstance(record, dict) else None
        label = label or value

    amount = None
    if stat_path:
        statistic_response = api_post(stat_path, body)
        if statistic_response.get('code') == 100200:
            try:
                amount = float((statistic_response.get('data') or {}).get('amount', 0) or 0)
            except (TypeError, ValueError):
                amount = 0.0
    results.append({'value': value, 'name': label, 'count': count, 'amount': amount})
    total_count += count
    if amount is not None:
        total_amount += amount

print(json.dumps({
    'code': 100200,
    'field': field,
    'data': results,
    'total': {'count': total_count, 'amount': total_amount if stat_path else None},
}, ensure_ascii=False))
PY
}

# ── 用户与组织 ─────────────────────────────────────────────────────────
crm_whoami() {
  api GET "${crm_base}/personal/center/info"
}

crm_verify() {
  local result
  result=$(crm_whoami 2>&1) || {
    echo "{\"status\":\"error\",\"message\":\"API密钥验证失败\",\"detail\":\"$result\"}"
    return 1
  }
  echo "$result"
}

crm_org() {
  local mode="${1:-tree}"
  case "$mode" in
    tree)
      [[ $# -le 1 ]] || die "crm org tree 不接受额外参数"
      api GET "${crm_base}/department/tree" --connect-timeout 10 --max-time 20
      ;;
    ids|outline)
      [[ $# -le 2 ]] || die "crm org ${mode} 只接受一个可选的部门名称或 ID"
      local target="${2:-}"
      api GET "${crm_base}/department/tree" --connect-timeout 10 --max-time 20 |
        "${PYTHON_CMD[@]}" "${SOP_DIR}/org_tree.py" "$mode" "$target"
      ;;
    *)
      die "未知的 crm org 模式: ${mode}。支持: tree, ids [部门名称或ID], outline [部门名称或ID]"
      ;;
  esac
}

crm_members() {
  local filter_name="" payload="" compact="0" active="0" exact_departments="0" payload_seen="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --name)
        [[ $# -ge 2 && -n "$2" ]] || die "crm members --name 需要非空姓名"
        filter_name="$2"
        shift 2
        ;;
      --compact)
        compact="1"
        shift
        ;;
      --active)
        active="1"
        shift
        ;;
      --exact-departments)
        exact_departments="1"
        shift
        ;;
      --*) die "未知 members 参数: $1" ;;
      *)
        [[ "$payload_seen" == "0" ]] || die "crm members 只接受一个 JSON/关键词参数"
        payload="$1"
        payload_seen="1"
        shift
        ;;
    esac
  done

  if [[ "$payload" == "-" || "$payload" == "@-" ]]; then
    payload=$(cat)
  fi

  # 所有成员查询统一为一个原生 Python 进程：显式 departmentIds 默认先按
  # 部门树递归展开本部门和全部子孙部门；仅 --exact-departments 跳过展开。
  # 未提供范围时读 6 小时全公司 ID 缓存或 GET 部门树。全链路不自动重试。
  check_keys
  CORDYS_FILTER_NAME="$filter_name" \
  CORDYS_MEMBERS_PAYLOAD="$payload" \
  CORDYS_MEMBERS_COMPACT="$compact" \
  CORDYS_MEMBERS_ACTIVE="$active" \
  CORDYS_MEMBERS_EXACT_DEPARTMENTS="$exact_departments" \
  CORDYS_MEMBERS_FROM_ENV="1" \
    "${PYTHON_CMD[@]}" "${SOP_DIR}/members_query.py"
}

# ── 原始 API 调用 ─────────────────────────────────────────────────────
# Server-side statistics and L2C helper APIs.
crm_stat() {
  local module="${1:-}" payload="${2:-}"
  if [[ "$payload" == "-" || "$payload" == "@-" ]]; then
    payload=$(cat)
  fi
  local body_file
  body_file=$(merge_payload "$payload" "$module" "json-only" "stat")
  case "${module}" in
    contract)                api_body_file POST "${crm_base}/contract/statistic" "$body_file" ;;
    contract/payment-record) api_body_file POST "${crm_base}/contract/payment-record/statistic" "$body_file" ;;
    opportunity)             api_body_file POST "${crm_base}/opportunity/statistic" "$body_file" ;;
    order)                   api_body_file POST "${crm_base}/order/statistic" "$body_file" ;;
    *) rm -f "$body_file"; die "unsupported stat module: ${module}. supported: contract, contract/payment-record, opportunity, order" ;;
  esac
}

crm_stat_home() {
  local kind="${1:-}" payload="${2:-}"
  if [[ "$payload" == "-" || "$payload" == "@-" ]]; then
    payload=$(cat)
  fi
  local body_file
  if [[ "${payload}" == \{* ]]; then
    body_file=$(json_body_file "$payload")
  else
    body_file=$(json_body_file '{"searchType":"SELF","timeField":"CREATE_TIME","userField":"OWNER","priorPeriodEnable":true}')
  fi
  case "${kind}" in
    lead)                 api_body_file POST "${crm_base}/home/statistic/lead" "$body_file" ;;
    opportunity)          api_body_file POST "${crm_base}/home/statistic/opportunity" "$body_file" ;;
    opportunity/success)  api_body_file POST "${crm_base}/home/statistic/opportunity/success" "$body_file" ;;
    opportunity/underway) api_body_file POST "${crm_base}/home/statistic/opportunity/underway" "$body_file" ;;
    dept-tree)            rm -f "$body_file"; api GET "${crm_base}/home/statistic/department/tree"; return ;;
    *) rm -f "$body_file"; die "unsupported home stat type: ${kind}. supported: lead, opportunity, opportunity/success, opportunity/underway, dept-tree" ;;
  esac
}

crm_glocount() {
  local keyword="${1:-}"
  [[ -n "${keyword}" ]] || die "glocount requires keyword"
  local encoded
  encoded=$("${PYTHON_CMD[@]}" - "$keyword" <<'PY'
from urllib.parse import quote
import sys
print(quote(sys.argv[1], safe=""))
PY
)
  api POST "${crm_base}/global/search/module/count?keyword=${encoded}"
}

crm_acct_sub() {
  local sub="${1:-}" acct_id="${2:-}" payload="${3:-}"
  [[ -n "${sub}" && -n "${acct_id}" ]] || die "acct-sub requires sub resource and account ID"
  if [[ "$payload" == "-" || "$payload" == "@-" ]]; then
    payload=$(cat)
  fi
  case "${sub}" in
    contract-stat)       api GET "${crm_base}/account/contract/statistic/${acct_id}"; return ;;
    payment-plan-stat)   api GET "${crm_base}/account/contract/payment-plan/statistic/${acct_id}"; return ;;
    payment-record-stat) api GET "${crm_base}/account/contract/payment-record/statistic/${acct_id}"; return ;;
    invoice-stat)        api GET "${crm_base}/account/invoice/statistic/${acct_id}"; return ;;
  esac
  local body_file
  local schema_module
  case "$sub" in
    contract) schema_module="contract" ;;
    opportunity) schema_module="opportunity" ;;
    payment-record) schema_module="contract/payment-record" ;;
    payment-plan) schema_module="contract/payment-plan" ;;
    *) schema_module="$sub" ;;
  esac
  body_file=$(parent_payload customerId "$acct_id" "$schema_module" "$payload")
  case "${sub}" in
    contract)            api_body_file POST "${crm_base}/account/contract/page" "$body_file" ;;
    opportunity)         api_body_file POST "${crm_base}/account/opportunity/page" "$body_file" ;;
    order)               api_body_file POST "${crm_base}/account/order/page" "$body_file" ;;
    payment-plan)        api_body_file POST "${crm_base}/account/contract/payment-plan/page" "$body_file" ;;
    payment-record)      api_body_file POST "${crm_base}/account/contract/payment-record/page" "$body_file" ;;
    invoice)             api_body_file POST "${crm_base}/account/invoice/page" "$body_file" ;;
    *) rm -f "$body_file"; die "unsupported account sub resource: ${sub}" ;;
  esac
}

# 合同维度取数器：acct-sub 的镜像。把 contractId 藏进内部（回款/回款计划走 /contract/{sub}/page
# 顶层 contractId），调用方只说 contract-sub <子资源> <合同ID>，不用手搓 body、不碰 contractId 位置坑。
crm_contract_sub() {
  local sub="${1:-}" contract_id="${2:-}" payload="${3:-}"
  [[ -n "${sub}" && -n "${contract_id}" ]] || die "contract-sub requires sub resource and contract ID"
  if [[ "$payload" == "-" || "$payload" == "@-" ]]; then
    payload=$(cat)
  fi
  case "${sub}" in
    invoice-stat)          api GET "${crm_base}/contract/invoice/statistic/${contract_id}"; return ;;
    # 发票/订单按合同的 /page 不吃 contractId 过滤（会返回全表），只能走统计端点。
    invoice|order)         die "合同名下的发票/订单查不了明细列表（/page 不按 contractId 过滤），只能取统计：cordys.sh crm contract-sub invoice-stat <合同ID>。客户名下明细走 cordys.sh crm acct-sub ${sub} <客户ID>。" ;;
  esac
  local body_file
  local schema_module="contract/${sub}"
  body_file=$(parent_payload contractId "$contract_id" "$schema_module" "$payload")
  case "${sub}" in
    payment-record)        api_body_file POST "${crm_base}/contract/payment-record/page" "$body_file" ;;
    payment-plan)          api_body_file POST "${crm_base}/contract/payment-plan/page" "$body_file" ;;
    *) rm -f "$body_file"; die "unsupported contract sub resource: ${sub}. supported: payment-record, payment-plan, invoice-stat" ;;
  esac
}

raw_api() {
  local method="${1:-}" path="${2:-}"
  shift 2
  [[ $# -le 1 ]] || die "raw 只接受 METHOD、PATH 和一个可选 JSON body"
  local raw_body="${1:-}"
  if [[ -n "$raw_body" && "$raw_body" != \{* && "$raw_body" != \[* ]]; then
    die "raw body 必须是 JSON 对象或数组，不接受 curl 参数"
  fi
  local raw_args=()
  local guarded_path="$path"

  if [[ "$guarded_path" == http* ]]; then
    guarded_path="/${guarded_path#*://*/}"
  fi
  guarded_path="${guarded_path%%\?*}"
  guarded_path="${guarded_path%%\#*}"
  case "$guarded_path" in
    /lead/transform|/lead/transition/account) legacy_transform_disabled ;;
    /pool/lead/page|/pool/account/page)
      local pool_module="${guarded_path#/pool/}"
      pool_module="${pool_module%/page}"
      die "raw 池分页已禁用：请改用 cordys.sh crm page pool/${pool_module}，由查询契约在联网前强制校验 payload 顶层 poolId。先执行 cordys.sh raw GET /pool/${pool_module}/options 获取 id。"
      ;;
  esac

  if [[ "$path" == *"/follow/"* || "$path" == *"/follow/page"* ]]; then
    local follow_path="$path"
    if [[ "$follow_path" == http* ]]; then
      follow_path="/${follow_path#*://*/}"
    fi
    [[ "$follow_path" =~ ^/follow/(plan|record)/page([?#].*)?$ ]] ||
      die "invalid follow path: expected /follow/<plan|record>/page"
    [[ "${method^^}" == "POST" ]] || die "跟进列表接口只支持 POST"
  fi

  if [[ -n "$raw_body" ]]; then
    "${PYTHON_CMD[@]}" -c 'import json,sys; json.loads(sys.argv[1])' "$raw_body" >/dev/null 2>&1 ||
      die "raw body 不是合法 JSON"
    raw_args=(--data-binary "$raw_body")
  fi

  if [[ "$path" == http* ]]; then
    if ! validate_url "$path"; then
      echo "❌ 拒绝请求：目标域名与配置的Cordys CRM域名不匹配" >&2
      echo "   配置的域名: $CORDYS_CRM_DOMAIN" >&2
      if [[ "${CORDYS_ALLOW_UNTRUSTED:-0}" != "1" ]]; then
        exit 1
      else
        warn "已启用不受信任域名模式，继续发送请求..."
      fi
    fi
    api "$method" "$path" "${raw_args[@]}"
  else
    api "$method" "${CORDYS_CRM_DOMAIN}${path}" "${raw_args[@]}"
  fi
}

# ── CLI 分发 ──────────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
cordys — CORDYS CRM CLI 工具（X-Access-Key 模式）

使用方法:
  cordys <命令> [参数...]

CRM 数据操作:
  crm view <模块>                          列出视图定义（不返回业务数据，仅 viewId 列表；查记录用 crm page）
  crm get <模块> <ID>                     获取单条记录详情
  crm search <模块> [关键词|JSON]          全局搜索记录
  crm page <模块> [关键词|JSON]            列表分页记录（只返回一页）
  crm page-summary <模块> <统计JSON> [查询JSON|-]  page 全量分页并在本地聚合，仅返回摘要
  crm follow <plan|record> [关键词|JSON|-] 查询统一跟进计划/记录列表（plan 默认 status=ALL）
  crm follow-get <plan|record> <模块> <ID> 获取跟进计划/记录详情（更新确认前使用）
  crm product [关键词|JSON]               查询产品列表
  crm dist <模块> <枚举字段> [JSON|-] [值列表]  枚举字段分布（脚本内逐桶；条件 JSON 可直接内联）
  crm contact <模块> <ID>                 获取联系人列表

统计与 L2C:
  crm stat <模块> [JSON]                   模块金额统计（contract/opportunity/order/contract/payment-record）
  crm stat-home <类型> [JSON]              首页统计（lead/opportunity/opportunity/success/opportunity/underway/dept-tree）
  crm glocount <关键词>                    全局搜索各模块命中计数
  crm acct-sub <子资源> <客户ID> [JSON]     客户子资源/统计（contract/opportunity/order/payment-plan/payment-record/invoice）
  crm contract-sub <子资源> <合同ID> [JSON] 合同子资源（payment-record/payment-plan 明细、invoice-stat 统计）

写入操作（创建/更新）:
  crm form <模块>                         获取可写模块表单定义
  crm create <模块> <JSON|->              创建记录（- 或 @- 读 UTF-8 stdin；子表模块自动附加当前表单配置）
  订单创建外层只传 contractId 和可选公共默认字段；CLI 按具体产品/服务+收入类型自动分组，同组多行合并、名称模板不变、逐单计算公式并分摊调整金额，全部成功后回写合同拆单标记；见 sop/order-create-flow.md
  crm update <模块> <JSON|->              更新记录（JSON 须包含 id；- 或 @- 从 UTF-8 stdin 读取）
  crm batch-update <模块> <JSON>          按字段批量更新（lead/account/opportunity/contact/contract/order）
  线索转化请使用 cordys_ext.sh transform（多步补全联系人、客户和商机字段）

用户与组织:
  crm whoami                              获取当前用户信息
  crm verify                              验证 API 密钥
  crm org [tree]                          获取完整组织架构树
  crm org ids [部门名称或ID]               展开部门及所有子部门ID（不传部门=全部可见部门）
  crm org outline [部门名称或ID]           输出 id/name/parentId/path/depth 层级（不传部门=全部可见部门）
  crm members [JSON] [--name 姓名] [--active] [--compact] [--exact-departments]  获取成员；部门默认递归，exact 仅直属范围

审批操作:
  crm approval todo <类型> [JSON]          审批代办列表
  crm approval action <操作> <JSON>        审批操作（同意/驳回/退回/加签/撤回）
  crm approval resource <操作> [参数]       审批资源（提审/撤销/详情）
  crm approval flow <操作> [参数]          审批流管理

模块列表:
  lead（线索）, pool/lead（线索池/线索公海）, account（客户）, pool/account（客户公海）,
  opportunity（商机）,
  contact（联系人）, contract（合同）,
  contract/payment-plan（回款计划）, invoice（发票）,
  contract/business-title（工商抬头）, contract/payment-record（回款记录）,
  opportunity/quotation（报价单）

审批 todo 类型: pending（待审）, processed（已处理）, initiated（我发起的）, cc（抄送我）, count（统计）
审批 action 操作: approve（同意）, reject（驳回）, back（退回）, sign（加签）, revoke（撤回）, batch-approve（批量同意）, batch-reject（批量驳回）
审批 resource 操作: push（提审）, revoke（撤销）, simple-detail（列表详情）, detail（记录详情）
审批 flow 操作: list（列表）, get（详情）, add（新建）, update（更新）, enable（启用）, disable（禁用）, by-form（按表单类型）, setting（状态权限）, webhook-test（测试webhook）

写入操作支持的模块:
  lead（线索）, account（客户）, opportunity（商机）, contact（联系人别名）/account/contact（真实路径）,
  contract（合同）, contract/payment-plan（回款计划）, contract/payment-record（回款记录）,
  invoice（发票）, contract/business-title（工商抬头）, opportunity/quotation（报价单）, order（订单）
批量编辑仅支持: lead, account, opportunity, contact（或 account/contact）, contract, order

查询示例:
  cordys raw GET /pool/lead/options             查询线索池/线索公海列表
  cordys raw GET /pool/account/options          查询客户公海列表
  cordys crm page pool/lead '{"poolId":"<线索池ID>","current":1,"pageSize":5,"sort":{"createTime":"desc"}}'
  cordys crm page pool/account '{"poolId":"<客户公海ID>","current":1,"pageSize":5,"sort":{"createTime":"desc"}}'
  注：具体池 page/page-summary 的 poolId 必须是 payload 顶层非空字符串；跨池 search 不传 poolId，但必须传 keyword
  cordys crm approval todo pending '{"current":1,"pageSize":30}'
  cordys crm approval todo pending '{"resourceType":"CONTRACT"}'
  cordys crm approval todo pending '{"combineSearch":{"conditions":[{"value":1777564800000,"operator":"GT","name":"createTime","type":"DATE_TIME"}]}}'
  cordys crm approval todo count
  cordys crm approval action approve '{"resourceId":"xxx","remark":"同意"}'
  cordys crm approval action reject '{"resourceId":"xxx","remark":"驳回原因"}'
  cordys crm approval resource push '{"resourceId":"xxx"}'
  cordys crm approval flow list '{"current":1,"pageSize":30}'
  cordys crm stat contract '{"viewId":"ALL","combineSearch":{"conditions":[]}}'
  cordys crm stat-home lead '{"searchType":"SELF","timeField":"CREATE_TIME","userField":"OWNER","priorPeriodEnable":true}'
  cordys crm glocount 华星科技
  cordys crm acct-sub payment-record-stat ACCOUNT_ID
  cordys crm contract-sub payment-record CONTRACT_ID
  cordys crm contract-sub invoice-stat CONTRACT_ID
  cordys crm date-ms "2026-07-01 00:00"       按 UTC+8 生成单个毫秒时间戳
  cordys crm date-range 2026-07-01 2026-07-31 生成 BETWEEN 闭区间（纯本地）
  cordys crm org outline 东区                  获取可按 parentId 连接的部/组/团队层级
  cordys crm members '{"departmentIds":["销售一部ID","销售二部ID"]}' --active --compact

写入示例:
  cordys crm form lead                        获取线索表单定义
  cordys crm form account/contact             获取联系人表单定义
  cordys crm create lead '{"name":"张三","phone":"13800138000","products":["p1"]}'
  cordys crm create account '{"name":"华星科技"}'
  cordys crm create opportunity '{"name":"华星采购项目","customerId":"xxx","contactId":"yyy","amount":120000,"products":["p1"]}'
  cordys crm create account/contact '{"customerId":"xxx","name":"张三","phone":"13800138000"}'
  cordys crm update contact '{"id":"xxx","moduleFields":[{"fieldId":"1751888184000051","fieldValue":"采购总监"}]}'
  cordys crm update lead '{"id":"xxx","name":"张三（已联系）"}'
  cordys crm batch-update lead '{"ids":["id1","id2"],"fieldId":"635449004900383","fieldValue":"admin"}'

原始 API:
  raw <方法> <路径> [JSON body]
  cordys raw GET /approval-todo/pending/count

环境变量:
  CORDYS_ACCESS_KEY  CORDYS_SECRET_KEY  CORDYS_CRM_DOMAIN
  CORDYS_PYTHON（可选；Windows 建议填真实 python.exe，绕过 WindowsApps 启动器）
EOF
}

cmd="${1:-}"
shift || true

case "$cmd" in
  crm)
    sub="${1:-}"; shift || die "crm 需要子命令"
    case "$sub" in
      view)    crm_view "$@" ;;
      get)     crm_get "$@" ;;
      search)  crm_search "$@" ;;
      page)    crm_page "$@" ;;
      page-summary) crm_page_summary "$@" ;;
      whoami)  crm_whoami ;;
      verify)  crm_verify ;;
      org)     crm_org "$@" ;;
      product) crm_product "$@" ;;
      dist) crm_dist "$@" ;;
      date-ms|date-range) crm_date_boundary "$sub" "$@" ;;
      stat) crm_stat "$@" ;;
      stat-home) crm_stat_home "$@" ;;
      glocount) crm_glocount "$@" ;;
      acct-sub) crm_acct_sub "$@" ;;
      contract-sub) crm_contract_sub "$@" ;;
      members) crm_members "$@" ;;
      contact) crm_contact "$@" ;;
      form)       crm_form "$@" ;;
      add|create)        crm_add "$@" ;;
      update)     crm_update "$@" ;;
      batch-update) crm_batch_update "$@" ;;
      transition|transform) legacy_transform_disabled ;;
      follow)
        kind="${1:-}"; shift || die "follow 需要 plan 或 record"
        case "${kind}" in
          plan|record) crm_follow_page "${kind}" "$@" ;;
          *) die "follow 只支持 plan 或 record" ;;
        esac
        ;;
      follow-get)
        crm_follow_get "$@"
        ;;
      approval)
        sub2="${1:-}"; shift || die "approval 需要子命令"
        case "${sub2}" in
          todo)     crm_approval_todo "$@" ;;
          action)   crm_approval_action "$@" ;;
          resource) crm_approval_resource "$@" ;;
          flow)     crm_approval_flow "$@" ;;
          *) die "未知的 approval 子命令: ${sub2}。支持: todo, action, resource, flow" ;;
        esac
        ;;
      # 容错：crm raw 等价于顶级 raw。raw 实际都打 CRM 端点，绝大多数命令又都在 crm 下，
      # AI 易把 raw 当成 crm 子命令顺手加前缀（已踩坑：crm raw 报错后转去 curl 绕过脚本）。
      raw)
        rmethod="${1:-}"; shift || die "raw 需要 HTTP 方法"
        rpath="${1:-}"; shift || die "raw 需要路径"
        raw_api "$rmethod" "$rpath" "$@" ;;
      *) die "未知的 crm 子命令: $sub" ;;
    esac
    ;;
  raw)
    method="${1:-}"; shift || die "raw 需要 HTTP 方法"
    path="${1:-}"; shift || die "raw 需要路径"
    raw_api "$method" "$path" "$@"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    die "未知命令: $cmd（尝试 cordys help）"
    ;;
esac
