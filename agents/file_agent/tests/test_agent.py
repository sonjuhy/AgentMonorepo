"""
[TDD] agents/file_agent/agent.py — cassiopeia-sdk 통신 단위 테스트

변경 사항:
- BLPOP(Redis Lists) 대신 CassiopeiaClient.listen() (Pub/Sub) 으로 메시지 수신
- _handle_task: raw JSON 문자열 → cassiopeia AgentMessage 객체 수신
- run(): aioredis.blpop 루프 제거, CassiopeiaClient 기반 루프 사용
"""
from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch, call

from cassiopeia_sdk.client import AgentMessage as SdkAgentMessage

from agents.file_agent.agent import FileAgent
from agents.file_agent.config import FileAgentConfig


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_allowed_root(tmp_path):
    return tmp_path


@pytest.fixture
def agent_config(tmp_allowed_root):
    return FileAgentConfig(
        allowed_roots=[tmp_allowed_root],
        max_file_size_mb=10,
    )


@pytest.fixture
def agent(agent_config):
    return FileAgent(config=agent_config)


def _make_sdk_message(action: str, task_id: str = "t-001", params: dict | None = None) -> SdkAgentMessage:
    return SdkAgentMessage(
        sender="orchestra",
        receiver="file-agent",
        action=action,
        payload={"task_id": task_id, "params": params or {}},
    )


async def _listen_gen(*messages: SdkAgentMessage) -> AsyncIterator[SdkAgentMessage]:
    for msg in messages:
        yield msg


# ---------------------------------------------------------------------------
# _handle_task — cassiopeia AgentMessage 수신 처리
# ---------------------------------------------------------------------------

