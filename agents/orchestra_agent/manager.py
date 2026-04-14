"""
오케스트라 매니저 (OrchestraManager)
- NLU → Plan → Dispatch → Monitor 전체 파이프라인
- Redis agent:orchestra:tasks 큐 수신 및 세션/스레드 기반 컨텍스트 관리
- SQLite 영구 저장소 연동 (StateManager)
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

# Redis 설정
_ORCHESTRA_TASKS_KEY = "agent:orchestra:tasks"
_RESULTS_KEY_PREFIX = "orchestra:results:"
_APPROVAL_KEY_PREFIX = "orchestra:approval:"
_MSG_VERSION = "1.1"
_APPROVAL_TIMEOUT_SEC = 300

# 플랫폼별 통신 큐 (source → queue key)
_PLATFORM_COMM_QUEUE: dict[str, str] = {
    "slack": "agent:communication:tasks",
    "discord": "agent:communication:discord:tasks",
    "telegram": "agent:communication:telegram:tasks",
}
_DEFAULT_COMM_QUEUE = "agent:communication:tasks"


def _build_dispatch_message(
    task_id: str,
    session_id: str,
    agent_name: str,
    action: str,
    params: dict[str, Any],
    requester: dict[str, str],
    timeout: int,
    content: str = "",
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
        "content": content,
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
    """{{step_N.result.field}} 형식의 플레이스홀더를 실제 결과로 치환합니다."""
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
            redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
            self._redis = aioredis.from_url(redis_url, decode_responses=True, socket_timeout=5.0)

        self._nlu = nlu_engine or build_nlu_engine()
        self._state = state_manager or StateManager(redis_client=self._redis)
        self._health = health_monitor or HealthMonitor(redis_client=self._redis)

    async def listen_tasks(self) -> None:
        """메인 루프: Redis 큐에서 작업을 수신합니다."""
        logger.info("[OrchestraManager] 메인 루프 시작")
        while True:
            try:
                result = await self._redis.blpop(_ORCHESTRA_TASKS_KEY, timeout=5)
                if result is None: continue

                _, raw = result
                task: OrchestraTask = json.loads(raw)
                asyncio.create_task(self._safe_process_task(task))
            except asyncio.CancelledError: break
            except Exception as exc:
                logger.error("[OrchestraManager] 루프 오류: %s", exc)
                await asyncio.sleep(1.0)

    async def _safe_process_task(self, task: OrchestraTask) -> None:
        try:
            await self.process_task(task)
        except Exception as exc:
            logger.exception("[OrchestraManager] 태스크 처리 실패: %s", exc)
            await self._send_error_to_user(task, str(exc))

    async def process_task(self, task: OrchestraTask) -> None:
        """NLU → Plan → Dispatch → Monitor 파이프라인"""
        user_text = task.get("content", "")
        requester = task.get("requester", {})
        user_id = requester.get("user_id", "unknown")
        channel_id = requester.get("channel_id", "unknown")
        thread_id = requester.get("thread_ts")
        session_id = thread_id if thread_id else task.get("session_id", str(uuid.uuid4()))
        task_id = task.get("task_id", str(uuid.uuid4()))

        await self._state.init_session(session_id, user_id, channel_id)
        await self._state.add_message(session_id, user_id, "user", user_text, provider="slack", thread_id=thread_id)
        
        await self._state.update_task_state(task_id, {"status": "PROCESSING", "session_id": session_id})

        context = await self._state.build_context_for_llm(session_id, user_id)
        summary_data = await self._state.get_session_context_summary(session_id)

        # 활성 에이전트 캐퍼빌리티를 Redis에서 동적으로 로드 (미등록 시 NLU 엔진 내부 폴백 사용)
        agent_capabilities = await self._health.get_nlu_capabilities() or None

        nlu_result: NLUResult = await self._nlu.analyze(
            user_text, session_id, context,
            style_guide=summary_data.get("style"),
            agent_capabilities=agent_capabilities,
        )

        if nlu_result.type == "direct_response":
            await self._send_to_comm_agent(task, nlu_result.params["answer"], False, "orchestra")
        elif nlu_result.type == "clarification":
            await self._route_clarification(nlu_result, task)
        elif nlu_result.type == "multi_step":
            await self.run_plan(nlu_result, task)
        else:
            await self._route_single(nlu_result, task)

    async def _route_clarification(self, nlu_result: Any, task: OrchestraTask) -> None:
        content = nlu_result.params.question
        if nlu_result.params.options:
            content += "\n\n" + "\n".join(f"• {opt}" for opt in nlu_result.params.options)
        await self._send_to_comm_agent(task, content, False, "communication_agent")

    async def _route_single(self, nlu_result: SingleNLUResult, task: OrchestraTask) -> None:
        agent_name = nlu_result.selected_agent
        dispatch_task_id = str(uuid.uuid4())

        ready, reason = await self._health.is_agent_ready(agent_name)
        if not ready:
            await self._send_agent_unavailable_error(task, agent_name, reason)
            return

        timeout = AGENT_TIMEOUT_MAP.get(agent_name, 300)
        dispatch = _build_dispatch_message(
            dispatch_task_id, task["session_id"], agent_name, nlu_result.action,
            nlu_result.params, task["requester"], timeout, content=task.get("content", ""),
            requires_approval=nlu_result.metadata.requires_user_approval
        )

        await self._dispatch_to_agent(agent_name, dispatch)
        result = await self.wait_for_result(dispatch_task_id, timeout=timeout)
        await self._handle_agent_result(result, task, nlu_result.metadata.requires_user_approval)

    async def run_plan(self, nlu_result: MultiStepNLUResult, original_task: OrchestraTask) -> None:
        plan = nlu_result.plan
        results: dict[int, dict[str, Any]] = {}
        total_steps = len(plan)

        for step in sorted(plan, key=lambda s: s.step):
            params = resolve_placeholders(step.params, results)
            dispatch_task_id = str(uuid.uuid4())
            timeout = AGENT_TIMEOUT_MAP.get(step.selected_agent, 300)
            
            dispatch = _build_dispatch_message(
                dispatch_task_id, original_task["session_id"], step.selected_agent,
                step.action, params, original_task["requester"], timeout,
                content=original_task.get("content", ""),
                step_info={"current": step.step, "total": total_steps},
                requires_approval=step.metadata.requires_user_approval
            )

            await self._send_progress_to_comm(original_task, int((step.step-1)/total_steps*100), f"[{step.step}/{total_steps}] {step.selected_agent} 작업 중...")
            await self._dispatch_to_agent(step.selected_agent, dispatch)
            result = await self.wait_for_result(dispatch_task_id, timeout=timeout)
            
            if result.get("status") == "FAILED":
                await self._send_error_to_user(original_task, result.get("error", {}).get("message", "오류"), step.selected_agent)
                return

            results[step.step] = result.get("result_data", {})
            if step.metadata.requires_user_approval:
                if not await self.request_user_approval(result, original_task): return

        final_res = results.get(plan[-1].step, {})
        summary = final_res.get("summary", "모든 단계가 완료되었습니다.")
        content = final_res.get("content", "")
        full_message = f"{summary}\n\n{content}".strip() if content else summary
        await self._send_to_comm_agent(original_task, full_message, False, "orchestra")

    async def wait_for_result(self, task_id: str, timeout: int = 600) -> dict[str, Any]:
        key = f"{_RESULTS_KEY_PREFIX}{task_id}"
        remaining = timeout
        while remaining > 0:
            res = await self._redis.blpop(key, timeout=min(5, remaining))
            if res: return json.loads(res[1])
            remaining -= 5
        return {"status": "FAILED", "error": {"message": "타임아웃"}}

    async def receive_agent_result(self, result: AgentResult) -> None:
        task_id = result["task_id"]
        await self._redis.rpush(f"{_RESULTS_KEY_PREFIX}{task_id}", json.dumps(result, ensure_ascii=False))

    async def _handle_agent_result(self, result: dict[str, Any], task: OrchestraTask, requires_approval: bool) -> None:
        if result.get("status") == "FAILED":
            await self._send_error_to_user(task, result.get("error", {}).get("message", "오류"), result.get("agent"))
            return
        
        res_data = result.get("result_data", {})
        summary = res_data.get("summary", "작업 완료")
        content = res_data.get("content", "")
        full_message = f"{summary}\n\n{content}".strip() if content else summary

        if requires_approval:
            if not await self.request_user_approval(result, task): return
        await self._send_to_comm_agent(task, full_message, False, result.get("agent", "agent"))

    def _get_comm_queue(self, task: OrchestraTask) -> str:
        """태스크의 source 필드를 기반으로 플랫폼별 통신 큐 키를 반환합니다."""
        source = task.get("source", "slack")
        return _PLATFORM_COMM_QUEUE.get(source, _DEFAULT_COMM_QUEUE)

    async def request_user_approval(self, result: dict[str, Any], task: OrchestraTask) -> bool:
        approval_id = str(uuid.uuid4())
        msg: CommAgentMessage = {"task_id": approval_id, "content": f"승인 필요: {result.get('result_data', {}).get('summary')}", "requires_user_approval": True, "agent_name": result.get("agent")}
        comm_queue = self._get_comm_queue(task)
        await self._redis.rpush(comm_queue, json.dumps(msg, ensure_ascii=False))
        res = await self._redis.blpop(f"{_APPROVAL_KEY_PREFIX}{approval_id}", timeout=_APPROVAL_TIMEOUT_SEC)
        return json.loads(res[1]).get("action") == "approve" if res else False

    async def _dispatch_to_agent(self, agent_name: str, dispatch: DispatchMessage) -> None:
        await self._redis.rpush(f"agent:{agent_name}:tasks", json.dumps(dispatch, ensure_ascii=False))

    async def _send_to_comm_agent(self, task: OrchestraTask, content: str, requires_approval: bool, agent_name: str) -> None:
        req = task.get("requester", {})
        session_id = req.get("thread_ts") or task.get("session_id")
        if session_id:
            await self._state.add_message(session_id, req.get("user_id", "unknown"), "assistant", content, provider="orchestra")

        msg: CommAgentMessage = {"task_id": task.get("task_id", str(uuid.uuid4())), "content": content, "requires_user_approval": requires_approval, "agent_name": agent_name}
        comm_queue = self._get_comm_queue(task)
        await self._redis.rpush(comm_queue, json.dumps(msg, ensure_ascii=False))

    async def _send_progress_to_comm(self, task: OrchestraTask, percent: int, message: str) -> None:
        msg: CommAgentMessage = {"task_id": task.get("task_id", str(uuid.uuid4())), "content": message, "requires_user_approval": False, "agent_name": "orchestra", "progress_percent": percent}
        comm_queue = self._get_comm_queue(task)
        await self._redis.rpush(comm_queue, json.dumps(msg, ensure_ascii=False))

    async def _send_error_to_user(self, task: OrchestraTask, error_message: str, agent_name: str = "orchestra") -> None:
        content = f"[{agent_name}] 오류: {error_message}"
        await self._send_to_comm_agent(task, content, False, agent_name)

    async def _send_agent_unavailable_error(self, task: OrchestraTask, agent_name: str, reason: str) -> None:
        await self._send_error_to_user(task, f"에이전트 {agent_name} 사용 불가 ({reason})")
