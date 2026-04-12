"""
Orchestra Agent FastAPI 서버

엔드포인트 목록:
  [시스템]
  GET  /health                        시스템 전체 헬스 조회
  GET  /queue/status                  Redis 에이전트 큐 대기 수 조회

  [에이전트 결과 수신 - 하위 에이전트용]
  POST /results                       하위 에이전트 실행 결과 수신

  [태스크]
  POST /tasks                         사용자 텍스트 → NLU → 에이전트 디스패치
  GET  /tasks/{task_id}               태스크 상태 조회

  [NLU]
  POST /nlu/analyze                   디스패치 없이 의도 분석만 수행

  [직접 디스패치]
  POST /dispatch                      NLU 없이 특정 에이전트로 직접 태스크 전달

  [에이전트 관리]
  GET  /agents                        등록된 에이전트 전체 목록 + 가용 목록
  POST /agents                        새 에이전트 레지스트리 등록
  DELETE /agents/{agent_name}         에이전트 레지스트리 해제
  GET  /agents/{agent_name}/health    특정 에이전트 헬스 조회
  PUT  /agents/{agent_name}/heartbeat 에이전트 하트비트 갱신
  GET  /agents/{agent_name}/circuit   Circuit Breaker 상태 조회
  POST /agents/{agent_name}/reset     Circuit Breaker 수동 초기화

  [세션]
  GET  /sessions/{session_id}         세션 상태 조회
  GET  /sessions/{session_id}/history 세션 대화 이력 조회
  DELETE /sessions/{session_id}       세션 초기화

  [사용자 프로필]
  GET  /users/{user_id}/profile       사용자 프로필 조회
  PUT  /users/{user_id}/profile       사용자 프로필 수정
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .health_monitor import HealthMonitor
from .manager import OrchestraManager
from .nlu_engine import build_nlu_engine
from .state_manager import StateManager

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("orchestra_agent.main")

# 에이전트 큐 키 접두사
_AGENT_QUEUE_PREFIX = "agent:{name}:tasks"
_KNOWN_AGENTS = [
    "coding_agent",
    "archive_agent",
    "research_agent",
    "calendar_agent",
    "file_agent",
    "communication_agent",
    "sandbox_agent",
]


# ── Request / Response 모델 ────────────────────────────────────────────────────


class AgentResultErrorBody(BaseModel):
    code: str
    message: str
    traceback: str | None = None


class AgentResultBody(BaseModel):
    """POST /results — 하위 에이전트 실행 결과."""

    task_id: str
    agent: str = ""
    status: str
    result_data: dict[str, Any] = {}
    error: AgentResultErrorBody | None = None
    usage_stats: dict[str, Any] = {}


class SubmitTaskBody(BaseModel):
    """POST /tasks — 사용자 텍스트 기반 태스크 제출."""

    content: str = Field(..., description="사용자 자연어 입력")
    user_id: str = Field(default="api-user", description="요청 사용자 ID")
    channel_id: str = Field(default="api", description="채널 ID")
    session_id: str | None = Field(
        default=None, description="세션 ID (없으면 자동 생성)"
    )


class NLUAnalyzeBody(BaseModel):
    """POST /nlu/analyze — NLU 분석 전용."""

    text: str = Field(..., description="분석할 자연어 텍스트")
    session_id: str = Field(
        default="nlu-session", description="컨텍스트 참조용 세션 ID"
    )
    user_id: str = Field(
        default="api-user", description="사용자 ID (컨텍스트 조회 시 사용)"
    )
    include_context: bool = Field(
        default=False, description="세션 이력을 컨텍스트로 포함할지 여부"
    )


class DirectDispatchBody(BaseModel):
    """POST /dispatch — 특정 에이전트 직접 디스패치."""

    agent_name: str = Field(..., description="대상 에이전트 이름")
    action: str = Field(..., description="에이전트가 실행할 액션")
    params: dict[str, Any] = Field(default_factory=dict, description="액션 파라미터")
    user_id: str = Field(default="api-user")
    channel_id: str = Field(default="api")
    priority: str = Field(
        default="MEDIUM", description="LOW | MEDIUM | HIGH | CRITICAL"
    )
    timeout: int = Field(default=300, description="타임아웃 (초)")


class RegisterAgentBody(BaseModel):
    """POST /agents — 에이전트 등록."""

    agent_name: str = Field(..., description="에이전트 고유 이름")
    capabilities: list[str] = Field(
        default_factory=list, description="에이전트 능력 목록"
    )


class HeartbeatBody(BaseModel):
    """PUT /agents/{agent_name}/heartbeat — 에이전트 하트비트."""

    status: str = Field(default="IDLE", description="IDLE | BUSY | MAINTENANCE | ERROR")
    current_tasks: int = Field(default=0, description="현재 처리 중인 태스크 수")
    version: str = Field(default="1.0.0")
    capabilities: list[str] = Field(default_factory=list)
    max_concurrency: int = Field(default=1)


class UpdateUserProfileBody(BaseModel):
    """PUT /users/{user_id}/profile — 사용자 프로필 수정."""

    name: str | None = None
    style_pref: dict[str, str] | None = None


# ── Application Context ────────────────────────────────────────────────────────


class _AppContext:
    manager: OrchestraManager
    state_manager: StateManager
    health_monitor: HealthMonitor
    redis_client: aioredis.Redis
    listen_task: asyncio.Task[None] | None = None
    monitor_task: asyncio.Task[None] | None = None


_ctx = _AppContext()


# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 수명 주기 관리: 초기화 → 백그라운드 실행 → 종료."""
    logger.info("[Lifespan] Orchestra Agent 시작")

    # 1. Redis 연결 (localhost → 127.0.0.1 보정)
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
    if "localhost" in redis_url:
        redis_url = redis_url.replace("localhost", "127.0.0.1")

    logger.info("[Lifespan] Redis 연결 시도: %s", redis_url)
    _ctx.redis_client = aioredis.from_url(
        redis_url,
        decode_responses=True,
        socket_timeout=60.0,
    )
    try:
        await _ctx.redis_client.ping()
        logger.info("[Lifespan] Redis 연결 성공")
    except Exception as exc:
        logger.error("[Lifespan] Redis 연결 실패: %s", exc)
        raise RuntimeError(f"Redis 연결 실패: {exc}")

    # 2. 컴포넌트 초기화
    _ctx.state_manager = StateManager(redis_client=_ctx.redis_client)
    await _ctx.state_manager.init_db()

    _ctx.health_monitor = HealthMonitor(redis_client=_ctx.redis_client)

    # 3. NLU 엔진 초기화 + 검증
    try:
        nlu_engine = build_nlu_engine()
        logger.info("[Lifespan] NLU 엔진 생성 완료 (%s)", nlu_engine.__class__.__name__)
        if not await nlu_engine.validate():
            raise RuntimeError("LLM API 연결 검증 실패")
    except Exception as exc:
        logger.error("[Lifespan] NLU 초기화 실패: %s", exc)
        raise RuntimeError(f"NLU 초기화 실패: {exc}")

    _ctx.manager = OrchestraManager(
        redis_client=_ctx.redis_client,
        nlu_engine=nlu_engine,
        state_manager=_ctx.state_manager,
        health_monitor=_ctx.health_monitor,
    )

    # 4. 알려진 에이전트 사전 등록
    _AGENT_CONFIGS = {
        "communication_agent": (["send_message", "ask_clarification"], "long_running"),
        "coding_agent":        (["execute_tdd_cycle", "review_code"], "long_running"),
        "archive_agent":       (["analyze_task", "create_plan", "update_task", "search_documents", "write_document", "read_document", "sync_documents"], "long_running"),
        "sandbox_agent":       (["run_code", "install_package"], "long_running"),
        "file_agent":          (["read_file", "write_file", "search_files"], "ephemeral"),
        "research_agent":      (["search_and_report"], "ephemeral"),
        "calendar_agent":      (["create_event", "query_events"], "ephemeral"),
    }
    
    for agent_name, (caps, ltype) in _AGENT_CONFIGS.items():
        # 항상 최신 상태로 갱신 (유형 변경 반영 가능)
        await _ctx.health_monitor.register_agent(agent_name, caps, lifecycle_type=ltype)
    logger.info("[Lifespan] 에이전트 레지스트리 초기화 완료 (%d개)", len(_AGENT_CONFIGS))

    # 4. 백그라운드 태스크 시작
    _ctx.listen_task = asyncio.create_task(
        _ctx.manager.listen_tasks(),
        name="orchestra_listen_tasks",
    )

    _ctx.monitor_task = asyncio.create_task(
        _ctx.health_monitor.monitor_loop(interval=30),
        name="orchestra_health_monitor",
    )

    logger.info("[Lifespan] 백그라운드 태스크 시작됨 (listen_tasks, monitor_loop)")

    yield

    # 종료 처리
    logger.info("[Lifespan] Orchestra Agent 종료 시작")
    for t in [_ctx.listen_task, _ctx.monitor_task]:
        if t and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    await _ctx.state_manager.close()
    await _ctx.redis_client.aclose()
    logger.info("[Lifespan] Orchestra Agent 종료 완료")


