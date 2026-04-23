"""
ScheduledTaskRunner — Redis Sorted Set 기반 태스크 스케줄러

- orchestra:scheduled_tasks (Sorted Set): score = 실행 예정 Unix timestamp
- 주기적으로 due 태스크를 꺼내 agent:orchestra:tasks 큐에 push
- repeat_interval_secs > 0 이면 완료 후 다음 실행 시각으로 재등록
- 환경변수 SCHEDULE_POLL_INTERVAL(초)로 폴링 간격 조정 (기본 10초)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger("orchestra_agent.scheduler")

_SCHEDULED_TASKS_KEY = "orchestra:scheduled_tasks"
_ORCHESTRA_TASKS_KEY = "agent:orchestra:tasks"
_POLL_INTERVAL: int = int(os.environ.get("SCHEDULE_POLL_INTERVAL", "10"))


class ScheduledTaskRunner:
    """
    Redis Sorted Set을 백킹 스토어로 사용하는 태스크 스케줄러.

    사용 예시:
        runner = ScheduledTaskRunner(redis_client)

        # 30초 후 1회 실행
        await runner.schedule(task, run_at=time.time() + 30)

        # 매 1시간마다 반복 실행
        await runner.schedule(task, run_at=time.time(), repeat_interval_secs=3600)

        # 백그라운드 루프 시작 (asyncio.create_task 사용)
        asyncio.create_task(runner.run_loop())
    """

    def __init__(
        self,
        redis_client: aioredis.Redis | None = None,
        orchestra_queue_key: str = _ORCHESTRA_TASKS_KEY,
    ) -> None:
        if redis_client is not None:
            self._redis = redis_client
        else:
            redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
            self._redis = aioredis.from_url(redis_url, decode_responses=True, socket_timeout=5.0)
        self._queue_key = orchestra_queue_key

    async def schedule(
        self,
        task: dict[str, Any],
        run_at: float,
        repeat_interval_secs: int = 0,
    ) -> str:
        """
        태스크를 특정 시각에 실행되도록 등록합니다.

        Args:
            task: OrchestraTask 형식의 dict (task_id 없으면 자동 생성)
            run_at: 실행할 Unix timestamp (time.time() 기준)
            repeat_interval_secs: 0이면 1회 실행, 양수면 해당 초마다 반복

        Returns:
            schedule_id (취소/조회용)
        """
        if "task_id" not in task:
            task = {**task, "task_id": str(uuid.uuid4())}
        schedule_id = str(uuid.uuid4())
        entry = {
            "schedule_id": schedule_id,
            "task": task,
            "repeat_interval_secs": repeat_interval_secs,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.zadd(_SCHEDULED_TASKS_KEY, {json.dumps(entry, ensure_ascii=False): run_at})
        logger.info(
            "[Scheduler] 태스크 등록: schedule_id=%s run_at=%.0f repeat=%ds",
            schedule_id, run_at, repeat_interval_secs,
        )
        return schedule_id

    async def cancel(self, schedule_id: str) -> bool:
        """schedule_id로 등록된 태스크를 취소합니다."""
        all_raw: list[str] = await self._redis.zrange(_SCHEDULED_TASKS_KEY, 0, -1)
        for raw in all_raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if data.get("schedule_id") == schedule_id:
                removed = await self._redis.zrem(_SCHEDULED_TASKS_KEY, raw)
                if removed:
                    logger.info("[Scheduler] 태스크 취소: schedule_id=%s", schedule_id)
                    return True
        return False

    async def list_pending(self) -> list[dict[str, Any]]:
        """현재 등록된 모든 예약 태스크를 반환합니다."""
        items: list[tuple[str, float]] = await self._redis.zrange(
            _SCHEDULED_TASKS_KEY, 0, -1, withscores=True
        )
        result = []
        for raw, score in items:
            try:
                data = json.loads(raw)
                data["run_at"] = score
                data["run_at_iso"] = datetime.fromtimestamp(score, tz=timezone.utc).isoformat()
                result.append(data)
            except json.JSONDecodeError:
                continue
        return result

    async def run_loop(self) -> None:
        """due 태스크를 폴링하여 오케스트라 큐에 push하는 메인 루프."""
        logger.info("[Scheduler] 루프 시작 (poll=%ds)", _POLL_INTERVAL)
        while True:
            try:
                now = time.time()
                due: list[tuple[str, float]] = await self._redis.zrangebyscore(
                    _SCHEDULED_TASKS_KEY, "-inf", now, withscores=True
                )
                for raw, score in due:
                    await self._dispatch_due_task(raw, score)

                await asyncio.sleep(_POLL_INTERVAL)
            except asyncio.CancelledError:
                logger.info("[Scheduler] 루프 종료")
                break
            except Exception as exc:
                logger.error("[Scheduler] 루프 오류: %s", exc)
                await asyncio.sleep(5)

    async def _dispatch_due_task(self, raw: str, score: float) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("[Scheduler] JSON 파싱 실패, 항목 삭제: %s", exc)
            await self._redis.zrem(_SCHEDULED_TASKS_KEY, raw)
            return

        task: dict[str, Any] = data["task"]
        repeat: int = data.get("repeat_interval_secs", 0)
        schedule_id: str = data.get("schedule_id", "unknown")

        await self._redis.zrem(_SCHEDULED_TASKS_KEY, raw)

        task_to_push = {**task, "task_id": str(uuid.uuid4())}
        await self._redis.rpush(self._queue_key, json.dumps(task_to_push, ensure_ascii=False))
        logger.info("[Scheduler] 태스크 디스패치: schedule_id=%s task_id=%s", schedule_id, task_to_push["task_id"])

        if repeat > 0:
            next_run = score + repeat
            next_entry = {**data, "task": {**task, "task_id": str(uuid.uuid4())}}
            await self._redis.zadd(_SCHEDULED_TASKS_KEY, {json.dumps(next_entry, ensure_ascii=False): next_run})
            logger.info(
                "[Scheduler] 반복 재등록: schedule_id=%s next_run=%.0f",
                schedule_id, next_run,
            )
