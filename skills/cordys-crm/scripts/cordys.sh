#!/usr/bin/env bash
# CORDYS CRM CLI 工具
# 使用 X-Access-Key / X-Secret-Key 进行鉴权
set -eo nounset
set -o pipefail 2>/dev/null || true  # Bash 3.2 (macOS default) doesn't support pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${SKILL_DIR}/.env"

# sop/ 公共库目录，供 pageall / aggregate 经 sys.path 加载 paginate。
# Windows Git Bash 下 $SCRIPT_DIR 是 MSYS 路径（/c/...），原生 python.exe 不认，
# 用 cygpath 转成原生路径（C:\...）；Linux/WSL/macOS 无 cygpath 时保持原样。
SOP_DIR="${SCRIPT_DIR}/sop"
if command -v cygpath >/dev/null 2>&1; then
  SOP_DIR="$(cygpath -w "$SOP_DIR")"
fi

# ── 加载环境变量 ──────────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

CORDYS_CRM_DOMAIN="${CORDYS_CRM_DOMAIN:-https://www.cordys.cn}"

# ── 辅助函数 ───────────────────────────────────────────────────────────
die()  { echo "错误: $*" >&2; exit 1; }
info() { echo ":: $*" >&2; }
warn() { echo "⚠️  警告: $*" >&2; }

check_keys() {
  [[ -n "${CORDYS_ACCESS_KEY:-}" ]] || die "未设置 CORDYS_ACCESS_KEY"
  [[ -n "${CORDYS_SECRET_KEY:-}" ]] || die "未设置 CORDYS_SECRET_KEY"
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
  local user_json="${1:-}"
  "${PYTHON_CMD[@]}" - "$user_json" <<'PY'
import json, sys, tempfile, os

raw = sys.argv[1] if len(sys.argv) > 1 else ""
try:
  user = json.loads(raw) if raw and raw.strip() else {}
except json.JSONDecodeError:
  # 不是合法 JSON，当作 keyword 处理
  user = {"keyword": raw}

default = {
  "current": 1,
  "pageSize": 30,
  "sort": {},
  "combineSearch": {"searchMode": "AND", "conditions": []},
  "keyword": "",
  "viewId": "ALL",
  "filters": []
}

merged = {**default, **user}
# 确保 current 和 pageSize 有值（即使用户传了无效值）
if not isinstance(merged.get("current"), int) or merged["current"] < 1:
  merged["current"] = 1
if not isinstance(merged.get("pageSize"), int) or merged["pageSize"] < 1:
  merged["pageSize"] = 30

tmpfile = os.path.join(tempfile.gettempdir(), f'cordys_{os.getpid()}.json')
with open(tmpfile, 'w', encoding='utf-8') as f:
  json.dump(merged, f, ensure_ascii=False)
print(tmpfile)
PY
}

account_payload() {
  local account_id="$1" user_json="${2:-}"
  "${PYTHON_CMD[@]}" - "$account_id" "$user_json" <<'PY'
import json, sys, tempfile, os

account_id = sys.argv[1]
raw = sys.argv[2] if len(sys.argv) > 2 else ""
try:
  user = json.loads(raw) if raw and raw.strip() else {}
except json.JSONDecodeError:
  user = {"keyword": raw}

default = {
  "current": 1,
  "pageSize": 30,
  "sort": {},
  "combineSearch": {"searchMode": "AND", "conditions": []},
  "keyword": "",
  "viewId": "ALL",
  "filters": []
}

merged = {**default, **user}
merged["customerId"] = account_id
if not isinstance(merged.get("current"), int) or merged["current"] < 1:
  merged["current"] = 1
if not isinstance(merged.get("pageSize"), int) or merged["pageSize"] < 1:
  merged["pageSize"] = 30

tmpfile = os.path.join(tempfile.gettempdir(), f'cordys_{os.getpid()}.json')
with open(tmpfile, 'w', encoding='utf-8') as f:
  json.dump(merged, f, ensure_ascii=False)
print(tmpfile)
PY
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
  curl -s --noproxy '*' -X "$method" "$url" \
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

# ── CRM 辅助函数 ──────────────────────────────────────────────────────
crm_base="${CORDYS_CRM_DOMAIN}"

crm_view() {
  local module="$1" opts="${2:-}"
  api GET "${crm_base}/${module}/view/list" $opts
}

crm_get() {
  local module="$1" id="$2"
  api GET "${crm_base}/${module}/get/${id}"
}

crm_contact() {
  local module="$1" id="$2"
  [[ "$module" == "opportunity" || "$module" == "account" ]] || die "contact 仅支持 opportunity 和 account 模块"
  api GET "${crm_base}/${module}/contact/list/${id}"
}

crm_page() {
  local module="$1"
  shift
  # 防呆：member/user/org 不是 page 模块。这些端点不存在，后端会静默返回空，
  # 诱导上层反复猜端点。这里响亮报错并指向正确命令。
  case "${module}" in
    member|members|user|users|staff|employee|personnel)
      die "查用户不走 'crm page ${module}'（该端点不存在，会静默返回空）。请用：1) cordys_ext.sh dept-children 取全公司部门ID  2) cordys.sh crm members '{\"departmentIds\":[...],\"keyword\":\"姓名\",\"pageSize\":500}' 取 userId。详见 core/cli-spec.md §4.2。" ;;
    org|organization|dept|department)
      die "组织/部门不走 'crm page ${module}'。查部门树用 cordys.sh crm org；展开部门及子部门ID用 cordys_ext.sh dept-children。详见 core/cli-spec.md §4.2/§11。" ;;
  esac
  local first="${1:-}"
  # 支持 stdin：first 为 - 或 @- 时从标准输入读 JSON（与 aggregate 一致）。
  # 不加这条时，管道喂入的 JSON 会落到 else 分支被当成 keyword，静默返回空（已踩坑：@- → total=0）。
  if [[ "$first" == "-" || "$first" == "@-" ]]; then
    first=$(cat)
  fi
  local body_file
  if [[ "$first" == \{* ]]; then
    body_file=$(merge_payload "$first")
  else
    body_file=$(page_payload "${first:-}")
  fi
  local path="${module}/page"
  api POST "${CORDYS_CRM_DOMAIN}/${path}" --data-binary "@${body_file}"
  rm -f "$body_file"
}

