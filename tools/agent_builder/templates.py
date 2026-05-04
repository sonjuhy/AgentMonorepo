"""
Agent Builder 템플릿 문자열 모음

모든 템플릿은 <<<VAR_NAME>>> 형식의 플레이스홀더를 사용합니다.
Python 코드 내의 {} 중괄호와 충돌하지 않도록 이 방식을 채택했습니다.

공통 변수:
    <<<SNAKE_NAME>>>   — 에이전트 스네이크 케이스 이름 (예: weather)
    <<<CLASS_NAME>>>   — 에이전트 파스칼 케이스 이름 (예: Weather)
    <<<PORT>>>         — 서버 바인딩 포트 (예: 8010)
    <<<DESCRIPTION>>>  — 에이전트 설명
"""

from __future__ import annotations


def render(template: str, **kwargs: str) -> str:
    """<<<KEY>>> 플레이스홀더를 kwargs 값으로 치환합니다."""
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"<<<{key}>>>", value)
    return result


# ── Python user_code.py 예시 ──────────────────────────────────────────────────

PYTHON_USER_CODE_EXAMPLE = '''\
"""
<<<CLASS_NAME>>> Agent 사용자 코드 — 직접 구현하세요.

규칙:
  - run(params: dict) -> dict 함수를 반드시 구현해야 합니다.
  - params: OrchestraManager가 전달하는 DispatchMessage.params
  - 반환값: AgentResult.result_data에 저장될 dict

예시 파라미터 키는 OrchestraManager와 협의하여 정의하세요.
"""
from __future__ import annotations

from typing import Any


def run(params: dict[str, Any]) -> dict[str, Any]:
    """
    메인 실행 함수. OrchestraManager가 이 함수를 호출합니다.

    Args:
        params: DispatchMessage.params (dict)

    Returns:
        result_data dict
    """
    # TODO: 여기에 로직을 구현하세요
    return {"message": "Hello from <<<CLASS_NAME>>>Agent", "params_received": params}
'''


# ── JavaScript user_code.js 예시 ─────────────────────────────────────────────

JS_USER_CODE_EXAMPLE = '''\
'use strict';

/**
 * <<<CLASS_NAME>>> Agent 사용자 코드 — 직접 구현하세요.
 *
 * 규칙:
 *   - run(params) 함수를 반드시 내보내야 합니다.
 *   - params: OrchestraManager가 전달하는 DispatchMessage.params (Object)
 *   - 반환값: result_data로 사용될 Object 또는 Promise<Object>
 */

/**
 * @param {Object} params - DispatchMessage.params
 * @returns {Object|Promise<Object>} result_data
 */
function run(params) {
    // TODO: 여기에 로직을 구현하세요
    return { message: 'Hello from <<<CLASS_NAME>>>Agent', paramsReceived: params };
}

module.exports = { run };
'''


# ── _js_shim.js (JS → Python 브릿지, 수정 불필요) ────────────────────────────

JS_SHIM = '''\
'use strict';
/**
 * Python js_runner.py가 호출하는 Node.js 브릿지.
 * stdin으로 JSON params를 받아 user_code.js의 run()을 실행하고
 * stdout으로 JSON result를 출력합니다.
 * 수정하지 마세요 — agent-builder가 자동 생성한 파일입니다.
 */
const path = require('path');
const { run } = require(path.join(__dirname, 'user_code'));

let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { raw += chunk; });
process.stdin.on('end', () => {
    const params = JSON.parse(raw || '{}');
    Promise.resolve(run(params))
        .then(result => {
            process.stdout.write(JSON.stringify(result ?? {}));
            process.exit(0);
        })
        .catch(err => {
            process.stderr.write(String(err.stack || err));
            process.exit(1);
        });
});
'''


# ── js_runner.py (Python → Node.js 실행 브릿지) ──────────────────────────────

