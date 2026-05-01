import asyncio
import json
import os
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from agents.archive_agent.obsidian.agent import ObsidianAgent

@pytest.fixture
def mock_env():
    with patch.dict(os.environ, {"OBSIDIAN_VAULT_PATH": "/tmp/vault", "ANTHROPIC_API_KEY": "test_key"}):
        yield

@pytest.mark.asyncio
async def test_obsidian_agent_storage_integration(mock_env):
    # Arrange
    mock_task_analyzer = AsyncMock()
    mock_task_analyzer.analyze_task.return_value = '{"action": "search", "query": "test"}'
    
    agent = ObsidianAgent()
    agent.task_analyzer = mock_task_analyzer
    agent._storage = AsyncMock()
    agent._storage.save_data.return_value = "ref_obsidian_123"
    agent.logger = AsyncMock()
    
    # Mock Obsidian vault list files
    agent.list_files = AsyncMock(return_value=["file1.md", "file2.md"])
    
    dispatch_msg = {
        "task_id": "test_obsidian_task",
        "content": "find test files",
        "params": {
            "action": "search",
            "query": "test"
        }
    }
    
    # Act
    result = await agent.handle_dispatch(dispatch_msg)
    
    # Assert
    assert result["status"] == "COMPLETED"
    assert result["result_data"]["reference_id"] == "ref_obsidian_123"
    assert "raw_data" not in result["result_data"]
    
    agent._storage.save_data.assert_awaited_once()
    args, kwargs = agent._storage.save_data.call_args
    assert "files" in kwargs["data"]
    assert kwargs["metadata"] == {"action": "search", "task_id": "test_obsidian_task", "source": "obsidian"}
