import pytest
import os
import json
from unittest.mock import patch, MagicMock
from cryptography.fernet import Fernet

from agents.cassiopeia_agent.state_manager import StateManager

@pytest.mark.asyncio
class TestStateManagerEncryption:
    async def test_missing_encryption_key_raises_error(self, monkeypatch):
        # Ensure ENCRYPTION_KEY is NOT set
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        mock_redis = MagicMock()
        
        with pytest.raises(RuntimeError) as exc_info:
            StateManager(redis_client=mock_redis)
            
        assert "ENCRYPTION_KEY 환경변수가 설정되지 않았습니다" in str(exc_info.value)

    async def test_llm_keys_are_encrypted_in_db(self, monkeypatch):
        # Set up environment variables for the test
        monkeypatch.setenv("DATABASE_PATH", ":memory:")
        monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode('utf-8'))
        
        # We need a mock redis client because StateManager requires it for initialization
        mock_redis = MagicMock()
        
        state_manager = StateManager(redis_client=mock_redis)
        user_id = "test_enc_user"
        
        # Ensure user exists (init_session implicitly creates user profile)
        # Or we can just get_user_profile which will create it
        await state_manager.get_user_profile(user_id)
        
        # The key we want to store
        sensitive_keys = {"gemini": "sk-super-secret-gemini-key"}
        
        # Update the profile
        await state_manager.update_user_profile(user_id, {"llm_keys": sensitive_keys})
        
        # 1. Verify decryption works through the standard API
        profile = await state_manager.get_user_profile(user_id)
        assert "llm_keys" in profile
        assert profile["llm_keys"] == sensitive_keys
        
        # 2. Verify encryption at rest by checking the raw DB content
        db = await state_manager.ensure_db()
        async with db.execute("SELECT llm_keys FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            raw_db_value = row["llm_keys"]
            
        # The raw value should NOT be the plain JSON
        assert raw_db_value != json.dumps(sensitive_keys, ensure_ascii=False)
        assert "sk-super-secret-gemini-key" not in raw_db_value
        
        # It should likely start with "gAAAAA" (Fernet signature) if using cryptography
        # but let's just assert it's different and not plain text.
