"""
Telegram 소통 에이전트 (TelegramCommAgent)
- Telegram Bot API와 Redis 사이의 양방향 게이트웨이
- Inbound:  Telegram 메시지 → on_user_message → Redis agent:orchestra:tasks
- Outbound: Redis agent:communication:telegram:tasks → listen_system_results → Telegram
- Feedback: [승인/수정 요청/취소] 인라인 버튼 클릭 → Redis orchestra:approval:{task_id}
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError

from ..models import TelegramEvent
from ..slack.redis_broker import TELEGRAM_COMM_TASKS_KEY, RedisBroker
from .formatter import TelegramFormatter

logger = logging.getLogger("telegram_agent.agent")

_MAX_RETRIES = 3

# 권한 관리: 허용된 채팅/사용자 (비어있으면 전체 허용)
_ALLOWED_CHATS: list[str] = [
    c for c in os.environ.get("TELEGRAM_ALLOWED_CHATS", "").split(",") if c
]
_ALLOWED_USER_IDS: list[str] = [
    u for u in os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",") if u
]


def _is_authorized(user_id: str, chat_id: str) -> bool:
    chat_ok = not _ALLOWED_CHATS or chat_id in _ALLOWED_CHATS
    user_ok = not _ALLOWED_USER_IDS or user_id in _ALLOWED_USER_IDS
    return chat_ok and user_ok


def _build_approval_keyboard(task_id: str) -> InlineKeyboardMarkup:
    """승인/수정 요청/취소 인라인 키보드를 생성합니다."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 승인", callback_data=f"approve:{task_id}"),
            InlineKeyboardButton("✏️ 수정 요청", callback_data=f"request_revision:{task_id}"),
            InlineKeyboardButton("🚫 취소", callback_data=f"cancel:{task_id}"),
        ]
    ])


