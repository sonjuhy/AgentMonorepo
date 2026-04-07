"""
Sandbox Agent 진입점

MODE 환경변수로 동작 모드를 선택합니다:
    server (기본): FastAPI + Redis 리스너 서버 실행
                   OrchestraManager로부터 태스크를 수신하여 처리
    ephemeral:     단발 테스트 실행 (테스트/디버깅용)
"""

from __future__ import annotations

import asyncio
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sandbox_agent.main")


def _run_ephemeral() -> None:
    """단발 테스트 실행 — python 코드 샘플로 동작 확인."""
    from .agent import SandboxAgent
    from .models import ExecuteRequest

    async def _test() -> None:
        agent = SandboxAgent()
        await agent.start()

        result = await agent.handle_dispatch({
            "task_id": "ephemeral-test",
            "params": {
                "language": "python",
                "code": "print('Sandbox Agent 동작 확인')\nprint(1 + 1)",
                "timeout": 10,
            },
        })
        logger.info("테스트 결과: %s", result)
        await agent.shutdown()

    asyncio.run(_test())


def _run_server() -> None:
    """FastAPI 서버 모드 — OrchestraManager Redis 큐 수신."""
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8003"))
    logger.info("Sandbox Agent 서버 시작: %s:%d", host, port)
    uvicorn.run(
        "agents.sandbox_agent.fastapi_app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


def main() -> None:
    mode = os.environ.get("MODE", "server").lower()
    if mode == "ephemeral":
        _run_ephemeral()
    else:
        _run_server()


if __name__ == "__main__":
    main()
