"""
Sandbox Agent 데이터 모델 (Python 3.12+)
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
    """DispatchMessage.params 스키마 (OrchestraManager → Sandbox Agent)"""
    runtime: SandboxRuntime          # "firecracker" | "docker"
    language: str                    # "python" | "javascript" | "bash" | ...
    code: str                        # 실행할 코드 문자열
    stdin: str                       # 표준 입력 (빈 문자열 가능)
    timeout: int                     # 실행 제한 시간(초), 기본 30
    memory_mb: int                   # 메모리 제한(MB), 기본 256
    env: dict[str, str]             # 추가 환경변수


class SandboxTaskResult(TypedDict):
    """AgentResult.result_data 스키마"""
    stdout: str
    stderr: str
    exit_code: int
    runtime_used: SandboxRuntime
    execution_time_ms: int


class VMInfo(TypedDict):
    """풀 내 VM 상태 정보 (stats() 반환값)"""
    vm_id: str
    runtime: SandboxRuntime
    status: SandboxStatus
    created_at: str                  # ISO 8601
    vsock_path: str | None           # firecracker only
    container_id: str | None         # docker only


# ── Pydantic 모델 (FastAPI 요청 바디 / 내부 실행 요청) ─────────────────────────

class DirectExecuteRequest(BaseModel):
    """POST /execute 요청 바디 — Redis 우회 직접 실행용."""
    task_id: str
    params: dict[str, Any]


class ExecuteRequest(BaseModel):
    """에이전트 내부 실행 요청 — VMPool.acquire() 후 sandbox.execute()에 전달."""
    language: str
    code: str
    stdin: str = ""
    timeout: int = Field(default=30, ge=1, le=300)
    memory_mb: int = Field(default=256, ge=64, le=4096)
    env: dict[str, str] = Field(default_factory=dict)
