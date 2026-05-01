"""
UnifiedArchiveAgent의 에이전트별/per-call LLM 설정 테스트

- 기본적으로 에이전트 전용 환경변수(ARCHIVE_AGENT_LLM_BACKEND)를 사용
- dispatch 메시지에 llm_config가 있으면 그것을 우선 적용
- dispatch에 llm_config가 없으면 에이전트 기본 설정 사용
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock, call

from shared_core.llm.interfaces import LLMUsage
from shared_core.llm.llm_config import LLMConfig


def _make_llm_mock(response: str = '{"target": "notion", "action": "search", "query": "test", "reasoning": "test"}') -> AsyncMock:
    provider = AsyncMock()
    provider.generate_response.return_value = (
        response,
        LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
    )
    return provider


@pytest.fixture
def base_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake_key")
    monkeypatch.setenv("NOTION_TOKEN", "fake_notion")
    monkeypatch.setenv("NOTION_DATABASE_ID", "fake_db")


# ── 에이전트별 기본 LLM 설정 ──────────────────────────────────────────────────

class TestAgentDefaultLLMConfig:
    def test_agent_uses_archive_agent_llm_backend_env(self, base_env, monkeypatch):
        """ARCHIVE_AGENT_LLM_BACKEND 환경변수로 에이전트 기본 LLM 백엔드를 설정할 수 있다."""
        monkeypatch.setenv("ARCHIVE_AGENT_LLM_BACKEND", "claude")
        monkeypatch.setenv("LLM_BACKEND", "gemini")

        mock_llm = _make_llm_mock()
        captured_configs = []

        def fake_build_from_config(cfg: LLMConfig):
            captured_configs.append(cfg)
            return mock_llm

        with (
            patch("agents.archive_agent.unified_agent.build_llm_provider_from_config", side_effect=fake_build_from_config),
            patch("agents.archive_agent.unified_agent.load_llm_config_for_agent", wraps=__import__("shared_core.llm.llm_config", fromlist=["load_llm_config_for_agent"]).load_llm_config_for_agent),
        ):
            from agents.archive_agent.unified_agent import UnifiedArchiveAgent
            agent = UnifiedArchiveAgent()

        assert any(cfg.backend == "claude" for cfg in captured_configs)

    def test_agent_default_config_stored_as_attribute(self, base_env, monkeypatch):
        """UnifiedArchiveAgent은 초기화 시 _llm_config 속성을 갖는다."""
        mock_llm = _make_llm_mock()

        with patch("agents.archive_agent.unified_agent.build_llm_provider_from_config", return_value=mock_llm):
            from agents.archive_agent.unified_agent import UnifiedArchiveAgent
            agent = UnifiedArchiveAgent()

        assert hasattr(agent, "_llm_config")
        assert isinstance(agent._llm_config, LLMConfig)


# ── per-call LLM 설정 (dispatch 메시지) ──────────────────────────────────────

class TestPerCallLLMConfig:
    @pytest.mark.asyncio
    async def test_dispatch_llm_config_overrides_default(self, base_env, monkeypatch):
        """dispatch에 llm_config가 있으면 에이전트 기본값 대신 해당 설정을 사용한다."""
        per_call_llm = _make_llm_mock()
        call_log: list[LLMConfig] = []

        def fake_build(cfg: LLMConfig):
            call_log.append(cfg)
            return per_call_llm

        dispatch = {
            "task_id": "t1",
            "content": "찾아줘",
            "params": {},
            "llm_config": {"backend": "claude", "model": "claude-haiku-4-5-20251001"},
        }

        with patch("agents.archive_agent.unified_agent.build_llm_provider_from_config", side_effect=fake_build):
            from agents.archive_agent.unified_agent import UnifiedArchiveAgent
            agent = UnifiedArchiveAgent()
            agent.notion_agent.handle_dispatch = AsyncMock(return_value={"status": "notion_success"})
            agent.obsidian_agent.handle_dispatch = AsyncMock(return_value={"status": "obsidian_success"})
            await agent.handle_dispatch(dispatch)

        per_call_configs = [cfg for cfg in call_log if cfg.backend == "claude"]
        assert len(per_call_configs) >= 1
        assert per_call_configs[0].model == "claude-haiku-4-5-20251001"

    @pytest.mark.asyncio
    async def test_dispatch_without_llm_config_uses_agent_default(self, base_env, monkeypatch):
        """dispatch에 llm_config가 없으면 에이전트 기본 설정을 사용한다."""
        monkeypatch.setenv("ARCHIVE_AGENT_LLM_BACKEND", "gemini")
        mock_llm = _make_llm_mock()

        with patch("agents.archive_agent.unified_agent.build_llm_provider_from_config", return_value=mock_llm):
            from agents.archive_agent.unified_agent import UnifiedArchiveAgent
            agent = UnifiedArchiveAgent()
            agent.notion_agent.handle_dispatch = AsyncMock(return_value={"status": "notion_success"})
            agent.obsidian_agent.handle_dispatch = AsyncMock(return_value={"status": "obsidian_success"})

        dispatch = {
            "task_id": "t2",
            "content": "노션에서 찾아줘",
            "params": {"source": "notion"},
        }
        await agent.handle_dispatch(dispatch)

        assert agent._llm_config.backend == "gemini"

    @pytest.mark.asyncio
    async def test_explicit_source_routing_does_not_call_llm(self, base_env, monkeypatch):
        """params에 source가 명시된 경우 LLM이 호출되지 않아야 한다 (기존 동작 보존)."""
        mock_llm = _make_llm_mock()

        with patch("agents.archive_agent.unified_agent.build_llm_provider_from_config", return_value=mock_llm):
            from agents.archive_agent.unified_agent import UnifiedArchiveAgent
            agent = UnifiedArchiveAgent()
            agent.notion_agent.handle_dispatch = AsyncMock(return_value={"status": "notion_success"})
            agent.obsidian_agent.handle_dispatch = AsyncMock(return_value={"status": "obsidian_success"})

        dispatch = {"content": "찾아줘", "params": {"source": "notion"}}
        await agent.handle_dispatch(dispatch)

        mock_llm.generate_response.assert_not_called()
