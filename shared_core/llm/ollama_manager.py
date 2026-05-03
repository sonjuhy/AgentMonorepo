"""
OllamaManager — Ollama 서버 생명주기 및 모델 관리

Ollama의 native REST API(/api/*)를 사용합니다.
LocalProvider가 사용하는 OpenAI 호환 엔드포인트(/v1/*)와는 별개입니다.

환경변수:
    OLLAMA_BASE_URL: Ollama 서버 주소 (기본값: http://localhost:11434)
    LOCAL_LLM_MODEL: 사용할 모델 이름 (기본값: llama3.2)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncIterator

import httpx

logger = logging.getLogger("shared_core.llm.ollama_manager")

_DEFAULT_BASE_URL = "http://localhost:11434"
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 30.0
_PULL_READ_TIMEOUT = 600.0  # 대형 모델 다운로드는 오래 걸림


class OllamaManager:
    """
    Ollama 서버 상태 확인 및 모델 관리 클래스.

    사용 예시:
        mgr = OllamaManager()
        await mgr.wait_until_ready(timeout=60)
        await mgr.ensure_model("qwen2.5:7b")
    """

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (
            base_url or os.environ.get("OLLAMA_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/")

    # ── 상태 확인 ────────────────────────────────────────────────────────────────

    async def is_ready(self) -> bool:
        """Ollama 서버가 응답 가능한 상태인지 확인합니다."""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=5.0, pool=5.0)
            ) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def wait_until_ready(self, timeout: int = 60, interval: float = 3.0) -> bool:
        """
        Ollama가 준비될 때까지 대기합니다.

        Args:
            timeout: 최대 대기 시간(초)
            interval: 재시도 간격(초)

        Returns:
            준비 완료 시 True, 타임아웃 시 False
        """
        elapsed = 0.0
        attempt = 0
        while elapsed < timeout:
            if await self.is_ready():
                logger.info("[OllamaManager] 서버 준비 완료 (%s, %.1fs 소요)", self._base_url, elapsed)
                return True
            attempt += 1
            logger.info("[OllamaManager] 서버 대기 중 (시도 %d, %.1fs 경과)...", attempt, elapsed)
            await asyncio.sleep(interval)
            elapsed += interval
        logger.error("[OllamaManager] 서버 준비 타임아웃 (%ds)", timeout)
        return False

    # ── 모델 관리 ────────────────────────────────────────────────────────────────

    async def list_models(self) -> list[str]:
        """
        로컬에 다운로드된 모델 목록을 반환합니다.

        Returns:
            모델 이름 목록 (예: ["qwen2.5:7b", "llama3.2:latest"])
        """
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=5.0, pool=5.0)
            ) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as exc:
            logger.error("[OllamaManager] 모델 목록 조회 실패: %s", exc)
            return []

    async def has_model(self, model: str) -> bool:
        """지정한 모델이 로컬에 존재하는지 확인합니다."""
        models = await self.list_models()
        # "qwen2.5:7b" 와 "qwen2.5" 모두 매칭
        return any(m == model or m.startswith(f"{model}:") for m in models)

    async def ensure_model(self, model: str, pull_timeout: int = 600) -> None:
        """
        모델이 없으면 자동으로 pull합니다.

        Args:
            model: 모델 이름 (예: "qwen2.5:7b")
            pull_timeout: pull 최대 대기 시간(초)

        Raises:
            RuntimeError: pull 실패 시
        """
        if await self.has_model(model):
            logger.info("[OllamaManager] 모델 이미 존재: %s", model)
            return

        logger.info("[OllamaManager] 모델 없음, pull 시작: %s", model)
        await self.pull_model(model, timeout=pull_timeout)

    async def pull_model(self, model: str, timeout: int = 600) -> None:
        """
        Ollama에서 모델을 다운로드합니다. 진행 상황을 로깅합니다.

        Args:
            model: 모델 이름
            timeout: 최대 다운로드 시간(초)

        Raises:
            RuntimeError: pull 실패 또는 타임아웃 시
        """
        logger.info("[OllamaManager] pull 시작: %s (최대 %ds)", model, timeout)
        last_status = ""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_PULL_READ_TIMEOUT, write=10.0, pool=5.0)
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/api/pull",
                    json={"model": model, "stream": True},
                    timeout=timeout,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            import json
                            data = json.loads(line)
                        except Exception:
                            continue

                        status = data.get("status", "")
                        if status != last_status:
                            if "pulling" in status or "downloading" in status:
                                total = data.get("total", 0)
                                completed = data.get("completed", 0)
                                if total > 0:
                                    pct = int(completed / total * 100)
                                    logger.info("[OllamaManager] %s: %s (%d%%)", model, status, pct)
                                else:
                                    logger.info("[OllamaManager] %s: %s", model, status)
                            else:
                                logger.info("[OllamaManager] %s: %s", model, status)
                            last_status = status

                        if data.get("error"):
                            raise RuntimeError(f"Ollama pull 오류: {data['error']}")
                        if status == "success":
                            logger.info("[OllamaManager] pull 완료: %s", model)
                            return

        except httpx.TimeoutException:
            raise RuntimeError(f"모델 pull 타임아웃 ({timeout}s): {model}")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"모델 pull 실패: {model} — {exc}") from exc

        # 스트림이 success 없이 끝난 경우 재확인
        if await self.has_model(model):
            logger.info("[OllamaManager] pull 완료 확인: %s", model)
        else:
            raise RuntimeError(f"pull 완료 후 모델 미확인: {model}")

    async def delete_model(self, model: str) -> bool:
        """로컬 모델을 삭제합니다."""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=5.0, pool=5.0)
            ) as client:
                resp = await client.request(
                    "DELETE",
                    f"{self._base_url}/api/delete",
                    json={"name": model},
                )
                if resp.status_code in (200, 404):
                    logger.info("[OllamaManager] 모델 삭제: %s", model)
                    return True
                return False
        except Exception as exc:
            logger.error("[OllamaManager] 모델 삭제 실패 %s: %s", model, exc)
            return False

    # ── 서버 정보 ────────────────────────────────────────────────────────────────

    async def get_version(self) -> str | None:
        """Ollama 서버 버전을 반환합니다."""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=5.0, pool=5.0)
            ) as client:
                resp = await client.get(f"{self._base_url}/api/version")
                resp.raise_for_status()
                return resp.json().get("version")
        except Exception:
            return None
