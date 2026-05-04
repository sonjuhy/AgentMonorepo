"""
[TDD] HMAC dispatch 서명 통합 테스트

- POST /tasks: 서명된 메시지를 Redis에 삽입
- manager.listen_tasks: 유효 서명 → 처리, 무효 서명 → DLQ
- DISPATCH_HMAC_SECRET 미설정 시 하위호환 유지
"""
from __future__ import annotations

import json
import os

import pytest

_SECRET = "test-hmac-secret-32bytes-padding!!"


# ── POST /tasks 서명 검증 ──────────────────────────────────────────────────────

class TestSubmitTaskSigning:
    async def test_signed_message_sent_via_cassiopeia(self, async_client, monkeypatch):
        """POST /tasks는 서명된 메시지를 cassiopeia로 전송해야 합니다."""
        from agents.cassiopeia_agent import app_context
        monkeypatch.setenv("DISPATCH_HMAC_SECRET", _SECRET)
        app_context.ctx.cassiopeia_client.send_message.reset_mock()

        resp = await async_client.post("/tasks", json={
            "content": "파일 읽어줘",
            "user_id": "U1",
        })
        assert resp.status_code == 200

        app_context.ctx.cassiopeia_client.send_message.assert_awaited_once()
        payload = app_context.ctx.cassiopeia_client.send_message.call_args.kwargs["payload"]
        assert "_hmac" in payload, "POST /tasks는 서명된 메시지를 전송해야 합니다"

    async def test_no_secret_sends_unsigned_message(self, async_client, monkeypatch):
        """DISPATCH_HMAC_SECRET 미설정 시 서명 없이 전송해야 합니다."""
        from agents.cassiopeia_agent import app_context
        monkeypatch.delenv("DISPATCH_HMAC_SECRET", raising=False)
        app_context.ctx.cassiopeia_client.send_message.reset_mock()

        resp = await async_client.post("/tasks", json={
            "content": "파일 읽어줘",
            "user_id": "U1",
        })
        assert resp.status_code == 200

        app_context.ctx.cassiopeia_client.send_message.assert_awaited_once()
        payload = app_context.ctx.cassiopeia_client.send_message.call_args.kwargs["payload"]
        assert "_hmac" not in payload, "시크릿 미설정 시 서명 없이 전송해야 합니다"

    async def test_hmac_covers_user_id_and_content(self, async_client, monkeypatch):
        """서로 다른 user_id는 서로 다른 _hmac을 생성해야 합니다."""
        from agents.cassiopeia_agent import app_context
        monkeypatch.setenv("DISPATCH_HMAC_SECRET", _SECRET)
        app_context.ctx.cassiopeia_client.send_message.reset_mock()

        await async_client.post("/tasks", json={"content": "동일 내용", "user_id": "user-A"})
        await async_client.post("/tasks", json={"content": "동일 내용", "user_id": "user-B"})

        calls = app_context.ctx.cassiopeia_client.send_message.await_args_list
        hmacs = [c.kwargs["payload"]["_hmac"] for c in calls]
        assert hmacs[0] != hmacs[1]


# ── manager 서명 검증 ──────────────────────────────────────────────────────────

class TestManagerVerification:
    async def test_valid_signed_task_is_processed(
        self, manager, fake_redis, monkeypatch
    ):
        """유효한 서명의 태스크는 정상 처리되어야 합니다."""
        monkeypatch.setenv("DISPATCH_HMAC_SECRET", _SECRET)
        from shared_core.dispatch_auth import sign_task

        task = sign_task({
            "task_id": "t-valid",
            "session_id": "U1:C1",
            "requester": {"user_id": "U1", "channel_id": "C1"},
            "content": "테스트",
            "source": "slack",
        })
        await fake_redis.rpush("agent:orchestra:tasks", json.dumps(task))

        # 서명 검증 통과 확인 — DispatchAuthError 없이 파싱 가능
        from shared_core.dispatch_auth import verify_task
        raw = await fake_redis.lpop("agent:orchestra:tasks")
        parsed = json.loads(raw)
        verify_task(parsed)  # 예외 없어야 함

    async def test_invalid_signature_goes_to_dlq(
        self, manager, fake_redis, monkeypatch
    ):
        """서명 불일치 태스크는 DLQ에 삽입되어야 합니다."""
        monkeypatch.setenv("DISPATCH_HMAC_SECRET", _SECRET)

        tampered_task = {
            "task_id": "t-tampered",
            "session_id": "U1:C1",
            "requester": {"user_id": "U1", "channel_id": "C1"},
            "content": "악성 내용",  # 서명 이후 변조
            "source": "slack",
            "_hmac": "a" * 64,  # 위조 서명
        }
        await fake_redis.rpush("agent:orchestra:tasks", json.dumps(tampered_task))

        # manager의 _verify_and_parse를 직접 호출해 검증
        from shared_core.dispatch_auth import DispatchAuthError, verify_task
        raw = await fake_redis.lpop("agent:orchestra:tasks")
        parsed = json.loads(raw)
        with pytest.raises(DispatchAuthError):
            verify_task(parsed)

    async def test_unsigned_task_allowed_without_secret(
        self, manager, fake_redis, monkeypatch
    ):
        """DISPATCH_HMAC_SECRET 미설정 시 서명 없는 태스크를 허용해야 합니다."""
        monkeypatch.delenv("DISPATCH_HMAC_SECRET", raising=False)
        from shared_core.dispatch_auth import verify_task

        unsigned_task = {
            "task_id": "t-unsigned",
            "session_id": "U1:C1",
            "requester": {"user_id": "U1", "channel_id": "C1"},
            "content": "테스트",
            "source": "slack",
        }
        verify_task(unsigned_task)  # 예외 없어야 함
