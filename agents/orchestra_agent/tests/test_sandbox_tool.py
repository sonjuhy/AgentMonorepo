"""
SandboxTool 단위 테스트 및 OrchestraManager 통합 테스트

[SandboxTool]
- execute_code(): 성공 / 필수 파라미터 누락 / VM 실행 오류 / release 보장
- start() / shutdown(): VMPool 위임 확인
- pool_stats(): VMPool.stats() 위임 확인

[OrchestraManager + SandboxTool]
- _execute_agent_task(): sandbox_agent → 직접 실행, 일반 에이전트 → Redis 경유
- _run_sandbox_task(): 성공 / INVALID_PARAMS / EXECUTION_ERROR 반환 포맷
- _is_internal_tool(): sandbox_tool 존재 여부에 따른 판별
- _route_single(): sandbox_agent는 헬스체크 우회
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ── SandboxTool 픽스처 ────────────────────────────────────────────────────────

@pytest.fixture
def mock_client():
    client = AsyncMock()
    # health()는 기본적으로 성공한다고 가정
    client.health.return_value = {"status": "ok"}
    return client


@pytest.fixture
def sandbox_tool(mock_client):
    with patch("agents.orchestra_agent.sandbox_tool.SandboxClient", return_value=mock_client):
        from agents.orchestra_agent.sandbox_tool import SandboxTool
        tool = SandboxTool()
        # __init__에서 생성된 _client를 mock으로 교체
        tool._client = mock_client
        return tool


def _make_result(stdout="Hello", stderr="", exit_code=0, runtime="docker", time_ms=50):
    # SandboxResult는 TypedDict이므로 dict와 유사한 구조
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "runtime_used": runtime,
        "execution_time_ms": time_ms,
    }


# ── SandboxTool.execute_code ──────────────────────────────────────────────────

class TestSandboxToolExecuteCode:
    async def test_success_returns_result(self, sandbox_tool, mock_client):
        mock_client.execute.return_value = _make_result(stdout="42\n")

        result = await sandbox_tool.execute_code({"language": "python", "code": "print(42)"})

        assert result["stdout"] == "42\n"
        assert result["exit_code"] == 0
        assert result["runtime_used"] == "docker"
        assert "execution_time_ms" in result

    async def test_missing_code_raises_value_error(self, sandbox_tool):
        with pytest.raises(ValueError, match="'code'"):
            await sandbox_tool.execute_code({"language": "python"})

    async def test_missing_language_raises_value_error(self, sandbox_tool):
        with pytest.raises(ValueError, match="'language'"):
            await sandbox_tool.execute_code({"code": "print(1)"})

    async def test_remote_error_raises_runtime_error(self, sandbox_tool, mock_client):
        from shared_core.sandbox.client import SandboxError
        mock_client.execute.side_effect = SandboxError("연결 실패")

        with pytest.raises(RuntimeError, match="샌드박스 실행 오류"):
            await sandbox_tool.execute_code({"language": "python", "code": "print(1)"})

    async def test_optional_params_passed_to_client(self, sandbox_tool, mock_client):
        mock_client.execute.return_value = _make_result()
        
        await sandbox_tool.execute_code({
            "language": "javascript",
            "code": "console.log(1)",
            "stdin": "input",
            "timeout": 10,
            "memory_mb": 512,
            "env": {"KEY": "VAL"}
        })

        mock_client.execute.assert_called_once_with(
            language="javascript",
            code="console.log(1)",
            stdin="input",
            timeout=10,
            memory_mb=512,
            env={"KEY": "VAL"}
        )


# ── SandboxTool lifecycle ────────────────────────────────────────────────────

class TestSandboxToolLifecycle:
    async def test_start_calls_health_check(self, sandbox_tool, mock_client):
        await sandbox_tool.start()
        mock_client.health.assert_called_once()

    async def test_shutdown_is_noop(self, sandbox_tool, mock_client):
        # 종료 시 원격 클라이언트는 특별한 동작을 하지 않음
        await sandbox_tool.shutdown()

    def test_pool_stats_returns_remote_info(self, sandbox_tool):
        stats = sandbox_tool.pool_stats()
        assert stats["status"] == "remote"
        assert "url" in stats

    def test_runtime_property(self, sandbox_tool):
        assert sandbox_tool.runtime == "remote"


# ── OrchestraManager + SandboxTool 통합 픽스처 ───────────────────────────────

@pytest.fixture
def sandbox_tool_mock():
    mock = AsyncMock()
    mock.execute_code = AsyncMock(return_value={
        "stdout": "42\n",
        "stderr": "",
        "exit_code": 0,
        "runtime_used": "docker",
        "execution_time_ms": 55,
    })
    return mock


@pytest_asyncio.fixture
async def manager_with_sandbox(fake_redis, nlu_engine, state_manager, health_monitor, sandbox_tool_mock):
    from agents.orchestra_agent.manager import OrchestraManager
    return OrchestraManager(
        redis_client=fake_redis,
        nlu_engine=nlu_engine,
        state_manager=state_manager,
        health_monitor=health_monitor,
        sandbox_tool=sandbox_tool_mock,
    )


@pytest_asyncio.fixture
async def manager_no_sandbox(fake_redis, nlu_engine, state_manager, health_monitor):
    from agents.orchestra_agent.manager import OrchestraManager
    return OrchestraManager(
        redis_client=fake_redis,
        nlu_engine=nlu_engine,
        state_manager=state_manager,
        health_monitor=health_monitor,
        sandbox_tool=None,
    )


_SANDBOX_DISPATCH = {
    "task_id": "t-sb",
    "params": {"language": "python", "code": "print(42)"},
    "agent": "sandbox_agent",
    "action": "execute_code",
    "session_id": "s-1",
    "requester": {},
    "timeout": 30,
    "version": "1.1",
    "timestamp": "2026-01-01T00:00:00Z",
    "content": "",
    "retry_info": {"count": 0, "max_retries": 3, "reason": None},
    "priority": "MEDIUM",
    "metadata": {},
}


# ── _is_internal_tool ────────────────────────────────────────────────────────

class TestIsInternalTool:
    def test_true_when_sandbox_tool_present(self, manager_with_sandbox):
        assert manager_with_sandbox._is_internal_tool("sandbox_agent") is True

    def test_false_when_sandbox_tool_absent(self, manager_no_sandbox):
        assert manager_no_sandbox._is_internal_tool("sandbox_agent") is False

    def test_false_for_other_agents(self, manager_with_sandbox):
        assert manager_with_sandbox._is_internal_tool("file_agent") is False
        assert manager_with_sandbox._is_internal_tool("archive_agent") is False


# ── _run_sandbox_task ────────────────────────────────────────────────────────

class TestRunSandboxTask:
    async def test_success_format(self, manager_with_sandbox, sandbox_tool_mock):
        result = await manager_with_sandbox._run_sandbox_task(
            "task-1", {"language": "python", "code": "print(42)"}
        )

        assert result["status"] == "COMPLETED"
        assert result["task_id"] == "task-1"
        assert result["result_data"]["stdout"] == "42\n"
        assert result["result_data"]["exit_code"] == 0
        assert "summary" in result["result_data"]
        assert result["result_data"]["content"] == "42\n"
        assert result["error"] is None

    async def test_invalid_params_returns_failed(self, manager_with_sandbox, sandbox_tool_mock):
        sandbox_tool_mock.execute_code.side_effect = ValueError("'code' 필드 없음")

        result = await manager_with_sandbox._run_sandbox_task("task-2", {"language": "python"})

        assert result["status"] == "FAILED"
        assert result["error"]["code"] == "INVALID_PARAMS"
        assert "'code'" in result["error"]["message"]

    async def test_execution_error_returns_failed(self, manager_with_sandbox, sandbox_tool_mock):
        sandbox_tool_mock.execute_code.side_effect = RuntimeError("VM 폭발")

        result = await manager_with_sandbox._run_sandbox_task(
            "task-3", {"language": "python", "code": "crash()"}
        )

        assert result["status"] == "FAILED"
        assert result["error"]["code"] == "EXECUTION_ERROR"
        assert "VM 폭발" in result["error"]["message"]

    async def test_usage_stats_included(self, manager_with_sandbox):
        result = await manager_with_sandbox._run_sandbox_task(
            "task-4", {"language": "python", "code": "pass"}
        )

        assert "runtime" in result["usage_stats"]
        assert result["usage_stats"]["runtime"] == "docker"


# ── _execute_agent_task ───────────────────────────────────────────────────────

class TestExecuteAgentTask:
    async def test_sandbox_bypasses_redis(self, manager_with_sandbox, sandbox_tool_mock, fake_redis):
        result = await manager_with_sandbox._execute_agent_task(
            "sandbox_agent", "task-sb-1", _SANDBOX_DISPATCH, timeout=30
        )

        sandbox_tool_mock.execute_code.assert_awaited_once()
        # Redis 큐에 아무것도 push되지 않아야 함
        queue_len = await fake_redis.llen("agent:sandbox_agent:tasks")
        assert queue_len == 0
        assert result["status"] == "COMPLETED"

    async def test_non_sandbox_uses_redis(self, manager_with_sandbox, fake_redis):
        dispatch = {**_SANDBOX_DISPATCH, "agent": "file_agent"}
        # 결과를 미리 Redis에 push해 두어야 wait_for_result가 반환함
        await fake_redis.rpush(
            "orchestra:results:task-redis",
            json.dumps({"task_id": "task-redis", "status": "COMPLETED", "result_data": {}, "error": None}),
        )

        result = await manager_with_sandbox._execute_agent_task(
            "file_agent", "task-redis", dispatch, timeout=5
        )

        assert result["status"] == "COMPLETED"
        queue_len = await fake_redis.llen("agent:file_agent:tasks")
        assert queue_len == 1  # Redis 큐에 dispatch 메시지가 쌓여 있어야 함

    async def test_sandbox_without_tool_uses_redis(self, manager_no_sandbox, fake_redis):
        await fake_redis.rpush(
            "orchestra:results:task-no-tool",
            json.dumps({"task_id": "task-no-tool", "status": "COMPLETED", "result_data": {}, "error": None}),
        )

        result = await manager_no_sandbox._execute_agent_task(
            "sandbox_agent", "task-no-tool", _SANDBOX_DISPATCH, timeout=5
        )

        assert result["status"] == "COMPLETED"
        queue_len = await fake_redis.llen("agent:sandbox_agent:tasks")
        assert queue_len == 1


# ── _route_single: sandbox_agent 헬스체크 우회 ───────────────────────────────

class TestRouteSingleSandboxBypass:
    async def test_sandbox_skips_health_check(self, manager_with_sandbox, sandbox_tool_mock, fake_redis):
        """sandbox_agent가 레지스트리에 없어도 (헬스체크 미통과) 직접 실행되어야 함.

        execute_code 는 APPROVAL_REQUIRED_ACTIONS 에 포함되므로 request_user_approval 을
        mock 처리해 즉시 승인 처리한다. 테스트의 핵심은 '헬스체크 없이 sandbox_tool 이 호출됨' 여부.
        """
        from agents.orchestra_agent.models import NLUMetadata, SingleNLUResult

        nlu_result = SingleNLUResult(
            type="single",
            intent="코드 실행",
            selected_agent="sandbox_agent",
            action="execute_code",
            params={"language": "python", "code": "print(1)"},
            metadata=NLUMetadata(reason="r", confidence_score=0.95, requires_user_approval=False),
        )

        _BASE_TASK = {
            "task_id": "task-hc-skip",
            "session_id": "sess-1",
            "requester": {"user_id": "u1", "channel_id": "ch1"},
            "content": "파이썬 실행",
            "source": "api",
        }

        # execute_code 는 서버사이드 강제 승인 대상이므로 request_user_approval 을 자동 승인으로 패치
        from unittest.mock import AsyncMock
        manager_with_sandbox.request_user_approval = AsyncMock(return_value=True)

        # sandbox_agent를 레지스트리에 등록하지 않음 → 일반 에이전트라면 NOT_FOUND 오류
        await manager_with_sandbox._route_single(nlu_result, _BASE_TASK)

        # sandbox_tool이 호출되어야 함 (헬스체크 실패로 종료되지 않음)
        sandbox_tool_mock.execute_code.assert_awaited_once()

    async def test_normal_agent_still_checks_health(self, manager_with_sandbox, fake_redis):
        """일반 에이전트는 여전히 헬스체크를 통과해야 함."""
        from agents.orchestra_agent.models import NLUMetadata, SingleNLUResult

        nlu_result = SingleNLUResult(
            type="single",
            intent="파일 읽기",
            selected_agent="file_agent",
            action="read_file",
            params={"path": "/tmp/a.txt"},
            metadata=NLUMetadata(reason="r", confidence_score=0.9, requires_user_approval=False),
        )

        _BASE_TASK = {
            "task_id": "task-hc-normal",
            "session_id": "sess-2",
            "requester": {"user_id": "u1", "channel_id": "ch1"},
            "content": "파일 읽기",
            "source": "api",
        }

        # file_agent 미등록 → 오류 메시지가 comm 큐에 전달되어야 함
        await manager_with_sandbox._route_single(nlu_result, _BASE_TASK)

        msg_raw = await fake_redis.lpop("agent:communication:tasks")
        assert msg_raw is not None
        msg = json.loads(msg_raw)
        assert "file_agent" in msg["content"]
