"""
Notion API 페이로드 파싱 모듈 (Notion-Version: 2022-06-28)
- notion-schema-expert 전략: 결정론적 안전한 Notion API 파싱
"""

from typing import Any

from ..models import ParsedTask, RawPayload


def parse_notion_task(payload: RawPayload) -> ParsedTask | None:
    """
    Notion API의 복잡한 JSON 페이로드(Notion-Version: 2022-06-28)에서 필요한 속성을 안전하게 추출합니다.

    Args:
        payload (RawPayload): Notion API로부터 반환된 단일 페이지 객체.

    Returns:
        ParsedTask | None: 파싱 성공 시 딕셔너리 반환, 필수 필드 누락/오류 시 None 반환.
    """
    try:
        page_id: str = payload["id"]
        properties: dict[str, Any] = payload.get("properties", {})

        # 안전한 중첩 구조 탐색 (IndexError, KeyError 방지)
        title_list: list[dict[str, Any]] = properties.get("제목", {}).get("title", [])
        title: str = title_list[0].get("plain_text", "제목 없음") if title_list else "제목 없음"

        desc_list: list[dict[str, Any]] = properties.get("목적", {}).get("rich_text", [])
        description: str = desc_list[0].get("plain_text", "") if desc_list else ""

        status_obj = properties.get("현황", {}).get("status")
        status: str = status_obj.get("name", "상태 미상") if isinstance(status_obj, dict) else "상태 미상"

        github_pr_obj = properties.get("GitHub PR", {})
        github_pr: str = github_pr_obj.get("url") if isinstance(github_pr_obj, dict) and github_pr_obj.get("url") else ""

        design_list = properties.get("기획안/설계도", {}).get("rich_text", [])
        design_doc: str = design_list[0].get("plain_text", "") if isinstance(design_list, list) and design_list else ""

        agent_list = properties.get("담당 에이전트", {}).get("multi_select", [])
        agent_assignees: list[str] = [a.get("name", "") for a in agent_list if isinstance(a, dict) and a.get("name")] if isinstance(agent_list, list) else []

        people_list = properties.get("담당자", {}).get("people", [])
        assignees: list[str] = [p.get("name", p.get("person", {}).get("email", "")) for p in people_list if isinstance(p, dict)] if isinstance(people_list, list) else []

        skeleton_list = properties.get("스켈레톤 코드", {}).get("rich_text", [])
        skeleton_code: str = skeleton_list[0].get("plain_text", "") if isinstance(skeleton_list, list) and skeleton_list else ""

        priority_obj = properties.get("우선순위", {}).get("select")
        priority: str = priority_obj.get("name", "") if isinstance(priority_obj, dict) else ""

        last_edited_time_obj = properties.get("최종 실행 시간", {})
        last_edited_time: str = last_edited_time_obj.get("last_edited_time", "") if isinstance(last_edited_time_obj, dict) else ""

        task_type_obj = properties.get("타입", {}).get("select")
        task_type: str = task_type_obj.get("name", "") if isinstance(task_type_obj, dict) else ""

        return ParsedTask(
            page_id=page_id,
            title=title,
            description=description,
            status=status,
            github_pr=github_pr,
            design_doc=design_doc,
            agent_assignees=agent_assignees,
            assignees=assignees,
            skeleton_code=skeleton_code,
            priority=priority,
            last_edited_time=last_edited_time,
            task_type=task_type,
        )
    except Exception as e:
        print(f"페이로드 파싱 실패: {e}")
        return None