# 拉全量：内部读 total 逐页翻页（pageSize 200），返回拼好的完整 list。
# crm page 只返回一页，做分组/排名/趋势时若 total>200 会被截断（已踩坑：只统计前 200 条且不报错）。
# 需要本地聚合全量数据时用本命令，不要自己翻页。求和/计数走 aggregate、枚举分布走 dist。
crm_pageall() {
  local module="${1:-}" payload="${2:-}"
  [[ -n "$module" ]] || die "pageall 用法: cordys.sh crm pageall <module> [payload|-]"
  case "${module}" in
    member|members|user|users|staff|employee|personnel|org|organization|dept|department)
      die "查用户/组织不走 'crm pageall ${module}'（端点不存在，静默返回空）。查用户用 cordys.sh crm members（见 core/cli-spec.md §4.2）；查部门用 cordys.sh crm org。" ;;
  esac
  check_keys

  # payload 直接经环境变量传给 Python（同 crm_aggregate，不走临时文件以规避 /tmp 路径转换坑）。
  local has_payload=0 payload_content=""
  if [[ "$payload" == "-" || "$payload" == "@-" ]]; then
    payload_content="$(cat)"
    has_payload=1
  elif [[ -n "$payload" ]]; then
    payload_content="$payload"
    has_payload=1
  fi

  CORDYS_PA_DOMAIN="$CORDYS_CRM_DOMAIN" \
  CORDYS_PA_KEY="$CORDYS_ACCESS_KEY" \
  CORDYS_PA_SECRET="$CORDYS_SECRET_KEY" \
  CORDYS_PA_MODULE="$module" \
  CORDYS_PA_PAYLOAD="$payload_content" \
  CORDYS_PA_HAS_PAYLOAD="$has_payload" \
  CORDYS_SOP_DIR="$SOP_DIR" \
  "${PYTHON_CMD[@]}" <<'PY'
import json, os, sys
sys.path.insert(0, os.environ['CORDYS_SOP_DIR'])
from paginate import fetch_all

records, total, _ = fetch_all('CORDYS_PA', 'pageall')
print(json.dumps({"code": 100200, "data": {"list": records, "total": total}}, ensure_ascii=True))
PY
}

crm_search() {
  local module="$1" json="${2:-}"
  case "${module}" in
    member|members|user|users|staff|employee|personnel|org|organization|dept|department)
      die "查用户/组织不走 'crm search ${module}'（端点不存在，静默返回空）。查用户用 cordys.sh crm members（见 core/cli-spec.md §4.2）；查部门用 cordys.sh crm org。" ;;
  esac
  # 支持 stdin：- 或 @- 时从标准输入读 JSON（与 page/aggregate 一致），否则管道 JSON 会被当 keyword 静默返回空。
  if [[ "$json" == "-" || "$json" == "@-" ]]; then
    json=$(cat)
  fi
  local body_file
  if [[ "$json" == \{* ]]; then
    body_file=$(merge_payload "$json")
  else
    body_file=$(page_payload "${json}")
  fi
  local path="global/search/${module}"
  api POST "${CORDYS_CRM_DOMAIN}/${path}" --data-binary "@${body_file}"
  rm -f "$body_file"
}

crm_follow_page() {
  local kind="$1" module="$2" payload="${3:-}"
  [[ "${kind}" == "plan" || "${kind}" == "record" ]] || die "follow 子命令只支持 plan/record"
  [[ -n "${module}" ]] || die "follow ${kind} 需要指定模块（lead/account 等）"
  local body
  body=$(merge_payload "${payload}")
  api POST "${crm_base}/follow/${kind}/page" --data-binary "$body"
}

