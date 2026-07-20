#!/usr/bin/env bash
# CORDYS CRM CLI 工具
# 使用 X-Access-Key / X-Secret-Key 进行鉴权
set -eo nounset
set -o pipefail 2>/dev/null || true

export PYTHONUTF8=1
if [[ -z "${PYTHONIOENCODING:-}" ]]; then
  export PYTHONIOENCODING=utf-8
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${SKILL_DIR}/.env"

# sop/ 公共库目录。
SOP_DIR="${SCRIPT_DIR}/sop"
QUERY_SCHEMA="${SKILL_DIR}/references/field-schema.json"
if command -v cygpath >/dev/null 2>&1; then
  SOP_DIR="$(cygpath -w "$SOP_DIR")"
  QUERY_SCHEMA="$(cygpath -w "$QUERY_SCHEMA")"
fi

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

# 查询依赖本实例的 field-schema/forms/自定义视图快照。每次进入依赖这些快照的
# 查询入口时先做一次 6 小时 TTL 检查；未过期只读取本地时间戳，过期才全量同步。
# 放在 CLI 内兜底，避免上层模型忘记显式执行 sync-if-needed 后继续使用旧快照。
query_sync_if_needed() {
  local sync_cli="${SCRIPT_DIR}/cordys_ext.sh"
  [[ -f "$sync_cli" ]] || die "查询前同步失败：未找到 ${sync_cli}"
  if ! bash "$sync_cli" sync-if-needed; then
    die "查询前表单/视图同步失败；已停止查询，避免使用过期或其他 CRM 实例的字段与视图快照。可单独执行 cordys_ext.sh sync 查看直接错误。"
  fi
}

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
# 第二参数传 "strip" 时剥离 owner（仅 create 用：交后端按 hasCurrentUser 设为当前用户，
# 避免误传 id 导致记录静默归错人）。update 不传，保留 owner——update 全量覆盖，剥了会清空负责人。
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

# 更新读回合并助手：把「现有记录(GET 返回)」与「调用方要改的字段」合并成 update body。
# /{module}/update 是全量覆盖——body 没带的可写字段和 moduleFields 会被清空。这里先保全
# 现有全部可写字段，再用调用方的新值覆盖，避免只传变更字段导致其余字段丢失（曾丢结束日期）。
# 只读/展示/审计/派生字段（*Name、createTime、optionMap、stage 等）不回发：它们要么被后端
# 忽略、要么会报错；实测 update 也不会清空这类派生字段（departmentId/stage 不发也保留）。
merge_update_payload() {
  local existing_json="$1" caller_json="$2"
  "${PYTHON_CMD[@]}" - "$existing_json" "$caller_json" <<'PY'
import json, sys, tempfile, os

existing_raw = sys.argv[1] if len(sys.argv) > 1 else ""
caller_raw = sys.argv[2] if len(sys.argv) > 2 else ""
try:
  ex_wrap = json.loads(existing_raw) if existing_raw.strip() else {}
except json.JSONDecodeError as e:
  sys.stderr.write(f"读回合并：现有记录解析失败: {e}\n"); sys.exit(1)
ex = ex_wrap.get("data") if isinstance(ex_wrap, dict) else None
if not isinstance(ex, dict) or not ex.get("id"):
  sys.stderr.write("读回合并：GET 未取到现有记录（id 不存在或已删除），中止以免清空字段\n"); sys.exit(1)
try:
  caller = json.loads(caller_raw) if caller_raw.strip() else {}
except json.JSONDecodeError as e:
  sys.stderr.write(f"读回合并：调用方 JSON 解析失败: {e}\n"); sys.exit(1)

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

tmpfile = os.path.join(tempfile.gettempdir(), f'cordys_update_{os.getpid()}.json')
with open(tmpfile, 'w', encoding='utf-8') as f:
  json.dump(body, f, ensure_ascii=False)
print(tmpfile)
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
  local resp http_code body
  resp=$(curl -sS --noproxy '*' -w $'\n%{http_code}' -X "$method" "$url" \
    -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
    -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
    -H "X-Request-Source: SKILL" \
    -H "Content-Type: application/json; charset=utf-8" \
    "$@")
  http_code="${resp##*$'\n'}"
  body="${resp%$'\n'*}"
  # body 非空就原样输出（不管 http_code）——上层按 code 字段判成败，
  # 这样 HTTP 500 但 body code=100200 的"假失败"能被正确识别为成功。
  if [[ -n "$body" ]]; then
    printf '%s\n' "$body"
  else
    # body 为空才是真失败（网络断/超时），给出结构化错误
    printf '{"code":0,"message":"HTTP %s，无响应体（可能网络中断或超时）","http_code":"%s"}\n' "$http_code" "$http_code"
  fi
}

