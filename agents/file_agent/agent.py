"""
File Agent 구체 구현체
- FileAgentProtocol 구현: read / write / update / delete
- cassiopeia-sdk CassiopeiaClient.listen()으로 오케스트라 디스패치 수신
- 처리 결과를 HTTP POST /results 로 오케스트라에 전송
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import redis.asyncio as aioredis
from cassiopeia_sdk.client import AgentMessage as SdkAgentMessage, CassiopeiaClient

from .config import FileAgentConfig, load_config_from_env
from .interfaces import FileOperationResult
from .validator import PathValidator, PathValidatorProtocol

logger = logging.getLogger("file_agent.agent")

_HEARTBEAT_INTERVAL: int = int(os.environ.get("HEARTBEAT_INTERVAL", "15"))
_HTTP_REPORT_TIMEOUT: float = float(os.environ.get("HTTP_REPORT_TIMEOUT", "10.0"))
_DLQ_KEY = "orchestra:dlq"


class FileAgent:
    """
    FileAgentProtocol의 구체 구현체.
    cassiopeia-sdk를 사용해 오케스트라로부터 태스크 메시지를 수신합니다.
    """

    agent_name: str = "file-agent"

    def __init__(
        self,
        config: FileAgentConfig | None = None,
        validator: PathValidatorProtocol | None = None,
    ) -> None:
        self._config = config or load_config_from_env()
        self._validator = validator or PathValidator()

    async def read_file(self, file_path: Path | str) -> FileOperationResult:
        try:
            path = self._validator.resolve_safe_path(file_path, self._config.allowed_roots)
            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb > self._config.max_file_size_mb:
                return FileOperationResult(status="error", message=f"파일 크기 초과: {size_mb:.1f}MB")
            content = path.read_text(encoding="utf-8")
            return FileOperationResult(status="success", message="읽기 완료", data=content)
        except Exception as e:
            return FileOperationResult(status="error", message=f"읽기 실패: {e}")

    async def write_file(self, file_path: Path | str, content: str, overwrite: bool = False) -> FileOperationResult:
        try:
            path = self._validator.resolve_safe_path(file_path, self._config.allowed_roots)
            if path.exists() and not overwrite:
                return FileOperationResult(status="error", message=f"파일이 이미 존재합니다")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return FileOperationResult(status="success", message=f"쓰기 완료: {path}")
        except Exception as e:
            return FileOperationResult(status="error", message=f"쓰기 실패: {e}")

    async def update_file(self, file_path: Path | str, content: str, append: bool = True) -> FileOperationResult:
        try:
            path = self._validator.resolve_safe_path(file_path, self._config.allowed_roots)
            if not path.exists():
                return FileOperationResult(status="error", message="파일 없음")
            if append:
                with path.open("a", encoding="utf-8") as f: f.write(content)
            else:
                path.write_text(content, encoding="utf-8")
            return FileOperationResult(status="success", message="업데이트 완료")
        except Exception as e:
            return FileOperationResult(status="error", message=f"업데이트 실패: {e}")

    async def delete_file(self, file_path: Path | str) -> FileOperationResult:
        try:
            path = self._validator.resolve_safe_path(file_path, self._config.allowed_roots)
            if not path.exists(): return FileOperationResult(status="error", message="파일 없음")
            path.unlink()
            return FileOperationResult(status="success", message="삭제 완료")
        except Exception as e:
            return FileOperationResult(status="error", message=f"삭제 실패: {e}")

    async def _dispatch(self, action: str, payload: dict) -> FileOperationResult:
        match action:
            case "read_file": return await self.read_file(payload["file_path"])
            case "write_file": return await self.write_file(payload["file_path"], payload["content"], payload.get("overwrite", False))
            case "update_file": return await self.update_file(payload["file_path"], payload["content"], payload.get("append", True))
            case "delete_file": return await self.delete_file(payload["file_path"])
            case _: return FileOperationResult(status="error", message=f"알 수 없는 액션: {action}")

    async def _report_result(
        self,
        orchestra_url: str,
        task_id: str,
        status: str,
        result_data: dict[str, Any],
        error: dict[str, Any] | None,
        redis: aioredis.Redis | None = None,
    ) -> None:
        """처리 결과를 오케스트라 /results 엔드포인트로 전송합니다. 최대 3회 재시도 후 DLQ 저장."""
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
                async with httpx.AsyncClient(timeout=_HTTP_REPORT_TIMEOUT) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                logger.info("[FileAgent] 결과 보고 완료: task_id=%s status=%s", task_id, status)
                return
            except Exception as exc:
                wait = 2 ** attempt
                logger.warning("[FileAgent] 결과 보고 실패 (attempt %d/3): %s — %ds 후 재시도", attempt + 1, exc, wait)
                if attempt < 2:
                    await asyncio.sleep(wait)
        logger.error("[FileAgent] 결과 보고 최종 실패: task_id=%s", task_id)
        if redis:
            try:
                dlq_entry = {**payload, "failed_at": datetime.now(timezone.utc).isoformat(), "reason": "http_report_failed"}
                await redis.rpush(_DLQ_KEY, json.dumps(dlq_entry, ensure_ascii=False))
                logger.warning("[FileAgent] 결과 DLQ 저장: task_id=%s", task_id)
            except Exception as dlq_exc:
                logger.error("[FileAgent] DLQ 저장 실패: %s", dlq_exc)

    async def _handle_task(
        self,
        msg: SdkAgentMessage,
        orchestra_url: str,
        redis: aioredis.Redis | None = None,
    ) -> None:
        """cassiopeia AgentMessage를 처리하고 결과를 오케스트라로 전송합니다.

        payload 구조:
            {
                "task_id": "...",
                "params": { ... }  # 각 액션에 필요한 파라미터
            }
        """
        task_id = msg.payload.get("task_id", "unknown")
        agent_result: dict[str, Any] = {
            "status": "FAILED",
            "result_data": {},
            "error": {"code": "INTERNAL_ERROR", "message": "처리 중 알 수 없는 오류", "traceback": None},
        }
        try:
            action = msg.action
            params = msg.payload.get("params", {})
            logger.info("[FileAgent] 태스크 수신: task_id=%s action=%s", task_id, action)

            op_result = await self._dispatch(action, params)

            if op_result.status == "error":
                agent_result = {
                    "status": "FAILED",
                    "result_data": {},
                    "error": {"code": "EXECUTION_ERROR", "message": op_result.message, "traceback": None},
                }
            else:
                agent_result = {
                    "status": "COMPLETED",
                    "result_data": {
                        "summary": op_result.message,
                        "raw_text": op_result.data or "",
                    },
                    "error": None,
                }

        except asyncio.CancelledError:
            logger.warning("[FileAgent] 태스크 취소됨: task_id=%s", task_id)
            agent_result["error"] = {"code": "CANCELLED", "message": "태스크가 취소되었습니다.", "traceback": None}
            raise
        except Exception as exc:
            logger.error("[FileAgent] 태스크 처리 실패 task_id=%s: %s", task_id, exc)
            agent_result["error"] = {"code": "INTERNAL_ERROR", "message": str(exc), "traceback": None}
        finally:
            try:
                await self._report_result(
                    orchestra_url=orchestra_url,
                    task_id=task_id,
                    status=agent_result.get("status", "FAILED"),
                    result_data=agent_result.get("result_data", {}),
                    error=agent_result.get("error"),
                    redis=redis,
                )
            except Exception as exc:
                logger.error("[FileAgent] 결과 보고 실패 task_id=%s: %s", task_id, exc)

    async def run(self) -> None:
        redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
        if "localhost" in redis_url:
            redis_url = redis_url.replace("localhost", "127.0.0.1")
        orchestra_url = os.environ.get("ORCHESTRA_URL", "http://orchestra-agent:8001")
        health_key = f"agent:{self.agent_name}:health"

        import re
        safe_redis_url = re.sub(r":([^:@]+)@", ":***MASKED***@", redis_url)
        logger.info("[FileAgent] 실행 시작 (Redis: %s, agent: %s)", safe_redis_url, self.agent_name)

        # 하트비트와 DLQ는 직접 Redis 클라이언트 사용
        redis = aioredis.from_url(redis_url, decode_responses=True)

        # 메시지 수신은 cassiopeia-sdk 사용
        cassiopeia = CassiopeiaClient(agent_id=self.agent_name, redis_url=redis_url)
        await cassiopeia.connect()

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
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(5)

        hb_task = asyncio.create_task(heartbeat_loop())

        try:
            async for msg in cassiopeia.listen():
                asyncio.create_task(self._handle_task(msg, orchestra_url, redis))
        except asyncio.CancelledError:
            logger.info("[FileAgent] 종료")
        finally:
            hb_task.cancel()
            await cassiopeia.disconnect()
            await redis.aclose()
            logger.info("[FileAgent] 실행 종료")
