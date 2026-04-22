"""
Orchestra Agent FastAPI 서버

엔드포인트 목록:
  [시스템]
  GET  /health                        시스템 전체 헬스 조회
  GET  /queue/status                  Redis 에이전트 큐 대기 수 조회

  [에이전트 결과·로그 수신 - 하위 에이전트용]
  POST /results                       하위 에이전트 실행 결과 수신
  POST /logs                          에이전트 활동 로그 수신

  [태스크]
  POST /tasks                         사용자 텍스트 → NLU → 에이전트 디스패치
  GET  /tasks/{task_id}               태스크 상태 조회

  [NLU]
  POST /nlu/analyze                   디스패치 없이 의도 분석만 수행

  [직접 디스패치]
  POST /dispatch                      NLU 없이 특정 에이전트로 직접 태스크 전달

  [에이전트 관리 (하위 에이전트 자기등록·헬스비트용)]
  GET  /agents                        등록된 에이전트 전체 목록 + 가용 목록
  POST /agents                        새 에이전트 레지스트리 자동 등록
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

  [관리자 GUI - /admin 접두사]
  → admin_router.py 참조 (대시보드·에이전트 생명주기·권한·큐·태스크·로그·세션·사용자·시스템 메트릭)
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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .app_context import ctx
from .admin_router import router as admin_router
from .health_monitor import HealthMonitor
from .manager import OrchestraManager
from .nlu_engine import build_nlu_engine
from .state_manager import StateManager
from .agent_builder_handler import AgentBuilderHandler
from .registry import AgentRegistry
from .marketplace_handler import MarketplaceHandler

load_dotenv(encoding="utf-8", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("orchestra_agent.main")

_KNOWN_AGENTS = [
    "coding_agent",
    "archive_agent",
    "research_agent",
    "calendar_agent",
    "file_agent",
    "communication_agent",
    "sandbox_agent",
]

# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 수명 주기 관리: 초기화 → 백그라운드 실행 → 종료."""
    logger.info("[Lifespan] Orchestra Agent 시작")

    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379").replace(
        "localhost", "127.0.0.1"
    )
    logger.info("[Lifespan] Redis 연결 시도: %s", redis_url)

    ctx.redis_client = aioredis.from_url(
        redis_url, decode_responses=True, socket_timeout=60.0
    )
    try:
        await ctx.redis_client.ping()
        logger.info("[Lifespan] Redis 연결 성공")
    except Exception as exc:
        logger.error("[Lifespan] Redis 연결 실패: %s", exc)
        raise RuntimeError(f"Redis 연결 실패: {exc}")

    ctx.state_manager = StateManager(redis_client=ctx.redis_client)
    ctx.health_monitor = HealthMonitor(redis_client=ctx.redis_client)
    ctx.builder_handler = AgentBuilderHandler()
    ctx.registry = AgentRegistry()
    ctx.marketplace = MarketplaceHandler(
        ctx.builder_handler, ctx.registry, ctx.health_monitor
    )

    try:
        nlu_engine = build_nlu_engine()
        logger.info("[Lifespan] NLU 엔진 생성 완료 (%s)", nlu_engine.__class__.__name__)
        if not await nlu_engine.validate():
            raise RuntimeError("LLM API 연결 검증 실패")
    except Exception as exc:
        logger.error("[Lifespan] NLU 초기화 실패: %s", exc)
        raise RuntimeError(f"NLU 초기화 실패: {exc}")

    ctx.manager = OrchestraManager(
        redis_client=ctx.redis_client,
        nlu_engine=nlu_engine,
        state_manager=ctx.state_manager,
        health_monitor=ctx.health_monitor,
    )

    # 기본 에이전트 레지스트리 등록
    _AGENT_CONFIGS = {
        "communication_agent": (["send_message", "ask_clarification"], "long_running"),
        "coding_agent": (["execute_tdd_cycle", "review_code"], "long_running"),
        "archive_agent": (
            ["list_databases", "get_page", "create_page", "search"],
            "long_running",
        ),
        "sandbox_agent": (["run_code", "install_package"], "long_running"),
        "file_agent": (["read_file", "write_file", "search_files"], "ephemeral"),
        "research_agent": (["search_and_report"], "ephemeral"),
        "calendar_agent": (["create_event", "query_events"], "ephemeral"),
    }
    for agent_name, (caps, ltype) in _AGENT_CONFIGS.items():
        await ctx.health_monitor.register_agent(agent_name, caps, lifecycle_type=ltype)

    ctx.listen_task = asyncio.create_task(
        ctx.manager.listen_tasks(), name="orchestra_listen_tasks"
    )
    ctx.monitor_task = asyncio.create_task(
        ctx.health_monitor.monitor_loop(interval=30), name="orchestra_health_monitor"
    )

    yield

    for t in [ctx.listen_task, ctx.monitor_task]:
        if t and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    await ctx.state_manager.close()
    await ctx.redis_client.aclose()