# ── CRM 辅助函数 ──────────────────────────────────────────────────────
crm_base="${CORDYS_CRM_DOMAIN}"

crm_api_module() {
  case "${1:-}" in
    contact) printf '%s' 'account/contact' ;;
    *) printf '%s' "${1:-}" ;;
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
      die "组织/部门不走 'crm page ${module}'。查部门树用 cordys.sh crm org；展开部门及子部门ID用 cordys_ext.sh dept-children。详见 core/cli-spec.md §2.4/§11。" ;;
    follow|follows|followup|follow-up|followrecord|record|records)
      die "跟进记录不走 'crm page ${module}'（该端点不存在，会静默返回空）。跟进记录只能按父模块查：cordys.sh crm follow record <lead|account|opportunity> '{...}'（跟进记录无 departmentId 字段，按 owner=userId 或 followTime 过滤）。要看'团队本周跟进了哪些记录'，查业务模块本身：cordys.sh crm page lead/account/opportunity 加 followTime + departmentId 过滤。详见 profiles/sales-manager.md「团队本周跟进」配方。" ;;
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
  case "${module}" in
    member|members|user|users|staff|employee|personnel|org|organization|dept|department)
      die "查用户/组织不走 'crm search ${module}'（端点不存在，静默返回空）。查用户用 cordys.sh crm members（见 core/cli-spec.md §2.4）；查部门用 cordys.sh crm org。" ;;
    contract|invoice|order|contract/payment-record|contract/payment-plan|contract/business-title|opportunity/quotation)
      die "${module} 无全局搜索，按父维度取数：客户名下用 cordys.sh crm acct-sub <子资源> <客户ID>；合同名下用 cordys.sh crm contract-sub payment-record|payment-plan|invoice-stat <合同ID>；只有名称关键词用 cordys.sh crm page ${module} '{\"keyword\":\"关键词\"}'。见 core/cli-spec.md §14。" ;;
    follow|follows|followup|follow-up|followrecord|record|records)
      die "跟进记录不走 'crm search ${module}'（端点不存在，静默返回空）。跟进记录用 cordys.sh crm follow record <lead|account|opportunity> '{...}'；查'团队本周跟进的记录'查业务模块本身（crm page lead/account/opportunity 加 followTime+departmentId）。详见 profiles/sales-manager.md「团队本周跟进」配方。" ;;
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
  local kind="${1:-}" module="${2:-}" payload="${3:-}"
  [[ "${kind}" == "plan" || "${kind}" == "record" ]] || die "follow 子命令只支持 plan/record"
  [[ -n "${module}" ]] || die "follow ${kind} 需要指定模块（lead/account 等）"
  if [[ "$payload" == "-" || "$payload" == "@-" ]]; then
    payload=$(cat)
  fi
  query_sync_if_needed
  local body_file
  local schema_module="follow"
  [[ "${kind}" == "plan" ]] && schema_module="follow-plan"
  body_file=$(merge_payload "${payload}" "${schema_module}")
  api_body_file POST "${crm_base}/${module}/follow/${kind}/page" "$body_file"
}

# ── 写入操作（创建/更新/转化）─────────────────────────────────────────

# 获取模块表单定义
# 用法: crm_form <模块>            → GET /{module}/module/form
#       crm_form account/contact   → GET /account/contact/module/form
crm_form() {
  local module="${1:-}"
  [[ -n "${module}" ]] || die "form 需要指定模块"
  local api_module
  api_module=$(crm_api_module "$module")
  api GET "${crm_base}/${api_module}/module/form"
}

