import pytest
from httpx import AsyncClient
from unittest.mock import patch, MagicMock, AsyncMock

@pytest.mark.asyncio
async def test_get_system_metrics(async_client: AsyncClient):
    client_headers = {"X-API-Key": "test-admin-key"}
    fake_memory_info = {
        "used_memory": 1024 * 1024,
        "used_memory_human": "1.00M",
        "maxmemory": 0,
    }
    fake_clients_info = {"connected_clients": 2}

    with patch("psutil.cpu_percent", return_value=42.8), \
         patch("psutil.virtual_memory") as mock_vm, \
         patch.object(async_client._transport.app.state if hasattr(async_client._transport, "app") else MagicMock(), "redis_client", create=True):

        mock_vm.return_value = MagicMock(percent=65.2, used=1024*1024*1024, total=2048*1024*1024)

        from agents.cassiopeia_agent import app_context
        original_info = app_context.ctx.redis_client.info
        app_context.ctx.redis_client.info = AsyncMock(side_effect=lambda section: {
            "memory": fake_memory_info,
            "clients": fake_clients_info,
        }.get(section, {}))

        try:
            response = await async_client.get("/admin/system/metrics", headers=client_headers)
            assert response.status_code == 200
            data = response.json()
            assert "redis" in data
            assert "agents" in data
            assert "queues" in data
            assert "logs" in data
        finally:
            app_context.ctx.redis_client.info = original_info

@pytest.mark.asyncio
async def test_get_agents(async_client: AsyncClient):
    client_headers = {"X-API-Key": "test-admin-key"}
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
    client_headers = {"X-API-Key": "test-admin-key"}
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
    client_headers = {"X-API-Key": "test-admin-key"}
    reg_response = await async_client.post("/admin/agents", json={
        "agent_name": "test_agent_1",
        "capabilities": ["do_something"],
        "lifecycle_type": "ephemeral",
        "nlu_description": ""
    }, headers=client_headers)
    assert reg_response.status_code == 201

    response = await async_client.put("/admin/agents/test_agent_1/permissions", json={
        "preset": "trusted"
    }, headers=client_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["agent_name"] == "test_agent_1"
