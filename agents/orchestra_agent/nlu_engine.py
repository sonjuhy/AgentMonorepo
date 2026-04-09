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
- coding_agent: Python 코드 작성·TDD 실행·디버깅 (actions: execute_tdd_cycle, review_code)
- archive_agent: Notion/Obsidian 문서 읽기·쓰기·시맨틱 검색 (actions: search_documents, write_document, read_document, sync_documents)
- research_agent: 웹 검색·정보 수집·보고서 작성 (actions: investigate)
- calendar_agent: 구글 캘린더 일정 CRUD (actions: create_event, query_events, update_event, delete_event)
- file_agent: 로컬 파일 시스템 CRUD·검색 (actions: read_file, write_file, search_files, move_file, copy_file, delete_file)
- communication_agent: 사용자에게 메시지 발송·질문 (actions: send_message, ask_clarification)
- agent_builder: Python 또는 JavaScript 코드와 패키지 목록으로 새 에이전트를 자동 생성·패키징 (actions: build_agent, params: name[필수]/language["python"|"javascript"]/code[필수]/packages[]/port[int]/description[str]/force[bool])
""".strip()

_SYSTEM_PROMPT_TEMPLATE = """\
# Role: AI Orchestra Agent (Chief Coordinator)
당신은 독립적인 전문 에이전트들로 구성된 오케스트라의 지휘자입니다.
사용자의 메시지를 분석하여 다음의 JSON 규격에 맞게 [의도 파악 - 에이전트 선택 - 파라미터 추출]을 수행하세요.
현재 날짜와 시간: {current_datetime}
사용자 타임존: {user_timezone}

# Constraints
1. 출력은 반드시 유효한 JSON 형식이어야 하며, 다른 설명은 포함하지 않습니다.
2. 사용자의 요청이 모호하거나 정보가 부족하면 communication_agent를 선택하고
   action을 "ask_clarification"으로 설정하십시오.
3. 복합 작업(여러 에이전트가 필요)은 type을 "multi_step"으로 설정하고
   plan 배열에 각 단계를 순서대로 나열하십시오.
4. 에이전트 선택 이유(reason)와 신뢰도(confidence_score)는 반드시 포함하십시오.
5. confidence_score가 {confidence_threshold} 미만이면 사용자에게 확인을 요청하십시오.
6. requires_user_approval은 파일 삭제, 코드 실행, 캘린더 변경 등 되돌리기 어려운 작업에 true를 설정하십시오.

# Available Agents & Capabilities
{agent_capabilities}

# Output Schema (Strict JSON)

## 단일 작업 (type: "single")
{{"type": "single", "intent": "string", "selected_agent": "string", "action": "string", "params": {{}}, "metadata": {{"reason": "string", "confidence_score": 0.0, "requires_user_approval": false}}}}

## 복합 작업 (type: "multi_step")
{{"type": "multi_step", "intent": "string", "plan": [{{"step": 1, "selected_agent": "string", "action": "string", "params": {{}}, "depends_on": [], "metadata": {{"reason": "string", "requires_user_approval": false}}}}], "metadata": {{"reason": "string", "confidence_score": 0.0, "requires_user_approval": false}}}}

## 추가 질문 필요 (type: "clarification")
{{"type": "clarification", "intent": "string", "selected_agent": "communication_agent", "action": "ask_clarification", "params": {{"question": "사용자에게 보낼 질문", "options": []}}, "metadata": {{"reason": "string", "confidence_score": 0.0, "requires_user_approval": false}}}}
"""


def _build_system_prompt() -> str:
    tz = ZoneInfo(_USER_TIMEZONE)
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    return _SYSTEM_PROMPT_TEMPLATE.format(
        current_datetime=now,
        user_timezone=_USER_TIMEZONE,
        confidence_threshold=NLU_CONFIDENCE_THRESHOLD,
        agent_capabilities=_AGENT_CAPABILITIES,
    )


def _build_user_prompt(user_text: str, context: list[dict[str, Any]]) -> str:
    if context:
        ctx_str = "\n".join(
            f"[{m.get('role', 'user')}]: {m.get('content', '')[:200]}"
            for m in context[-5:]  # 최근 5개 메시지만 포함
        )
        return f"[이전 대화]\n{ctx_str}\n\n[현재 요청]\n{user_text}"
    return user_text


def _parse_nlu_result(raw: str) -> NLUResult:
    """LLM 응답 문자열을 NLUResult Pydantic 모델로 파싱합니다."""
    # 마크다운 코드블록 제거
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    data = json.loads(raw)
    nlu_type = data.get("type", "single")

    if nlu_type == "multi_step":
        return MultiStepNLUResult(**data)
    if nlu_type == "clarification":
        return ClarificationNLUResult(**data)
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
        api_key = os.environ["GEMINI_API_KEY"]
        self._client = genai.Client(api_key=api_key)
        self._model = model or os.environ.get("GEMINI_NLU_MODEL", "gemini-2.0-flash")

    async def analyze(
        self,
        user_text: str,
        session_id: str,
        context: list[dict[str, Any]],
    ) -> NLUResult:
        """Gemini API로 의도·에이전트·파라미터 추출 (최대 3회 재시도)."""
        from google.genai import types

        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(user_text, context)
        last_error = ""

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        max_output_tokens=1024,
                        temperature=0.1,  # 낮은 temperature로 일관된 JSON 출력
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
        self._client = anthropic.AsyncAnthropic()
        self._model = model or os.environ.get("CLAUDE_NLU_MODEL", "claude-haiku-4-5-20251001")

    async def analyze(
        self,
        user_text: str,
        session_id: str,
        context: list[dict[str, Any]],
    ) -> NLUResult:
        """Claude API로 의도 파악 (최대 3회 재시도)."""
        system_prompt = _build_system_prompt()
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