JS_RUNNER_PY = '''\
"""
JS 코드 실행 브릿지 — 자동 생성 (agent-builder), 수정하지 마세요.
user_code.js를 Node.js 서브프로세스로 실행합니다.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_JS_SHIM = os.path.join(_THIS_DIR, "_js_shim.js")


def run(params: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    """
    user_code.js의 run(params) 함수를 Node.js로 실행합니다.

    Args:
        params: OrchestraManager 파라미터
        timeout: 실행 제한 시간(초)

    Returns:
        result dict

    Raises:
        RuntimeError: JS 실행 실패 시
        FileNotFoundError: Node.js 미설치 시
    """
    proc = subprocess.run(
        ["node", _JS_SHIM],
        input=json.dumps(params),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=_THIS_DIR,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"JS 실행 오류 (exit {proc.returncode}): {proc.stderr}")
    return json.loads(proc.stdout)
'''


# ── agent.py (Python 사용자 코드용) ──────────────────────────────────────────

AGENT_PY_PYTHON = '''\
"""
<<<CLASS_NAME>>> Agent — 자동 생성 (agent-builder)
<<<DESCRIPTION>>>
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .user_code import run as _user_run

logger = logging.getLogger("<<<SNAKE_NAME>>>_agent.agent")


class <<<CLASS_NAME>>>Agent:
    """<<<DESCRIPTION>>>"""

    async def handle_dispatch(self, dispatch_msg: dict[str, Any]) -> dict[str, Any]:
        task_id: str = dispatch_msg.get("task_id", "unknown")
        params: dict[str, Any] = dispatch_msg.get("params", {})
        start_ms = time.monotonic()

        logger.info("[<<<CLASS_NAME>>>Agent] 태스크 수신: task_id=%s", task_id)

        try:
            result = _user_run(params)
            if not isinstance(result, dict):
                result = {"output": result}
        except Exception as exc:
            logger.error("[<<<CLASS_NAME>>>Agent] 실행 실패 task_id=%s: %s", task_id, exc)
            return {
                "task_id": task_id,
                "status": "FAILED",
                "result_data": {},
                "error": {"code": "EXECUTION_ERROR", "message": str(exc), "traceback": None},
                "usage_stats": {},
            }

        elapsed_ms = int((time.monotonic() - start_ms) * 1000)
        logger.info("[<<<CLASS_NAME>>>Agent] 완료: task_id=%s elapsed=%dms", task_id, elapsed_ms)
        return {
            "task_id": task_id,
            "status": "COMPLETED",
            "result_data": result,
            "error": None,
            "usage_stats": {"elapsed_ms": elapsed_ms},
        }
'''


# ── agent.py (JavaScript 사용자 코드용, js_runner 경유) ──────────────────────

AGENT_PY_JS = '''\
"""
<<<CLASS_NAME>>> Agent — 자동 생성 (agent-builder, JavaScript 모드)
<<<DESCRIPTION>>>
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .js_runner import run as _user_run

logger = logging.getLogger("<<<SNAKE_NAME>>>_agent.agent")


class <<<CLASS_NAME>>>Agent:
    """<<<DESCRIPTION>>>"""

    async def handle_dispatch(self, dispatch_msg: dict[str, Any]) -> dict[str, Any]:
        task_id: str = dispatch_msg.get("task_id", "unknown")
        params: dict[str, Any] = dispatch_msg.get("params", {})
        start_ms = time.monotonic()

        logger.info("[<<<CLASS_NAME>>>Agent] 태스크 수신: task_id=%s", task_id)

        try:
            result = _user_run(params)
            if not isinstance(result, dict):
                result = {"output": result}
        except Exception as exc:
            logger.error("[<<<CLASS_NAME>>>Agent] 실행 실패 task_id=%s: %s", task_id, exc)
            return {
                "task_id": task_id,
                "status": "FAILED",
                "result_data": {},
                "error": {"code": "EXECUTION_ERROR", "message": str(exc), "traceback": None},
                "usage_stats": {},
            }

        elapsed_ms = int((time.monotonic() - start_ms) * 1000)
        logger.info("[<<<CLASS_NAME>>>Agent] 완료: task_id=%s elapsed=%dms", task_id, elapsed_ms)
        return {
            "task_id": task_id,
            "status": "COMPLETED",
            "result_data": result,
            "error": None,
            "usage_stats": {"elapsed_ms": elapsed_ms},
        }
'''


