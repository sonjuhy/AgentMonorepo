"""
SandboxMixin — 에이전트에 격리 코드 실행 기능을 추가하는 Mixin

모든 에이전트 클래스에 상속하면 `execute_code()` 메서드를 즉시 사용할 수 있습니다.
sandbox_agent 서비스가 실행 중이어야 하며, SANDBOX_URL 환경변수로 URL을 지정합니다.

사용 예시:
    class PlanningAgent(SandboxMixin):
        def __init__(self):
            self._init_sandbox()  # SANDBOX_URL 또는 기본값 사용

        async def run_analysis(self, code: str) -> str:
            result = await self.execute_code("python", code, timeout=60)
            return result["stdout"]
"""

from __future__ import annotations

import logging
import os

from .client import SandboxClient, SandboxError
from .models import SandboxResult

logger = logging.getLogger("shared_core.sandbox.mixin")

_SANDBOX_URL_ENV = "SANDBOX_URL"
_DEFAULT_SANDBOX_URL = "http://sandbox-agent:8003"


class SandboxMixin:
    """
    격리 코드 실행 기능을 추가하는 Mixin.

    에이전트 클래스에 상속하고 `_init_sandbox()`를 호출하면
    `execute_code()`로 sandbox_agent에 코드를 실행할 수 있습니다.

    환경변수:
        SANDBOX_URL: sandbox_agent 베이스 URL
                     (기본값: http://sandbox-agent:8003)
    """

    def _init_sandbox(self, sandbox_url: str | None = None) -> None:
        """
        SandboxClient를 초기화합니다. 에이전트 __init__에서 호출하세요.

        Args:
            sandbox_url: 명시적 URL. None이면 SANDBOX_URL 환경변수 → 기본값 순으로 사용.
        """
        url = sandbox_url or os.environ.get(_SANDBOX_URL_ENV, _DEFAULT_SANDBOX_URL)
        self._sandbox_client = SandboxClient(url)
        logger.debug("[SandboxMixin] 초기화 완료 (url=%s)", url)

    async def execute_code(
        self,
        language: str,
        code: str,
        *,
        task_id: str | None = None,
        stdin: str = "",
        timeout: int = 30,
        memory_mb: int = 256,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """
        격리된 환경에서 코드를 실행합니다.

        Args:
            language: 실행 언어 ("python", "javascript", "bash" 등)
            code: 실행할 코드 문자열
            task_id: 추적용 ID (미지정 시 UUID 자동 생성)
            stdin: 표준 입력
            timeout: 실행 제한 시간(초), 최대 300
            memory_mb: 메모리 제한(MB), 최대 4096
            env: 추가 환경 변수

        Returns:
            SandboxResult: stdout, stderr, exit_code, runtime_used, execution_time_ms

        Raises:
            SandboxError: 실행 실패 시
            AttributeError: _init_sandbox() 미호출 시
        """
        if not hasattr(self, "_sandbox_client"):
            raise AttributeError(
                "SandboxMixin을 사용하려면 __init__에서 _init_sandbox()를 먼저 호출하세요."
            )

        return await self._sandbox_client.execute(
            language,
            code,
            task_id=task_id,
            stdin=stdin,
            timeout=timeout,
            memory_mb=memory_mb,
            env=env,
        )

    async def sandbox_health(self) -> dict:
        """sandbox_agent 상태를 확인합니다."""
        if not hasattr(self, "_sandbox_client"):
            raise AttributeError(
                "SandboxMixin을 사용하려면 __init__에서 _init_sandbox()를 먼저 호출하세요."
            )
        return await self._sandbox_client.health()
