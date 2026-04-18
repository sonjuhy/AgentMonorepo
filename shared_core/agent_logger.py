"""
에이전트 활동 로깅 유틸리티 (Shared Core)
- 모든 에이전트가 공통으로 사용하여 오케스트라에 로그를 보고합니다.
"""

import os
import logging
import httpx
from typing import Any

logger = logging.getLogger("shared_core.agent_logger")

class AgentLogger:
    def __init__(self, agent_name: str, orchestra_url: str | None = None):
        self.agent_name = agent_name
        self.orchestra_url = orchestra_url or os.environ.get("ORCHESTRA_URL", "http://127.0.0.1:8001")

    async def log_action(
        self, 
        action: str, 
        message: str, 
        task_id: str | None = None, 
        session_id: str | None = None, 
        payload: dict[str, Any] | None = None
    ):
        """오케스트라의 /logs 엔드포인트로 활동 로그를 전송합니다."""
        url = f"{self.orchestra_url}/logs"
        data = {
            "agent_name": self.agent_name,
            "action": action,
            "message": message,
            "task_id": task_id,
            "session_id": session_id,
            "payload": payload
        }
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=data)
                resp.raise_for_status()
        except Exception as e:
            logger.warning(f"[{self.agent_name}] 로그 전송 실패: {e}")

# 각 에이전트에서 사용 예시:
# logger = AgentLogger("archive_agent")
# await logger.log_action("query_database", "Notion DB 조회 성공", task_id="...", payload={"db_id": "..."})
