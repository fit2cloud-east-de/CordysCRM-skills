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
