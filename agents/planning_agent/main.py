"""
Planning Agent 진입점

MODE 환경변수로 동작 모드를 선택합니다:
    ephemeral (기본): Notion에서 '검토중' 태스크를 가져와 처리 후 자연 종료
                      ephemeral-docker-ops 전략 준수 (cron/스케줄러 실행용)
    server:           FastAPI + Redis 리스너 서버 실행
                      OrchestraManager로부터 태스크를 수신하여 처리
"""

from __future__ import annotations

import asyncio
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("planning_agent.main")


def _run_ephemeral() -> None:
    """Notion 기반 단발성 실행 (기본 ephemeral 모드)."""
    from .notion.agent import PlanningAgent

    agent = PlanningAgent()
    asyncio.run(agent.run())


def _run_server() -> None:
    """FastAPI 서버 모드 — OrchestraManager Redis 큐 수신."""
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8002"))
    logger.info("Planning Agent 서버 시작: %s:%d", host, port)
    uvicorn.run(
        "agents.planning_agent.fastapi_app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


def main() -> None:
    mode = os.environ.get("MODE", "ephemeral").lower()
    if mode == "server":
        _run_server()
    else:
        _run_ephemeral()


if __name__ == "__main__":
    main()