# ── 写入操作（创建/更新/转化）─────────────────────────────────────────

# 获取模块表单定义
# 用法: crm_form <模块>            → GET /{module}/module/form
#       crm_form account/contact   → GET /account/contact/module/form
crm_form() {
  local module="$1"
  [[ -n "${module}" ]] || die "form 需要指定模块"
  api GET "${crm_base}/${module}/module/form"
}

# 创建记录
# 用法: crm_add <模块> <JSON>
crm_add() {
  local module="$1" payload="${2:-}"
  [[ -n "${module}" ]] || die "add 需要指定模块（lead/account/opportunity）"
  [[ -n "${payload}" && "${payload}" == \{* ]] || die "add 需要 JSON body"
  api POST "${crm_base}/${module}/add" --data-binary "$payload"
}

# 更新记录
# 用法: crm_update <模块> <JSON>   → JSON 中必须包含 id 字段
crm_update() {
  local module="$1" payload="${2:-}"
  [[ -n "${module}" ]] || die "update 需要指定模块（lead/account/opportunity）"
  [[ -n "${payload}" && "${payload}" == \{* ]] || die "update 需要 JSON body（须包含 id）"
  api POST "${crm_base}/${module}/update" --data-binary "$payload"
}

# 批量更新（按字段批量修改多条记录的同一字段值）
# 用法: crm_batch_update <模块> '{"ids":["id1","id2"],"fieldId":"字段key","fieldValue":"新值"}'
crm_batch_update() {
  local module="$1" payload="${2:-}"
  [[ -n "${module}" ]] || die "batch-update 需要指定模块"
  [[ -n "${payload}" && "${payload}" == \{* ]] || die "batch-update 需要 JSON body（须包含 ids, fieldId, fieldValue）"
  api POST "${crm_base}/${module}/batch/update" --data-binary "$payload"
}

# 线索转客户
# 用法: crm_lead_transition '{"clueId":"线索ID","name":"客户名称",...}'
crm_lead_transition() {
  local payload="${1:-}"
  [[ -n "${payload}" && "${payload}" == \{* ]] || die "transition 需要 JSON body（须包含 clueId, name）"
  api POST "${crm_base}/lead/transition/account" --data-binary "$payload"
}

# 线索转换（快速转为客户+可选商机）
# 用法: crm_lead_transform '{"clueId":"线索ID","oppCreated":true,"oppName":"商机名称"}'
crm_lead_transform() {
  local payload="${1:-}"
  [[ -n "${payload}" && "${payload}" == \{* ]] || die "transform 需要 JSON body（须包含 clueId）"
  api POST "${crm_base}/lead/transform" --data-binary "$payload"
}

# ── 审批相关 ──────────────────────────────────────────────────────────

crm_approval_todo() {
  local kind="$1" payload="${2:-}"
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
  local action="$1" payload="${2:-}"
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
  local action="$1"
  shift
  case "${action}" in
    push)          local bf; bf=$(json_body_file "${1:-}"); api POST "${crm_base}/approval-resource/push" --data-binary "@${bf}"; rm -f "$bf" ;;
    revoke)        local bf; bf=$(json_body_file "${1:-}"); api POST "${crm_base}/approval-resource/revoke" --data-binary "@${bf}"; rm -f "$bf" ;;
    simple-detail) api GET "${crm_base}/approval-resource/simple-detail/$1" ;;
    detail)        api GET "${crm_base}/approval-resource/detail/$1" ;;
    *) die "未知的审批资源操作: ${action}。支持: push, revoke, simple-detail, detail" ;;
  esac
}

crm_approval_flow() {
  local action="$1"
  shift
  case "${action}" in
    list)         local bf; bf=$(merge_payload "$1"); api POST "${crm_base}/approval-flow/page" --data-binary "@${bf}"; rm -f "$bf" ;;
    get)          api GET "${crm_base}/approval-flow/get/$1" ;;
    add)          api POST "${crm_base}/approval-flow/add" --data-binary "$1" ;;
    update)       api POST "${crm_base}/approval-flow/update" --data-binary "$1" ;;
    enable)       api GET "${crm_base}/approval-flow/enable/$1?enable=true" ;;
    disable)      api GET "${crm_base}/approval-flow/enable/$1?enable=false" ;;
    by-form)      api GET "${crm_base}/approval-flow/get-by-form-type/$1" ;;
    setting)      api GET "${crm_base}/approval-flow/status-permission/setting/$1" ;;
    webhook-test) local bf; bf=$(json_body_file "${1:-}"); api POST "${crm_base}/approval-flow/webhook/test" --data-binary "@${bf}"; rm -f "$bf" ;;
    *) die "未知的审批流操作: ${action}" ;;
  esac
}

