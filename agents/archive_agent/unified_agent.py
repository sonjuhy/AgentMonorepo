"""
Unified Archive Agent
- 사용자의 요청을 분석하여 Notion 또는 Obsidian으로 작업을 라우팅합니다.
"""

import json
import logging
import re
from typing import Any

from .notion.agent import ArchiveAgent
from .obsidian.agent import ObsidianAgent
from shared_core.llm.factory import build_llm_provider_from_config
from shared_core.llm.llm_config import LLMConfig, load_llm_config_for_agent, llm_config_from_dispatch

logger = logging.getLogger("archive_agent.unified_agent")

class UnifiedArchiveAgent:
    agent_name: str = "archive_agent"

    def __init__(self) -> None:
        self.notion_agent = ArchiveAgent()
        self.obsidian_agent = ObsidianAgent()
        self._llm_config: LLMConfig = load_llm_config_for_agent(self.agent_name)
        self.llm = build_llm_provider_from_config(self._llm_config)
        logger.info(
            "[UnifiedArchiveAgent] Notion 및 Obsidian 에이전트 로드 완료 "
            "(LLM 라우터 활성화, backend=%s)",
            self._llm_config.backend,
        )

    def _get_llm(self, dispatch_msg: dict) -> Any:
        """dispatch 메시지의 per-call llm_config가 있으면 해당 공급자를 생성해 반환합니다."""
        per_call = llm_config_from_dispatch(dispatch_msg)
        if per_call is None:
            return self.llm
        logger.info(
            "[UnifiedArchiveAgent] per-call LLM 설정 적용 (backend=%s, model=%s)",
            per_call.backend,
            per_call.model,
        )
        return build_llm_provider_from_config(per_call)

    async def handle_dispatch(self, dispatch_msg: dict[str, Any]) -> dict[str, Any]:
        task_id = dispatch_msg.get("task_id", "unknown")
        user_text = str(dispatch_msg.get("content") or "").strip()
        params = dispatch_msg.get("params") or {}

        # 완전 빈 요청에 대한 예외 처리 (조기 실패)
        if not user_text and not params:
            logger.error(f"[UnifiedArchiveAgent] 의미 있는 요청 데이터가 없습니다. (task_id: {task_id})")
            return {
                "task_id": task_id,
                "status": "FAILED",
                "result_data": {},
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "요청 내용(content) 및 파라미터(params)가 모두 비어있어 처리할 수 없습니다.",
                    "traceback": ""
                }
            }

        # 1. 대상 결정 (Routing Logic)
        target = "notion" # 기본값

        # params에 명시된 경우 (Orchestra가 이미 판단한 경우)
        if params.get("source") in ["obsidian", "notion"]:
            target = params.get("source")
        elif user_text:
            # dispatch별 LLM 공급자 선택 (per-call 오버라이드 지원)
            llm = self._get_llm(dispatch_msg)

            system_prompt = """당신은 사용자 요청을 분석하여 문서를 어디서, 어떻게 찾을지 결정하는 라우팅 전문가입니다.
오직 유효한 JSON 형식으로만 응답하세요. (마크다운 백틱 없이 작성)

형식:
{
    "target": "notion" 또는 "obsidian" 또는 "unknown",
    "action": "search" 또는 "get_page" 또는 "query_database" 또는 "read_file" 또는 "write_file",
    "query": "검색어 또는 추출된 조건",
    "reasoning": "선택한 이유"
}

규칙:
1. '옵시디언', '로컬', '파일', '메모장', '.md' 등의 키워드가 있거나 로컬 파일 시스템 조작에 가까우면 "obsidian"으로 라우팅하세요.
2. '노션', '데이터베이스', 'DB', '표', '페이지' 등의 키워드가 있으면 "notion"으로 라우팅하세요.
3. 문서 검색, 조회, 생성과 전혀 관련 없는 엉뚱한 요청이거나 해석이 불가능하면 "target": "unknown"을 반환하세요.
4. 그 외 명확하지 않지만 문서 작업으로 보이면 기본적으로 "notion"을 사용하세요.
5. action은 요청의 의도(조회, 검색, 작성 등)에 맞게 선택하세요."""

            try:
                response_text, _ = await llm.generate_response(
                    prompt=f"사용자 요청: {user_text}\n현재 파라미터: {json.dumps(params, ensure_ascii=False)}",
                    system_instruction=system_prompt
                )

                # json 파싱 (수다스러운 LLM 응답 대비 정규식 추출)
                match = re.search(r"\{.*\}", response_text, re.DOTALL)
                if match:
                    clean_json = match.group(0)
                    llm_decision = json.loads(clean_json)
                else:
                    # 정규식 실패 시 기존 방식 시도
                    clean_json = response_text.replace("```json", "").replace("```", "").strip()
                    llm_decision = json.loads(clean_json)

                target = llm_decision.get("target", target)

                if llm_decision.get("action") and not params.get("action"):
                    params["action"] = llm_decision["action"]
                if llm_decision.get("query") and not params.get("query") and not params.get("page_id"):
                    params["query"] = llm_decision["query"]

                logger.info(f"[UnifiedArchiveAgent] LLM 라우팅 결정 ({target}): {llm_decision.get('reasoning')}")

            except Exception as e:
                logger.warning(f"[UnifiedArchiveAgent] LLM 라우팅 실패, 룰백 사용: {e}")
                if any(kw in user_text.lower() for kw in ["옵시디언", "obsidian", "로컬", "파일", "메모장", ".md"]):
                    target = "obsidian"

        # 파라미터 갱신
        dispatch_msg["params"] = params

        # 2. 에이전트 할당 및 실행
        if target == "unknown":
            logger.warning(f"[UnifiedArchiveAgent] 처리 불가 요청 감지 (task_id: {task_id})")
            return {
                "task_id": task_id,
                "status": "FAILED",
                "result_data": {},
                "error": {
                    "code": "UNSUPPORTED_REQUEST",
                    "message": "문서 아카이브와 관련 없는 요청이거나 처리할 수 없는 명령입니다.",
                    "traceback": ""
                }
            }
        elif target == "obsidian":
            logger.info(f"[UnifiedArchiveAgent] Obsidian 라우팅: {user_text[:30]}...")
            return await self.obsidian_agent.handle_dispatch(dispatch_msg)
        else:
            logger.info(f"[UnifiedArchiveAgent] Notion 라우팅 (target={target}): {user_text[:30]}...")
            return await self.notion_agent.handle_dispatch(dispatch_msg)
