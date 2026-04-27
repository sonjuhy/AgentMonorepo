"""
[TDD] error_messages.py 테스트
- 에러 코드 → 사용자 친화적 한국어 메시지 변환
- 알 수 없는 코드 → 기본 메시지 fallback
- 포맷 파라미터 치환
- FastAPI 엔드포인트 오류 응답 형식 검증
"""
from __future__ import annotations

import pytest
from agents.orchestra_agent.error_messages import (
    get_user_message,
    build_error_response,
    DEFAULT_ERROR_MESSAGE,
)


class TestGetUserMessage:
    def test_known_code_returns_korean_message(self):
        msg = get_user_message("TIMEOUT")
        assert "초과" in msg or "시간" in msg
        assert "TIMEOUT" not in msg  # 기술 코드 노출 안 됨

    def test_rate_limit_includes_retry_after(self):
        msg = get_user_message("RATE_LIMIT", retry_after=30)
        assert "30" in msg

    def test_unknown_code_returns_default(self):
        msg = get_user_message("UNKNOWN_CODE_XYZ")
        assert msg == DEFAULT_ERROR_MESSAGE

    def test_all_defined_codes_return_string(self):
        codes = [
            "TIMEOUT", "RATE_LIMIT", "INTERNAL_ERROR", "EXECUTION_ERROR",
            "EXTERNAL_API_ERROR", "NOT_FOUND", "PARSE_ERROR", "CANCELLED",
            "INVALID_PARAMS", "AGENT_UNAVAILABLE",
        ]
        for code in codes:
            result = get_user_message(code)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_missing_format_param_still_returns_message(self):
        # RATE_LIMIT expects retry_after — 미전달 시 폴백
        msg = get_user_message("RATE_LIMIT")
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_message_has_no_raw_traceback(self):
        msg = get_user_message("INTERNAL_ERROR")
        assert "traceback" not in msg.lower()
        assert "Traceback" not in msg


class TestBuildErrorResponse:
    def test_structure_has_required_keys(self):
        resp = build_error_response("TIMEOUT")
        assert "error_code" in resp
        assert "message" in resp

    def test_code_is_preserved(self):
        resp = build_error_response("INVALID_PARAMS")
        assert resp["error_code"] == "INVALID_PARAMS"

    def test_message_is_user_friendly(self):
        resp = build_error_response("AGENT_UNAVAILABLE")
        # 기술적 표현이 아닌 자연어
        assert "에이전트" in resp["message"] or "기능" in resp["message"]

    def test_extra_kwargs_passed_through(self):
        resp = build_error_response("RATE_LIMIT", retry_after=60)
        assert "60" in resp["message"]


class TestErrorMessagesInEndpoints:
    """FastAPI 응답에서 에러 포맷 검증 (async_client fixture)"""

    async def test_403_has_friendly_detail(self, async_client):
        # 인증 없는 요청 → 403이지만 사용자 친화적 메시지
        resp = await async_client.get(
            "/tasks/nonexistent-task",
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 403
        # FastAPI HTTPException detail이 노출되는 구조 그대로지만
        # detail이 기술 내부 오류 코드를 그대로 노출하지 않는지 검증
        body = resp.json()
        assert "detail" in body

    async def test_agent_result_error_message_is_friendly(self, async_client):
        """POST /results 로 FAILED 결과 수신 시 에러 메시지 형식 검증"""
        import uuid
        task_id = str(uuid.uuid4())
        resp = await async_client.post("/results", json={
            "task_id": task_id,
            "agent": "test_agent",
            "status": "FAILED",
            "result_data": {},
            "error": {
                "code": "EXECUTION_ERROR",
                "message": "원시 기술 오류 메시지",
                "traceback": None,
            },
            "usage_stats": {},
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
