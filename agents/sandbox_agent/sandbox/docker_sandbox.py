"""
Docker 기반 폴백 샌드박스

Firecracker(/dev/kvm)를 사용할 수 없는 환경에서 Docker 컨테이너로 코드를 실행합니다.

격리 정책:
- --network=none: 완전한 네트워크 차단
- --memory: 메모리 제한
- --rm: 실행 후 컨테이너 자동 삭제
- --read-only: 루트 파일시스템 읽기 전용 (--tmpfs /tmp 예외)
- stdin 파이프로 코드 전달 (파일 마운트 불필요)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

from .models import ExecuteRequest, SandboxTaskResult

logger = logging.getLogger("cassiopeia_agent.sandbox.docker_sandbox")

_DOCKER_IMAGE = os.environ.get("SANDBOX_DOCKER_IMAGE", "python:3.12-alpine")

_LANGUAGE_MAP: dict[str, tuple[str, list[str]]] = {
    "python":     (_DOCKER_IMAGE, ["python3", "-c"]),
    "python3":    (_DOCKER_IMAGE, ["python3", "-c"]),
    "javascript": ("node:22-alpine", ["node", "-e"]),
    "js":         ("node:22-alpine", ["node", "-e"]),
    "bash":       ("alpine:3.20", ["sh", "-c"]),
    "sh":         ("alpine:3.20", ["sh", "-c"]),
}
_DEFAULT_INTERPRETER: list[str] = ["sh", "-c"]

# 컨테이너에 전달 허용되는 환경변수 접두사/이름 화이트리스트
_ALLOWED_ENV_PREFIXES = ("SB_", "DATA_", "USER_")
_ALLOWED_ENV_KEYS = frozenset({
    "LANG", "LC_ALL", "PYTHONIOENCODING", "ALLOWED_VAR"
})


class DockerSandbox:
    """Docker 컨테이너 기반 격리 실행 환경."""

    def __init__(self, use_gvisor: bool = False) -> None:
        self.vm_id = str(uuid.uuid4())[:8]
        self._use_gvisor = use_gvisor

    async def execute(self, req: ExecuteRequest) -> SandboxTaskResult:
        cmd = self._build_cmd(req)
        logger.debug("[DockerSandbox] 실행: %s (vm_id=%s)", cmd[:5], self.vm_id)

        start_ms = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdin_bytes = req.stdin.encode("utf-8") if req.stdin else None
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=stdin_bytes),
                    timeout=req.timeout + 5,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                runtime_used: SandboxRuntime = "gvisor" if self._use_gvisor else "docker"
                return SandboxTaskResult(
                    stdout="",
                    stderr="실행 시간 초과",
                    exit_code=124,
                    runtime_used=runtime_used,
                    execution_time_ms=int((time.monotonic() - start_ms) * 1000),
                )

        except Exception as exc:
            logger.error("[DockerSandbox] 실행 실패 (vm_id=%s): %s", self.vm_id, exc)
            raise

        elapsed_ms = int((time.monotonic() - start_ms) * 1000)
        runtime_used: SandboxRuntime = "gvisor" if self._use_gvisor else "docker"
        return SandboxTaskResult(
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            exit_code=proc.returncode or 0,
            runtime_used=runtime_used,
            execution_time_ms=elapsed_ms,
        )

    async def close(self) -> None:
        """no-op — 컨테이너는 --rm으로 자동 삭제됩니다."""

    def _build_cmd(self, req: ExecuteRequest) -> list[str]:
        image, interpreter = _LANGUAGE_MAP.get(
            req.language.lower(),
            (_DOCKER_IMAGE, _DEFAULT_INTERPRETER),
        )

        cmd = [
            "docker", "run",
            "--rm",
            "--network=none",  # 항상 네트워크 차단
            f"--memory={req.memory_mb}m",
            "--memory-swap=0",
            f"--cpus={os.environ.get('SANDBOX_CPUS', '0.5')}",  # CPU 제한 강화
            "--read-only",
            "--tmpfs=/tmp:size=64m",
            "--no-healthcheck",
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
            "--pids-limit=32",  # 프로세스 개수 제한 강화
            "--ulimit", "nproc=32:32",
            "--ulimit", "fsize=10000000:10000000",  # 최대 파일 크기 10MB 제한
            "--user=65534:65534",
            f"--name=sandbox-{self.vm_id}",
        ]

        if self._use_gvisor:
            cmd.insert(2, "--runtime=runsc")

        for key, value in req.env.items():
            # 화이트리스트 검사: 명시적 허용 키 또는 특정 접두사로 시작하는 경우만 허용
            is_allowed = (
                key in _ALLOWED_ENV_KEYS or 
                any(key.startswith(pre) for pre in _ALLOWED_ENV_PREFIXES)
            )
            
            if not is_allowed:
                logger.warning("[DockerSandbox] 허용되지 않은 env 키 무시: %s (vm_id=%s)", key, self.vm_id)
                continue
            cmd += ["-e", f"{key}={value}"]

        cmd += ["-i"]
        cmd += [image] + interpreter + [req.code]
        return cmd
