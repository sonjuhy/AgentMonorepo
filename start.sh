#!/bin/bash
set -e

echo "=========================================="
echo "  Cassiopeia - Startup Script"
echo "  카시오페아 시작 스크립트"
echo "=========================================="
echo ""

# ── 1. 언어 선택 ─────────────────────────────────────────────────────────────
echo "Select language / 언어를 선택하세요"
echo "  [1] English"
echo "  [2] 한국어"
read -rp "  → " LANG
LANG=${LANG:-1}

if [ "$LANG" = "2" ]; then
  L_ENV_OK=".env 파일 확인됨."
  L_ENV_SETUP=".env 파일이 없습니다. 설정을 시작합니다."
  L_LLM="LLM 백엔드 선택 [gemini/claude/local, 기본값: gemini]: "
  L_GEMINI="GEMINI_API_KEY 입력: "
  L_CLAUDE="ANTHROPIC_API_KEY 입력: "
  L_LOCAL_URL="LOCAL_LLM_BASE_URL [기본값: http://localhost:11434/v1]: "
  L_LOCAL_MODEL="LOCAL_LLM_MODEL [기본값: llama3.2]: "
  L_USE_SLACK="Slack 연동 설정? (y/N): "
  L_SLACK_BOT="  SLACK_BOT_TOKEN (xoxb-...): "
  L_SLACK_APP="  SLACK_APP_TOKEN (xapp-...): "
  L_SLACK_CH="  SLACK_CHANNEL (C0...): "
  L_USE_NOTION="Notion 연동 설정? (y/N): "
  L_NOTION_TOKEN="  NOTION_TOKEN: "
  L_NOTION_DB="  NOTION_DATABASE_ID: "
  L_SECRETS="보안 키 설정 (비워두면 자동 생성):"
  L_ADMIN="  ADMIN_API_KEY: "
  L_CLIENT="  CLIENT_API_KEY: "
  L_HMAC="  DISPATCH_HMAC_SECRET: "
  L_ENC="  ENCRYPTION_KEY: "
  L_R_CASS="  REDIS_CASSIOPEIA_PASSWORD: "
  L_R_COMM="  REDIS_COMMUNITY_PASSWORD: "
  L_ENV_DONE=".env 파일이 생성되었습니다."
  L_MISSING_KEYS="다음 필수 키가 .env에 없거나 비어 있습니다:"
  L_FILL_MISSING="값을 입력하세요 (자동 생성 항목은 Enter로 건너뜁니다):"
  L_MISSING_AUTO="Enter 입력 시 자동 생성"
  L_ENV_UPDATED=".env 파일이 업데이트되었습니다."
  L_RUN="실행 방식을 선택하세요:"
  L_RUN1="  1) Python  (개발 환경)"
  L_RUN2="  2) Docker  (운영 권장)"
  L_RUN_SEL="선택 [1/2]: "
  L_VENV="가상환경 생성 및 의존성 설치 중..."
  L_VENV_OK="준비 완료."
  L_PY="Python으로 시작합니다..."
  L_DOCKER="Docker로 시작합니다..."
  L_INVALID="잘못된 입력입니다."
