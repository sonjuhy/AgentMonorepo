"""
TDD: SANDBOX_RUNTIME=disabled 지원 테스트

환경변수로 샌드박스를 완전히 비활성화할 수 있어야 한다.
비활성화 시 SandboxTool.start()가 예외 없이 완료되고,
execute_code()는 명확한 오류를 반환해야 한다.
"""
import pytest
import os
from unittest.mock import patch


class TestSandboxDisabled:

    def test_detect_runtime_returns_disabled(self):
        """SANDBOX_RUNTIME=disabled 이면 _detect_runtime() 이 'disabled' 를 반환한다."""
        from agents.orchestra_agent.sandbox_tool import _detect_runtime
        with patch.dict(os.environ, {"SANDBOX_RUNTIME": "disabled"}):
            assert _detect_runtime() == "disabled"

    @pytest.mark.asyncio
    async def test_start_does_not_raise_when_disabled(self):
        """disabled 모드에서 start() 가 예외 없이 완료된다."""
        from agents.orchestra_agent.sandbox_tool import SandboxTool
        with patch.dict(os.environ, {"SANDBOX_RUNTIME": "disabled"}):
            tool = SandboxTool()
            await tool.start()   # 예외 없어야 함

    @pytest.mark.asyncio
    async def test_execute_code_raises_when_disabled(self):
        """disabled 모드에서 execute_code() 는 RuntimeError 를 발생시킨다."""
        from agents.orchestra_agent.sandbox_tool import SandboxTool
        with patch.dict(os.environ, {"SANDBOX_RUNTIME": "disabled"}):
            tool = SandboxTool()
            await tool.start()
            with pytest.raises(RuntimeError, match="비활성화"):
                await tool.execute_code({"language": "python", "code": "print(1)"})

    @pytest.mark.asyncio
    async def test_shutdown_does_not_raise_when_disabled(self):
        """disabled 모드에서 shutdown() 이 예외 없이 완료된다."""
        from agents.orchestra_agent.sandbox_tool import SandboxTool
        with patch.dict(os.environ, {"SANDBOX_RUNTIME": "disabled"}):
            tool = SandboxTool()
            await tool.start()
            await tool.shutdown()

    def test_pool_stats_returns_disabled_info(self):
        """disabled 모드에서 pool_stats() 가 status=disabled 를 반환한다."""
        from agents.orchestra_agent.sandbox_tool import SandboxTool
        with patch.dict(os.environ, {"SANDBOX_RUNTIME": "disabled"}):
            tool = SandboxTool()
            stats = tool.pool_stats()
            assert stats["status"] == "disabled"

    def test_runtime_property_returns_disabled(self):
        """disabled 모드에서 runtime 프로퍼티가 'disabled' 를 반환한다."""
        from agents.orchestra_agent.sandbox_tool import SandboxTool
        with patch.dict(os.environ, {"SANDBOX_RUNTIME": "disabled"}):
            tool = SandboxTool()
            assert tool.runtime == "disabled"


class TestManagerWithDisabledSandbox:
    """OrchestraManager 가 sandbox=None 상태에서 sandbox 요청을 안전하게 거부한다."""

    @pytest.mark.asyncio
    async def test_run_sandbox_task_returns_failed_when_no_tool(
        self, fake_redis, nlu_engine, state_manager, health_monitor
    ):
        from agents.orchestra_agent.manager import OrchestraManager
        manager = OrchestraManager(
            redis_client=fake_redis,
            nlu_engine=nlu_engine,
            state_manager=state_manager,
            health_monitor=health_monitor,
            sandbox_tool=None,   # 비활성화 상태
        )
        result = await manager._run_sandbox_task("t1", {"language": "python", "code": "print(1)"})
        assert result["status"] == "FAILED"
        assert result["error"]["code"] == "SANDBOX_DISABLED"
