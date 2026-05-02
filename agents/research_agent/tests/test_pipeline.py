import asyncio
from unittest.mock import AsyncMock

import pytest

from agents.research_agent.pipeline import IntentAnalyzer, SearchExecutor, ReportSynthesizer
from shared_core.search.interfaces import SearchResult, SearchProviderProtocol

@pytest.fixture
def mock_provider():
    provider = AsyncMock(spec=SearchProviderProtocol)
    provider.search.return_value = SearchResult(answer="Mock answer", citations=["http://mock.com"])
    return provider

@pytest.mark.asyncio
async def test_intent_analyzer():
    mock_llm = AsyncMock()
    mock_response = AsyncMock()
    mock_response.text = '["query 1", "query 2"]'
    mock_llm.generate_content.return_value = mock_response
    
    analyzer = IntentAnalyzer(mock_llm)
    queries = await analyzer.analyze("broad query")
    
    assert isinstance(queries, list)
    assert len(queries) == 2
    assert queries == ["query 1", "query 2"]
    mock_llm.generate_content.assert_awaited_once()

@pytest.mark.asyncio
async def test_search_executor(mock_provider):
    executor = SearchExecutor(mock_provider)
    results = await executor.execute(["query 1", "query 2"])
    
    assert len(results) == 2
    assert results[0].answer == "Mock answer"
    assert results[1].answer == "Mock answer"
    assert mock_provider.search.call_count == 2

@pytest.mark.asyncio
async def test_report_synthesizer():
    mock_llm = AsyncMock()
    mock_response = AsyncMock()
    mock_response.text = "# Synthesized Report\n\nData from sources [1][2]."
    mock_llm.generate_content.return_value = mock_response
    
    synthesizer = ReportSynthesizer(mock_llm)
    
    results = [
        SearchResult(answer="Data 1", citations=["http://doc1.com"]),
        SearchResult(answer="Data 2", citations=["http://doc2.com"])
    ]
    
    report, citations = await synthesizer.synthesize("original query", results)
    
    assert "Synthesized Report" in report
    assert citations == ["http://doc1.com", "http://doc2.com"]
    mock_llm.generate_content.assert_awaited_once()
