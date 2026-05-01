"""
Archive Agent Redis 리스너
- OrchestraManager가 agent:archive_agent:tasks 큐에 push한 DispatchMessage를 BLPOP으로 수신
- ArchiveAgent.handle_dispatch()에 위임 후 orchestra /results로 결과 보고
- agent:archive_agent:health Redis Hash를 15초 주기로 갱신 (OrchestraManager HealthMonitor 연동)
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

from .unified_agent import UnifiedArchiveAgent

logger = logging.getLogger("archive_agent.redis_listener")

_AGENT_NAME = "archive_agent"
_QUEUE_KEY = f"agent:{_AGENT_NAME}:tasks"
_HEALTH_KEY = f"agent:{_AGENT_NAME}:health"
_DLQ_KEY = "orchestra:dlq"
_HEARTBEAT_INTERVAL: int = int(os.environ.get("HEARTBEAT_INTERVAL", "15"))
_BLPOP_TIMEOUT: int = int(os.environ.get("BLPOP_TIMEOUT", "5"))
_HTTP_REPORT_TIMEOUT: float = float(os.environ.get("HTTP_REPORT_TIMEOUT", "10.0"))
_HEALTH_TTL: int = _HEARTBEAT_INTERVAL * 4


class ArchiveRedisListener:
    """
    OrchestraManager ↔ UnifiedArchiveAgent 연결 브리지.

    - BLPOP으로 agent:archive_agent:tasks 큐 감시
    - UnifiedArchiveAgent에게 위임 (스스로 Notion/Obsidian 판단)
    - HTTP POST {orchestra_url}/results 결과 보고
    - 15초 주기 heartbeat (agent:archive_agent:health)
    """

    def __init__(
        self,
        archive_agent: UnifiedArchiveAgent | None = None,
        redis_url: str | None = None,
        orchestra_url: str | None = None,
    ) -> None:
        self._agent = archive_agent or UnifiedArchiveAgent()
        
        _url = redis_url or os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
        self._redis_url = _url.replace("localhost", "127.0.0.1")
        self._orchestra_url = orchestra_url or os.environ.get(
            "ORCHESTRA_URL", "http://127.0.0.1:8001"
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
        agent:archive_agent:tasks 큐를 BLPOP으로 감시하는 메인 루프.
        CancelledError를 수신하면 정상 종료합니다.
        """
        redis = await self._ensure_redis()
        logger.info("[ArchiveRedisListener] listen_tasks 시작 (queue: %s)", _QUEUE_KEY)

        try:
            while True:
                result = await redis.blpop(_QUEUE_KEY, timeout=_BLPOP_TIMEOUT)
                if result is None:
                    continue   # timeout → 다시 대기

                _, raw = result
                task = asyncio.create_task(self.handle_task(raw))
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)

        except asyncio.CancelledError:
            logger.info("[ArchiveRedisListener] listen_tasks 정상 종료")
        except Exception as exc:
            logger.error("[ArchiveRedisListener] listen_tasks 오류: %s", exc)
            raise

    # ── 태스크 처리 ────────────────────────────────────────────────────────────

    async def handle_task(self, raw: str) -> None:
        """
        수신한 JSON 문자열을 파싱하고 ArchiveAgent에 위임한 뒤 결과를 보고합니다.
        CancelledError 포함 모든 경로에서 반드시 오케스트라로 결과를 전송합니다.

        Args:
            raw: BLPOP으로 받은 직렬화된 JSON 문자열 (DispatchMessage 형식).
        """
        task_id = "unknown"
        agent_result: dict[str, Any] = {
            "task_id": "unknown",
            "agent": _AGENT_NAME,
            "status": "FAILED",
            "result_data": {},
            "reference_id": None,
            "payload_summary": None,
            "error": {"code": "INTERNAL_ERROR", "message": "처리 중 알 수 없는 오류", "traceback": None},
            "usage_stats": {},
        }
        try:
            dispatch_msg: dict[str, Any] = json.loads(raw)
            task_id = dispatch_msg.get("task_id", "unknown")
            agent_result["task_id"] = task_id
            logger.info("[ArchiveRedisListener] 태스크 수신: task_id=%s", task_id)

            self._current_task_count += 1
            await self._update_health("BUSY")

            # ArchiveAgent 위임
            result = await self._agent.handle_dispatch(dispatch_msg)
            agent_result = {**result, "agent": _AGENT_NAME, "task_id": task_id}

        except json.JSONDecodeError as exc:
            logger.error("[ArchiveRedisListener] JSON 파싱 실패: %s", exc)
            agent_result.update({
                "error": {"code": "PARSE_ERROR", "message": str(exc), "traceback": None},
            })
        except asyncio.CancelledError:
            logger.warning("[ArchiveRedisListener] 태스크 취소됨: task_id=%s", task_id)
            agent_result.update({
                "error": {"code": "CANCELLED", "message": "태스크가 취소되었습니다.", "traceback": None},
            })
            raise
        except Exception as exc:
            logger.error("[ArchiveRedisListener] 태스크 처리 실패 task_id=%s: %s", task_id, exc)
            agent_result.update({
                "error": {"code": "INTERNAL_ERROR", "message": str(exc), "traceback": None},
            })
        finally:
            self._current_task_count = max(0, self._current_task_count - 1)
            if self._current_task_count == 0:
                await self._update_health("IDLE")
            try:
                await self._report_result(
                    task_id=agent_result.get("task_id", task_id),
                    agent=agent_result.get("agent", _AGENT_NAME),
                    result_data=agent_result.get("result_data", {}),
                    status=agent_result.get("status", "FAILED"),
                    error=agent_result.get("error"),
                    reference_id=agent_result.get("result_data", {}).get("reference_id"),
                    payload_summary=agent_result.get("result_data", {}).get("payload_summary"),
                )
            except Exception as exc:
                logger.error("[ArchiveRedisListener] 결과 보고 실패 task_id=%s: %s", task_id, exc)

    # ── 결과 보고 ──────────────────────────────────────────────────────────────

    async def _report_result(
        self,
        task_id: str,
        agent: str,
        result_data: dict[str, Any],
        status: str,
        error: dict[str, Any] | None,
        reference_id: str | None = None,
        payload_summary: str | None = None,
    ) -> None:
        """
        처리 결과를 OrchestraManager POST /results 엔드포인트로 전송합니다.
        네트워크 오류 시 최대 3회 재시도 (1s, 2s, 4s 백오프).
        """
        payload = {
            "task_id": task_id,
            "agent": agent,
            "status": status,
            "result_data": result_data,
            "reference_id": reference_id,
            "payload_summary": payload_summary,
            "error": error,
            "usage_stats": {},
        }
        url = f"{self._orchestra_url}/results"

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=_HTTP_REPORT_TIMEOUT) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                logger.info(
                    "[ArchiveRedisListener] 결과 보고 완료: task_id=%s status=%s",
                    task_id, status,
                )
                return
            except Exception as exc:
                wait = 2 ** attempt
                logger.warning(
                    "[ArchiveRedisListener] 결과 보고 실패 (attempt %d/3): %s — %ds 후 재시도",
                    attempt + 1, exc, wait,
                )
                if attempt < 2:
                    await asyncio.sleep(wait)

        logger.error("[ArchiveRedisListener] 결과 보고 최종 실패: task_id=%s", task_id)
        try:
            redis = await self._ensure_redis()
            dlq_entry = {**payload, "failed_at": datetime.now(timezone.utc).isoformat(), "reason": "http_report_failed"}
            await redis.rpush(_DLQ_KEY, json.dumps(dlq_entry, ensure_ascii=False))
            logger.warning("[ArchiveRedisListener] 결과 DLQ 저장: task_id=%s", task_id)
        except Exception as dlq_exc:
            logger.error("[ArchiveRedisListener] DLQ 저장 실패: %s", dlq_exc)

    # ── Heartbeat ──────────────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """
        15초 주기로 agent:archive_agent:health Redis Hash를 갱신합니다.
        OrchestraManager HealthMonitor가 이 키를 읽어 가용 여부를 판단합니다.
        CancelledError를 수신하면 정상 종료합니다.
        """
        logger.info("[ArchiveRedisListener] heartbeat 시작")
        try:
            while True:
                await self._update_health(
                    "BUSY" if self._current_task_count > 0 else "IDLE"
                )
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            logger.info("[ArchiveRedisListener] heartbeat 정상 종료")

    # NLU가 이 에이전트를 이해하는 데 사용하는 설명입니다.
    # 새 action 추가 시 이 문자열만 업데이트하면 오케스트라는 자동으로 인식합니다.
    _NLU_DESCRIPTION = (
        "- archive_agent: Notion/Obsidian 자료 조회 및 저장 (Archive Hub)\n"
        "  - actions:\n"
        "    - list_databases: 연결된 모든 노션 데이터베이스 목록 조회\n"
        "    - get_database_schema: 특정 데이터베이스의 컬럼 구조 및 타입 파악 (params: database_id)\n"
        "    - query_database: 데이터베이스 항목 목록 조회 (params: database_id[선택])\n"
        "    - get_page: 특정 페이지 상세 내용 조회 (params: page_id[필수])\n"
        "    - create_page: 노션에 새 페이지 생성 또는 저장 (params: title[필수], database_id[선택], content[선택])"
        " - \"저장해줘\", \"기록해줘\", \"노션에 써줘\" 요청에 사용\n"
        "    - search: 노션/옵시디언 전체 검색 (params: query)\n"
        "    - read_file: 옵시디언 파일 내용 읽기 (params: page_id)\n"
        "    - write_file: 옵시디언 파일 생성/수정 (params: title[필수], content[선택])\n"
        "    - append_file: 옵시디언 파일에 내용 추가 (params: title[필수], content[필수])\n"
        "    - list_files: 옵시디언 볼트 파일 목록 검색 (params: query[선택])"
    )

    async def _update_health(self, status: str) -> None:
        """agent:archive_agent:health Hash 필드를 업데이트합니다."""
        try:
            redis = await self._ensure_redis()
            await redis.hset(
                _HEALTH_KEY,
                mapping={
                    "agent_id": _AGENT_NAME,
                    "status": status,
                    "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                    "version": "2.0.0",
                    "capabilities": "archive_notion,archive_obsidian,analyze_content",
                    "nlu_description": self._NLU_DESCRIPTION,
                    "current_tasks": str(self._current_task_count),
                    "max_concurrency": "3",
                },
            )
            await redis.expire(_HEALTH_KEY, _HEALTH_TTL)
        except Exception as exc:
            logger.warning("[ArchiveRedisListener] heartbeat 업데이트 실패: %s", exc)