# ── FastAPI 앱 ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Orchestra Agent API",
    version="2.0.0",
    description=(
        "AI 에이전트 오케스트라 지휘자 — 외부 제어 및 관리자 API\n\n"
        "관리자 GUI 전용 엔드포인트는 `/admin` 접두사를 사용합니다."
    ),
    lifespan=lifespan,
)

# CORS — GUI 도구(Electron, 웹 대시보드 등)에서 접근 가능하도록 설정
_CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 관리자 라우터 포함
app.include_router(admin_router)

# ── Request / Response 모델 ────────────────────────────────────────────────────


class AgentLogBody(BaseModel):
    agent_name: str
    action: str
    message: str
    task_id: str | None = None
    session_id: str | None = None
    payload: dict[str, Any] | None = None


class AgentResultErrorBody(BaseModel):
    code: str
    message: str
    traceback: str | None = None


class AgentResultBody(BaseModel):
    task_id: str
    agent: str = ""
    status: str
    result_data: dict[str, Any] = {}
    error: AgentResultErrorBody | None = None
    usage_stats: dict[str, Any] = {}


class SubmitTaskBody(BaseModel):
    content: str = Field(..., description="사용자 자연어 입력")
    user_id: str = Field(default="api-user")
    channel_id: str = Field(default="api")
    session_id: str | None = None


class SubmitMarketplaceInstallBody(BaseModel):
    item_url: str = Field(..., description="마켓플레이스 에이전트 매니페스트 JSON URL")
    user_id: str = Field(default="admin")


class NLUAnalyzeBody(BaseModel):
    text: str
    session_id: str = "nlu-session"
    user_id: str = "api-user"
    include_context: bool = False


class DirectDispatchBody(BaseModel):
    agent_name: str
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    content: str = ""
    user_id: str = "api-user"
    channel_id: str = "api"
    priority: str = "MEDIUM"
    timeout: int = 300


class RegisterAgentBody(BaseModel):
    agent_name: str
    capabilities: list[str] = Field(default_factory=list)
    lifecycle_type: str = "long_running"
    nlu_description: str = ""


class HeartbeatBody(BaseModel):
    status: str = "IDLE"
    current_tasks: int = 0
    version: str = "1.0.0"
    capabilities: list[str] = Field(default_factory=list)
    max_concurrency: int = 1
    nlu_description: str = ""


class UpdateUserProfileBody(BaseModel):
    name: str | None = None
    style_pref: dict[str, str] | None = None


# ── 시스템 엔드포인트 ──────────────────────────────────────────────────────────


@app.get("/health", tags=["시스템"])
async def health_check() -> dict[str, Any]:
    try:
        redis_ok = await ctx.redis_client.ping()
    except Exception:
        redis_ok = False
    system_health = await ctx.health_monitor.get_system_health()
    listen_running = ctx.listen_task is not None and not ctx.listen_task.done()
    return {
        "status": "ok" if redis_ok and listen_running else "degraded",
        "redis_connected": bool(redis_ok),
        "listen_task_running": listen_running,
        "agents": system_health,
    }


@app.get("/queue/status", tags=["시스템"])
async def queue_status() -> dict[str, Any]:
    """모든 에이전트 큐의 대기 메시지 수를 반환합니다."""
    return await ctx.health_monitor.get_all_queues_status()


# ── 하위 에이전트 수신 엔드포인트 ────────────────────────────────────────────


@app.post("/results", tags=["에이전트"])
async def receive_result(result: AgentResultBody) -> dict[str, Any]:
    await ctx.manager.receive_agent_result(result.model_dump())
    return {"status": "accepted", "task_id": result.task_id}


