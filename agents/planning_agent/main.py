"""
Planning Agent 진입점
- ephemeral-docker-ops 전략: 단발성 실행 후 자연 종료
"""

import asyncio

from agents.planning_agent.agent import PlanningAgent


def main() -> None:
    agent = PlanningAgent()
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
