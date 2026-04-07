"""
Planning Agent 구체 구현체
- Notion API 연동 및 태스크 처리 로직
- ephemeral-docker-ops 전략: 단발성 실행 후 자연 종료
- v2: handle_dispatch() 추가 — OrchestraManager DispatchMessage 처리
"""

import os
import traceback
from typing import Any

import httpx

from ..models import (
    ExecutionResult,
    ParsedTask,
    PlanningTaskParams,
    PlanningTaskResult,
    RawPayload,
)
from .notion_parser import parse_notion_task
from .task_analyzer import ClaudeAPITaskAnalyzer, TaskAnalyzerProtocol

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class PlanningAgent:
    """
    PlanningAgentProtocol의 구체 구현체.
    환경 변수에서 Notion 인증 정보를 읽어 API를 호출합니다.
    """

    agent_name: str = "planning-agent"

    def __init__(self, task_analyzer: TaskAnalyzerProtocol | None = None) -> None:
        self._token: str = os.environ["NOTION_TOKEN"]
        self._database_id: str = os.environ["NOTION_DATABASE_ID"]
        self._headers: dict[str, str] = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        self.task_analyzer = task_analyzer or ClaudeAPITaskAnalyzer()

    async def fetch_pending_tasks(self) -> list[RawPayload]:
        """
        Notion 데이터베이스에서 기획 단계('검토중') 상태의 작업 목록을 조회합니다.

        Returns:
            list[RawPayload]: 파싱되기 전의 Notion API JSON 리스트.
        """
        url = f"{NOTION_API_BASE}/databases/{self._database_id}/query"
        body = {
            "filter": {
                "property": "현황",
                "status": {"equals": "검토중"},
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=self._headers, json=body)
            response.raise_for_status()
            data = response.json()

        return data.get("results", [])

    async def update_notion_task(
        self,
        page_id: str,
        status: str | None = None,
        agent_names: list[str] | None = None,
        design_doc: str | None = None,
        skeleton_code: str | None = None,
        github_pr_url: str | None = None,
    ) -> ExecutionResult:
        """
        Notion API를 사용하여 지정된 페이지(태스크)의 속성을 업데이트합니다.

        Args:
            page_id (str): 업데이트할 노션 페이지 ID
            status (str | None): 변경할 '현황' 상태 (예: '기획 중', '완료' 등)
            agent_names (list[str] | None): '담당 에이전트' Multi-select 옵션 이름 목록
            design_doc (str | None): '기획안/설계도' Rich text 내용
            skeleton_code (str | None): '스켈레톤 코드' Rich text 내용
            github_pr_url (str | None): 'GitHub PR' URL

        Returns:
            ExecutionResult: (성공 여부, 처리 결과 메시지)
        """
        url = f"{NOTION_API_BASE}/pages/{page_id}"
        properties: dict[str, Any] = {}

        if status is not None:
            properties["현황"] = {"status": {"name": status}}

        if agent_names is not None:
            properties["담당 에이전트"] = {"multi_select": [{"name": name} for name in agent_names]}

        if design_doc is not None:
            properties["기획안/설계도"] = {"rich_text": [{"text": {"content": design_doc}}]}

        if skeleton_code is not None:
            properties["스켈레톤 코드"] = {"rich_text": [{"text": {"content": skeleton_code}}]}

        if github_pr_url is not None:
            properties["GitHub PR"] = {"url": github_pr_url}

        if not properties:
            return (False, "업데이트할 속성이 제공되지 않았습니다.")

        body = {"properties": properties}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.patch(url, headers=self._headers, json=body)
                response.raise_for_status()
            return (True, f"페이지 업데이트 성공: {page_id}")
        except httpx.HTTPStatusError as e:
            return (False, f"Notion API 에러: {e.response.text}")
        except Exception as e:
            return (False, f"업데이트 실패: {e}")

    async def process_task(self, task_data: ParsedTask) -> ExecutionResult:
        """
        개별 기획 태스크를 처리합니다.
        문서 생성기를 통해 요구사항을 세분화하여 Markdown 파일과 Notion 기획안 속성을 갱신합니다.

        Args:
            task_data (ParsedTask): 파싱 완료된 작업 데이터.

        Returns:
            ExecutionResult: (성공 여부, 처리 결과 메시지)
        """
        try:
            print(
                f"[{self.agent_name}] 처리 중: [{task_data['status']}] {task_data['title']}"
            )
            if task_data["description"]:
                print(f"  목적: {task_data['description']}")

            # 1. 마크다운 생성 (목표, 과정, 결과 - 기능/조립도/출력)
            markdown_doc = await self.task_analyzer.analyze_task(task_data)
            
            # 2. 로컬 MD 파일 저장 (또는 CLI나 LLM으로 생성된 최종 결과물 보관)
            file_name = f"task_{task_data['page_id']}.md"
            with open(file_name, "w", encoding="utf-8") as file:
                file.write(markdown_doc)
            print(f"[{self.agent_name}] 상세 기획 마크다운 작성 완료: {file_name}")

            # 3. Notion 업데이트
            # 기획안/설계도에 markdown_doc 전체를 업데이트
            # 실제 DB 상태 옵션(hex 검증): 검토중 → 승인 대기중 → 완료
            update_success, update_msg = await self.update_notion_task(
                page_id=task_data["page_id"],
                status="승인 대기중",
                design_doc=markdown_doc
            )

            if update_success:
                return (True, f"태스크 처리 및 노션 업데이트 완료: {task_data['page_id']}")
            else:
                return (False, f"태스크 처리 완료하지만 노션 업데이트 실패: {update_msg}")
            
        except Exception as e:
            return (False, f"태스크 처리 실패: {e}")

    async def run(self) -> None:
        """
        에이전트 사이클의 진입점.
        작업 조회 → 파싱 → 처리 후 자연 종료합니다.
        (ephemeral-docker-ops 전략 준수: while True / asyncio.sleep 반복 금지)
        """
        print(f"[{self.agent_name}] 실행 시작")

        raw_tasks = await self.fetch_pending_tasks()
        print(f"[{self.agent_name}] 조회된 태스크 수: {len(raw_tasks)}")

        for raw in raw_tasks:
            task = parse_notion_task(raw)
            if task is None:
                continue

            success, message = await self.process_task(task)
            status_label = "완료" if success else "실패"
            print(f"[{self.agent_name}] {status_label}: {message}")

        print(f"[{self.agent_name}] 실행 종료")

    async def handle_dispatch(
        self,
        dispatch_msg: dict[str, Any],
    ) -> dict[str, Any]:
        """
        OrchestraManager가 보낸 DispatchMessage를 처리하여 AgentResult 형식으로 반환합니다.

        DispatchMessage.params는 PlanningTaskParams 구조를 따릅니다:
        - source: "notion" → page_id 기반 Notion 태스크 처리
        - source: "direct" → title/description 직접 분석

        Args:
            dispatch_msg: OrchestraManager DispatchMessage TypedDict (dict).

        Returns:
            AgentResult 호환 딕셔너리:
            {task_id, status, result_data: PlanningTaskResult, error, usage_stats}
        """
        task_id: str = dispatch_msg.get("task_id", "unknown")
        params: dict[str, Any] = dispatch_msg.get("params", {})

        try:
            # DispatchMessage.params → ParsedTask 변환
            parsed: ParsedTask = {
                "page_id": params.get("page_id") or "",
                "title": params.get("title", ""),
                "description": params.get("description", ""),
                "status": "검토중",
                "github_pr": "",
                "design_doc": "",
                "agent_assignees": ["planning-agent"],
                "assignees": [],
                "skeleton_code": "",
                "priority": params.get("priority", ""),
                "last_edited_time": "",
                "task_type": params.get("task_type", ""),
            }

            print(f"[{self.agent_name}] dispatch 처리: task_id={task_id}, title={parsed['title']}")

            # LLM 분석 → 마크다운 생성
            markdown_doc = await self.task_analyzer.analyze_task(parsed)

            # Notion 업데이트 (update_source=True + page_id 있을 때)
            updated_page_id: str | None = None
            if params.get("update_source") and parsed["page_id"]:
                update_ok, _ = await self.update_notion_task(
                    page_id=parsed["page_id"],
                    status="승인 대기중",
                    design_doc=markdown_doc,
                )
                if update_ok:
                    updated_page_id = parsed["page_id"]

            result_data: PlanningTaskResult = {
                "markdown_doc": markdown_doc,
                "page_id": updated_page_id,
                "design_doc_preview": markdown_doc[:300],
                "source": params.get("source", "direct"),
            }

            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "result_data": result_data,
                "error": None,
                "usage_stats": {},
            }

        except Exception as exc:
            return {
                "task_id": task_id,
                "status": "FAILED",
                "result_data": {},
                "error": {
                    "code": "EXECUTION_ERROR",
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                },
                "usage_stats": {},
            }
