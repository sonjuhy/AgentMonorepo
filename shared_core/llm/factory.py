"""
LLM 공급자 팩토리.
환경변수 LLM_BACKEND에 따라 적절한 공급자 인스턴스를 반환합니다.
"""

from __future__ import annotations

import os

from .interfaces import LLMProviderProtocol


def build_llm_provider(
    backend: str | None = None,
    model: str | None = None,
) -> LLMProviderProtocol:
    """
    환경변수 LLM_BACKEND에 따라 LLM 공급자 인스턴스를 생성합니다.

    Args:
        backend: 공급자 이름 ("gemini" | "claude" | "local").
                 None이면 LLM_BACKEND 환경변수 사용, 기본값 "gemini".
        model:   모델 이름 오버라이드. None이면 공급자별 환경변수 또는 기본값 사용.

    Returns:
        LLMProviderProtocol을 만족하는 공급자 인스턴스.

    Raises:
        ValueError: 지원하지 않는 backend 이름인 경우.
    """
    selected = (backend or os.environ.get("LLM_BACKEND", "gemini")).lower()

    match selected:
        case "claude":
            from .providers.claude import ClaudeProvider
            return ClaudeProvider(model=model)
        case "local":
            from .providers.local import LocalProvider
            return LocalProvider(model=model)
        case "gemini":
            from .providers.gemini import GeminiProvider
            return GeminiProvider(model=model)
        case _:
            raise ValueError(
                f"지원하지 않는 LLM 백엔드: {selected!r}. "
                f"허용값: 'gemini', 'claude', 'local'"
            )
