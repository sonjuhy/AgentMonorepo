"""
Schedule Agent 진입점
- ephemeral-docker-ops 전략: 메시지 1건 처리 후 자연 종료
"""

import asyncio
from shared_core.agent_logger import setup_logging

from agents.schedule_agent.agent import ScheduleAgent

# 보안 마스킹 필터가 적용된 로깅 설정 활성화
setup_logging()


def main() -> None:
    agent = ScheduleAgent()
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
