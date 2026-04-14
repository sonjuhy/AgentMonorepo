"""
NLU (Natural Language Understanding) 의도 파악 엔진
- Gemini API 기반 (Primary), Claude API 기반 (Fallback)
- nlu_system_prompt_design.md의 시스템 프롬프트 적용
- 최대 3회 재시도, 실패 시 clarification 반환
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .models import (
    ClarificationNLUResult,
    DirectResponseNLUResult,
    MultiStepNLUResult,
    NLU_CONFIDENCE_THRESHOLD,
    NLUResult,
    SingleNLUResult,
)

logger = logging.getLogger("orchestra_agent.nlu_engine")

_MAX_RETRIES = 3
_USER_TIMEZONE = os.environ.get("USER_TIMEZONE", "Asia/Seoul")

# ── 에이전트 능력 레지스트리 ──────────────────────────────────────────────────────

_AGENT_CAPABILITIES = """
- archive_agent: Notion/Obsidian 자료 조회, 저장 및 반환 (Archive Hub)
  - actions:
    - list_databases: 연결된 모든 노션 데이터베이스 목록 조회
    - get_database_schema: 특정 데이터베이스의 컬럼 구조 및 타입 파악 (params: database_id)
    - query_database: 데이터베이스 내 아이템 목록(데이터 전체)을 가져올 때 사용 (params: database_id[선택])
    - get_page: 특정 낱개 페이지의 상세 내용을 볼 때 사용 (params: page_id[필수])
    - create_page: 노션에 새 페이지를 생성하거나 내용을 저장할 때 사용 (params: title[필수], database_id[선택], content[선택]) - "저장해줘", "기록해줘", "노션에 써줘" 등의 요청에 사용
    - search: 노션/옵시디언 전체에서 검색 (params: query)
    - read_file: 옵시디언 파일 내용 읽기 (params: page_id)
    - analyze_task: (Legacy) 노션 태스크 기획안 생성

- schedule_agent: 구글 캘린더 일정 관리 (actions: list_schedules, add_schedule, modify_schedule, remove_schedule)
- research_agent: 웹 검색 및 정보 수집 (actions: investigate)
- coding_agent: Python 코드 작성 및 테스트 (actions: execute_tdd_cycle)
- file_agent: 로컬 파일 시스템 관리 (actions: read_file, write_file, search_files)
- communication_agent: 사용자 질문 및 응답 (actions: ask_clarification)
""".strip()

_SYSTEM_PROMPT_TEMPLATE = """\
# Role: AI Orchestra Agent (Chief Coordinator)
당신은 독립적인 전문 에이전트들로 구성된 오케스트라의 지휘자입니다.
사용자의 메시지를 분석하여 다음의 JSON 규격에 맞게 [의도 파악 - 에이전트 선택 - 파라미터 추출]을 수행하세요.
현재 날짜와 시간: {current_datetime}
사용자 타임존: {user_timezone}

# Constraints
1. 출력은 반드시 유효한 JSON 형식이어야 하며, 다른 설명은 포함하지 않습니다.
2. 사용자의 요청이 단순 인사, 감사, 날씨 질문, 자기소개 등 하위 에이전트의 전문 도구가 필요 없는 일상적인 대화라면 type을 "direct_response"로 설정하고 직접 답변하십시오.
3. 사용자의 요청이 모호하거나 정보가 부족하면 communication_agent를 선택하고
   action을 "ask_clarification"으로 설정하십시오.
4. 복합 작업(여러 에이전트가 필요)은 type을 "multi_step"으로 설정하고
   plan 배열에 각 단계를 순서대로 나열하십시오.
5. 에이전트 선택 이유(reason)와 신뢰도(confidence_score)는 반드시 포함하십시오.
6. confidence_score가 {confidence_threshold} 미만이면 사용자에게 확인을 요청하십시오.
7. requires_user_approval은 파일 삭제, 코드 실행, 캘린더 변경 등 되돌리기 어려운 작업에 true를 설정하십시오.

# Available Agents & Capabilities
{agent_capabilities}

# Output Schema (Strict JSON)

## 단일 작업 (type: "single")
{{"type": "single", "intent": "string", "selected_agent": "string", "action": "string", "params": {{}}, "metadata": {{"reason": "string", "confidence_score": 0.0, "requires_user_approval": false}}}}

## 복합 작업 (type: "multi_step")
{{"type": "multi_step", "intent": "string", "plan": [{{"step": 1, "selected_agent": "string", "action": "string", "params": {{}}, "depends_on": [], "metadata": {{"reason": "string", "requires_user_approval": false}}}}], "metadata": {{"reason": "string", "confidence_score": 0.0, "requires_user_approval": false}}}}

