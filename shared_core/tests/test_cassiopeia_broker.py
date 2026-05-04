"""
[TDD] shared_core.messaging.CassiopeiaMessageBroker 단위 테스트

cassiopeia-sdk의 CassiopeiaClient를 래핑하여 에이전트 간 메시지를 전달하는
CassiopeiaMessageBroker 구현에 대한 TDD 테스트입니다.

테스트 전략:
- CassiopeiaClient의 send_message / listen을 Mock으로 대체
- 브로커 계층의 변환 로직(AgentMessage 매핑)만 검증
"""
from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, call
from typing import AsyncIterator

from shared_core.messaging.broker import CassiopeiaMessageBroker
from shared_core.messaging.schema import AgentMessage


# ---------------------------------------------------------------------------
# 헬퍼 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_message() -> AgentMessage:
    return AgentMessage(
        sender="orchestra",
        receiver="file",
        action="read_file",
        payload={"task_id": "t-001", "params": {"file_path": "/tmp/test.txt"}},
    )


async def _make_listen_gen(*messages):
    """cassiopeia AgentMessage를 yield하는 가짜 listen() 제너레이터를 반환합니다."""
    from cassiopeia_sdk.client import AgentMessage as SdkAgentMessage
    for msg in messages:
        yield SdkAgentMessage(
            sender=msg.sender,
            receiver=msg.receiver,
            action=msg.action,
            payload=dict(msg.payload),
            reference_id=msg.reference_id,
            payload_summary=msg.payload_summary,
        )


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------

class TestConnect:
    async def test_connect_delegates_to_cassiopeia_client(self):
        broker = CassiopeiaMessageBroker(agent_id="file", redis_url="redis://localhost:6379")
        broker._client.connect = AsyncMock()

        await broker.connect()

        broker._client.connect.assert_awaited_once()

    async def test_disconnect_delegates_to_cassiopeia_client(self):
        broker = CassiopeiaMessageBroker(agent_id="file", redis_url="redis://localhost:6379")
        broker._client.disconnect = AsyncMock()

        await broker.disconnect()

        broker._client.disconnect.assert_awaited_once()

    async def test_async_context_manager_connects_and_disconnects(self):
        broker = CassiopeiaMessageBroker(agent_id="file", redis_url="redis://localhost:6379")
        broker._client.connect = AsyncMock()
        broker._client.disconnect = AsyncMock()

        async with broker:
            broker._client.connect.assert_awaited_once()

        broker._client.disconnect.assert_awaited_once()


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

class TestPublish:
    async def test_publish_calls_send_message_with_correct_fields(self, sample_message):
        broker = CassiopeiaMessageBroker(agent_id="orchestra", redis_url="redis://localhost:6379")
        broker._client.send_message = AsyncMock(return_value=True)

        result = await broker.publish(sample_message)

        broker._client.send_message.assert_awaited_once_with(
            action=sample_message.action,
            payload=dict(sample_message.payload),
            receiver=sample_message.receiver,
        )
        assert result is True

    async def test_publish_returns_false_when_send_message_fails(self, sample_message):
        broker = CassiopeiaMessageBroker(agent_id="orchestra", redis_url="redis://localhost:6379")
        broker._client.send_message = AsyncMock(return_value=False)

        result = await broker.publish(sample_message)

        assert result is False

    async def test_publish_different_receivers(self):
        broker = CassiopeiaMessageBroker(agent_id="orchestra", redis_url="redis://localhost:6379")
        broker._client.send_message = AsyncMock(return_value=True)

        for receiver in ("file", "schedule", "research"):
            msg = AgentMessage(sender="orchestra", receiver=receiver, action="ping", payload={})
            await broker.publish(msg)

        calls = broker._client.send_message.await_args_list
        receivers = [c.kwargs["receiver"] for c in calls]
        assert receivers == ["file", "schedule", "research"]


# ---------------------------------------------------------------------------
# subscribe
# ---------------------------------------------------------------------------

class TestSubscribe:
    async def test_subscribe_yields_agent_messages(self, sample_message):
        broker = CassiopeiaMessageBroker(agent_id="file", redis_url="redis://localhost:6379")
        broker._client.listen = MagicMock(return_value=_make_listen_gen(sample_message))

        received = []
        async for msg in broker.subscribe():
            received.append(msg)
            break  # 하나만 수신

        assert len(received) == 1
        assert received[0].action == sample_message.action
        assert received[0].sender == sample_message.sender
        assert received[0].receiver == sample_message.receiver

    async def test_subscribe_maps_payload_correctly(self, sample_message):
        broker = CassiopeiaMessageBroker(agent_id="file", redis_url="redis://localhost:6379")
        broker._client.listen = MagicMock(return_value=_make_listen_gen(sample_message))

        async for msg in broker.subscribe():
            assert msg.payload == sample_message.payload
            break

    async def test_subscribe_maps_reference_id(self):
        broker = CassiopeiaMessageBroker(agent_id="file", redis_url="redis://localhost:6379")
        msg_with_ref = AgentMessage(
            sender="orchestra",
            receiver="file",
            action="read_file",
            payload={},
            reference_id="ref-123",
        )
        broker._client.listen = MagicMock(return_value=_make_listen_gen(msg_with_ref))

        async for msg in broker.subscribe():
            assert msg.reference_id == "ref-123"
            break

    async def test_subscribe_yields_multiple_messages(self, sample_message):
        broker = CassiopeiaMessageBroker(agent_id="file", redis_url="redis://localhost:6379")
        msg2 = AgentMessage(sender="orchestra", receiver="file", action="write_file", payload={})
        broker._client.listen = MagicMock(return_value=_make_listen_gen(sample_message, msg2))

        received = []
        async for msg in broker.subscribe():
            received.append(msg)

        assert len(received) == 2
        assert received[0].action == "read_file"
        assert received[1].action == "write_file"


# ---------------------------------------------------------------------------
# 프로토콜 준수 검증
# ---------------------------------------------------------------------------

class TestProtocolCompliance:
    def test_broker_has_publish_method(self):
        broker = CassiopeiaMessageBroker(agent_id="file", redis_url="redis://localhost:6379")
        assert hasattr(broker, "publish")
        assert callable(broker.publish)

    def test_broker_has_subscribe_method(self):
        broker = CassiopeiaMessageBroker(agent_id="file", redis_url="redis://localhost:6379")
        assert hasattr(broker, "subscribe")
        assert callable(broker.subscribe)

    def test_broker_has_agent_id(self):
        broker = CassiopeiaMessageBroker(agent_id="file", redis_url="redis://localhost:6379")
        assert broker.agent_id == "file"