class TestHandleTask:
    async def test_handle_read_file_success(self, agent, tmp_allowed_root):
        test_file = tmp_allowed_root / "hello.txt"
        test_file.write_text("내용입니다", encoding="utf-8")

        msg = _make_sdk_message("read_file", params={"file_path": str(test_file)})
        report = AsyncMock()
        agent._report_result = report

        await agent._handle_task(msg, "http://orchestra:8001")

        report.assert_awaited_once()
        kwargs = report.await_args.kwargs
        assert kwargs["status"] == "COMPLETED"

    async def test_handle_write_file_success(self, agent, tmp_allowed_root):
        target = tmp_allowed_root / "output.txt"
        msg = _make_sdk_message("write_file", params={"file_path": str(target), "content": "테스트"})
        agent._report_result = AsyncMock()

        await agent._handle_task(msg, "http://orchestra:8001")

        assert target.exists()
        assert target.read_text(encoding="utf-8") == "테스트"

    async def test_handle_unknown_action_reports_failed(self, agent):
        msg = _make_sdk_message("unknown_action")
        report = AsyncMock()
        agent._report_result = report

        await agent._handle_task(msg, "http://orchestra:8001")

        kwargs = report.await_args.kwargs
        assert kwargs["status"] == "FAILED"

    async def test_handle_task_extracts_task_id_from_payload(self, agent, tmp_allowed_root):
        test_file = tmp_allowed_root / "x.txt"
        test_file.write_text("hi", encoding="utf-8")
        msg = _make_sdk_message("read_file", task_id="my-task-99", params={"file_path": str(test_file)})
        report = AsyncMock()
        agent._report_result = report

        await agent._handle_task(msg, "http://orchestra:8001")

        kwargs = report.await_args.kwargs
        assert kwargs["task_id"] == "my-task-99"

    async def test_handle_task_extracts_action_from_message(self, agent):
        msg = _make_sdk_message("unknown_xyz")
        agent._report_result = AsyncMock()

        await agent._handle_task(msg, "http://orchestra:8001")

        kwargs = agent._report_result.await_args.kwargs
        assert kwargs["status"] == "FAILED"

    async def test_handle_delete_file_success(self, agent, tmp_allowed_root):
        target = tmp_allowed_root / "del.txt"
        target.write_text("delete me", encoding="utf-8")
        msg = _make_sdk_message("delete_file", params={"file_path": str(target)})
        agent._report_result = AsyncMock()

        await agent._handle_task(msg, "http://orchestra:8001")

        assert not target.exists()
        kwargs = agent._report_result.await_args.kwargs
        assert kwargs["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# run() — CassiopeiaClient.listen() 사용 검증
# ---------------------------------------------------------------------------

class TestRun:
    async def test_run_uses_cassiopeia_client(self, agent, tmp_allowed_root):
        """run()이 aioredis.blpop 대신 CassiopeiaClient.listen()을 사용하는지 검증합니다."""
        test_file = tmp_allowed_root / "run_test.txt"
        test_file.write_text("data", encoding="utf-8")

        msg = _make_sdk_message("read_file", params={"file_path": str(test_file)})

        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.listen = MagicMock(return_value=_listen_gen(msg))

        with patch("agents.file_agent.agent.CassiopeiaClient", return_value=mock_client):
            with patch("agents.file_agent.agent.aioredis") as mock_aioredis:
                mock_redis = AsyncMock()
                mock_aioredis.from_url.return_value = mock_redis
                mock_redis.hset = AsyncMock()
                mock_redis.expire = AsyncMock()
                mock_redis.aclose = AsyncMock()

                agent._report_result = AsyncMock()

                await agent.run()

        mock_client.connect.assert_awaited_once()
        mock_client.listen.assert_called_once()

    async def test_run_creates_cassiopeia_client_with_agent_name(self, agent):
        """run()이 에이전트 이름으로 CassiopeiaClient를 생성하는지 검증합니다."""
        captured_args = {}

        async def fake_listen():
            return
            yield  # make it an async generator

        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.listen = MagicMock(return_value=fake_listen())

        def capture_client(agent_id, redis_url):
            captured_args["agent_id"] = agent_id
            captured_args["redis_url"] = redis_url
            return mock_client

        with patch("agents.file_agent.agent.CassiopeiaClient", side_effect=capture_client):
            with patch("agents.file_agent.agent.aioredis") as mock_aioredis:
                mock_redis = AsyncMock()
                mock_aioredis.from_url.return_value = mock_redis
                mock_redis.hset = AsyncMock()
                mock_redis.expire = AsyncMock()
                mock_redis.aclose = AsyncMock()

                agent._report_result = AsyncMock()
                await agent.run()

        assert captured_args["agent_id"] == agent.agent_name

    async def test_run_disconnects_client_on_finish(self, agent):
        """run() 종료 시 CassiopeiaClient.disconnect()를 호출하는지 검증합니다."""
        async def empty_listen():
            return
            yield

        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.listen = MagicMock(return_value=empty_listen())

        with patch("agents.file_agent.agent.CassiopeiaClient", return_value=mock_client):
            with patch("agents.file_agent.agent.aioredis") as mock_aioredis:
                mock_redis = AsyncMock()
                mock_aioredis.from_url.return_value = mock_redis
                mock_redis.hset = AsyncMock()
                mock_redis.expire = AsyncMock()
                mock_redis.aclose = AsyncMock()

                await agent.run()

        mock_client.disconnect.assert_awaited_once()


# ---------------------------------------------------------------------------
# _report_result — 기존 HTTP 보고 로직 유지 검증
# ---------------------------------------------------------------------------

class TestReportResult:
    async def test_report_result_posts_to_orchestra(self, agent):
        import httpx
        with patch("agents.file_agent.agent.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await agent._report_result(
                orchestra_url="http://orchestra:8001",
                task_id="t-001",
                status="COMPLETED",
                result_data={"summary": "ok"},
                error=None,
            )

        mock_http.post.assert_awaited_once()
        call_kwargs = mock_http.post.call_args
        assert "http://orchestra:8001/results" in call_kwargs[0]

    async def test_report_result_sends_to_dlq_after_max_retries(self, agent):
        with patch("agents.file_agent.agent.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(side_effect=Exception("connection refused"))
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_redis = AsyncMock()
            mock_redis.rpush = AsyncMock()

            with patch("asyncio.sleep", new_callable=AsyncMock):
                await agent._report_result(
                    orchestra_url="http://orchestra:8001",
                    task_id="failed-task",
                    status="FAILED",
                    result_data={},
                    error={"code": "ERR"},
                    redis=mock_redis,
                )

        mock_redis.rpush.assert_awaited_once()
        dlq_call = mock_redis.rpush.call_args
        assert "orchestra:dlq" in dlq_call[0]
