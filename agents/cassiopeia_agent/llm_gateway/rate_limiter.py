"""
LLM Gateway 토큰 기반 Rate Limiter

Redis 단순 카운터(INCRBY + EXPIRE) 방식:
  - 키: llm_gateway:{agent_id}:tokens (현재 시간 버킷 — 1시간 TTL)
  - check() 호출 시 per_request 한도 먼저 검사, 이후 시간당 누적 한도 검사
  - 초과 시 소비하지 않고 (False, retry_after) 반환
"""
from __future__ import annotations

import time

import redis.asyncio as aioredis


class TokenRateLimiter:
    def __init__(
        self,
        redis_client: aioredis.Redis,
        tokens_per_hour: int = 10_000,
        max_per_request: int = 2_000,
    ) -> None:
        self._redis = redis_client
        self._tokens_per_hour = tokens_per_hour
        self._max_per_request = max_per_request
        self._window = 3600  # 1시간

    def _key(self, agent_id: str) -> str:
        bucket = int(time.time()) // self._window
        return f"llm_gateway:{agent_id}:tokens:{bucket}"

    async def check(self, agent_id: str, requested_tokens: int) -> tuple[bool, int]:
        """토큰 사용 허용 여부를 확인하고 허용 시 소비합니다.

        Returns:
            (allowed, retry_after_seconds)
            - per_request 초과: (False, 0) — 요청 자체가 너무 큼
            - 시간당 한도 초과: (False, retry_after > 0)
            - 허용: (True, 0)
        """
        if requested_tokens > self._max_per_request:
            return False, 0

        key = self._key(agent_id)
        current = int(await self._redis.get(key) or 0)

        if current + requested_tokens > self._tokens_per_hour:
            bucket_start = (int(time.time()) // self._window) * self._window
            retry_after = bucket_start + self._window - int(time.time())
            return False, max(1, retry_after)

        await self._redis.incrby(key, requested_tokens)
        await self._redis.expire(key, self._window)
        return True, 0

    async def get_used_tokens(self, agent_id: str) -> int:
        key = self._key(agent_id)
        return int(await self._redis.get(key) or 0)
