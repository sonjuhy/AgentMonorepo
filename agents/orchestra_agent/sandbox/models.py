"""
Sandbox 데이터 모델 (Python 3.12+)
- 실행 요청/결과 스키마 (TypedDict: 내부 타입 힌트용)
- VM 상태 스키마 (TypedDict)
- FastAPI 요청 바디 (Pydantic v2)
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


# Python 3.12+ type alias
type SandboxRuntime = Literal["firecracker", "docker"]
type SandboxStatus = Literal["IDLE", "BUSY", "STARTING", "ERROR"]
type TaskStatus = Literal["COMPLETED", "FAILED", "TIMEOUT"]


# ── TypedDict 스키마 ──────────────────────────────────────────────────────────

class SandboxTaskParams(TypedDict):
    """실행 요청 파라미터 스키마"""
    runtime: SandboxRuntime
    language: str
    code: str
    stdin: str
    timeout: int
    memory_mb: int
    env: dict[str, str]


class SandboxTaskResult(TypedDict):
    """실행 결과 스키마"""
    stdout: str
    stderr: str
    exit_code: int
    runtime_used: SandboxRuntime
    execution_time_ms: int


class VMInfo(TypedDict):
    """풀 내 VM 상태 정보"""
    vm_id: str
    runtime: SandboxRuntime
    status: SandboxStatus
    created_at: str
    vsock_path: str | None
    container_id: str | None


# ── Pydantic 모델 ─────────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    """에이전트 내부 실행 요청 — VMPool.acquire() 후 sandbox.execute()에 전달."""
    language: str
    code: str
    stdin: str = ""
    timeout: int = Field(default=30, ge=1, le=300)
    memory_mb: int = Field(default=256, ge=64, le=4096)
    env: dict[str, str] = Field(default_factory=dict)
