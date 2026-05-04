"""
[TDD] manager.py LLM Gateway 라우팅 테스트

- action="llm_call" 메시지는 LLMGatewayHandler.handle()로 라우팅되어야 함
- 일반 action="user_request"는 기존 NLU 파이프라인으로 라우팅되어야 함
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
import pytest_asyncio


def _make_msg(action: str, payload: dict):
    msg = MagicMock()
    msg.action = action
    msg.payload = payload
    return msg


@pytest_asyncio.fixture
async def redis():
    server = fakeredis.FakeServer()
    r = fakeredis.FakeAsyncRedis(decode_responses=True, server=server)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
def mock_cassiopeia():
    c = MagicMock()
    c.connect = AsyncMock()
    c.disconnect = AsyncMock()
    c.send_message = AsyncMock(return_value=True)

    async def _listen():
        return
        yield  # noqa: unreachable — makes this an async generator

    c.listen = MagicMock(return_value=_listen())
    return c


@pytest_asyncio.fixture
async def manager(redis, mock_cassiopeia):
    from agents.cassiopeia_agent.manager import OrchestraManager
    from agents.cassiopeia_agent.nlu_engine import NLUEngine
    from agents.cassiopeia_agent.state_manager import StateManager
    from agents.cassiopeia_agent.health_monitor import HealthMonitor

    sm = StateManager(redis_client=redis)
    hm = HealthMonitor(redis_client=redis)
    nlu = MagicMock(spec=NLUEngine)
    mgr = OrchestraManager(
        redis_client=redis,
        nlu_engine=nlu,
        state_manager=sm,
        health_monitor=hm,
        cassiopeia=mock_cassiopeia,
    )
    yield mgr
    await sm.close()


class TestLLMGatewayRouting:
    async def test_llm_call_action_routed_to_gateway(self, manager, redis):
        """action='llm_call' 메시지는 LLMGatewayHandler.handle()을 호출해야 한다."""
        mock_handler = AsyncMock()
        manager._llm_gateway = mock_handler

        payload = {
            "task_id": "gw-001",
            "agent_id": "ext_agent",
            "messages": [{"role": "user", "content": "안녕"}],
            "max_tokens": 100,
        }
        await manager._route_message(action="llm_call", payload=payload)

        mock_handler.handle.assert_awaited_once_with(payload)

    async def test_user_request_action_not_routed_to_gateway(self, manager):
        """action='user_request'는 NLU 파이프라인으로 가야 한다 (gateway 호출 없음)."""
        mock_handler = AsyncMock()
        manager._llm_gateway = mock_handler

        task = {
            "task_id": "t-001",
            "session_id": "U1:C1",
            "requester": {"user_id": "U1", "channel_id": "C1"},
            "content": "파일 읽어줘",
            "source": "slack",
        }
        with patch.object(manager, "process_task", new_callable=AsyncMock) as mock_process:
            await manager._route_message(action="user_request", payload=task)
            mock_process.assert_awaited_once()

        mock_handler.handle.assert_not_awaited()

    async def test_llm_gateway_not_set_skips_gracefully(self, manager):
        """_llm_gateway가 None이면 llm_call을 조용히 무시해야 한다."""
        manager._llm_gateway = None
        payload = {"task_id": "gw-002", "agent_id": "ext_agent"}
        await manager._route_message(action="llm_call", payload=payload)
        # 예외 없이 통과하면 통과
