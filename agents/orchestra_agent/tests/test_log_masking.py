import pytest
import json
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from agents.orchestra_agent.main import app
from agents.orchestra_agent.app_context import ctx
from agents.orchestra_agent.auth import verify_client_key

client = TestClient(app)

async def mock_verify_client_key():
    return None

@pytest.fixture(autouse=True)
def setup_mocks():
    ctx.state_manager = AsyncMock()
    app.dependency_overrides[verify_client_key] = mock_verify_client_key
    yield
    app.dependency_overrides.clear()

def test_log_masking_various_keys():
    test_cases = [
        # (original_message, expected_masked_message)
        ("Using OpenAI key sk-1234567890abcdef1234567890abcdef", "Using OpenAI key ***MASKED***"),
        ("Using Anthropic key sk-ant-api03-abcdefg1234567890-xyz", "Using Anthropic key ***MASKED***"),
        ("Using Gemini key AIzaSyD-1234567890abcdefghijklmnopqrst", "Using Gemini key ***MASKED***"),
        ("Using Github token ghp_1234567890abcdefghijklmnopqrstuvwxyz", "Using Github token ***MASKED***"),
        ("Header Authorization: Bearer abcdef1234567890", "Header Authorization: Bearer ***MASKED***"),
        ("No keys here just text", "No keys here just text"),
    ]

    for original, expected in test_cases:
        payload = {
            "agent_name": "test_agent",
            "action": "test_action",
            "message": original,
            "task_id": "test_task",
            "payload": {"details": original}
        }
        
        response = client.post("/logs", json=payload)
        assert response.status_code == 200
        
        # Check what was passed to add_agent_log
        call_args = ctx.state_manager.add_agent_log.call_args
        assert call_args is not None
        
        logged_message = call_args[0][2]
        logged_payload = call_args[0][5]
        
        assert logged_message == expected
        assert logged_payload["details"] == expected
