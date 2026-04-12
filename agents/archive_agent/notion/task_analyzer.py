"""
기획 에이전트 작업 세분화 인터페이스 및 구현
- python-strict-typing 전략: 엄격한 정적 타입 선언 및 추상 인터페이스
"""

import asyncio
import os
from typing import Protocol

from ..models import ParsedTask


_SYSTEM_PROMPT = """당신은 소프트웨어 기획 전문가입니다.
주어진 태스크를 분석하여 다음 구조의 마크다운 문서를 작성하세요.

## 1. 목표
이 태스크가 달성하려는 목적과 기대 효과를 명확히 기술하세요.

## 2. 과정
구현을 위한 단계별 처리 흐름을 기술하세요.

## 3. 결과

### 기능
구현될 기능 목록을 나열하세요.

### 기능들의 조립도
컴포넌트/모듈 아키텍처 및 연결 구조를 기술하세요.

### 출력
최종 결과물 형태 및 제약사항을 기술하세요.

반드시 한국어로 작성하고, 마크다운 형식을 준수하세요."""


def _build_prompt(task: ParsedTask) -> str:
    parts = [f"# 태스크: {task['title']}"]
    if task.get("description"):
        parts.append(f"\n## 목적\n{task['description']}")
    if task.get("task_type"):
        parts.append(f"\n**타입**: {task['task_type']}")
    if task.get("priority"):
        parts.append(f"\n**우선순위**: {task['priority']}")
    return "\n".join(parts)


class TaskAnalyzerProtocol(Protocol):
    """
    Notion 태스크를 입력받아 세분화된 마크다운 문서로 변환하는 추상 인터페이스입니다.
    gemini, claude api 또는 cli 등 다양한 방식으로 구현될 수 있습니다.
    """

    async def analyze_task(self, task: ParsedTask) -> str:
        """
        주어진 기획 태스크를 세분화하여 마크다운 문자열로 반환합니다.
        마크다운은 다음 구조를 포함해야 합니다:
        1. 목표
        2. 과정
        3. 결과 (기능, 기능들의 조립도, 출력)

        Args:
            task (ParsedTask): 파싱 완료된 작업 데이터.

        Returns:
            str: 생성된 마크다운 문서.
        """
        ...


class ClaudeAPITaskAnalyzer:
    """Anthropic Claude API를 사용하는 구현체. 환경변수: ANTHROPIC_API_KEY"""

    def __init__(self, model: str = "claude-opus-4-6") -> None:
        import anthropic
        self._client = anthropic.AsyncAnthropic()
        self._model = model

    async def analyze_task(self, task: ParsedTask) -> str:
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=4096,
            thinking={"type": "enabled", "budget_tokens": 2048},
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(task)}],
        ) as stream:
            final = await stream.get_final_message()
        return next(b.text for b in final.content if b.type == "text")


class GeminiAPITaskAnalyzer:
    """Google Gemini API를 사용하는 구현체. 환경변수: GEMINI_API_KEY"""

    def __init__(self, model: str = "gemini-2.0-flash") -> None:
        from google import genai
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._model = model

    async def analyze_task(self, task: ParsedTask) -> str:
        from google.genai import types

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=_build_prompt(task),
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                max_output_tokens=4096,
            ),
        )
        return response.text


class ClaudeCLITaskAnalyzer:
    """Claude CLI(claude -p)를 subprocess로 호출하는 구현체."""

    async def analyze_task(self, task: ParsedTask) -> str:
        prompt = f"{_SYSTEM_PROMPT}\n\n{_build_prompt(task)}"
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Claude CLI 오류: {stderr.decode()}")
        return stdout.decode().strip()


class GeminiCLITaskAnalyzer:
    """Gemini CLI(gemini)를 subprocess로 stdin 파이프로 호출하는 구현체."""

    async def analyze_task(self, task: ParsedTask) -> str:
        prompt = f"{_SYSTEM_PROMPT}\n\n{_build_prompt(task)}"
        proc = await asyncio.create_subprocess_exec(
            "gemini",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=prompt.encode())
        if proc.returncode != 0:
            raise RuntimeError(f"Gemini CLI 오류: {stderr.decode()}")
        return stdout.decode().strip()


def build_task_analyzer(backend: str | None = None) -> TaskAnalyzerProtocol:
    """
    환경변수 TASK_ANALYZER_BACKEND에 따라 적절한 TaskAnalyzer를 반환합니다.

    백엔드 선택:
        claude (기본): ClaudeAPITaskAnalyzer (ANTHROPIC_API_KEY 필요)
        gemini:        GeminiAPITaskAnalyzer (GEMINI_API_KEY 필요)
        claude_cli:    ClaudeCLITaskAnalyzer (claude CLI 설치 필요)
        gemini_cli:    GeminiCLITaskAnalyzer (gemini CLI 설치 필요)
    """
    selected = backend or os.environ.get("TASK_ANALYZER_BACKEND", "claude")
    match selected:
        case "gemini":
            return GeminiAPITaskAnalyzer()
        case "claude_cli":
            return ClaudeCLITaskAnalyzer()
        case "gemini_cli":
            return GeminiCLITaskAnalyzer()
        case _:
            return ClaudeAPITaskAnalyzer()
