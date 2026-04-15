"""
Unified Archive Agent
- 사용자의 요청을 분석하여 Notion 또는 Obsidian으로 작업을 라우팅합니다.
"""

import logging
from typing import Any

from .notion.agent import ArchiveAgent
from .obsidian.agent import ObsidianAgent

logger = logging.getLogger("archive_agent.unified_agent")

class UnifiedArchiveAgent:
    agent_name: str = "archive_agent"

    def __init__(self) -> None:
        self.notion_agent = ArchiveAgent()
        self.obsidian_agent = ObsidianAgent()
        logger.info("[UnifiedArchiveAgent] Notion 및 Obsidian 에이전트 로드 완료")

    async def handle_dispatch(self, dispatch_msg: dict[str, Any]) -> dict[str, Any]:
        user_text = str(dispatch_msg.get("content") or "").lower()
        params = dispatch_msg.get("params") or {}
        
        # 1. 대상 결정 (Routing Logic)
        target = "notion" # 기본값
        
        # 명시적 키워드 체크
        if any(kw in user_text for kw in ["옵시디언", "obsidian", "로컬", "파일", "메모장"]):
            target = "obsidian"
        elif any(kw in user_text for kw in ["노션", "notion", "db", "데이터베이스"]):
            target = "notion"
        
        # 확장자 체크
        if ".md" in user_text:
            target = "obsidian"
            
        # params에 명시된 경우 (Orchestra가 이미 판단한 경우)
        if params.get("source") == "obsidian":
            target = "obsidian"
        elif params.get("source") == "notion":
            target = "notion"

        # 2. 에이전트 할당 및 실행
        if target == "obsidian":
            logger.info(f"[UnifiedArchiveAgent] Obsidian 라우팅: {user_text[:30]}...")
            return await self.obsidian_agent.handle_dispatch(dispatch_msg)
        else:
            logger.info(f"[UnifiedArchiveAgent] Notion 라우팅: {user_text[:30]}...")
            return await self.notion_agent.handle_dispatch(dispatch_msg)
