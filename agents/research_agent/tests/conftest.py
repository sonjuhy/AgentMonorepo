import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from shared_core.search.interfaces import SearchResult


@pytest.fixture(autouse=True)
def auto_patch_llm_provider():
    """모든 research_agent 테스트에서 LLM 공급자 생성 시 API 키 없이도 실행되도록 패치."""
    mock_llm = AsyncMock()
    mock_llm.generate_response.return_value = (
        '["query 1", "query 2"]',
        MagicMock(prompt_tokens=5, completion_tokens=5, total_tokens=10),
    )
    with patch("agents.research_agent.agent.build_llm_provider_from_config", return_value=mock_llm):
        yield mock_llm


@pytest.fixture
def mock_search_result():
    return SearchResult(answer="Test answer", citations=["http://test.com"])
