"""
세션 상태 및 대화 이력 관리 (State Manager)
- Redis Hash: 세션 상태 (TTL: 2시간)
- Redis List: 최근 메시지 슬라이딩 윈도우 (최대 20개)
- PostgreSQL: 영구 이력 저장 (선택적 — POSTGRES_URL 없으면 skip)
- state_management_design.md 스키마 준수
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger("orchestra_agent.state_manager")

# 세션 TTL: 2시간
_SESSION_TTL = 7200
# 태스크 상태 TTL: 24시간
_TASK_TTL = 86400
# 슬라이딩 윈도우: 최근 20개 메시지
_MAX_MESSAGES = 20
# 요약 트리거 임계값
_SUMMARIZE_THRESHOLD = 20
_SUMMARIZE_TOKEN_THRESHOLD = 8000


class StateManager:
    """
    오케스트라 에이전트의 세션 상태 및 대화 이력 관리자.

    환경 변수:
        REDIS_URL:      Redis 접속 URL (기본값: redis://localhost:6379)
        POSTGRES_URL:   PostgreSQL 접속 URL (선택, 없으면 영구 저장 skip)
    """

    def __init__(
        self,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        if redis_client is not None:
            self._redis = redis_client
        else:
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
            self._redis = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=5.0,
            )

        # PostgreSQL 클라이언트 (선택적)
        self._pg_pool = None
        self._pg_enabled = False

    async def init_postgres(self) -> None:
        """PostgreSQL 연결 풀을 초기화합니다 (POSTGRES_URL 없으면 skip)."""
        postgres_url = os.environ.get("POSTGRES_URL")
        if not postgres_url:
            logger.info("[StateManager] POSTGRES_URL 미설정 — PostgreSQL 비활성화")
            return
        try:
            import asyncpg
            self._pg_pool = await asyncpg.create_pool(postgres_url, min_size=1, max_size=5)
            self._pg_enabled = True
            logger.info("[StateManager] PostgreSQL 연결 성공")
        except Exception as exc:
            logger.warning("[StateManager] PostgreSQL 초기화 실패 (%s) — 비활성화", exc)

    async def close(self) -> None:
        """연결을 종료합니다."""
        await self._redis.aclose()
        if self._pg_pool:
            await self._pg_pool.close()

    # ── 세션 상태 (Redis Hash) ─────────────────────────────────────────────────

    async def get_session_state(self, session_id: str) -> dict[str, Any]:
        """Redis에서 세션 상태를 조회합니다."""
        data = await self._redis.hgetall(f"session:{session_id}:state")
        return data

    async def update_session_state(self, session_id: str, fields: dict[str, Any]) -> None:
        """세션 상태를 업데이트하고 TTL을 갱신합니다."""
        key = f"session:{session_id}:state"
        # datetime 값은 ISO 문자열로 직렬화
        serialized = {
            k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
            for k, v in fields.items()
        }
        serialized["last_active_at"] = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(key, mapping=serialized)
        await self._redis.expire(key, _SESSION_TTL)

    async def init_session(
        self,
        session_id: str,
        user_id: str,
        channel_id: str,
    ) -> None:
        """새 세션 상태를 초기화합니다 (이미 있으면 last_active_at만 갱신)."""
        key = f"session:{session_id}:state"
        exists = await self._redis.exists(key)
        if not exists:
            now = datetime.now(timezone.utc).isoformat()
            await self._redis.hset(key, mapping={
                "last_summary": "",
                "active_agent": "",
                "current_goal": "",
                "current_plan": "{}",
                "token_usage": json.dumps({"input": 0, "output": 0, "total": 0, "cost_usd": 0.0}),
                "user_id": user_id,
                "channel_id": channel_id,
                "created_at": now,
                "last_active_at": now,
            })
            await self._redis.expire(key, _SESSION_TTL)
            logger.debug("[StateManager] 세션 초기화 session_id=%s", session_id)
        else:
            await self._redis.hset(key, "last_active_at", datetime.now(timezone.utc).isoformat())
            await self._redis.expire(key, _SESSION_TTL)

        # PostgreSQL sessions 테이블에 upsert
        if self._pg_enabled and self._pg_pool:
            await self._pg_pool.execute(
                """
                INSERT INTO sessions (session_id, user_id, channel_id)
                VALUES ($1::uuid, $2, $3)
                ON CONFLICT (session_id) DO UPDATE SET last_active = NOW()
                """,
                session_id.replace(":", "-"),  # user_id:channel_id → UUID 형식 변환
                user_id,
                channel_id,
            )

    # ── 메시지 이력 (Redis List) ───────────────────────────────────────────────

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        provider: str = "system",
        tokens: int = 0,
    ) -> None:
        """
        대화 이력에 메시지를 추가합니다.

        Args:
            session_id: 세션 식별자.
            role: "user" | "assistant" | "system"
            content: 메시지 본문.
            provider: "gemini" | "openai" | "anthropic" | "system"
            tokens: 토큰 수 (비용 추적용).
        """
        key = f"session:{session_id}:messages"
        message = json.dumps({
            "role": role,
            "content": content,
            "provider": provider,
            "tokens": tokens,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False)

        await self._redis.rpush(key, message)
        await self._redis.ltrim(key, -_MAX_MESSAGES, -1)
        await self._redis.expire(key, _SESSION_TTL)

        # token_usage 업데이트
        await self._update_token_usage(session_id, tokens)

        # PostgreSQL 영구 저장
        if self._pg_enabled and self._pg_pool:
            await self._pg_pool.execute(
                """
                INSERT INTO chat_history (session_id, role, content, provider, tokens_in, tokens_out, created_at)
                VALUES ($1::uuid, $2, $3, $4, $5, 0, NOW())
                """,
                session_id.replace(":", "-"),
                role,
                content,
                provider,
                tokens,
            )

    async def _update_token_usage(self, session_id: str, tokens: int) -> None:
        """토큰 사용량을 업데이트합니다."""
        key = f"session:{session_id}:state"
        raw = await self._redis.hget(key, "token_usage")
        usage = json.loads(raw) if raw else {"input": 0, "output": 0, "total": 0, "cost_usd": 0.0}
        usage["total"] = usage.get("total", 0) + tokens
        await self._redis.hset(key, "token_usage", json.dumps(usage))

    # ── LLM 컨텍스트 구성 ─────────────────────────────────────────────────────

    async def build_context_for_llm(
        self,
        session_id: str,
        provider: str = "gemini",
    ) -> list[dict[str, Any]]:
        """
        현재 세션의 컨텍스트를 LLM 형식으로 재구성합니다.

        Args:
            session_id: 세션 식별자.
            provider: "gemini" | "openai" | "anthropic"

        Returns:
            LLM 메시지 리스트 (role/content 형식).
        """
        state = await self._redis.hgetall(f"session:{session_id}:state")
        messages_raw = await self._redis.lrange(f"session:{session_id}:messages", 0, -1)
        messages = [json.loads(m) for m in messages_raw]

        context: list[dict[str, Any]] = []

        # 이전 대화 요약 주입 (있는 경우)
        summary = state.get("last_summary", "")
        if summary:
            if provider == "gemini":
                context.append({"role": "user", "content": f"[이전 대화 요약]: {summary}"})
                context.append({"role": "model", "content": "이해했습니다. 이전 대화 맥락을 참고하겠습니다."})
            else:
                context.append({"role": "system", "content": f"[이전 대화 요약]: {summary}"})

        # 최근 메시지 주입
        for msg in messages:
            role = msg.get("role", "user")
            if provider == "gemini":
                # Gemini는 user/model 역할 체계
                role = role.replace("assistant", "model")
            context.append({"role": role, "content": msg.get("content", "")})

        return context

    async def maybe_summarize(self, session_id: str) -> None:
        """
        필요 시 오래된 메시지를 요약하고 Redis를 정리합니다.

        트리거 조건:
            - Redis List 항목이 _SUMMARIZE_THRESHOLD(20)개 초과
            - token_usage.total이 _SUMMARIZE_TOKEN_THRESHOLD(8000) 초과
        """
        msg_count = await self._redis.llen(f"session:{session_id}:messages")
        state = await self._redis.hgetall(f"session:{session_id}:state")
        token_usage = json.loads(state.get("token_usage", "{}"))
        total_tokens = token_usage.get("total", 0)

        if msg_count <= _SUMMARIZE_THRESHOLD and total_tokens <= _SUMMARIZE_TOKEN_THRESHOLD:
            return

        logger.info("[StateManager] 요약 트리거 — session=%s msg_count=%d tokens=%d",
                    session_id, msg_count, total_tokens)

        # 오래된 절반을 추출하여 요약
        half = msg_count // 2
        old_messages_raw = await self._redis.lrange(
            f"session:{session_id}:messages", 0, half - 1
        )
        old_messages = [json.loads(m) for m in old_messages_raw]
        summary = await self._summarize_messages(old_messages)

        # 오래된 메시지 제거 + 요약 저장
        await self._redis.ltrim(f"session:{session_id}:messages", half, -1)
        await self._redis.hset(f"session:{session_id}:state", "last_summary", summary)
        logger.info("[StateManager] 요약 완료 — session=%s", session_id)

    async def _summarize_messages(self, messages: list[dict[str, Any]]) -> str:
        """Gemini/Claude API로 메시지 목록을 1~2문장으로 요약합니다."""
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            content = "\n".join(
                f"[{m.get('role')}]: {m.get('content', '')[:300]}"
                for m in messages
            )
            prompt = f"다음 대화를 한국어로 1~2문장으로 간결하게 요약하세요:\n\n{content}"
            resp = await client.aio.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(max_output_tokens=200),
            )
            return resp.text or ""
        except Exception as exc:
            logger.warning("[StateManager] 요약 API 실패: %s", exc)
            return ""

    # ── 태스크 상태 (Redis Hash) ──────────────────────────────────────────────

    async def update_task_state(self, task_id: str, fields: dict[str, Any]) -> None:
        """
        태스크 상태를 업데이트합니다.

        Args:
            task_id: 태스크 식별자.
            fields: 업데이트할 필드 딕셔너리
                    (status, session_id, agent, step, created_at, updated_at 등).
        """
        key = f"task:{task_id}:state"
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        serialized = {
            k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
            for k, v in fields.items()
        }
        await self._redis.hset(key, mapping=serialized)
        await self._redis.expire(key, _TASK_TTL)

    async def get_task_state(self, task_id: str) -> dict[str, Any]:
        """태스크 상태를 조회합니다."""
        return await self._redis.hgetall(f"task:{task_id}:state")