# ── FastAPI 앱 ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Orchestra Agent API",
    version="2.0.0",
    description="AI 에이전트 오케스트라 지휘자 — 외부 제어 API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ══════════════════════════════════════════════════════════════════════════════
# 시스템
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/health", tags=["시스템"], summary="시스템 헬스 조회")
async def health_check() -> dict[str, Any]:
    """Redis 연결, 백그라운드 루프, 등록 에이전트 상태를 반환합니다."""
    try:
        redis_ok = await _ctx.redis_client.ping()
    except Exception:
        redis_ok = False

    system_health = {}
    try:
        system_health = await _ctx.health_monitor.get_system_health()
    except Exception:
        pass

    listen_running = _ctx.listen_task is not None and not _ctx.listen_task.done()

    return {
        "status": "ok" if redis_ok and listen_running else "degraded",
        "redis_connected": bool(redis_ok),
        "listen_task_running": listen_running,
        "agents": system_health,
    }


@app.get("/queue/status", tags=["시스템"], summary="에이전트 큐 대기 수 조회")
async def queue_status() -> dict[str, Any]:
    """
    각 에이전트의 Redis 태스크 큐(`agent:{name}:tasks`)에 대기 중인 태스크 수를 반환합니다.
    오케스트라 입력 큐(`agent:orchestra:tasks`)도 포함합니다.
    """
    queues: dict[str, int] = {}

    target_agents = ["orchestra"] + _KNOWN_AGENTS
    for name in target_agents:
        key = f"agent:{name}:tasks"
        try:
            count = await _ctx.redis_client.llen(key)
            queues[name] = count
        except Exception:
            queues[name] = -1

    return {"queues": queues, "checked_at": datetime.now(timezone.utc).isoformat()}