# ── models.py ─────────────────────────────────────────────────────────────────

MODELS_PY = '''\
"""
<<<CLASS_NAME>>> Agent 데이터 모델 — 자동 생성 (agent-builder)
에이전트 동작에 맞게 TypedDict 필드를 추가하세요.
"""
from __future__ import annotations

from typing import Any, TypedDict


class <<<CLASS_NAME>>>TaskParams(TypedDict, total=False):
    """OrchestraManager → <<<CLASS_NAME>>>Agent DispatchMessage.params 스키마.
    사용자 정의 파라미터 키를 여기에 추가하세요.
    """


class <<<CLASS_NAME>>>TaskResult(TypedDict, total=False):
    """<<<CLASS_NAME>>>Agent → OrchestraManager AgentResult.result_data 스키마.
    run() 함수가 반환하는 키를 여기에 추가하세요.
    """
'''


# ── protocols.py ──────────────────────────────────────────────────────────────

PROTOCOLS_PY = '''\
"""
<<<CLASS_NAME>>> Agent 프로토콜 인터페이스 — 자동 생성 (agent-builder)
"""
from __future__ import annotations

from typing import Any, Protocol


class <<<CLASS_NAME>>>AgentProtocol(Protocol):
    """<<<CLASS_NAME>>>Agent의 공개 인터페이스."""

    async def handle_dispatch(self, dispatch_msg: dict[str, Any]) -> dict[str, Any]:
        """OrchestraManager DispatchMessage를 처리하고 AgentResult를 반환합니다."""
        ...
'''


# ── redis_listener.py ─────────────────────────────────────────────────────────

