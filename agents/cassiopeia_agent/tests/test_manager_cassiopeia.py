"""
OrchestraManager cassiopeia-sdk 마이그레이션 TDD 테스트
- listen_tasks(): cassiopeia.listen() 사용 검증
- _dispatch_to_agent(): cassiopeia.send_message() 사용 검증
- _send_to_comm_agent(): cassiopeia.send_message() 사용 검증
- _send_progress_to_comm(): cassiopeia.send_message() 사용 검증
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest

from agents.cassiopeia_agent.manager import OrchestraManager
from agents.cassiopeia_agent.models import DispatchMessage


def _make_sdk_message(action: str = "user_request", payload: dict | None = None):
    msg = MagicMock()
    msg.action = action
    msg.payload = payload or {}
    msg.sender = "test-sender"
    msg.receiver = "orchestra"
    return msg


def _signed_task(task_id: str = "task-001") -> dict:
    """DISPATCH_HMAC_SECRET 없이도 통과하는 태스크(서명 생략 모드)."""
    return {
        "task_id": task_id,
        "session_id": "sess-001",
        "requester": {"user_id": "user-1", "channel_id": "ch-1"},
        "content": "테스트",
        "source": "api",
    }


@pytest.fixture
def fake_redis():
    server = fakeredis.FakeServer()
    r = fakeredis.FakeAsyncRedis(decode_responses=True, server=server)
    return r


@pytest.fixture
def mock_cassiopeia():
    c = MagicMock()
    c.connect = AsyncMock()
    c.disconnect = AsyncMock()
    c.send_message = AsyncMock(return_value=True)
    # listen() is called synchronously and returns an async generator — use MagicMock
    c.listen = MagicMock()
    return c


@pytest.fixture
def mock_nlu():
    from agents.cassiopeia_agent.nlu_engine import NLUEngine
    from shared_core.llm.interfaces import LLMUsage
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
    return NLUEngine(provider=provider)


@pytest.fixture
def mock_state(fake_redis, tmp_path):
    import os
    os.environ.setdefault("DATABASE_PATH", str(tmp_path / "test.db"))
    from agents.cassiopeia_agent.state_manager import StateManager
    return StateManager(redis_client=fake_redis)


@pytest.fixture
def mock_health(fake_redis):
    from agents.cassiopeia_agent.health_monitor import HealthMonitor
    return HealthMonitor(redis_client=fake_redis)


@pytest.fixture
def manager(fake_redis, mock_cassiopeia, mock_nlu, mock_state, mock_health):
    return OrchestraManager(
        redis_client=fake_redis,
        nlu_engine=mock_nlu,
        state_manager=mock_state,
        health_monitor=mock_health,
        cassiopeia=mock_cassiopeia,
    )


# ── listen_tasks ──────────────────────────────────────────────────────────────

class TestListenTasksCassiopeia:
    async def test_calls_cassiopeia_connect(self, manager, mock_cassiopeia):
        """listen_tasks() 시작 시 cassiopeia.connect() 호출."""
        async def _empty_gen():
            return
            yield

        mock_cassiopeia.listen.return_value = _empty_gen()
        await manager.listen_tasks()
        mock_cassiopeia.connect.assert_awaited_once()

    async def test_calls_cassiopeia_listen(self, manager, mock_cassiopeia):
        """listen_tasks()가 cassiopeia.listen()을 호출한다."""
        async def _empty_gen():
            return
            yield

        mock_cassiopeia.listen.return_value = _empty_gen()
        await manager.listen_tasks()
        mock_cassiopeia.listen.assert_called_once()

    async def test_calls_cassiopeia_disconnect_on_finish(self, manager, mock_cassiopeia):
        """listen_tasks() 종료 시 cassiopeia.disconnect() 호출."""
        async def _empty_gen():
            return
            yield

        mock_cassiopeia.listen.return_value = _empty_gen()
        await manager.listen_tasks()
        mock_cassiopeia.disconnect.assert_awaited_once()

    async def test_processes_valid_task(self, manager, mock_cassiopeia):
        """유효한 서명 태스크는 _safe_process_task()로 전달된다."""
        task = _signed_task("task-valid")
        sdk_msg = _make_sdk_message("user_request", task)

        async def _one_msg():
            yield sdk_msg

        mock_cassiopeia.listen.return_value = _one_msg()

        processed = []

        async def _capture(t):
            processed.append(t)

        manager._safe_process_task = _capture
        await manager.listen_tasks()
        # Allow event loop to run the created task
        await asyncio.sleep(0)
        assert len(processed) == 1
        assert processed[0]["task_id"] == "task-valid"

    async def test_invalid_hmac_pushes_to_dlq(self, fake_redis, mock_cassiopeia, mock_nlu, mock_state, mock_health):
        """서명 검증 실패 시 orchestra:dlq에 저장되고 태스크를 처리하지 않는다."""
        import os
        os.environ["DISPATCH_HMAC_SECRET"] = "test-secret"
        try:
            mgr = OrchestraManager(
                redis_client=fake_redis,
                nlu_engine=mock_nlu,
                state_manager=mock_state,
                health_monitor=mock_health,
                cassiopeia=mock_cassiopeia,
            )
            bad_task = {"task_id": "bad-task", "content": "hack", "_hmac": "invalid-sig"}
            sdk_msg = _make_sdk_message("user_request", bad_task)

            async def _one_msg():
                yield sdk_msg

            mock_cassiopeia.listen.return_value = _one_msg()
            processed = []
            mgr._safe_process_task = AsyncMock(side_effect=lambda t: processed.append(t))

            await mgr.listen_tasks()

            assert len(processed) == 0
            dlq_raw = await fake_redis.lrange("orchestra:dlq", 0, -1)
            assert len(dlq_raw) == 1
            dlq_entry = json.loads(dlq_raw[0])
            assert dlq_entry["reason"] == "INVALID_SIGNATURE"
        finally:
            del os.environ["DISPATCH_HMAC_SECRET"]

    async def test_does_not_use_blpop(self, manager, mock_cassiopeia, fake_redis):
        """listen_tasks()가 Redis blpop을 호출하지 않는다."""
        async def _empty_gen():
            return
            yield

        mock_cassiopeia.listen.return_value = _empty_gen()
        original_blpop = fake_redis.blpop
        called = []
        fake_redis.blpop = AsyncMock(side_effect=lambda *a, **kw: called.append(a))

        await manager.listen_tasks()
        assert len(called) == 0
        fake_redis.blpop = original_blpop


# ── _dispatch_to_agent ────────────────────────────────────────────────────────

class TestDispatchToAgentCassiopeia:
    async def test_calls_cassiopeia_send_message(self, manager, mock_cassiopeia):
        """_dispatch_to_agent()가 cassiopeia.send_message()를 호출한다."""
        dispatch = {
            "version": "1.1",
            "task_id": "task-001",
            "session_id": "sess-001",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "requester": {"user_id": "u1", "channel_id": "ch1"},
            "content": "",
            "agent": "file_agent",
            "action": "read_file",
            "params": {"path": "/tmp/x.txt"},
            "retry_info": {"count": 0, "max_retries": 3, "reason": None},
            "priority": "MEDIUM",
            "timeout": 60,
            "metadata": {},
        }
        await manager._dispatch_to_agent("file_agent", dispatch)
        mock_cassiopeia.send_message.assert_awaited_once()

    async def test_receiver_is_agent_name(self, manager, mock_cassiopeia):
        """cassiopeia.send_message(receiver=agent_name) 으로 전송된다."""
        dispatch = {
            "version": "1.1", "task_id": "t1", "session_id": "s1",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "requester": {}, "content": "",
            "agent": "schedule_agent", "action": "list_schedules",
            "params": {}, "retry_info": {}, "priority": "MEDIUM",
            "timeout": 60, "metadata": {},
        }
        await manager._dispatch_to_agent("schedule_agent", dispatch)
        call_kwargs = mock_cassiopeia.send_message.call_args.kwargs
        assert call_kwargs["receiver"] == "schedule_agent"

    async def test_action_from_dispatch_dict(self, manager, mock_cassiopeia):
        """cassiopeia action은 dispatch["action"] 값이다."""
        dispatch = {
            "version": "1.1", "task_id": "t1", "session_id": "s1",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "requester": {}, "content": "",
            "agent": "archive_agent", "action": "create_page",
            "params": {}, "retry_info": {}, "priority": "MEDIUM",
            "timeout": 60, "metadata": {},
        }
        await manager._dispatch_to_agent("archive_agent", dispatch)
        call_kwargs = mock_cassiopeia.send_message.call_args.kwargs
        assert call_kwargs["action"] == "create_page"

    async def test_payload_contains_dispatch_fields(self, manager, mock_cassiopeia):
        """payload에 task_id, params, action 등 dispatch 필드가 포함된다."""
        dispatch = {
            "version": "1.1", "task_id": "task-xyz", "session_id": "sess-abc",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "requester": {"user_id": "u2"}, "content": "do something",
            "agent": "file_agent", "action": "write_file",
            "params": {"path": "/out.txt", "content": "hello"},
            "retry_info": {"count": 0, "max_retries": 3, "reason": None},
            "priority": "MEDIUM", "timeout": 120, "metadata": {},
        }
        await manager._dispatch_to_agent("file_agent", dispatch)
        call_kwargs = mock_cassiopeia.send_message.call_args.kwargs
        payload = call_kwargs["payload"]
        assert payload["task_id"] == "task-xyz"
        assert payload["params"]["path"] == "/out.txt"

    async def test_does_not_use_rpush(self, manager, mock_cassiopeia, fake_redis):
        """_dispatch_to_agent()가 Redis rpush를 호출하지 않는다."""
        dispatch = {
            "version": "1.1", "task_id": "t1", "session_id": "s1",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "requester": {}, "content": "",
            "agent": "file_agent", "action": "read_file",
            "params": {}, "retry_info": {}, "priority": "MEDIUM",
            "timeout": 60, "metadata": {},
        }
        called = []
        original_rpush = fake_redis.rpush
        fake_redis.rpush = AsyncMock(side_effect=lambda *a, **kw: called.append(a))

        await manager._dispatch_to_agent("file_agent", dispatch)
        assert len(called) == 0
        fake_redis.rpush = original_rpush


# ── _send_to_comm_agent ───────────────────────────────────────────────────────

class TestSendToCommAgentCassiopeia:
    _TASK = {
        "task_id": "task-comm-001",
        "session_id": "sess-comm-001",
        "requester": {"user_id": "u1", "channel_id": "ch-1"},
        "content": "test",
        "source": "slack",
    }

    async def test_calls_cassiopeia_send_message(self, manager, mock_cassiopeia):
        """_send_to_comm_agent()가 cassiopeia.send_message()를 호출한다."""
        await manager._send_to_comm_agent(self._TASK, "응답 메시지", False, "file_agent")
        mock_cassiopeia.send_message.assert_awaited_once()

    async def test_receiver_is_communication(self, manager, mock_cassiopeia):
        """통신 에이전트로 전송할 때 receiver='communication' 이다."""
        await manager._send_to_comm_agent(self._TASK, "응답", False, "orchestra")
        kwargs = mock_cassiopeia.send_message.call_args.kwargs
        assert kwargs["receiver"] == "communication"

    async def test_payload_contains_content(self, manager, mock_cassiopeia):
        """payload에 content 메시지가 포함된다."""
        await manager._send_to_comm_agent(self._TASK, "최종 응답 메시지", False, "file_agent")
        kwargs = mock_cassiopeia.send_message.call_args.kwargs
        assert kwargs["payload"]["content"] == "최종 응답 메시지"

    async def test_does_not_rpush_to_agent_queue(self, manager, mock_cassiopeia, fake_redis):
        """_send_to_comm_agent()가 'agent:*:tasks' Redis List에 rpush하지 않는다."""
        agent_queue_calls = []
        original = fake_redis.rpush

        async def _track_rpush(key, *args, **kwargs):
            if "agent:" in str(key) and ":tasks" in str(key):
                agent_queue_calls.append(key)
            return await original(key, *args, **kwargs)

        fake_redis.rpush = _track_rpush
        await manager._send_to_comm_agent(self._TASK, "msg", False, "orchestra")
        assert len(agent_queue_calls) == 0
        fake_redis.rpush = original


# ── _send_progress_to_comm ────────────────────────────────────────────────────

class TestSendProgressToCommCassiopeia:
    _TASK = {
        "task_id": "task-prog-001",
        "session_id": "sess-prog-001",
        "requester": {"user_id": "u1", "channel_id": "ch-1"},
        "content": "test",
        "source": "api",
    }

    async def test_calls_cassiopeia_send_message(self, manager, mock_cassiopeia):
        """_send_progress_to_comm()가 cassiopeia.send_message()를 호출한다."""
        await manager._send_progress_to_comm(self._TASK, 50, "작업 중...")
        mock_cassiopeia.send_message.assert_awaited_once()

    async def test_receiver_is_communication(self, manager, mock_cassiopeia):
        """receiver가 'communication'이다."""
        await manager._send_progress_to_comm(self._TASK, 75, "거의 완료")
        kwargs = mock_cassiopeia.send_message.call_args.kwargs
        assert kwargs["receiver"] == "communication"

    async def test_payload_contains_progress_percent(self, manager, mock_cassiopeia):
        """payload에 progress_percent 값이 포함된다."""
        await manager._send_progress_to_comm(self._TASK, 30, "30% 완료")
        kwargs = mock_cassiopeia.send_message.call_args.kwargs
        assert kwargs["payload"]["progress_percent"] == 30

    async def test_does_not_rpush_to_agent_queue(self, manager, mock_cassiopeia, fake_redis):
        """_send_progress_to_comm()가 'agent:*:tasks' Redis List에 rpush하지 않는다."""
        agent_queue_calls = []
        original = fake_redis.rpush

        async def _track_rpush(key, *args, **kwargs):
            if "agent:" in str(key) and ":tasks" in str(key):
                agent_queue_calls.append(key)
            return await original(key, *args, **kwargs)

        fake_redis.rpush = _track_rpush
        await manager._send_progress_to_comm(self._TASK, 10, "시작")
        assert len(agent_queue_calls) == 0
        fake_redis.rpush = original
