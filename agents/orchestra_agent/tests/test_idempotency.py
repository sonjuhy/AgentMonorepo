"""
[TDD] Idempotency Key 테스트 (X-Idempotency-Key 헤더)
- 같은 키 재전송 → 캐시된 task_id 반환 (새 태스크 미생성)
- 다른 키 → 독립 태스크 생성
- TTL 경과 후 동일 키 → 새 태스크 생성
- 키 없으면 일반 처리
"""
from __future__ import annotations

import pytest


class TestIdempotencyStateManager:
    async def test_save_and_get_idempotency_result(self, state_manager):
        await state_manager.save_idempotency_result(
            "idem-key-1", {"task_id": "task-abc", "status": "accepted"}
        )
        result = await state_manager.get_idempotency_result("idem-key-1")
        assert result is not None
        assert result["task_id"] == "task-abc"

    async def test_missing_key_returns_none(self, state_manager):
        result = await state_manager.get_idempotency_result("nonexistent-key")
        assert result is None

    async def test_overwrite_same_key(self, state_manager):
        await state_manager.save_idempotency_result("key-x", {"task_id": "old"})
        await state_manager.save_idempotency_result("key-x", {"task_id": "new"})
        result = await state_manager.get_idempotency_result("key-x")
        assert result["task_id"] == "new"


class TestIdempotencyEndpoint:
    async def test_same_key_returns_cached_task_id(self, async_client):
        resp1 = await async_client.post(
            "/tasks",
            json={"content": "파일 읽어줘", "user_id": "u1"},
            headers={"X-Idempotency-Key": "unique-idem-key-001"},
        )
        assert resp1.status_code == 200
        task_id_1 = resp1.json()["task_id"]

        resp2 = await async_client.post(
            "/tasks",
            json={"content": "파일 읽어줘", "user_id": "u1"},
            headers={"X-Idempotency-Key": "unique-idem-key-001"},
        )
        assert resp2.status_code == 200
        task_id_2 = resp2.json()["task_id"]

        # 동일 Idempotency Key → 동일 task_id 반환
        assert task_id_1 == task_id_2

    async def test_different_keys_create_different_tasks(self, async_client):
        resp1 = await async_client.post(
            "/tasks",
            json={"content": "작업 A", "user_id": "u1"},
            headers={"X-Idempotency-Key": "key-A"},
        )
        resp2 = await async_client.post(
            "/tasks",
            json={"content": "작업 B", "user_id": "u1"},
            headers={"X-Idempotency-Key": "key-B"},
        )
        assert resp1.json()["task_id"] != resp2.json()["task_id"]

    async def test_no_key_creates_task_normally(self, async_client):
        resp = await async_client.post(
            "/tasks",
            json={"content": "일반 요청", "user_id": "u1"},
        )
        assert resp.status_code == 200
        assert "task_id" in resp.json()

    async def test_cached_response_has_idempotent_flag(self, async_client):
        await async_client.post(
            "/tasks",
            json={"content": "중복 테스트", "user_id": "u1"},
            headers={"X-Idempotency-Key": "flag-test-key"},
        )
        resp2 = await async_client.post(
            "/tasks",
            json={"content": "중복 테스트", "user_id": "u1"},
            headers={"X-Idempotency-Key": "flag-test-key"},
        )
        data = resp2.json()
        # 두 번째 응답은 idempotent 플래그 포함
        assert data.get("idempotent") is True