REDIS_LISTENER_PY = '''\
"""
<<<CLASS_NAME>>> Agent Redis 리스너 — 자동 생성 (agent-builder)
- OrchestraManager가 agent:<<<SNAKE_NAME>>>:tasks 큐에 push한 DispatchMessage를 BLPOP으로 수신
- <<<CLASS_NAME>>>Agent.handle_dispatch()에 위임 후 orchestra /results로 결과 보고
- agent:<<<SNAKE_NAME>>>:health Redis Hash를 주기적으로 갱신 (HEARTBEAT_INTERVAL 환경변수)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis

from .agent import <<<CLASS_NAME>>>Agent

logger = logging.getLogger("<<<SNAKE_NAME>>>_agent.redis_listener")

_QUEUE_KEY = "agent:<<<SNAKE_NAME>>>:tasks"
_HEALTH_KEY = "agent:<<<SNAKE_NAME>>>:health"
_DLQ_KEY = "orchestra:dlq"
_HEARTBEAT_INTERVAL: int = int(os.environ.get("HEARTBEAT_INTERVAL", "15"))
_BLPOP_TIMEOUT: int = int(os.environ.get("BLPOP_TIMEOUT", "5"))
_HTTP_REPORT_TIMEOUT: float = float(os.environ.get("HTTP_REPORT_TIMEOUT", "10.0"))
_HEALTH_TTL: int = _HEARTBEAT_INTERVAL * 4


class <<<CLASS_NAME>>>RedisListener:
    """OrchestraManager ↔ <<<CLASS_NAME>>>Agent 연결 브릿지."""

    def __init__(
        self,
        agent: <<<CLASS_NAME>>>Agent,
        redis_url: str | None = None,
        orchestra_url: str | None = None,
    ) -> None:
        self._agent = agent
        # 커뮤니티 에이전트는 제한된 권한의 REDIS_COMMUNITY_URL을 우선 사용합니다.
        # REDIS_COMMUNITY_URL은 agent:*:tasks, agent:*:health, orchestra:results:*, orchestra:dlq
        # 키만 접근 가능한 'community' 계정 URL입니다.
        self._redis_url = redis_url or os.environ.get(
            "REDIS_COMMUNITY_URL",
            os.environ.get("REDIS_URL", "redis://localhost:6379"),
        )
        self._orchestra_url = orchestra_url or os.environ.get(
            "ORCHESTRA_URL", "http://orchestra-agent:8001"
        )
        self._redis: aioredis.Redis | None = None
        self._current_task_count: int = 0

    async def _ensure_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    async def listen_tasks(self) -> None:
        redis = await self._ensure_redis()
        logger.info("[<<<CLASS_NAME>>>RedisListener] listen_tasks 시작 (queue: %s)", _QUEUE_KEY)
        try:
            while True:
                result = await redis.blpop(_QUEUE_KEY, timeout=_BLPOP_TIMEOUT)
                if result is None:
                    continue
                _, raw = result
                asyncio.create_task(self.handle_task(raw))
        except asyncio.CancelledError:
            logger.info("[<<<CLASS_NAME>>>RedisListener] listen_tasks 정상 종료")
        except Exception as exc:
            logger.error("[<<<CLASS_NAME>>>RedisListener] listen_tasks 오류: %s", exc)
            raise

    async def handle_task(self, raw: str) -> None:
        task_id = "unknown"
        callback_api_key = os.environ.get("ORCHESTRA_CLIENT_KEY", "")
        agent_result: dict[str, Any] = {
            "task_id": "unknown",
            "status": "FAILED",
            "result_data": {},
            "error": {"code": "INTERNAL_ERROR", "message": "처리 중 알 수 없는 오류", "traceback": None},
            "usage_stats": {},
        }
        try:
            dispatch_msg: dict[str, Any] = json.loads(raw)
            task_id = dispatch_msg.get("task_id", "unknown")
            agent_result["task_id"] = task_id
            # dispatch 메시지 메타데이터에서 콜백 인증 키 추출 (오케스트라가 주입)
            callback_api_key = (
                dispatch_msg.get("metadata", {}).get("callback_api_key")
                or callback_api_key
            )
            logger.info("[<<<CLASS_NAME>>>RedisListener] 태스크 수신: task_id=%s", task_id)
            self._current_task_count += 1
            await self._update_health("BUSY")
            agent_result = await self._agent.handle_dispatch(dispatch_msg)
        except json.JSONDecodeError as exc:
            logger.error("[<<<CLASS_NAME>>>RedisListener] JSON 파싱 실패: %s", exc)
            agent_result.update({
                "error": {"code": "PARSE_ERROR", "message": str(exc), "traceback": None},
            })
        except asyncio.CancelledError:
            logger.warning("[<<<CLASS_NAME>>>RedisListener] 태스크 취소됨: task_id=%s", task_id)
            agent_result.update({
                "error": {"code": "CANCELLED", "message": "태스크가 취소되었습니다.", "traceback": None},
            })
            raise
        except Exception as exc:
            logger.error("[<<<CLASS_NAME>>>RedisListener] 처리 실패 task_id=%s: %s", task_id, exc)
            agent_result.update({
                "error": {"code": "INTERNAL_ERROR", "message": str(exc), "traceback": None},
            })
        finally:
            self._current_task_count = max(0, self._current_task_count - 1)
            if self._current_task_count == 0:
                await self._update_health("IDLE")
            try:
                await self._report_result(
                    task_id=agent_result.get("task_id", task_id),
                    result_data=agent_result.get("result_data", {}),
                    status=agent_result.get("status", "FAILED"),
                    error=agent_result.get("error"),
                    callback_api_key=callback_api_key,
                )
            except Exception as exc:
                logger.error("[<<<CLASS_NAME>>>RedisListener] 결과 보고 실패 task_id=%s: %s", task_id, exc)

    async def _report_result(
        self,
        task_id: str,
        result_data: dict[str, Any],
        status: str,
        error: dict[str, Any] | None,
        callback_api_key: str = "",
    ) -> None:
        payload = {
            "task_id": task_id,
            "status": status,
            "result_data": result_data,
            "error": error,
            "usage_stats": {},
        }
        headers = {"X-API-Key": callback_api_key} if callback_api_key else {}
        url = f"{self._orchestra_url}/results"
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=_HTTP_REPORT_TIMEOUT) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                logger.info(
                    "[<<<CLASS_NAME>>>RedisListener] 결과 보고 완료: task_id=%s status=%s",
                    task_id, status,
                )
                return
            except Exception as exc:
                wait = 2 ** attempt
                logger.warning(
                    "[<<<CLASS_NAME>>>RedisListener] 결과 보고 실패 (attempt %d/3): %s — %ds 후 재시도",
                    attempt + 1, exc, wait,
                )
                if attempt < 2:
                    await asyncio.sleep(wait)
        logger.error("[<<<CLASS_NAME>>>RedisListener] 결과 보고 최종 실패: task_id=%s", task_id)
        try:
            redis = await self._ensure_redis()
            dlq_entry = {**payload, "failed_at": datetime.now(timezone.utc).isoformat(), "reason": "http_report_failed"}
            await redis.rpush(_DLQ_KEY, json.dumps(dlq_entry, ensure_ascii=False))
            logger.warning("[<<<CLASS_NAME>>>RedisListener] 결과 DLQ 저장: task_id=%s", task_id)
        except Exception as dlq_exc:
            logger.error("[<<<CLASS_NAME>>>RedisListener] DLQ 저장 실패: %s", dlq_exc)

    async def _heartbeat_loop(self) -> None:
        logger.info("[<<<CLASS_NAME>>>RedisListener] heartbeat 시작")
        try:
            while True:
                await self._update_health(
                    "BUSY" if self._current_task_count > 0 else "IDLE"
                )
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            logger.info("[<<<CLASS_NAME>>>RedisListener] heartbeat 정상 종료")

    async def _update_health(self, status: str) -> None:
        try:
            redis = await self._ensure_redis()
            await redis.hset(
                _HEALTH_KEY,
                mapping={
                    "agent_id": "<<<SNAKE_NAME>>>-agent",
                    "status": status,
                    "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                    "version": "1.0.0",
                    "current_tasks": str(self._current_task_count),
                },
            )
            await redis.expire(_HEALTH_KEY, _HEALTH_TTL)
        except Exception as exc:
            logger.warning("[<<<CLASS_NAME>>>RedisListener] heartbeat 업데이트 실패: %s", exc)
'''


