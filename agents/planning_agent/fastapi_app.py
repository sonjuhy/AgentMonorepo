"""
Planning Agent FastAPI 서버 (server 모드)
- GET  /health       : 에이전트 상태 조회
- POST /execute      : Redis 우회 직접 실행 (개발/테스트용)

Lifespan 백그라운드:
    - PlanningRedisListener.listen_tasks()  — BLPOP 큐 감시
    - PlanningRedisListener._heartbeat_loop() — 15초 주기 health 갱신
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

from .notion.agent import PlanningAgent
from .notion.task_analyzer import build_task_analyzer
from .redis_listener import PlanningRedisListener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("planning_agent.fastapi_app")


# ── Pydantic 요청 바디 ─────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    """POST /execute 요청 바디 — DispatchMessage.params 구조와 동일."""
    source: str = "direct"
    page_id: str | None = None
    file_path: str | None = None
    title: str
    description: str = ""
    task_type: str = ""
    priority: str = "MEDIUM"
    update_source: bool = False


# ── Application Context ────────────────────────────────────────────────────────

class _AppContext:
    agent: PlanningAgent
    listener: PlanningRedisListener
    listen_task: asyncio.Task[None] | None = None
    heartbeat_task: asyncio.Task[None] | None = None


_ctx = _AppContext()


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 수명 주기: 초기화 → 백그라운드 시작 → 종료."""
    logger.info("[Lifespan] Planning Agent 서버 시작")

    _ctx.agent = PlanningAgent(task_analyzer=build_task_analyzer())
    _ctx.listener = PlanningRedisListener(
        planning_agent=_ctx.agent,
        redis_url=os.environ.get("REDIS_URL"),
        orchestra_url=os.environ.get("ORCHESTRA_URL"),
    )

    _ctx.listen_task = asyncio.create_task(
        _ctx.listener.listen_tasks(),
        name="planning_listen_tasks",
    )
    _ctx.heartbeat_task = asyncio.create_task(
        _ctx.listener._heartbeat_loop(),
        name="planning_heartbeat",
    )
    logger.info("[Lifespan] 백그라운드 태스크 시작됨")

    yield

    # 종료
    logger.info("[Lifespan] Planning Agent 서버 종료 시작")
    for task in (_ctx.listen_task, _ctx.heartbeat_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await _ctx.listener.close()
    logger.info("[Lifespan] Planning Agent 서버 종료 완료")


# ── FastAPI 앱 ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Planning Agent",
    version="2.0.0",
    description="AI 기획 에이전트 — Notion/Obsidian 태스크 분석 및 기획 문서 생성",
    lifespan=lifespan,
)


# ── 엔드포인트 ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check() -> dict[str, Any]:
    """에이전트 상태와 백그라운드 태스크 실행 여부를 반환합니다."""
    listen_running = (
        _ctx.listen_task is not None and not _ctx.listen_task.done()
    )
    heartbeat_running = (
        _ctx.heartbeat_task is not None and not _ctx.heartbeat_task.done()
    )
    return {
        "status": "ok",
        "mode": "server",
        "listen_task_running": listen_running,
        "heartbeat_running": heartbeat_running,
        "current_tasks": _ctx.listener._current_task_count,
    }


@app.post("/execute", status_code=status.HTTP_202_ACCEPTED)
async def direct_execute(req: ExecuteRequest) -> dict[str, Any]:
    """
    Redis 큐를 우회하여 직접 기획 태스크를 실행합니다.
    개발/테스트 환경에서 사용합니다.
    """
    try:
        dispatch_msg = {
            "task_id": f"direct-{req.title[:20].replace(' ', '-')}",
            "params": {
                "source": req.source,
                "page_id": req.page_id,
                "file_path": req.file_path,
                "title": req.title,
                "description": req.description,
                "task_type": req.task_type,
                "priority": req.priority,
                "update_source": req.update_source,
            },
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
    port = int(os.environ.get("PORT", "8002"))
    uvicorn.run(
        "agents.planning_agent.fastapi_app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