## 추가 질문 필요 (type: "clarification")
{{"type": "clarification", "intent": "string", "selected_agent": "communication_agent", "action": "ask_clarification", "params": {{"question": "사용자에게 보낼 질문", "options": []}}, "metadata": {{"reason": "string", "confidence_score": 0.0, "requires_user_approval": false}}}}

## 직접 답변 (type: "direct_response")
{{"type": "direct_response", "intent": "chitchat", "params": {{"answer": "사용자에게 보낼 답변 내용"}}, "metadata": {{"reason": "단순 대화 요청임", "confidence_score": 1.0, "requires_user_approval": false}}}}
"""


def _build_system_prompt(
    style_guide: dict[str, str] | None = None,
    agent_capabilities: str | None = None,
) -> str:
    tz = ZoneInfo(_USER_TIMEZONE)
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")

    # 동적으로 주입된 캐퍼빌리티가 있으면 사용, 없으면 하드코딩 폴백
    capabilities = agent_capabilities if agent_capabilities else _AGENT_CAPABILITIES

    style_str = ""
    if style_guide:
        style_str = "\n# Persona & Response Style\n" + "\n".join(f"- {k}: {v}" for k, v in style_guide.items())

    return _SYSTEM_PROMPT_TEMPLATE.format(
        current_datetime=now,
        user_timezone=_USER_TIMEZONE,
        confidence_threshold=NLU_CONFIDENCE_THRESHOLD,
        agent_capabilities=capabilities,
    ) + style_str


def _build_user_prompt(user_text: str, context: list[dict[str, Any]]) -> str:
    if context:
        ctx_str = "\n".join(
            f"[{m.get('role', 'user')}]: {m.get('content', '')[:200]}"
            for m in context[-5:]  # 최근 5개 메시지만 포함
        )
        return f"[이전 대화]\n{ctx_str}\n\n[현재 요청]\n{user_text}"
    return user_text


import re

def _parse_nlu_result(raw: str) -> NLUResult:
    """LLM 응답 문자열을 NLUResult Pydantic 모델로 파싱합니다."""
    # 1. 정규표현식으로 JSON 블록 추출 시도
    # ```json ... ``` 또는 { ... } 형태를 찾음
    json_match = re.search(r"(\{.*\})", raw, re.DOTALL)
    if json_match:
        raw = json_match.group(1)
    else:
        # 정규표현식 실패 시 기본 strip() 처리
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("[NLU] JSON 파싱 에러: %s | Raw Output: %s", e, raw)
        raise e

    nlu_type = data.get("type", "single")

    if nlu_type == "multi_step":
        return MultiStepNLUResult(**data)
    if nlu_type == "clarification":
        return ClarificationNLUResult(**data)
    if nlu_type == "direct_response":
        return DirectResponseNLUResult(**data)
    return SingleNLUResult(**data)


def _make_clarification_fallback(reason: str = "요청을 이해하지 못했습니다.") -> ClarificationNLUResult:
    return ClarificationNLUResult(
        type="clarification",
        intent="unknown",
        selected_agent="communication_agent",
        action="ask_clarification",
        params={"question": "죄송합니다, 요청을 이해하지 못했습니다. 좀 더 구체적으로 말씀해 주시겠어요?", "options": []},
        metadata={"reason": reason, "confidence_score": 0.0, "requires_user_approval": False},
    )


# ── Gemini NLU Engine ────────────────────────────────────────────────────────

class GeminiNLUEngine:
    """
    Gemini API를 사용하는 NLU 의도 파악 엔진.

    환경 변수:
        GEMINI_API_KEY: Google AI API 키
        GEMINI_NLU_MODEL: 사용할 모델 (기본값: gemini-2.0-flash)
    """

    def __init__(self, model: str | None = None) -> None:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
        self._client = genai.Client(api_key=api_key)
        self._model = model or os.environ.get("GEMINI_NLU_MODEL", "gemini-2.0-flash")

    async def validate(self) -> bool:
        """API 키 유효성 및 연결 상태를 검증합니다."""
        try:
            # 아주 짧은 텍스트로 테스트 생성 요청
            await self._client.aio.models.generate_content(
                model=self._model,
                contents="hi",
                config={"max_output_tokens": 1}
            )
            logger.info("[NLU/Gemini] LLM 연결 검증 성공")
            return True
        except Exception as e:
            logger.error("[NLU/Gemini] LLM 연결 검증 실패: %s", e)
            return False

    async def analyze(
        self,
        user_text: str,
        session_id: str,
        context: list[dict[str, Any]],
        style_guide: dict[str, str] | None = None,
        agent_capabilities: str | None = None,
    ) -> NLUResult:
        """Gemini API로 의도·에이전트·파라미터 추출 (최대 3회 재시도)."""
        from google.genai import types

        system_prompt = _build_system_prompt(style_guide, agent_capabilities)
        user_prompt = _build_user_prompt(user_text, context)
        last_error = ""

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        max_output_tokens=2048,  # 토큰 제한 상향
                        temperature=0.1,
                    ),
                )
                raw = response.text or ""
                result = _parse_nlu_result(raw)

                # confidence_score < threshold이면 clarification으로 강제 변환
                if hasattr(result, "metadata") and result.metadata.confidence_score < NLU_CONFIDENCE_THRESHOLD:
                    if result.type != "clarification":
                        logger.info(
                            "[NLU] confidence=%.2f < %.1f → clarification 전환",
                            result.metadata.confidence_score,
                            NLU_CONFIDENCE_THRESHOLD,
                        )
                        return _make_clarification_fallback(
                            f"신뢰도 부족 (score={result.metadata.confidence_score:.2f})"
                        )

                logger.info("[NLU] 분석 완료 type=%s session=%s", result.type, session_id)
                return result

            except (json.JSONDecodeError, ValidationError) as e:
                last_error = str(e)
                logger.warning("[NLU] 파싱 실패 (시도 %d/%d): %s", attempt + 1, _MAX_RETRIES, e)
            except Exception as e:
                last_error = str(e)
                logger.error("[NLU] API 오류 (시도 %d/%d): %s", attempt + 1, _MAX_RETRIES, e)

        logger.error("[NLU] 최대 재시도 초과 — clarification 반환. 마지막 오류: %s", last_error)
        return _make_clarification_fallback(f"JSON 파싱 실패: {last_error}")


# ── Claude NLU Engine (Fallback) ─────────────────────────────────────────────

class ClaudeNLUEngine:
    """
    Claude API를 사용하는 NLU 의도 파악 엔진 (폴백용).

    환경 변수:
        ANTHROPIC_API_KEY: Anthropic API 키
        CLAUDE_NLU_MODEL: 사용할 모델 (기본값: claude-haiku-4-5-20251001)
    """

    def __init__(self, model: str | None = None) -> None:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model or os.environ.get("CLAUDE_NLU_MODEL", "claude-haiku-4-5-20251001")

    async def validate(self) -> bool:
        """API 키 유효성 및 연결 상태를 검증합니다."""
        try:
            await self._client.messages.create(
                model=self._model,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            logger.info("[NLU/Claude] LLM 연결 검증 성공")
            return True
        except Exception as e:
            logger.error("[NLU/Claude] LLM 연결 검증 실패: %s", e)
            return False

    async def analyze(
        self,
        user_text: str,
        session_id: str,
        context: list[dict[str, Any]],
        style_guide: dict[str, str] | None = None,
        agent_capabilities: str | None = None,
    ) -> NLUResult:
        """Claude API로 의도 파악 (최대 3회 재시도)."""
        system_prompt = _build_system_prompt(style_guide, agent_capabilities)
        user_prompt = _build_user_prompt(user_text, context)
        last_error = ""

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                raw = response.content[0].text if response.content else ""
                result = _parse_nlu_result(raw)

                # 토큰 사용량 로그
                usage = response.usage
                if usage:
                    logger.info(
                        "[NLU/Claude] 토큰 사용량: Input=%d, Output=%d, Total=%d",
                        usage.input_tokens,
                        usage.output_tokens,
                        usage.input_tokens + usage.output_tokens,
                    )

                if hasattr(result, "metadata") and result.metadata.confidence_score < NLU_CONFIDENCE_THRESHOLD:
                    if result.type != "clarification":
                        return _make_clarification_fallback(
                            f"신뢰도 부족 (score={result.metadata.confidence_score:.2f})"
                        )

                logger.info("[NLU/Claude] 분석 완료 type=%s session=%s", result.type, session_id)
                return result

            except (json.JSONDecodeError, ValidationError) as e:
                last_error = str(e)
                logger.warning("[NLU/Claude] 파싱 실패 (시도 %d/%d): %s", attempt + 1, _MAX_RETRIES, e)
            except Exception as e:
                last_error = str(e)
                logger.error("[NLU/Claude] API 오류 (시도 %d/%d): %s", attempt + 1, _MAX_RETRIES, e)

        return _make_clarification_fallback(f"JSON 파싱 실패: {last_error}")


def build_nlu_engine() -> GeminiNLUEngine | ClaudeNLUEngine:
    """
    환경변수 NLU_BACKEND에 따라 NLU 엔진을 생성합니다.
    기본값: gemini (GEMINI_API_KEY 필요)
    폴백: claude (ANTHROPIC_API_KEY 필요)
    """
    backend = os.environ.get("NLU_BACKEND", "gemini").lower()
    if backend == "claude":
        return ClaudeNLUEngine()
    return GeminiNLUEngine()
