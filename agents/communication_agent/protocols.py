"""
Slack Agent 추상 인터페이스 (Protocol)
- python-strict-typing 전략: 엄격한 정적 타입 선언 및 추상 인터페이스
- ephemeral-docker-ops 전략: 단발성 실행 사이클 계약
- v2: slack_sdk AsyncWebClient 기반 (Incoming Webhook 미사용)
"""

from typing import Protocol

from .models import ExecutionResult, ParsedTask, RawPayload, SlackMessage


class SlackAgentProtocol(Protocol):
    """
    Slack 알림 에이전트의 동작을 정의하는 추상 인터페이스입니다.
    무한 루프나 데몬 없이, 스케줄링된 1회 실행 주기를 갖습니다.
    """

    agent_name: str

    async def fetch_notifications(self) -> list[RawPayload]:
        """
        Notion 데이터베이스에서 Slack 알림을 보내야 할 태스크 목록을 조회합니다.
        요청 시 반드시 헤더에 "Notion-Version": "2022-06-28"를 포함해야 합니다.

        Returns:
            list[RawPayload]: 파싱되기 전의 Notion API JSON 리스트.
        """
        ...

    async def format_slack_message(self, task_data: ParsedTask) -> SlackMessage:
        """
        파싱 완료된 Notion 태스크를 Slack Block Kit 페이로드로 변환합니다.

        Args:
            task_data (ParsedTask): 파싱 완료된 작업 데이터.

        Returns:
            SlackMessage: Slack Incoming Webhook 전송용 딕셔너리 페이로드.
        """
        ...

    async def push_to_slack(self, message: SlackMessage) -> ExecutionResult:
        """
        slack_sdk AsyncWebClient.chat_postMessage 으로 메시지를 전송합니다.

        Args:
            message (SlackMessage): Slack에 전송할 Block Kit 페이로드.

        Returns:
            ExecutionResult: (성공 여부, 처리 결과 메시지)
        """
        ...

    async def run(self) -> None:
        """
        에이전트 사이클의 진입점입니다.
        알림 조회 → 포맷팅 → Slack 전송 후 자연 종료합니다.
        (ephemeral-docker-ops 전략 준수: while True 혹은 asyncio.sleep 반복 금지)
        """
        ...