# 创建记录
# 用法: crm_add <模块> <JSON>
# 走 write_payload（UTF-8 落盘 + 默认剥 owner 交后端兜底）+ api_write（假失败检测）
crm_add() {
  local module="${1:-}" payload="${2:-}"
  [[ -n "${module}" ]] || die "add 需要指定模块（lead/account/opportunity/contact）"
  [[ -n "${payload}" && "${payload}" == \{* ]] || die "add 需要 JSON body"
  local body_file
  body_file=$(write_payload "$payload" strip) || die "构建请求体失败"
  local api_module
  api_module=$(crm_api_module "$module")
  api_write POST "${crm_base}/${api_module}/add" --data-binary "@${body_file}"
  cleanup_temp_file "$body_file"
}

# 更新记录
# 用法: crm_update <模块> <JSON>   → JSON 中必须包含 id 字段
# 读回合并：先 GET 现有记录，把调用方要改的字段覆盖上去再整体发。调用方只需传 id + 要改的
# 字段，其余（结束日期、owner、所有 moduleField）由脚本自动保全，不受 /update 全量覆盖影响。
crm_update() {
  local module="${1:-}" payload="${2:-}"
  [[ -n "${module}" ]] || die "update 需要指定模块（lead/account/opportunity/contact）"
  [[ -n "${payload}" && "${payload}" == \{* ]] || die "update 需要 JSON body（须包含 id）"
  local id
  id=$(printf '%s' "$payload" | "${PYTHON_CMD[@]}" -c 'import sys,json;
try: d=json.load(sys.stdin)
except Exception: d={}
print((d or {}).get("id","") if isinstance(d,dict) else "")')
  [[ -n "$id" ]] || die "update 的 JSON body 必须包含 id"
  local api_module
  api_module=$(crm_api_module "$module")
  local existing
  existing=$(api GET "${crm_base}/${api_module}/get/${id}")
  local body_file
  body_file=$(merge_update_payload "$existing" "$payload") || die "读回合并失败（GET 未取到记录或 JSON 解析失败）"
  api_write POST "${crm_base}/${api_module}/update" --data-binary "@${body_file}"
  cleanup_temp_file "$body_file"
}

# 批量更新（按字段批量修改多条记录的同一字段值）
# 用法: crm_batch_update <模块> '{"ids":["id1","id2"],"fieldId":"字段key","fieldValue":"新值"}'
crm_batch_update() {
  local module="${1:-}" payload="${2:-}"
  [[ -n "${module}" ]] || die "batch-update 需要指定模块"
  [[ -n "${payload}" && "${payload}" == \{* ]] || die "batch-update 需要 JSON body（须包含 ids, fieldId, fieldValue）"
  local body_file
  body_file=$(write_payload "$payload") || die "构建请求体失败"
  local api_module
  api_module=$(crm_api_module "$module")
  api_write POST "${crm_base}/${api_module}/batch/update" --data-binary "@${body_file}"
  cleanup_temp_file "$body_file"
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
  api GET "${crm_base}/department/tree"
}

crm_members() {
  local filter_name="" payload="" compact="0" payload_seen="0"
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

  # 所有成员查询统一为一个原生 Python 进程：已有 departmentIds 时只 POST 一次；
  # 未提供时才读 6 小时缓存或 GET 部门树。无临时 payload、curl、命令替换和自动重试。
  check_keys
  CORDYS_FILTER_NAME="$filter_name" \
  CORDYS_MEMBERS_PAYLOAD="$payload" \
  CORDYS_MEMBERS_COMPACT="$compact" \
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
    [[ "$follow_path" =~ ^/[^/]+/follow/(plan|record)/page([?#].*)?$ ]] ||
      die "invalid follow path: expected /<module>/follow/<plan|record>/page"
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
  crm follow <plan|record> <模块> [JSON]   查询跟进计划/记录
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
  crm form <模块>                         获取模块表单定义（lead/account/opportunity/account/contact）
  crm create <模块> <JSON>                创建记录（不传 owner，后端设为当前用户）
  crm update <模块> <JSON>                更新记录（JSON 须包含 id）
  crm batch-update <模块> <JSON>          按字段批量更新
  线索转化请使用 cordys_ext.sh transform（多步补全联系人、客户和商机字段）

用户与组织:
  crm whoami                              获取当前用户信息
  crm verify                              验证 API 密钥
  crm org                                 获取组织架构树
  crm members [JSON] [--name 姓名] [--compact]  获取成员；缺部门时自动补全可见部门范围

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

写入操作支持的模块: lead（线索）, account（客户）, opportunity（商机）, contact（联系人别名，自动映射 account/contact）

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
      org)     crm_org ;;
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
