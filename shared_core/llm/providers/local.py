"""
로컬 OpenAI-호환 LLM 서버 공급자.
Ollama, LM Studio, llama.cpp 등 /v1/chat/completions 엔드포인트를 지원합니다.
openai 패키지 없이 httpx만 사용합니다.
"""

from __future__ import annotations

import logging
import os

import httpx

from ..interfaces import LLMGenerateOptions, LLMUsage

logger = logging.getLogger("shared_core.llm.local")

_DEFAULT_BASE_URL = "http://localhost:11434/v1"
_DEFAULT_MODEL = "llama3.2"
_DEFAULT_MAX_TOKENS = 1024
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 120.0  # 로컬 추론은 느릴 수 있음


class LocalProvider:
    """
    로컬 OpenAI-호환 서버(Ollama, LM Studio 등)를 사용하는 LLM 공급자.

    OpenAI /v1/chat/completions 엔드포인트를 직접 호출합니다.
    openai 패키지 의존성 없이 httpx만 사용합니다.

    환경 변수:
        LOCAL_LLM_BASE_URL: API 기본 URL
            - Ollama:    http://localhost:11434/v1  (기본값)
            - LM Studio: http://localhost:1234/v1
        LOCAL_LLM_MODEL: 모델 이름 (기본값: llama3.2)
        LOCAL_LLM_API_KEY: API 키 (더미 허용, 기본값: "ollama")
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._base_url = (
            base_url or os.environ.get("LOCAL_LLM_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/")
        self._model = model or os.environ.get("LOCAL_LLM_MODEL", _DEFAULT_MODEL)
        self._api_key = api_key or os.environ.get("LOCAL_LLM_API_KEY", "ollama")
        self._endpoint = f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    def _build_payload(
        self,
        prompt: str,
        system_instruction: str | None,
        options: LLMGenerateOptions | None,
    ) -> dict:
        messages: list[dict[str, str]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload: dict = {
            "model": self._model,
            "messages": messages,
            "max_tokens": (
                options.max_tokens
                if options and options.max_tokens is not None
                else _DEFAULT_MAX_TOKENS
            ),
            "stream": False,
        }
        if options and options.temperature is not None:
            payload["temperature"] = options.temperature

        return payload

    async def generate_response(
        self,
        prompt: str,
        system_instruction: str | None = None,
        options: LLMGenerateOptions | None = None,
    ) -> tuple[str, LLMUsage]:
        payload = self._build_payload(prompt, system_instruction, options)
        timeout = httpx.Timeout(
            connect=_CONNECT_TIMEOUT,
            read=_READ_TIMEOUT,
            write=10.0,
            pool=5.0,
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                self._endpoint,
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        text: str = data["choices"][0]["message"]["content"]
        raw_usage = data.get("usage", {})
        usage = LLMUsage(
            prompt_tokens=raw_usage.get("prompt_tokens", 0),
            completion_tokens=raw_usage.get("completion_tokens", 0),
            total_tokens=raw_usage.get("total_tokens", 0),
        )
        logger.debug("[Local/%s] tokens: %d total", self._model, usage.total_tokens)
        return text, usage

    async def validate(self) -> bool:
        """
        로컬 서버 연결 상태를 /v1/models 엔드포인트로 검증합니다.
        Ollama와 LM Studio 모두 이 엔드포인트를 지원합니다.
        """
        models_url = f"{self._base_url}/models"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=_CONNECT_TIMEOUT, read=5.0, write=5.0, pool=5.0)
            ) as client:
                resp = await client.get(models_url, headers=self._headers())
                resp.raise_for_status()
            logger.info("[Local] 연결 검증 성공 (%s)", self._base_url)
            return True
        except Exception as e:
            logger.error("[Local] 연결 검증 실패 (%s): %s", self._base_url, e)
            return False