# ── 产品 ──────────────────────────────────────────────────────────────
crm_product() {
  local keyword="${1:-}"
  local body_file
  if [[ "$keyword" == \{* ]]; then
    body_file=$(merge_payload "$keyword")
  else
    body_file=$(page_payload "${keyword}")
  fi
  api POST "${CORDYS_CRM_DOMAIN}/field/source/product" --data-binary "@${body_file}"
  rm -f "$body_file"
}

# ── 聚合计算 ──────────────────────────────────────────────────────
# 用法: cordys.sh crm aggregate <module> <field> <op> [payload|-] [--by <分组字段>]
#   不带 --by：返回单个标量（sum/avg/count/max/min）。
#   带 --by：按分组字段（如 ownerName/departmentName）分组，每组算 <op>，
#            返回按 op 值降序的桶 + 合计。替代「pageall 拉全量再手写脚本本地 group-by」，
#            避免 1.5MB JSON 被截断与 Windows 编码坑。分组键为枚举时优先用 dist（服务端逐桶）。
crm_aggregate() {
  local module="$1" field="$2" op="${3:-sum}"
  shift $(( $# >= 3 ? 3 : $# ))
  # 剩余参数里挑出可选的 --by <字段> 和 payload（payload 可在 --by 前或后）。
  local payload="" group_by=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --by) group_by="${2:-}"; shift 2 ;;
      *)    payload="$1"; shift ;;
    esac
  done
  [[ -n "$module" && -n "$field" ]] || die "aggregate 用法: cordys.sh crm aggregate <module> <field> <op> [payload|-] [--by <分组字段>]"
  check_keys

  # payload 直接经环境变量传给 Python（不走临时文件）。
  # 旧实现用 mktemp /tmp/...json 写文件、再让 Windows 原生 Python 用 os.path.exists 找回，
  # /tmp 是 MSYS 虚拟路径，经 env 传递时路径转换在不同环境不一致：找不到文件就静默退化成
  # 空 conditions → 查全租户求和，返回貌似合理的巨大数字（已踩坑：模型环境 count=25346/19.8亿）。
  # 改为直接传内容，并用 CORDYS_AGG_HAS_PAYLOAD 标记是否真传了 payload，解析失败时 die 而非静默查全库。
  local has_payload=0 payload_content=""
  if [[ "$payload" == "-" || "$payload" == "@-" ]]; then
    payload_content="$(cat)"
    has_payload=1
  elif [[ -n "$payload" ]]; then
    payload_content="$payload"
    has_payload=1
  fi

  CORDYS_AGG_DOMAIN="$CORDYS_CRM_DOMAIN" \
  CORDYS_AGG_KEY="$CORDYS_ACCESS_KEY" \
  CORDYS_AGG_SECRET="$CORDYS_SECRET_KEY" \
  CORDYS_AGG_MODULE="$module" \
  CORDYS_AGG_FIELD="$field" \
  CORDYS_AGG_OP="$op" \
  CORDYS_AGG_GROUP_BY="$group_by" \
  CORDYS_AGG_PAYLOAD="$payload_content" \
  CORDYS_AGG_HAS_PAYLOAD="$has_payload" \
  CORDYS_SOP_DIR="$SOP_DIR" \
  "${PYTHON_CMD[@]}" <<'PY'
import json, os, sys
sys.path.insert(0, os.environ['CORDYS_SOP_DIR'])
from paginate import fetch_all

field = os.environ['CORDYS_AGG_FIELD']
op = os.environ['CORDYS_AGG_OP']
group_by = os.environ.get('CORDYS_AGG_GROUP_BY', '').strip()

TOP_LEVEL_FIELDS = {'amount','ownerName','departmentName','stageName','customerName',
                    'createTime','updateTime','actualEndTime','expectedEndTime','name','id'}

def extract_field(record, field_name):
    if field_name in TOP_LEVEL_FIELDS and field_name in record:
        return record[field_name]
    if field_name in record and field_name not in TOP_LEVEL_FIELDS:
        return record[field_name]
    for mf in record.get('moduleFields', []):
        if mf.get('fieldId') == field_name or mf.get('fieldName') == field_name:
            return mf.get('fieldValue')
    return None

def compute(records):
    """对一组记录按 op 算标量；count 数记录条数，其余对 field 的数值求 sum/avg/max/min。"""
    vals = []
    for r in records:
        v = extract_field(r, field)
        if v is not None:
            try:
                vals.append(float(v))
            except (ValueError, TypeError):
                pass
    if op == 'count':
        return len(records)
    if op == 'avg':
        return sum(vals) / len(vals) if vals else 0
    if op == 'max':
        return max(vals) if vals else 0
    if op == 'min':
        return min(vals) if vals else 0
    return sum(vals)  # sum 及兜底

all_records, _, _ = fetch_all('CORDYS_AGG', 'aggregate')

if group_by:
    # 按 group_by 分组，每组算 op，按 op 值降序排列。
    groups = {}
    for r in all_records:
        key = extract_field(r, group_by)
        key = '（空）' if key in (None, '') else str(key)
        groups.setdefault(key, []).append(r)
    rows = [{"group": k,
             "value": compute(v),
             "count": len(v)} for k, v in groups.items()]
    rows.sort(key=lambda x: x["value"], reverse=True)
    print(json.dumps({
        "op": op,
        "field": field,
        "groupBy": group_by,
        "rows": rows,
        "total": {"value": compute(all_records), "count": len(all_records)}
    }, ensure_ascii=True))
else:
    print(json.dumps({
        "op": op,
        "field": field,
        "value": compute(all_records),
        "count": len(all_records)
    }, ensure_ascii=True))
PY
}

# ── 枚举字段分布 ──────────────────────────────────────────────────────
# 按枚举字段逐桶服务端聚合，脚本内部循环（模型不再手拼多段 JSON）。
# 用法: cordys.sh crm dist <module> <field> [baseJSON|-] [values]
#   field   枚举字段名（stage，或 fieldId 如 1751888184000030）
#   baseJSON 范围/时间/部门条件，传一次（省略=全量）；含中文可直接内联
#   values  逗号分隔值列表，仅当字段不在 optionMap（如 stage）时需要
crm_dist() {
  local module="$1" field="$2" payload="${3:-}" values="${4:-}"
  [[ -n "$module" && -n "$field" ]] || die "dist 用法: cordys.sh crm dist <module> <field> [baseJSON|-] [values]"
  check_keys

  # baseJSON 直接经环境变量传给 Python（不写临时文件，同 crm_aggregate）。
  # 旧实现写 tmpfile 再让原生 python.exe 用 os.path.exists 找回，路径转换在不同环境不一致，
  # 找不到就静默退化成空 conditions → 查全量。改为直传内容 + HAS_PAYLOAD 标记，解析失败 die。
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
  CORDYS_DIST_FIELD="$field" \
  CORDYS_DIST_VALUES="$values" \
  CORDYS_DIST_PAYLOAD="$payload_content" \
  CORDYS_DIST_HAS_PAYLOAD="$has_payload" \
  "${PYTHON_CMD[@]}" <<'PY'
import json, sys, os, copy, urllib.request, urllib.error

# Windows(cp936) 终端下 stdout 默认非 UTF-8，会把 API 返回的中文打成乱码（�½�）。
# 强制 UTF-8，修显示层乱码；reconfigure 为 3.7+，老版本静默跳过。
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding='utf-8')
    except Exception: pass

domain = os.environ['CORDYS_DIST_DOMAIN']
access_key = os.environ['CORDYS_DIST_KEY']
secret_key = os.environ['CORDYS_DIST_SECRET']
module = os.environ['CORDYS_DIST_MODULE']
field = os.environ['CORDYS_DIST_FIELD']
values_arg = os.environ.get('CORDYS_DIST_VALUES', '').strip()
payload_raw = os.environ.get('CORDYS_DIST_PAYLOAD', '')
has_payload = os.environ.get('CORDYS_DIST_HAS_PAYLOAD', '0') == '1'

# 绕过本地代理（同 crm_aggregate）。
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def api_post(path, body):
    url = f"{domain}{path}"
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'X-Access-Key': access_key,
        'X-Secret-Key': secret_key,
        'Content-Type': 'application/json; charset=utf-8'
    })
    try:
        with _opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode('utf-8'))

