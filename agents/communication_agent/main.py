"""
Slack Agent 진입점
- ephemeral-docker-ops 전략: 단발성 실행 후 자연 종료
"""

import asyncio

from agents.slack_agent.slack.agent import SlackAgent


def main() -> None:
    agent = SlackAgent()
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
