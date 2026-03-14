"""
Planning Agent 데이터 모델 (Python 3.12+)
"""

from typing import Any, TypedDict

# Python 3.12: PEP 695 Type Aliases
type RawPayload = dict[str, Any]
type PageId = str
type ExecutionResult = tuple[bool, str]


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