# 支持服务端金额统计的模块 → /statistic 端点
STAT_PATH = {
    'opportunity': '/opportunity/statistic',
    'contract': '/contract/statistic',
    'contract/payment-record': '/contract/payment-record/statistic',
    'order': '/order/statistic',
}

def fail(msg):
    print(json.dumps({'code': 40000, 'message': msg}, ensure_ascii=False))
    sys.exit(1)

# 读 base payload，宽容归一化 combineSearch 大小写
base = {}
raw = (payload_raw or '').strip()
if has_payload:
    # 传了 payload 却解析不出来：必须 fail，绝不静默用空 conditions 查全量。
    if not raw:
        fail('dist: 收到空 baseJSON（has_payload=1 但内容为空），已中止以避免误查全量')
    try:
        base = json.loads(raw)
    except json.JSONDecodeError as e:
        fail(f'dist: baseJSON 不是合法 JSON: {e}')
if not isinstance(base, dict):
    fail('dist: baseJSON 顶层必须是对象')
if 'combineSearch' not in base:
    for k in list(base.keys()):
        if isinstance(k, str) and k.lower() == 'combinesearch':
            base['combineSearch'] = base.pop(k)
            break
cs = base.get('combineSearch') or {'searchMode': 'AND', 'conditions': []}
cs.setdefault('searchMode', 'AND')
cs.setdefault('conditions', [])
base_conditions = cs['conditions']

