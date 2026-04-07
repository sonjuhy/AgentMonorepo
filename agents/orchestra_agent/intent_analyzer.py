"""
LLM 기반 사용자 의도 분석기
- 사용자 자연어 입력 → AgentMessage 리스트 변환
- Claude API, Gemini API, Claude CLI, Gemini CLI 구현체 제공
- python-strict-typing 전략: Protocol 기반 다형성
"""

import asyncio
import json
import os
from typing import Any, Protocol

from shared_core.messaging import AgentMessage, AgentName

_FALLBACK_RECEIVER: AgentName = "planning"

_SYSTEM_PROMPT_TEMPLATE = """당신은 사용자의 자연어 요청을 분석하여 처리할 에이전트와 작업을 결정하는 오케스트라 라우터입니다.

사용 가능한 에이전트 목록:
{agents_description}

규칙:
1. 사용자 요청을 분석하여 필요한 에이전트 작업 목록을 JSON 배열로 반환하세요.
2. 반드시 다음 JSON 형식만 출력하세요 (설명 없이 JSON만):
[
  {{
    "receiver": "에이전트_이름",
    "action": "작업_이름",
    "payload": {{
      "key": "value"
    }}
  }}
]
3. receiver는 반드시 위 목록에 있는 에이전트 이름 중 하나여야 합니다.
4. action은 해당 에이전트가 수행할 작업을 snake_case로 표현하세요. (예: process_task, send_notification)
5. payload에는 작업에 필요한 상세 정보를 포함하세요.
6. 요청 처리에 여러 에이전트가 필요하면 여러 항목을 반환하세요.
"""


def _build_system_prompt(capabilities: dict[AgentName, str]) -> str:
    agents_description = "\n".join(
        f"- {name}: {desc}" for name, desc in capabilities.items()
    )
    return _SYSTEM_PROMPT_TEMPLATE.format(agents_description=agents_description)


def _parse_agent_messages(
    raw: str,
    sender: AgentName,
    valid_receivers: set[AgentName],
) -> list[AgentMessage]:
    """LLM 응답 JSON을 파싱하여 AgentMessage 리스트로 변환합니다."""
    try:
        # 코드블록 제거 (```json ... ```)
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        data: list[dict[str, Any]] = json.loads(text)
        messages: list[AgentMessage] = []

        for item in data:
            receiver = item.get("receiver", _FALLBACK_RECEIVER)
            if receiver not in valid_receivers:
                receiver = _FALLBACK_RECEIVER
            messages.append(
                AgentMessage(
                    sender=sender,
                    receiver=receiver,
                    action=item.get("action", "process_request"),
                    payload=item.get("payload", {}),
                )
            )
        return messages if messages else _fallback_messages(sender)

    except (json.JSONDecodeError, TypeError, KeyError):
        return _fallback_messages(sender)


def _fallback_messages(sender: AgentName) -> list[AgentMessage]:
    return [
        AgentMessage(
            sender=sender,
            receiver=_FALLBACK_RECEIVER,
            action="process_request",
            payload={},
        )
    ]


class IntentAnalyzerProtocol(Protocol):
    """사용자 입력을 분석하여 AgentMessage 리스트를 반환하는 추상 인터페이스."""

    async def analyze(
        self,
        user_input: str,
        capabilities: dict[AgentName, str],
    ) -> list[AgentMessage]:
        """
        사용자 입력을 분석하여 각 에이전트에게 전달할 메시지 목록을 생성합니다.

        Args:
            user_input: 사용자의 자연어 입력.
            capabilities: 등록된 에이전트 이름 → 역할 설명 매핑.

        Returns:
            각 에이전트에게 전송할 AgentMessage 리스트.
        """
        ...


class ClaudeAPIIntentAnalyzer:
    """Anthropic Claude API를 사용하는 의도 분석기. 환경변수: ANTHROPIC_API_KEY"""

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic()
        self._model = model

    async def analyze(
        self,
        user_input: str,
        capabilities: dict[AgentName, str],
    ) -> list[AgentMessage]:

        system_prompt = _build_system_prompt(capabilities)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_input}],
        )
        raw = response.content[0].text if response.content else "[]"
        return _parse_agent_messages(raw, "orchestra", set(capabilities.keys()))


class GeminiAPIIntentAnalyzer:
    """Google Gemini API를 사용하는 의도 분석기. 환경변수: GEMINI_API_KEY"""

    def __init__(self, model: str = "gemini-2.0-flash") -> None:
        from google import genai

        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._model = model

    async def analyze(
        self,
        user_input: str,
        capabilities: dict[AgentName, str],
    ) -> list[AgentMessage]:
        from google.genai import types

        system_prompt = _build_system_prompt(capabilities)
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=user_input,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=1024,
            ),
        )
        raw = response.text or "[]"
        return _parse_agent_messages(raw, "orchestra", set(capabilities.keys()))


class ClaudeCLIIntentAnalyzer:
    """Claude CLI(claude -p)를 subprocess로 호출하는 의도 분석기."""

    async def analyze(
        self,
        user_input: str,
        capabilities: dict[AgentName, str],
    ) -> list[AgentMessage]:
        full_prompt = (
            f"{_build_system_prompt(capabilities)}\n\n사용자 요청: {user_input}"
        )
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            full_prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f"[intent_analyzer] Claude CLI 오류: {stderr.decode()}")
            return _fallback_messages("orchestra")
        return _parse_agent_messages(
            stdout.decode().strip(), "orchestra", set(capabilities.keys())
        )


class GeminiCLIIntentAnalyzer:
    """Gemini CLI(gemini)를 subprocess로 stdin 파이프로 호출하는 의도 분석기."""

    async def analyze(
        self,
        user_input: str,
        capabilities: dict[AgentName, str],
    ) -> list[AgentMessage]:
        full_prompt = (
            f"{_build_system_prompt(capabilities)}\n\n사용자 요청: {user_input}"
        )
        proc = await asyncio.create_subprocess_exec(
            "gemini",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=full_prompt.encode())
        if proc.returncode != 0:
            print(f"[intent_analyzer] Gemini CLI 오류: {stderr.decode()}")
            return _fallback_messages("orchestra")
        return _parse_agent_messages(
            stdout.decode().strip(), "orchestra", set(capabilities.keys())
        )
