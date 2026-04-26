import pytest
from unittest.mock import patch, AsyncMock, MagicMock

pytestmark = pytest.mark.skip(reason="마켓플레이스 기능 임시 비활성화로 인한 테스트 스킵")

from agents.orchestra_agent.marketplace_handler import MarketplaceHandler, _validate_marketplace_url

@pytest.mark.asyncio
async def test_ssrf_dns_rebinding_prevention():
    builder = AsyncMock()
    registry = MagicMock()
    handler = MarketplaceHandler(builder, registry)

    # We want to assert that httpx.AsyncClient.get is called with the resolved IP, not the hostname.
    original_url = "https://example.com/agent.json"
    
    with patch("agents.orchestra_agent.marketplace_handler.socket.gethostbyname") as mock_dns:
        mock_dns.return_value = "93.184.216.34" # example.com IP
        
        with patch("agents.orchestra_agent.marketplace_handler.httpx.AsyncClient.get") as mock_get:
            mock_response = AsyncMock()
            mock_response.json.return_value = {
                "name": "test_agent",
                "code": "print('hello')"
            }
            mock_get.return_value = mock_response
            
            await handler.install_from_marketplace(original_url, "task-123")
            
            # Verify socket.gethostbyname was called with the hostname
            mock_dns.assert_called_once_with("example.com")
            
            # The critical check: httpx.get should be called with the IP address to prevent DNS rebinding
            # And it should probably have a headers={"Host": "example.com"} to pass vhost routing
            call_args, call_kwargs = mock_get.call_args
            called_url = call_args[0]
            
            assert "93.184.216.34" in called_url, "HTTP request should use the resolved IP address to prevent DNS rebinding"
            assert "example.com" not in called_url, "HTTP request should NOT use the hostname to prevent DNS rebinding"
