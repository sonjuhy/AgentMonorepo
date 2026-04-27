"""
TDD: requires_user_approval 서버사이드 강제 테스트

LLM이 requires_user_approval=False 로 반환해도
APPROVAL_REQUIRED_ACTIONS 에 속하는 액션이면 서버에서 강제로 승인을 요청해야 한다.
반대로 화이트리스트에 없는 일반 조회 액션은 LLM 판단(False)을 그대로 따른다.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agents.orchestra_agent.manager import (
    APPROVAL_REQUIRED_ACTIONS,
    _requires_approval,
)


# ── 단위: APPROVAL_REQUIRED_ACTIONS 상수 ────────────────────────────────────

class TestApprovalRequiredActions:
    def test_constant_is_frozenset(self):
        assert isinstance(APPROVAL_REQUIRED_ACTIONS, frozenset)

    def test_destructive_file_actions_included(self):
        for action in ("delete_file", "write_file", "overwrite_file"):
            assert action in APPROVAL_REQUIRED_ACTIONS, f"{action} must require approval"

    def test_code_execution_included(self):
        assert "execute_code" in APPROVAL_REQUIRED_ACTIONS
        assert "run_code" in APPROVAL_REQUIRED_ACTIONS

    def test_calendar_mutating_actions_included(self):
        for action in ("add_schedule", "modify_schedule", "remove_schedule"):
            assert action in APPROVAL_REQUIRED_ACTIONS

    def test_read_only_actions_not_included(self):
        for action in ("read_file", "search_files", "list_databases", "query_database",
                       "get_page", "search", "list_schedules", "search_and_report"):
            assert action not in APPROVAL_REQUIRED_ACTIONS, f"{action} should NOT require approval"


# ── 단위: _requires_approval 헬퍼 ────────────────────────────────────────────

class TestRequiresApprovalHelper:
    """_requires_approval(action, llm_flag) → bool"""

    def test_destructive_action_forces_true_regardless_of_llm(self):
        assert _requires_approval("delete_file", llm_flag=False) is True

    def test_destructive_action_stays_true_when_llm_also_true(self):
        assert _requires_approval("delete_file", llm_flag=True) is True

    def test_safe_action_respects_llm_false(self):
        assert _requires_approval("read_file", llm_flag=False) is False

    def test_safe_action_respects_llm_true(self):
        assert _requires_approval("read_file", llm_flag=True) is True

    def test_unknown_action_respects_llm_flag(self):
        assert _requires_approval("some_new_action", llm_flag=False) is False
        assert _requires_approval("some_new_action", llm_flag=True) is True


# ── 통합: _route_single 에서 강제 승인 요청 ────────────────────────────────────

@pytest.mark.asyncio
async def test_route_single_forces_approval_for_destructive_action(
    fake_redis, nlu_engine, state_manager, health_monitor
):
    """
    LLM이 requires_user_approval=False 로 반환한 delete_file 액션도
    OrchestraManager 가 승인 요청을 발행해야 한다.
    """
    from agents.orchestra_agent.manager import OrchestraManager
    from agents.orchestra_agent.models import SingleNLUResult

    manager = OrchestraManager(
        redis_client=fake_redis,
        nlu_engine=nlu_engine,
        state_manager=state_manager,
        health_monitor=health_monitor,
    )

    # LLM이 requires_user_approval=False 로 delete_file 을 반환
    nlu_result = SingleNLUResult(
        type="single",
        intent="파일 삭제",
        selected_agent="file_agent",
        action="delete_file",
        params={"path": "/tmp/test.txt"},
        metadata={"reason": "삭제 테스트", "confidence_score": 0.95, "requires_user_approval": False},
    )

    task = {
        "task_id": "t1",
        "session_id": "user1:api",
        "requester": {"user_id": "user1", "channel_id": "api"},
        "content": "파일 삭제해줘",
        "source": "api",
    }

    approval_requested = False

    async def mock_request_approval(result, orig_task):
        nonlocal approval_requested
        approval_requested = True
        return False  # 사용자가 거부

    manager.request_user_approval = mock_request_approval

    # 에이전트 가용 상태로 설정
    await health_monitor.register_agent("file_agent", ["delete_file"], lifecycle_type="ephemeral")
    await fake_redis.hset("agent:file_agent:health", mapping={"agent_id": "file_agent", "status": "IDLE"})

    await manager._route_single(nlu_result, task)

    assert approval_requested, "delete_file 은 LLM 판단과 무관하게 승인 요청이 발생해야 한다"


@pytest.mark.asyncio
async def test_route_single_skips_approval_for_safe_action(
    fake_redis, nlu_engine, state_manager, health_monitor
):
    """read_file 같은 안전 액션은 승인 없이 바로 dispatch 되어야 한다."""
    from agents.orchestra_agent.manager import OrchestraManager
    from agents.orchestra_agent.models import SingleNLUResult

    manager = OrchestraManager(
        redis_client=fake_redis,
        nlu_engine=nlu_engine,
        state_manager=state_manager,
        health_monitor=health_monitor,
    )

    nlu_result = SingleNLUResult(
        type="single",
        intent="파일 읽기",
        selected_agent="file_agent",
        action="read_file",
        params={"path": "/tmp/test.txt"},
        metadata={"reason": "읽기 테스트", "confidence_score": 0.95, "requires_user_approval": False},
    )

    task = {
        "task_id": "t2",
        "session_id": "user1:api",
        "requester": {"user_id": "user1", "channel_id": "api"},
        "content": "파일 읽어줘",
        "source": "api",
    }

    approval_requested = False

    async def mock_request_approval(result, orig_task):
        nonlocal approval_requested
        approval_requested = True
        return True

    manager.request_user_approval = mock_request_approval

    # execute_agent_task 를 mock 으로 대체해 실제 dispatch 없이 진행
    async def mock_execute(agent_name, task_id, dispatch, timeout):
        return {"status": "COMPLETED", "result_data": {"summary": "ok"}, "agent": agent_name}

    manager._execute_agent_task = mock_execute

    await health_monitor.register_agent("file_agent", ["read_file"], lifecycle_type="ephemeral")
    await fake_redis.hset("agent:file_agent:health", mapping={"agent_id": "file_agent", "status": "IDLE"})

    await manager._route_single(nlu_result, task)

    assert not approval_requested, "read_file 은 승인 요청 없이 바로 실행되어야 한다"


@pytest.mark.asyncio
async def test_run_plan_forces_approval_for_destructive_step(
    fake_redis, nlu_engine, state_manager, health_monitor
):
    """멀티스텝 계획에서도 write_file 스텝은 서버사이드 승인이 강제된다."""
    from agents.orchestra_agent.manager import OrchestraManager
    from agents.orchestra_agent.models import MultiStepNLUResult, PlanStep, PlanStepMetadata, NLUMetadata

    manager = OrchestraManager(
        redis_client=fake_redis,
        nlu_engine=nlu_engine,
        state_manager=state_manager,
        health_monitor=health_monitor,
    )

    nlu_result = MultiStepNLUResult(
        type="multi_step",
        intent="검색 후 파일 저장",
        plan=[
            PlanStep(
                step=1, selected_agent="research_agent", action="search_and_report",
                params={"query": "AI 뉴스"}, depends_on=[],
                metadata=PlanStepMetadata(reason="검색", requires_user_approval=False),
            ),
            PlanStep(
                step=2, selected_agent="file_agent", action="write_file",
                params={"path": "/tmp/result.txt", "content": "{{step_1.result.summary}}"},
                depends_on=[1],
                metadata=PlanStepMetadata(reason="파일 저장", requires_user_approval=False),  # LLM은 false
            ),
        ],
        metadata=NLUMetadata(reason="복합 작업", confidence_score=0.9, requires_user_approval=False),
    )

    task = {
        "task_id": "t3",
        "session_id": "user1:api",
        "requester": {"user_id": "user1", "channel_id": "api"},
        "content": "검색해서 저장해줘",
        "source": "api",
    }

    approval_requested_for_actions: list[str] = []

    async def mock_request_approval(result, orig_task):
        # dispatch 메시지에서 액션 추출
        approval_requested_for_actions.append("write_file")
        return False

    manager.request_user_approval = mock_request_approval

    # step1 은 정상 완료, step2 는 승인 거부로 중단
    call_count = 0
    async def mock_execute(agent_name, task_id, dispatch, timeout):
        nonlocal call_count
        call_count += 1
        return {"status": "COMPLETED", "result_data": {"summary": "검색 완료"}, "agent": agent_name}

    manager._execute_agent_task = mock_execute

    for ag in ("research_agent", "file_agent"):
        await health_monitor.register_agent(ag, [], lifecycle_type="ephemeral")
        await fake_redis.hset(f"agent:{ag}:health", mapping={"agent_id": ag, "status": "IDLE"})

    await manager.run_plan(nlu_result, task)

    assert "write_file" in approval_requested_for_actions, \
        "write_file 스텝은 LLM 판단과 무관하게 서버사이드 승인이 요청되어야 한다"
