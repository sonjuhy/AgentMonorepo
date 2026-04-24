"""
scheduler.py 테스트
- schedule(): 단일 / 반복 태스크 등록
- cancel(): 취소 성공 / 없는 ID
- list_pending(): 전체 조회
- _dispatch_due_task(): 큐 push / 반복 재등록
- run_loop(): due 태스크 처리 후 CancelledError 정상 종료
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from agents.orchestra_agent.scheduler import ScheduledTaskRunner

_QUEUE_KEY = "agent:orchestra:tasks"
_SCHEDULED_KEY = "orchestra:scheduled_tasks"


@pytest.fixture
def scheduler(fake_redis):
    return ScheduledTaskRunner(redis_client=fake_redis, orchestra_queue_key=_QUEUE_KEY)


# ── schedule ──────────────────────────────────────────────────────────────────

class TestSchedule:
    async def test_returns_schedule_id(self, scheduler):
        sid = await scheduler.schedule({"content": "test"}, run_at=time.time() + 60)
        assert isinstance(sid, str) and len(sid) == 36  # UUID

    async def test_single_task_stored_in_sorted_set(self, scheduler, fake_redis):
        run_at = time.time() + 60
        await scheduler.schedule({"content": "test"}, run_at=run_at)
        count = await fake_redis.zcard(_SCHEDULED_KEY)
        assert count == 1

    async def test_task_id_auto_generated(self, scheduler, fake_redis):
        await scheduler.schedule({"content": "no_id"}, run_at=time.time() + 60)
        items = await fake_redis.zrange(_SCHEDULED_KEY, 0, -1)
        data = json.loads(items[0])
        assert "task_id" in data["task"]

    async def test_task_id_preserved_if_given(self, scheduler, fake_redis):
        await scheduler.schedule({"task_id": "my-id-123", "content": "x"}, run_at=time.time() + 60)
        items = await fake_redis.zrange(_SCHEDULED_KEY, 0, -1)
        data = json.loads(items[0])
        assert data["task"]["task_id"] == "my-id-123"

    async def test_repeat_interval_stored(self, scheduler, fake_redis):
        await scheduler.schedule({"content": "repeat"}, run_at=time.time(), repeat_interval_secs=3600)
        items = await fake_redis.zrange(_SCHEDULED_KEY, 0, -1)
        data = json.loads(items[0])
        assert data["repeat_interval_secs"] == 3600

    async def test_multiple_tasks_stored(self, scheduler, fake_redis):
        for i in range(3):
            await scheduler.schedule({"content": f"task-{i}"}, run_at=time.time() + i * 10)
        assert await fake_redis.zcard(_SCHEDULED_KEY) == 3


# ── cancel ────────────────────────────────────────────────────────────────────

class TestCancel:
    async def test_cancel_existing_task(self, scheduler, fake_redis):
        sid = await scheduler.schedule({"content": "to_cancel"}, run_at=time.time() + 60)
        result = await scheduler.cancel(sid)
        assert result is True
        assert await fake_redis.zcard(_SCHEDULED_KEY) == 0

    async def test_cancel_nonexistent_returns_false(self, scheduler):
        result = await scheduler.cancel("non-existent-id")
        assert result is False

    async def test_cancel_only_removes_matching_task(self, scheduler, fake_redis):
        sid1 = await scheduler.schedule({"content": "task1"}, run_at=time.time() + 60)
        await scheduler.schedule({"content": "task2"}, run_at=time.time() + 120)
        await scheduler.cancel(sid1)
        assert await fake_redis.zcard(_SCHEDULED_KEY) == 1


# ── list_pending ──────────────────────────────────────────────────────────────

class TestListPending:
    async def test_empty_returns_empty_list(self, scheduler):
        result = await scheduler.list_pending()
        assert result == []

    async def test_returns_all_tasks(self, scheduler):
        for i in range(3):
            await scheduler.schedule({"content": f"t{i}"}, run_at=time.time() + i * 10)
        result = await scheduler.list_pending()
        assert len(result) == 3

    async def test_includes_run_at_and_iso(self, scheduler):
        run_at = time.time() + 100.0
        await scheduler.schedule({"content": "t"}, run_at=run_at)
        result = await scheduler.list_pending()
        assert abs(result[0]["run_at"] - run_at) < 1.0
        assert "run_at_iso" in result[0]


# ── _dispatch_due_task ────────────────────────────────────────────────────────

class TestDispatchDueTask:
    async def test_pushes_task_to_orchestra_queue(self, scheduler, fake_redis):
        entry = json.dumps({
            "schedule_id": "sid-1",
            "task": {"task_id": "t1", "content": "hello"},
            "repeat_interval_secs": 0,
        })
        await scheduler._dispatch_due_task(entry, time.time())
        length = await fake_redis.llen(_QUEUE_KEY)
        assert length == 1

    async def test_dispatched_task_has_new_task_id(self, scheduler, fake_redis):
        entry = json.dumps({
            "schedule_id": "sid-1",
            "task": {"task_id": "original-id", "content": "x"},
            "repeat_interval_secs": 0,
        })
        await scheduler._dispatch_due_task(entry, time.time())
        raw = await fake_redis.lpop(_QUEUE_KEY)
        pushed = json.loads(raw)
        assert pushed["task_id"] != "original-id"

    async def test_one_shot_not_rescheduled(self, scheduler, fake_redis):
        entry = json.dumps({
            "schedule_id": "sid-1",
            "task": {"task_id": "t1", "content": "x"},
            "repeat_interval_secs": 0,
        })
        await scheduler._dispatch_due_task(entry, time.time())
        assert await fake_redis.zcard(_SCHEDULED_KEY) == 0

    async def test_recurring_task_rescheduled(self, scheduler, fake_redis):
        score = time.time()
        entry = json.dumps({
            "schedule_id": "sid-1",
            "task": {"task_id": "t1", "content": "repeat"},
            "repeat_interval_secs": 3600,
        })
        await scheduler._dispatch_due_task(entry, score)
        assert await fake_redis.zcard(_SCHEDULED_KEY) == 1
        # 다음 실행 시각 = score + 3600
        items = await fake_redis.zrange(_SCHEDULED_KEY, 0, -1, withscores=True)
        _, next_score = items[0]
        assert abs(next_score - (score + 3600)) < 1.0

    async def test_invalid_json_removed_from_set(self, scheduler, fake_redis):
        bad_entry = "not-valid-json"
        await fake_redis.zadd(_SCHEDULED_KEY, {bad_entry: time.time()})
        await scheduler._dispatch_due_task(bad_entry, time.time())
        assert await fake_redis.zcard(_SCHEDULED_KEY) == 0


# ── run_loop ──────────────────────────────────────────────────────────────────

class TestRunLoop:
    async def test_dispatches_due_tasks_and_cancels(self, scheduler, fake_redis):
        # 현재 시각보다 과거인 태스크 등록
        await scheduler.schedule({"content": "due_task"}, run_at=time.time() - 1)

        async def _run_and_cancel():
            task = asyncio.create_task(scheduler.run_loop())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await _run_and_cancel()
        assert await fake_redis.llen(_QUEUE_KEY) == 1

    async def test_future_tasks_not_dispatched_early(self, scheduler, fake_redis):
        await scheduler.schedule({"content": "future"}, run_at=time.time() + 9999)

        async def _run_briefly():
            task = asyncio.create_task(scheduler.run_loop())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await _run_briefly()
        assert await fake_redis.llen(_QUEUE_KEY) == 0
