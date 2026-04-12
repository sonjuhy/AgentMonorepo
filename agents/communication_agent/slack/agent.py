"""
소통 에이전트 구체 구현체 (v3 - SlackCommAgent)
- Slack API와 Redis 사이의 양방향 게이트웨이
- Inbound:  Slack → on_user_request → Redis agent:orchestra:tasks
- Outbound: Redis agent:communication:tasks → listen_system_results → Slack
- Feedback: [승인/수정 요청/취소] 버튼 클릭 → Redis orchestra:results
- Notion 알림 발송 기능 유지 (fetch_notifications / run)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from ..models import (
    ApprovalFeedback,
    ExecutionResult,
    OrchestraResult,
    ParsedTask,
    RawPayload,
    SlackEvent,
    SlackMessage,
)
from .message_cleaner import MessageCleaner
from .notion_parser import parse_notion_task
from .redis_broker import RedisBroker

logger = logging.getLogger("slack_agent.agent")

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
NOTION_PAGE_BASE = "https://www.notion.so"

_DESIGN_DOC_MAX_LEN = 500
_MAX_RETRIES = 3

_PRIORITY_EMOJI: dict[str, str] = {
    "높음": "🔴",
    "중간": "🟡",
    "낮음": "🟢",
}

# 권한 관리: 허용된 채널/사용자 (비어있으면 전체 허용)
_ALLOWED_CHANNELS: list[str] = [
    c for c in os.environ.get("SLACK_ALLOWED_CHANNELS", "").split(",") if c
]
_ALLOWED_USER_IDS: list[str] = [
    u for u in os.environ.get("SLACK_ALLOWED_USERS", "").split(",") if u
]


def _is_authorized(user_id: str, channel_id: str) -> bool:
    """허용된 채널 및 사용자인지 확인합니다."""
    channel_ok = not _ALLOWED_CHANNELS or channel_id in _ALLOWED_CHANNELS
    user_ok = not _ALLOWED_USER_IDS or user_id in _ALLOWED_USER_IDS
    return channel_ok and user_ok


class SlackCommAgent:
    """
    소통 에이전트 (Communication Agent) 구체 구현체.

    역할:
        - 사용자 Slack 메시지를 수신하여 오케스트라 Redis 큐로 전달
        - 오케스트라 처리 결과를 Redis에서 수신하여 Slack으로 렌더링
        - 승인/반려 버튼 UI 제공 및 피드백 Redis 전달
        - Notion 승인 대기 태스크 알림 발송 (기존 기능 유지)

    환경 변수:
        NOTION_TOKEN          : Notion API 인증 토큰
        NOTION_DB_ID          : 조회할 Notion 데이터베이스 ID
        SLACK_CHANNEL         : 메시지를 발송할 Slack 채널 ID
        SLACK_ALLOWED_CHANNELS: 허용된 채널 ID 목록 (쉼표 구분, 비어있으면 전체 허용)
        SLACK_ALLOWED_USERS   : 허용된 사용자 ID 목록 (쉼표 구분, 비어있으면 전체 허용)
        REDIS_URL             : Redis 접속 URL (기본값: redis://localhost:6379)
    """

    agent_name: str = "communication_agent"

    def __init__(
        self,
        web_client: AsyncWebClient | None = None,
        redis: RedisBroker | None = None,
    ) -> None:
        """
        SlackCommAgent 초기화.

        Args:
            web_client (AsyncWebClient | None):
                외부 주입 slack_sdk AsyncWebClient.
                None이면 SLACK_BOT_TOKEN 환경변수로 새로 생성합니다.
            redis (RedisBroker | None):
                외부 주입 RedisBroker.
                None이면 REDIS_URL 환경변수로 새로 생성합니다.
                Redis 없이도 Notion 알림 기능은 동작합니다.
        """
        self._notion_token: str = os.environ.get("NOTION_TOKEN", "")
        self._database_id: str = os.environ.get("NOTION_DB_ID", "")
        self._slack_channel: str = os.environ.get("SLACK_CHANNEL", "")
        self._notion_headers: dict[str, str] = {
            "Authorization": f"Bearer {self._notion_token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

        if web_client is not None:
            self._web_client = web_client
        else:
            bot_token: str = os.environ["SLACK_BOT_TOKEN"]
            self._web_client = AsyncWebClient(token=bot_token)

        self._redis: RedisBroker | None = redis
        self._heartbeat_task: asyncio.Task[None] | None = None

    # ── 권한 확인 ──────────────────────────────────────────────────────────────

    def is_authorized(self, user_id: str, channel_id: str) -> bool:
        """허용된 채널 및 사용자인지 확인합니다."""
        return _is_authorized(user_id, channel_id)

    # ── Inbound: 사용자 요청 처리 ──────────────────────────────────────────────

    async def on_user_request(self, event: SlackEvent, say: Any) -> None:
        """
        Slack 메시지를 수신하여 정제 후 오케스트라 Redis 큐로 전달합니다.

        변경 사항:
            - 세션 단위 스레드 캐싱 제거
            - 사용자의 현재 메시지에 대해 스레드로 응답 (또는 이미 스레드면 유지)
        """
        user_id: str = event["user"]
        channel_id: str = event["channel"]
        ts: str = event["ts"]

        if not self.is_authorized(user_id, channel_id):
            logger.warning("[CommAgent] 미허가 접근 user=%s channel=%s", user_id, channel_id)
            return

        clean_text = MessageCleaner.clean(event["text"])
        if not clean_text:
            return

        if self._redis is None:
            logger.warning("[CommAgent] Redis 미설정 — on_user_request 건너뜀")
            return

        # 사용자의 현재 메시지에 스레드로 답변 (이미 스레드 내부라면 해당 스레드 유지)
        # 만약 스레드 없이 새 메시지로만 하고 싶다면 thread_ts = None 으로 설정하면 됩니다.
        thread_ts = event.get("thread_ts") or ts

        await self._web_client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="⏳ 요청을 접수했습니다. 처리 중입니다...",
        )

        # 세션 ID: NLU 컨텍스트용
        session_id = f"{user_id}:{channel_id}"

        # 오케스트라 큐에 전달 (현재 메시지의 thread_ts 전달)
        task_id = await self._redis.push_to_orchestra(
            user_id=user_id,
            channel_id=channel_id,
            content=clean_text,
            thread_ts=thread_ts,
        )

        # 태스크 컨텍스트 저장 (결과 수신 시 정확한 채널/스레드로 복원)
        await self._redis.save_task_context(task_id, {
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
            "session_id": session_id,
        })

        logger.info(
            "[CommAgent] 오케스트라 전달 — task_id=%s user=%s thread_ts=%s",
            task_id,
            user_id,
            thread_ts,
        )

    # ── Outbound: 시스템 결과 수신 루프 ───────────────────────────────────────

    async def listen_system_results(self) -> None:
        """
        Redis agent:communication:tasks 큐를 모니터링하여
        오케스트라 결과를 Slack Block Kit으로 렌더링합니다.
        """
        if self._redis is None:
            logger.warning("[CommAgent] Redis 미설정 — listen_system_results 종료")
            return

        # 백그라운드 하트비트 시작 (참조 보관으로 GC 방지)
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="comm_agent_heartbeat"
        )

        logger.info("[CommAgent] Redis 결과 리스너 시작 (queue=%s)", "agent:communication:tasks")
        while True:
            try:
                result = await self._redis.blpop_comm_task(timeout=5.0)
                if result:
                    await self._handle_system_result(result)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[CommAgent] 결과 처리 오류: %s", exc)
                await asyncio.sleep(1)

    async def _heartbeat_loop(self) -> None:
        """15초마다 Orchestra Agent에 생존 신호를 기록합니다 (유효 시간 30초)."""
        from datetime import datetime, timezone
        logger.info("[CommAgent] 하트비트 루프 시작 (agent=%s)", self.agent_name)
        while True:
            try:
                if self._redis:
                    await self._redis.update_agent_health(
                        self.agent_name,
                        {
                            "status": "IDLE",
                            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                            "version": "1.0.0",
                        },
                    )
                    logger.debug("[CommAgent] 하트비트 전송 완료 (agent=%s)", self.agent_name)
                await asyncio.sleep(15)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[CommAgent] 하트비트 전송 실패: %s", e)
                await asyncio.sleep(5)

    async def _handle_system_result(self, result: dict[str, Any]) -> None:
        """
        수신된 OrchestraResult를 파싱하고 Slack으로 전송합니다.
        """
        task_id: str = result.get("task_id", "")
        content: str = result.get("content", "")
        requires_approval: bool = result.get("requires_user_approval", False)
        agent_name: str = result.get("agent_name", "에이전트")
        progress_percent: int | None = result.get("progress_percent")

        # 태스크 컨텍스트 복원
        ctx = await self._redis.get_task_context(task_id) if self._redis else None
        if ctx is None:
            logger.warning("[CommAgent] 태스크 컨텍스트 없음: task_id=%s", task_id)
            return

        channel_id: str = ctx["channel_id"]
        thread_ts: str = ctx["thread_ts"]
        
        # 진행 상태 업데이트 (task_id를 사용하여 태스크별 진행 메시지 관리)
        if progress_percent is not None:
            await self._post_progress_update(
                task_id=task_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                percent=progress_percent,
                message=content,
            )
            return

        # 최종 결과 전송
        if requires_approval:
            blocks = self.build_approval_blocks(content, task_id)
            text_fallback = f"⚠️ 실행 승인 요청: {content[:100]}"
        else:
            blocks = self._build_standard_blocks(content, agent_name)
            text_fallback = f"✅ {agent_name} 처리 완료"

        await self._send_with_retry(
            channel=channel_id,
            blocks=blocks,
            text=text_fallback,
            thread_ts=thread_ts,
        )

    async def _post_progress_update(
        self,
        task_id: str,
        channel_id: str,
        thread_ts: str,
        percent: int,
        message: str,
    ) -> None:
        """
        진행 상태 메시지를 chat_update로 업데이트합니다.
        세션 단위가 아닌 태스크 단위(task_id)로 관리하여 충돌을 방지합니다.
        """
        if self._redis is None:
            return

        progress_text = f"🔄 {message} ({percent}%)"
        # task_id를 키로 사용하여 현재 태스크의 진행 메시지만 추적
        existing_ts = await self._redis.get_progress_msg_ts(task_id)

        if existing_ts:
            try:
                await self._web_client.chat_update(
                    channel=channel_id,
                    ts=existing_ts,
                    text=progress_text,
                )
                return
            except SlackApiError:
                pass

        resp = await self._web_client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=progress_text,
        )
        await self._redis.save_progress_msg_ts(task_id, resp["ts"])

    # ── Block Kit 빌더 ────────────────────────────────────────────────────────

    def build_approval_blocks(self, content: str, task_id: str) -> list[dict[str, Any]]:
        """
        [승인] [수정 요청] [취소] 버튼이 포함된 Slack Block Kit 블록 리스트를 생성합니다.

        Args:
            content (str): 승인 요청 내용 요약 텍스트.
            task_id (str): 버튼 value에 포함될 태스크 식별자.

        Returns:
            list[dict]: Slack Block Kit 블록 리스트.
        """
        return [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "⚠️ 실행 승인 요청", "emoji": True},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": content},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "승인", "emoji": True},
                        "style": "primary",
                        "action_id": "approve_task",
                        "value": task_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "수정 요청", "emoji": True},
                        "action_id": "request_revision",
                        "value": task_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "취소", "emoji": True},
                        "style": "danger",
                        "action_id": "cancel_task",
                        "value": task_id,
                    },
                ],
            },
        ]

    def _build_standard_blocks(
        self, content: str, agent_name: str
    ) -> list[dict[str, Any]]:
        """
        일반 결과 응답용 Slack Block Kit 블록 리스트를 생성합니다.

        Args:
            content (str): 결과 본문 텍스트 (마크다운 지원).
            agent_name (str): 처리한 에이전트 이름.

        Returns:
            list[dict]: Slack Block Kit 블록 리스트.
        """
        return [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "✅ 작업이 완료되었습니다.", "emoji": True},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": content},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"처리 에이전트: *{agent_name}*"},
                ],
            },
        ]

    # ── Rate Limit 재시도 전송 ────────────────────────────────────────────────

    async def _send_with_retry(
        self,
        channel: str,
        blocks: list[dict[str, Any]],
        text: str = "",
        thread_ts: str | None = None,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        """
        Slack API Rate Limit 시 Retry-After 헤더를 준수하여 재시도합니다.

        Args:
            channel (str): 전송할 Slack 채널 ID.
            blocks (list): Block Kit 블록 리스트.
            text (str): 알림용 폴백 텍스트.
            thread_ts (str | None): 스레드 답글 시 원본 메시지 ts.
            max_retries (int): 최대 재시도 횟수.

        Raises:
            SlackApiError: 재시도 초과 또는 Rate Limit 외 오류.
        """
        kwargs: dict[str, Any] = {"channel": channel, "blocks": blocks, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        for attempt in range(max_retries):
            try:
                await self._web_client.chat_postMessage(**kwargs)
                return
            except SlackApiError as e:
                if e.response["error"] == "ratelimited":
                    retry_after = int(e.response.headers.get("Retry-After", 30))
                    logger.warning(
                        "[CommAgent] Rate Limit — %d초 후 재시도 (%d/%d)",
                        retry_after,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(retry_after)
                else:
                    raise

        raise SlackApiError(
            message="Slack API Rate Limit: 최대 재시도 초과",
            response={"error": "max_retries_exceeded"},
        )

    # ── Notion 알림 발송 (기존 기능 유지) ──────────────────────────────────────

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
        ParsedTask를 Notion 알림용 Slack Block Kit 페이로드로 변환합니다.

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
                text="Notion 태스크 알림",
            )
            ts: str = response.get("ts", "")
            return (True, f"Slack 전송 성공 (ts={ts})")
        except Exception as exc:
            return (False, f"Slack 전송 실패: {exc}")

    async def run(self) -> None:
        """
        에이전트 사이클의 진입점 (Notion 알림 발송 전용).
        알림 조회 → 포맷팅 → Slack 전송 후 자연 종료합니다.
        (ephemeral-docker-ops 전략 준수: while True / asyncio.sleep 반복 금지)
        """
        logger.info("[%s] 실행 시작", self.agent_name)

        raw_payloads = await self.fetch_notifications()
        logger.info("[%s] 조회된 알림 대상 태스크 수: %d", self.agent_name, len(raw_payloads))

        for raw in raw_payloads:
            task = parse_notion_task(raw)
            if task is None:
                continue

            message = await self.format_slack_message(task)
            success, msg = await self.push_to_slack(message)
            status_label = "완료" if success else "실패"
            logger.info("[%s] [%s] Slack 전송 %s: %s", self.agent_name, task["title"], status_label, msg)

        logger.info("[%s] 실행 종료", self.agent_name)


# 하위 호환: 기존 SlackAgent 이름으로도 접근 가능
SlackAgent = SlackCommAgent
