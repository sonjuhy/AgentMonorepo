"""
오케스트라 에이전트 데이터 모델 (Python 3.12+)
- NLU 결과 스키마 (Pydantic v2: 구조 검증용)
- Redis 통신 메시지 스키마 (TypedDict: 내부 타입 힌트용)
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


# ── NLU 출력 스키마 (Pydantic - 검증 필수) ────────────────────────────────────

class NLUMetadata(BaseModel):
    """NLU 결과 메타데이터"""
    reason: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    requires_user_approval: bool = False


class PlanStepMetadata(BaseModel):
    """복합 작업 단계 메타데이터"""
    reason: str
    requires_user_approval: bool = False


class PlanStep(BaseModel):
    """복합 작업 단일 실행 단계"""
    step: int
    selected_agent: str
    action: str
    params: dict[str, Any]
    depends_on: list[int] = Field(default_factory=list)
    metadata: PlanStepMetadata


class SingleNLUResult(BaseModel):
    """단일 에이전트 작업 NLU 결과"""
    type: Literal["single"]
    intent: str
    selected_agent: str
    action: str
    params: dict[str, Any]
    metadata: NLUMetadata


class MultiStepNLUResult(BaseModel):
    """복합 작업 NLU 결과"""
    type: Literal["multi_step"]
    intent: str
    plan: list[PlanStep]
    metadata: NLUMetadata


class ClarificationParams(BaseModel):
    """추가 질문 파라미터"""
    question: str
    options: list[str] = Field(default_factory=list)


class ClarificationNLUResult(BaseModel):
    """추가 질문 NLU 결과 (confidence < 0.7 또는 정보 부족)"""
    type: Literal["clarification"]
    intent: str
    selected_agent: Literal["communication_agent"]
    action: Literal["ask_clarification"]
    params: ClarificationParams
    metadata: NLUMetadata


# NLU 결과 타입 유니온
NLUResult = SingleNLUResult | MultiStepNLUResult | ClarificationNLUResult

# 신뢰도 임계값
NLU_CONFIDENCE_THRESHOLD = 0.7


# ── Redis 통신 메시지 스키마 (TypedDict) ──────────────────────────────────────

class TaskRequester(TypedDict):
    """작업 요청자 정보"""
    user_id: str
    channel_id: str


class OrchestraTask(TypedDict):
    """소통 에이전트 → 오케스트라 작업 요청 (agent:orchestra:tasks 큐)"""
    task_id: str
    session_id: str        # NLU 컨텍스트 주입용 (format: user_id:channel_id)
    requester: TaskRequester
    content: str
    source: str            # 항상 "slack"
    thread_ts: str | None


class RetryInfo(TypedDict):
    """재시도 정보"""
    count: int
    max_retries: int
    reason: str | None


class DispatchMessage(TypedDict):
    """오케스트라 → 하위 에이전트 작업 지시서 (agent:{name}:tasks 큐)"""
    version: str
    task_id: str
    session_id: str
    timestamp: str
    requester: TaskRequester
    agent: str
    action: str
    params: dict[str, Any]
    retry_info: RetryInfo
    priority: str          # LOW | MEDIUM | HIGH | CRITICAL
    timeout: int           # 초 단위
    metadata: dict[str, Any]


class AgentResultError(TypedDict):
    """에이전트 실행 오류"""
    code: str
    message: str
    traceback: str | None


class AgentResult(TypedDict):
    """하위 에이전트 → 오케스트라 결과 (orchestra:results:{task_id} 큐)"""
    task_id: str
    status: str            # COMPLETED | FAILED | WAITING_USER | PROCESSING
    result_data: dict[str, Any]
    error: AgentResultError | None
    usage_stats: dict[str, Any]


class AgentHealth(TypedDict):
    """에이전트 헬스 정보 (agent:{name}:health Redis Hash)"""
    agent_id: str
    status: str            # IDLE | BUSY | MAINTENANCE | ERROR
    last_heartbeat: str    # ISO 8601
    version: str
    capabilities: list[str]
    current_tasks: int
    max_concurrency: int


class CommAgentMessage(TypedDict):
    """오케스트라 → 소통 에이전트 전달 메시지 (agent:communication:tasks 큐)"""
    task_id: str                    # 승인 task_id (orchestra:approval:{task_id} 응답용)
    content: str                    # 마크다운 본문
    requires_user_approval: bool
    agent_name: str
    progress_percent: int | None    # None = 최종 결과, 0~99 = 진행 중


# 에이전트 레지스트리: 에이전트 이름 → 기본 timeout(초)
AGENT_TIMEOUT_MAP: dict[str, int] = {
    "coding_agent": 600,
    "planning_agent": 300,
    "research_agent": 300,
    "calendar_agent": 60,
    "file_agent": 120,
    "archive_agent": 120,
    "communication_agent": 30,
    "sandbox_agent": 60,
    "agent_builder": 120,   # 로컬 빌드 (패키지 검증 포함), Redis 큐 미사용
}

# 재시도 가능한 에러 코드
RETRYABLE_ERROR_CODES: frozenset[str] = frozenset({
    "TIMEOUT", "RATE_LIMIT", "EXTERNAL_API_ERROR", "INTERNAL_ERROR", "EXECUTION_ERROR"
})
