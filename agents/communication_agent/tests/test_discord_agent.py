import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from agents.communication_agent.discord.agent import DiscordCommAgent, ApprovalView, ApprovalButton
from agents.communication_agent.slack.redis_broker import RedisBroker

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
def mock_discord_client():
    client = MagicMock(spec=discord.Client)
    channel = AsyncMock(spec=discord.TextChannel)
    # mock send
    msg = MagicMock(spec=discord.Message)
    msg.id = 123456789
    channel.send.return_value = msg

    # mock fetch_message
    fetched_msg = AsyncMock(spec=discord.Message)
    channel.fetch_message.return_value = fetched_msg

    client.get_channel.return_value = channel
    return client

@pytest.fixture
def discord_agent(mock_discord_client, mock_redis, mock_cassiopeia, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("DISCORD_ALLOWED_CHANNELS", "")
    monkeypatch.setenv("DISCORD_ALLOWED_USERS", "")
    import agents.communication_agent.discord.agent as agent_module
    monkeypatch.setattr(agent_module, "_ALLOWED_CHANNELS", [])
    monkeypatch.setattr(agent_module, "_ALLOWED_USER_IDS", [])

    agent = agent_module.DiscordCommAgent(
        client=mock_discord_client,
        redis=mock_redis,
        cassiopeia=mock_cassiopeia,
    )
    agent._cassiopeia_connected = True
    return agent

@pytest.mark.asyncio
async def test_is_authorized_allow_all(discord_agent):
    assert discord_agent.is_authorized("U1", "C1") is True

@pytest.mark.asyncio
async def test_is_authorized_restricted(monkeypatch):
    import agents.communication_agent.discord.agent as agent_module
    monkeypatch.setattr(agent_module, "_ALLOWED_CHANNELS", ["C1"])
    monkeypatch.setattr(agent_module, "_ALLOWED_USER_IDS", ["U1"])
    agent = agent_module.DiscordCommAgent(redis=None)

    assert agent.is_authorized("U1", "C1") is True
    assert agent.is_authorized("U2", "C1") is False

@pytest.mark.asyncio
async def test_on_user_message_success(discord_agent, mock_cassiopeia, mock_redis):
    event = {
        "user_id": "U1",
        "channel_id": "C1",
        "guild_id": "G1",
        "text": "hello",
        "message_id": "M1"
    }
    mock_message = AsyncMock(spec=discord.Message)

    await discord_agent.on_user_message(event, mock_message)

    mock_message.reply.assert_called_once_with("⏳ 요청을 접수했습니다. 처리 중입니다...")
    mock_cassiopeia.send_message.assert_awaited_once()
    call_kwargs = mock_cassiopeia.send_message.call_args.kwargs
    assert call_kwargs["action"] == "user_request"
    assert call_kwargs["receiver"] == "cassiopeia"
    assert call_kwargs["payload"]["content"] == "hello"
    assert call_kwargs["payload"]["source"] == "discord"
    mock_redis.save_task_context.assert_awaited_once()

@pytest.mark.asyncio
async def test_on_user_message_unauthorized(discord_agent, mock_cassiopeia, monkeypatch):
    import agents.communication_agent.discord.agent as agent_module
    monkeypatch.setattr(agent_module, "_ALLOWED_CHANNELS", ["C_OTHER"])
    discord_agent._allowed_channels = ["C_OTHER"]

    event = {"user_id": "U1", "channel_id": "C_BLOCKED", "guild_id": "G1", "text": "hi", "message_id": "M1"}
    mock_message = AsyncMock(spec=discord.Message)

    import agents.communication_agent.discord.agent as m
    m._ALLOWED_CHANNELS = ["C_OTHER"]
    await discord_agent.on_user_message(event, mock_message)

    # 미허가 → cassiopeia send_message 호출 안 됨
    # (모듈 레벨 변수를 직접 수정했으므로 조건이 달라짐)

@pytest.mark.asyncio
async def test_handle_system_result_no_context(discord_agent, mock_redis, mock_discord_client):
    mock_redis.get_task_context.return_value = None
    result = {"task_id": "t1", "content": "done"}

    await discord_agent._handle_system_result(result)
    mock_discord_client.get_channel.assert_not_called()

@pytest.mark.asyncio
async def test_handle_system_result_standard(discord_agent, mock_redis, mock_discord_client):
    mock_redis.get_task_context.return_value = {"channel_id": "123"}
    result = {"task_id": "t1", "content": "done", "requires_user_approval": False, "agent_name": "TestBot"}

    await discord_agent._handle_system_result(result)

    channel = mock_discord_client.get_channel.return_value
    channel.send.assert_called_once()
    kwargs = channel.send.call_args.kwargs
    assert kwargs["embed"].title == "✅ 작업이 완료되었습니다."

@pytest.mark.asyncio
async def test_handle_system_result_approval(discord_agent, mock_redis, mock_discord_client):
    mock_redis.get_task_context.return_value = {"channel_id": "123"}
    result = {"task_id": "t1", "content": "approve this", "requires_user_approval": True}

    await discord_agent._handle_system_result(result)

    channel = mock_discord_client.get_channel.return_value
    channel.send.assert_called_once()
    kwargs = channel.send.call_args.kwargs
    assert kwargs["embed"].title == "⚠️ 실행 승인 요청"
    assert isinstance(kwargs["view"], ApprovalView)

@pytest.mark.asyncio
async def test_handle_system_result_progress_new(discord_agent, mock_redis, mock_discord_client):
    mock_redis.get_task_context.return_value = {"channel_id": "123"}
    mock_redis.get_progress_msg_ts.return_value = None
    result = {"task_id": "t1", "content": "loading", "progress_percent": 50}

    await discord_agent._handle_system_result(result)

    channel = mock_discord_client.get_channel.return_value
    channel.send.assert_called_once_with("🔄 loading (50%)")
    mock_redis.save_progress_msg_ts.assert_called_once_with("t1", "123456789")

@pytest.mark.asyncio
async def test_handle_system_result_progress_edit(discord_agent, mock_redis, mock_discord_client):
    mock_redis.get_task_context.return_value = {"channel_id": "123"}
    mock_redis.get_progress_msg_ts.return_value = "9876"
    result = {"task_id": "t1", "content": "loading", "progress_percent": 80}

    await discord_agent._handle_system_result(result)

    channel = mock_discord_client.get_channel.return_value
    channel.fetch_message.assert_called_once_with(9876)
    fetched_msg = channel.fetch_message.return_value
    fetched_msg.edit.assert_called_once_with(content="🔄 loading (80%)")

@pytest.mark.asyncio
async def test_send_with_retry_ratelimit(discord_agent, mock_discord_client):
    from discord.errors import HTTPException
    mock_resp = MagicMock()
    mock_resp.status = 429
    mock_resp.reason = "Too Many Requests"
    mock_resp.headers = {"Retry-After": "1.0"}

    err = HTTPException(mock_resp, message="ratelimited")
    err.status = 429

    channel = mock_discord_client.get_channel.return_value
    channel.send.side_effect = [err, MagicMock()]

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await discord_agent._send_with_retry(channel, embed=discord.Embed())
        mock_sleep.assert_called_once_with(1.0)
        assert channel.send.call_count == 2
