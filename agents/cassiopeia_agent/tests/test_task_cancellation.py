import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import HTTPException

from agents.cassiopeia_agent.main import app
from agents.cassiopeia_agent.app_context import ctx
from agents.cassiopeia_agent.auth import verify_client_key

async def mock_verify_client_key():
    return None

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_mocks():
    # Mock the manager's cancel_task method
    ctx.manager = AsyncMock()
    app.dependency_overrides[verify_client_key] = mock_verify_client_key
    yield
    app.dependency_overrides.clear()

def test_cancel_task_success():
    ctx.manager.cancel_task.return_value = True
    
    response = client.post("/tasks/test-task-id/cancel")
    assert response.status_code == 200
    assert response.json() == {"status": "CANCELLED", "task_id": "test-task-id"}
    ctx.manager.cancel_task.assert_called_once_with("test-task-id", "api-user")

def test_cancel_task_failure():
    ctx.manager.cancel_task.return_value = False
    
    response = client.post("/tasks/test-task-id-fail/cancel")
    assert response.status_code == 400
    assert "태스크를 취소할 수 없습니다" in response.json()["detail"]
    ctx.manager.cancel_task.assert_called_once_with("test-task-id-fail", "api-user")
