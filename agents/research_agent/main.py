"""
Research Agent 진입점
- ephemeral-docker-ops 전략: 메시지 1건 처리 후 자연 종료
"""

import asyncio

from agents.research_agent.agent import ResearchAgent


def main() -> None:
    agent = ResearchAgent()
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