@app.post("/logs", tags=["에이전트"])
async def receive_log(body: AgentLogBody) -> dict[str, Any]:
    # 대용량 로그로 인한 오케스트라 DB 부하 방지 (Hybrid Architecture)
    message = body.message if len(body.message) <= 1000 else body.message[:1000] + "...(truncated)"
    payload = body.payload
    
    if payload:
        payload_str = json.dumps(payload, ensure_ascii=False)
        if len(payload_str) > 2000:
            payload = {"_truncated_": True, "note": "Payload too large to be stored in central DB."}
            
    await ctx.state_manager.add_agent_log(
        body.agent_name,
        body.action,
        message,
        body.task_id,
        body.session_id,
        payload,
    )
    return {"status": "logged"}


# ── 태스크 엔드포인트 ──────────────────────────────────────────────────────────


@app.post("/tasks", tags=["태스크"])
async def submit_task(body: SubmitTaskBody) -> dict[str, Any]:
    """사용자 자연어 입력을 NLU로 분석하여 적절한 에이전트에 디스패치합니다."""
    task_id = str(uuid.uuid4())
    session_id = body.session_id or f"{body.user_id}:{body.channel_id}"
    task = {
        "task_id": task_id,
        "session_id": session_id,
        "requester": {"user_id": body.user_id, "channel_id": body.channel_id},
        "content": body.content,
        "source": "api",
    }
    await ctx.redis_client.rpush(
        "agent:orchestra:tasks", json.dumps(task, ensure_ascii=False)
    )
    return {"status": "accepted", "task_id": task_id, "session_id": session_id}


@app.get("/tasks/{task_id}", tags=["태스크"])
async def get_task(task_id: str) -> dict[str, Any]:
    state = await ctx.state_manager.get_task_state(task_id)
    return (
        {"task_id": task_id, **state}
        if state
        else {"task_id": task_id, "status": "NOT_FOUND"}
    )


# ── NLU 분석 ──────────────────────────────────────────────────────────────────


@app.post("/nlu/analyze", tags=["NLU"])
async def nlu_analyze(body: NLUAnalyzeBody) -> dict[str, Any]:
    """디스패치 없이 NLU 의도 분석 결과만 반환합니다 (개발·테스트용)."""
    context: list[dict[str, Any]] = []
    if body.include_context:
        context = await ctx.state_manager.build_context_for_llm(
            body.session_id, body.user_id
        )

    agent_capabilities = await ctx.health_monitor.get_nlu_capabilities() or None
    result = await ctx.manager._nlu.analyze(
        body.text,
        body.session_id,
        context,
        agent_capabilities=agent_capabilities,
    )
    return result.model_dump()


# ── 직접 디스패치 ──────────────────────────────────────────────────────────────


@app.post("/dispatch", tags=["태스크"])
async def direct_dispatch(body: DirectDispatchBody) -> dict[str, Any]:
    """NLU를 거치지 않고 특정 에이전트에 직접 태스크를 전달합니다."""
    ready, reason = await ctx.health_monitor.is_agent_ready(body.agent_name)
    if not ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"에이전트 '{body.agent_name}' 사용 불가: {reason}",
        )

    task_id = str(uuid.uuid4())
    dispatch_msg = {
        "version": "1.1",
        "task_id": task_id,
        "session_id": f"{body.user_id}:{body.channel_id}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "requester": {"user_id": body.user_id, "channel_id": body.channel_id},
        "content": body.content,
        "agent": body.agent_name,
        "action": body.action,
        "params": body.params,
        "priority": body.priority,
        "timeout": body.timeout,
        "retry_info": {"count": 0, "max_retries": 3, "reason": None},
        "metadata": {},
    }
    await ctx.redis_client.rpush(
        f"agent:{body.agent_name}:tasks",
        json.dumps(dispatch_msg, ensure_ascii=False),
    )

    # 결과 대기 (timeout 초)
    result = await ctx.manager.wait_for_result(task_id, timeout=body.timeout)
    return {"task_id": task_id, "agent": body.agent_name, **result}


# ── 에이전트 관리 (자기 등록·하트비트용) ──────────────────────────────────────


@app.get("/agents", tags=["에이전트 관리"])
async def list_agents() -> dict[str, Any]:
    return {
        "available": await ctx.health_monitor.get_available_agents(),
        "all": await ctx.health_monitor.get_system_health(),
    }


@app.post("/agents", tags=["에이전트 관리"], status_code=status.HTTP_201_CREATED)
async def register_agent(body: RegisterAgentBody) -> dict[str, Any]:
    """에이전트 시작 시 자기 등록 엔드포인트."""
    await ctx.health_monitor.register_agent(
        body.agent_name,
        body.capabilities,
        lifecycle_type=body.lifecycle_type,
        nlu_description=body.nlu_description,
    )
    return {"status": "registered", "agent_name": body.agent_name}


