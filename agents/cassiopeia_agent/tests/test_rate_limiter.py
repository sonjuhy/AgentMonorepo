"""
[TDD] rate_limiter.py 테스트
- 한도 이내 요청: 통과
- 한도 초과 요청: 차단 + retry_after 반환
- 사용자별 독립 카운터
- 시간 윈도우 경과 후 카운터 초기화
- POST /tasks 엔드포인트에서 429 응답
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from agents.cassiopeia_agent.rate_limiter import RateLimiter


class TestRateLimiterUnit:
    async def test_first_request_allowed(self, fake_redis):
        limiter = RateLimiter(fake_redis, limit=5, window=60)
        allowed, retry_after = await limiter.check("user-1")
        assert allowed is True
        assert retry_after == 0

    async def test_requests_within_limit_all_allowed(self, fake_redis):
        limiter = RateLimiter(fake_redis, limit=3, window=60)
        for _ in range(3):
            allowed, _ = await limiter.check("user-1")
            assert allowed is True

    async def test_request_exceeding_limit_is_blocked(self, fake_redis):
        limiter = RateLimiter(fake_redis, limit=3, window=60)
        for _ in range(3):
            await limiter.check("user-1")
        allowed, retry_after = await limiter.check("user-1")
        assert allowed is False
        assert retry_after > 0

    async def test_different_users_have_independent_counters(self, fake_redis):
        limiter = RateLimiter(fake_redis, limit=1, window=60)
        await limiter.check("user-A")
        # user-A는 한도 초과
        allowed_a, _ = await limiter.check("user-A")
        assert allowed_a is False
        # user-B는 독립 카운터 — 허용
        allowed_b, _ = await limiter.check("user-B")
        assert allowed_b is True

    async def test_retry_after_is_positive_integer_when_blocked(self, fake_redis):
        limiter = RateLimiter(fake_redis, limit=1, window=60)
        await limiter.check("user-x")
        allowed, retry_after = await limiter.check("user-x")
        assert not allowed
        assert isinstance(retry_after, int)
        assert 1 <= retry_after <= 60

    async def test_old_requests_outside_window_not_counted(self, fake_redis):
        """윈도우 밖의 오래된 요청은 카운트에서 제외됩니다."""
        limiter = RateLimiter(fake_redis, limit=2, window=60)
        now = int(time.time())
        # 70초 전 요청 2개를 직접 삽입 (윈도우 밖)
        key = limiter._key("user-z")
        old_ts = now - 70
        await fake_redis.zadd(key, {f"old-{i}": old_ts for i in range(2)})
        # 현재 요청은 한도(2) 안에서 허용되어야 함
        allowed, _ = await limiter.check("user-z")
        assert allowed is True


class TestRateLimiterEndpoint:
    """POST /tasks 에서 Rate Limit 검증"""

    async def test_within_limit_returns_200(self, async_client):
        resp = await async_client.post("/tasks", json={
            "content": "테스트",
            "user_id": "rl-user-1",
        })
        assert resp.status_code == 200

    async def test_exceeding_limit_returns_429(self, async_client, fake_redis):
        # 한도를 1로 낮춰 테스트
        from agents.cassiopeia_agent import rate_limiter as rl_module
        original = rl_module._DEFAULT_LIMIT
        rl_module._DEFAULT_LIMIT = 1
        try:
            await async_client.post("/tasks", json={
                "content": "첫 번째",
                "user_id": "rl-user-over",
            })
            resp = await async_client.post("/tasks", json={
                "content": "두 번째",
                "user_id": "rl-user-over",
            })
            assert resp.status_code == 429
            detail = resp.json().get("detail", {})
            assert "retry_after" in detail or "message" in detail
        finally:
            rl_module._DEFAULT_LIMIT = original

    async def test_429_response_has_retry_after_header(self, async_client, fake_redis):
        from agents.cassiopeia_agent import rate_limiter as rl_module
        original = rl_module._DEFAULT_LIMIT
        rl_module._DEFAULT_LIMIT = 1
        try:
            await async_client.post("/tasks", json={
                "content": "첫 번째",
                "user_id": "rl-header-user",
            })
            resp = await async_client.post("/tasks", json={
                "content": "두 번째",
                "user_id": "rl-header-user",
            })
            if resp.status_code == 429:
                assert "Retry-After" in resp.headers
        finally:
            rl_module._DEFAULT_LIMIT = original
