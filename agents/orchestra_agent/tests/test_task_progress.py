import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from agents.orchestra_agent.main import app
from agents.orchestra_agent.app_context import ctx
from agents.orchestra_agent.auth import verify_client_key

async def mock_verify_client_key():
    return None

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_mocks():
    # Mock state_manager's methods used by get_task
    ctx.state_manager = AsyncMock()
    app.dependency_overrides[verify_client_key] = mock_verify_client_key
    yield
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_get_task_without_logs():
    ctx.state_manager.get_task_state.return_value = {"status": "PROCESSING", "session_id": "test-session"}
    
    response = client.get("/tasks/test-task-123")
    assert response.status_code == 200
    data = response.json()
    
    assert data["task_id"] == "test-task-123"
    assert data["status"] == "PROCESSING"
    assert "recent_logs" not in data
    
    ctx.state_manager.get_task_state.assert_called_once_with("test-task-123")
    ctx.state_manager.get_agent_logs.assert_not_called()

@pytest.mark.asyncio
async def test_get_task_with_logs():
    ctx.state_manager.get_task_state.return_value = {"status": "PROCESSING", "session_id": "test-session"}
    ctx.state_manager.get_agent_logs.return_value = [
        {"action": "test_action", "message": "Doing something...", "timestamp": "2024-01-01T00:00:00Z"}
    ]
    
    response = client.get("/tasks/test-task-456?include_logs=true")
    assert response.status_code == 200
    data = response.json()
    
    assert data["task_id"] == "test-task-456"
    assert data["status"] == "PROCESSING"
    assert "recent_logs" in data
    assert len(data["recent_logs"]) == 1
    assert data["recent_logs"][0]["action"] == "test_action"
    
    ctx.state_manager.get_task_state.assert_called_once_with("test-task-456")
    ctx.state_manager.get_agent_logs.assert_called_once_with(task_id="test-task-456", limit=5)

@pytest.mark.asyncio
async def test_get_task_not_found():
    ctx.state_manager.get_task_state.return_value = None
    
    response = client.get("/tasks/nonexistent-task")
    assert response.status_code == 200
    data = response.json()
    
    assert data["task_id"] == "nonexistent-task"
    assert data["status"] == "NOT_FOUND"
    
    ctx.state_manager.get_agent_logs.assert_not_called()
