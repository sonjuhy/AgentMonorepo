"""
[TDD] LLM Gateway TokenRateLimiter 단위 테스트

- 시간당 토큰 한도 초과 시 (False, retry_after) 반환
- 한도 미만이면 (True, 0) 반환
- 여러 에이전트는 독립적으로 카운트
- per_request 초과 시 (False, 0) 반환
"""
from __future__ import annotations

import fakeredis
import pytest
import pytest_asyncio


class TestTokenRateLimiter:
    @pytest_asyncio.fixture
    async def redis(self):
        server = fakeredis.FakeServer()
        r = fakeredis.FakeAsyncRedis(decode_responses=True, server=server)
        yield r
        await r.aclose()

    @pytest_asyncio.fixture
    async def limiter(self, redis):
        from agents.cassiopeia_agent.llm_gateway.rate_limiter import TokenRateLimiter
        return TokenRateLimiter(redis_client=redis, tokens_per_hour=1000, max_per_request=200)

    async def test_first_request_allowed(self, limiter):
        allowed, retry_after = await limiter.check("agent-a", requested_tokens=100)
        assert allowed is True
        assert retry_after == 0

    async def test_within_limit_allowed(self, limiter):
        await limiter.check("agent-a", requested_tokens=150)
        allowed, _ = await limiter.check("agent-a", requested_tokens=150)
        assert allowed is True

    async def test_exceeds_hourly_limit_blocked(self, limiter):
        await limiter.check("agent-a", requested_tokens=200)
        await limiter.check("agent-a", requested_tokens=200)
        await limiter.check("agent-a", requested_tokens=200)
        await limiter.check("agent-a", requested_tokens=200)
        await limiter.check("agent-a", requested_tokens=200)  # 누적 1000
        allowed, retry_after = await limiter.check("agent-a", requested_tokens=100)
        assert allowed is False
        assert retry_after > 0

    async def test_exceeds_per_request_limit_blocked(self, limiter):
        # max_per_request=200이므로 201은 한 번에 요청 불가
        allowed, retry_after = await limiter.check("agent-a", requested_tokens=201)
        assert allowed is False
        assert retry_after == 0  # hourly 초과가 아닌 per_request 초과

    async def test_different_agents_independent(self, limiter):
        # agent-a 한도 소진
        for _ in range(5):
            await limiter.check("agent-a", requested_tokens=200)
        # agent-b는 독립적
        allowed, _ = await limiter.check("agent-b", requested_tokens=100)
        assert allowed is True

    async def test_consume_records_tokens(self, limiter):
        await limiter.check("agent-x", requested_tokens=150)
        used = await limiter.get_used_tokens("agent-x")
        assert used == 150

    async def test_multiple_calls_accumulate(self, limiter):
        await limiter.check("agent-a", requested_tokens=100)
        await limiter.check("agent-a", requested_tokens=150)
        used = await limiter.get_used_tokens("agent-a")
        assert used == 250

    async def test_exact_hourly_limit_allowed(self, limiter):
        # 200 × 5 = 1000 = tokens_per_hour, 마지막도 허용돼야 함
        for _ in range(4):
            await limiter.check("agent-a", requested_tokens=200)
        allowed, _ = await limiter.check("agent-a", requested_tokens=200)
        assert allowed is True

    async def test_over_limit_not_consumed(self, limiter):
        for _ in range(5):
            await limiter.check("agent-a", requested_tokens=200)  # 1000 소진
        await limiter.check("agent-a", requested_tokens=100)  # 초과 — 소비 안 됨
        used = await limiter.get_used_tokens("agent-a")
        assert used == 1000
