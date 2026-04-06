"""
Sandbox Agent 핵심 로직

OrchestraManager로부터 DispatchMessage를 수신하여
VMPool을 통해 격리된 환경에서 코드를 실행하고
AgentResult 형식으로 결과를 반환합니다.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from .models import ExecuteRequest, SandboxRuntime, SandboxTaskParams, SandboxTaskResult
from .pool import VMPool

logger = logging.getLogger("sandbox_agent.agent")


def _detect_runtime() -> SandboxRuntime:
    """
    실행 환경에 따라 적절한 runtime을 자동 결정합니다.

    - /dev/kvm 존재 → "firecracker" (KVM 하드웨어 가상화 가용)
    - 없음 → "docker" (폴백)
    """
    forced = os.environ.get("SANDBOX_RUNTIME")
    if forced in ("firecracker", "docker"):
        return forced  # type: ignore[return-value]

    if os.path.exists("/dev/kvm"):
        logger.info("[SandboxAgent] /dev/kvm 감지 → Firecracker 모드")
        return "firecracker"

    logger.info("[SandboxAgent] /dev/kvm 없음 → Docker 폴백 모드")
    return "docker"


class SandboxAgent:
    """
    격리 코드 실행 에이전트.

    - OrchestraManager가 보낸 DispatchMessage에서 SandboxTaskParams를 추출
    - VMPool을 통해 격리된 VM을 획득하고 코드를 실행
    - 결과를 AgentResult 형식으로 반환
    """

    def __init__(self) -> None:
        self._runtime: SandboxRuntime = _detect_runtime()
        self._pool: VMPool = VMPool(self._runtime)

    async def start(self) -> None:
        """VMPool을 초기화하고 VM을 사전 워밍합니다."""
        logger.info("[SandboxAgent] 시작 (runtime=%s)", self._runtime)
        await self._pool.start()

    async def handle_dispatch(self, dispatch_msg: dict[str, Any]) -> dict[str, Any]:
        """
        DispatchMessage를 처리하고 AgentResult를 반환합니다.

        Args:
            dispatch_msg: OrchestraManager가 push한 DispatchMessage (TypedDict 형식).
                          params 필드에 SandboxTaskParams가 포함됩니다.

        Returns:
            AgentResult 형식:
            {
                "task_id": str,
                "status": "COMPLETED" | "FAILED",
                "result_data": SandboxTaskResult,
                "error": AgentResultError | None,
                "usage_stats": dict,
            }
        """
        task_id: str = dispatch_msg.get("task_id", "unknown")
        params: dict[str, Any] = dispatch_msg.get("params", {})
        start_ms = time.monotonic()

        logger.info("[SandboxAgent] 태스크 수신: task_id=%s", task_id)

        try:
            exec_req = self._build_execute_request(params)
        except (KeyError, ValueError) as exc:
            return self._make_error_result(task_id, "INVALID_PARAMS", str(exc))

        vm = await self._pool.acquire()
        try:
            result: SandboxTaskResult = await vm.execute(exec_req)
            await self._pool.release(vm)
        except Exception as exc:
            await self._pool.release(vm)
            logger.error("[SandboxAgent] 실행 실패 task_id=%s: %s", task_id, exc)
            return self._make_error_result(task_id, "EXECUTION_ERROR", str(exc))

        elapsed_ms = int((time.monotonic() - start_ms) * 1000)
        logger.info(
            "[SandboxAgent] 실행 완료: task_id=%s exit_code=%d elapsed=%dms",
            task_id, result["exit_code"], elapsed_ms,
        )

        return {
            "task_id": task_id,
            "status": "COMPLETED",
            "result_data": dict(result),
            "error": None,
            "usage_stats": {"elapsed_ms": elapsed_ms, "runtime": self._runtime},
        }

    async def shutdown(self) -> None:
        """VMPool을 종료하고 모든 자원을 정리합니다."""
        logger.info("[SandboxAgent] 종료")
        await self._pool.shutdown()

    def pool_stats(self) -> dict[str, Any]:
        """VMPool 상태를 반환합니다."""
        return self._pool.stats()

    @property
    def runtime(self) -> SandboxRuntime:
        return self._runtime

    # ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_execute_request(params: dict[str, Any]) -> ExecuteRequest:
        """
        DispatchMessage.params → ExecuteRequest 변환.

        필수: language, code
        선택: stdin, timeout, memory_mb, env, runtime
        """
        if "code" not in params:
            raise ValueError("params에 'code' 필드가 없습니다")
        if "language" not in params:
            raise ValueError("params에 'language' 필드가 없습니다")

        return ExecuteRequest(
            language=params["language"],
            code=params["code"],
            stdin=params.get("stdin", ""),
            timeout=int(params.get("timeout", 30)),
            memory_mb=int(params.get("memory_mb", 256)),
            env=params.get("env", {}),
        )

    @staticmethod
    def _make_error_result(task_id: str, code: str, message: str) -> dict[str, Any]:
        return {
            "task_id": task_id,
            "status": "FAILED",
            "result_data": {},
            "error": {"code": code, "message": message, "traceback": None},
            "usage_stats": {},
        }
