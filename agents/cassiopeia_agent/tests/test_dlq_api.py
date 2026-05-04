"""
[TDD] DLQ (Dead Letter Queue) 관리 API 테스트
- GET  /admin/dlq           — DLQ 항목 목록 + 페이지네이션
- POST /admin/dlq/replay    — 특정 항목 재처리 큐로 재삽입
- DELETE /admin/dlq         — DLQ 전체 비우기
"""
from __future__ import annotations

import json
import uuid

import pytest


async def _push_dlq(fake_redis, count: int = 3) -> list[dict]:
    entries = []
    for i in range(count):
        entry = {
            "id": str(uuid.uuid4()),
            "reason": "timeout",
            "task_id": f"task-{i}",
            "error": {"code": "TIMEOUT", "message": "시간 초과"},
            "ts": "2025-01-01T00:00:00+00:00",
        }
        await fake_redis.rpush("orchestra:dlq", json.dumps(entry, ensure_ascii=False))
        entries.append(entry)
    return entries


class TestDLQList:
    async def test_empty_dlq_returns_empty_list(self, async_client):
        resp = await async_client.get("/admin/dlq")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 0

    async def test_returns_dlq_entries(self, async_client, fake_redis):
        await _push_dlq(fake_redis, count=3)
        resp = await async_client.get("/admin/dlq")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

    async def test_pagination_limit(self, async_client, fake_redis):
        await _push_dlq(fake_redis, count=5)
        resp = await async_client.get("/admin/dlq?limit=2")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2

    async def test_items_have_required_fields(self, async_client, fake_redis):
        await _push_dlq(fake_redis, count=1)
        resp = await async_client.get("/admin/dlq")
        item = resp.json()["items"][0]
        assert "task_id" in item
        assert "reason" in item
        assert "ts" in item

    async def test_requires_admin_key(self, async_client):
        resp = await async_client.get(
            "/admin/dlq",
            headers={"X-API-Key": "test-client-key"},  # admin 아닌 client 키
        )
        assert resp.status_code == 403


class TestDLQReplay:
    async def test_replay_single_entry(self, async_client, fake_redis):
        entries = await _push_dlq(fake_redis, count=2)
        target_task_id = entries[0]["task_id"]
        resp = await async_client.post("/admin/dlq/replay", json={
            "task_id": target_task_id,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["replayed"] == 1

    async def test_replay_pushes_to_orchestra_queue(self, async_client, fake_redis):
        entries = await _push_dlq(fake_redis, count=1)
        task_id = entries[0]["task_id"]

        before_len = await fake_redis.llen("agent:orchestra:tasks")
        await async_client.post("/admin/dlq/replay", json={"task_id": task_id})
        after_len = await fake_redis.llen("agent:orchestra:tasks")

        assert after_len == before_len + 1

    async def test_replay_nonexistent_task_returns_404(self, async_client):
        resp = await async_client.post("/admin/dlq/replay", json={
            "task_id": "nonexistent-task-id",
        })
        assert resp.status_code == 404


class TestDLQClear:
    async def test_clear_empties_dlq(self, async_client, fake_redis):
        await _push_dlq(fake_redis, count=3)
        resp = await async_client.delete("/admin/dlq")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cleared"] == 3

        # 이후 DLQ가 비어있는지 확인
        check = await async_client.get("/admin/dlq")
        assert check.json()["total"] == 0

    async def test_clear_empty_dlq_returns_zero(self, async_client):
        resp = await async_client.delete("/admin/dlq")
        assert resp.status_code == 200
        assert resp.json()["cleared"] == 0
