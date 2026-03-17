"""
LLM 기반 에이전트 라우터/분류기
- python-strict-typing 전략: Protocol 기반 다형성
- Claude API, Gemini API, Claude CLI, Gemini CLI 구현체 제공
"""

import asyncio
import os
from typing import Protocol

from ..models import AGENT_REGISTRY, AgentName, SlackEvent

_FALLBACK_AGENT: AgentName = "planning_agent"

_SYSTEM_PROMPT_TEMPLATE = """당신은 사용자 메시지를 분석하여 처리할 에이전트를 선택하는 라우터입니다.

사용 가능한 에이전트 목록:
{agents_description}

규칙:
1. 메시지 내용을 분석하여 가장 적합한 에이전트 이름 하나만 반환하세요.
2. 반드시 위 목록에 있는 에이전트 이름 중 하나만 출력하세요.
3. 설명 없이 에이전트 이름만 출력하세요. (예: planning_agent)
4. 판단하기 어려우면 planning_agent를 반환하세요."""


def _build_system_prompt() -> str:
    agents_description = "\n".join(
        f"- {name}: {desc}" for name, desc in AGENT_REGISTRY.items()
    )
    return _SYSTEM_PROMPT_TEMPLATE.format(agents_description=agents_description)


def _build_user_prompt(event: SlackEvent) -> str:
    return f"다음 Slack 메시지를 처리할 에이전트를 선택하세요:\n\n{event['text']}"


def _parse_agent_name(raw: str) -> AgentName:
    """LLM 응답에서 유효한 에이전트 이름을 추출합니다."""
    candidate = raw.strip().lower()
    if candidate in AGENT_REGISTRY:
        return candidate
    # 부분 매칭 시도
    for name in AGENT_REGISTRY:
        if name in candidate:
            return name
    return _FALLBACK_AGENT


class ClassifierProtocol(Protocol):
    """메시지를 분석하여 적합한 에이전트 이름을 반환하는 추상 인터페이스"""

    async def classify(self, event: SlackEvent) -> AgentName:
        """
        Slack 이벤트를 분석하여 처리할 에이전트 이름을 반환합니다.

        Args:
            event (SlackEvent): 수신된 Slack 메시지 이벤트.

        Returns:
            AgentName: AGENT_REGISTRY에 등록된 에이전트 이름.
        """
        ...


class ClaudeAPIClassifier:
    """Anthropic Claude API를 사용하는 분류기. 환경변수: ANTHROPIC_API_KEY"""

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        import anthropic
        self._client = anthropic.AsyncAnthropic()
        self._model = model
        self._system_prompt = _build_system_prompt()

    async def classify(self, event: SlackEvent) -> AgentName:
        import anthropic
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=64,
            system=self._system_prompt,
            messages=[{"role": "user", "content": _build_user_prompt(event)}],
        )
        raw = response.content[0].text if response.content else _FALLBACK_AGENT
        return _parse_agent_name(raw)


class GeminiAPIClassifier:
    """Google Gemini API를 사용하는 분류기. 환경변수: GEMINI_API_KEY"""

    def __init__(self, model: str = "gemini-2.0-flash") -> None:
        from google import genai
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._model = model
        self._system_prompt = _build_system_prompt()

    async def classify(self, event: SlackEvent) -> AgentName:
        from google.genai import types
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=_build_user_prompt(event),
            config=types.GenerateContentConfig(
                system_instruction=self._system_prompt,
                max_output_tokens=64,
            ),
        )
        raw = response.text or _FALLBACK_AGENT
        return _parse_agent_name(raw)


class ClaudeCLIClassifier:
    """Claude CLI(claude -p)를 subprocess로 호출하는 분류기."""

    def __init__(self) -> None:
        self._prompt_prefix = _build_system_prompt()

    async def classify(self, event: SlackEvent) -> AgentName:
        full_prompt = f"{self._prompt_prefix}\n\n{_build_user_prompt(event)}"
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", full_prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f"[classifier] Claude CLI 오류: {stderr.decode()}")
            return _FALLBACK_AGENT
        return _parse_agent_name(stdout.decode().strip())


class GeminiCLIClassifier:
    """Gemini CLI(gemini)를 subprocess로 stdin 파이프로 호출하는 분류기."""

    def __init__(self) -> None:
        self._prompt_prefix = _build_system_prompt()

    async def classify(self, event: SlackEvent) -> AgentName:
        full_prompt = f"{self._prompt_prefix}\n\n{_build_user_prompt(event)}"
        proc = await asyncio.create_subprocess_exec(
            "gemini",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=full_prompt.encode())
        if proc.returncode != 0:
            print(f"[classifier] Gemini CLI 오류: {stderr.decode()}")
            return _FALLBACK_AGENT
        return _parse_agent_name(stdout.decode().strip())
