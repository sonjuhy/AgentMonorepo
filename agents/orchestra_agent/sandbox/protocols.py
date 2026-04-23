"""
Sandbox 프로토콜 인터페이스 (Python 3.12+)
- 모든 인터페이스는 typing.Protocol로 정의 (ABC 미사용)
- 구현체: FirecrackerSandbox, DockerSandbox, VMPool
"""

from __future__ import annotations

from typing import Any, Protocol

from .models import ExecuteRequest, SandboxTaskResult


class SandboxProtocol(Protocol):
    """단일 샌드박스 실행 인터페이스 (Firecracker/Docker 공통)."""

    vm_id: str

    async def execute(self, req: ExecuteRequest) -> SandboxTaskResult:
        """격리된 환경에서 코드를 실행하고 결과를 반환합니다."""
        ...

    async def close(self) -> None:
        """샌드박스 자원(프로세스, 소켓, 네트워크)을 정리합니다."""
        ...


class VMPoolProtocol(Protocol):
    """VM 사전 워밍 풀 인터페이스."""

    async def start(self) -> None:
        """풀 초기화 및 min_ready개 VM 사전 부팅."""
        ...

    async def acquire(self) -> SandboxProtocol:
        """풀에서 준비된 VM을 대여합니다."""
        ...

    async def release(self, vm: SandboxProtocol) -> None:
        """사용 완료된 VM을 폐기하고 새 VM으로 보충합니다."""
        ...

    async def shutdown(self) -> None:
        """대기 중인 모든 VM을 정리하고 풀을 종료합니다."""
        ...

    def stats(self) -> dict[str, Any]:
        """ready_count, active_count, max_size, runtime 등 현재 상태를 반환합니다."""
        ...
