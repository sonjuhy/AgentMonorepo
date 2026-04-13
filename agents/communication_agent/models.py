"""
Communication Agent 데이터 모델 (Python 3.12+)
"""

from typing import Any, TypedDict

# Python 3.12: PEP 695 Type Aliases
type RawPayload = dict[str, Any]
type PageId = str
type ExecutionResult = tuple[bool, str]
type SlackMessage = dict[str, Any]
type AgentName = str

# 에이전트 레지스트리: 에이전트 이름 → 역할 설명
AGENT_REGISTRY: dict[str, str] = {
    "archive_agent": "소프트웨어 기획, 요구사항 분석, 설계 문서 작성, 태스크 분해 요청을 처리합니다.",
    "slack_agent": "Slack 알림 발송, 메시지 전달 등 커뮤니케이션 요청을 처리합니다.",
}


class SlackEvent(TypedDict):
    """Slack Socket Mode에서 수신된 메시지 이벤트의 표준 데이터 구조"""
    user: str
    channel: str
    text: str
    ts: str
    thread_ts: str | None


class DiscordEvent(TypedDict):
    """Discord에서 수신된 메시지 이벤트의 표준 데이터 구조"""
    user_id: str            # Discord 사용자 ID (int → str 변환)
    channel_id: str         # 채널 또는 DM 채널 ID
    guild_id: str | None    # 서버 ID (DM이면 None)
    text: str
    message_id: str         # 메시지 ID (스레드 추적용)


class TelegramEvent(TypedDict):
    """Telegram에서 수신된 메시지 이벤트의 표준 데이터 구조"""
    user_id: str            # Telegram 사용자 ID (int → str 변환)
    chat_id: str            # 채팅 ID (그룹/개인)
    text: str
    message_id: str         # 메시지 ID (진행 메시지 추적용)


class ParsedTask(TypedDict):
    """파싱 완료된 노션 태스크의 표준 데이터 구조"""
    page_id: PageId
    title: str
    description: str
    status: str
    github_pr: str
    design_doc: str
    agent_assignees: list[str]
    assignees: list[str]
    skeleton_code: str
    priority: str
    last_edited_time: str
    task_type: str


# ── Redis 기반 메시지 브로커 스키마 ──────────────────────────────────────────────

class OrchestraTaskRequester(TypedDict):
    """오케스트라 태스크 요청자 정보"""
    user_id: str
    channel_id: str


class OrchestraTask(TypedDict):
    """소통 에이전트 → Redis → 오케스트라 전달 메시지 스키마"""
    task_id: str
    session_id: str        # 오케스트라 NLU 컨텍스트 주입용 (format: user_id:channel_id)
    requester: OrchestraTaskRequester
    content: str
    source: str            # 항상 "slack"
    thread_ts: str | None  # 스레드 루트 ts (세션 연속성용)


class OrchestraResult(TypedDict):
    """오케스트라 → Redis → 소통 에이전트 결과 메시지 스키마"""
    task_id: str
    content: str
    requires_user_approval: bool
    agent_name: str
    progress_percent: int | None  # None이면 완료, 0~99면 진행 중


class ApprovalFeedback(TypedDict):
    """사용자 [승인/수정 요청/취소] 버튼 클릭 피드백 스키마"""
    task_id: str
    action: str           # "approve" | "request_revision" | "cancel"
    user_id: str
    channel_id: str
    comment: str | None   # 수정 요청 시 입력된 텍스트
