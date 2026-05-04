"""
LLM Gateway Handler

외부 에이전트의 llm_call 요청을 처리하는 게이트웨이.

처리 순서:
  1. 에이전트 등록 및 allow_llm_access 확인
  2. 파라미터 검증 (화이트리스트)
  3. Rate limit 확인
  4. shared_core.llm 호출
  5. 결과를 cassiopeia로 요청 에이전트에게 반송
"""
from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from agents.cassiopeia_agent.llm_gateway.rate_limiter import TokenRateLimiter

logger = logging.getLogger(__name__)

_MAX_TOKENS_LIMIT = 2_000
_ALLOWED_ROLES = {"user", "assistant"}
_MAX_MESSAGES = 20


class LLMGatewayHandler:
    def __init__(
        self,
        redis_client: aioredis.Redis,
        llm_provider: Any,
        cassiopeia: Any,
        rate_limiter: TokenRateLimiter | None = None,
    ) -> None:
        self._redis = redis_client
        self._llm = llm_provider
        self._cassiopeia = cassiopeia
        self._rate_limiter = rate_limiter or TokenRateLimiter(redis_client=redis_client)

    async def handle(self, request: dict) -> None:
        agent_id = request.get("agent_id", "")
        task_id = request.get("task_id", "")

        # ── 1. 인증 ──────────────────────────────────────────────────────────
        auth_error = await self._check_auth(agent_id)
        if auth_error:
            await self._reply(agent_id, task_id, status="unauthorized", error=auth_error)
            return

        # ── 2. 파라미터 검증 ──────────────────────────────────────────────────
        messages, max_tokens, temperature, param_error = self._validate_params(request)
        if param_error:
            await self._reply(agent_id, task_id, status="error", error=param_error)
            return

        # ── 3. Rate limit ─────────────────────────────────────────────────────
        allowed, retry_after = await self._rate_limiter.check(agent_id, max_tokens)
        if not allowed:
            await self._reply(
                agent_id, task_id,
                status="rate_limited",
                error="토큰 사용량 한도 초과",
                extra={"retry_after": retry_after},
            )
            return

        # ── 4. LLM 호출 ───────────────────────────────────────────────────────
        try:
            content, usage = await self._llm.generate_response(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            logger.warning("LLM gateway error for agent %s: %s", agent_id, exc)
            await self._reply(agent_id, task_id, status="error", error=str(exc))
            return

        # ── 5. 결과 반송 ──────────────────────────────────────────────────────
        await self._reply(
            agent_id, task_id,
            status="completed",
            content=content,
            usage={
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            },
        )

    async def _check_auth(self, agent_id: str) -> str | None:
        raw = await self._redis.hget("agents:registry", agent_id)
        if not raw:
            return f"에이전트 '{agent_id}'가 등록되어 있지 않습니다"
        data = json.loads(raw)
        if not data.get("allow_llm_access", False):
            return f"에이전트 '{agent_id}'에 LLM 접근 권한이 없습니다"
        return None

    def _validate_params(
        self, request: dict
    ) -> tuple[list[dict], int, float, str | None]:
        messages = request.get("messages", [])
        max_tokens = request.get("max_tokens", 500)
        temperature = request.get("temperature", 0.7)

        if not messages:
            return [], 0, 0.0, "messages가 비어 있습니다"

        if len(messages) > _MAX_MESSAGES:
            return [], 0, 0.0, f"messages는 최대 {_MAX_MESSAGES}개까지 허용됩니다"

        for msg in messages:
            if msg.get("role") not in _ALLOWED_ROLES:
                return [], 0, 0.0, (
                    f"허용되지 않는 role: '{msg.get('role')}'. "
                    f"허용: {sorted(_ALLOWED_ROLES)}"
                )

        if not isinstance(max_tokens, int) or max_tokens < 1 or max_tokens > _MAX_TOKENS_LIMIT:
            return [], 0, 0.0, f"max_tokens는 1~{_MAX_TOKENS_LIMIT} 범위여야 합니다"

        if not isinstance(temperature, (int, float)) or not (0.0 <= temperature <= 1.0):
            return [], 0, 0.0, "temperature는 0.0~1.0 범위여야 합니다"

        safe_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
        return safe_messages, int(max_tokens), float(temperature), None

    async def _reply(
        self,
        agent_id: str,
        task_id: str,
        *,
        status: str,
        content: str = "",
        usage: dict | None = None,
        error: str | None = None,
        extra: dict | None = None,
    ) -> None:
        payload: dict = {
            "task_id": task_id,
            "status": status,
            "content": content,
            "usage": usage or {},
            "error": error,
        }
        if extra:
            payload.update(extra)
        await self._cassiopeia.send_message(
            action="llm_result",
            payload=payload,
            receiver=agent_id,
        )
