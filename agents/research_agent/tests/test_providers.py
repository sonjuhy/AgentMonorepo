import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agents.research_agent.providers import FallbackSearchProvider
from shared_core.search.interfaces import SearchProviderProtocol, SearchResult

@pytest.fixture
def primary_provider():
    provider = AsyncMock(spec=SearchProviderProtocol)
    provider.search.return_value = SearchResult(answer="Primary Answer", citations=["http://primary.com"])
    provider.search_with_context.return_value = SearchResult(answer="Primary Answer Context", citations=[])
    return provider

@pytest.fixture
def secondary_provider():
    provider = AsyncMock(spec=SearchProviderProtocol)
    provider.search.return_value = SearchResult(answer="Secondary Answer", citations=["http://secondary.com"])
    provider.search_with_context.return_value = SearchResult(answer="Secondary Answer Context", citations=[])
    return provider

@pytest.mark.asyncio
async def test_fallback_search_provider_success_primary(primary_provider, secondary_provider):
    """Primary provider succeeds, secondary is not called."""
    fallback_provider = FallbackSearchProvider(primary_provider, secondary_provider)
    result = await fallback_provider.search("test query")
    
    assert result.answer == "Primary Answer"
    primary_provider.search.assert_awaited_once_with("test query")
    secondary_provider.search.assert_not_awaited()

@pytest.mark.asyncio
async def test_fallback_search_provider_primary_fails(primary_provider, secondary_provider):
    """Primary provider fails, secondary is called and succeeds."""
    primary_provider.search.side_effect = Exception("API rate limit exceeded")
    
    fallback_provider = FallbackSearchProvider(primary_provider, secondary_provider)
    result = await fallback_provider.search("test query")
    
    assert result.answer == "Secondary Answer"
    primary_provider.search.assert_awaited_once_with("test query")
    secondary_provider.search.assert_awaited_once_with("test query")

@pytest.mark.asyncio
async def test_fallback_search_provider_both_fail(primary_provider, secondary_provider):
    """Both providers fail, exception is raised."""
    primary_provider.search.side_effect = Exception("Primary failed")
    secondary_provider.search.side_effect = Exception("Secondary failed")
    
    fallback_provider = FallbackSearchProvider(primary_provider, secondary_provider)
    
    with pytest.raises(Exception, match="Secondary failed"):
        await fallback_provider.search("test query")

@pytest.mark.asyncio
async def test_fallback_search_with_context_primary_fails(primary_provider, secondary_provider):
    """Primary provider fails for search_with_context, secondary is called."""
    primary_provider.search_with_context.side_effect = Exception("Primary context failed")
    
    fallback_provider = FallbackSearchProvider(primary_provider, secondary_provider)
    result = await fallback_provider.search_with_context("test query", "test context")
    
    assert result.answer == "Secondary Answer Context"
    primary_provider.search_with_context.assert_awaited_once_with("test query", "test context")
    secondary_provider.search_with_context.assert_awaited_once_with("test query", "test context")
