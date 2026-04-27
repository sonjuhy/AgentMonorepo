"""
VM 사전 워밍 풀 (VMPool)

보안 원칙: VM은 절대 재사용하지 않습니다.
- release() 시 기존 VM을 폐기하고 새 VM으로 보충
- min_ready개 VM을 항상 사전 부팅 상태로 유지
- max_size Semaphore로 동시 실행 수 제한
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from .models import SandboxRuntime
from .protocols import SandboxProtocol

logger = logging.getLogger("orchestra_agent.sandbox.pool")

_MIN_READY = int(os.environ.get("VM_POOL_MIN_READY", "3"))
_MAX_SIZE = int(os.environ.get("VM_POOL_MAX_SIZE", "10"))


class VMPool:
    """
    Firecracker/Docker VM 사전 워밍 풀.

    - start() 시 min_ready개 VM을 병렬로 미리 부팅
    - acquire(): 대기 중 VM 즉시 반환, 없으면 새로 생성
    - release(): VM 즉시 폐기 후 백그라운드에서 새 VM 보충
    - shutdown(): 모든 대기 VM 정리
    """

    def __init__(self, runtime: SandboxRuntime) -> None:
        self._runtime: SandboxRuntime = runtime
        self._ready: asyncio.Queue[SandboxProtocol] = asyncio.Queue()
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(_MAX_SIZE)
        self._active_count: int = 0
        self._min_ready: int = _MIN_READY
        self._max_size: int = _MAX_SIZE

    async def start(self) -> None:
        """min_ready개 VM을 병렬로 사전 부팅합니다."""
        logger.info(
            "[VMPool] 사전 워밍 시작: runtime=%s, min_ready=%d",
            self._runtime, self._min_ready,
        )
        tasks = [self._create_and_enqueue() for _ in range(self._min_ready)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success = sum(1 for r in results if not isinstance(r, Exception))
        failed = len(results) - success
        if failed:
            logger.warning("[VMPool] 사전 워밍 부분 실패: %d/%d", failed, len(results))
        logger.info("[VMPool] 사전 워밍 완료: %d개 준비됨", success)

    async def acquire(self) -> SandboxProtocol:
        """
        풀에서 VM을 대여합니다.

        풀이 비어있으면 새 VM을 즉시 생성합니다.
        max_size Semaphore로 최대 동시 실행 수를 제한합니다.
        """
        await self._semaphore.acquire()
        self._active_count += 1

        try:
            vm = self._ready.get_nowait()
            logger.debug("[VMPool] 풀에서 VM 대여: ready=%d", self._ready.qsize())
            return vm
        except asyncio.QueueEmpty:
            logger.debug("[VMPool] 풀 비어있음 — 새 VM 즉시 생성")
            try:
                vm = await self._create_vm()
                return vm
            except Exception:
                self._active_count -= 1
                self._semaphore.release()
                raise

    async def release(self, vm: SandboxProtocol) -> None:
        """
        VM을 즉시 폐기하고 백그라운드에서 새 VM으로 보충합니다.
        보안 원칙: 사용 완료된 VM은 절대 재사용하지 않습니다.
        """
        self._active_count = max(0, self._active_count - 1)
        self._semaphore.release()

        asyncio.create_task(self._close_vm(vm))
        asyncio.create_task(self._replenish())

    async def shutdown(self) -> None:
        """대기 중인 모든 VM을 정리합니다."""
        logger.info("[VMPool] 풀 종료 시작")
        close_tasks: list[asyncio.Task] = []

        while not self._ready.empty():
            try:
                vm = self._ready.get_nowait()
                close_tasks.append(asyncio.create_task(self._close_vm(vm)))
            except asyncio.QueueEmpty:
                break

        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

        logger.info("[VMPool] 풀 종료 완료")

    def stats(self) -> dict[str, Any]:
        """현재 풀 상태를 반환합니다."""
        return {
            "runtime": self._runtime,
            "ready_count": self._ready.qsize(),
            "active_count": self._active_count,
            "min_ready": self._min_ready,
            "max_size": self._max_size,
        }

    async def _create_vm(self) -> SandboxProtocol:
        """runtime에 따라 Firecracker 또는 Docker 샌드박스를 생성합니다."""
        if self._runtime == "firecracker":
            from .firecracker import FirecrackerSandbox
            vm = FirecrackerSandbox()
            await vm.start()
        elif self._runtime == "gvisor":
            from .docker_sandbox import DockerSandbox
            vm = DockerSandbox(use_gvisor=True)
        else:
            from .docker_sandbox import DockerSandbox
            vm = DockerSandbox(use_gvisor=False)
        return vm  # type: ignore[return-value]

    async def _create_and_enqueue(self) -> None:
        """VM을 생성하고 준비 큐에 추가합니다 (사전 워밍용)."""
        try:
            vm = await self._create_vm()
            await self._ready.put(vm)
        except Exception as exc:
            logger.error("[VMPool] VM 생성 실패: %s", exc)
            raise

    async def _replenish(self) -> None:
        """풀이 min_ready 미만이면 새 VM을 보충합니다."""
        needed = self._min_ready - self._ready.qsize()
        if needed <= 0:
            return

        logger.debug("[VMPool] 풀 보충: %d개 추가 예정", needed)
        tasks = [self._create_and_enqueue() for _ in range(needed)]
        await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    async def _close_vm(vm: SandboxProtocol) -> None:
        """VM을 안전하게 종료합니다."""
        try:
            await vm.close()
        except Exception as exc:
            logger.warning("[VMPool] VM 종료 실패 (vm_id=%s): %s", vm.vm_id, exc)
