"""
OllamaManager 테스트  (shared_core/llm/ollama_manager.py)
- is_ready(): 200 OK / 서버 다운 / non-200
- wait_until_ready(): 첫 시도 성공 / 재시도 후 성공 / 타임아웃
- list_models(): 정상 파싱 / 서버 에러 → 빈 리스트
- has_model(): 정확 일치 / prefix 일치 / 없음
- ensure_model(): 이미 있음 → pull 미호출 / 없으면 pull 호출
- pull_model(): 성공(스트림) / 서버 에러 / RuntimeError 전파
- delete_model(): 200 / 404도 성공 / 에러 → False
- get_version(): 반환 / 연결 실패 → None
"""
from __future__ import annotations

import json
import pytest
import httpx
from pytest_httpx import HTTPXMock
from unittest.mock import AsyncMock, patch

from shared_core.llm.ollama_manager import OllamaManager

_BASE = "http://localhost:11434"


@pytest.fixture
def mgr():
    return OllamaManager(base_url=_BASE)


# ── is_ready ──────────────────────────────────────────────────────────────────

class TestIsReady:
    async def test_true_when_200(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{_BASE}/api/tags", method="GET",
            json={"models": []}, status_code=200,
        )
        assert await mgr.is_ready() is True

    async def test_false_when_non_200(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{_BASE}/api/tags", method="GET", status_code=503,
        )
        assert await mgr.is_ready() is False

    async def test_false_when_connection_refused(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url=f"{_BASE}/api/tags",
        )
        assert await mgr.is_ready() is False

    async def test_false_when_timeout(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(
            httpx.TimeoutException("timed out"),
            url=f"{_BASE}/api/tags",
        )
        assert await mgr.is_ready() is False


# ── wait_until_ready ──────────────────────────────────────────────────────────

class TestWaitUntilReady:
    async def test_returns_true_on_first_success(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{_BASE}/api/tags", json={"models": []}, status_code=200,
        )
        assert await mgr.wait_until_ready(timeout=5, interval=0.01) is True

    async def test_retries_and_succeeds(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(url=f"{_BASE}/api/tags", status_code=503)
        httpx_mock.add_response(url=f"{_BASE}/api/tags", json={"models": []})
        assert await mgr.wait_until_ready(timeout=1, interval=0.01) is True

    async def test_returns_false_on_timeout(self, mgr, monkeypatch):
        # is_ready를 직접 패치해 빠르게 타임아웃 재현
        monkeypatch.setattr(mgr, "is_ready", AsyncMock(return_value=False))
        assert await mgr.wait_until_ready(timeout=0.05, interval=0.02) is False


# ── list_models ───────────────────────────────────────────────────────────────

class TestListModels:
    async def test_returns_model_names(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{_BASE}/api/tags",
            json={"models": [{"name": "qwen2.5:7b"}, {"name": "llama3.2:latest"}]},
        )
        models = await mgr.list_models()
        assert "qwen2.5:7b" in models
        assert "llama3.2:latest" in models

    async def test_empty_when_no_models(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(url=f"{_BASE}/api/tags", json={"models": []})
        assert await mgr.list_models() == []

    async def test_empty_list_on_server_error(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(
            httpx.ConnectError("down"), url=f"{_BASE}/api/tags",
        )
        assert await mgr.list_models() == []


# ── has_model ─────────────────────────────────────────────────────────────────

class TestHasModel:
    async def test_exact_match(self, mgr, monkeypatch):
        monkeypatch.setattr(mgr, "list_models", AsyncMock(return_value=["qwen2.5:7b"]))
        assert await mgr.has_model("qwen2.5:7b") is True

    async def test_prefix_match(self, mgr, monkeypatch):
        # "qwen2.5" → "qwen2.5:7b" 매칭
        monkeypatch.setattr(mgr, "list_models", AsyncMock(return_value=["qwen2.5:7b"]))
        assert await mgr.has_model("qwen2.5") is True

    async def test_not_found(self, mgr, monkeypatch):
        monkeypatch.setattr(mgr, "list_models", AsyncMock(return_value=["llama3.2:latest"]))
        assert await mgr.has_model("qwen2.5") is False

    async def test_empty_list(self, mgr, monkeypatch):
        monkeypatch.setattr(mgr, "list_models", AsyncMock(return_value=[]))
        assert await mgr.has_model("any-model") is False


# ── ensure_model ──────────────────────────────────────────────────────────────

class TestEnsureModel:
    async def test_skips_pull_if_model_exists(self, mgr, monkeypatch):
        monkeypatch.setattr(mgr, "has_model", AsyncMock(return_value=True))
        mock_pull = AsyncMock()
        monkeypatch.setattr(mgr, "pull_model", mock_pull)
        await mgr.ensure_model("qwen2.5:7b")
        mock_pull.assert_not_awaited()

    async def test_pulls_if_model_missing(self, mgr, monkeypatch):
        monkeypatch.setattr(mgr, "has_model", AsyncMock(return_value=False))
        mock_pull = AsyncMock()
        monkeypatch.setattr(mgr, "pull_model", mock_pull)
        await mgr.ensure_model("qwen2.5:7b", pull_timeout=30)
        mock_pull.assert_awaited_once_with("qwen2.5:7b", timeout=30)


# ── pull_model ────────────────────────────────────────────────────────────────

class TestPullModel:
    def _stream_lines(self, *statuses: str) -> bytes:
        return b"".join(
            json.dumps({"status": s}).encode() + b"\n" for s in statuses
        )

    async def test_success(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{_BASE}/api/pull", method="POST",
            content=self._stream_lines("pulling manifest", "success"),
        )
        await mgr.pull_model("qwen2.5:7b")  # 예외 없이 완료

    async def test_error_in_stream_raises(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{_BASE}/api/pull", method="POST",
            content=json.dumps({"status": "error", "error": "model not found"}).encode() + b"\n",
        )
        with pytest.raises(RuntimeError, match="model not found"):
            await mgr.pull_model("nonexistent:model")

    async def test_http_error_raises(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{_BASE}/api/pull", method="POST", status_code=500,
        )
        with pytest.raises(Exception):
            await mgr.pull_model("qwen2.5:7b")

    async def test_stream_ends_without_success_but_model_present(self, mgr, httpx_mock: HTTPXMock, monkeypatch):
        # 스트림이 success 없이 끝나도 모델이 있으면 정상
        httpx_mock.add_response(
            url=f"{_BASE}/api/pull", method="POST",
            content=self._stream_lines("pulling manifest", "verifying"),
        )
        monkeypatch.setattr(mgr, "has_model", AsyncMock(return_value=True))
        await mgr.pull_model("qwen2.5:7b")  # 예외 없이 완료

    async def test_stream_ends_without_success_model_absent_raises(self, mgr, httpx_mock: HTTPXMock, monkeypatch):
        httpx_mock.add_response(
            url=f"{_BASE}/api/pull", method="POST",
            content=self._stream_lines("pulling manifest"),
        )
        monkeypatch.setattr(mgr, "has_model", AsyncMock(return_value=False))
        with pytest.raises(RuntimeError, match="pull 완료 후 모델 미확인"):
            await mgr.pull_model("qwen2.5:7b")


# ── delete_model ──────────────────────────────────────────────────────────────

class TestDeleteModel:
    async def test_returns_true_on_200(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{_BASE}/api/delete", method="DELETE", status_code=200,
        )
        assert await mgr.delete_model("qwen2.5:7b") is True

    async def test_returns_true_on_404(self, mgr, httpx_mock: HTTPXMock):
        # 이미 없는 모델 삭제도 성공으로 처리
        httpx_mock.add_response(
            url=f"{_BASE}/api/delete", method="DELETE", status_code=404,
        )
        assert await mgr.delete_model("nonexistent") is True

    async def test_returns_false_on_error(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{_BASE}/api/delete", method="DELETE", status_code=500,
        )
        assert await mgr.delete_model("qwen2.5:7b") is False

    async def test_returns_false_on_connection_error(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(
            httpx.ConnectError("down"), url=f"{_BASE}/api/delete",
        )
        assert await mgr.delete_model("qwen2.5:7b") is False


# ── get_version ───────────────────────────────────────────────────────────────

class TestGetVersion:
    async def test_returns_version_string(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{_BASE}/api/version", method="GET",
            json={"version": "0.3.12"},
        )
        assert await mgr.get_version() == "0.3.12"

    async def test_returns_none_on_connection_error(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(
            httpx.ConnectError("down"), url=f"{_BASE}/api/version",
        )
        assert await mgr.get_version() is None

    async def test_returns_none_on_http_error(self, mgr, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{_BASE}/api/version", method="GET", status_code=404,
        )
        assert await mgr.get_version() is None
