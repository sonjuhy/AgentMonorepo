"""
Redis 메시지 브로커 클라이언트
- 세션 상태·승인 피드백·헬스체크 전용
- Discord/Telegram은 아직 cassiopeia Pub/Sub 미전환 — blpop_comm_task 잔존

참고: Slack 오케스트라 ↔ 소통 에이전트 간 태스크 통신은
      cassiopeia-sdk (Redis Pub/Sub)를 통해 SlackCommAgent가 직접 처리합니다.
"""

import json
import logging
import os
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger("slack_agent.redis_broker")

# Discord/Telegram 아웃바운드 큐 (아직 Pub/Sub 미전환)
COMM_TASKS_KEY = "agent:communication:tasks"
DISCORD_COMM_TASKS_KEY = "agent:communication:discord:tasks"
TELEGRAM_COMM_TASKS_KEY = "agent:communication:telegram:tasks"

PLATFORM_COMM_QUEUE: dict[str, str] = {
    "slack": COMM_TASKS_KEY,
    "discord": DISCORD_COMM_TASKS_KEY,
    "telegram": TELEGRAM_COMM_TASKS_KEY,
}

# 승인 피드백은 태스크별 큐를 사용 (오케스트라와 일치)
_APPROVAL_KEY_PREFIX = "orchestra:approval:"

# 세션 TTL: 2시간
_SESSION_TTL = 7200


class RedisBroker:
    """
    소통 에이전트의 Redis 클라이언트 (세션 상태·승인 피드백 전용).

    환경 변수:
        REDIS_URL: Redis 접속 URL (기본값: redis://localhost:6379)
    """

    def __init__(self, url: str | None = None) -> None:
        redis_url = url or os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
        if "localhost" in redis_url:
            redis_url = redis_url.replace("localhost", "127.0.0.1")

        self._client: aioredis.Redis = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=60.0,
            socket_connect_timeout=5.0,
        )

    async def push_approval(self, feedback: dict[str, Any]) -> None:
        """
        사용자 승인/반려 피드백을 orchestra:approval:{task_id} 큐에 삽입합니다.

        오케스트라는 태스크별 큐(orchestra:approval:{approval_task_id})에서
        BLPOP으로 승인 응답을 대기합니다. 단일 큐(orchestra:results)에 push하면
        오케스트라가 응답을 수신하지 못하므로 반드시 task_id별 큐를 사용합니다.

        Args:
            feedback (dict): ApprovalFeedback 스키마 딕셔너리.
                             반드시 "task_id" 필드를 포함해야 합니다.
        """
        task_id = feedback.get("task_id", "")
        if not task_id:
            logger.error("[RedisBroker] push_approval: task_id 없음 — 피드백 무시")
            return
        key = f"{_APPROVAL_KEY_PREFIX}{task_id}"
        await self._client.rpush(key, json.dumps(feedback, ensure_ascii=False))
        logger.debug("[RedisBroker] push_approval key=%s action=%s", key, feedback.get("action"))

    async def push_to_orchestra(
        self,
        user_id: str,
        channel_id: str,
        content: str,
        thread_ts: str | None = None,
        source: str = "slack",
    ) -> str:
        """Discord/Telegram용 오케스트라 큐 직접 삽입 (Pub/Sub 전환 전까지 잔존).
        Slack은 SlackCommAgent가 cassiopeia.send_message()로 직접 처리합니다.
        """
        import uuid as _uuid
        from shared_core.dispatch_auth import sign_task as _sign_task
        task_id = str(_uuid.uuid4())
        session_id = f"{user_id}:{channel_id}"
        task: dict[str, Any] = {
            "task_id": task_id,
            "session_id": session_id,
            "requester": {"user_id": user_id, "channel_id": channel_id},
            "content": content,
            "source": source,
            "thread_ts": thread_ts,
        }
        await self._client.rpush("agent:orchestra:tasks", json.dumps(_sign_task(task), ensure_ascii=False))
        logger.debug("[RedisBroker] push_to_orchestra task_id=%s source=%s", task_id, source)
        return task_id

    async def blpop_comm_task(self, timeout: float = 5.0, queue_key: str | None = None) -> dict[str, Any] | None:
        """Discord/Telegram 아웃바운드 큐에서 결과를 수신합니다 (Pub/Sub 전환 전까지 잔존)."""
        key = queue_key or COMM_TASKS_KEY
        result = await self._client.blpop(key, timeout=timeout)
        if result is None:
            return None
        _, value = result
        return json.loads(value)

    # ── 세션 스레드 관리 ───────────────────────────────────────────────────────

    async def get_thread_ts(self, session_id: str) -> str | None:
        """
        세션에 연결된 Slack 스레드 루트 ts를 조회합니다.

        Args:
            session_id (str): 세션 식별자 (보통 task_id 또는 user_id+channel_id 조합).

        Returns:
            str | None: 저장된 thread_ts, 없으면 None.
        """
        return await self._client.get(f"slack:session:{session_id}:thread_ts")

    async def save_thread_ts(self, session_id: str, thread_ts: str) -> None:
        """세션의 스레드 루트 ts를 저장합니다 (TTL: 2시간)."""
        await self._client.setex(f"slack:session:{session_id}:thread_ts", _SESSION_TTL, thread_ts)

    async def get_progress_msg_ts(self, session_id: str) -> str | None:
        """진행 상태 메시지의 ts를 조회합니다 (chat_update 용)."""
        return await self._client.get(f"slack:session:{session_id}:progress_msg_ts")

    async def save_progress_msg_ts(self, session_id: str, ts: str) -> None:
        """진행 상태 메시지의 ts를 저장합니다 (TTL: 2시간)."""
        await self._client.setex(f"slack:session:{session_id}:progress_msg_ts", _SESSION_TTL, ts)

    # ── 태스크 컨텍스트 ────────────────────────────────────────────────────────

    async def save_task_context(self, task_id: str, context: dict[str, Any]) -> None:
        """
        태스크 컨텍스트(채널 ID, 스레드 ts 등)를 저장합니다.
        승인 버튼 클릭 시 채널/스레드 정보를 복원하는 데 사용합니다.

        Args:
            task_id (str): 태스크 식별자.
            context (dict): 저장할 컨텍스트 딕셔너리.
        """
        await self._client.setex(
            f"slack:task:{task_id}:context",
            _SESSION_TTL,
            json.dumps(context, ensure_ascii=False),
        )

    async def get_task_context(self, task_id: str) -> dict[str, Any] | None:
        """
        저장된 태스크 컨텍스트를 조회합니다.

        Args:
            task_id (str): 태스크 식별자.

        Returns:
            dict | None: 컨텍스트 딕셔너리, 없으면 None.
        """
        data = await self._client.get(f"slack:task:{task_id}:context")
        return json.loads(data) if data else None

    # ── 연결 관리 ──────────────────────────────────────────────────────────────

    async def ping(self) -> bool:
        """Redis 연결 상태를 확인합니다."""
        try:
            await self._client.ping()
            return True
        except Exception:
            return False

    async def update_agent_health(self, agent_name: str, fields: dict[str, str]) -> None:
        """
        agent:{agent_name}:health Hash를 갱신합니다 (하트비트 전송용).

        Args:
            agent_name: 에이전트 이름 (예: "communication_agent")
            fields: 저장할 헬스 필드 딕셔너리
        """
        key = f"agent:{agent_name}:health"
        await self._client.hset(key, mapping=fields)
        await self._client.expire(key, 60)

    async def close(self) -> None:
        """Redis 연결을 종료합니다."""
        await self._client.aclose()