@app.delete("/agents/{agent_name}", tags=["에이전트 관리"])
async def deregister_agent(agent_name: str) -> dict[str, Any]:
    """에이전트 종료 시 자기 해제 엔드포인트."""
    await ctx.redis_client.hdel("agents:registry", agent_name)
    return {"status": "deregistered", "agent_name": agent_name}


@app.get("/agents/{agent_name}/health", tags=["에이전트 관리"])
async def get_agent_health(agent_name: str) -> dict[str, Any]:
    health = await ctx.redis_client.hgetall(f"agent:{agent_name}:health")
    if not health:
        raise HTTPException(
            status_code=404, detail=f"에이전트 '{agent_name}'의 헬스 데이터가 없습니다."
        )
    return {"agent_name": agent_name, "health": health}


@app.put("/agents/{agent_name}/heartbeat", tags=["에이전트 관리"])
async def update_heartbeat(agent_name: str, body: HeartbeatBody) -> dict[str, Any]:
    """에이전트 하트비트 갱신 — 에이전트가 주기적으로 호출합니다."""
    mapping: dict[str, str] = {
        "agent_id": agent_name,
        "status": body.status,
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        "version": body.version,
        "current_tasks": str(body.current_tasks),
        "max_concurrency": str(body.max_concurrency),
    }
    if body.nlu_description:
        mapping["nlu_description"] = body.nlu_description
    if body.capabilities:
        mapping["capabilities"] = ",".join(body.capabilities)

    await ctx.redis_client.hset(f"agent:{agent_name}:health", mapping=mapping)
    await ctx.redis_client.expire(f"agent:{agent_name}:health", 60)
    return {"status": "updated", "agent_name": agent_name}


@app.get("/agents/{agent_name}/circuit", tags=["에이전트 관리"])
async def get_circuit(agent_name: str) -> dict[str, Any]:
    failures = int(await ctx.redis_client.get(f"circuit:{agent_name}:failures") or 0)
    return {
        "agent_name": agent_name,
        "failures": failures,
        "threshold": 3,
        "is_open": failures >= 3,
    }


@app.post("/agents/{agent_name}/reset", tags=["에이전트 관리"])
async def reset_circuit(agent_name: str) -> dict[str, Any]:
    await ctx.health_monitor.reset_circuit_breaker(agent_name)
    return {"status": "reset", "agent_name": agent_name}


@app.post("/marketplace/install", tags=["에이전트 관리"])
async def install_from_marketplace(body: SubmitMarketplaceInstallBody):
    """외부 마켓플레이스로부터 에이전트를 내려받아 빌드 및 등록합니다."""
    task_id = f"mkt-{str(uuid.uuid4())[:8]}"
    result = await ctx.marketplace.install_from_marketplace(body.item_url, task_id)
    if result.get("status") == "FAILED":
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ── 세션 엔드포인트 ────────────────────────────────────────────────────────────


@app.get("/sessions/{session_id}", tags=["세션"])
async def get_session(session_id: str) -> dict[str, Any]:
    state = await ctx.redis_client.hgetall(f"session:{session_id}:state")
    return {"session_id": session_id, "state": state}


@app.get("/sessions/{session_id}/history", tags=["세션"])
async def get_session_history(
    session_id: str,
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    history = await ctx.state_manager.get_session_history(session_id, limit=limit)
    return {"session_id": session_id, "count": len(history), "history": history}


@app.delete("/sessions/{session_id}", tags=["세션"])
async def delete_session(session_id: str) -> dict[str, Any]:
    await ctx.state_manager.delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}


# ── 사용자 프로필 ──────────────────────────────────────────────────────────────


@app.get("/users/{user_id}/profile", tags=["사용자"])
async def get_profile(user_id: str) -> dict[str, Any]:
    return await ctx.state_manager.get_user_profile(user_id)


@app.put("/users/{user_id}/profile", tags=["사용자"])
async def update_profile(user_id: str, body: UpdateUserProfileBody) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.style_pref is not None:
        updates["style_pref"] = body.style_pref
    if not updates:
        raise HTTPException(status_code=400, detail="수정할 필드가 없습니다.")
    await ctx.state_manager.update_user_profile(user_id, updates)
    return await ctx.state_manager.get_user_profile(user_id)


# ── 진입점 ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
