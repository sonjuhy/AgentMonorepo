"""
Archive Agent 데이터 모델 (Python 3.12+)
- 기획 중심에서 데이터 조회/반환(Retrieval) 중심으로 변경
"""

from typing import Any, Literal, TypedDict

# Python 3.12: PEP 695 Type Aliases
type RawPayload = dict[str, Any]
type PageId = str
type ExecutionResult = tuple[bool, str]
type ArchiveSource = Literal["notion", "obsidian", "direct"]
type ArchiveAction = Literal["get_page", "query_database", "search", "read_file", "analyze_task", "list_databases", "get_database_schema"]


class ParsedTask(TypedDict):
    """파싱 완료된 노션/옵시디언 태스크의 표준 데이터 구조"""
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

class ArchiveTaskParams(TypedDict):
    """
    OrchestraManager가 DispatchMessage.params로 전달하는 archive_agent 전용 스키마.
    """
    source: ArchiveSource        # "notion" | "obsidian" | "direct"
    action: ArchiveAction        # "get_page" | "query_database" | "search" | "read_file"
    
    # 조회 조건
    page_id: str | None          # Notion page ID 또는 Obsidian 상대 경로
    database_id: str | None      # Notion Database ID
    query: str | None            # 검색어 또는 필터 조건
    
    # 기존 기획 연동용 (하위 호환)
    title: str | None
    description: str | None
    update_source: bool          # 처리 완료 후 원본 업데이트 여부


class ArchiveTaskResult(TypedDict):
    """
    AgentResult.result_data에 담길 archive_agent 전용 결과 스키마.
    """
    status: str                  # "success" | "error"
    source: ArchiveSource
    action: ArchiveAction
    
    # 반환 데이터
    raw_data: Any | None         # API 응답 원본 (JSON 등)
    content: str | None          # 텍스트/마크다운 내용
    summary: str                 # 요약 메시지
    
    # 부가 정보
    metadata: dict[str, Any]
