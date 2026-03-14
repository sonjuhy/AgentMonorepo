"""
Planning Agent 구체 구현체
- Notion API 연동 및 태스크 처리 로직
- ephemeral-docker-ops 전략: 단발성 실행 후 자연 종료
"""

import os
from typing import Any

import httpx

from .models import ExecutionResult, ParsedTask, RawPayload
from .notion_parser import parse_notion_task

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class PlanningAgent:
    """
    PlanningAgentProtocol의 구체 구현체.
    환경 변수에서 Notion 인증 정보를 읽어 API를 호출합니다.
    """

    agent_name: str = "planning-agent"

    def __init__(self) -> None:
        self._token: str = os.environ["NOTION_TOKEN"]
        self._database_id: str = os.environ["NOTION_DATABASE_ID"]
        self._headers: dict[str, str] = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

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
        현재는 태스크 정보를 출력하고 성공으로 보고합니다.

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

            # TODO: 실제 기획 처리 로직 삽입 (예: LLM 호출, 문서 생성 등)

            return (True, f"태스크 처리 완료: {task_data['page_id']}")
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
