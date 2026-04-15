"""
Obsidian Archive Agent 구현체
- 로컬 마크다운 파일(Obsidian Vault)에서 자료를 조회하고 반환합니다.
- python-strict-typing 전략 준수
"""

from __future__ import annotations

import glob
import os
import traceback
from typing import Any

from ..models import (
    ArchiveTaskParams,
    ArchiveTaskResult,
    ExecutionResult,
    ParsedTask,
    RawPayload,
)
from ..notion.notion_parser import parse_notion_task  # 호환용
from ..notion.task_analyzer import ClaudeAPITaskAnalyzer, TaskAnalyzerProtocol

class ObsidianArchiveAgent:
    """
    Obsidian 볼트 내 자료를 검색하고 읽어오는 에이전트입니다.
    """

    agent_name: str = "obsidian_archive_agent"

    def __init__(
        self,
        vault_path: str | None = None,
        task_analyzer: TaskAnalyzerProtocol | None = None,
    ) -> None:
        self.vault_path = vault_path or os.environ.get("OBSIDIAN_VAULT_PATH", "/vault")
        self.task_analyzer = task_analyzer or ClaudeAPITaskAnalyzer()

    async def read_file(self, file_path: str) -> str:
        """파일 내용을 읽어옵니다."""
        full_path = os.path.join(self.vault_path, file_path)
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    async def search_files(self, query: str) -> list[str]:
        """키워드로 파일을 검색합니다."""
        pattern = os.path.join(self.vault_path, "**", f"*{query}*.md")
        return [os.path.relpath(p, self.vault_path) for p in glob.glob(pattern, recursive=True)]

    async def handle_dispatch(
        self,
        dispatch_msg: dict[str, Any],
    ) -> dict[str, Any]:
        """
        OrchestraManager의 DispatchMessage를 처리합니다.
        """
        task_id: str = dispatch_msg.get("task_id", "unknown")
        params: ArchiveTaskParams = dispatch_msg.get("params") or {}
        action = dispatch_msg.get("action") or params.get("action", "read_file")

        try:
            result_data: ArchiveTaskResult = {
                "status": "success",
                "source": "obsidian",
                "action": action,
                "raw_data": None,
                "content": None,
                "summary": "",
                "metadata": {"vault_path": self.vault_path},
            }

            if action == "read_file":
                file_path = params.get("page_id") or params.get("file_path")
                if not file_path: raise ValueError("file_path가 필요합니다.")
                
                content = await self.read_file(file_path)
                result_data["content"] = content
                result_data["summary"] = f"파일 '{file_path}' 조회 완료"

            elif action == "search":
                query = params.get("query", "")
                files = await self.search_files(query)
                result_data["raw_data"] = {"files": files}
                result_data["content"] = "\n".join([f"- {f}" for f in files])
                result_data["summary"] = f"검색어 '{query}'로 {len(files)}개의 파일을 찾았습니다."

            else:
                raise ValueError(f"지원하지 않는 Action: {action}")

            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "result_data": result_data,
                "error": None,
                "usage_stats": {},
            }

        except Exception as exc:
            return {
                "task_id": task_id,
                "status": "FAILED",
                "result_data": {},
                "error": {
                    "code": "OBSIDIAN_ERROR",
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                },
                "usage_stats": {},
            }
