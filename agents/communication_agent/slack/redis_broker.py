"""
Redis 메시지 브로커 클라이언트
- agent:orchestra:tasks   : 소통 에이전트 → 오케스트라 (사용자 요청 전달)
- agent:communication:tasks: 오케스트라 → 소통 에이전트 (처리 결과 수신)
- orchestra:results        : 소통 에이전트 → 오케스트라 (사용자 승인/반려 피드백)
- slack:session:{id}:*     : 세션 기반 스레드 및 진행 메시지 ts 캐싱
"""

import json
import logging
import os
import uuid
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger("slack_agent.redis_broker")

# Redis 큐 키 상수
ORCHESTRA_TASKS_KEY = "agent:orchestra:tasks"
COMM_TASKS_KEY = "agent:communication:tasks"                       # Slack 기본
DISCORD_COMM_TASKS_KEY = "agent:communication:discord:tasks"       # Discord 전용
TELEGRAM_COMM_TASKS_KEY = "agent:communication:telegram:tasks"     # Telegram 전용

# 플랫폼 → 통신 큐 매핑
PLATFORM_COMM_QUEUE: dict[str, str] = {
    "slack": COMM_TASKS_KEY,
    "discord": DISCORD_COMM_TASKS_KEY,
    "telegram": TELEGRAM_COMM_TASKS_KEY,
}

# 승인 피드백은 태스크별 큐를 사용 (오케스트라와 일치)
# 키 형식: orchestra:approval:{approval_task_id}
_APPROVAL_KEY_PREFIX = "orchestra:approval:"

# 세션 TTL: 2시간
_SESSION_TTL = 7200


class RedisBroker:
    """
    소통 에이전트의 Redis 메시지 브로커 클라이언트.

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

    # ── 오케스트라 큐 ──────────────────────────────────────────────────────────

    async def push_to_orchestra(
        self,
        user_id: str,
        channel_id: str,
        content: str,
        thread_ts: str | None = None,
        source: str = "slack",
    ) -> str:
        """
        사용자 요청을 agent:orchestra:tasks 큐에 삽입합니다.

        Args:
            user_id (str): 플랫폼 사용자 ID.
            channel_id (str): 플랫폼 채널/채팅 ID.
            content (str): 정제된 메시지 텍스트.
            thread_ts (str | None): 스레드 루트 ts (Slack) 또는 메시지 ID (Discord/Telegram).
            source (str): 메시지 출처 플랫폼 ("slack" | "discord" | "telegram").

        Returns:
            str: 생성된 task_id (UUID).
        """
        task_id = str(uuid.uuid4())
        session_id = f"{user_id}:{channel_id}"
        task: dict[str, Any] = {
            "task_id": task_id,
            "session_id": session_id,
            "requester": {"user_id": user_id, "channel_id": channel_id},
            "content": content,
            "source": source,
            "thread_ts": thread_ts,
        }
        await self._client.rpush(ORCHESTRA_TASKS_KEY, json.dumps(task, ensure_ascii=False))
        logger.debug("[RedisBroker] push_to_orchestra task_id=%s session_id=%s source=%s", task_id, session_id, source)
        return task_id

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

    async def blpop_comm_task(self, timeout: float = 5.0, queue_key: str | None = None) -> dict[str, Any] | None:
        """
        통신 결과 큐에서 메시지를 블로킹으로 수신합니다.

        Args:
            timeout (float): 블로킹 대기 시간(초). 0이면 무제한 대기.
            queue_key (str | None): 수신할 큐 키. None이면 기본 Slack 큐 사용.

        Returns:
            dict | None: OrchestraResult 스키마 딕셔너리, 타임아웃 시 None.
        """
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
