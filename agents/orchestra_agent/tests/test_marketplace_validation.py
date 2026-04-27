"""
TDD: 마켓플레이스 매니페스트 입력값 검증 테스트

외부 URL 에서 받은 매니페스트의 name, code, packages 필드가
서버사이드에서 엄격하게 검증되어야 한다.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.orchestra_agent.marketplace_handler import (
    MarketplaceHandler,
    _validate_manifest,
)


# ── 단위: _validate_manifest ─────────────────────────────────────────────────

class TestValidateManifest:

    def _call(self, manifest: dict):
        return _validate_manifest(manifest)

    # name 필드 검증
    def test_name_missing_raises(self):
        with pytest.raises(ValueError, match="name"):
            self._call({"code": "print(1)"})

    def test_name_empty_raises(self):
        with pytest.raises(ValueError, match="name"):
            self._call({"name": "", "code": "print(1)"})

    def test_name_path_traversal_raises(self):
        with pytest.raises(ValueError, match="name"):
            self._call({"name": "../../etc/passwd", "code": "x"})

    def test_name_with_spaces_raises(self):
        with pytest.raises(ValueError, match="name"):
            self._call({"name": "my agent", "code": "x"})

    def test_name_with_special_chars_raises(self):
        with pytest.raises(ValueError, match="name"):
            self._call({"name": "agent<script>", "code": "x"})

    def test_name_too_long_raises(self):
        with pytest.raises(ValueError, match="name"):
            self._call({"name": "a" * 65, "code": "x"})

    def test_valid_name_passes(self):
        self._call({"name": "weather_agent", "code": "print(1)"})
        self._call({"name": "MyAgent42", "code": "print(1)"})
        self._call({"name": "a", "code": "print(1)"})

    # code 필드 검증
    def test_code_missing_raises(self):
        with pytest.raises(ValueError, match="code"):
            self._call({"name": "agent"})

    def test_code_empty_raises(self):
        with pytest.raises(ValueError, match="code"):
            self._call({"name": "agent", "code": ""})

    def test_code_too_large_raises(self):
        big_code = "x = 1\n" * 100_000  # ~700 KB
        with pytest.raises(ValueError, match="code"):
            self._call({"name": "agent", "code": big_code})

    def test_valid_code_passes(self):
        self._call({"name": "agent", "code": "def run(p): return {}"})

    # packages 필드 검증
    def test_packages_too_many_raises(self):
        pkgs = [f"pkg{i}" for i in range(21)]
        with pytest.raises(ValueError, match="packages"):
            self._call({"name": "agent", "code": "x", "packages": pkgs})

    def test_package_name_with_shell_injection_raises(self):
        with pytest.raises(ValueError, match="packages"):
            self._call({"name": "agent", "code": "x", "packages": ["requests; rm -rf /"]})

    def test_package_name_with_path_raises(self):
        with pytest.raises(ValueError, match="packages"):
            self._call({"name": "agent", "code": "x", "packages": ["../evil"]})

    def test_valid_packages_pass(self):
        self._call({"name": "agent", "code": "x", "packages": ["requests", "numpy>=1.0", "pydantic~=2.0"]})

    # permissions 필드 검증
    def test_invalid_permission_preset_raises(self):
        with pytest.raises(ValueError, match="permissions"):
            self._call({"name": "agent", "code": "x", "permissions": "superroot"})

    def test_valid_permission_presets_pass(self):
        for preset in ("minimal", "standard", "trusted"):
            self._call({"name": "agent", "code": "x", "permissions": preset})


# ── 통합: install_from_marketplace 에서 검증 실행 ────────────────────────────

@pytest.mark.asyncio
async def test_install_rejects_path_traversal_name():
    builder = AsyncMock()
    registry = MagicMock()
    handler = MarketplaceHandler(builder, registry)

    with patch("agents.orchestra_agent.marketplace_handler.socket.gethostbyname", return_value="93.184.216.34"):
        with patch("agents.orchestra_agent.marketplace_handler.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = AsyncMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"name": "../../evil", "code": "x"}),
            )

            result = await handler.install_from_marketplace("https://example.com/agent.json", "t1")

    assert result["status"] == "FAILED"
    assert "name" in result["error"]["message"].lower()


@pytest.mark.asyncio
async def test_install_rejects_oversized_code():
    builder = AsyncMock()
    registry = MagicMock()
    handler = MarketplaceHandler(builder, registry)

    big_code = "x = 1\n" * 100_000

    with patch("agents.orchestra_agent.marketplace_handler.socket.gethostbyname", return_value="93.184.216.34"):
        with patch("agents.orchestra_agent.marketplace_handler.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = AsyncMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"name": "valid_agent", "code": big_code}),
            )

            result = await handler.install_from_marketplace("https://example.com/agent.json", "t2")

    assert result["status"] == "FAILED"
    assert "code" in result["error"]["message"].lower()


@pytest.mark.asyncio
async def test_install_rejects_injection_in_packages():
    builder = AsyncMock()
    registry = MagicMock()
    handler = MarketplaceHandler(builder, registry)

    with patch("agents.orchestra_agent.marketplace_handler.socket.gethostbyname", return_value="93.184.216.34"):
        with patch("agents.orchestra_agent.marketplace_handler.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = AsyncMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={
                    "name": "myagent",
                    "code": "def run(p): return {}",
                    "packages": ["requests; rm -rf /"],
                }),
            )

            result = await handler.install_from_marketplace("https://example.com/agent.json", "t3")

    assert result["status"] == "FAILED"
    assert "packages" in result["error"]["message"].lower()
