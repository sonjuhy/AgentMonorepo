"""
Sandbox Agent FastAPI 서버 (server 모드)
- GET  /health       : 에이전트 상태 및 VM 풀 상태 조회
- POST /execute      : Redis 우회 직접 실행 (개발/테스트용)

Lifespan 백그라운드:
    - SandboxAgent.start()              — VMPool 초기화 및 사전 워밍
    - SandboxRedisListener.listen_tasks()  — BLPOP 큐 감시
    - SandboxRedisListener._heartbeat_loop() — 15초 주기 health 갱신
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, status

from .agent import SandboxAgent
from .models import DirectExecuteRequest
from .redis_listener import SandboxRedisListener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sandbox_agent.fastapi_app")


# ── Application Context ────────────────────────────────────────────────────────

class _AppContext:
    agent: SandboxAgent
    listener: SandboxRedisListener
    listen_task: asyncio.Task[None] | None = None
    heartbeat_task: asyncio.Task[None] | None = None


_ctx = _AppContext()


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 수명 주기: 초기화 → 백그라운드 시작 → 종료."""
    logger.info("[Lifespan] Sandbox Agent 서버 시작")

    _ctx.agent = SandboxAgent()
    await _ctx.agent.start()   # VMPool 초기화 + 사전 워밍

    _ctx.listener = SandboxRedisListener(
        agent=_ctx.agent,
        redis_url=os.environ.get("REDIS_URL"),
        orchestra_url=os.environ.get("ORCHESTRA_URL"),
    )

    _ctx.listen_task = asyncio.create_task(
        _ctx.listener.listen_tasks(),
        name="sandbox_listen_tasks",
    )
    _ctx.heartbeat_task = asyncio.create_task(
        _ctx.listener._heartbeat_loop(),
        name="sandbox_heartbeat",
    )
    logger.info("[Lifespan] 백그라운드 태스크 시작됨 (runtime=%s)", _ctx.agent.runtime)

    yield

    # 종료
    logger.info("[Lifespan] Sandbox Agent 서버 종료 시작")
    for task in (_ctx.listen_task, _ctx.heartbeat_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await _ctx.listener.close()
    await _ctx.agent.shutdown()
    logger.info("[Lifespan] Sandbox Agent 서버 종료 완료")


# ── FastAPI 앱 ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Sandbox Agent",
    version="1.0.0",
    description="격리 코드 실행 에이전트 — Firecracker MicroVM / Docker 폴백",
    lifespan=lifespan,
)


# ── 엔드포인트 ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check() -> dict[str, Any]:
    """에이전트 상태, VM 풀 통계, 백그라운드 태스크 실행 여부를 반환합니다."""
    listen_running = (
        _ctx.listen_task is not None and not _ctx.listen_task.done()
    )
    heartbeat_running = (
        _ctx.heartbeat_task is not None and not _ctx.heartbeat_task.done()
    )
    return {
        "status": "ok",
        "mode": "server",
        "runtime": _ctx.agent.runtime,
        "pool_stats": _ctx.agent.pool_stats(),
        "listen_task_running": listen_running,
        "heartbeat_running": heartbeat_running,
        "current_tasks": _ctx.listener._current_task_count,
    }


@app.post("/execute", status_code=status.HTTP_202_ACCEPTED)
async def direct_execute(req: DirectExecuteRequest) -> dict[str, Any]:
    """
    Redis 큐를 우회하여 직접 코드를 실행합니다.
    개발/테스트 환경에서 사용합니다.

    요청 예시:
        {
            "task_id": "test-001",
            "params": {
                "language": "python",
                "code": "print('hello')",
                "timeout": 30
            }
        }
    """
    try:
        dispatch_msg = {
            "task_id": req.task_id,
            "params": req.params,
        }
        result = await _ctx.agent.handle_dispatch(dispatch_msg)
        return result
    except Exception as exc:
        logger.error("[/execute] 실행 실패: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


# ── 진입점 ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8003"))
    uvicorn.run(
        "agents.sandbox_agent.fastapi_app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
