from collections.abc import AsyncIterator
from typing import Any

from cassiopeia_sdk.client import CassiopeiaClient
from cassiopeia_sdk.client import AgentMessage as SdkAgentMessage

from .schema import AgentMessage, AgentName

_CHANNEL_PREFIX = "agent"


class CassiopeiaMessageBroker:
    """cassiopeia-sdk의 CassiopeiaClient를 래핑한 에이전트 간 메시지 브로커.

    채널 이름 규칙: ``agent:{agent_name}`` (cassiopeia-sdk와 동일)

    Example::

        async with CassiopeiaMessageBroker("file", "redis://localhost:6379") as broker:
            msg = AgentMessage(sender="orchestra", receiver="file", action="read_file", payload={...})
            await broker.publish(msg)

            async for message in broker.subscribe():
                print(message)
    """

    def __init__(self, agent_id: str, redis_url: str = "redis://localhost:6379") -> None:
        self.agent_id = agent_id
        self._client = CassiopeiaClient(agent_id=agent_id, redis_url=redis_url)

    async def connect(self) -> None:
        await self._client.connect()

    async def disconnect(self) -> None:
        await self._client.disconnect()

    async def __aenter__(self) -> "CassiopeiaMessageBroker":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()

    async def publish(self, message: AgentMessage) -> bool:
        """메시지를 cassiopeia-sdk의 send_message로 발행합니다.

        Args:
            message: 발행할 AgentMessage. message.receiver 채널로 전송됩니다.

        Returns:
            발행 성공 시 True, 실패 시 False.
        """
        return await self._client.send_message(
            action=message.action,
            payload=dict(message.payload),
            receiver=message.receiver,
        )

    async def subscribe(self) -> AsyncIterator[AgentMessage]:
        """이 브로커의 agent_id를 대상으로 하는 메시지를 비동기로 수신합니다.

        cassiopeia-sdk의 listen()을 호출하여 ``agent:{agent_id}`` 채널을 구독합니다.

        Yields:
            수신된 AgentMessage 인스턴스.
        """
        async for sdk_msg in self._client.listen():
            yield _from_sdk_message(sdk_msg)


# ---------------------------------------------------------------------------
# 내부 변환 헬퍼
# ---------------------------------------------------------------------------

def _from_sdk_message(sdk_msg: SdkAgentMessage) -> AgentMessage:
    """cassiopeia SDK AgentMessage를 내부 AgentMessage로 변환합니다."""
    return AgentMessage(
        sender=sdk_msg.sender,
        receiver=sdk_msg.receiver,
        action=sdk_msg.action,
        payload=dict(sdk_msg.payload),
        reference_id=sdk_msg.reference_id,
        payload_summary=sdk_msg.payload_summary,
        timestamp=sdk_msg.timestamp,
    )
