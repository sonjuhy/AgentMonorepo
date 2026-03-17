"""
Slack Agent 구체 구현체 (v2 - slack_sdk.WebClient 기반)
- Incoming Webhook(httpx) 대신 slack_sdk AsyncWebClient 로 메시지 전송
- WebClient 인스턴스를 외부 주입(DI) 받아 FastAPI lifespan 과 공유
- Notion API 연동 및 승인 대기 태스크 알림 발송
- ephemeral-docker-ops 전략: 단발성 실행 후 자연 종료
"""

import os
from typing import Any

import httpx
from slack_sdk.web.async_client import AsyncWebClient

from ..models import ExecutionResult, ParsedTask, RawPayload, SlackMessage
from .notion_parser import parse_notion_task

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
NOTION_PAGE_BASE = "https://www.notion.so"

_DESIGN_DOC_MAX_LEN = 500

_PRIORITY_EMOJI: dict[str, str] = {
    "높음": "🔴",
    "중간": "🟡",
    "낮음": "🟢",
}


class SlackAgent:
    """
    SlackAgentProtocol의 구체 구현체 (slack_sdk.AsyncWebClient 기반).

    Notion DB에서 '승인 대기중' 태스크를 조회하여 Slack 채널로 알림을 발송합니다.

    Attributes:
        agent_name (str): 에이전트 식별 이름.

    환경 변수:
        NOTION_TOKEN       : Notion API 인증 토큰
        NOTION_DATABASE_ID : 조회할 Notion 데이터베이스 ID
        SLACK_CHANNEL      : 메시지를 발송할 Slack 채널 ID (예: C06XXXXXXX)
    """

    agent_name: str = "slack-agent"

    def __init__(self, web_client: AsyncWebClient | None = None) -> None:
        """
        SlackAgent 초기화.

        Args:
            web_client (AsyncWebClient | None):
                외부에서 주입할 slack_sdk AsyncWebClient 인스턴스.
                None 이면 SLACK_BOT_TOKEN 환경변수로 새로 생성합니다.
        """
        self._notion_token: str = os.environ["NOTION_TOKEN"]
        self._database_id: str = os.environ["NOTION_DB_ID"]
        self._slack_channel: str = os.environ.get("SLACK_CHANNEL", "")
        self._notion_headers: dict[str, str] = {
            "Authorization": f"Bearer {self._notion_token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        # WebClient 외부 주입 or 자체 생성
        if web_client is not None:
            self._web_client = web_client
        else:
            bot_token: str = os.environ["SLACK_BOT_TOKEN"]
            self._web_client = AsyncWebClient(token=bot_token)

    async def fetch_notifications(self) -> list[RawPayload]:
        """
        Notion 데이터베이스에서 '승인 대기중' 상태의 태스크 목록을 조회합니다.

        Returns:
            list[RawPayload]: 파싱되기 전의 Notion API JSON 리스트.
        """
        url = f"{NOTION_API_BASE}/databases/{self._database_id}/query"
        body: dict[str, Any] = {
            "filter": {
                "property": "현황",
                "status": {"equals": "승인 대기중"},
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=self._notion_headers, json=body)
            response.raise_for_status()
            data: dict[str, Any] = response.json()

        return data.get("results", [])

    async def format_slack_message(self, task_data: ParsedTask) -> SlackMessage:
        """
        ParsedTask를 Slack Block Kit 페이로드로 변환합니다.

        Args:
            task_data (ParsedTask): 파싱 완료된 작업 데이터.

        Returns:
            SlackMessage: chat_postMessage 전송용 딕셔너리 페이로드.
        """
        page_id_clean = task_data["page_id"].replace("-", "")
        notion_url = f"{NOTION_PAGE_BASE}/{page_id_clean}"

        priority_emoji = _PRIORITY_EMOJI.get(task_data["priority"], "⚪")
        priority_text = f"{priority_emoji} {task_data['priority']}" if task_data["priority"] else "미설정"
        agents_text = ", ".join(task_data["agent_assignees"]) if task_data["agent_assignees"] else "없음"
        assignees_text = ", ".join(task_data["assignees"]) if task_data["assignees"] else "없음"

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📋 승인 대기: {task_data['title']}",
                    "emoji": True,
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*상태*\n`{task_data['status']}`"},
                    {"type": "mrkdwn", "text": f"*우선순위*\n{priority_text}"},
                    {"type": "mrkdwn", "text": f"*타입*\n{task_data['task_type'] or '미설정'}"},
                    {"type": "mrkdwn", "text": f"*담당 에이전트*\n{agents_text}"},
                    {"type": "mrkdwn", "text": f"*담당자*\n{assignees_text}"},
                ],
            },
        ]

        if task_data["description"]:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*목적*\n{task_data['description']}"},
            })

        if task_data["design_doc"]:
            doc = task_data["design_doc"]
            if len(doc) > _DESIGN_DOC_MAX_LEN:
                doc = doc[:_DESIGN_DOC_MAX_LEN] + "..."
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*기획안/설계도 요약*\n```{doc}```"},
            })

        actions: list[dict[str, Any]] = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Notion 페이지 보기", "emoji": True},
                "url": notion_url,
                "action_id": "open_notion",
            }
        ]

        if task_data["github_pr"]:
            actions.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "GitHub PR 보기", "emoji": True},
                "url": task_data["github_pr"],
                "action_id": "open_github_pr",
                "style": "primary",
            })

        blocks.append({"type": "actions", "elements": actions})

        return {"blocks": blocks}

    async def push_to_slack(self, message: SlackMessage) -> ExecutionResult:
        """
        slack_sdk AsyncWebClient.chat_postMessage 으로 메시지를 전송합니다.

        Args:
            message (SlackMessage): Slack에 전송할 Block Kit 페이로드.

        Returns:
            ExecutionResult: (성공 여부, 처리 결과 메시지)
        """
        if not self._slack_channel:
            return (False, "SLACK_CHANNEL 환경변수가 설정되지 않았습니다.")

        try:
            response = await self._web_client.chat_postMessage(
                channel=self._slack_channel,
                blocks=message.get("blocks", []),
                text="Notion 태스크 알림",  # 알림 폴백 텍스트
            )
            ts: str = response.get("ts", "")
            return (True, f"Slack 전송 성공 (ts={ts})")
        except Exception as exc:
            return (False, f"Slack 전송 실패: {exc}")

    async def run(self) -> None:
        """
        에이전트 사이클의 진입점.
        알림 조회 → 포맷팅 → Slack 전송 후 자연 종료합니다.
        (ephemeral-docker-ops 전략 준수: while True / asyncio.sleep 반복 금지)
        """
        print(f"[{self.agent_name}] 실행 시작")

        raw_payloads = await self.fetch_notifications()
        print(f"[{self.agent_name}] 조회된 알림 대상 태스크 수: {len(raw_payloads)}")

        for raw in raw_payloads:
            task = parse_notion_task(raw)
            if task is None:
                continue

            message = await self.format_slack_message(task)
            success, msg = await self.push_to_slack(message)
            status_label = "완료" if success else "실패"
            print(f"[{self.agent_name}] [{task['title']}] Slack 전송 {status_label}: {msg}")

        print(f"[{self.agent_name}] 실행 종료")