# ══════════════════════════════════════════════════════════════════════════════
# 하위 에이전트 결과 수신 (에이전트 내부 호출용)
# ══════════════════════════════════════════════════════════════════════════════


@app.post(
    "/results",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["에이전트 결과"],
    summary="하위 에이전트 실행 결과 수신",
)
async def receive_result(result: AgentResultBody) -> dict[str, str]:
    """
    하위 에이전트가 작업을 완료한 뒤 결과를 POST합니다.
    결과는 `orchestra:results:{task_id}` 큐에 push되어 OrchestraManager가 수신합니다.
    """
    try:
        await _ctx.manager.receive_agent_result(result.model_dump())
        return {"status": "accepted", "task_id": result.task_id}
    except Exception as exc:
        logger.error("[/results] 결과 수신 실패: %s", exc)
        raise HTTPException(status_code=500, detail=f"결과 처리 실패: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# 태스크
# ══════════════════════════════════════════════════════════════════════════════


@app.post(
    "/tasks",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["태스크"],
    summary="사용자 텍스트 기반 태스크 제출",
)
async def submit_task(body: SubmitTaskBody) -> dict[str, str]:
    """
    자연어 텍스트를 받아 NLU 분석 후 적절한 에이전트로 디스패치합니다.
    처리는 백그라운드에서 비동기로 진행되며, task_id로 상태를 추적할 수 있습니다.

    - `session_id` 미입력 시 `{user_id}:{channel_id}` 형식으로 자동 생성됩니다.
    - 결과는 `/tasks/{task_id}` 로 조회합니다.
    """
    task_id = str(uuid.uuid4())
    session_id = body.session_id or f"{body.user_id}:{body.channel_id}"

    task: dict[str, Any] = {
        "task_id": task_id,
        "session_id": session_id,
        "requester": {"user_id": body.user_id, "channel_id": body.channel_id},
        "content": body.content,
        "source": "api",
        "thread_ts": None,
    }

    await _ctx.redis_client.rpush(
        "agent:orchestra:tasks", json.dumps(task, ensure_ascii=False)
    )
    logger.info("[/tasks] 태스크 제출 task_id=%s session=%s", task_id, session_id)

    return {"status": "accepted", "task_id": task_id, "session_id": session_id}


@app.get(
    "/tasks/{task_id}",
    tags=["태스크"],
    summary="태스크 상태 조회",
)
async def get_task(task_id: str) -> dict[str, Any]:
    """
    `task_id`로 태스크의 현재 상태를 조회합니다.

    status 값:
    - `PROCESSING` : NLU 분석 및 에이전트 디스패치 진행 중
    - `PENDING`    : 에이전트 실행 결과 대기 중
    - `COMPLETED`  : 완료
    - `FAILED`     : 실패
    - `NOT_FOUND`  : 해당 task_id 없음 (TTL 만료 포함)
    """
    state = await _ctx.state_manager.get_task_state(task_id)
    if not state:
        return {"task_id": task_id, "status": "NOT_FOUND"}
    return {"task_id": task_id, **state}


# ══════════════════════════════════════════════════════════════════════════════
# NLU
# ══════════════════════════════════════════════════════════════════════════════


@app.post(
    "/nlu/analyze",
    tags=["NLU"],
    summary="의도 분석 전용 (디스패치 없음)",
)
async def nlu_analyze(body: NLUAnalyzeBody) -> dict[str, Any]:
    """
    텍스트를 NLU 엔진으로 분석하고 결과를 반환합니다.
    에이전트 디스패치는 수행하지 않습니다.

    반환 type:
    - `single`          : 단일 에이전트 작업
    - `multi_step`      : 여러 에이전트가 필요한 복합 작업
    - `clarification`   : 정보 부족 — 추가 질문 필요
    - `direct_response` : 에이전트 없이 직접 답변 가능한 일상 대화
    """
    context: list[dict[str, Any]] = []
    if body.include_context:
        try:
            context = await _ctx.state_manager.build_context_for_llm(
                body.session_id, body.user_id
            )
        except Exception:
            pass

    result = await _ctx.manager._nlu.analyze(
        user_text=body.text,
        session_id=body.session_id,
        context=context,
    )
    return result.model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# 직접 디스패치
# ══════════════════════════════════════════════════════════════════════════════


@app.post(
    "/dispatch",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["디스패치"],
    summary="특정 에이전트로 직접 태스크 전달 (NLU 없음)",
)
async def direct_dispatch(body: DirectDispatchBody) -> dict[str, Any]:
    """
    NLU 분석 없이 지정한 에이전트의 특정 액션을 직접 호출합니다.
    에이전트 이름·액션·파라미터를 명시적으로 지정해야 합니다.

    Circuit Breaker가 열려 있으면 `circuit_open: true`를 반환하고 전달하지 않습니다.
    """
    # Circuit Breaker 확인
    cb_open = await _ctx.health_monitor.check_circuit_breaker(body.agent_name)
    if cb_open:
        return {
            "status": "rejected",
            "reason": "circuit_open",
            "agent_name": body.agent_name,
        }

    task_id = str(uuid.uuid4())
    session_id = f"{body.user_id}:{body.channel_id}"

    dispatch: dict[str, Any] = {
        "version": "1.1",
        "task_id": task_id,
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "requester": {"user_id": body.user_id, "channel_id": body.channel_id},
        "agent": body.agent_name,
        "action": body.action,
        "params": body.params,
        "retry_info": {"count": 0, "max_retries": 3, "reason": None},
        "priority": body.priority,
        "timeout": body.timeout,
        "metadata": {"step_info": {}, "requires_user_approval": False},
    }

    queue_key = f"agent:{body.agent_name}:tasks"
    await _ctx.redis_client.rpush(queue_key, json.dumps(dispatch, ensure_ascii=False))

    await _ctx.state_manager.update_task_state(
        task_id,
        {
            "status": "PENDING",
            "session_id": session_id,
            "agent": body.agent_name,
            "action": body.action,
        },
    )

    logger.info(
        "[/dispatch] 직접 디스패치 agent=%s action=%s task_id=%s",
        body.agent_name,
        body.action,
        task_id,
    )

    return {
        "status": "accepted",
        "task_id": task_id,
        "agent_name": body.agent_name,
        "action": body.action,
        "queue_key": queue_key,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 에이전트 관리
# ══════════════════════════════════════════════════════════════════════════════


@app.get(
    "/agents",
    tags=["에이전트 관리"],
    summary="등록된 에이전트 전체 목록 + 가용 목록",
)
async def list_agents() -> dict[str, Any]:
    """레지스트리에 등록된 모든 에이전트와 현재 가용한 에이전트 목록을 반환합니다."""
    available = await _ctx.health_monitor.get_available_agents()
    system_health = await _ctx.health_monitor.get_system_health()
    return {"available": available, "all": system_health}


@app.post(
    "/agents",
    status_code=status.HTTP_201_CREATED,
    tags=["에이전트 관리"],
    summary="에이전트 레지스트리 등록",
)
async def register_agent(body: RegisterAgentBody) -> dict[str, str]:
    """
    새 에이전트를 시스템 레지스트리(`agents:registry`)에 등록합니다.
    이미 등록된 에이전트를 재등록하면 capabilities가 갱신됩니다.
    """
    await _ctx.health_monitor.register_agent(body.agent_name, body.capabilities)
    return {"status": "registered", "agent_name": body.agent_name}


@app.delete(
    "/agents/{agent_name}",
    tags=["에이전트 관리"],
    summary="에이전트 레지스트리 해제",
)
async def unregister_agent(agent_name: str) -> dict[str, str]:
    """레지스트리에서 에이전트를 제거하고 관련 헬스·Circuit Breaker 데이터를 삭제합니다."""
    await _ctx.redis_client.hdel("agents:registry", agent_name)
    await _ctx.redis_client.delete(f"agent:{agent_name}:health")
    await _ctx.redis_client.delete(f"circuit:{agent_name}:failures")
    logger.info("[/agents] 에이전트 해제: %s", agent_name)
    return {"status": "unregistered", "agent_name": agent_name}


@app.get(
    "/agents/{agent_name}/health",
    tags=["에이전트 관리"],
    summary="특정 에이전트 헬스 조회",
)
async def get_agent_health(agent_name: str) -> dict[str, Any]:
    """Redis에 저장된 특정 에이전트의 헬스 데이터를 반환합니다."""
    health = await _ctx.health_monitor.get_agent_health(agent_name)
    if not health:
        raise HTTPException(
            status_code=404, detail=f"에이전트 '{agent_name}' 를 찾을 수 없습니다."
        )

    ready, reason = await _ctx.health_monitor.is_agent_ready(agent_name)
    return {**health, "ready": ready, "ready_reason": reason}


@app.put(
    "/agents/{agent_name}/heartbeat",
    tags=["에이전트 관리"],
    summary="에이전트 하트비트 갱신",
)
async def update_heartbeat(agent_name: str, body: HeartbeatBody) -> dict[str, str]:
    """
    에이전트가 주기적으로 자신의 상태를 보고할 때 사용합니다.
    `agent:{agent_name}:health` Redis Hash를 갱신하고 하트비트 시각을 기록합니다.
    하트비트가 30초 이상 없으면 HealthMonitor가 해당 에이전트를 INACTIVE로 간주합니다.
    """
    health_data = {
        "status": body.status,
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        "version": body.version,
        "current_tasks": str(body.current_tasks),
        "max_concurrency": str(body.max_concurrency),
        "capabilities": json.dumps(body.capabilities, ensure_ascii=False),
    }
    await _ctx.redis_client.hset(f"agent:{agent_name}:health", mapping=health_data)
    # 하트비트 키 TTL: 60초 (2배 여유)
    await _ctx.redis_client.expire(f"agent:{agent_name}:health", 60)
    return {"status": "updated", "agent_name": agent_name}


@app.get(
    "/agents/{agent_name}/circuit",
    tags=["에이전트 관리"],
    summary="Circuit Breaker 상태 조회",
)
async def get_circuit_breaker(agent_name: str) -> dict[str, Any]:
    """에이전트의 Circuit Breaker 실패 횟수와 개방 여부를 반환합니다."""
    raw = await _ctx.redis_client.get(f"circuit:{agent_name}:failures")
    failures = int(raw or 0)
    ttl = await _ctx.redis_client.ttl(f"circuit:{agent_name}:failures")
    is_open = await _ctx.health_monitor.check_circuit_breaker(agent_name)
    return {
        "agent_name": agent_name,
        "failures": failures,
        "is_open": is_open,
        "threshold": 3,
        "window_sec": 300,
        "ttl_remaining": ttl if ttl > 0 else None,
    }


@app.post(
    "/agents/{agent_name}/reset",
    tags=["에이전트 관리"],
    summary="Circuit Breaker 수동 초기화",
)
async def reset_circuit_breaker(agent_name: str) -> dict[str, str]:
    """Circuit Breaker를 초기화하고 에이전트 상태를 MAINTENANCE → IDLE로 복구합니다."""
    await _ctx.health_monitor.reset_circuit_breaker(agent_name)
    return {"status": "reset", "agent_name": agent_name}


# ══════════════════════════════════════════════════════════════════════════════
# 세션
# ══════════════════════════════════════════════════════════════════════════════


@app.get(
    "/sessions/{session_id}",
    tags=["세션"],
    summary="세션 상태 조회",
)
async def get_session(session_id: str) -> dict[str, Any]:
    """
    Redis에 저장된 세션의 상태 정보를 반환합니다.
    세션 TTL은 2시간이며, 만료된 세션은 `NOT_FOUND`를 반환합니다.
    """
    state = await _ctx.redis_client.hgetall(f"session:{session_id}:state")
    if not state:
        return {"session_id": session_id, "status": "NOT_FOUND"}
    return {"session_id": session_id, **state}


@app.get(
    "/sessions/{session_id}/history",
    tags=["세션"],
    summary="세션 대화 이력 조회",
)
async def get_session_history(
    session_id: str,
    limit: int = Query(
        default=20, ge=1, le=100, description="반환할 메시지 수 (최근 순)"
    ),
) -> dict[str, Any]:
    """
    세션의 대화 이력을 최신 순으로 반환합니다.
    슬라이딩 윈도우(최대 20개) 내에서 조회합니다.
    """
    raw_messages = await _ctx.redis_client.lrange(
        f"session:{session_id}:messages", -limit, -1
    )
    messages = [json.loads(m) for m in raw_messages]
    return {
        "session_id": session_id,
        "count": len(messages),
        "messages": messages,
    }


@app.delete(
    "/sessions/{session_id}",
    tags=["세션"],
    summary="세션 초기화",
)
async def delete_session(session_id: str) -> dict[str, str]:
    """세션 상태와 대화 이력을 Redis에서 삭제합니다."""
    deleted_state = await _ctx.redis_client.delete(f"session:{session_id}:state")
    deleted_msgs = await _ctx.redis_client.delete(f"session:{session_id}:messages")
    logger.info(
        "[/sessions] 세션 삭제: %s (state=%d, messages=%d)",
        session_id,
        deleted_state,
        deleted_msgs,
    )
    return {"status": "deleted", "session_id": session_id}


# ══════════════════════════════════════════════════════════════════════════════
# 사용자 프로필
# ══════════════════════════════════════════════════════════════════════════════


@app.get(
    "/users/{user_id}/profile",
    tags=["사용자 프로필"],
    summary="사용자 프로필 조회",
)
async def get_user_profile(user_id: str) -> dict[str, Any]:
    """사용자 프로필(이름, 응답 스타일 설정)을 조회합니다. 없으면 기본값으로 생성됩니다."""
    profile = await _ctx.state_manager.get_user_profile(user_id)
    return {"user_id": user_id, **profile}


@app.put(
    "/users/{user_id}/profile",
    tags=["사용자 프로필"],
    summary="사용자 프로필 수정",
)
async def update_user_profile(
    user_id: str, body: UpdateUserProfileBody
) -> dict[str, str]:
    """
    사용자 이름과 응답 스타일 설정을 수정합니다.
    `style_pref`는 NLU 프롬프트의 Persona 지침에 반영됩니다.

    style_pref 예시:
    ```json
    {
      "tone": "간결하고 직설적임",
      "language": "한국어",
      "detail_level": "핵심 요약 위주"
    }
    ```
    """
    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.style_pref is not None:
        updates["style_pref"] = body.style_pref
    if not updates:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다.")
    await _ctx.state_manager.update_user_profile(user_id, updates)
    return {"status": "updated", "user_id": user_id}


# ── 진입점 ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8001"))
    uvicorn.run(
        "agents.orchestra_agent.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