else
  L_ENV_OK=".env found."
  L_ENV_SETUP=".env not found. Starting setup."
  L_LLM="LLM backend [gemini/claude/local, default: gemini]: "
  L_GEMINI="GEMINI_API_KEY: "
  L_CLAUDE="ANTHROPIC_API_KEY: "
  L_LOCAL_URL="LOCAL_LLM_BASE_URL [default: http://localhost:11434/v1]: "
  L_LOCAL_MODEL="LOCAL_LLM_MODEL [default: llama3.2]: "
  L_USE_SLACK="Set up Slack integration? (y/N): "
  L_SLACK_BOT="  SLACK_BOT_TOKEN (xoxb-...): "
  L_SLACK_APP="  SLACK_APP_TOKEN (xapp-...): "
  L_SLACK_CH="  SLACK_CHANNEL (C0...): "
  L_USE_NOTION="Set up Notion integration? (y/N): "
  L_NOTION_TOKEN="  NOTION_TOKEN: "
  L_NOTION_DB="  NOTION_DATABASE_ID: "
  L_SECRETS="Configure security keys (leave blank to auto-generate):"
  L_ADMIN="  ADMIN_API_KEY: "
  L_CLIENT="  CLIENT_API_KEY: "
  L_HMAC="  DISPATCH_HMAC_SECRET: "
  L_ENC="  ENCRYPTION_KEY: "
  L_R_CASS="  REDIS_CASSIOPEIA_PASSWORD: "
  L_R_COMM="  REDIS_COMMUNITY_PASSWORD: "
  L_ENV_DONE=".env file created."
  L_MISSING_KEYS="Missing required keys detected in .env:"
  L_FILL_MISSING="Enter values below (press Enter to auto-generate where applicable):"
  L_MISSING_AUTO="Enter to auto-generate"
  L_ENV_UPDATED=".env updated with missing keys."
  L_RUN="How would you like to run Cassiopeia?"
  L_RUN1="  1) Python  (development)"
  L_RUN2="  2) Docker  (recommended for production)"
  L_RUN_SEL="Select [1/2]: "
  L_VENV="Setting up virtual environment and installing dependencies..."
  L_VENV_OK="Ready."
  L_PY="Starting with Python..."
  L_DOCKER="Starting with Docker..."
  L_INVALID="Invalid selection."
fi

# helpers
gen_hex() { python3 -c "import secrets; print(secrets.token_hex($1))"; }
gen_b64() { python3 -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"; }

# Update or append a key=value pair in .env
_upsert_env() {
  local k="$1" v="$2"
  python3 -c "
import re, sys
k = sys.argv[1]; v = sys.argv[2]
with open('.env') as f: txt = f.read()
pat = re.compile(r'^' + re.escape(k) + r'=.*', re.M)
if pat.search(txt):
    txt = pat.sub(lambda m: k + '=' + v, txt)
else:
    txt = txt.rstrip('\n') + '\n' + k + '=' + v + '\n'
with open('.env', 'w') as f: f.write(txt)
" "$k" "$v"
}

# ── 2. .env ───────────────────────────────────────────────────────────────────
echo ""
if [ -f ".env" ]; then
  echo "[1/3] $L_ENV_OK"

  # Load existing values into current shell
  set -a; source .env 2>/dev/null; set +a

  # Detect missing or empty required keys
  _MISSING=()
  case "${LLM_BACKEND:-gemini}" in
    gemini) [ -z "${GEMINI_API_KEY:-}" ]    && _MISSING+=(GEMINI_API_KEY) ;;
    claude) [ -z "${ANTHROPIC_API_KEY:-}" ] && _MISSING+=(ANTHROPIC_API_KEY) ;;
  esac
  [ -z "${ADMIN_API_KEY:-}" ]             && _MISSING+=(ADMIN_API_KEY)
  [ -z "${CLIENT_API_KEY:-}" ]            && _MISSING+=(CLIENT_API_KEY)
  [ -z "${ENCRYPTION_KEY:-}" ]            && _MISSING+=(ENCRYPTION_KEY)
  [ -z "${REDIS_CASSIOPEIA_PASSWORD:-}" ] && _MISSING+=(REDIS_CASSIOPEIA_PASSWORD)
  [ -z "${REDIS_COMMUNITY_PASSWORD:-}" ]  && _MISSING+=(REDIS_COMMUNITY_PASSWORD)
  [ -z "${DISPATCH_HMAC_SECRET:-}" ]      && _MISSING+=(DISPATCH_HMAC_SECRET)
  [ -z "${SANDBOX_API_KEY:-}" ]           && _MISSING+=(SANDBOX_API_KEY)

  if [ ${#_MISSING[@]} -gt 0 ]; then
    echo ""
    echo "$L_MISSING_KEYS"
    for _k in "${_MISSING[@]}"; do echo "  - $_k"; done
    echo ""
    echo "$L_FILL_MISSING"
    echo ""

    for _k in "${_MISSING[@]}"; do
      case "$_k" in
        GEMINI_API_KEY)
          read -rp "  GEMINI_API_KEY: " _v
          _upsert_env "$_k" "$_v" ;;
        ANTHROPIC_API_KEY)
          read -rp "  ANTHROPIC_API_KEY: " _v
          _upsert_env "$_k" "$_v" ;;
        ADMIN_API_KEY)
          read -rp "  ADMIN_API_KEY [$L_MISSING_AUTO]: " _v
          _upsert_env "$_k" "${_v:-$(gen_hex 32)}" ;;
        CLIENT_API_KEY)
          read -rp "  CLIENT_API_KEY [$L_MISSING_AUTO]: " _v
          _upsert_env "$_k" "${_v:-$(gen_hex 32)}" ;;
        ENCRYPTION_KEY)
          read -rp "  ENCRYPTION_KEY [$L_MISSING_AUTO]: " _v
          _upsert_env "$_k" "${_v:-$(gen_b64)}" ;;
        REDIS_CASSIOPEIA_PASSWORD)
          read -rp "  REDIS_CASSIOPEIA_PASSWORD [$L_MISSING_AUTO]: " _v
          _upsert_env "$_k" "${_v:-$(gen_hex 16)}" ;;
        REDIS_COMMUNITY_PASSWORD)
          read -rp "  REDIS_COMMUNITY_PASSWORD [$L_MISSING_AUTO]: " _v
          _upsert_env "$_k" "${_v:-$(gen_hex 16)}" ;;
        DISPATCH_HMAC_SECRET)
          read -rp "  DISPATCH_HMAC_SECRET [$L_MISSING_AUTO]: " _v
          _upsert_env "$_k" "${_v:-$(gen_hex 32)}" ;;
        SANDBOX_API_KEY)
          _upsert_env "$_k" "$(gen_hex 32)"
          echo "  SANDBOX_API_KEY: ($L_MISSING_AUTO)" ;;
      esac
    done

    echo ""
    echo "[1/3] $L_ENV_UPDATED"
  fi
