"""
TDD: callback_url SSRF 방어 테스트

submit_task 엔드포인트의 callback_url 필드에
내부망/루프백 IP를 지정할 수 없도록 검증합니다.
"""
import pytest
from unittest.mock import patch


# ── 단위: _validate_callback_url ─────────────────────────────────────────────

class TestValidateCallbackUrl:
    """main.py 내 _validate_callback_url 순수 함수 테스트."""

    def _call(self, url: str):
        from agents.cassiopeia_agent.main import _validate_callback_url
        return _validate_callback_url(url)

    def test_loopback_ipv4_blocked(self):
        with patch("agents.cassiopeia_agent.main.socket.gethostbyname", return_value="127.0.0.1"):
            with pytest.raises(ValueError, match="내부"):
                self._call("http://localhost/hook")

    def test_private_class_a_blocked(self):
        with patch("agents.cassiopeia_agent.main.socket.gethostbyname", return_value="10.0.0.1"):
            with pytest.raises(ValueError, match="내부"):
                self._call("http://internal.corp/hook")

    def test_private_class_b_blocked(self):
        with patch("agents.cassiopeia_agent.main.socket.gethostbyname", return_value="172.16.0.5"):
            with pytest.raises(ValueError, match="내부"):
                self._call("http://172.16.0.5/hook")

    def test_private_class_c_blocked(self):
        with patch("agents.cassiopeia_agent.main.socket.gethostbyname", return_value="192.168.1.100"):
            with pytest.raises(ValueError, match="내부"):
                self._call("http://192.168.1.100/hook")

    def test_link_local_blocked(self):
        with patch("agents.cassiopeia_agent.main.socket.gethostbyname", return_value="169.254.1.1"):
            with pytest.raises(ValueError, match="내부"):
                self._call("http://169.254.1.1/hook")

    def test_non_http_scheme_blocked(self):
        with pytest.raises(ValueError, match="스킴"):
            self._call("ftp://attacker.com/hook")

    def test_file_scheme_blocked(self):
        with pytest.raises(ValueError, match="스킴"):
            self._call("file:///etc/passwd")

    def test_valid_https_url_passes(self):
        with patch("agents.cassiopeia_agent.main.socket.gethostbyname", return_value="93.184.216.34"):
            # 예외 없이 통과해야 함
            self._call("https://webhook.example.com/callback")

    def test_valid_http_url_passes(self):
        with patch("agents.cassiopeia_agent.main.socket.gethostbyname", return_value="93.184.216.34"):
            self._call("http://webhook.example.com/callback")


# ── 통합: /tasks 엔드포인트 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_task_rejects_private_callback_url(async_client):
    """callback_url에 내부망 주소를 제공하면 400 을 반환해야 한다."""
    with patch("agents.cassiopeia_agent.main.socket.gethostbyname", return_value="192.168.1.1"):
        resp = await async_client.post(
            "/tasks",
            json={
                "content": "hello",
                "user_id": "user1",
                "callback_url": "http://internal.corp/hook",
            },
        )
    assert resp.status_code == 400
    assert "callback_url" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_submit_task_accepts_valid_callback_url(async_client):
    """유효한 외부 callback_url은 허용하고 task_id를 반환해야 한다."""
    with patch("agents.cassiopeia_agent.main.socket.gethostbyname", return_value="93.184.216.34"):
        resp = await async_client.post(
            "/tasks",
            json={
                "content": "hello",
                "user_id": "user1",
                "callback_url": "https://webhook.example.com/callback",
            },
        )
    assert resp.status_code == 200
    assert "task_id" in resp.json()


@pytest.mark.asyncio
async def test_submit_task_without_callback_url_always_passes(async_client):
    """callback_url 없이 요청하면 SSRF 검증을 수행하지 않고 정상 처리된다."""
    resp = await async_client.post(
        "/tasks",
        json={"content": "hello", "user_id": "user1"},
    )
    assert resp.status_code == 200
    assert "task_id" in resp.json()
