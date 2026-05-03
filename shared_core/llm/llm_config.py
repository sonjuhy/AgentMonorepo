"""
에이전트별 LLM 설정 관리.

- LLMConfig: 불변 LLM 설정 값 객체
- load_llm_config_for_agent: 에이전트 이름 기반 환경변수 우선순위 해석
- llm_config_from_dispatch: dispatch 메시지에서 per-call 설정 추출
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    """
    LLM 공급자 설정 값 객체.

    Attributes:
        backend: 공급자 이름 ("gemini" | "claude" | "local" | "openai").
        model:   모델 이름 오버라이드. None이면 공급자 기본값 사용.
        api_key: API 키 오버라이드. None이면 환경변수에서 읽음.
    """
    backend: str = "gemini"
    model: str | None = None
    api_key: str | None = None


def _normalize_agent_name(agent_name: str) -> str:
    """에이전트 이름을 환경변수 접두사 형태로 정규화."""
    return agent_name.upper().replace("-", "_")


def load_llm_config_for_agent(agent_name: str) -> LLMConfig:
    """
    에이전트별 환경변수에서 LLMConfig를 로드합니다.

    우선순위:
    1. {AGENT_NAME}_LLM_BACKEND  (에이전트 전용, 예: ARCHIVE_AGENT_LLM_BACKEND)
    2. LLM_BACKEND               (전역 설정)
    3. "gemini"                  (기본값)

    모델/API키:
    - {AGENT_NAME}_LLM_MODEL
    - {AGENT_NAME}_LLM_API_KEY

    Args:
        agent_name: 에이전트 식별자 (예: "archive_agent", "research-agent").

    Returns:
        해석된 LLMConfig 인스턴스.
    """
    prefix = _normalize_agent_name(agent_name)

    backend_key = f"{prefix}_LLM_BACKEND"
    raw_backend = (
        os.environ.get(backend_key)
        or os.environ.get("LLM_BACKEND", "gemini")
    )
    backend = raw_backend.lower()

    model = os.environ.get(f"{prefix}_LLM_MODEL") or None
    api_key = os.environ.get(f"{prefix}_LLM_API_KEY") or None

    return LLMConfig(backend=backend, model=model, api_key=api_key)


def llm_config_from_dispatch(dispatch_msg: dict) -> LLMConfig | None:
    """
    dispatch 메시지의 llm_config 필드에서 per-call LLMConfig를 추출합니다.

    llm_config 필드가 없거나, backend가 명시되지 않은 경우 None을 반환합니다.

    dispatch 메시지 형식:
        {
            "task_id": "...",
            "llm_config": {
                "backend": "claude",          # 필수
                "model": "claude-haiku-...",  # 선택
                "api_key": "sk-..."           # 선택
            }
        }

    Returns:
        LLMConfig 인스턴스 또는 None.
    """
    raw = dispatch_msg.get("llm_config")
    if not raw or not isinstance(raw, dict):
        return None

    backend = raw.get("backend")
    if not backend:
        return None

    return LLMConfig(
        backend=backend.lower(),
        model=raw.get("model") or None,
        api_key=raw.get("api_key") or None,
    )
