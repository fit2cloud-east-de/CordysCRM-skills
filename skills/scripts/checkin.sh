#!/usr/bin/env bash
# 打卡系统 CLI（Shell 版）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${PROJECT_DIR}/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

CHECKIN_API_URL="${CHECKIN_API_URL:-}"

die() { echo "错误: $*" >&2; exit 1; }

check_base_url() {
  [[ -n "$CHECKIN_API_URL" ]] || die "未设置 CHECKIN_API_URL"
}

api_post() {
  local path="$1" body="$2"
  check_base_url
  printf '%s' "$body" | curl -s -X POST "${CHECKIN_API_URL%/}${path}" \
    -H "Content-Type: application/json; charset=utf-8" \
    -d @-
}

usage() {
  cat <<'EOF'
用法:
  checkin.sh create-checkin '<JSON>'
  checkin.sh submit-checkin '<JSON>'

依赖环境变量:
  CHECKIN_API_URL
EOF
}

cmd="${1:-}"
case "$cmd" in
  create-checkin)
    shift || true
    api_post "/api/wechat/create-checkin" "${1:-}"
    ;;
  submit-checkin)
    shift || true
    api_post "/api/wechat/submit-checkin" "${1:-}"
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    die "未知命令: $cmd"
    ;;
esac
