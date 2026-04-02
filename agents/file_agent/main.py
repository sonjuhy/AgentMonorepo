"""
File Agent 진입점
- ephemeral-docker-ops 전략: 메시지 1건 처리 후 자연 종료
"""

import asyncio

from agents.file_agent.agent import FileAgent


def main() -> None:
    agent = FileAgent()
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
