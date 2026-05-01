"""
Archive Agent (Obsidian 구현체) - Autonomous Edition
- 로컬 마크다운 파일(Obsidian Vault)을 CRUD(조회, 생성, 수정, 삭제)합니다.
"""

import os
import traceback
import json
import glob
from pathlib import Path
from typing import Any

from ..models import (
    ArchiveTaskParams,
    ArchiveTaskResult,
    ExecutionResult,
    ParsedTask,
    RawPayload,
)
from shared_core.agent_logger import AgentLogger
from shared_core.storage.sqlite_manager import SqliteStorageManager

class ObsidianAgent:
    agent_name: str = "obsidian_agent"

    def __init__(self, storage = None) -> None:
        self.vault_path = os.environ.get("OBSIDIAN_VAULT_PATH")
        if not self.vault_path:
            # 기본값 설정 (개발 환경 대응)
            self.vault_path = os.path.join(os.getcwd(), "obsidian_vault")
            
        if not os.path.exists(self.vault_path):
            os.makedirs(self.vault_path, exist_ok=True)
            
        self.logger = AgentLogger(self.agent_name)
        self._storage = storage or SqliteStorageManager()

    # ── 기본 도구 (File System Wrappers) ──────────────────────────────────────────

    def _safe_path(self, file_name: str) -> Path:
        """
        vault_path 밖으로 벗어나는 경로(path traversal)를 차단합니다.
        반환된 Path는 반드시 vault 내부에 위치합니다.
        """
        if not file_name.endswith(".md"):
            file_name += ".md"
        vault = Path(self.vault_path).resolve()
        resolved = (vault / file_name).resolve()
        if not str(resolved).startswith(str(vault) + os.sep) and resolved != vault:
            raise ValueError(f"허용되지 않은 경로입니다: {file_name}")
        return resolved

    async def read_file(self, file_name: str) -> str:
        """파일 내용을 읽어옵니다."""
        full_path = self._safe_path(file_name)

        if not full_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_name}")

        return full_path.read_text(encoding="utf-8")

    async def write_file(self, file_name: str, content: str, append: bool = False) -> str:
        """파일을 생성하거나 수정합니다."""
        full_path = self._safe_path(file_name)

        full_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with full_path.open(mode, encoding="utf-8") as f:
            if append and full_path.stat().st_size > 0:
                f.write("\n\n")
            f.write(content)

        return str(full_path)

    async def delete_file(self, file_name: str) -> bool:
        """파일을 삭제합니다."""
        full_path = self._safe_path(file_name)

        if full_path.exists():
            full_path.unlink()
            return True
        return False

    async def list_files(self, query: str = "") -> list[str]:
        """파일 목록을 검색합니다."""
        pattern = os.path.join(self.vault_path, "**", "*.md")
        all_files = [os.path.relpath(p, self.vault_path) for p in glob.glob(pattern, recursive=True)]
        
        if query:
            return [f for f in all_files if query.lower() in f.lower()]
        return all_files

    # ── 자율 처리 로직 (Autonomous Logic) ─────────────────────────────────────────

    async def handle_dispatch(self, dispatch_msg: dict[str, Any]) -> dict[str, Any]:
        task_id = dispatch_msg.get("task_id", "unknown")
        params = dispatch_msg.get("params") or {}
        # action은 DispatchMessage 최상위 레벨에서 읽고, 없을 때만 params 내부를 fallback으로 사용
        action = dispatch_msg.get("action") or params.get("action", "read_file")
        user_text = str(dispatch_msg.get("content") or "")
        
        # Notion Agent와의 호환성을 위해 page_id를 file_name으로 간주
        file_name = params.get("file_name") or params.get("page_id") or params.get("title")
        content = params.get("content") or params.get("text") or user_text

        try:
            res_data: ArchiveTaskResult = {
                "status": "success", "source": "obsidian", "action": action,
                "raw_data": None, "content": None, "summary": "", "metadata": {"vault_path": self.vault_path},
            }

            # [자율 판단 1] 파일명이 없는데 "쓰기/저장" 요청인 경우 원문에서 제목 추출 시도
            if not file_name and ("저장" in user_text or "생성" in user_text or action == "write_file"):
                # 간단한 제목 추출 규칙 (예: '제목'으로 저장해줘 -> 제목)
                import re
                match = re.search(r"['\"](.*?)['\"]", user_text)
                file_name = match.group(1) if match else "새 메모"
                action = "write_file"
                await self.logger.log_action("reasoning", f"파일명 누락으로 원문에서 추출: {file_name}", task_id=task_id)

            # [자율 판단 2] 액션 분기 처리
            if action in ["write_file", "create_page", "update_page", "append_file"]:
                if not file_name: raise ValueError("저장할 파일명이 필요합니다.")
                # "append_file" action이거나 사용자 텍스트에 "추가" 키워드가 있으면 append 모드
                is_append = action == "append_file" or "추가" in user_text

                path = await self.write_file(file_name, content, append=is_append)
                res_data["action"] = "write_file"
                res_data["summary"] = f"Obsidian 파일 '{file_name}'에 성공적으로 {'추가' if is_append else '저장'}했습니다."
                res_data["content"] = f"✅ **Obsidian 저장 완료**\n- 경로: `{path}`"

            elif action in ["read_file", "get_page"]:
                if not file_name:
                    # 파일명이 없으면 목록 검색 시도
                    files = await self.list_files(query=user_text)
                    if files:
                        file_name = files[0]
                        await self.logger.log_action("fallback", f"파일명 누락으로 검색 결과 사용: {file_name}", task_id=task_id)
                    else:
                        raise ValueError("읽어올 파일명을 찾을 수 없습니다.")
                
                file_content = await self.read_file(file_name)
                res_data["raw_data"] = {"content": file_content}
                res_data["content"] = file_content
                res_data["summary"] = f"Obsidian 파일 '{file_name}'을(를) 읽어왔습니다."

            elif action in ["delete_file", "delete_page"]:
                if not file_name: raise ValueError("삭제할 파일명이 필요합니다.")
                success = await self.delete_file(file_name)
                if success:
                    res_data["summary"] = f"Obsidian 파일 '{file_name}'을(를) 삭제했습니다."
                    res_data["content"] = f"🗑️ **Obsidian 파일 삭제 완료**: `{file_name}`"
                else:
                    raise FileNotFoundError(f"삭제할 파일을 찾을 수 없습니다: {file_name}")

            elif action in ["list_files", "search"]:
                query = params.get("query") or ""
                files = await self.list_files(query)
                res_data["raw_data"] = {"files": files}
                res_data["content"] = "\n".join([f"- {f}" for f in files]) if files else "검색 결과가 없습니다."
                res_data["summary"] = f"Obsidian 볼트에서 {len(files)}개의 파일을 찾았습니다."

            else:
                raise ValueError(f"지원하지 않는 action: {action}")

            # 하이브리드 아키텍처: 대용량 메타데이터(JSON) 분산 저장
            ref_id = None
            if res_data["raw_data"]:
                ref_id = await self._storage.save_data(
                    data=res_data["raw_data"],
                    metadata={"action": action, "task_id": task_id, "source": "obsidian"}
                )
            
            res_data["reference_id"] = ref_id
            res_data["payload_summary"] = res_data["summary"]
            
            # 오케스트라 큐 오버헤드를 줄이기 위해 raw_data 삭제
            res_data.pop("raw_data", None)

            return {"task_id": task_id, "status": "COMPLETED", "result_data": res_data, "error": None, "usage_stats": {}}

        except Exception as exc:
            await self.logger.log_action("error", str(exc), task_id=task_id)
            return {
                "task_id": task_id, "status": "FAILED", "result_data": {},
                "error": {"code": "OBSIDIAN_ERROR", "message": str(exc), "traceback": traceback.format_exc()}
            }
