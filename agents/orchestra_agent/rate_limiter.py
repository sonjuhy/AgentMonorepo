"""
사용자별 슬라이딩 윈도우 Rate Limiter

Redis Sorted Set을 이용한 슬라이딩 윈도우 알고리즘:
  - 각 요청을 타임스탬프 score로 zadd
  - 윈도우 밖 항목 제거 후 count 검사
  - 한도 초과 시 (False, retry_after_초) 반환

환경변수:
  RATE_LIMIT_PER_MIN  — 분당 허용 요청 수 (기본 20)
  RATE_LIMIT_WINDOW   — 슬라이딩 윈도우 초 (기본 60)
"""
from __future__ import annotations

import os
import time
import uuid

import redis.asyncio as aioredis

_DEFAULT_LIMIT: int = int(os.environ.get("RATE_LIMIT_PER_MIN", "20"))
_DEFAULT_WINDOW: int = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))


class RateLimiter:
    def __init__(
        self,
        redis_client: aioredis.Redis,
        limit: int | None = None,
        window: int | None = None,
    ) -> None:
        self._redis = redis_client
        self._limit = limit if limit is not None else _DEFAULT_LIMIT
        self._window = window if window is not None else _DEFAULT_WINDOW

    def _key(self, user_id: str) -> str:
        return f"rate_limit:{user_id}"

    async def check(self, user_id: str) -> tuple[bool, int]:
        """요청 허용 여부를 확인하고 카운터를 증가합니다.

        Returns:
            (allowed, retry_after_seconds)
            - allowed=True  → 요청 허용
            - allowed=False → 한도 초과, retry_after초 후 재시도
        """
        key = self._key(user_id)
        now = int(time.time())
        window_start = now - self._window

        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(uuid.uuid4()): now})
            pipe.zcount(key, window_start + 1, "+inf")
            pipe.expire(key, self._window)
            results = await pipe.execute()

        count: int = results[2]
        if count > self._limit:
            oldest = await self._redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                oldest_ts = int(oldest[0][1])
                retry_after = self._window - (now - oldest_ts)
            else:
                retry_after = self._window
            return False, max(1, retry_after)

        return True, 0
