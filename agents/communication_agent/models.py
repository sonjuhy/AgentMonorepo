"""
Slack Agent 데이터 모델 (Python 3.12+)
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
    "planning_agent": "소프트웨어 기획, 요구사항 분석, 설계 문서 작성, 태스크 분해 요청을 처리합니다.",
    "slack_agent": "Slack 알림 발송, 메시지 전달 등 커뮤니케이션 요청을 처리합니다.",
}


class SlackEvent(TypedDict):
    """Slack Socket Mode에서 수신된 메시지 이벤트의 표준 데이터 구조"""
    user: str
    channel: str
    text: str
    ts: str
    thread_ts: str | None


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
