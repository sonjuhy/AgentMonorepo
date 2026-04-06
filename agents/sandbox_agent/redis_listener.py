"""
Sandbox Agent Redis 리스너
- OrchestraManager가 agent:sandbox:tasks 큐에 push한 DispatchMessage를 BLPOP으로 수신
- SandboxAgent.handle_dispatch()에 위임 후 orchestra /results로 결과 보고
- agent:sandbox:health Redis Hash를 15초 주기로 갱신 (OrchestraManager HealthMonitor 연동)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis

from .agent import SandboxAgent

logger = logging.getLogger("sandbox_agent.redis_listener")

_QUEUE_KEY = "agent:sandbox:tasks"
_HEALTH_KEY = "agent:sandbox:health"
_HEARTBEAT_INTERVAL = 15         # 초
_BLPOP_TIMEOUT = 5               # 초 (5초마다 CancelledError 체크)


class SandboxRedisListener:
    """
    OrchestraManager ↔ SandboxAgent 연결 브리지.

    - BLPOP으로 agent:sandbox:tasks 큐 감시
    - SandboxAgent.handle_dispatch() 위임
    - HTTP POST {orchestra_url}/results 결과 보고
    - 15초 주기 heartbeat (agent:sandbox:health)
    """

    def __init__(
        self,
        agent: SandboxAgent,
        redis_url: str | None = None,
        orchestra_url: str | None = None,
    ) -> None:
        self._agent = agent
        self._redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self._orchestra_url = orchestra_url or os.environ.get(
            "ORCHESTRA_URL", "http://orchestra-agent:8001"
        )
        self._redis: aioredis.Redis | None = None
        self._current_task_count: int = 0

    # ── 초기화 / 정리 ──────────────────────────────────────────────────────────

    async def _ensure_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def close(self) -> None:
        """Redis 연결을 닫습니다."""
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    # ── 메인 루프 ──────────────────────────────────────────────────────────────

    async def listen_tasks(self) -> None:
        """
        agent:sandbox:tasks 큐를 BLPOP으로 감시하는 메인 루프.
        CancelledError를 수신하면 정상 종료합니다.
        """
        redis = await self._ensure_redis()
        logger.info("[SandboxRedisListener] listen_tasks 시작 (queue: %s)", _QUEUE_KEY)

        try:
            while True:
                result = await redis.blpop(_QUEUE_KEY, timeout=_BLPOP_TIMEOUT)
                if result is None:
                    continue   # timeout → 다시 대기

                _, raw = result
                asyncio.create_task(self.handle_task(raw))

        except asyncio.CancelledError:
            logger.info("[SandboxRedisListener] listen_tasks 정상 종료")
        except Exception as exc:
            logger.error("[SandboxRedisListener] listen_tasks 오류: %s", exc)
            raise

    # ── 태스크 처리 ────────────────────────────────────────────────────────────

    async def handle_task(self, raw: str) -> None:
        """
        수신한 JSON 문자열을 파싱하고 SandboxAgent에 위임한 뒤 결과를 보고합니다.

        Args:
            raw: BLPOP으로 받은 직렬화된 JSON 문자열 (DispatchMessage 형식).
        """
        task_id = "unknown"
        try:
            dispatch_msg: dict[str, Any] = json.loads(raw)
            task_id = dispatch_msg.get("task_id", "unknown")
            logger.info("[SandboxRedisListener] 태스크 수신: task_id=%s", task_id)

            self._current_task_count += 1
            await self._update_health("BUSY")

            agent_result: dict[str, Any] = await self._agent.handle_dispatch(dispatch_msg)

        except json.JSONDecodeError as exc:
            logger.error("[SandboxRedisListener] JSON 파싱 실패: %s", exc)
            agent_result = {
                "task_id": task_id,
                "status": "FAILED",
                "result_data": {},
                "error": {"code": "PARSE_ERROR", "message": str(exc), "traceback": None},
                "usage_stats": {},
            }
        except Exception as exc:
            logger.error(
                "[SandboxRedisListener] 태스크 처리 실패 task_id=%s: %s", task_id, exc
            )
            agent_result = {
                "task_id": task_id,
                "status": "FAILED",
                "result_data": {},
                "error": {"code": "INTERNAL_ERROR", "message": str(exc), "traceback": None},
                "usage_stats": {},
            }
        finally:
            self._current_task_count = max(0, self._current_task_count - 1)
            if self._current_task_count == 0:
                await self._update_health("IDLE")

        await self._report_result(
            task_id=agent_result.get("task_id", task_id),
            result_data=agent_result.get("result_data", {}),
            status=agent_result.get("status", "FAILED"),
            error=agent_result.get("error"),
        )

    # ── 결과 보고 ──────────────────────────────────────────────────────────────

    async def _report_result(
        self,
        task_id: str,
        result_data: dict[str, Any],
        status: str,
        error: dict[str, Any] | None,
    ) -> None:
        """
        처리 결과를 OrchestraManager POST /results 엔드포인트로 전송합니다.
        네트워크 오류 시 최대 3회 재시도 (1s, 2s, 4s 백오프).
        """
        payload = {
            "task_id": task_id,
            "status": status,
            "result_data": result_data,
            "error": error,
            "usage_stats": {},
        }
        url = f"{self._orchestra_url}/results"

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                logger.info(
                    "[SandboxRedisListener] 결과 보고 완료: task_id=%s status=%s",
                    task_id, status,
                )
                return
            except Exception as exc:
                wait = 2 ** attempt
                logger.warning(
                    "[SandboxRedisListener] 결과 보고 실패 (attempt %d/3): %s — %ds 후 재시도",
                    attempt + 1, exc, wait,
                )
                if attempt < 2:
                    await asyncio.sleep(wait)

        logger.error(
            "[SandboxRedisListener] 결과 보고 최종 실패: task_id=%s", task_id
        )

    # ── Heartbeat ──────────────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """
        15초 주기로 agent:sandbox:health Redis Hash를 갱신합니다.
        OrchestraManager HealthMonitor가 이 키를 읽어 가용 여부를 판단합니다.
        CancelledError를 수신하면 정상 종료합니다.
        """
        logger.info("[SandboxRedisListener] heartbeat 시작")
        try:
            while True:
                await self._update_health(
                    "BUSY" if self._current_task_count > 0 else "IDLE"
                )
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            logger.info("[SandboxRedisListener] heartbeat 정상 종료")

    async def _update_health(self, status: str) -> None:
        """agent:sandbox:health Hash 필드를 업데이트합니다."""
        try:
            redis = await self._ensure_redis()
            pool_stats = self._agent.pool_stats()
            await redis.hset(
                _HEALTH_KEY,
                mapping={
                    "agent_id": "sandbox-agent",
                    "status": status,
                    "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                    "version": "1.0.0",
                    "capabilities": "execute_code,firecracker,docker",
                    "current_tasks": str(self._current_task_count),
                    "max_concurrency": str(pool_stats.get("max_size", 10)),
                    "runtime": pool_stats.get("runtime", "unknown"),
                    "pool_ready": str(pool_stats.get("ready_count", 0)),
                },
            )
        except Exception as exc:
            logger.warning("[SandboxRedisListener] heartbeat 업데이트 실패: %s", exc)
