"""
main.py cassiopeia-sdk 마이그레이션 TDD 테스트
- POST /tasks: cassiopeia.send_message(receiver="orchestra") 사용 검증
- POST /dispatch: cassiopeia.send_message(receiver=agent_name) 사용 검증
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import httpx
import pytest
import pytest_asyncio

import os
os.environ.setdefault("LLM_BACKEND", "gemini")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("CLIENT_API_KEY", "test-client-key")
os.environ.setdefault("ENCRYPTION_KEY", "sjbWLtj1X4WskngsFoQj-21Bx37TgszKXX0b2vlQhHY=")


@pytest_asyncio.fixture
async def fake_redis():
    server = fakeredis.FakeServer()
    r = fakeredis.FakeAsyncRedis(decode_responses=True, server=server)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def mock_cassiopeia_client():
    c = AsyncMock()
    c.connect = AsyncMock()
    c.disconnect = AsyncMock()
    c.send_message = AsyncMock(return_value=True)
    return c


@pytest_asyncio.fixture
async def async_client(fake_redis, mock_cassiopeia_client, tmp_path):
    from agents.cassiopeia_agent.main import app
    from agents.cassiopeia_agent import app_context
    from agents.cassiopeia_agent.health_monitor import HealthMonitor
    from agents.cassiopeia_agent.manager import OrchestraManager
    from agents.cassiopeia_agent.state_manager import StateManager
    from agents.cassiopeia_agent.agent_builder_handler import AgentBuilderHandler
    from agents.cassiopeia_agent.registry import AgentRegistry
    from agents.cassiopeia_agent.marketplace_handler import MarketplaceHandler
    from agents.cassiopeia_agent.nlu_engine import NLUEngine
    from shared_core.llm.interfaces import LLMUsage

    db_path = str(tmp_path / "test_app.db")

    provider = AsyncMock()
    provider.validate = AsyncMock(return_value=True)
    provider.generate_response = AsyncMock(
        return_value=(
            json.dumps({
                "type": "single",
                "intent": "파일 조회",
                "selected_agent": "file_agent",
                "action": "read_file",
                "params": {},
                "metadata": {
                    "reason": "test",
                    "confidence_score": 0.9,
                    "requires_user_approval": False,
                },
            }),
            LLMUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )
    )
    nlu = NLUEngine(provider=provider)

    import agents.cassiopeia_agent.auth as auth_module
    auth_module.ADMIN_API_KEY = "test-admin-key"
    auth_module.CLIENT_API_KEY = "test-client-key"

    sm = StateManager(redis_client=fake_redis)
    sm._db_path = db_path
    hm = HealthMonitor(redis_client=fake_redis)
    mgr = OrchestraManager(
        redis_client=fake_redis,
        nlu_engine=nlu,
        state_manager=sm,
        health_monitor=hm,
    )

    app_context.ctx.redis_client = fake_redis
    app_context.ctx.state_manager = sm
    app_context.ctx.health_monitor = hm
    app_context.ctx.manager = mgr
    app_context.ctx.builder_handler = AgentBuilderHandler()
    app_context.ctx.registry = AgentRegistry()
    app_context.ctx.marketplace = MarketplaceHandler(
        app_context.ctx.builder_handler,
        app_context.ctx.registry,
        app_context.ctx.health_monitor,
    )
    app_context.ctx.listen_task = None
    app_context.ctx.monitor_task = None
    app_context.ctx.cassiopeia_client = mock_cassiopeia_client

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-API-Key": "test-admin-key"},
        ) as client:
            client.cassiopeia = mock_cassiopeia_client  # type: ignore
            yield client
    finally:
        app.router.lifespan_context = original_lifespan
        await sm.close()


# ── POST /tasks (submit_task) ─────────────────────────────────────────────────

class TestSubmitTaskCassiopeia:
    async def test_uses_cassiopeia_send_message(self, async_client, mock_cassiopeia_client):
        """POST /tasks가 cassiopeia.send_message()로 오케스트라에 태스크를 전달한다."""
        resp = await async_client.post(
            "/tasks",
            json={"user_id": "user-1", "channel_id": "ch-1", "content": "파일 읽어줘"},
        )
        assert resp.status_code == 200
        mock_cassiopeia_client.send_message.assert_awaited_once()

    async def test_sends_to_orchestra_receiver(self, async_client, mock_cassiopeia_client):
        """receiver='orchestra'로 전송한다."""
        await async_client.post(
            "/tasks",
            json={"user_id": "user-1", "channel_id": "ch-1", "content": "테스트"},
        )
        kwargs = mock_cassiopeia_client.send_message.call_args.kwargs
        assert kwargs["receiver"] == "orchestra"

    async def test_action_is_user_request(self, async_client, mock_cassiopeia_client):
        """action='user_request' 로 전송한다."""
        await async_client.post(
            "/tasks",
            json={"user_id": "user-1", "channel_id": "ch-1", "content": "테스트"},
        )
        kwargs = mock_cassiopeia_client.send_message.call_args.kwargs
        assert kwargs["action"] == "user_request"

    async def test_payload_contains_task_id(self, async_client, mock_cassiopeia_client):
        """payload에 task_id가 있다."""
        await async_client.post(
            "/tasks",
            json={"user_id": "user-1", "channel_id": "ch-1", "content": "테스트"},
        )
        kwargs = mock_cassiopeia_client.send_message.call_args.kwargs
        assert "task_id" in kwargs["payload"]

    async def test_does_not_use_rpush(self, async_client, fake_redis):
        """POST /tasks가 Redis rpush를 호출하지 않는다."""
        called = []
        original = fake_redis.rpush
        fake_redis.rpush = AsyncMock(side_effect=lambda *a, **kw: called.append(a))

        await async_client.post(
            "/tasks",
            json={"user_id": "user-1", "channel_id": "ch-1", "content": "테스트"},
        )
        # rpush가 호출됐다면 이전 Redis List 방식이 여전히 사용 중
        assert len(called) == 0
        fake_redis.rpush = original


# ── POST /dispatch (direct_dispatch) ──────────────────────────────────────────

class TestDirectDispatchCassiopeia:
    async def test_uses_cassiopeia_send_message(self, async_client, mock_cassiopeia_client):
        """POST /dispatch가 cassiopeia.send_message()로 에이전트에 태스크를 전달한다."""
        from agents.cassiopeia_agent import app_context
        app_context.ctx.health_monitor.is_agent_ready = AsyncMock(return_value=(True, "ok"))
        app_context.ctx.manager.wait_for_result = AsyncMock(
            return_value={"status": "COMPLETED", "result_data": {}, "error": None, "usage_stats": {}}
        )
        mock_cassiopeia_client.send_message.reset_mock()

        resp = await async_client.post(
            "/dispatch",
            json={
                "user_id": "user-1",
                "channel_id": "ch-1",
                "agent_name": "file_agent",
                "action": "read_file",
                "params": {"path": "/tmp/test.txt"},
                "content": "",
                "priority": "MEDIUM",
                "timeout": 60,
            },
        )
        assert resp.status_code == 200
        mock_cassiopeia_client.send_message.assert_awaited()

    async def test_dispatch_receiver_is_agent_name(self, async_client, mock_cassiopeia_client):
        """receiver가 요청한 agent_name이다."""
        from agents.cassiopeia_agent import app_context
        app_context.ctx.health_monitor.is_agent_ready = AsyncMock(return_value=(True, "ok"))
        app_context.ctx.manager.wait_for_result = AsyncMock(
            return_value={"status": "COMPLETED", "result_data": {}, "error": None, "usage_stats": {}}
        )
        mock_cassiopeia_client.send_message.reset_mock()

        await async_client.post(
            "/dispatch",
            json={
                "user_id": "u1", "channel_id": "ch1",
                "agent_name": "schedule_agent",
                "action": "list_schedules",
                "params": {}, "content": "",
                "priority": "MEDIUM", "timeout": 30,
            },
        )
        kwargs = mock_cassiopeia_client.send_message.call_args.kwargs
        assert kwargs["receiver"] == "schedule_agent"

    async def test_dispatch_action_matches_request(self, async_client, mock_cassiopeia_client):
        """cassiopeia action이 요청된 action과 일치한다."""
        from agents.cassiopeia_agent import app_context
        app_context.ctx.health_monitor.is_agent_ready = AsyncMock(return_value=(True, "ok"))
        app_context.ctx.manager.wait_for_result = AsyncMock(
            return_value={"status": "COMPLETED", "result_data": {}, "error": None, "usage_stats": {}}
        )
        mock_cassiopeia_client.send_message.reset_mock()

        await async_client.post(
            "/dispatch",
            json={
                "user_id": "u1", "channel_id": "ch1",
                "agent_name": "archive_agent",
                "action": "search",
                "params": {"query": "test"}, "content": "",
                "priority": "MEDIUM", "timeout": 30,
            },
        )
        kwargs = mock_cassiopeia_client.send_message.call_args.kwargs
        assert kwargs["action"] == "search"
