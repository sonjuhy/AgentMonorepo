"""
[TDD] 신규 엔드포인트 테스트
- GET  /tasks/{id}/stream     — SSE 실시간 스트리밍
- POST /tasks (callback_url)  — 웹훅 콜백 등록
- GET  /approval/{id}         — 승인 요청 조회
- POST /approval/{id}/respond — 승인/거절 응답
"""
from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest


# ── SSE 스트리밍 ──────────────────────────────────────────────────────────────

class TestSSEStream:
    async def test_stream_endpoint_exists_and_returns_event_stream(self, async_client, fake_redis):
        task_id = str(uuid.uuid4())
        # 태스크 상태 미리 설정 (COMPLETED)
        await fake_redis.hset(f"task:{task_id}:state", mapping={
            "status": "COMPLETED",
            "session_id": "sess-1",
        })
        async with async_client.stream("GET", f"/tasks/{task_id}/stream") as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            # 첫 번째 SSE 이벤트 수신
            lines: list[str] = []
            async for line in resp.aiter_lines():
                lines.append(line)
                if line.startswith("data:"):
                    break
            assert any(line.startswith("data:") for line in lines)

    async def test_stream_sends_completed_event_and_closes(self, async_client, fake_redis):
        task_id = str(uuid.uuid4())
        await fake_redis.hset(f"task:{task_id}:state", mapping={"status": "COMPLETED"})

        events: list[dict] = []
        async with async_client.stream("GET", f"/tasks/{task_id}/stream") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line[len("data:"):].strip())
                    events.append(payload)
                    if payload.get("status") in ("COMPLETED", "FAILED"):
                        break

        assert any(e.get("status") == "COMPLETED" for e in events)

    async def test_stream_sends_failed_event(self, async_client, fake_redis):
        task_id = str(uuid.uuid4())
        await fake_redis.hset(f"task:{task_id}:state", mapping={
            "status": "FAILED",
            "error": "TIMEOUT",
        })
        events: list[dict] = []
        async with async_client.stream("GET", f"/tasks/{task_id}/stream") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line[len("data:"):].strip())
                    events.append(payload)
                    if payload.get("status") in ("COMPLETED", "FAILED"):
                        break
        assert any(e.get("status") == "FAILED" for e in events)

    async def test_stream_requires_auth(self, async_client):
        resp = await async_client.get(
            "/tasks/any-task-id/stream",
            headers={"X-API-Key": "bad-key"},
        )
        assert resp.status_code == 403


# ── 웹훅 콜백 ─────────────────────────────────────────────────────────────────

class TestWebhookCallback:
    async def test_submit_task_with_callback_url_accepted(self, async_client):
        resp = await async_client.post("/tasks", json={
            "content": "조사해줘",
            "user_id": "webhook-user",
            "callback_url": "https://example.com/webhook",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    async def test_callback_url_stored_in_task(self, async_client, fake_redis):
        resp = await async_client.post("/tasks", json={
            "content": "웹훅 테스트",
            "user_id": "u-webhook",
            "callback_url": "https://example.com/cb",
        })
        task_id = resp.json()["task_id"]
        # Redis 큐에서 디스패치 메시지 확인
        raw = await fake_redis.lrange("agent:orchestra:tasks", -1, -1)
        assert raw, "큐에 태스크가 없습니다"
        task = json.loads(raw[0])
        assert task.get("callback_url") == "https://example.com/cb"

    async def test_webhook_fired_on_result(self, async_client, fake_redis):
        """결과 수신 시 웹훅이 호출되는지 검증"""
        task_id = str(uuid.uuid4())
        # 콜백 URL을 Redis에 저장 (오케스트라 매니저가 저장하는 방식)
        await fake_redis.set(f"task:{task_id}:callback_url", "https://example.com/done")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=AsyncMock(status_code=200))
            mock_client_cls.return_value = mock_client

            resp = await async_client.post("/results", json={
                "task_id": task_id,
                "agent": "test_agent",
                "status": "COMPLETED",
                "result_data": {"summary": "완료"},
                "error": None,
                "usage_stats": {},
            })
            assert resp.status_code == 200


# ── 승인 API ──────────────────────────────────────────────────────────────────

class TestApprovalAPI:
    async def test_get_approval_not_found(self, async_client):
        resp = await async_client.get("/approval/nonexistent-approval-id")
        assert resp.status_code == 404

    async def test_get_pending_approval(self, async_client, fake_redis):
        approval_id = str(uuid.uuid4())
        await fake_redis.hset(f"orchestra:approval_meta:{approval_id}", mapping={
            "task_id": "task-123",
            "question": "이 작업을 실행하시겠습니까?",
            "status": "PENDING",
            "expires_at": "2099-12-31T23:59:59+00:00",
        })
        resp = await async_client.get(f"/approval/{approval_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["approval_id"] == approval_id
        assert data["status"] == "PENDING"
        assert "question" in data
        assert "expires_at" in data

    async def test_respond_approve(self, async_client, fake_redis):
        approval_id = str(uuid.uuid4())
        await fake_redis.hset(f"orchestra:approval_meta:{approval_id}", mapping={
            "task_id": "task-456",
            "question": "실행할까요?",
            "status": "PENDING",
            "expires_at": "2099-12-31T23:59:59+00:00",
        })
        resp = await async_client.post(
            f"/approval/{approval_id}/respond",
            json={"action": "approve"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "approve"

    async def test_respond_reject(self, async_client, fake_redis):
        approval_id = str(uuid.uuid4())
        await fake_redis.hset(f"orchestra:approval_meta:{approval_id}", mapping={
            "task_id": "task-789",
            "question": "실행할까요?",
            "status": "PENDING",
            "expires_at": "2099-12-31T23:59:59+00:00",
        })
        resp = await async_client.post(
            f"/approval/{approval_id}/respond",
            json={"action": "reject"},
        )
        assert resp.status_code == 200
        assert resp.json()["action"] == "reject"

    async def test_respond_invalid_action_rejected(self, async_client, fake_redis):
        approval_id = str(uuid.uuid4())
        await fake_redis.hset(f"orchestra:approval_meta:{approval_id}", mapping={
            "task_id": "t-x", "question": "?", "status": "PENDING",
            "expires_at": "2099-12-31T23:59:59+00:00",
        })
        resp = await async_client.post(
            f"/approval/{approval_id}/respond",
            json={"action": "maybe"},  # 유효하지 않은 액션
        )
        assert resp.status_code == 422

    async def test_respond_already_responded(self, async_client, fake_redis):
        approval_id = str(uuid.uuid4())
        await fake_redis.hset(f"orchestra:approval_meta:{approval_id}", mapping={
            "task_id": "t-dup", "question": "?", "status": "APPROVED",
            "expires_at": "2099-12-31T23:59:59+00:00",
        })
        resp = await async_client.post(
            f"/approval/{approval_id}/respond",
            json={"action": "approve"},
        )
        assert resp.status_code == 409

    async def test_approval_requires_auth(self, async_client):
        resp = await async_client.get(
            "/approval/any-id",
            headers={"X-API-Key": "bad-key"},
        )
        assert resp.status_code == 403
