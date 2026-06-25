#!/usr/bin/env bash
# CORDYS CRM CLI 工具
# 使用 X-Access-Key / X-Secret-Key 进行鉴权
set -eo nounset
set -o pipefail 2>/dev/null || true  # Bash 3.2 (macOS default) doesn't support pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${SKILL_DIR}/.env"

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
  local body_file
  if [[ "${payload}" == \{* ]]; then
    body_file=$(merge_payload "${payload}")
  else
    body_file=$(page_payload "${payload}")
  fi
  api POST "${crm_base}/${module}/follow/${kind}/page" --data-binary "@${body_file}"
  rm -f "$body_file"
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
    add)          local bf; bf=$(json_body_file "${1:-}"); api POST "${crm_base}/approval-flow/add" --data-binary "@${bf}"; rm -f "$bf" ;;
    update)       local bf; bf=$(json_body_file "${1:-}"); api POST "${crm_base}/approval-flow/update" --data-binary "@${bf}"; rm -f "$bf" ;;
    delete)       api GET "${crm_base}/approval-flow/delete/$1" ;;
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
crm_aggregate() {
  local module="$1" field="$2" op="${3:-sum}" payload="${4:-}"
  [[ -n "$module" && -n "$field" ]] || die "aggregate 用法: cordys.sh crm aggregate <module> <field> <op> [payload|-]"
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
  CORDYS_AGG_PAYLOAD="$payload_content" \
  CORDYS_AGG_HAS_PAYLOAD="$has_payload" \
  "${PYTHON_CMD[@]}" <<'PY'
import json, sys, os, urllib.request, urllib.error

domain = os.environ['CORDYS_AGG_DOMAIN']
access_key = os.environ['CORDYS_AGG_KEY']
secret_key = os.environ['CORDYS_AGG_SECRET']
module = os.environ['CORDYS_AGG_MODULE']
field = os.environ['CORDYS_AGG_FIELD']
op = os.environ['CORDYS_AGG_OP']
payload_raw = os.environ.get('CORDYS_AGG_PAYLOAD', '')
has_payload = os.environ.get('CORDYS_AGG_HAS_PAYLOAD', '0') == '1'

def api_post(path, body):
    url = f"{domain}{path}"
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'X-Access-Key': access_key,
        'X-Secret-Key': secret_key,
        'Content-Type': 'application/json; charset=utf-8'
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode('utf-8'))

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

payload = {}
raw = (payload_raw or '').strip()
if has_payload:
    # 传了 payload 却解析不出来：必须 die，绝不静默用空 conditions 查全租户（会返回貌似合理的全库求和）。
    if not raw:
        print(json.dumps({"error": "aggregate 收到空 payload（has_payload=1 但内容为空），已中止以避免误查全库"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"aggregate payload 不是合法 JSON: {e}", "raw_head": raw[:120]}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
if 'combineSearch' not in payload:
    payload['combineSearch'] = {'searchMode': 'AND', 'conditions': []}

all_records = []
current = 1
while True:
    payload['current'] = current
    payload['pageSize'] = 200
    resp = api_post(f'/{module}/page', payload)
    if resp.get('code') != 100200:
        print(json.dumps(resp, ensure_ascii=False))
        sys.exit(1)
    data = resp.get('data', {})
    records = data.get('list', [])
    total = data.get('total', 0)
    all_records.extend(records)
    if current * 200 >= total:
        break
    current += 1

values = []
for r in all_records:
    v = extract_field(r, field)
    if v is not None:
        try:
            values.append(float(v))
        except (ValueError, TypeError):
            pass

if op == 'sum':
    result = sum(values)
elif op == 'avg':
    result = sum(values) / len(values) if values else 0
elif op == 'count':
    result = len(all_records)
elif op == 'max':
    result = max(values) if values else 0
elif op == 'min':
    result = min(values) if values else 0
else:
    result = sum(values)

print(json.dumps({
    "op": op,
    "field": field,
    "value": result,
    "count": len(all_records)
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
  crm page <模块> [关键词|JSON]            列表分页记录
  crm follow <plan|record> <模块> [JSON]   查询跟进计划/记录
  crm product [关键词|JSON]               查询产品列表
  crm aggregate <模块> <字段> <op> [JSON]  聚合计算（sum/avg/count/max/min）
  crm contact <模块> <ID>                 获取联系人列表

统计与 L2C:
  crm stat <模块> [JSON]                   模块金额统计（contract/opportunity/order/contract/payment-record）
  crm stat-home <类型> [JSON]              首页统计（lead/opportunity/opportunity/success/opportunity/underway/dept-tree）
  crm glocount <关键词>                    全局搜索各模块命中计数
  crm acct-sub <子资源> <客户ID> [JSON]     客户子资源/统计（contract/opportunity/order/payment-plan/payment-record/invoice）
  crm contract-sub <子资源> <合同ID>        合同子资源统计（invoice-stat）

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
审批 flow 操作: list（列表）, get（详情）, add（新建）, update（更新）, delete（删除）, enable（启用）, disable（禁用）, by-form（按表单类型）, setting（状态权限）, webhook-test（测试webhook）

示例:
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
      whoami)  crm_whoami ;;
      verify)  crm_verify ;;
      org)     crm_org ;;
      product) crm_product "$@" ;;
      aggregate) crm_aggregate "$@" ;;
      stat) crm_stat "$@" ;;
      stat-home) crm_stat_home "$@" ;;
      glocount) crm_glocount "$@" ;;
      acct-sub) crm_acct_sub "$@" ;;
      contract-sub) crm_contract_sub "$@" ;;
      members) crm_members "$@" ;;
      contact) crm_contact "$@" ;;
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