# ── fastapi_app.py ────────────────────────────────────────────────────────────

FASTAPI_APP_PY = '''\
"""
<<<CLASS_NAME>>> Agent FastAPI 서버 — 자동 생성 (agent-builder)
- GET  /health : 에이전트 상태 조회
- POST /dispatch : Redis 우회 직접 실행 (X-Dispatch-Secret 헤더 인증 필수)
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel

from .agent import <<<CLASS_NAME>>>Agent
from .redis_listener import <<<CLASS_NAME>>>RedisListener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("<<<SNAKE_NAME>>>_agent.fastapi_app")


class _AppContext:
    agent: <<<CLASS_NAME>>>Agent
    listener: <<<CLASS_NAME>>>RedisListener
    listen_task: asyncio.Task[None] | None = None
    heartbeat_task: asyncio.Task[None] | None = None


_ctx = _AppContext()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[Lifespan] <<<CLASS_NAME>>> Agent 서버 시작")
    _ctx.agent = <<<CLASS_NAME>>>Agent()
    _ctx.listener = <<<CLASS_NAME>>>RedisListener(
        agent=_ctx.agent,
        redis_url=os.environ.get("REDIS_URL"),
        orchestra_url=os.environ.get("ORCHESTRA_URL"),
    )
    _ctx.listen_task = asyncio.create_task(
        _ctx.listener.listen_tasks(), name="<<<SNAKE_NAME>>>_listen"
    )
    _ctx.heartbeat_task = asyncio.create_task(
        _ctx.listener._heartbeat_loop(), name="<<<SNAKE_NAME>>>_heartbeat"
    )
    yield
    logger.info("[Lifespan] <<<CLASS_NAME>>> Agent 서버 종료")
    for task in (_ctx.listen_task, _ctx.heartbeat_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    await _ctx.listener.close()


app = FastAPI(
    title="<<<CLASS_NAME>>> Agent",
    version="1.0.0",
    description="<<<DESCRIPTION>>>",
    lifespan=lifespan,
)


_DISPATCH_SECRET_HEADER = APIKeyHeader(name="X-Dispatch-Secret", auto_error=False)
_DISPATCH_SECRET: str = os.environ.get("AGENT_DISPATCH_SECRET", "")


async def _verify_dispatch_secret(
    secret: str | None = Security(_DISPATCH_SECRET_HEADER),
) -> None:
    if not _DISPATCH_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AGENT_DISPATCH_SECRET 환경변수가 설정되지 않아 /dispatch를 사용할 수 없습니다.",
        )
    if not secret or secret != _DISPATCH_SECRET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="유효하지 않은 X-Dispatch-Secret 헤더입니다.",
        )


class DispatchRequest(BaseModel):
    task_id: str
    params: dict[str, Any] = {}


@app.get("/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "agent": "<<<SNAKE_NAME>>>-agent",
        "listen_task_running": _ctx.listen_task is not None and not _ctx.listen_task.done(),
        "heartbeat_running": _ctx.heartbeat_task is not None and not _ctx.heartbeat_task.done(),
        "current_tasks": _ctx.listener._current_task_count,
    }


@app.post("/dispatch", status_code=status.HTTP_202_ACCEPTED,
          dependencies=[Depends(_verify_dispatch_secret)])
async def direct_dispatch(req: DispatchRequest) -> dict[str, Any]:
    """Redis 우회 직접 실행 — X-Dispatch-Secret 헤더 인증 필수."""
    try:
        return await _ctx.agent.handle_dispatch({"task_id": req.task_id, "params": req.params})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "<<<PORT>>>"))
    uvicorn.run(
        "agents.<<<SNAKE_NAME>>>_agent.fastapi_app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
'''


