"""
Discord 소통 에이전트 (DiscordCommAgent)
- Discord API와 Redis 사이의 양방향 게이트웨이
- Inbound:  Discord 메시지 → on_user_message → Redis agent:orchestra:tasks
- Outbound: Redis agent:communication:discord:tasks → listen_system_results → Discord
- Feedback: [승인/수정 요청/취소] 버튼 클릭 → Redis orchestra:approval:{task_id}
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import discord
import discord.ui

from ..models import DiscordEvent
from ..slack.redis_broker import DISCORD_COMM_TASKS_KEY, RedisBroker
from .formatter import DiscordFormatter

logger = logging.getLogger("discord_agent.agent")

_MAX_RETRIES = 3

# 권한 관리: 허용된 채널/사용자 (비어있으면 전체 허용)
_ALLOWED_CHANNELS: list[str] = [
    c for c in os.environ.get("DISCORD_ALLOWED_CHANNELS", "").split(",") if c
]
_ALLOWED_USER_IDS: list[str] = [
    u for u in os.environ.get("DISCORD_ALLOWED_USERS", "").split(",") if u
]


def _is_authorized(user_id: str, channel_id: str) -> bool:
    channel_ok = not _ALLOWED_CHANNELS or channel_id in _ALLOWED_CHANNELS
    user_ok = not _ALLOWED_USER_IDS or user_id in _ALLOWED_USER_IDS
    return channel_ok and user_ok


class ApprovalButton(discord.ui.Button):
    """승인/수정 요청/취소 버튼"""

    def __init__(
        self,
        task_id: str,
        action: str,
        label: str,
        style: discord.ButtonStyle,
        redis: RedisBroker,
    ) -> None:
        # custom_id는 고유해야 하므로 task_id 포함
        super().__init__(label=label, style=style, custom_id=f"{action}:{task_id[:36]}")
        self.task_id = task_id
        self.action = action
        self.redis = redis

    async def callback(self, interaction: discord.Interaction) -> None:  # type: ignore[override]
        feedback: dict[str, Any] = {
            "task_id": self.task_id,
            "action": self.action,
            "user_id": str(interaction.user.id),
            "channel_id": str(interaction.channel_id),
            "comment": None,
        }
        await self.redis.push_approval(feedback)

        labels = {
            "approve": "✅ 승인됨",
            "request_revision": "✏️ 수정 요청됨",
            "cancel": "🚫 취소됨",
        }
        label = labels.get(self.action, self.action)
        await interaction.response.send_message(
            f"{label} — {interaction.user.mention}님이 처리했습니다."
        )
        if self.view:
            self.view.stop()


class ApprovalView(discord.ui.View):
    """승인 요청 버튼 뷰 (5분 타임아웃)"""

    def __init__(self, task_id: str, redis: RedisBroker) -> None:
        super().__init__(timeout=300)
        self.add_item(ApprovalButton(task_id, "approve", "승인", discord.ButtonStyle.green, redis))
        self.add_item(ApprovalButton(task_id, "request_revision", "수정 요청", discord.ButtonStyle.grey, redis))
        self.add_item(ApprovalButton(task_id, "cancel", "취소", discord.ButtonStyle.red, redis))

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


class DiscordCommAgent:
    """
    Discord ↔ Redis 양방향 소통 에이전트.

    환경 변수:
        DISCORD_BOT_TOKEN         : Discord 봇 토큰
        DISCORD_ALLOWED_CHANNELS  : 허용된 채널 ID 목록 (쉼표 구분, 비어있으면 전체 허용)
        DISCORD_ALLOWED_USERS     : 허용된 사용자 ID 목록 (쉼표 구분, 비어있으면 전체 허용)
        REDIS_URL                 : Redis 접속 URL (기본값: redis://localhost:6379)
    """

    agent_name: str = "discord_communication_agent"

    def __init__(
        self,
        client: discord.Client | None = None,
        redis: RedisBroker | None = None,
    ) -> None:
        self._redis = redis
        self._client = client
        self._heartbeat_task: asyncio.Task[None] | None = None

    def set_client(self, client: discord.Client) -> None:
        self._client = client

    # ── 권한 확인 ──────────────────────────────────────────────────────────────

    def is_authorized(self, user_id: str, channel_id: str) -> bool:
        return _is_authorized(user_id, channel_id)

    # ── Inbound: 사용자 메시지 처리 ────────────────────────────────────────────

    async def on_user_message(self, event: DiscordEvent, message: discord.Message) -> None:
        """
        Discord 메시지를 수신하여 오케스트라 Redis 큐로 전달합니다.

        Args:
            event (DiscordEvent): 파싱된 Discord 이벤트.
            message (discord.Message): 원본 Discord 메시지 객체 (접수 확인 전송용).
        """
        user_id = event["user_id"]
        channel_id = event["channel_id"]
        message_id = event["message_id"]

        if not self.is_authorized(user_id, channel_id):
            logger.warning("[DiscordAgent] 미허가 접근 user=%s channel=%s", user_id, channel_id)
            return

        if self._redis is None:
            logger.warning("[DiscordAgent] Redis 미설정 — on_user_message 건너뜀")
            return

        # 접수 확인 메시지 전송 (원본 메시지에 reply)
        await message.reply("⏳ 요청을 접수했습니다. 처리 중입니다...")

        task_id = await self._redis.push_to_orchestra(
            user_id=user_id,
            channel_id=channel_id,
            content=event["text"],
            thread_ts=message_id,
            source="discord",
        )

        await self._redis.save_task_context(task_id, {
            "channel_id": channel_id,
            "thread_ts": message_id,    # Discord에서는 원본 메시지 ID
            "user_id": user_id,
            "session_id": f"{user_id}:{channel_id}",
            "platform": "discord",
        })

        logger.info(
            "[DiscordAgent] 오케스트라 전달 — task_id=%s user=%s message_id=%s",
            task_id, user_id, message_id,
        )

    # ── Outbound: 시스템 결과 수신 루프 ───────────────────────────────────────

    async def listen_system_results(self) -> None:
        """Redis agent:communication:discord:tasks 큐를 모니터링합니다."""
        if self._redis is None:
            logger.warning("[DiscordAgent] Redis 미설정 — listen_system_results 종료")
            return

        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="discord_agent_heartbeat"
        )

        logger.info("[DiscordAgent] Redis 결과 리스너 시작 (queue=%s)", DISCORD_COMM_TASKS_KEY)
        while True:
            try:
                result = await self._redis.blpop_comm_task(
                    timeout=5.0, queue_key=DISCORD_COMM_TASKS_KEY
                )
                if result:
                    await self._handle_system_result(result)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[DiscordAgent] 결과 처리 오류: %s", exc)
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
                logger.error("[DiscordAgent] 하트비트 전송 실패: %s", e)
                await asyncio.sleep(5)

    async def _handle_system_result(self, result: dict[str, Any]) -> None:
        """수신된 결과를 Discord로 전송합니다."""
        task_id: str = result.get("task_id", "")
        content: str = result.get("content", "")
        requires_approval: bool = result.get("requires_user_approval", False)
        agent_name: str = result.get("agent_name", "에이전트")
        progress_percent: int | None = result.get("progress_percent")

        ctx = await self._redis.get_task_context(task_id) if self._redis else None
        if ctx is None:
            logger.warning("[DiscordAgent] 태스크 컨텍스트 없음: task_id=%s", task_id)
            return

        channel_id = ctx["channel_id"]
        ref_message_id = ctx.get("thread_ts")

        channel = self._client.get_channel(int(channel_id)) if self._client else None
        if channel is None:
            logger.warning("[DiscordAgent] 채널을 찾을 수 없음: channel_id=%s", channel_id)
            return

        # 진행 상태 업데이트
        if progress_percent is not None:
            await self._post_progress_update(
                task_id=task_id,
                channel=channel,
                percent=progress_percent,
                message=content,
            )
            return

        # 최종 결과 전송
        if requires_approval:
            embed = self._build_approval_embed(content)
            view = ApprovalView(task_id, self._redis)
            await self._send_with_retry(channel, embed=embed, view=view)
        else:
            embed = self._build_standard_embed(content, agent_name)
            await self._send_with_retry(channel, embed=embed)

    async def _post_progress_update(
        self,
        task_id: str,
        channel: discord.abc.Messageable,
        percent: int,
        message: str,
    ) -> None:
        """진행 상태 메시지를 편집하거나 새로 전송합니다."""
        if self._redis is None:
            return

        progress_text = f"🔄 {message} ({percent}%)"
        existing_ref = await self._redis.get_progress_msg_ts(task_id)

        if existing_ref:
            try:
                msg = await channel.fetch_message(int(existing_ref))  # type: ignore[attr-defined]
                await msg.edit(content=progress_text)
                return
            except discord.NotFound:
                pass

        sent = await channel.send(progress_text)  # type: ignore[union-attr]
        await self._redis.save_progress_msg_ts(task_id, str(sent.id))

    # ── Embed 빌더 ───────────────────────────────────────────────────────────

    def _build_approval_embed(self, content: str) -> discord.Embed:
        embed = discord.Embed(
            title="⚠️ 실행 승인 요청",
            description=DiscordFormatter.format(content),
            color=discord.Color.yellow(),
        )
        return embed

    def _build_standard_embed(self, content: str, agent_name: str) -> discord.Embed:
        embed = discord.Embed(
            title="✅ 작업이 완료되었습니다.",
            description=DiscordFormatter.format(content),
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"처리 에이전트: {agent_name}")
        return embed

    # ── 재시도 전송 ──────────────────────────────────────────────────────────

    async def _send_with_retry(
        self,
        channel: discord.abc.Messageable,
        embed: discord.Embed,
        view: discord.ui.View | None = None,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        kwargs: dict[str, Any] = {"embed": embed}
        if view is not None:
            kwargs["view"] = view

        for attempt in range(max_retries):
            try:
                await channel.send(**kwargs)  # type: ignore[union-attr]
                return
            except discord.HTTPException as e:
                if e.status == 429:  # Rate limited
                    retry_after = float(e.response.headers.get("Retry-After", 5))
                    logger.warning("[DiscordAgent] Rate Limit — %.1f초 후 재시도 (%d/%d)", retry_after, attempt + 1, max_retries)
                    await asyncio.sleep(retry_after)
                else:
                    raise

    # ── 직접 메시지 전송 (REST API 용) ────────────────────────────────────────

    async def send_message(
        self,
        channel_id: str,
        content: str,
        reference_message_id: str | None = None,
    ) -> str:
        """채널에 메시지를 전송하고 message_id를 반환합니다."""
        if self._client is None:
            raise RuntimeError("Discord client가 초기화되지 않았습니다.")
        channel = self._client.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"채널을 찾을 수 없습니다: {channel_id}")

        kwargs: dict[str, Any] = {"content": content}
        if reference_message_id:
            try:
                ref_msg = await channel.fetch_message(int(reference_message_id))  # type: ignore[attr-defined]
                kwargs["reference"] = ref_msg
            except discord.NotFound:
                pass

        sent = await channel.send(**kwargs)  # type: ignore[union-attr]
        return str(sent.id)
