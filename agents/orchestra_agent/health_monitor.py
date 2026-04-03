"""
에이전트 헬스 모니터링 및 Circuit Breaker
- 에이전트 하트비트 수집 (agent:{name}:health Redis Hash)
- 가용 에이전트 목록 조회 (30초 이내 하트비트 + IDLE 상태)
- Circuit Breaker: 5분 내 3회 이상 실패 시 MAINTENANCE 전환
- 동적 에이전트 등록/조회 (agents:registry Redis Hash)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger("orchestra_agent.health_monitor")

# Circuit Breaker 임계값
_CB_THRESHOLD = 3
_CB_WINDOW_SEC = 300   # 5분

# 하트비트 유효 시간 (30초)
_HEARTBEAT_VALID_SEC = 30


def _is_heartbeat_recent(last_heartbeat: str) -> bool:
    """last_heartbeat이 30초 이내인지 확인합니다."""
    if not last_heartbeat:
        return False
    try:
        hb_time = datetime.fromisoformat(last_heartbeat.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = (now - hb_time).total_seconds()
        return diff <= _HEARTBEAT_VALID_SEC
    except (ValueError, TypeError):
        return False


class HealthMonitor:
    """
    에이전트 헬스 모니터링 및 Circuit Breaker 관리자.

    환경 변수:
        REDIS_URL: Redis 접속 URL (기본값: redis://localhost:6379)
    """

    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        if redis_client is not None:
            self._redis = redis_client
        else:
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
            self._redis = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=5.0,
            )

    # ── 에이전트 등록 ─────────────────────────────────────────────────────────

    async def register_agent(self, agent_name: str, capabilities: list[str]) -> None:
        """에이전트를 시스템 레지스트리에 등록합니다 (시작 시 호출)."""
        await self._redis.hset(
            "agents:registry",
            agent_name,
            json.dumps({
                "name": agent_name,
                "capabilities": capabilities,
                "status": "IDLE",
                "registered_at": datetime.now(timezone.utc).isoformat(),
                "health_key": f"agent:{agent_name}:health",
            }, ensure_ascii=False),
        )
        logger.info("[HealthMonitor] 에이전트 등록: %s capabilities=%s", agent_name, capabilities)

    # ── 가용 에이전트 조회 ────────────────────────────────────────────────────

    async def get_available_agents(self) -> list[str]:
        """
        하트비트가 30초 이내이고 IDLE 상태인 에이전트 목록을 반환합니다.

        Returns:
            가용 에이전트 이름 목록.
        """
        registry_raw = await self._redis.hgetall("agents:registry")
        available: list[str] = []

        for name, data_raw in registry_raw.items():
            try:
                data = json.loads(data_raw)
                health = await self._redis.hgetall(f"agent:{name}:health")

                if health.get("status") == "IDLE" and _is_heartbeat_recent(health.get("last_heartbeat", "")):
                    available.append(name)
            except (json.JSONDecodeError, Exception):
                continue

        return available

    async def get_agent_health(self, agent_name: str) -> dict[str, Any]:
        """특정 에이전트의 헬스 정보를 조회합니다."""
        return await self._redis.hgetall(f"agent:{agent_name}:health")

    # ── Circuit Breaker ────────────────────────────────────────────────────────

    async def check_circuit_breaker(self, agent_name: str) -> bool:
        """
        Circuit Breaker 열림 여부를 확인합니다.

        Returns:
            True: 차단됨 (5분 내 3회 이상 실패), False: 정상
        """
        key = f"circuit:{agent_name}:failures"
        failures_raw = await self._redis.get(key)
        count = int(failures_raw or 0)
        is_open = count >= _CB_THRESHOLD
        if is_open:
            logger.warning("[HealthMonitor] Circuit Breaker 열림: agent=%s failures=%d", agent_name, count)
        return is_open

    async def record_failure(self, agent_name: str) -> None:
        """
        에이전트 실패를 기록합니다.
        _CB_THRESHOLD 이상 실패 시 MAINTENANCE 상태로 전환합니다.
        """
        key = f"circuit:{agent_name}:failures"
        count = await self._redis.incr(key)

        # 첫 번째 실패 시 TTL 설정 (5분 window)
        if count == 1:
            await self._redis.expire(key, _CB_WINDOW_SEC)

        if count >= _CB_THRESHOLD:
            await self._redis.hset(f"agent:{agent_name}:health", "status", "MAINTENANCE")
            logger.error(
                "[HealthMonitor] Circuit Breaker 작동: agent=%s (5분 내 %d회 실패 → MAINTENANCE)",
                agent_name,
                count,
            )

    async def record_success(self, agent_name: str) -> None:
        """에이전트 성공 시 실패 카운터를 초기화합니다."""
        key = f"circuit:{agent_name}:failures"
        await self._redis.delete(key)

    async def reset_circuit_breaker(self, agent_name: str) -> None:
        """
        Circuit Breaker를 수동으로 초기화합니다 (관리 목적).
        MAINTENANCE → IDLE 상태로 복구합니다.
        """
        await self._redis.delete(f"circuit:{agent_name}:failures")
        await self._redis.hset(f"agent:{agent_name}:health", "status", "IDLE")
        logger.info("[HealthMonitor] Circuit Breaker 초기화: agent=%s", agent_name)

    # ── 헬스 상태 요약 ────────────────────────────────────────────────────────

    async def get_system_health(self) -> dict[str, Any]:
        """모든 에이전트의 헬스 상태를 요약하여 반환합니다."""
        registry_raw = await self._redis.hgetall("agents:registry")
        summary: dict[str, Any] = {}

        for name, data_raw in registry_raw.items():
            health = await self._redis.hgetall(f"agent:{name}:health")
            cb_failures_raw = await self._redis.get(f"circuit:{name}:failures")
            summary[name] = {
                "status": health.get("status", "UNKNOWN"),
                "last_heartbeat": health.get("last_heartbeat", ""),
                "heartbeat_valid": _is_heartbeat_recent(health.get("last_heartbeat", "")),
                "circuit_breaker_failures": int(cb_failures_raw or 0),
                "circuit_breaker_open": int(cb_failures_raw or 0) >= _CB_THRESHOLD,
            }

        return summary
