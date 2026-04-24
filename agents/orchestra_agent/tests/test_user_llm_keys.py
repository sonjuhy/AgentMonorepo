import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock

from agents.orchestra_agent.state_manager import StateManager
from agents.orchestra_agent.nlu_engine import GeminiNLUEngine
from shared_core.llm.interfaces import LLMUsage

import os

@pytest.mark.asyncio
class TestUserLLMKeys:
    async def test_state_manager_saves_and_retrieves_llm_keys(self, fake_redis, monkeypatch):
        monkeypatch.setenv("DATABASE_PATH", ":memory:")
        state = StateManager(redis_client=fake_redis)
        await state.init_session("sess1", "user1", "chan1")
        
        # Update user profile with LLM keys
        await state.update_user_profile("user1", {"llm_keys": {"gemini": "user1-gemini-key"}})
        
        # Retrieve user profile
        profile = await state.get_user_profile("user1")
        assert "llm_keys" in profile
        assert profile["llm_keys"].get("gemini") == "user1-gemini-key"

    @patch("agents.orchestra_agent.nlu_engine.build_llm_provider")
    async def test_nlu_engine_uses_user_llm_key_if_present(self, mock_build, fake_redis, monkeypatch):
        monkeypatch.setenv("DATABASE_PATH", ":memory:")
        monkeypatch.setenv("LLM_BACKEND", "gemini")
        
        # mock provider
        mock_provider = AsyncMock()
        mock_provider.generate_response.return_value = (
            json.dumps({"type": "direct_response", "intent": "chitchat", "params": {"answer": "Hello"}, "metadata": {"reason": "r", "confidence_score": 1.0, "requires_user_approval": False}}),
            LLMUsage(prompt_tokens=5, completion_tokens=10, total_tokens=15)
        )
        mock_build.return_value = mock_provider
        
        state = StateManager(redis_client=fake_redis)
        await state.init_session("sess1", "user1", "chan1")
        await state.update_user_profile("user1", {"llm_keys": {"gemini": "user1-secret-key"}})
        
        nlu = GeminiNLUEngine()
        await nlu.analyze(
            user_text="test",
            session_id="sess1",
            context=[],
            user_llm_keys={"gemini": "user1-secret-key"}
        )
        
        # Check if build_llm_provider was called with api_key="user1-secret-key"
        mock_build.assert_called_with(backend="gemini", api_key="user1-secret-key")

