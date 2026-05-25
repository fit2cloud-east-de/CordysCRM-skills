#!/usr/bin/env bash
# Cordys CRM 扩展 CLI（Shell 版）
# 封装官方 CLI 不支持的写入类操作
# 兼容 macOS / Linux / Windows (Git Bash / WSL)

set -euo pipefail
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

die() { echo "错误: $*" >&2; exit 1; }

check_keys() {
  [[ -n "${CORDYS_ACCESS_KEY:-}" ]] || die "未设置 CORDYS_ACCESS_KEY"
  [[ -n "${CORDYS_SECRET_KEY:-}" ]] || die "未设置 CORDYS_SECRET_KEY"
}

api_get() {
  check_keys
  curl -s -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
       -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
       -H "Content-Type: application/json;charset=UTF-8" \
       "${CORDYS_CRM_DOMAIN}${1}"
}

api_post() {
  check_keys
  curl -s -X POST \
       -H "X-Access-Key: ${CORDYS_ACCESS_KEY}" \
       -H "X-Secret-Key: ${CORDYS_SECRET_KEY}" \
       -H "Content-Type: application/json;charset=UTF-8" \
       -d "$2" \
       "${CORDYS_CRM_DOMAIN}${1}"
}

# ── 全局查重 ─────────────────────────────────────────────────────────

cmd_check() {
  local keyword="${1:?用法: cordys-ext check <关键词或JSON>}"

  if command -v python3 &>/dev/null; then
    python3 "${SCRIPT_DIR}/cordys_ext.py" check "$keyword"
  else
    die "查重功能需要 Python 环境，请安装 python3"
  fi
}

# ── 表单配置 ─────────────────────────────────────────────────────────

cmd_form() {
  local form_key="${1:?用法: cordys-ext form <formKey>}"

  if command -v python3 &>/dev/null; then
    python3 "${SCRIPT_DIR}/cordys_ext.py" form "$form_key"
  else
    die "表单配置功能需要 Python 环境，请安装 python3"
  fi
}

# ── 创建（统一委托 Python）─────────────────────────────────────────────

# ── 主入口 ────────────────────────────────────────────────────────────

usage() {
  cat <<'EOF'
cordys-ext — Cordys CRM 扩展 CLI

用法:
  cordys-ext form <module>                     获取表单配置（含必填标记）
  cordys-ext check <keyword>                   全局查重（搜索所有模块）
  cordys-ext create lead <JSON>                创建线索
  cordys-ext create account <JSON>             创建客户（待实现）
  cordys-ext create opportunity <JSON>         创建商机（待实现）
  cordys-ext create contact <JSON>             创建联系人（待实现）
  cordys-ext help                              显示帮助

示例:
  cordys-ext form clue
  cordys-ext check 13800138000
  cordys-ext create lead '{"name":"千里眼科技","姓名":"李老师","手机":"13777788888","线索来源":"线上","线上来源详情":"400电话","区域":"东区","行业":"高科技和互联网","是否已拜访":"否"}'

EOF
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  check)
    cmd_check "$@"
    ;;
  form)
    cmd_form "$@"
    ;;
  create)
    module="${1:-}"; shift || die "create 需要指定模块"
    case "$module" in
      lead|account|opportunity|contact)
        if command -v python3 &>/dev/null; then
          python3 "${SCRIPT_DIR}/cordys_ext.py" create "$module" "$@"
        else
          die "创建操作需要 Python 环境（用于字段映射），请安装 python3"
        fi
        ;;
      *) die "不支持的模块: ${module}" ;;
    esac
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    die "未知命令: $cmd（尝试 cordys-ext help）"
    ;;
esac
