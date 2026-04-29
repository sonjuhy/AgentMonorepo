"""
Slack Agent FastAPI 서버 진입점
- uvicorn 으로 FastAPI 앱을 실행합니다.
- Socket Mode 클라이언트는 FastAPI lifespan 내부에서 관리됩니다.
- 환경변수:
    SLACK_BOT_TOKEN    : xoxb-... 형식의 봇 토큰 (필수)
    SLACK_APP_TOKEN    : xapp-... 형식의 앱-레벨 토큰 (Socket Mode, 필수)
    CLASSIFIER_BACKEND : claude_api | gemini_api | claude_cli | gemini_cli (기본: gemini_api)
    PORT               : 서버 포트 (기본: 8000)
    HOST               : 서버 바인드 주소 (기본: 0.0.0.0)
"""

import logging
import os

import uvicorn
from shared_core.agent_logger import setup_logging

# 보안 마스킹 필터가 적용된 로깅 설정 활성화
setup_logging()

# uvicorn 과 통합된 로그 포맷 설정
# uvicorn.run() 이 내부 로거를 덮어쓰므로 log_config 로 직접 지정
LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["default"],
    },
    "loggers": {
        "uvicorn": {"level": "INFO", "propagate": True},
        "uvicorn.error": {"level": "INFO", "propagate": True},
        "uvicorn.access": {"level": "INFO", "propagate": True},
        "slack_agent": {"level": "INFO", "propagate": True},
        "slack_bolt": {
            "level": "WARNING",
            "propagate": True,
        },  # slack_bolt 내부 로그 간소화
    },
}


def main() -> None:
    """
    uvicorn 을 사용하여 FastAPI Slack Agent 서버를 시작합니다.
    """
    host: str = os.environ.get("HOST", "0.0.0.0")
    port: int = int(os.environ.get("PORT", "8000"))

    print(f"\n{'='*50}")
    print(f"  Slack Agent FastAPI 서버 시작")
    print(f"  주소: http://{host}:{port}")
    print(f"  문서: http://localhost:{port}/docs")
    print(f"{'='*50}\n")

    uvicorn.run(
        "agents.communication_agent.slack.fastapi_app:app",
        host=host,
        port=port,
        reload=False,
        log_config=LOG_CONFIG,
    )


if __name__ == "__main__":
    main()
