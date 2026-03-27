"""
OrchestraAgent 진입점
- 장기 실행(long-running) 서비스: Redis Pub/Sub 구독 지속
- ephemeral-docker-ops 전략과 달리 종료 없이 메시지를 계속 처리합니다.
"""

import asyncio
import os

from shared_core.messaging import RedisMessageBroker

from agents.orchestra_agent.agent import OrchestraAgent
from agents.orchestra_agent.registry import AgentRegistry


async def _run() -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    registry = AgentRegistry(include_defaults=True)

    async with RedisMessageBroker(redis_url) as broker:
        agent = OrchestraAgent(broker=broker, registry=registry)
        await agent.run()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
