import pytest
from httpx import AsyncClient
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_get_system_metrics(async_client: AsyncClient):
    client_headers = {"X-API-Key": "test-client-key"}
    # Mock psutil behavior
    with patch("psutil.cpu_percent", return_value=42.8), \
         patch("psutil.virtual_memory") as mock_vm:
        
        mock_vm.return_value = MagicMock(percent=65.2, used=1024*1024*1024, total=2048*1024*1024)
        
        response = await async_client.get("/admin/system/metrics", headers=client_headers)
        assert response.status_code == 200
        data = response.json()
        assert "cpu_usage_percent" in data
        assert "memory_usage_percent" in data

@pytest.mark.asyncio
async def test_get_agents(async_client: AsyncClient):
    client_headers = {"X-API-Key": "test-client-key"}
    # Need to register an agent first to see details
    reg_response = await async_client.post("/admin/agents", json={
        "agent_name": "test_agent_1",
        "capabilities": ["do_something"],
        "lifecycle_type": "ephemeral",
        "nlu_description": ""
    }, headers=client_headers)
    assert reg_response.status_code == 201

    response = await async_client.get("/admin/agents", headers=client_headers)
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
    assert "test_agent_1" in data["agents"]

@pytest.mark.asyncio
async def test_get_agent_specific_detail(async_client: AsyncClient):
    client_headers = {"X-API-Key": "test-client-key"}
    reg_response = await async_client.post("/admin/agents", json={
        "agent_name": "test_agent_1",
        "capabilities": ["do_something"],
        "lifecycle_type": "ephemeral",
        "nlu_description": ""
    }, headers=client_headers)
    assert reg_response.status_code == 201

    response = await async_client.get("/admin/agents/test_agent_1", headers=client_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["agent_name"] == "test_agent_1"

@pytest.mark.asyncio
async def test_put_agent_permissions(async_client: AsyncClient):
    client_headers = {"X-API-Key": "test-client-key"}
    reg_response = await async_client.post("/admin/agents", json={
        "agent_name": "test_agent_1",
        "capabilities": ["do_something"],
        "lifecycle_type": "ephemeral",
        "nlu_description": ""
    }, headers=client_headers)
    assert reg_response.status_code == 201

    response = await async_client.put("/admin/agents/test_agent_1/permissions", json={
        "preset": "strict"
    }, headers=client_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["agent_name"] == "test_agent_1"