else
  echo "[1/3] $L_ENV_SETUP"
  echo ""

  read -rp "$L_LLM" LLM_BACKEND
  LLM_BACKEND=${LLM_BACKEND:-gemini}

  GEMINI_API_KEY="" ANTHROPIC_API_KEY="" LOCAL_LLM_BASE_URL="" LOCAL_LLM_MODEL="" NLU_LLM_MODEL="gemini-2.5-flash"
  case "$LLM_BACKEND" in
    gemini) read -rp "$L_GEMINI" GEMINI_API_KEY ;;
    claude) read -rp "$L_CLAUDE" ANTHROPIC_API_KEY ;;
    local)
      read -rp "$L_LOCAL_URL"   LOCAL_LLM_BASE_URL; LOCAL_LLM_BASE_URL=${LOCAL_LLM_BASE_URL:-http://localhost:11434/v1}
      read -rp "$L_LOCAL_MODEL" LOCAL_LLM_MODEL;    LOCAL_LLM_MODEL=${LOCAL_LLM_MODEL:-llama3.2}
      NLU_LLM_MODEL="$LOCAL_LLM_MODEL" ;;
  esac

  SLACK_BOT_TOKEN="" SLACK_APP_TOKEN="" SLACK_CHANNEL=""
  read -rp "$L_USE_SLACK" _slack
  if [[ "${_slack,,}" == "y" ]]; then
    read -rp "$L_SLACK_BOT" SLACK_BOT_TOKEN
    read -rp "$L_SLACK_APP" SLACK_APP_TOKEN
    read -rp "$L_SLACK_CH"  SLACK_CHANNEL
  fi

  NOTION_TOKEN="" NOTION_DATABASE_ID=""
  read -rp "$L_USE_NOTION" _notion
  if [[ "${_notion,,}" == "y" ]]; then
    read -rp "$L_NOTION_TOKEN" NOTION_TOKEN
    read -rp "$L_NOTION_DB"   NOTION_DATABASE_ID
  fi

  echo ""
  echo "$L_SECRETS"
  read -rp "$L_ADMIN"  ADMIN_API_KEY;             ADMIN_API_KEY=${ADMIN_API_KEY:-$(gen_hex 32)}
  read -rp "$L_CLIENT" CLIENT_API_KEY;            CLIENT_API_KEY=${CLIENT_API_KEY:-$(gen_hex 32)}
  read -rp "$L_HMAC"   DISPATCH_HMAC_SECRET;      DISPATCH_HMAC_SECRET=${DISPATCH_HMAC_SECRET:-$(gen_hex 32)}
  read -rp "$L_ENC"    ENCRYPTION_KEY;            ENCRYPTION_KEY=${ENCRYPTION_KEY:-$(gen_b64)}
  read -rp "$L_R_CASS" REDIS_CASSIOPEIA_PASSWORD; REDIS_CASSIOPEIA_PASSWORD=${REDIS_CASSIOPEIA_PASSWORD:-$(gen_hex 16)}
  read -rp "$L_R_COMM" REDIS_COMMUNITY_PASSWORD;  REDIS_COMMUNITY_PASSWORD=${REDIS_COMMUNITY_PASSWORD:-$(gen_hex 16)}

  cat > .env <<ENVEOF
# Generated by Cassiopeia start.sh
PYTHONPATH=.
LLM_BACKEND=${LLM_BACKEND}
GEMINI_API_KEY=${GEMINI_API_KEY}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
LOCAL_LLM_BASE_URL=${LOCAL_LLM_BASE_URL}
LOCAL_LLM_MODEL=${LOCAL_LLM_MODEL}
NLU_LLM_MODEL=${NLU_LLM_MODEL}
NLU_LLM_TEMPERATURE=0.2
NLU_CONFIDENCE_THRESHOLD=0.7
SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN}
SLACK_APP_TOKEN=${SLACK_APP_TOKEN}
SLACK_CHANNEL=${SLACK_CHANNEL}
NOTION_TOKEN=${NOTION_TOKEN}
NOTION_DATABASE_ID=${NOTION_DATABASE_ID}
ADMIN_API_KEY=${ADMIN_API_KEY}
CLIENT_API_KEY=${CLIENT_API_KEY}
DISPATCH_HMAC_SECRET=${DISPATCH_HMAC_SECRET}
ENCRYPTION_KEY=${ENCRYPTION_KEY}
REDIS_CASSIOPEIA_PASSWORD=${REDIS_CASSIOPEIA_PASSWORD}
REDIS_COMMUNITY_PASSWORD=${REDIS_COMMUNITY_PASSWORD}
REDIS_URL=redis://cassiopeia:${REDIS_CASSIOPEIA_PASSWORD}@127.0.0.1:6379
USER_TIMEZONE=Asia/Seoul
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
RESPONSE_TIMEOUT_SEC=30.0
CB_THRESHOLD=3
CB_WINDOW_SEC=300
HEARTBEAT_VALID_SEC=30
RATE_LIMIT_PER_MIN=20
RATE_LIMIT_WINDOW=60
SANDBOX_RUNTIME=disabled
SANDBOX_API_KEY=$(gen_hex 32)
ENVEOF

  echo ""
  echo "[1/3] $L_ENV_DONE"
fi

# ── 3. 실행 방식 선택 ─────────────────────────────────────────────────────────
echo ""
echo "[2/3] $L_RUN"
echo "$L_RUN1"
echo "$L_RUN2"
echo ""
read -rp "$L_RUN_SEL" RUN_MODE

# ── 4. 실행 ──────────────────────────────────────────────────────────────────
echo ""
case "$RUN_MODE" in
  1)
    echo "[3/3] $L_VENV"
    [ ! -d "venv" ] && python3 -m venv venv
    source venv/bin/activate
    pip install -q --no-cache-dir -r agents/cassiopeia_agent/requirements.txt
    echo "[3/3] $L_VENV_OK"
    echo ""
    echo "$L_PY"
    python -m agents.cassiopeia_agent.main
    ;;
  2)
    echo "$L_DOCKER"
    docker-compose up
    ;;
  *)
    echo "$L_INVALID"
    exit 1
    ;;
esac
