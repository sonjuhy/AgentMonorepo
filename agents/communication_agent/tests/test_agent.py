import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.communication_agent.slack.agent import SlackCommAgent
from agents.communication_agent.slack.redis_broker import RedisBroker
from slack_sdk.errors import SlackApiError

@pytest.fixture
def mock_web_client():
    client = AsyncMock()
    # By default, chat_postMessage returns a fake ts
    client.chat_postMessage.return_value = {"ts": "12345.6789"}
    client.chat_update.return_value = {"ts": "12345.6789"}
    return client

@pytest.fixture
def mock_redis():
    broker = AsyncMock(spec=RedisBroker)
    return broker

@pytest.fixture
def mock_cassiopeia():
    client = AsyncMock()
    client.send_message = AsyncMock(return_value=True)
    return client

@pytest.fixture
def agent(mock_web_client, mock_redis, mock_cassiopeia, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    monkeypatch.setenv("NOTION_TOKEN", "fake-notion")
    monkeypatch.setenv("NOTION_DB_ID", "fake-db")
    monkeypatch.setenv("SLACK_CHANNEL", "C_ALARM")
    # Reset allowed lists for testing
    monkeypatch.setenv("SLACK_ALLOWED_CHANNELS", "")
    monkeypatch.setenv("SLACK_ALLOWED_USERS", "")
    a = SlackCommAgent(web_client=mock_web_client, redis=mock_redis, cassiopeia=mock_cassiopeia)
    a._cassiopeia_connected = True
    return a

@pytest.mark.asyncio
async def test_is_authorized_allow_all(agent):
    assert agent.is_authorized("U1", "C1") is True

@pytest.mark.asyncio
async def test_is_authorized_restricted(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    import agents.communication_agent.slack.agent as agent_module
    monkeypatch.setattr(agent_module, "_ALLOWED_CHANNELS", ["C1", "C2"])
    monkeypatch.setattr(agent_module, "_ALLOWED_USER_IDS", ["U1"])
    restricted_agent = agent_module.SlackCommAgent()
    
    assert restricted_agent.is_authorized("U1", "C1") is True
    assert restricted_agent.is_authorized("U2", "C1") is False
    assert restricted_agent.is_authorized("U1", "C3") is False

@pytest.mark.asyncio
async def test_on_user_request_unauthorized(agent, mock_redis, mock_cassiopeia, mock_web_client):
    # Mocking it to return False
    agent.is_authorized = MagicMock(return_value=False)

    event = {"user": "U1", "channel": "C1", "ts": "111", "text": "hello"}
    await agent.on_user_request(event, say=AsyncMock())

    mock_cassiopeia.send_message.assert_not_called()
    mock_web_client.chat_postMessage.assert_not_called()

@pytest.mark.asyncio
async def test_on_user_request_success(agent, mock_redis, mock_cassiopeia, mock_web_client):
    event = {"user": "U1", "channel": "C1", "ts": "111.0", "text": "<@U123> help"}
    await agent.on_user_request(event, say=AsyncMock())

    mock_web_client.chat_postMessage.assert_called_once_with(
        channel="C1",
        thread_ts="111.0",
        text="⏳ 요청을 접수했습니다. 처리 중입니다..."
    )
    # cassiopeia should send to orchestra with signed task payload
    mock_cassiopeia.send_message.assert_called_once()
    call_kwargs = mock_cassiopeia.send_message.call_args.kwargs
    assert call_kwargs["action"] == "user_request"
    assert call_kwargs["receiver"] == "orchestra"
    payload = call_kwargs["payload"]
    assert payload["content"] == "help"
    assert payload["requester"]["user_id"] == "U1"
    assert payload["requester"]["channel_id"] == "C1"

    # task context should be saved
    mock_redis.save_task_context.assert_called_once()
    ctx_args = mock_redis.save_task_context.call_args
    task_id = ctx_args[0][0]
    ctx = ctx_args[0][1]
    assert ctx["channel_id"] == "C1"
    assert ctx["thread_ts"] == "111.0"
    assert ctx["user_id"] == "U1"
    assert ctx["session_id"] == "U1:C1"

@pytest.mark.asyncio
async def test_handle_system_result_no_context(agent, mock_redis, mock_web_client):
    mock_redis.get_task_context.return_value = None
    result = {"task_id": "t1", "content": "done"}
    await agent._handle_system_result(result)
    mock_web_client.chat_postMessage.assert_not_called()

@pytest.mark.asyncio
async def test_handle_system_result_standard(agent, mock_redis, mock_web_client):
    mock_redis.get_task_context.return_value = {"channel_id": "C1", "thread_ts": "111", "user_id": "U1"}
    result = {"task_id": "t1", "content": "task is complete", "requires_user_approval": False, "agent_name": "TestAgent"}
    
    await agent._handle_system_result(result)
    
    mock_web_client.chat_postMessage.assert_called_once()
    kwargs = mock_web_client.chat_postMessage.call_args.kwargs
    assert kwargs["channel"] == "C1"
    assert kwargs["thread_ts"] == "111"
    assert "✅ 작업이 완료되었습니다." in str(kwargs["blocks"])
    assert "TestAgent" in str(kwargs["blocks"])

@pytest.mark.asyncio
async def test_handle_system_result_approval(agent, mock_redis, mock_web_client):
    mock_redis.get_task_context.return_value = {"channel_id": "C1", "thread_ts": "111", "user_id": "U1"}
    result = {"task_id": "t1", "content": "please approve", "requires_user_approval": True}
    
    await agent._handle_system_result(result)
    
    mock_web_client.chat_postMessage.assert_called_once()
    kwargs = mock_web_client.chat_postMessage.call_args.kwargs
    assert "⚠️ 실행 승인 요청" in str(kwargs["blocks"])
    assert "approve_task" in str(kwargs["blocks"])

@pytest.mark.asyncio
async def test_handle_system_result_progress(agent, mock_redis, mock_web_client):
    mock_redis.get_task_context.return_value = {"channel_id": "C1", "thread_ts": "111"}
    mock_redis.get_progress_msg_ts.return_value = None
    
    result = {"task_id": "t1", "content": "downloading", "progress_percent": 50}
    await agent._handle_system_result(result)
    
    mock_web_client.chat_postMessage.assert_called_once_with(
        channel="C1",
        thread_ts="111",
        text="🔄 downloading (50%)"
    )
    mock_redis.save_progress_msg_ts.assert_called_once_with("t1", "12345.6789")

@pytest.mark.asyncio
async def test_handle_system_result_progress_update(agent, mock_redis, mock_web_client):
    mock_redis.get_task_context.return_value = {"channel_id": "C1", "thread_ts": "111"}
    mock_redis.get_progress_msg_ts.return_value = "999.0"
    
    result = {"task_id": "t1", "content": "processing", "progress_percent": 80}
    await agent._handle_system_result(result)
    
    mock_web_client.chat_update.assert_called_once_with(
        channel="C1",
        ts="999.0",
        text="🔄 processing (80%)"
    )

@pytest.mark.asyncio
async def test_send_with_retry_ratelimit(agent, mock_web_client):
    # Simulate rate limit error on first call, success on second
    from slack_sdk.web.slack_response import SlackResponse
    
    error_resp = SlackResponse(
        client=None,
        http_verb="POST",
        api_url="http://fake",
        req_args={},
        data={"error": "ratelimited"},
        headers={"Retry-After": "1"},
        status_code=429
    )
    api_error = SlackApiError(message="rate limited", response=error_resp)
    
    mock_web_client.chat_postMessage.side_effect = [api_error, {"ts": "success"}]
    
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await agent._send_with_retry(channel="C1", blocks=[], text="hi")
        mock_sleep.assert_called_once_with(1)
        assert mock_web_client.chat_postMessage.call_count == 2
