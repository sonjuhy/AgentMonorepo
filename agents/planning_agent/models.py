"""
Planning Agent 데이터 모델 (Python 3.12+)
"""

from typing import Any, Literal, TypedDict

# Python 3.12: PEP 695 Type Aliases
type RawPayload = dict[str, Any]
type PageId = str
type ExecutionResult = tuple[bool, str]
type PlanningSource = Literal["notion", "obsidian", "direct"]
type PlanningAction = Literal["analyze_task", "create_plan", "update_task"]


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


# ── OrchestraManager DispatchMessage 연동 스키마 ───────────────────────────────

class PlanningTaskParams(TypedDict):
    """
    OrchestraManager가 DispatchMessage.params로 전달하는 planning_agent 전용 스키마.
    source에 따라 page_id(Notion) 또는 file_path(Obsidian) 중 하나가 채워진다.
    """
    source: PlanningSource       # "notion" | "obsidian" | "direct"
    page_id: str | None          # Notion page ID (source="notion")
    file_path: str | None        # Obsidian 절대 경로 (source="obsidian")
    title: str
    description: str
    task_type: str
    priority: str                # LOW | MEDIUM | HIGH | CRITICAL
    update_source: bool          # 처리 완료 후 원본(Notion/Obsidian) 업데이트 여부


class PlanningTaskResult(TypedDict):
    """
    AgentResult.result_data에 담길 planning_agent 전용 결과 스키마.
    OrchestraManager가 이 구조를 파싱하여 사용자에게 전달한다.
    """
    markdown_doc: str            # 생성된 전체 기획 마크다운
    page_id: str | None          # 업데이트된 Notion page ID (없으면 None)
    design_doc_preview: str      # markdown_doc 첫 300자 (Slack 미리보기용)
    source: PlanningSource       # 처리된 소스 타입