# 纯 ASCII 诊断（到 stderr，不污染 stdout 的 JSON 结果）：暴露 baseJSON 是否真到达。
# 默认关闭，排查时 CORDYS_DIST_DEBUG=1 打开。raw_bytes=0/conds=0 表示条件没送达 → 全量。
if os.environ.get('CORDYS_DIST_DEBUG', '0') == '1':
    _names = [str(c.get('name')) + ':' + str(c.get('operator')) for c in base_conditions if isinstance(c, dict)]
    sys.stderr.write('[dist] raw_bytes=%d conds=%d [%s]\n' % (
        len(raw), len(base_conditions), ', '.join(_names)))

# 一次 page 调用拿 optionMap + total（带 base 条件）
probe = copy.deepcopy(base)
probe['combineSearch'] = {'searchMode': cs['searchMode'], 'conditions': base_conditions}
probe['current'] = 1
probe['pageSize'] = 1
probe.setdefault('viewId', 'ALL')
presp = api_post(f'/{module}/page', probe)
if presp.get('code') != 100200:
    print(json.dumps(presp, ensure_ascii=False)); sys.exit(1)
option_map = (presp.get('data') or {}).get('optionMap', {}) or {}

# 定枚举值集合：显式 values 优先 → optionMap → 报错
# buckets: list of (value, label)
buckets = []
if values_arg:
    for v in values_arg.split(','):
        v = v.strip()
        if v:
            buckets.append((v, None))  # label 稍后从样本记录补
elif field in option_map:
    for o in option_map[field]:
        buckets.append((o.get('id'), o.get('name')))
else:
    fail(f"dist: 字段 {field} 不在 optionMap（仅含 {', '.join(option_map.keys())}）。"
         f"系统码值字段（如 stage）请用第 4 参数传值列表，如 CREATE,SUCCESS,FAIL")

# 该字段在记录里的展示名键（用于给显式值补中文标签，如 stage→stageName）
name_key = field + 'Name'

stat_path = STAT_PATH.get(module)
results = []
tot_count = 0
tot_amount = 0.0
for value, label in buckets:
    conds = list(base_conditions) + [
        {'operator': 'EQUALS', 'name': field, 'value': value, 'type': 'SELECT'}
    ]
    body = copy.deepcopy(base)
    body['combineSearch'] = {'searchMode': cs['searchMode'], 'conditions': conds}
    body.setdefault('viewId', 'ALL')

    # count + 样本（用于补 label）
    pbody = copy.deepcopy(body)
    pbody['current'] = 1
    pbody['pageSize'] = 1
    cresp = api_post(f'/{module}/page', pbody)
    if cresp.get('code') != 100200:
        print(json.dumps(cresp, ensure_ascii=False)); sys.exit(1)
    cdata = cresp.get('data') or {}
    count = cdata.get('total', 0) or 0
    if label is None:
        lst = cdata.get('list') or []
        if lst and isinstance(lst[0], dict) and lst[0].get(name_key):
            label = lst[0][name_key]
        else:
            label = value

    # amount（服务端 /statistic，不拉明细）
    amount = None
    if stat_path:
        aresp = api_post(stat_path, body)
        if aresp.get('code') == 100200:
            amount = (aresp.get('data') or {}).get('amount', 0) or 0
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                amount = 0.0

    results.append({'value': value, 'name': label, 'count': count, 'amount': amount})
    tot_count += count
    if amount is not None:
        tot_amount += amount

print(json.dumps({
    'code': 100200,
    'field': field,
    'data': results,
    'total': {'count': tot_count, 'amount': tot_amount if stat_path else None},
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
  local body_file
  body_file=$(merge_payload "$1")
  api POST "${crm_base}/user/list" --data-binary "@${body_file}"
  rm -f "$body_file"
}

# ── 原始 API 调用 ─────────────────────────────────────────────────────
# Server-side statistics and L2C helper APIs.
crm_stat() {
  local module="$1" payload="${2:-}"
  local body_file
  if [[ "${payload}" == \{* ]]; then
    body_file=$(merge_payload "$payload")
  else
    body_file=$(page_payload "${payload}")
  fi
  case "${module}" in
    contract)                api POST "${crm_base}/contract/statistic" --data-binary "@${body_file}" ;;
    contract/payment-record) api POST "${crm_base}/contract/payment-record/statistic" --data-binary "@${body_file}" ;;
    opportunity)             api POST "${crm_base}/opportunity/statistic" --data-binary "@${body_file}" ;;
    order)                   api POST "${crm_base}/order/statistic" --data-binary "@${body_file}" ;;
    *) rm -f "$body_file"; die "unsupported stat module: ${module}. supported: contract, contract/payment-record, opportunity, order" ;;
  esac
  rm -f "$body_file"
}

