# AgentMonorepo 실행 & 테스트 가이드

## 목차

1. [프로젝트 아키텍처 개요](#1-프로젝트-아키텍처-개요)
2. [사전 요구사항](#2-사전-요구사항)
3. [환경 설정](#3-환경-설정)
4. [패키지 설치](#4-패키지-설치)
5. [Redis 실행](#5-redis-실행)
6. [에이전트별 단독 실행 & 테스트](#6-에이전트별-단독-실행--테스트)
   - [File Agent](#61-file-agent)
   - [Research Agent](#62-research-agent)
   - [Schedule Agent](#63-schedule-agent)
   - [Planning Agent](#64-planning-agent)
   - [Sandbox Agent](#65-sandbox-agent)
   - [Orchestra Agent](#66-orchestra-agent)
7. [전체 파이프라인 실행 (Docker Compose)](#7-전체-파이프라인-실행-docker-compose)
8. [Slack 연동 테스트](#8-slack-연동-테스트)
9. [트러블슈팅](#9-트러블슈팅)

---

## 1. 프로젝트 아키텍처 개요

```
Slack 메시지
    │
    ▼
Communication Agent (slack_listener)  ─── 장기 실행 서버
    │  Redis List RPUSH
    ▼
Orchestra Agent  ─── NLU 의도 파악 → 에이전트 선택 → 디스패치
    │
    ├─ Redis Pub/Sub ──► File Agent      (ephemeral, 1건 처리 후 종료)
    ├─ Redis Pub/Sub ──► Research Agent  (ephemeral)
    ├─ Redis Pub/Sub ──► Schedule Agent  (ephemeral)
    └─ Redis List   ──► Planning Agent   (server 또는 ephemeral)
                    ──► Sandbox Agent    (server)
```

### 에이전트 통신 방식

| 에이전트 | 통신 방식 | Redis 키 | 실행 방식 |
|---|---|---|---|
| orchestra | BLPOP (List) | `agent:orchestra:tasks` | 장기 실행 서버 |
| communication | BLPOP (List) | `agent:communication:tasks` | 장기 실행 서버 |
| planning | BLPOP (List) | `agent:planning:tasks` | server / ephemeral |
| sandbox | BLPOP (List) | `agent:sandbox:tasks` | 장기 실행 서버 |
| file | Pub/Sub | `agent:file` | ephemeral (1건 처리) |
| research | Pub/Sub | `agent:research` | ephemeral (1건 처리) |
| schedule | Pub/Sub | `agent:schedule` | ephemeral (1건 처리) |

---

## 2. 사전 요구사항

### 필수

| 항목 | 버전 | 설치 방법 |
|---|---|---|
| Python | 3.12 이상 | [python.org](https://python.org) |
| Redis | 7.x 이상 | Docker 또는 직접 설치 |
| Docker | 24.x 이상 | [docker.com](https://docker.com) |

### API 키 (사용할 에이전트에 따라 선택)

| 키 | 용도 | 필수 여부 |
|---|---|---|
| `GEMINI_API_KEY` | Orchestra NLU, Research Agent | Orchestra / Research 사용 시 필수 |
| `ANTHROPIC_API_KEY` | Orchestra NLU 폴백, Claude 분류기 | 선택 |
| `PERPLEXITY_API_KEY` | Research Agent (Perplexity 공급자) | Research + Perplexity 선택 시 |
| `SLACK_BOT_TOKEN` | Slack 연동 | Slack 사용 시 필수 |
| `SLACK_APP_TOKEN` | Slack Socket Mode | Slack 사용 시 필수 |
| `NOTION_TOKEN` | Planning Agent | Planning 사용 시 필수 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Schedule Agent | Schedule 사용 시 필수 |

---

## 3. 환경 설정

### 3-1. `.env` 파일 작성

프로젝트 루트의 `.env`를 편집합니다.

```dotenv
# ── 공통 ──────────────────────────────────────────
PYTHONPATH=.
REDIS_URL=redis://127.0.0.1:6379

# ── LLM API ────────────────────────────────────────
GEMINI_API_KEY=your_gemini_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here   # 선택

# ── Orchestra NLU ──────────────────────────────────
NLU_BACKEND=gemini                  # gemini | claude
GEMINI_NLU_MODEL=gemini-2.0-flash  # 선택 (기본값)
USER_TIMEZONE=Asia/Seoul

# ── Research Agent ─────────────────────────────────
RESEARCH_SEARCH_PROVIDER=gemini     # gemini | perplexity
GEMINI_SEARCH_MODEL=gemini-2.0-flash
PERPLEXITY_API_KEY=your_perplexity_key_here  # perplexity 선택 시
RESEARCH_REPORT_OUTPUT_DIR=./reports

# ── Schedule Agent ─────────────────────────────────
GOOGLE_CALENDAR_ID=primary
# 방법 A: JSON 파일 경로
GOOGLE_SERVICE_ACCOUNT_KEY_FILE=/path/to/service-account.json
# 방법 B: JSON 문자열 직접 주입 (파일보다 우선)
# GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"..."}

# ── File Agent ─────────────────────────────────────
FILE_AGENT_ALLOWED_ROOTS=/tmp,/workspace
FILE_AGENT_MAX_FILE_SIZE_MB=10

# ── Planning Agent ─────────────────────────────────
NOTION_TOKEN=your_notion_integration_token
NOTION_DATABASE_ID=your_notion_database_id

# ── Slack / Communication ──────────────────────────
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_CHANNEL=C0XXXXXXXXX
CLASSIFIER_BACKEND=gemini_api       # claude_api | gemini_api
```

### 3-2. 가상환경 생성

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
```

---

## 4. 패키지 설치

현재 `requirements.txt`가 없으므로 에이전트별 필요 패키지를 직접 설치합니다.

```bash
# 공통 (모든 에이전트)
pip install redis pydantic

# Orchestra Agent
pip install google-genai anthropic fastapi uvicorn asyncpg

# Research Agent (Gemini 공급자)
pip install google-generativeai

# Research Agent (Perplexity 공급자)
pip install httpx

# Schedule Agent
pip install google-api-python-client google-auth

# Planning Agent
pip install notion-client anthropic fastapi uvicorn

# Sandbox Agent
pip install docker fastapi uvicorn

# Communication Agent (Slack)
pip install slack-sdk fastapi uvicorn
```

> **팁:** 전체 개발 환경용 한 번에 설치:
> ```bash
> pip install redis pydantic google-genai google-generativeai anthropic \
>             httpx google-api-python-client google-auth \
>             notion-client docker fastapi uvicorn slack-sdk asyncpg
> ```

---

## 5. Redis 실행

### Docker로 실행 (권장)

```bash
docker run -d --name redis-dev -p 6379:6379 redis:7-alpine
```

### 연결 확인

```bash
redis-cli ping
# PONG
```

---

## 6. 에이전트별 단독 실행 & 테스트

> 모든 명령은 **프로젝트 루트**에서 실행합니다.
> 터미널을 2개 열어서 하나는 에이전트 실행, 하나는 메시지 전송에 사용합니다.

### 6.1 File Agent

파일 CRUD를 처리하는 ephemeral 에이전트입니다.

#### 실행

```bash
# 터미널 1: 에이전트 대기
PYTHONPATH=. FILE_AGENT_ALLOWED_ROOTS=/tmp python -m agents.file_agent.main
```

#### 테스트 메시지 전송

```bash
# 터미널 2: 테스트 파일 생성 후 메시지 전송

# 1) 파일 쓰기
redis-cli PUBLISH agent:file '{
  "sender": "orchestra",
  "receiver": "file",
  "action": "write_file",
  "payload": {
    "file_path": "/tmp/hello.txt",
    "content": "안녕하세요, File Agent 테스트입니다.",
    "overwrite": true
  },
  "timestamp": "2026-04-10T00:00:00"
}'

# 2) 파일 읽기 (에이전트를 다시 실행한 후)
redis-cli PUBLISH agent:file '{
  "sender": "orchestra",
  "receiver": "file",
  "action": "read_file",
  "payload": {"file_path": "/tmp/hello.txt"},
  "timestamp": "2026-04-10T00:00:00"
}'

# 3) 파일 삭제
redis-cli PUBLISH agent:file '{
  "sender": "orchestra",
  "receiver": "file",
  "action": "delete_file",
  "payload": {"file_path": "/tmp/hello.txt"},
  "timestamp": "2026-04-10T00:00:00"
}'
```

#### 응답 수신 확인

```bash
# 에이전트가 응답을 agent:orchestra 채널로 발행하므로 구독하여 확인
redis-cli SUBSCRIBE agent:orchestra
```

---

### 6.2 Research Agent

웹 검색 후 마크다운 보고서를 생성하는 ephemeral 에이전트입니다.

#### 전제 조건

- `GEMINI_API_KEY` 또는 `PERPLEXITY_API_KEY` 설정 필요
- Gemini 사용 시: `pip install google-generativeai`
- Perplexity 사용 시: `pip install httpx`

#### 실행

```bash
# Gemini 공급자로 실행
PYTHONPATH=. \
RESEARCH_SEARCH_PROVIDER=gemini \
GEMINI_API_KEY=$GEMINI_API_KEY \
RESEARCH_REPORT_OUTPUT_DIR=/tmp/reports \
python -m agents.research_agent.main
```

#### 테스트 메시지 전송

```bash
# 1) 주제 조사 + 보고서 반환
redis-cli PUBLISH agent:research '{
  "sender": "orchestra",
  "receiver": "research",
  "action": "search_and_report",
  "payload": {"topic": "2025년 AI 에이전트 기술 동향"},
  "timestamp": "2026-04-10T00:00:00"
}'

# 2) 조사 + 파일 저장
redis-cli PUBLISH agent:research '{
  "sender": "orchestra",
  "receiver": "research",
  "action": "search_and_report",
  "payload": {
    "topic": "Python asyncio 최신 기능",
    "file_path": "asyncio_report.md"
  },
  "timestamp": "2026-04-10T00:00:00"
}'

# 3) 출처 URL만 수집
redis-cli PUBLISH agent:research '{
  "sender": "orchestra",
  "receiver": "research",
  "action": "get_citations",
  "payload": {"topic": "LLM 기반 멀티에이전트 시스템"},
  "timestamp": "2026-04-10T00:00:00"
}'

# 4) 내용 파일 저장
redis-cli PUBLISH agent:research '{
  "sender": "orchestra",
  "receiver": "research",
  "action": "save_report",
  "payload": {
    "content": "# 테스트 보고서\n\n내용입니다.",
    "file_path": "test_report.md"
  },
  "timestamp": "2026-04-10T00:00:00"
}'
```

---

### 6.3 Schedule Agent

Google Calendar를 통해 일정을 관리하는 ephemeral 에이전트입니다.

#### 전제 조건

Google Cloud Console에서 서비스 계정 설정이 필요합니다.

**서비스 계정 발급 절차:**
1. [Google Cloud Console](https://console.cloud.google.com) → IAM & Admin → Service Accounts
2. 새 서비스 계정 생성 → JSON 키 다운로드
3. [Google Calendar](https://calendar.google.com) → 캘린더 설정 → 해당 서비스 계정 이메일 공유 (편집자 권한)

```bash
pip install google-api-python-client google-auth
```

#### 실행

```bash
# 방법 A: JSON 파일 경로
PYTHONPATH=. \
GOOGLE_CALENDAR_ID=primary \
GOOGLE_SERVICE_ACCOUNT_KEY_FILE=/path/to/service-account.json \
python -m agents.schedule_agent.main

# 방법 B: JSON 문자열 직접 주입
PYTHONPATH=. \
GOOGLE_CALENDAR_ID=primary \
GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":"..."}' \
python -m agents.schedule_agent.main
```

#### 테스트 메시지 전송

```bash
# 1) 일정 조회
redis-cli PUBLISH agent:schedule '{
  "sender": "orchestra",
  "receiver": "schedule",
  "action": "list_schedules",
  "payload": {
    "start_time": "2026-04-10T00:00:00+09:00",
    "end_time": "2026-04-17T23:59:59+09:00"
  },
  "timestamp": "2026-04-10T00:00:00"
}'

# 2) 일정 추가
redis-cli PUBLISH agent:schedule '{
  "sender": "orchestra",
  "receiver": "schedule",
  "action": "add_schedule",
  "payload": {
    "event": {
      "title": "팀 스탠드업 미팅",
      "start_time": "2026-04-15T10:00:00+09:00",
      "end_time": "2026-04-15T10:30:00+09:00",
      "description": "주간 팀 스탠드업",
      "attendees": ["team@example.com"]
    }
  },
  "timestamp": "2026-04-10T00:00:00"
}'

# 3) 일정 수정 (event_id는 add_schedule 결과에서 확인)
redis-cli PUBLISH agent:schedule '{
  "sender": "orchestra",
  "receiver": "schedule",
  "action": "modify_schedule",
  "payload": {
    "event_id": "YOUR_EVENT_ID_HERE",
    "event": {
      "title": "팀 스탠드업 미팅 (수정됨)",
      "start_time": "2026-04-15T11:00:00+09:00",
      "end_time": "2026-04-15T11:30:00+09:00"
    }
  },
  "timestamp": "2026-04-10T00:00:00"
}'

# 4) 일정 삭제
redis-cli PUBLISH agent:schedule '{
  "sender": "orchestra",
  "receiver": "schedule",
  "action": "remove_schedule",
  "payload": {"event_id": "YOUR_EVENT_ID_HERE"},
  "timestamp": "2026-04-10T00:00:00"
}'
```

#### 응답 확인

```bash
redis-cli SUBSCRIBE agent:orchestra
```

---

### 6.4 Planning Agent

Notion 기반 태스크 분석 에이전트입니다.

#### 전제 조건

- Notion Integration 토큰 및 Database ID 필요
- [Notion Developers](https://developers.notion.com) → New Integration → 토큰 복사

```bash
pip install notion-client anthropic
```

#### ephemeral 모드 (Notion 태스크 직접 처리)

```bash
PYTHONPATH=. \
NOTION_TOKEN=your_notion_token \
NOTION_DATABASE_ID=your_database_id \
GEMINI_API_KEY=$GEMINI_API_KEY \
python -m agents.planning_agent.main
```

#### server 모드 (Orchestra와 연동)

```bash
PYTHONPATH=. \
MODE=server \
NOTION_TOKEN=your_notion_token \
NOTION_DATABASE_ID=your_database_id \
GEMINI_API_KEY=$GEMINI_API_KEY \
PORT=8002 \
python -m agents.planning_agent.main
```

---

### 6.5 Sandbox Agent

Python/JavaScript 코드를 격리된 환경에서 실행하는 에이전트입니다.

#### 전제 조건

- Docker 실행 중이어야 합니다.

#### ephemeral 모드 (동작 확인용)

```bash
PYTHONPATH=. MODE=ephemeral python -m agents.sandbox_agent.main
```

#### server 모드

```bash
PYTHONPATH=. MODE=server PORT=8003 python -m agents.sandbox_agent.main
```

#### Redis 큐로 테스트 메시지 전송

```bash
redis-cli RPUSH agent:sandbox:tasks '{
  "task_id": "test-001",
  "session_id": "test-session",
  "timestamp": "2026-04-10T00:00:00Z",
  "requester": {"user_id": "tester", "channel_id": ""},
  "agent": "sandbox",
  "action": "execute_tdd_cycle",
  "params": {
    "language": "python",
    "code": "def add(a, b):\n    return a + b\n\nprint(add(1, 2))",
    "timeout": 30
  },
  "retry_info": {"count": 0, "max_retries": 3, "reason": null},
  "priority": "MEDIUM",
  "timeout": 60,
  "metadata": {"step_info": {}, "requires_user_approval": false},
  "version": "1.1"
}'
```

---

### 6.6 Orchestra Agent

전체 에이전트를 조율하는 FastAPI 서버입니다.

#### 전제 조건

```bash
pip install google-genai anthropic fastapi uvicorn asyncpg redis
```

PostgreSQL이 필요합니다:

```bash
docker run -d --name postgres-dev \
  -e POSTGRES_USER=agent \
  -e POSTGRES_PASSWORD=agent \
  -e POSTGRES_DB=agentdb \
  -p 5432:5432 \
  postgres:16-alpine
```

#### 실행

```bash
PYTHONPATH=. \
GEMINI_API_KEY=$GEMINI_API_KEY \
REDIS_URL=redis://127.0.0.1:6379 \
DATABASE_URL=postgresql://agent:agent@localhost:5432/agentdb \
NLU_BACKEND=gemini \
PORT=8001 \
python -m agents.orchestra_agent.main
```

#### HTTP 엔드포인트 테스트

```bash
# 헬스 체크
curl http://localhost:8001/health

# 등록된 에이전트 목록
curl http://localhost:8001/agents

# 에이전트 결과 전송 (에이전트가 직접 호출하는 엔드포인트)
curl -X POST http://localhost:8001/results \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "test-001",
    "status": "SUCCESS",
    "result_data": {"summary": "테스트 성공", "raw_text": ""},
    "usage_stats": {}
  }'
```

#### 태스크 직접 주입 테스트

```bash
redis-cli RPUSH agent:orchestra:tasks '{
  "task_id": "manual-001",
  "session_id": "test-session-001",
  "content": "오늘 오후 3시에 팀 회의 일정 추가해줘",
  "requester": {
    "user_id": "U12345",
    "channel_id": "C12345",
    "platform": "test"
  }
}'
```

---

## 7. 전체 파이프라인 실행 (Docker Compose)

### 7-1. 이미지 빌드

```bash
# 장기 실행 서비스 이미지 빌드
docker compose build slack_listener

# 단발성 에이전트 이미지 빌드 (profiles=agents)
docker compose --profile agents build
```

### 7-2. 인프라 먼저 실행

```bash
# Redis 컨테이너 (compose에 없으므로 별도 실행)
docker run -d --name redis-dev \
  --network host \
  redis:7-alpine
```

### 7-3. Slack Listener 실행

```bash
docker compose up slack_listener
```

### 7-4. 로그 확인

```bash
docker compose logs -f slack_listener
```

### 7-5. 서비스 종료

```bash
docker compose down
```

---

## 8. Slack 연동 테스트

Slack App 설정이 완료된 경우 전체 파이프라인을 테스트할 수 있습니다.

### Slack App 설정 체크리스트

- [ ] [Slack API](https://api.slack.com/apps) → 앱 생성
- [ ] **Socket Mode** 활성화 → App-Level Token 발급 (`xapp-` 접두사)
- [ ] **OAuth & Permissions** → Bot Token Scopes 추가:
  - `channels:history`, `channels:read`
  - `chat:write`, `chat:write.public`
  - `users:read`
- [ ] 앱을 워크스페이스에 설치 → Bot Token 복사 (`xoxb-` 접두사)
- [ ] 채널에 앱 초대: `/invite @앱이름`

### 테스트 시나리오

Slack 채널에서 다음 메시지를 전송하면 전체 파이프라인이 동작합니다:

```
파이썬으로 피보나치 수열 코드 작성해줘
```

```
다음 주 월요일 오전 10시에 팀 회의 등록해줘
```

```
AI 에이전트 최신 트렌드 조사해서 보고서 만들어줘
```

---

## 9. 트러블슈팅

### Redis 연결 실패

```
RuntimeError: Redis 연결이 초기화되지 않았습니다.
```

```bash
# Redis 실행 확인
redis-cli ping

# REDIS_URL 환경변수 확인
echo $REDIS_URL
```

### PYTHONPATH 오류

```
ModuleNotFoundError: No module named 'shared_core'
```

```bash
# 프로젝트 루트에서 실행 중인지 확인
pwd

# PYTHONPATH 설정
export PYTHONPATH=.
```

### Google Calendar 인증 실패

```
ValueError: 서비스 계정 키가 설정되지 않았습니다.
```

```bash
# 환경변수 설정 확인
echo $GOOGLE_SERVICE_ACCOUNT_KEY_FILE

# JSON 파일 경로가 올바른지 확인
ls -la $GOOGLE_SERVICE_ACCOUNT_KEY_FILE
```

### Gemini API 오류 (google-generativeai)

Research Agent에서 `protos.Tool` 관련 오류 발생 시 패키지 버전을 확인합니다:

```bash
pip show google-generativeai
# Required: >= 0.8

pip install --upgrade google-generativeai
```

### ephemeral 에이전트가 메시지를 수신하지 못하는 경우

Pub/Sub은 **구독 전에 발행된 메시지를 수신하지 못합니다.** 에이전트를 먼저 실행한 뒤 메시지를 전송하세요.

```bash
# 올바른 순서
# 1) 에이전트 실행 (구독 시작 대기)
python -m agents.file_agent.main &

# 2) 잠시 후 메시지 전송
sleep 1 && redis-cli PUBLISH agent:file '{...}'
```

### Docker 소켓 권한 오류 (Sandbox Agent)

```bash
# Linux/macOS
sudo chmod 666 /var/run/docker.sock

# 또는 사용자를 docker 그룹에 추가
sudo usermod -aG docker $USER
```

### Schedule Agent — 캘린더 접근 거부

서비스 계정 이메일을 캘린더에 공유해야 합니다:
1. 서비스 계정 JSON에서 `client_email` 값 확인
2. Google Calendar → 캘린더 설정 → 특정 사용자와 공유 → 해당 이메일 추가 (편집자 권한)
