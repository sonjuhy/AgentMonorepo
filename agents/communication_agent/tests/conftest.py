import pytest
from fakeredis import FakeAsyncRedis

@pytest.fixture
async def fake_redis():
    """Mock Redis fixture using fakeredis."""
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()