crm_stat_home() {
  local kind="$1" payload="${2:-}"
  local body_file
  if [[ "${payload}" == \{* ]]; then
    body_file=$(json_body_file "$payload")
  else
    body_file=$(json_body_file '{"searchType":"SELF","timeField":"CREATE_TIME","userField":"OWNER","priorPeriodEnable":true}')
  fi
  case "${kind}" in
    lead)                 api POST "${crm_base}/home/statistic/lead" --data-binary "@${body_file}" ;;
    opportunity)          api POST "${crm_base}/home/statistic/opportunity" --data-binary "@${body_file}" ;;
    opportunity/success)  api POST "${crm_base}/home/statistic/opportunity/success" --data-binary "@${body_file}" ;;
    opportunity/underway) api POST "${crm_base}/home/statistic/opportunity/underway" --data-binary "@${body_file}" ;;
    dept-tree)            rm -f "$body_file"; api GET "${crm_base}/home/statistic/department/tree"; return ;;
    *) rm -f "$body_file"; die "unsupported home stat type: ${kind}. supported: lead, opportunity, opportunity/success, opportunity/underway, dept-tree" ;;
  esac
  rm -f "$body_file"
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
  local sub="$1" acct_id="$2" payload="${3:-}"
  [[ -n "${sub}" && -n "${acct_id}" ]] || die "acct-sub requires sub resource and account ID"
  case "${sub}" in
    contract-stat)       api GET "${crm_base}/account/contract/statistic/${acct_id}"; return ;;
    payment-plan-stat)   api GET "${crm_base}/account/contract/payment-plan/statistic/${acct_id}"; return ;;
    payment-record-stat) api GET "${crm_base}/account/contract/payment-record/statistic/${acct_id}"; return ;;
    invoice-stat)        api GET "${crm_base}/account/invoice/statistic/${acct_id}"; return ;;
  esac
  local body_file
  body_file=$(account_payload "$acct_id" "$payload")
  case "${sub}" in
    contract)            api POST "${crm_base}/account/contract/page" --data-binary "@${body_file}" ;;
    opportunity)         api POST "${crm_base}/account/opportunity/page" --data-binary "@${body_file}" ;;
    order)               api POST "${crm_base}/account/order/page" --data-binary "@${body_file}" ;;
    payment-plan)        api POST "${crm_base}/account/contract/payment-plan/page" --data-binary "@${body_file}" ;;
    payment-record)      api POST "${crm_base}/account/contract/payment-record/page" --data-binary "@${body_file}" ;;
    invoice)             api POST "${crm_base}/account/invoice/page" --data-binary "@${body_file}" ;;
    *) rm -f "$body_file"; die "unsupported account sub resource: ${sub}" ;;
  esac
  rm -f "$body_file"
}

crm_contract_sub() {
  local sub="$1" contract_id="$2"
  [[ -n "${sub}" && -n "${contract_id}" ]] || die "contract-sub requires sub resource and contract ID"
  case "${sub}" in
    invoice-stat) api GET "${crm_base}/contract/invoice/statistic/${contract_id}" ;;
    *) die "unsupported contract sub resource: ${sub}. supported: invoice-stat" ;;
  esac
}

