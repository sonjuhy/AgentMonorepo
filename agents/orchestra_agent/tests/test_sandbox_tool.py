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
def mock_pool():
    pool = AsyncMock()
    # stats()는 동기 메서드 → MagicMock으로 교체
    pool.stats = MagicMock(return_value={"ready_count": 3, "active_count": 0, "max_size": 10, "runtime": "docker"})
    return pool


@pytest.fixture
def sandbox_tool(mock_pool):
    with patch("agents.orchestra_agent.sandbox_tool.VMPool", return_value=mock_pool):
        from agents.orchestra_agent.sandbox_tool import SandboxTool
        tool = SandboxTool()
        tool._pool = mock_pool
        return tool


def _make_vm(stdout="Hello", stderr="", exit_code=0, runtime="docker", time_ms=50):
    vm = AsyncMock()
    vm.vm_id = "test-vm-id"
    vm.execute.return_value = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "runtime_used": runtime,
        "execution_time_ms": time_ms,
    }
    return vm


# ── SandboxTool.execute_code ──────────────────────────────────────────────────

class TestSandboxToolExecuteCode:
    async def test_success_returns_result(self, sandbox_tool, mock_pool):
        vm = _make_vm(stdout="42\n")
        mock_pool.acquire = AsyncMock(return_value=vm)
        mock_pool.release = AsyncMock()

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

    async def test_release_called_on_success(self, sandbox_tool, mock_pool):
        vm = _make_vm()
        mock_pool.acquire = AsyncMock(return_value=vm)
        mock_pool.release = AsyncMock()

        await sandbox_tool.execute_code({"language": "python", "code": "print(1)"})

        mock_pool.release.assert_called_once_with(vm)

    async def test_release_called_on_vm_error(self, sandbox_tool, mock_pool):
        vm = _make_vm()
        vm.execute.side_effect = RuntimeError("VM 충돌")
        mock_pool.acquire = AsyncMock(return_value=vm)
        mock_pool.release = AsyncMock()

        with pytest.raises(RuntimeError, match="VM 충돌"):
            await sandbox_tool.execute_code({"language": "python", "code": "crash"})

        mock_pool.release.assert_called_once_with(vm)

    async def test_optional_params_defaults(self, sandbox_tool, mock_pool):
        vm = _make_vm()
        mock_pool.acquire = AsyncMock(return_value=vm)
        mock_pool.release = AsyncMock()

        await sandbox_tool.execute_code({"language": "python", "code": "pass"})

        req_arg = vm.execute.call_args[0][0]
        assert req_arg.timeout == 30
        assert req_arg.memory_mb == 256
        assert req_arg.stdin == ""
        assert req_arg.env == {}

    async def test_custom_params_forwarded(self, sandbox_tool, mock_pool):
        vm = _make_vm()
        mock_pool.acquire = AsyncMock(return_value=vm)
        mock_pool.release = AsyncMock()

        await sandbox_tool.execute_code({
            "language": "python",
            "code": "pass",
            "timeout": 60,
            "memory_mb": 512,
            "stdin": "input",
            "env": {"KEY": "VAL"},
        })

        req_arg = vm.execute.call_args[0][0]
        assert req_arg.timeout == 60
        assert req_arg.memory_mb == 512
        assert req_arg.stdin == "input"
        assert req_arg.env == {"KEY": "VAL"}


# ── SandboxTool lifecycle ────────────────────────────────────────────────────

class TestSandboxToolLifecycle:
    async def test_start_calls_pool_start(self, sandbox_tool, mock_pool):
        await sandbox_tool.start()
        mock_pool.start.assert_awaited_once()

    async def test_shutdown_calls_pool_shutdown(self, sandbox_tool, mock_pool):
        await sandbox_tool.shutdown()
        mock_pool.shutdown.assert_awaited_once()

    def test_pool_stats_delegates_to_pool(self, sandbox_tool, mock_pool):
        stats = sandbox_tool.pool_stats()
        assert stats["ready_count"] == 3
        mock_pool.stats.assert_called_once()

    def test_runtime_property(self, sandbox_tool):
        assert sandbox_tool.runtime in ("docker", "firecracker")


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
        """sandbox_agent가 레지스트리에 없어도 (헬스체크 미통과) 직접 실행되어야 함."""
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
