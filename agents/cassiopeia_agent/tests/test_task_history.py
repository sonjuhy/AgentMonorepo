"""
[TDD] 작업 히스토리 API 테스트
- StateManager: save_task_history / update_task_history_status / get_user_task_history
- GET /users/{user_id}/tasks 엔드포인트
  - 내 작업만 반환
  - 페이지네이션
  - 상태 필터
  - 최신순 정렬
"""
from __future__ import annotations

import pytest


class TestTaskHistoryStateManager:
    async def test_save_and_retrieve_task(self, state_manager):
        await state_manager.save_task_history(
            task_id="t-001", user_id="u-1", content="파일 읽어줘"
        )
        tasks, total = await state_manager.get_user_task_history("u-1")
        assert total == 1
        assert tasks[0]["task_id"] == "t-001"
        assert tasks[0]["content"] == "파일 읽어줘"
        assert tasks[0]["status"] == "PENDING"

    async def test_update_status(self, state_manager):
        await state_manager.save_task_history("t-002", "u-1", "검색해줘")
        await state_manager.update_task_history_status("t-002", "COMPLETED")
        tasks, _ = await state_manager.get_user_task_history("u-1")
        completed = [t for t in tasks if t["task_id"] == "t-002"]
        assert completed[0]["status"] == "COMPLETED"

    async def test_user_isolation(self, state_manager):
        await state_manager.save_task_history("t-a1", "user-A", "A의 작업")
        await state_manager.save_task_history("t-b1", "user-B", "B의 작업")
        tasks_a, total_a = await state_manager.get_user_task_history("user-A")
        assert total_a == 1
        assert tasks_a[0]["task_id"] == "t-a1"

    async def test_pagination(self, state_manager):
        for i in range(5):
            await state_manager.save_task_history(f"t-p{i}", "u-page", f"작업 {i}")
        tasks, total = await state_manager.get_user_task_history("u-page", limit=2, offset=0)
        assert total == 5
        assert len(tasks) == 2

    async def test_latest_first_ordering(self, state_manager):
        await state_manager.save_task_history("t-old", "u-order", "오래된 작업")
        await state_manager.save_task_history("t-new", "u-order", "최근 작업")
        tasks, _ = await state_manager.get_user_task_history("u-order")
        assert tasks[0]["task_id"] == "t-new"

    async def test_status_filter(self, state_manager):
        await state_manager.save_task_history("t-done", "u-filter", "완료")
        await state_manager.save_task_history("t-fail", "u-filter", "실패")
        await state_manager.update_task_history_status("t-done", "COMPLETED")
        await state_manager.update_task_history_status("t-fail", "FAILED")

        tasks, total = await state_manager.get_user_task_history(
            "u-filter", status_filter="COMPLETED"
        )
        assert total == 1
        assert tasks[0]["task_id"] == "t-done"

    async def test_empty_history_returns_empty_list(self, state_manager):
        tasks, total = await state_manager.get_user_task_history("no-tasks-user")
        assert tasks == []
        assert total == 0


class TestTaskHistoryEndpoint:
    async def test_get_user_tasks_returns_200(self, async_client):
        resp = await async_client.get("/users/u-test/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert "tasks" in data
        assert "total" in data

    async def test_submit_task_creates_history_entry(self, async_client):
        resp = await async_client.post("/tasks", json={
            "content": "히스토리 테스트",
            "user_id": "hist-user-1",
        })
        assert resp.status_code == 200

        hist = await async_client.get("/users/hist-user-1/tasks")
        assert hist.status_code == 200
        data = hist.json()
        assert data["total"] >= 1
        task_ids = [t["task_id"] for t in data["tasks"]]
        assert resp.json()["task_id"] in task_ids

    async def test_pagination_params(self, async_client):
        resp = await async_client.get("/users/u-page/tasks?limit=5&offset=0")
        assert resp.status_code == 200

    async def test_status_filter_param(self, async_client):
        resp = await async_client.get("/users/u-filter/tasks?status=COMPLETED")
        assert resp.status_code == 200

    async def test_requires_auth(self, async_client):
        resp = await async_client.get(
            "/users/u-test/tasks",
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 403
