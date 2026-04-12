# Orchestra Agent + Slack 연동 실행 가이드

Slack으로 메시지를 보내면 Orchestra Agent가 의도를 분석하고 결과를 Slack으로 돌려주는
전체 파이프라인의 설치·실행·검증 절차를 다룹니다.

## 목차

1. [전체 흐름 이해](#1-전체-흐름-이해)
2. [사전 준비](#2-사전-준비)
3. [환경 변수 설정](#3-환경-변수-설정)
4. [패키지 설치](#4-패키지-설치)
5. [인프라 실행 (Redis)](#5-인프라-실행-redis)
6. [Orchestra Agent 실행](#6-orchestra-agent-실행)
7. [Communication Agent (Slack) 실행](#7-communication-agent-slack-실행)
8. [Slack 메시지 수신 확인](#8-slack-메시지-수신-확인)
9. [단계별 동작 검증](#9-단계별-동작-검증)
10. [트러블슈팅](#10-트러블슈팅)

---

## 1. 전체 흐름 이해

```
사용자 (Slack 채널)
    │
    │  메시지 입력
    ▼
┌─────────────────────────────────────────────────┐
│  Communication Agent  (port 8000)               │
│  FastAPI + Slack Socket Mode                    │
│                                                 │
│  1. Slack 메시지 수신 (slack_bolt)               │
│  2. MessageCleaner로 @멘션 등 제거               │
│  3. "⏳ 접수했습니다." 스레드 메시지 발송          │
│  4. Redis RPUSH → agent:orchestra:tasks         │
└───────────────────┬─────────────────────────────┘
                    │  Redis List RPUSH
                    ▼
┌─────────────────────────────────────────────────┐
│  Orchestra Agent  (port 8001)                   │
│  FastAPI + BLPOP 메인 루프                       │
│                                                 │
│  5. BLPOP ← agent:orchestra:tasks               │
│  6. Gemini NLU → 에이전트·액션·파라미터 추출      │
│  7. 하위 에이전트 Redis 큐에 RPUSH               │
│  8. 결과 BLPOP ← orchestra:results:{task_id}    │
│  9. RPUSH → agent:communication:tasks           │
└───────────────────┬─────────────────────────────┘
                    │  Redis List RPUSH
                    ▼
┌─────────────────────────────────────────────────┐
│  Communication Agent (결과 리스너)               │
│                                                 │
│  10. BLPOP ← agent:communication:tasks          │
│  11. Slack Block Kit으로 렌더링                  │
│  12. Slack 스레드에 최종 결과 발송               │
└─────────────────────────────────────────────────┘
    │
    ▼
사용자 (Slack 스레드 답글로 결과 수신)
```

### Redis 큐 역할 요약

| 큐 키 | 방향 | 용도 |
|---|---|---|
| `agent:orchestra:tasks` | Comm → Orchestra | 사용자 요청 전달 |
| `agent:communication:tasks` | Orchestra → Comm | 처리 결과 전달 |
| `orchestra:results:{task_id}` | 하위 에이전트 → Orchestra | 에이전트 실행 결과 |
| `orchestra:approval:{task_id}` | Comm → Orchestra | 사용자 승인/반려 피드백 |

---

## 2. 사전 준비

### 2-1. Slack App 생성

1. [https://api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. 앱 이름 입력 후 워크스페이스 선택

#### Socket Mode 활성화

- 좌측 메뉴 **Socket Mode** → **Enable Socket Mode** ON
- **App-Level Tokens** → **Generate Token and Scopes** 클릭
  - Token Name: 임의 이름 (예: `socket-token`)
  - Scope: `connections:write` 추가
  - **Generate** → 토큰 복사 (`xapp-` 접두사) → `SLACK_APP_TOKEN`

#### Bot Token Scopes 설정

- 좌측 메뉴 **OAuth & Permissions** → **Scopes** → **Bot Token Scopes** 추가:

  | Scope | 용도 |
  |---|---|
  | `channels:history` | 채널 메시지 조회 |
  | `channels:read` | 채널 정보 조회 |
  | `chat:write` | 메시지 발송 |
  | `chat:write.public` | 초대 없이 공개 채널 발송 |
  | `users:read` | 사용자 정보 조회 |

#### 앱 설치 및 Bot Token 발급

- **OAuth & Permissions** → **Install to Workspace** → 허용
- **Bot User OAuth Token** 복사 (`xoxb-` 접두사) → `SLACK_BOT_TOKEN`

#### 메시지 이벤트 구독 설정

- 좌측 메뉴 **Event Subscriptions** → **Enable Events** ON
- **Subscribe to bot events** → `message.channels` 추가
- **Save Changes**

#### 채널에 앱 초대

- Slack 채널에서:
  ```
  /invite @앱이름
  ```
- 채널 ID 확인: 채널 이름 우클릭 → **채널 세부 정보 보기** → 하단에 채널 ID 표시 (`C`로 시작)

---

### 2-2. Python 환경

```bash
# Python 3.12 이상 필요
python --version

# 프로젝트 루트에서 가상환경 생성
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 2-3. Docker

Redis 실행에 Docker를 사용합니다.

```bash
docker --version   # 24.x 이상 권장
```

---

## 3. 환경 변수 설정

프로젝트 루트의 `.env` 파일을 편집합니다.

```dotenv
# ── 공통 ──────────────────────────────────────────────────
PYTHONPATH=.
REDIS_URL=redis://localhost:6379

# ── LLM (Orchestra NLU 필수) ──────────────────────────────
# 둘 중 하나 이상 설정 (기본: Gemini)
GEMINI_API_KEY=AIza...
ANTHROPIC_API_KEY=sk-ant-...   # 선택 (Claude 폴백용)

# NLU 백엔드 선택: gemini (기본) | claude
NLU_BACKEND=gemini
GEMINI_NLU_MODEL=gemini-2.0-flash
USER_TIMEZONE=Asia/Seoul

# ── Slack ─────────────────────────────────────────────────
SLACK_BOT_TOKEN=xoxb-...         # Bot User OAuth Token
SLACK_APP_TOKEN=xapp-...         # App-Level Token (Socket Mode)
SLACK_CHANNEL=C0XXXXXXXXX        # 메시지를 발송할 채널 ID

# LLM 분류기 (폴백 경로용)
CLASSIFIER_BACKEND=gemini_api    # gemini_api | claude_api

# 특정 채널/사용자만 허용 (비어있으면 전체 허용)
SLACK_ALLOWED_CHANNELS=          # 예: C0AAA,C0BBB
SLACK_ALLOWED_USERS=             # 예: U0AAA,U0BBB

# ── PostgreSQL (선택 — 없으면 Redis만 사용) ────────────────
# POSTGRES_URL=postgresql://user:pass@localhost:5432/agentdb
```

> `POSTGRES_URL`을 설정하지 않으면 Orchestra Agent가 Redis만으로 동작합니다.
> 간단한 테스트에는 PostgreSQL 없이 진행해도 됩니다.

---

## 4. 패키지 설치

```bash
# Orchestra Agent
pip install \
  fastapi uvicorn \
  redis \
  pydantic \
  google-genai \
  anthropic

# Communication Agent (Slack)
pip install \
  slack-sdk \
  slack-bolt \
  python-dotenv \
  httpx

# 공통
pip install asyncpg   # PostgreSQL 사용 시만 필요
```

한 번에 설치:

```bash
pip install fastapi uvicorn redis pydantic google-genai anthropic \
            slack-sdk slack-bolt python-dotenv httpx
```

---

## 5. 인프라 실행 (Redis)

```bash
# Redis 컨테이너 실행
docker run -d \
  --name redis-dev \
  -p 6379:6379 \
  redis:7-alpine

# 연결 확인
redis-cli ping
# PONG
```

---

## 6. Orchestra Agent 실행

Orchestra Agent는 **FastAPI 서버**로, 포트 8001에서 실행됩니다.

### 6-1. 실행

```bash
# .env 로드 후 실행
PYTHONPATH=. \
GEMINI_API_KEY=$GEMINI_API_KEY \
REDIS_URL=redis://localhost:6379 \
NLU_BACKEND=gemini \
USER_TIMEZONE=Asia/Seoul \
PORT=8001 \
python -m agents.orchestra_agent.main
```

또는 `.env`를 직접 사용하는 경우:

Linux
```bash
set -a && source .env && set +a
python -m agents.orchestra_agent.main
```

Windows
```bash
for /f "eol=# tokens=1,* delims==" %A in (.env) do set "%A=%B"
python -m agents.orchestra_agent.main
```

### 6-2. 정상 실행 로그

```
INFO     orchestra_agent.main: [Lifespan] Orchestra Agent 시작
INFO     orchestra_agent.state_manager: [StateManager] POSTGRES_URL 미설정 — PostgreSQL 비활성화
INFO     orchestra_agent.manager: [OrchestraManager] 메인 루프 시작 (queue=agent:orchestra:tasks)
INFO     uvicorn.server: Application startup complete.
```

### 6-3. 헬스체크 확인

```bash
curl http://localhost:8001/health
```

예상 응답:

```json
{
  "status": "ok",
  "listen_task_running": true,
  "agents": {}
}
```

---

## 7. Communication Agent (Slack) 실행

Communication Agent는 **FastAPI + Slack Socket Mode** 서버로, 포트 8000에서 실행됩니다.
**Orchestra Agent가 먼저 실행된 상태**에서 시작하세요.

### 7-1. 실행

```bash
# 새 터미널에서 실행
PYTHONPATH=. \
SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
SLACK_APP_TOKEN=$SLACK_APP_TOKEN \
SLACK_CHANNEL=$SLACK_CHANNEL \
REDIS_URL=redis://localhost:6379 \
GEMINI_API_KEY=$GEMINI_API_KEY \
CLASSIFIER_BACKEND=gemini_api \
PORT=8000 \
python -m agents.communication_agent.listener_main
```

또는 `.env` 로드 후:

```bash
set -a && source .env && set +a
python -m agents.communication_agent.listener_main
```

### 7-2. 정상 실행 로그

```
==================================================
  Slack Agent FastAPI 서버 시작
  주소: http://0.0.0.0:8000
  문서: http://localhost:8000/docs
==================================================

INFO  slack_agent.fastapi_app: [lifespan] Redis 연결 성공
INFO  slack_agent.fastapi_app: [lifespan] Redis 결과 리스너 시작
INFO  slack_agent.fastapi_app: [lifespan] Slack Socket Mode 연결 시작 (backend=gemini_api)
INFO  uvicorn.server: Application startup complete.
```

### 7-3. 헬스체크 확인

```bash
curl http://localhost:8000/health
```

예상 응답:

```json
{
  "status": "ok",
  "socket_running": true,
  "redis_listener_running": true,
  "redis_connected": true,
  "sse_clients": 0,
  "recent_messages_buffered": 0
}
```

`socket_running`과 `redis_connected`가 모두 `true`이어야 정상입니다.

---

## 8. Slack 메시지 수신 확인

### 8-1. Slack에서 메시지 전송

앱이 초대된 채널에서 메시지를 입력합니다:

```
안녕, 테스트 메시지야
```

또는 에이전트 기능을 사용하는 메시지:

```
파이썬으로 피보나치 함수 작성해줘
```

### 8-2. 예상 동작 순서

| 단계 | 위치 | 내용 |
|---|---|---|
| 1 | Slack 채널 | 사용자가 메시지 입력 |
| 2 | Slack 채널 | Bot이 "⏳ 요청을 접수했습니다. 처리 중입니다..." 스레드 메시지 발송 |
| 3 | Communication Agent 로그 | `[CommAgent] 오케스트라 전달 — task_id=... text=...` |
| 4 | Orchestra Agent 로그 | `[OrchestraManager] 메인 루프: 태스크 수신 task_id=...` |
| 5 | Orchestra Agent 로그 | `[NLU] 분석 완료 type=single session=...` |
| 6 | Orchestra Agent 로그 | `[Manager] 디스패치 → {에이전트명} task_id=...` |
| 7 | Slack 스레드 | Bot이 최종 결과를 Block Kit 형식으로 답글 발송 |

### 8-3. 수신 메시지 API로 확인

Communication Agent가 수신한 메시지를 REST API로도 확인할 수 있습니다:

```bash
# 최근 수신 메시지 조회 (인메모리)
curl http://localhost:8000/messages/recent

# 특정 채널 기준 필터링
curl "http://localhost:8000/messages/recent?channel=C0XXXXXXXXX"

# Slack API를 통한 채널 히스토리 조회
curl "http://localhost:8000/messages/history?channel=C0XXXXXXXXX&limit=10"
```

### 8-4. 실시간 메시지 스트리밍 (SSE)

메시지가 수신될 때마다 스트리밍으로 확인:

```bash
curl -N http://localhost:8000/messages/live
```

메시지를 Slack에 입력하면 즉시 아래와 같이 출력됩니다:

```
data: {"event": "connected", "message": "Slack 실시간 메시지 스트림 연결됨", ...}

data: {"user": "U0XXXXXXX", "channel": "C0XXXXXXX", "text": "안녕, 테스트야", "ts": "1234567890.123456", ...}
```

---

## 9. 단계별 동작 검증

각 단계를 Redis CLI로 직접 확인하며 파이프라인을 검증합니다.

### 9-1. Orchestra 큐에 태스크 직접 주입

Slack 없이 Orchestra Agent만 테스트합니다.

```bash
redis-cli RPUSH agent:orchestra:tasks '{
  "task_id": "test-manual-001",
  "session_id": "U00001:C00001",
  "content": "안녕하세요, 테스트입니다.",
  "requester": {
    "user_id": "U00001",
    "channel_id": "C00001"
  }
}'
```

Orchestra Agent 로그에서 NLU 분석이 시작되는 것을 확인합니다:

```
INFO  orchestra_agent.manager: [Manager] 태스크 처리 시작 task_id=test-manual-001
INFO  orchestra_agent.nlu_engine: [NLU] 분석 완료 type=clarification session=U00001:C00001
```

### 9-2. Communication 큐에 결과 직접 주입

Communication Agent가 Slack으로 결과를 발송하는지 확인합니다.
단, 태스크 컨텍스트(채널·스레드 정보)가 Redis에 없으면 발송이 건너뛰어집니다.

```bash
# 먼저 태스크 컨텍스트 저장
redis-cli SETEX "slack:task:test-comm-001:context" 7200 \
  '{"channel_id":"C0XXXXXXXXX","thread_ts":"","user_id":"U00001","session_id":"U00001:C0XXXXXXXXX"}'

# 결과 메시지 주입
redis-cli RPUSH agent:communication:tasks '{
  "task_id": "test-comm-001",
  "content": "이것은 테스트 결과 메시지입니다.",
  "requires_user_approval": false,
  "agent_name": "test-agent",
  "progress_percent": null
}'
```

`SLACK_CHANNEL`에 설정된 채널에 Bot 메시지가 발송되면 정상입니다.

### 9-3. Communication Agent REST API로 직접 메시지 발송

```bash
curl -X POST http://localhost:8000/send \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "C0XXXXXXXXX",
    "text": "REST API를 통한 테스트 메시지입니다."
  }'
```

### 9-4. 전체 파이프라인 Redis 모니터링

별도 터미널에서 Redis 명령을 실시간으로 모니터링합니다:

```bash
redis-cli MONITOR
```

Slack에서 메시지를 보내면 아래와 같은 명령들이 순서대로 출력됩니다:

```
"RPUSH" "agent:orchestra:tasks" "{...}"       ← Comm Agent가 삽입
"BLPOP" "agent:orchestra:tasks" "5"           ← Orchestra가 수신
"HSET"  "session:..."                          ← 세션 상태 저장
"RPUSH" "agent:communication:tasks" "{...}"   ← Orchestra가 결과 전달
"BLPOP" "agent:communication:tasks" "5"       ← Comm Agent가 수신
```

---

## 10. 트러블슈팅

### Communication Agent — "⏳ 접수" 메시지는 오지만 결과가 없는 경우

Orchestra Agent 로그를 확인합니다:

```bash
# 큐에 태스크가 쌓여 있는지 확인
redis-cli LLEN agent:orchestra:tasks

# 큐 내용 확인
redis-cli LRANGE agent:orchestra:tasks 0 -1
```

Orchestra Agent가 실행 중이지 않거나 NLU 오류가 발생한 경우입니다.

```bash
# Orchestra 헬스체크
curl http://localhost:8001/health
```

---

### "⏳ 접수" 메시지도 오지 않는 경우

Communication Agent가 메시지를 수신하지 못하고 있습니다.

```bash
# Socket Mode 연결 확인
curl http://localhost:8000/health | python -m json.tool
# socket_running: true 이어야 함

# 최근 수신 메시지 확인 (인메모리)
curl http://localhost:8000/messages/recent
```

Slack App의 **Event Subscriptions**에 `message.channels` 이벤트가 등록되어 있는지 확인합니다.

---

### NLU 분석 실패 — JSON 파싱 오류 반복

```
WARNING orchestra_agent.nlu_engine: [NLU] 파싱 실패 (시도 1/3): ...
```

모델이 유효한 JSON을 반환하지 못한 경우입니다. 최대 3회 재시도 후 `clarification` 응답으로 전환됩니다.
`GEMINI_NLU_MODEL`을 안정적인 버전으로 지정합니다:

```bash
export GEMINI_NLU_MODEL=gemini-2.0-flash
```

---

### Redis 연결 실패

```
WARNING slack_agent.fastapi_app: [lifespan] Redis 초기화 실패
```

Redis 미연결 시 Communication Agent는 **폴백 경로**(LLM 분류 → Docker 디스패치)로 동작합니다.
이 경우 Orchestra 파이프라인을 거치지 않습니다.

```bash
# Redis 실행 확인
docker ps | grep redis
redis-cli ping   # PONG이 나와야 함

# REDIS_URL 확인
echo $REDIS_URL
```

---

### Slack API 권한 오류 (missing_scope)

```json
{"error": "missing_scope", "needed_scopes": ["channels:history"]}
```

Slack App의 **OAuth & Permissions → Bot Token Scopes**에 필요한 스코프를 추가한 후
앱을 재설치합니다 (**Reinstall to Workspace**).

---

### Socket Mode 연결 끊김

```
ERROR slack_bolt: Failed to connect to Slack
```

`SLACK_APP_TOKEN`이 올바른지, Socket Mode가 활성화되어 있는지 확인합니다:

1. [https://api.slack.com/apps](https://api.slack.com/apps) → 앱 선택
2. **Socket Mode** → **Enable Socket Mode** ON 확인
3. **App-Level Tokens**에서 `connections:write` 스코프가 있는 토큰 사용 확인
