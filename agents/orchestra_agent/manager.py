"""
오케스트라 매니저 (OrchestraManager)
- NLU → Plan → Dispatch → Monitor 전체 파이프라인
- Redis agent:orchestra:tasks 큐 BLPOP 메인 루프
- 복합 작업 순차 실행 및 {{step_N.result}} 플레이스홀더 치환
- 사용자 승인 브릿지 (Mediator)
- implementation_spec.md 청사진 기반 구현
  - 보완: wait_for_result → BLPOP 방식 (polling 제거)
  - 보완: 에이전트 결과 큐 → orchestra:results:{task_id} (태스크별 격리)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from .health_monitor import HealthMonitor
from .models import (
    AGENT_TIMEOUT_MAP,
    RETRYABLE_ERROR_CODES,
    AgentResult,
    CommAgentMessage,
    DispatchMessage,
    MultiStepNLUResult,
    NLUResult,
    OrchestraTask,
    PlanStep,
    RetryInfo,
    SingleNLUResult,
)
from .nlu_engine import GeminiNLUEngine, build_nlu_engine
from .state_manager import StateManager

logger = logging.getLogger("orchestra_agent.manager")

# Redis 큐 키
_ORCHESTRA_TASKS_KEY = "agent:orchestra:tasks"
_RESULTS_KEY_PREFIX = "orchestra:results:"
_APPROVAL_KEY_PREFIX = "orchestra:approval:"

# 메시지 버전
_MSG_VERSION = "1.1"

# 승인 대기 최대 시간 (5분)
_APPROVAL_TIMEOUT_SEC = 300


def _build_dispatch_message(
    task_id: str,
    session_id: str,
    agent_name: str,
    action: str,
    params: dict[str, Any],
    requester: dict[str, str],
    timeout: int,
    step_info: dict[str, int] | None = None,
    retry_info: RetryInfo | None = None,
    requires_approval: bool = False,
) -> DispatchMessage:
    """에이전트에 전달할 작업 지시서를 생성합니다."""
    return {
        "version": _MSG_VERSION,
        "task_id": task_id,
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "requester": requester,
        "agent": agent_name,
        "action": action,
        "params": params,
        "retry_info": retry_info or {"count": 0, "max_retries": 3, "reason": None},
        "priority": "MEDIUM",
        "timeout": timeout,
        "metadata": {
            "llm_config": {"model": "gemini-2.0-flash", "temperature": 0.2},
            "step_info": step_info or {},
            "requires_user_approval": requires_approval,
        },
    }


def resolve_placeholders(params: dict[str, Any], results: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """
    {{step_N.result.field}} 형식의 플레이스홀더를 실제 결과로 치환합니다.

    Args:
        params: 플레이스홀더가 포함된 파라미터 딕셔너리.
        results: step 번호 → AgentResult 딕셔너리.

    Returns:
        치환이 완료된 파라미터 딕셔너리.
    """
    params_str = json.dumps(params, ensure_ascii=False)

    def replacer(match: re.Match) -> str:
        step_num = int(match.group(1))
        field_path = match.group(2).split(".")
        value: Any = results.get(step_num, {})
        for key in field_path:
            value = value.get(key, "") if isinstance(value, dict) else ""
        return str(value) if value else ""

    resolved = re.sub(r"\{\{step_(\d+)\.result\.([\w.]+)\}\}", replacer, params_str)
    try:
        return json.loads(resolved)
    except json.JSONDecodeError:
        return params


class OrchestraManager:
    """
    오케스트라 에이전트 메인 관제 클래스.

    역할:
        - agent:orchestra:tasks 큐에서 작업 수신
        - NLU로 의도 파악 및 에이전트 선택
        - 단일 / 복합 작업 라우팅
        - 에이전트 결과 수집 및 사용자 승인 브릿지
        - Circuit Breaker 연동

    환경 변수:
        REDIS_URL: Redis 접속 URL (기본값: redis://localhost:6379)
    """

    def __init__(
        self,
        redis_client: aioredis.Redis | None = None,
        nlu_engine: GeminiNLUEngine | None = None,
        state_manager: StateManager | None = None,
        health_monitor: HealthMonitor | None = None,
    ) -> None:
        if redis_client is not None:
            self._redis = redis_client
        else:
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
            self._redis = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=5.0,
            )

        self._nlu = nlu_engine or build_nlu_engine()
        self._state = state_manager or StateManager(redis_client=self._redis)
        self._health = health_monitor or HealthMonitor(redis_client=self._redis)

    # ── 메인 루프 ─────────────────────────────────────────────────────────────

    async def listen_tasks(self) -> None:
        """
        agent:orchestra:tasks 큐를 BLPOP으로 감시하는 메인 루프입니다.
        각 태스크를 비동기 Task로 독립적으로 처리합니다.
        """
        logger.info("[OrchestraManager] 메인 루프 시작 (queue=%s)", _ORCHESTRA_TASKS_KEY)
        while True:
            try:
                result = await self._redis.blpop(_ORCHESTRA_TASKS_KEY, timeout=5)
                if result is None:
                    continue  # timeout — 계속 대기

                _, raw = result
                task: OrchestraTask = json.loads(raw)
                asyncio.create_task(
                    self._safe_process_task(task),
                    name=f"task-{task.get('task_id', 'unknown')}",
                )

            except asyncio.CancelledError:
                logger.info("[OrchestraManager] 메인 루프 종료")
                break
            except Exception as exc:
                logger.error("[OrchestraManager] 루프 오류: %s", exc)
                await asyncio.sleep(1.0)

    async def _safe_process_task(self, task: OrchestraTask) -> None:
        """process_task의 예외를 포착하여 안전하게 처리합니다."""
        try:
            await self.process_task(task)
        except Exception as exc:
            logger.exception("[OrchestraManager] 태스크 처리 중 예외: task_id=%s: %s",
                             task.get("task_id"), exc)
            await self._send_error_to_user(task, str(exc))

    # ── 태스크 처리 파이프라인 ────────────────────────────────────────────────

    async def process_task(self, task: OrchestraTask) -> None:
        """
        단일 태스크 처리 파이프라인: NLU → Plan → Dispatch → Monitor.

        Args:
            task: 소통 에이전트로부터 수신된 작업 요청.
        """
        task_id = task.get("task_id", "")
        session_id = task.get("session_id", "")
        user_text = task.get("content", "")
        requester = task.get("requester", {})

        logger.info("[Manager] 태스크 처리 시작 task_id=%s session=%s", task_id, session_id)

        # 세션 초기화 및 상태 기록
        await self._state.init_session(
            session_id,
            requester.get("user_id", ""),
            requester.get("channel_id", ""),
        )
        await self._state.add_message(session_id, "user", user_text, provider="slack")
        await self._state.update_task_state(task_id, {
            "status": "PROCESSING",
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # NLU 의도 파악
        context = await self._state.build_context_for_llm(session_id, provider="gemini")
        nlu_result: NLUResult = await self._nlu.analyze(user_text, session_id, context)

        logger.info("[Manager] NLU 결과 type=%s session=%s", nlu_result.type, session_id)

        # 타입별 처리 분기
        if nlu_result.type == "clarification":
            await self._route_clarification(nlu_result, task)

        elif nlu_result.type == "multi_step":
            await self.run_plan(nlu_result, task)

        else:  # single
            await self._route_single(nlu_result, task)  # type: ignore[arg-type]

        # 컨텍스트 요약 (필요 시)
        await self._state.maybe_summarize(session_id)

    async def _route_clarification(self, nlu_result: Any, task: OrchestraTask) -> None:
        """추가 질문 필요 시 소통 에이전트로 전달합니다."""
        question = nlu_result.params.question
        options = nlu_result.params.options
        content = question
        if options:
            content += "\n\n" + "\n".join(f"• {opt}" for opt in options)

        await self._send_to_comm_agent(
            task=task,
            content=content,
            requires_approval=False,
            agent_name="communication_agent",
        )

    async def _route_single(self, nlu_result: SingleNLUResult, task: OrchestraTask) -> None:
        """단일 에이전트 작업을 라우팅합니다."""
        agent_name = nlu_result.selected_agent
        timeout = AGENT_TIMEOUT_MAP.get(agent_name, 300)

        # Circuit Breaker 확인
        if await self._health.check_circuit_breaker(agent_name):
            await self._send_fallback_message(task, agent_name)
            return

        dispatch_task_id = str(uuid.uuid4())
        dispatch = _build_dispatch_message(
            task_id=dispatch_task_id,
            session_id=task["session_id"],
            agent_name=agent_name,
            action=nlu_result.action,
            params=nlu_result.params,
            requester=task["requester"],
            timeout=timeout,
            requires_approval=nlu_result.metadata.requires_user_approval,
        )

        await self._dispatch_to_agent(agent_name, dispatch)
        await self._state.update_task_state(dispatch_task_id, {
            "status": "PENDING",
            "session_id": task["session_id"],
            "agent": agent_name,
        })

        # 결과 수신 대기
        result = await self.wait_for_result(dispatch_task_id, timeout=timeout)
        await self._handle_agent_result(result, task, nlu_result.metadata.requires_user_approval)

    # ── 복합 작업 플래너 ──────────────────────────────────────────────────────

    async def run_plan(self, nlu_result: MultiStepNLUResult, original_task: OrchestraTask) -> None:
        """
        plan 배열의 각 step을 depends_on을 고려하여 순차 실행합니다.

        Args:
            nlu_result: multi_step NLU 결과.
            original_task: 원래 수신된 작업 요청.
        """
        plan = nlu_result.plan
        results: dict[int, dict[str, Any]] = {}
        total_steps = len(plan)

        logger.info("[Manager] 복합 작업 시작: %d단계 session=%s", total_steps, original_task["session_id"])

        for step in sorted(plan, key=lambda s: s.step):
            # 선행 단계 완료 대기
            for dep_step in step.depends_on:
                waited = 0
                while dep_step not in results and waited < 60:
                    await asyncio.sleep(0.5)
                    waited += 0.5
                if dep_step not in results:
                    logger.error("[Manager] 의존 단계 %d 타임아웃 — 복합 작업 중단", dep_step)
                    await self._send_error_to_user(original_task, f"단계 {dep_step} 결과를 받지 못했습니다.")
                    return

            # 플레이스홀더 치환
            params = resolve_placeholders(step.params, results)

            # Circuit Breaker 확인
            if await self._health.check_circuit_breaker(step.selected_agent):
                await self._send_fallback_message(original_task, step.selected_agent)
                return

            # 단계 실행
            dispatch_task_id = str(uuid.uuid4())
            timeout = AGENT_TIMEOUT_MAP.get(step.selected_agent, 300)
            dispatch = _build_dispatch_message(
                task_id=dispatch_task_id,
                session_id=original_task["session_id"],
                agent_name=step.selected_agent,
                action=step.action,
                params=params,
                requester=original_task["requester"],
                timeout=timeout,
                step_info={"current": step.step, "total": total_steps},
                requires_approval=step.metadata.requires_user_approval,
            )

            # 진행 상황 알림
            await self._send_progress_to_comm(
                original_task,
                percent=int((step.step - 1) / total_steps * 100),
                message=f"[{step.step}/{total_steps}] {step.selected_agent} 작업 중...",
            )

            await self._dispatch_to_agent(step.selected_agent, dispatch)
            result = await self.wait_for_result(dispatch_task_id, timeout=timeout)
            results[step.step] = result.get("result_data", {})

            # 실패 처리
            if result.get("status") == "FAILED":
                error_msg = result.get("error", {}).get("message", "알 수 없는 오류")
                logger.error("[Manager] 단계 %d 실패: %s", step.step, error_msg)
                await self._health.record_failure(step.selected_agent)
                await self._send_error_to_user(
                    original_task,
                    f"단계 {step.step} ({step.selected_agent}) 실패: {error_msg}",
                )
                return

            await self._health.record_success(step.selected_agent)

            # 승인 필요 단계 처리
            if step.metadata.requires_user_approval:
                approved = await self.request_user_approval(result, original_task)
                if not approved:
                    await self.notify_cancellation(original_task)
                    return

        # 최종 결과 전달
        final_result_data = results.get(plan[-1].step, {})
        summary = final_result_data.get("summary", "모든 단계가 완료되었습니다.")
        body = final_result_data.get("raw_text", "")
        content = f"{summary}\n\n{body}".strip() if body else summary

        await self._send_to_comm_agent(
            task=original_task,
            content=content,
            requires_approval=False,
            agent_name="orchestra",
        )

    # ── 결과 수집 ─────────────────────────────────────────────────────────────

    async def wait_for_result(self, task_id: str, timeout: int = 600) -> dict[str, Any]:
        """
        orchestra:results:{task_id} 큐에서 BLPOP으로 결과를 대기합니다.

        명세서 보완: polling(asyncio.sleep(1)) 대신 BLPOP 사용으로 즉시 수신.

        Args:
            task_id: 대기할 태스크 ID.
            timeout: 최대 대기 시간 (초).

        Returns:
            AgentResult 딕셔너리. 타임아웃 시 FAILED 상태 반환.
        """
        key = f"{_RESULTS_KEY_PREFIX}{task_id}"
        remaining = timeout

        while remaining > 0:
            wait_sec = min(5, remaining)  # 최대 5초 단위로 BLPOP
            result = await self._redis.blpop(key, timeout=wait_sec)
            if result:
                _, raw = result
                data: dict[str, Any] = json.loads(raw)
                logger.info("[Manager] 결과 수신 task_id=%s status=%s", task_id, data.get("status"))
                return data
            remaining -= wait_sec

        logger.warning("[Manager] 결과 타임아웃 task_id=%s timeout=%ds", task_id, timeout)
        return {
            "task_id": task_id,
            "status": "FAILED",
            "result_data": {},
            "error": {"code": "TIMEOUT", "message": f"{timeout}초 내 응답 없음", "traceback": None},
            "usage_stats": {},
        }

    async def receive_agent_result(self, result: AgentResult) -> None:
        """
        하위 에이전트로부터 HTTP를 통해 결과를 수신하여
        orchestra:results:{task_id} 큐에 push합니다.

        FastAPI POST /results 엔드포인트에서 호출됩니다.

        Args:
            result: 에이전트 실행 결과.
        """
        task_id = result["task_id"]
        key = f"{_RESULTS_KEY_PREFIX}{task_id}"
        await self._redis.rpush(key, json.dumps(result, ensure_ascii=False))
        await self._state.update_task_state(task_id, {"status": result["status"]})
        logger.info("[Manager] 결과 저장 task_id=%s status=%s", task_id, result["status"])

    # ── 에이전트 결과 처리 ────────────────────────────────────────────────────

    async def _handle_agent_result(
        self,
        result: dict[str, Any],
        task: OrchestraTask,
        requires_approval: bool,
    ) -> None:
        """단일 작업 결과를 처리합니다 (소통 에이전트 전달 또는 승인 요청)."""
        status = result.get("status", "FAILED")
        agent_name = result.get("agent", "에이전트")

        if status == "FAILED":
            error_msg = result.get("error", {}).get("message", "알 수 없는 오류")
            await self._health.record_failure(agent_name)
            await self._send_error_to_user(task, error_msg)
            return

        await self._health.record_success(agent_name)

        result_data = result.get("result_data", {})
        summary = result_data.get("summary", "작업이 완료되었습니다.")
        body = result_data.get("raw_text", "")
        content = f"{summary}\n\n{body}".strip() if body else summary

        if requires_approval:
            approved = await self.request_user_approval(result, task)
            if not approved:
                await self.notify_cancellation(task)
                return

        await self._send_to_comm_agent(
            task=task,
            content=content,
            requires_approval=False,
            agent_name=agent_name,
        )

    # ── 사용자 승인 브릿지 ────────────────────────────────────────────────────

    async def request_user_approval(
        self,
        result: dict[str, Any],
        original_task: OrchestraTask,
    ) -> bool:
        """
        소통 에이전트로 승인 요청을 발송하고 사용자 응답을 대기합니다.

        승인 응답은 orchestra:approval:{approval_task_id} 큐로 수신됩니다.
        (소통 에이전트의 push_approval이 task별 큐에 push)

        Args:
            result: 승인 대상 에이전트 결과.
            original_task: 원래 수신된 작업 요청.

        Returns:
            True: 승인, False: 거절/취소/타임아웃
        """
        approval_task_id = str(uuid.uuid4())
        result_data = result.get("result_data", {})
        summary = result_data.get("summary", "결과를 확인해 주세요.")
        content = f"*승인이 필요한 작업이 완료되었습니다.*\n\n{summary}"

        # 소통 에이전트로 승인 요청 메시지 전달
        approval_msg: CommAgentMessage = {
            "task_id": approval_task_id,
            "content": content,
            "requires_user_approval": True,
            "agent_name": result.get("agent", "에이전트"),
            "progress_percent": None,
        }
        await self._redis.rpush(
            "agent:communication:tasks",
            json.dumps(approval_msg, ensure_ascii=False),
        )
        logger.info("[Manager] 승인 요청 발송 approval_task_id=%s", approval_task_id)

        # 사용자 응답 대기 (최대 5분)
        approval_key = f"{_APPROVAL_KEY_PREFIX}{approval_task_id}"
        resp_raw = await self._redis.blpop(approval_key, timeout=_APPROVAL_TIMEOUT_SEC)

        if not resp_raw:
            logger.warning("[Manager] 승인 타임아웃 approval_task_id=%s", approval_task_id)
            return False

        _, raw = resp_raw
        resp = json.loads(raw)
        action = resp.get("action", "cancel")
        logger.info("[Manager] 승인 응답 수신 action=%s", action)
        return action == "approve"

    async def notify_cancellation(self, original_task: OrchestraTask) -> None:
        """작업 취소를 사용자에게 알립니다."""
        await self._send_to_comm_agent(
            task=original_task,
            content="✋ 작업이 취소되었습니다.",
            requires_approval=False,
            agent_name="orchestra",
        )

    # ── 내부 유틸리티 ─────────────────────────────────────────────────────────

    async def _dispatch_to_agent(self, agent_name: str, dispatch: DispatchMessage) -> None:
        """에이전트 큐에 작업 지시서를 전달합니다."""
        queue_key = f"agent:{agent_name}:tasks"
        await self._redis.rpush(queue_key, json.dumps(dispatch, ensure_ascii=False))
        logger.info("[Manager] 디스패치 → %s task_id=%s", agent_name, dispatch["task_id"])

    async def _send_to_comm_agent(
        self,
        task: OrchestraTask,
        content: str,
        requires_approval: bool,
        agent_name: str,
    ) -> None:
        """소통 에이전트로 최종 메시지를 전달합니다."""
        comm_task_id = str(uuid.uuid4())
        msg: CommAgentMessage = {
            "task_id": comm_task_id,
            "content": content,
            "requires_user_approval": requires_approval,
            "agent_name": agent_name,
            "progress_percent": None,
        }
        await self._redis.rpush("agent:communication:tasks", json.dumps(msg, ensure_ascii=False))
        logger.debug("[Manager] 소통 에이전트 전달 task_id=%s", comm_task_id)

    async def _send_progress_to_comm(
        self,
        task: OrchestraTask,
        percent: int,
        message: str,
    ) -> None:
        """진행 상황을 소통 에이전트로 전달합니다."""
        comm_task_id = str(uuid.uuid4())
        msg: CommAgentMessage = {
            "task_id": comm_task_id,
            "content": message,
            "requires_user_approval": False,
            "agent_name": "orchestra",
            "progress_percent": percent,
        }
        await self._redis.rpush("agent:communication:tasks", json.dumps(msg, ensure_ascii=False))

    async def _send_error_to_user(self, task: OrchestraTask, error_message: str) -> None:
        """에러 메시지를 사용자에게 전달합니다."""
        await self._send_to_comm_agent(
            task=task,
            content=f"❌ 오류가 발생했습니다.\n\n{error_message}",
            requires_approval=False,
            agent_name="orchestra",
        )

    async def _send_fallback_message(self, task: OrchestraTask, agent_name: str) -> None:
        """Circuit Breaker로 차단된 에이전트에 대한 안내 메시지를 전달합니다."""
        await self._send_to_comm_agent(
            task=task,
            content=f"⚠️ *{agent_name}* 에이전트가 일시적으로 사용 불가 상태입니다. 잠시 후 다시 시도해 주세요.",
            requires_approval=False,
            agent_name="orchestra",
        )