raw_api() {
  local method="$1" path="$2"
  shift 2
  local raw_args=("$@")

  if [[ "$path" == *"/follow/"* || "$path" == *"/follow/page"* ]]; then
    local follow_path="$path"
    if [[ "$follow_path" == http* ]]; then
      follow_path="/${follow_path#*://*/}"
    fi
    [[ "$follow_path" =~ ^/[^/]+/follow/(plan|record)/page([?#].*)?$ ]] ||
      die "invalid follow path: expected /<module>/follow/<plan|record>/page"
  fi

  if [[ "${#raw_args[@]}" -eq 1 && "${raw_args[0]}" != -* ]]; then
    raw_args=(--data-binary "${raw_args[0]}")
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
  crm view <模块> [参数]                   列出视图定义（不返回业务数据，仅 viewId 列表；查记录用 crm page）
  crm get <模块> <ID>                     获取单条记录详情
  crm search <模块> [关键词|JSON]          全局搜索记录
  crm page <模块> [关键词|JSON]            列表分页记录（只返回一页）
  crm pageall <模块> [JSON|-]              拉全量（内部逐页翻页，做分组/排名/趋势用）
  crm follow <plan|record> <模块> [JSON]   查询跟进计划/记录
  crm product [关键词|JSON]               查询产品列表
  crm aggregate <模块> <字段> <op> [JSON] [--by 分组字段]  聚合(sum/avg/count/max/min)；带 --by 按字段分组排名
  crm dist <模块> <枚举字段> [JSON|-] [值列表]  枚举字段分布（脚本内逐桶；条件 JSON 可直接内联）
  crm contact <模块> <ID>                 获取联系人列表

统计与 L2C:
  crm stat <模块> [JSON]                   模块金额统计（contract/opportunity/order/contract/payment-record）
  crm stat-home <类型> [JSON]              首页统计（lead/opportunity/opportunity/success/opportunity/underway/dept-tree）
  crm glocount <关键词>                    全局搜索各模块命中计数
  crm acct-sub <子资源> <客户ID> [JSON]     客户子资源/统计（contract/opportunity/order/payment-plan/payment-record/invoice）
  crm contract-sub <子资源> <合同ID>        合同子资源统计（invoice-stat）

写入操作（创建/更新/转化）:
  crm form <模块>                         获取模块表单定义（lead/account/opportunity/account/contact）
  crm add <模块> <JSON>                   创建记录
  crm update <模块> <JSON>                更新记录（JSON 须包含 id）
  crm batch-update <模块> <JSON>          按字段批量更新
  crm transition <JSON>                   线索转客户
  crm transform <JSON>                    线索转换（转客户+可选商机）

用户与组织:
  crm whoami                              获取当前用户信息
  crm verify                              验证 API 密钥
  crm org                                 获取组织架构树
  crm members <JSON>                      获取部门成员列表

审批操作:
  crm approval todo <类型> [JSON]          审批代办列表
  crm approval action <操作> <JSON>        审批操作（同意/驳回/退回/加签/撤回）
  crm approval resource <操作> [参数]       审批资源（提审/撤销/详情）
  crm approval flow <操作> [参数]          审批流管理

模块列表:
  lead（线索）, opportunity（商机）, account（客户）,
  contact（联系人）, contract（合同）,
  contract/payment-plan（回款计划）, invoice（发票）,
  contract/business-title（工商抬头）, contract/payment-record（回款记录）,
  opportunity/quotation（报价单）

审批 todo 类型: pending（待审）, processed（已处理）, initiated（我发起的）, cc（抄送我）, count（统计）
审批 action 操作: approve（同意）, reject（驳回）, back（退回）, sign（加签）, revoke（撤回）, batch-approve（批量同意）, batch-reject（批量驳回）
审批 resource 操作: push（提审）, revoke（撤销）, simple-detail（列表详情）, detail（记录详情）
审批 flow 操作: list（列表）, get（详情）, add（新建）, update（更新）, enable（启用）, disable（禁用）, by-form（按表单类型）, setting（状态权限）, webhook-test（测试webhook）

写入操作支持的模块: lead（线索）, account（客户）, opportunity（商机）, account/contact（联系人）

查询示例:
  cordys crm approval todo pending '{"current":1,"pageSize":30}'
  cordys crm approval todo pending '{"resourceType":"CONTRACT"}'
  cordys crm approval todo pending '{"combineSearch":{"conditions":[{"value":"2026-05-01","operator":"GT","name":"createTime","type":"DATE_TIME"}]}}'
  cordys crm approval todo count
  cordys crm approval action approve '{"resourceId":"xxx","remark":"同意"}'
  cordys crm approval action reject '{"resourceId":"xxx","remark":"驳回原因"}'
  cordys crm approval resource push '{"resourceId":"xxx"}'
  cordys crm approval flow list '{"current":1,"pageSize":30}'
  cordys crm stat contract '{"viewId":"ALL","combineSearch":{"conditions":[]}}'
  cordys crm stat-home lead '{"searchType":"SELF","timeField":"CREATE_TIME","userField":"OWNER","priorPeriodEnable":true}'
  cordys crm glocount 华星科技
  cordys crm acct-sub payment-record-stat ACCOUNT_ID
  cordys crm contract-sub invoice-stat CONTRACT_ID

写入示例:
  cordys crm form lead                        获取线索表单定义
  cordys crm form account/contact             获取联系人表单定义
  cordys crm add lead '{"name":"张三","phone":"13800138000","products":["p1"]}'
  cordys crm add account '{"name":"华星科技","owner":"user123"}'
  cordys crm add opportunity '{"name":"华星采购项目","customerId":"xxx","contactId":"yyy","amount":120000,"owner":"user123","products":["p1"]}'
  cordys crm add account/contact '{"customerId":"xxx","name":"张三","phone":"13800138000"}'
  cordys crm update lead '{"id":"xxx","name":"张三（已联系）"}'
  cordys crm batch-update lead '{"ids":["id1","id2"],"fieldId":"635449004900383","fieldValue":"admin"}'
  cordys crm transition '{"clueId":"xxx","name":"华星科技"}'
  cordys crm transform '{"clueId":"xxx","oppCreated":true,"oppName":"华星采购项目"}'

原始 API:
  raw <方法> <路径> [curl参数...]
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
      pageall) crm_pageall "$@" ;;
      whoami)  crm_whoami ;;
      verify)  crm_verify ;;
      org)     crm_org ;;
      product) crm_product "$@" ;;
      aggregate) crm_aggregate "$@" ;;
      dist) crm_dist "$@" ;;
      stat) crm_stat "$@" ;;
      stat-home) crm_stat_home "$@" ;;
      glocount) crm_glocount "$@" ;;
      acct-sub) crm_acct_sub "$@" ;;
      contract-sub) crm_contract_sub "$@" ;;
      members) crm_members "$@" ;;
      contact) crm_contact "$@" ;;
      form)       crm_form "$@" ;;
      add)        crm_add "$@" ;;
      update)     crm_update "$@" ;;
      batch-update) crm_batch_update "$@" ;;
      transition) crm_lead_transition "$@" ;;
      transform)  crm_lead_transform "$@" ;;
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
