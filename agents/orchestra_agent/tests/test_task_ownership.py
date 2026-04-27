"""
TDD: cancel_task 소유권 검증 테스트

태스크를 제출한 user_id 와 취소를 요청한 user_id 가 다를 경우
cancel_task 가 PermissionError 를 발생시켜야 한다.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── 단위: OrchestraManager.cancel_task ───────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_task_by_owner_succeeds(fake_redis, nlu_engine, state_manager, health_monitor):
    """소유자(owner)가 취소하면 True 를 반환한다."""
    from agents.orchestra_agent.manager import OrchestraManager

    manager = OrchestraManager(
        redis_client=fake_redis,
        nlu_engine=nlu_engine,
        state_manager=state_manager,
        health_monitor=health_monitor,
    )

    task_id = "task-owner-test"
    owner_id = "alice"

    # task state 에 소유자 기록
    await state_manager.update_task_state(task_id, {
        "status": "PROCESSING",
        "session_id": f"{owner_id}:api",
        "user_id": owner_id,
    })

    result = await manager.cancel_task(task_id, owner_id)
    assert result is True


@pytest.mark.asyncio
async def test_cancel_task_by_non_owner_raises(fake_redis, nlu_engine, state_manager, health_monitor):
    """다른 사용자가 취소하면 PermissionError 가 발생해야 한다."""
    from agents.orchestra_agent.manager import OrchestraManager

    manager = OrchestraManager(
        redis_client=fake_redis,
        nlu_engine=nlu_engine,
        state_manager=state_manager,
        health_monitor=health_monitor,
    )

    task_id = "task-ownership-deny"
    owner_id = "alice"
    attacker_id = "bob"

    await state_manager.update_task_state(task_id, {
        "status": "PROCESSING",
        "session_id": f"{owner_id}:api",
        "user_id": owner_id,
    })

    with pytest.raises(PermissionError, match="권한"):
        await manager.cancel_task(task_id, attacker_id)


@pytest.mark.asyncio
async def test_cancel_task_not_found_returns_false(fake_redis, nlu_engine, state_manager, health_monitor):
    """존재하지 않는 태스크는 False 를 반환한다."""
    from agents.orchestra_agent.manager import OrchestraManager

    manager = OrchestraManager(
        redis_client=fake_redis,
        nlu_engine=nlu_engine,
        state_manager=state_manager,
        health_monitor=health_monitor,
    )

    result = await manager.cancel_task("nonexistent-task", "any-user")
    assert result is False


@pytest.mark.asyncio
async def test_cancel_already_completed_returns_false(fake_redis, nlu_engine, state_manager, health_monitor):
    """이미 완료된 태스크는 False 를 반환한다."""
    from agents.orchestra_agent.manager import OrchestraManager

    manager = OrchestraManager(
        redis_client=fake_redis,
        nlu_engine=nlu_engine,
        state_manager=state_manager,
        health_monitor=health_monitor,
    )

    task_id = "task-completed"
    owner_id = "alice"

    await state_manager.update_task_state(task_id, {
        "status": "COMPLETED",
        "session_id": f"{owner_id}:api",
        "user_id": owner_id,
    })

    result = await manager.cancel_task(task_id, owner_id)
    assert result is False


# ── 통합: /tasks/{task_id}/cancel 엔드포인트 ────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_endpoint_uses_user_id_from_query(async_client):
    """
    /tasks/{id}/cancel?user_id=alice 처럼 user_id 쿼리 파라미터를 받아
    manager.cancel_task 에 전달해야 한다.
    """
    from agents.orchestra_agent.app_context import ctx

    ctx.manager = AsyncMock()
    ctx.manager.cancel_task.return_value = True

    resp = await async_client.post("/tasks/task-xyz/cancel?user_id=alice")
    assert resp.status_code == 200
    ctx.manager.cancel_task.assert_called_once_with("task-xyz", "alice")


@pytest.mark.asyncio
async def test_cancel_endpoint_defaults_user_id_to_api_user(async_client):
    """user_id 를 생략하면 기본값 'api-user' 로 호출된다."""
    from agents.orchestra_agent.app_context import ctx

    ctx.manager = AsyncMock()
    ctx.manager.cancel_task.return_value = True

    resp = await async_client.post("/tasks/task-abc/cancel")
    assert resp.status_code == 200
    ctx.manager.cancel_task.assert_called_once_with("task-abc", "api-user")


@pytest.mark.asyncio
async def test_cancel_endpoint_returns_403_on_permission_error(async_client):
    """manager.cancel_task 가 PermissionError 를 발생시키면 403 을 반환한다."""
    from agents.orchestra_agent.app_context import ctx

    ctx.manager = AsyncMock()
    ctx.manager.cancel_task.side_effect = PermissionError("이 태스크를 취소할 권한이 없습니다.")

    resp = await async_client.post("/tasks/task-owned-by-bob/cancel?user_id=alice")
    assert resp.status_code == 403
    assert "권한" in resp.json()["detail"]
