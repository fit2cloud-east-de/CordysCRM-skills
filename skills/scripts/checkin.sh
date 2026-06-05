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
OPENCLAW_WEBHOOK_URL="${OPENCLAW_WEBHOOK_URL:-}"

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

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

inject_webhook_url() {
  local body="$1" webhook

  [[ -n "$OPENCLAW_WEBHOOK_URL" ]] || {
    printf '%s' "$body"
    return
  }

  webhook="$(json_escape "$OPENCLAW_WEBHOOK_URL")"

  if [[ "$body" == *"<OPENCLAW_WEBHOOK_URL>"* ]]; then
    body="${body//<OPENCLAW_WEBHOOK_URL>/$webhook}"
    printf '%s' "$body"
    return
  fi

  if [[ "$body" == *'"webhookUrl"'* ]]; then
    printf '%s' "$body"
    return
  fi

  while [[ "$body" =~ [[:space:]]$ ]]; do
    body="${body%?}"
  done

  if [[ "$body" == \{*\} ]]; then
    local prefix="${body%?}"
    if [[ "$prefix" =~ \{[[:space:]]*$ ]]; then
      printf '%s"webhookUrl":"%s"}' "$prefix" "$webhook"
    else
      printf '%s,"webhookUrl":"%s"}' "$prefix" "$webhook"
    fi
  else
    printf '%s' "$body"
  fi
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
    api_post "/api/wechat/create-checkin" "$(inject_webhook_url "${1:-}")"
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
