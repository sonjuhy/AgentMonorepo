from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis

from .schema import AgentMessage, AgentName

_CHANNEL_PREFIX = "agent"


class RedisMessageBroker:
    """Redis Pub/Sub 기반의 에이전트 간 메시지 브로커 구현체.

    채널 이름 규칙: ``agent:{agent_name}``

    Example::

        async with RedisMessageBroker("redis://localhost:6379") as broker:
            # 발행
            msg = AgentMessage(sender="slack", receiver="planning", action="analyze_task", payload={...})
            await broker.publish(msg)

            # 구독 (비동기 제너레이터)
            async for message in broker.subscribe("planning"):
                print(message)
    """

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        """브로커를 초기화합니다.

        Args:
            redis_url: Redis 서버 URL. 기본값은 ``redis://localhost:6379``.
        """
        self._redis_url = redis_url
        self._client: aioredis.Redis | None = None  # type: ignore[type-arg]

    async def connect(self) -> None:
        """Redis 클라이언트 연결을 초기화합니다."""
        self._client = await aioredis.from_url(self._redis_url, decode_responses=True)

    async def disconnect(self) -> None:
        """Redis 클라이언트 연결을 종료합니다."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "RedisMessageBroker":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()

    def _require_client(self) -> aioredis.Redis:  # type: ignore[type-arg]
        """연결된 클라이언트를 반환합니다. 연결이 없으면 RuntimeError를 발생시킵니다."""
        if self._client is None:
            raise RuntimeError(
                "Redis 연결이 초기화되지 않았습니다. connect() 또는 async with 구문을 먼저 사용하세요."
            )
        return self._client

    async def publish(self, message: AgentMessage) -> bool:
        """메시지를 수신 에이전트의 채널에 발행합니다.

        Args:
            message: 발행할 AgentMessage 객체. ``message.receiver`` 채널로 전송됩니다.

        Returns:
            발행 성공 시 ``True``, 실패(예외 발생) 시 ``False``.
        """
        client = self._require_client()
        channel = f"{_CHANNEL_PREFIX}:{message.receiver}"
        try:
            await client.publish(channel, message.to_json())
            return True
        except Exception:
            return False

    async def subscribe(self, agent_name: AgentName) -> AsyncIterator[AgentMessage]:
        """특정 에이전트를 대상으로 하는 메시지를 비동기로 수신 대기합니다.

        Args:
            agent_name: 구독할 에이전트 이름. ``agent:{agent_name}`` 채널을 구독합니다.

        Yields:
            수신된 AgentMessage 인스턴스.
        """
        client = self._require_client()
        channel = f"{_CHANNEL_PREFIX}:{agent_name}"
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for raw in pubsub.listen():
                if raw.get("type") == "message":
                    yield AgentMessage.from_json(raw["data"])
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
