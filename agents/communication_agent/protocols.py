"""
Communication Agent 추상 인터페이스 (Protocol)
- python-strict-typing 전략: 엄격한 정적 타입 선언 및 추상 인터페이스
- ephemeral-docker-ops 전략: 단발성 실행 사이클 계약
- v3: SlackCommAgent 인터페이스 추가 (Redis 기반 양방향 게이트웨이)
"""

from typing import Any, Protocol

from .models import DiscordEvent, ExecutionResult, ParsedTask, RawPayload, SlackMessage, SlackEvent, TelegramEvent


class SlackAgentProtocol(Protocol):
    """
    Slack 알림 에이전트의 동작을 정의하는 추상 인터페이스입니다.
    무한 루프나 데몬 없이, 스케줄링된 1회 실행 주기를 갖습니다.
    (Notion 알림 발송 전용)
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
            SlackMessage: chat_postMessage 전송용 딕셔너리 페이로드.
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


class SlackCommAgentProtocol(Protocol):
    """
    소통 에이전트(Communication Agent)의 양방향 게이트웨이 인터페이스입니다.
    - Inbound:  Slack → on_user_request → Redis agent:orchestra:tasks
    - Outbound: Redis agent:communication:tasks → listen_system_results → Slack
    - Feedback: 사용자 버튼 클릭 → build_approval_blocks → Redis orchestra:results
    """

    agent_name: str

    async def on_user_request(self, event: SlackEvent, say: Any) -> None:
        """
        Slack 이벤트를 수신하여 메시지를 정제하고 오케스트라 Redis 큐로 전달합니다.

        처리 흐름:
            1. 권한 확인 (허용된 채널/사용자 검증)
            2. MessageCleaner로 @bot 멘션 등 불필요한 태그 제거
            3. 세션 기반 Slack 스레드 생성 또는 조회
            4. Redis agent:orchestra:tasks 큐에 OrchestraTask 삽입
            5. 사용자에게 접수 확인 메시지 전송

        Args:
            event (SlackEvent): slack_bolt에서 전달된 메시지 이벤트.
            say (Any): 현재 채널/스레드에 메시지를 보내는 slack_bolt 유틸리티.
        """
        ...

    async def listen_system_results(self) -> None:
        """
        Redis agent:communication:tasks 큐를 모니터링하여 에이전트 실행 결과를
        Slack Block Kit으로 렌더링하여 사용자에게 전달합니다.

        처리 흐름:
            1. BLPOP으로 큐에서 OrchestraResult 수신
            2. requires_user_approval에 따라 승인 UI 또는 표준 결과 블록 생성
            3. 세션 스레드에 메시지 전송 (chat_update 또는 chat_postMessage)

        Note:
            FastAPI lifespan에서 asyncio.Task로 실행되는 백그라운드 루프입니다.
            CancelledError를 감지하여 정상 종료합니다.
        """
        ...

    def build_approval_blocks(self, content: str, task_id: str) -> list[dict[str, Any]]:
        """
        [승인] [수정 요청] [취소] 버튼이 포함된 Slack Block Kit 블록 리스트를 생성합니다.

        Args:
            content (str): 승인 요청 내용 요약 텍스트.
            task_id (str): 버튼 action_id와 value에 포함될 태스크 식별자.

        Returns:
            list[dict[str, Any]]: Slack Block Kit 블록 리스트.
        """
        ...


class DiscordCommAgentProtocol(Protocol):
    """
    Discord 소통 에이전트의 양방향 게이트웨이 인터페이스입니다.
    - Inbound:  Discord 메시지 → on_user_message → Redis agent:orchestra:tasks
    - Outbound: Redis agent:communication:discord:tasks → listen_system_results → Discord
    - Feedback: 사용자 버튼 클릭 → Redis orchestra:approval:{task_id}
    """

    agent_name: str

    async def on_user_message(self, event: DiscordEvent) -> None:
        """Discord 메시지를 수신하여 오케스트라 Redis 큐로 전달합니다."""
        ...

    async def listen_system_results(self) -> None:
        """Redis agent:communication:discord:tasks 큐를 모니터링하여 결과를 Discord로 전달합니다."""
        ...

    async def send_message(self, channel_id: str, content: str, reference_message_id: str | None = None) -> str:
        """Discord 채널에 메시지를 전송하고 message_id를 반환합니다."""
        ...


class TelegramCommAgentProtocol(Protocol):
    """
    Telegram 소통 에이전트의 양방향 게이트웨이 인터페이스입니다.
    - Inbound:  Telegram 메시지 → on_user_message → Redis agent:orchestra:tasks
    - Outbound: Redis agent:communication:telegram:tasks → listen_system_results → Telegram
    - Feedback: 사용자 인라인 버튼 클릭 → Redis orchestra:approval:{task_id}
    """

    agent_name: str

    async def on_user_message(self, event: TelegramEvent) -> None:
        """Telegram 메시지를 수신하여 오케스트라 Redis 큐로 전달합니다."""
        ...

    async def listen_system_results(self) -> None:
        """Redis agent:communication:telegram:tasks 큐를 모니터링하여 결과를 Telegram으로 전달합니다."""
        ...

    async def send_message(self, chat_id: str, text: str, reply_to_message_id: str | None = None) -> str:
        """Telegram 채팅에 메시지를 전송하고 message_id를 반환합니다."""
        ...
