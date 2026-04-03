"""
Orchestra Agent FastAPI 서버
- POST /results  : 하위 에이전트로부터 결과 수신
- GET  /health   : 시스템 헬스 조회
- GET  /agents   : 등록된 에이전트 목록 조회
- GET  /agents/{name}/health : 특정 에이전트 헬스 조회
- POST /agents/{name}/reset  : Circuit Breaker 수동 초기화

Lifespan 백그라운드:
    - OrchestraManager.listen_tasks() — BLPOP 기반 태스크 감시
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .health_monitor import HealthMonitor
from .manager import OrchestraManager
from .nlu_engine import build_nlu_engine
from .state_manager import StateManager


# FastAPI request body models (Pydantic) ─────────────────────────────────────

class AgentResultErrorBody(BaseModel):
    code: str
    message: str
    traceback: str | None = None


class AgentResultBody(BaseModel):
    """POST /results 요청 바디 — 하위 에이전트 실행 결과."""
    task_id: str
    status: str
    result_data: dict[str, Any] = {}
    error: AgentResultErrorBody | None = None
    usage_stats: dict[str, Any] = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("orchestra_agent.main")


# ── Application Context ────────────────────────────────────────────────────────

class _AppContext:
    manager: OrchestraManager
    state_manager: StateManager
    health_monitor: HealthMonitor
    listen_task: asyncio.Task[None] | None = None


_ctx = _AppContext()


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 수명 주기 관리: 초기화 → 백그라운드 실행 → 종료."""
    logger.info("[Lifespan] Orchestra Agent 시작")

    # 컴포넌트 초기화
    _ctx.state_manager = StateManager()
    await _ctx.state_manager.init_postgres()

    _ctx.health_monitor = HealthMonitor()

    nlu_engine = build_nlu_engine()
    _ctx.manager = OrchestraManager(
        nlu_engine=nlu_engine,
        state_manager=_ctx.state_manager,
        health_monitor=_ctx.health_monitor,
    )

    # 백그라운드 태스크: BLPOP 태스크 감시 루프
    _ctx.listen_task = asyncio.create_task(
        _ctx.manager.listen_tasks(),
        name="orchestra_listen_tasks",
    )
    logger.info("[Lifespan] listen_tasks 백그라운드 태스크 시작됨")

    yield

    # 종료 처리
    logger.info("[Lifespan] Orchestra Agent 종료 시작")
    if _ctx.listen_task and not _ctx.listen_task.done():
        _ctx.listen_task.cancel()
        try:
            await _ctx.listen_task
        except asyncio.CancelledError:
            pass

    await _ctx.state_manager.close()
    logger.info("[Lifespan] Orchestra Agent 종료 완료")


# ── FastAPI 앱 생성 ────────────────────────────────────────────────────────────

app = FastAPI(
    title="Orchestra Agent",
    version="1.0.0",
    description="AI 에이전트 오케스트라 지휘자 — NLU → Dispatch → Monitor",
    lifespan=lifespan,
)


# ── 엔드포인트 ──────────────────────────────────────────────────────────────────

@app.post("/results", status_code=status.HTTP_202_ACCEPTED)
async def receive_result(result: AgentResultBody) -> dict[str, str]:
    """
    하위 에이전트로부터 실행 결과를 수신합니다.
    결과는 `orchestra:results:{task_id}` Redis 큐에 push됩니다.
    """
    try:
        await _ctx.manager.receive_agent_result(result.model_dump())
        return {"status": "accepted", "task_id": result.task_id}
    except Exception as exc:
        logger.error("[/results] 결과 수신 실패: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"결과 처리 실패: {exc}",
        )


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """시스템 전체 헬스 상태를 반환합니다."""
    try:
        system_health = await _ctx.health_monitor.get_system_health()
        listen_task_running = (
            _ctx.listen_task is not None
            and not _ctx.listen_task.done()
        )
        return {
            "status": "ok",
            "listen_task_running": listen_task_running,
            "agents": system_health,
        }
    except Exception as exc:
        logger.error("[/health] 헬스 조회 실패: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "detail": str(exc)},
        )


@app.get("/agents")
async def list_agents() -> dict[str, Any]:
    """등록된 에이전트 목록과 가용 에이전트를 반환합니다."""
    try:
        available = await _ctx.health_monitor.get_available_agents()
        system_health = await _ctx.health_monitor.get_system_health()
        return {
            "available": available,
            "all": system_health,
        }
    except Exception as exc:
        logger.error("[/agents] 에이전트 목록 조회 실패: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@app.get("/agents/{agent_name}/health")
async def get_agent_health(agent_name: str) -> dict[str, Any]:
    """특정 에이전트의 헬스 정보를 반환합니다."""
    try:
        health = await _ctx.health_monitor.get_agent_health(agent_name)
        if not health:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"에이전트 '{agent_name}'를 찾을 수 없습니다.",
            )
        return health
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@app.post("/agents/{agent_name}/reset", status_code=status.HTTP_200_OK)
async def reset_circuit_breaker(agent_name: str) -> dict[str, str]:
    """
    특정 에이전트의 Circuit Breaker를 수동으로 초기화합니다.
    MAINTENANCE → IDLE 상태로 복구됩니다.
    """
    try:
        await _ctx.health_monitor.reset_circuit_breaker(agent_name)
        return {"status": "reset", "agent": agent_name}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


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
