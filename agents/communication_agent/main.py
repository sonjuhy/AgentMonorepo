"""
Communication Agent 진입점 (Notion 알림 발송 전용)
- ephemeral-docker-ops 전략: 단발성 실행 후 자연 종료
"""

import asyncio

from .slack.agent import SlackCommAgent


def main() -> None:
    agent = SlackCommAgent()
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