# ── main.py ───────────────────────────────────────────────────────────────────

MAIN_PY = '''\
"""
<<<CLASS_NAME>>> Agent 진입점 — 자동 생성 (agent-builder)

MODE 환경변수:
    server (기본): FastAPI + Redis 리스너 서버 실행
    ephemeral:     단발성 실행 (서브클래스에서 run() 오버라이드 시 사용)
"""
from __future__ import annotations

import asyncio
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("<<<SNAKE_NAME>>>_agent.main")


def main() -> None:
    mode = os.environ.get("MODE", "server").lower()
    if mode == "server":
        import uvicorn
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "<<<PORT>>>"))
        logger.info("<<<CLASS_NAME>>> Agent 서버 시작: %s:%d", host, port)
        uvicorn.run(
            "agents.<<<SNAKE_NAME>>>_agent.fastapi_app:app",
            host=host,
            port=port,
            reload=False,
            log_level="info",
        )
    else:
        logger.warning("ephemeral 모드: handle_dispatch를 직접 호출하세요.")


if __name__ == "__main__":
    main()
'''


# ── __init__.py (생성된 에이전트 패키지) ──────────────────────────────────────

AGENT_INIT_PY = '''\
"""<<<CLASS_NAME>>> Agent — 자동 생성 (agent-builder)"""
'''


# ── requirements.txt ──────────────────────────────────────────────────────────

