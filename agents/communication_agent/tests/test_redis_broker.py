import json
import pytest
import uuid
from agents.communication_agent.slack.redis_broker import RedisBroker

@pytest.fixture
def broker(fake_redis):
    # Overwrite the internal client with fakeredis
    b = RedisBroker()
    b._client = fake_redis
    return b

@pytest.mark.asyncio
async def test_push_to_orchestra(broker, fake_redis):
    task_id = await broker.push_to_orchestra(
        user_id="U1",
        channel_id="C1",
        content="hello world",
        thread_ts="123.456",
        source="slack"
    )
    
    assert task_id is not None
    
    val = await fake_redis.lpop("agent:orchestra:tasks")
    data = json.loads(val)
    
    assert data["task_id"] == task_id
    assert data["session_id"] == "U1:C1"
    assert data["requester"]["user_id"] == "U1"
    assert data["requester"]["channel_id"] == "C1"
    assert data["content"] == "hello world"
    assert data["thread_ts"] == "123.456"
    assert data["source"] == "slack"

@pytest.mark.asyncio
async def test_push_approval(broker, fake_redis):
    feedback = {
        "task_id": "task-123",
        "action": "approve"
    }
    await broker.push_approval(feedback)
    
    val = await fake_redis.lpop("orchestra:approval:task-123")
    assert val is not None
    data = json.loads(val)
    assert data["action"] == "approve"

@pytest.mark.asyncio
async def test_push_approval_no_task_id(broker, fake_redis):
    feedback = {"action": "approve"}
    await broker.push_approval(feedback)
    # Should not push anywhere if task_id is missing
    keys = await fake_redis.keys("orchestra:approval:*")
    assert len(keys) == 0

@pytest.mark.asyncio
async def test_blpop_comm_task(broker, fake_redis):
    task_data = {"task_id": "1", "content": "done"}
    await fake_redis.rpush("agent:communication:tasks", json.dumps(task_data))
    
    result = await broker.blpop_comm_task(timeout=1.0)
    assert result is not None
    assert result["task_id"] == "1"

@pytest.mark.asyncio
async def test_blpop_comm_task_timeout(broker):
    result = await broker.blpop_comm_task(timeout=0.1)
    assert result is None

@pytest.mark.asyncio
async def test_save_and_get_task_context(broker, fake_redis):
    ctx = {"channel_id": "C1", "thread_ts": "123"}
    await broker.save_task_context("t1", ctx)
    
    res = await broker.get_task_context("t1")
    assert res == ctx
    
    ttl = await fake_redis.ttl("slack:task:t1:context")
    assert ttl > 0

@pytest.mark.asyncio
async def test_update_agent_health(broker, fake_redis):
    await broker.update_agent_health("comm_agent", {"status": "IDLE"})
    res = await fake_redis.hgetall("agent:comm_agent:health")
    assert res["status"] == "IDLE"
    ttl = await fake_redis.ttl("agent:comm_agent:health")
    assert ttl > 0
