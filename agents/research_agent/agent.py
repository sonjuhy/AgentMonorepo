"""
Research Agent 구체 구현체
- 웹 검색 및 정보 수집
- Redis BLPOP으로 오케스트라 디스패치 수신
- 처리 결과를 HTTP POST /results 로 오케스트라에 전송
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis

from .config import ResearchAgentConfig, load_config_from_env
from .providers import SearchProviderProtocol, build_provider

logger = logging.getLogger("research_agent.agent")

_HEARTBEAT_INTERVAL = 15
_BLPOP_TIMEOUT = 5


class ResearchAgent:
    agent_name: str = "research-agent"

    def __init__(self, config: ResearchAgentConfig | None = None, provider: SearchProviderProtocol | None = None) -> None:
        self._config = config or load_config_from_env()
        self._provider = provider or build_provider(self._config)

    async def investigate(self, query: str) -> str:
        try:
            return await self._provider.search(query)
        except Exception as e:
            return f"검색 중 오류 발생: {e}"

    async def _dispatch(self, action: str, payload: dict) -> dict[str, Any]:
        if action == "investigate":
            result_text = await self.investigate(payload.get("query", ""))
            return {"status": "success", "data": result_text}
        return {"status": "error", "message": f"알 수 없는 액션: {action}"}

    async def _report_result(
        self,
        orchestra_url: str,
        task_id: str,
        status: str,
        result_data: dict[str, Any],
        error: dict[str, Any] | None,
    ) -> None:
        """처리 결과를 오케스트라 /results 엔드포인트로 전송합니다. 최대 3회 재시도."""
        payload = {
            "task_id": task_id,
            "agent": self.agent_name,
            "status": status,
            "result_data": result_data,
            "error": error,
            "usage_stats": {},
        }
        url = f"{orchestra_url}/results"
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                logger.info("[ResearchAgent] 결과 보고 완료: task_id=%s status=%s", task_id, status)
                return
            except Exception as exc:
                wait = 2 ** attempt
                logger.warning("[ResearchAgent] 결과 보고 실패 (attempt %d/3): %s — %ds 후 재시도", attempt + 1, exc, wait)
                if attempt < 2:
                    await asyncio.sleep(wait)
        logger.error("[ResearchAgent] 결과 보고 최종 실패: task_id=%s", task_id)

    async def _handle_task(self, raw: str, orchestra_url: str) -> None:
        """BLPOP으로 수신한 DispatchMessage를 처리하고 결과를 오케스트라로 전송합니다."""
        task_id = "unknown"
        agent_result: dict[str, Any] = {
            "status": "FAILED",
            "result_data": {},
            "error": {"code": "INTERNAL_ERROR", "message": "처리 중 알 수 없는 오류", "traceback": None},
        }
        try:
            dispatch_msg: dict[str, Any] = json.loads(raw)
            task_id = dispatch_msg.get("task_id", "unknown")
            action = dispatch_msg.get("action", "")
            params = dispatch_msg.get("params", {})
            logger.info("[ResearchAgent] 태스크 수신: task_id=%s action=%s", task_id, action)

            result = await self._dispatch(action, params)

            if result.get("status") == "error":
                agent_result = {
                    "status": "FAILED",
                    "result_data": {},
                    "error": {"code": "EXECUTION_ERROR", "message": result.get("message", "실행 오류"), "traceback": None},
                }
            else:
                raw_text = result.get("data", "")
                # 하이브리드 아키텍처: 대용량 원문을 로컬에 저장하고 reference_id 발급
                ref_id = await self._storage.save_data(
                    data={"raw_text": raw_text},
                    metadata={"action": action, "task_id": task_id}
                )
                summary = f"{action} 완료 (길이: {len(raw_text)}자)"

                agent_result = {
                    "status": "COMPLETED",
                    "result_data": {
                        "summary": summary,
                    },
                    "reference_id": ref_id,
                    "payload_summary": summary,
                    "error": None,
                }

        except asyncio.CancelledError:
            logger.warning("[ResearchAgent] 태스크 취소됨: task_id=%s", task_id)
            agent_result["error"] = {"code": "CANCELLED", "message": "태스크가 취소되었습니다.", "traceback": None}
            raise
        except Exception as exc:
            logger.error("[ResearchAgent] 태스크 처리 실패 task_id=%s: %s", task_id, exc)
            agent_result["error"] = {"code": "INTERNAL_ERROR", "message": str(exc), "traceback": None}
        finally:
            try:
                await self._report_result(
                    orchestra_url=orchestra_url,
                    task_id=task_id,
                    status=agent_result.get("status", "FAILED"),
                    result_data=agent_result.get("result_data", {}),
                    error=agent_result.get("error"),
                    reference_id=agent_result.get("reference_id"),
                    payload_summary=agent_result.get("payload_summary"),
                )
            except Exception as exc:
                logger.error("[ResearchAgent] 결과 보고 실패 task_id=%s: %s", task_id, exc)

    async def run(self) -> None:
        redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
        if "localhost" in redis_url: redis_url = redis_url.replace("localhost", "127.0.0.1")
        orchestra_url = os.environ.get("ORCHESTRA_URL", "http://orchestra-agent:8001")
        queue_key = f"agent:{self.agent_name}:tasks"
        health_key = f"agent:{self.agent_name}:health"

        logger.info("[ResearchAgent] 실행 시작 (Redis: %s, queue: %s)", redis_url, queue_key)

        redis = aioredis.from_url(redis_url, decode_responses=True)

        async def heartbeat_loop():
            while True:
                try:
                    await redis.hset(health_key, mapping={
                        "status": "IDLE",
                        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                        "version": "1.0.0"
                    })
                    await redis.expire(health_key, 60)
                    await asyncio.sleep(_HEARTBEAT_INTERVAL)
                except asyncio.CancelledError: break
                except Exception: await asyncio.sleep(5)

        hb_task = asyncio.create_task(heartbeat_loop())

        try:
            while True:
                result = await redis.blpop(queue_key, timeout=_BLPOP_TIMEOUT)
                if result is None:
                    continue
                _, raw = result
                asyncio.create_task(self._handle_task(raw, orchestra_url))
        except asyncio.CancelledError:
            logger.info("[ResearchAgent] 종료")
        finally:
            hb_task.cancel()
            await redis.aclose()
            logger.info("[ResearchAgent] 실행 종료")
