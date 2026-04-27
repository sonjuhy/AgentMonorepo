"""
Communication Agent 진입점 (Notion 알림 발송 전용)
- ephemeral-docker-ops 전략: 단발성 실행 후 자연 종료
"""

import asyncio
from shared_core.agent_logger import setup_logging

from .slack.agent import SlackCommAgent

# 보안 마스킹 필터가 적용된 로깅 설정 활성화
setup_logging()


def main() -> None:
    agent = SlackCommAgent()
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
