"""
SandboxTool — 오케스트라 내부 코드 실행 도구

sandbox_agent의 VMPool/DockerSandbox/FirecrackerSandbox를 인프로세스로 직접 구동합니다.
Redis 큐 통신이나 HTTP 보고 없이 OrchestraManager에서 직접 호출됩니다.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from .sandbox.pool import VMPool
from .sandbox.models import ExecuteRequest, SandboxRuntime

logger = logging.getLogger("orchestra_agent.sandbox_tool")


def _detect_runtime() -> SandboxRuntime:
    forced = os.environ.get("SANDBOX_RUNTIME")
    if forced in ("firecracker", "docker"):
        return forced  # type: ignore[return-value]
    if os.path.exists("/dev/kvm"):
        logger.info("[SandboxTool] /dev/kvm 감지 → Firecracker 모드")
        return "firecracker"
    logger.info("[SandboxTool] /dev/kvm 없음 → Docker 폴백 모드")
    return "docker"


class SandboxTool:
    """
    오케스트라 내부 코드 실행 도구.

    OrchestraManager가 sandbox_agent 작업을 Redis 큐 대신 직접 호출합니다.
    VMPool을 보유하여 VM 사전 워밍과 동시성 제한을 유지합니다.
    """

    def __init__(self) -> None:
        self._runtime: SandboxRuntime = _detect_runtime()
        self._pool: VMPool = VMPool(self._runtime)

    async def start(self) -> None:
        """VMPool을 초기화하고 VM을 사전 워밍합니다."""
        logger.info("[SandboxTool] 시작 (runtime=%s)", self._runtime)
        await self._pool.start()

    async def execute_code(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        격리된 VM에서 코드를 실행하고 결과를 반환합니다.

        Args:
            params: language, code 필수; stdin, timeout, memory_mb, env 선택

        Returns:
            stdout, stderr, exit_code, runtime_used, execution_time_ms

        Raises:
            ValueError: 필수 파라미터(language, code) 누락
            Exception: VM 실행 오류
        """
        if "code" not in params:
            raise ValueError("params에 'code' 필드가 없습니다")
        if "language" not in params:
            raise ValueError("params에 'language' 필드가 없습니다")

        req = ExecuteRequest(
            language=params["language"],
            code=params["code"],
            stdin=params.get("stdin", ""),
            timeout=int(params.get("timeout", 30)),
            memory_mb=int(params.get("memory_mb", 256)),
            env=params.get("env", {}),
        )

        start_ms = time.monotonic()
        vm = await self._pool.acquire()
        try:
            result = await vm.execute(req)
        finally:
            await self._pool.release(vm)

        elapsed_ms = int((time.monotonic() - start_ms) * 1000)
        logger.info(
            "[SandboxTool] 실행 완료: exit_code=%d elapsed=%dms",
            result["exit_code"], elapsed_ms,
        )
        return {
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "exit_code": result["exit_code"],
            "runtime_used": result["runtime_used"],
            "execution_time_ms": elapsed_ms,
        }

    async def shutdown(self) -> None:
        """VMPool을 종료하고 모든 자원을 정리합니다."""
        logger.info("[SandboxTool] 종료")
        await self._pool.shutdown()

    def pool_stats(self) -> dict[str, Any]:
        return self._pool.stats()

    @property
    def runtime(self) -> SandboxRuntime:
        return self._runtime