class TelegramCommAgent:
    """
    Telegram ↔ Redis 양방향 소통 에이전트.

    환경 변수:
        TELEGRAM_BOT_TOKEN        : Telegram 봇 토큰 (@BotFather에서 발급)
        TELEGRAM_ALLOWED_CHATS    : 허용된 채팅 ID 목록 (쉼표 구분, 비어있으면 전체 허용)
        TELEGRAM_ALLOWED_USERS    : 허용된 사용자 ID 목록 (쉼표 구분, 비어있으면 전체 허용)
        REDIS_URL                 : Redis 접속 URL (기본값: redis://localhost:6379)
    """

    agent_name: str = "telegram_communication_agent"

    def __init__(
        self,
        bot: Bot | None = None,
        redis: RedisBroker | None = None,
    ) -> None:
        self._bot = bot
        self._redis = redis
        self._heartbeat_task: asyncio.Task[None] | None = None

    def set_bot(self, bot: Bot) -> None:
        self._bot = bot

    # ── 권한 확인 ──────────────────────────────────────────────────────────────

    def is_authorized(self, user_id: str, chat_id: str) -> bool:
        return _is_authorized(user_id, chat_id)

    # ── Inbound: 사용자 메시지 처리 ────────────────────────────────────────────

    async def on_user_message(self, event: TelegramEvent, message: Message) -> None:
        """
        Telegram 메시지를 수신하여 오케스트라 Redis 큐로 전달합니다.

        Args:
            event (TelegramEvent): 파싱된 Telegram 이벤트.
            message (Message): 원본 Telegram 메시지 객체 (접수 확인 전송용).
        """
        user_id = event["user_id"]
        chat_id = event["chat_id"]
        message_id = event["message_id"]

        if not self.is_authorized(user_id, chat_id):
            logger.warning("[TelegramAgent] 미허가 접근 user=%s chat=%s", user_id, chat_id)
            return

        if self._redis is None:
            logger.warning("[TelegramAgent] Redis 미설정 — on_user_message 건너뜀")
            return

        # 접수 확인 메시지 전송
        await message.reply_text("⏳ 요청을 접수했습니다. 처리 중입니다...")

        task_id = await self._redis.push_to_orchestra(
            user_id=user_id,
            channel_id=chat_id,
            content=event["text"],
            thread_ts=message_id,
            source="telegram",
        )

        await self._redis.save_task_context(task_id, {
            "channel_id": chat_id,
            "thread_ts": message_id,    # Telegram에서는 원본 메시지 ID
            "user_id": user_id,
            "session_id": f"{user_id}:{chat_id}",
            "platform": "telegram",
        })

        logger.info(
            "[TelegramAgent] 오케스트라 전달 — task_id=%s user=%s message_id=%s",
            task_id, user_id, message_id,
        )

    async def on_approval_callback(
        self,
        action: str,
        task_id: str,
        user_id: str,
        chat_id: str,
    ) -> None:
        """
        인라인 버튼 클릭(CallbackQuery)을 처리하여 오케스트라에 피드백을 전달합니다.

        Args:
            action (str): "approve" | "request_revision" | "cancel"
            task_id (str): 버튼 callback_data에서 추출한 태스크 ID.
            user_id (str): 버튼을 클릭한 Telegram 사용자 ID.
            chat_id (str): 버튼이 있는 채팅 ID.
        """
        if self._redis is None:
            return

        feedback: dict[str, Any] = {
            "task_id": task_id,
            "action": action,
            "user_id": user_id,
            "channel_id": chat_id,
            "comment": None,
        }
        await self._redis.push_approval(feedback)
        logger.info("[TelegramAgent] 피드백 전달 — task_id=%s action=%s", task_id, action)

    # ── Outbound: 시스템 결과 수신 루프 ───────────────────────────────────────

    async def listen_system_results(self) -> None:
        """Redis agent:communication:telegram:tasks 큐를 모니터링합니다."""
        if self._redis is None:
            logger.warning("[TelegramAgent] Redis 미설정 — listen_system_results 종료")
            return

        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="telegram_agent_heartbeat"
        )

        logger.info("[TelegramAgent] Redis 결과 리스너 시작 (queue=%s)", TELEGRAM_COMM_TASKS_KEY)
        while True:
            try:
                result = await self._redis.blpop_comm_task(
                    timeout=5.0, queue_key=TELEGRAM_COMM_TASKS_KEY
                )
                if result:
                    await self._handle_system_result(result)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[TelegramAgent] 결과 처리 오류: %s", exc)
                await asyncio.sleep(1)

    async def _heartbeat_loop(self) -> None:
        from datetime import datetime, timezone
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
                await asyncio.sleep(15)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[TelegramAgent] 하트비트 전송 실패: %s", e)
                await asyncio.sleep(5)

    async def _handle_system_result(self, result: dict[str, Any]) -> None:
        """수신된 결과를 Telegram으로 전송합니다."""
        task_id: str = result.get("task_id", "")
        content: str = result.get("content", "")
        requires_approval: bool = result.get("requires_user_approval", False)
        agent_name: str = result.get("agent_name", "에이전트")
        progress_percent: int | None = result.get("progress_percent")

        ctx = await self._redis.get_task_context(task_id) if self._redis else None
        if ctx is None:
            logger.warning("[TelegramAgent] 태스크 컨텍스트 없음: task_id=%s", task_id)
            return

        chat_id = ctx["channel_id"]
        ref_message_id = ctx.get("thread_ts")

        # 진행 상태 업데이트
        if progress_percent is not None:
            await self._post_progress_update(
                task_id=task_id,
                chat_id=chat_id,
                percent=progress_percent,
                message=content,
            )
            return

        # 최종 결과 전송
        if requires_approval:
            text = f"⚠️ <b>실행 승인 요청</b>\n\n{TelegramFormatter.format(content)}"
            keyboard = _build_approval_keyboard(task_id)
            await self._send_with_retry(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                reply_to_message_id=int(ref_message_id) if ref_message_id else None,
            )
        else:
            text = f"✅ <b>작업이 완료되었습니다.</b>\n\n{TelegramFormatter.format(content)}\n\n<i>처리 에이전트: {agent_name}</i>"
            await self._send_with_retry(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=int(ref_message_id) if ref_message_id else None,
            )

    async def _post_progress_update(
        self,
        task_id: str,
        chat_id: str,
        percent: int,
        message: str,
    ) -> None:
        """진행 상태 메시지를 편집하거나 새로 전송합니다."""
        if self._redis is None or self._bot is None:
            return

        progress_text = f"🔄 {message} ({percent}%)"
        existing_ref = await self._redis.get_progress_msg_ts(task_id)

        if existing_ref:
            try:
                await self._bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=int(existing_ref),
                    text=progress_text,
                )
                return
            except TelegramError:
                pass

        sent = await self._bot.send_message(chat_id=chat_id, text=progress_text)
        await self._redis.save_progress_msg_ts(task_id, str(sent.message_id))

    # ── 재시도 전송 ──────────────────────────────────────────────────────────

    async def _send_with_retry(
        self,
        chat_id: str,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        reply_to_message_id: int | None = None,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        if self._bot is None:
            logger.warning("[TelegramAgent] Bot 미초기화 — 메시지 전송 건너뜀")
            return

        kwargs: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": ParseMode.HTML,
        }
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        if reply_to_message_id is not None:
            kwargs["reply_to_message_id"] = reply_to_message_id

        for attempt in range(max_retries):
            try:
                await self._bot.send_message(**kwargs)
                return
            except RetryAfter as e:
                logger.warning("[TelegramAgent] Rate Limit — %.1f초 후 재시도 (%d/%d)", e.retry_after, attempt + 1, max_retries)
                await asyncio.sleep(e.retry_after)
            except TelegramError as exc:
                logger.error("[TelegramAgent] 메시지 전송 실패: %s", exc)
                raise

    # ── 직접 메시지 전송 (REST API 용) ────────────────────────────────────────

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to_message_id: str | None = None,
    ) -> str:
        """채팅에 메시지를 전송하고 message_id를 반환합니다."""
        if self._bot is None:
            raise RuntimeError("Telegram Bot이 초기화되지 않았습니다.")

        kwargs: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": ParseMode.HTML,
        }
        if reply_to_message_id:
            kwargs["reply_to_message_id"] = int(reply_to_message_id)

        sent = await self._bot.send_message(**kwargs)
        return str(sent.message_id)