REQUIREMENTS_TXT = '''\
# 사용자 패키지
<<<PACKAGES_LINES>>>

# 에이전트 인프라 의존성 (수정하지 마세요)
fastapi
uvicorn[standard]
httpx
redis[hiredis]
pydantic>=2.0
'''


# ── package.json (JavaScript 전용) ────────────────────────────────────────────

PACKAGE_JSON = '''\
{
  "name": "<<<SNAKE_NAME>>>-agent",
  "version": "1.0.0",
  "description": "<<<DESCRIPTION>>>",
  "main": "user_code.js",
  "dependencies": {
<<<NPM_DEPS>>>
  }
}
'''


# ── Dockerfile (Python 전용) ──────────────────────────────────────────────────

DOCKERFILE_PYTHON = '''\
# <<<CLASS_NAME>>> Agent Dockerfile — 자동 생성 (agent-builder)
FROM python:3.12-alpine

WORKDIR /app

COPY ./shared_core /app/shared_core
COPY ./agents/<<<SNAKE_NAME>>>_agent /app/agents/<<<SNAKE_NAME>>>_agent

RUN pip install --no-cache-dir -r /app/agents/<<<SNAKE_NAME>>>_agent/requirements.txt

<<<DOCKERFILE_USER_SETUP>>>
CMD ["python", "-m", "agents.<<<SNAKE_NAME>>>_agent.main"]
'''


# ── Dockerfile (JavaScript 전용, Python 인프라 + Node.js) ─────────────────────

DOCKERFILE_JS = '''\
# <<<CLASS_NAME>>> Agent Dockerfile — 자동 생성 (agent-builder, JavaScript 모드)
FROM python:3.12-alpine

# Python 인프라 + Node.js 런타임
RUN apk add --no-cache nodejs npm

WORKDIR /app

COPY ./shared_core /app/shared_core
COPY ./agents/<<<SNAKE_NAME>>>_agent /app/agents/<<<SNAKE_NAME>>>_agent

# Python 의존성
RUN pip install --no-cache-dir -r /app/agents/<<<SNAKE_NAME>>>_agent/requirements.txt

# Node.js 의존성
RUN cd /app/agents/<<<SNAKE_NAME>>>_agent && npm install --production

<<<DOCKERFILE_USER_SETUP>>>
CMD ["python", "-m", "agents.<<<SNAKE_NAME>>>_agent.main"]
'''


# ── docker-compose 스니펫 (출력용) ────────────────────────────────────────────

COMPOSE_SNIPPET = '''\
  <<<SNAKE_NAME>>>_agent:
    build:
      context: .
      dockerfile: agents/<<<SNAKE_NAME>>>_agent/Dockerfile
    image: agentmonorepo-<<<SNAKE_NAME>>>_agent
    environment:
      # 커뮤니티 에이전트는 제한된 권한의 community 계정 URL만 사용합니다 (ACL 적용).
      - REDIS_COMMUNITY_URL=${REDIS_COMMUNITY_URL}
      - ORCHESTRA_URL=${ORCHESTRA_URL:-http://orchestra-agent:8001}
      # 오케스트라 HTTP 콜백 인증 키 (/results, /logs 등 호출 시 X-API-Key 헤더에 사용)
      - ORCHESTRA_CLIENT_KEY=${CLIENT_API_KEY}
      - HOST=0.0.0.0
      - PORT=<<<PORT>>>
      # /dispatch 엔드포인트 보호용 시크릿 (미설정 시 /dispatch 비활성화)
      - AGENT_DISPATCH_SECRET=${AGENT_DISPATCH_SECRET}
    # 커뮤니티 에이전트 포트는 내부 네트워크만 노출합니다 (호스트에 직접 바인딩 금지).
    # 외부 접근이 필요한 경우 리버스 프록시(nginx 등)를 통해 제한적으로 허용하세요.
    expose:
      - "<<<PORT>>>"
<<<COMPOSE_SECURITY>>>
'''
