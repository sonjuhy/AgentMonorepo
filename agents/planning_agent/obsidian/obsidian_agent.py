"""
Obsidian Planning Agent 구현체
- 로컬 마크다운 파일(Obsidian Vault) 연동 기획 에이전트
- YAML Frontmatter 파싱 및 업데이트
- ephemeral-docker-ops 전략: 단발성 실행 후 자연 종료
"""

from __future__ import annotations

import glob
import os
import re
import traceback
from typing import Any

from ..models import ExecutionResult, ParsedTask, RawPayload
from ..notion.task_analyzer import ClaudeAPITaskAnalyzer, TaskAnalyzerProtocol

# Frontmatter 블록을 추출하는 패턴 (--- 사이)
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# 단순 key: value 파싱 패턴 (들여쓰기 없는 최상위 키만)
_KV_RE = re.compile(r"^([A-Za-z가-힣_][A-Za-z가-힣_0-9]*)\s*:\s*(.*)", re.MULTILINE)


def _parse_yaml_simple(text: str) -> dict[str, str]:
    """
    경량 YAML 파서 — 최상위 key: value 쌍만 추출합니다.
    리스트나 중첩 구조는 문자열로 반환합니다.
    외부 라이브러리(pyyaml) 없이 re만 사용합니다.
    """
    result: dict[str, str] = {}
    for match in _KV_RE.finditer(text):
        key = match.group(1).strip()
        val = match.group(2).strip()
        # 따옴표 제거
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        result[key] = val
    return result


def _set_frontmatter_key(content: str, key: str, value: str) -> str:
    """
    마크다운 본문에서 Frontmatter의 특정 key 값을 교체합니다.
    key가 없으면 Frontmatter 블록 끝 직전에 추가합니다.
    Frontmatter 자체가 없으면 파일 상단에 새로 삽입합니다.
    """
    fm_match = _FRONTMATTER_RE.match(content)
    if not fm_match:
        return f"---\n{key}: {value}\n---\n\n{content}"

    fm_text = fm_match.group(1)
    rest = content[fm_match.end():]

    kv_pattern = re.compile(rf"^({re.escape(key)}\s*:\s*).*$", re.MULTILINE)
    if kv_pattern.search(fm_text):
        new_fm = kv_pattern.sub(rf"\g<1>{value}", fm_text)
    else:
        new_fm = fm_text + f"\n{key}: {value}"

    return f"---\n{new_fm}\n---\n{rest}"


class ObsidianPlanningAgent:
    """
    Obsidian 볼트 내 마크다운 파일을 파싱하여 기획 태스크를 처리하는 에이전트.

    Vault 폴더를 스캔하여 YAML Frontmatter의 status가 '검토중'인 파일을
    찾아 LLM으로 기획안을 생성하고, 파일 본문과 메타데이터를 업데이트합니다.
    """

    agent_name: str = "obsidian-planning-agent"

    def __init__(
        self,
        vault_path: str,
        task_folder: str = "Tasks/Planning",
        task_analyzer: TaskAnalyzerProtocol | None = None,
    ) -> None:
        """
        Args:
            vault_path: Obsidian 볼트의 루트 절대 경로.
            task_folder: 태스크 파일이 위치한 볼트 내 하위 폴더.
            task_analyzer: LLM 분석 구현체 (기본: ClaudeAPITaskAnalyzer).
        """
        self.vault_path = vault_path
        self.target_dir = os.path.join(vault_path, task_folder)
        self.task_analyzer = task_analyzer or ClaudeAPITaskAnalyzer()

        if not os.path.isdir(self.target_dir):
            print(f"[{self.agent_name}] 경고: 태스크 폴더가 없습니다 → {self.target_dir}")

    # ── 내부 유틸리티 ──────────────────────────────────────────────────────────

    async def _parse_frontmatter(self, file_content: str) -> dict[str, str]:
        """
        마크다운 파일 내용에서 YAML Frontmatter를 추출하여 딕셔너리로 반환합니다.

        Args:
            file_content: 마크다운 파일 전체 문자열.

        Returns:
            Frontmatter key-value 딕셔너리 (없으면 빈 딕셔너리).
        """
        fm_match = _FRONTMATTER_RE.match(file_content)
        if not fm_match:
            return {}
        return _parse_yaml_simple(fm_match.group(1))

    def _get_body(self, file_content: str) -> str:
        """Frontmatter를 제외한 본문 텍스트를 반환합니다."""
        fm_match = _FRONTMATTER_RE.match(file_content)
        return file_content[fm_match.end():] if fm_match else file_content

    # ── PlanningAgentProtocol 구현 ─────────────────────────────────────────────

    async def fetch_pending_tasks(self) -> list[RawPayload]:
        """
        target_dir 내 모든 .md 파일을 스캔하여 status가 '검토중'인 파일 목록을 반환합니다.

        Returns:
            list[RawPayload]: 각 파일의 경로·메타데이터·본문을 담은 딕셔너리 리스트.
        """
        if not os.path.isdir(self.target_dir):
            return []

        pending: list[RawPayload] = []
        pattern = os.path.join(self.target_dir, "**", "*.md")

        for filepath in glob.glob(pattern, recursive=True):
            try:
                with open(filepath, encoding="utf-8") as f:
                    content = f.read()

                fm = await self._parse_frontmatter(content)
                status = fm.get("status", fm.get("현황", ""))

                if status in ("검토중", "pending", "review"):
                    pending.append(
                        {
                            "filepath": filepath,
                            "frontmatter": fm,
                            "body": self._get_body(content),
                            "raw_content": content,
                        }
                    )
            except Exception as exc:
                print(f"[{self.agent_name}] 파일 읽기 실패 {filepath}: {exc}")

        return pending

    async def parse_obsidian_task(self, raw_data: RawPayload) -> ParsedTask | None:
        """
        Obsidian RawPayload를 표준 ParsedTask로 변환합니다.
        Notion의 parse_notion_task()와 동일한 역할입니다.

        Args:
            raw_data: fetch_pending_tasks()가 반환한 딕셔너리.

        Returns:
            ParsedTask | None: 변환 성공 시 딕셔너리, 필수 필드 누락 시 None.
        """
        try:
            fm: dict[str, str] = raw_data.get("frontmatter", {})
            filepath: str = raw_data.get("filepath", "")
            body: str = raw_data.get("body", "")

            title = (
                fm.get("title")
                or fm.get("제목")
                or os.path.splitext(os.path.basename(filepath))[0]
                or "제목 없음"
            )
            description = fm.get("description") or fm.get("목적") or body[:200]
            status = fm.get("status") or fm.get("현황") or "검토중"
            priority = fm.get("priority") or fm.get("우선순위") or ""
            task_type = fm.get("type") or fm.get("타입") or ""

            return ParsedTask(
                page_id=filepath,       # Obsidian에서는 파일 경로가 고유 ID 역할
                title=title,
                description=description,
                status=status,
                github_pr=fm.get("github_pr", ""),
                design_doc=fm.get("design_doc", ""),
                agent_assignees=["obsidian-planning-agent"],
                assignees=[],
                skeleton_code="",
                priority=priority,
                last_edited_time="",
                task_type=task_type,
            )
        except Exception as exc:
            print(f"[{self.agent_name}] 파싱 실패: {exc}")
            return None

    async def update_obsidian_task(
        self,
        filepath: str,
        status: str | None = None,
        agent_names: list[str] | None = None,
        design_doc: str | None = None,
        skeleton_code: str | None = None,
    ) -> ExecutionResult:
        """
        대상 마크다운 파일의 Frontmatter와 본문을 업데이트합니다.

        처리 흐름:
        1. 파일 읽기
        2. Frontmatter에 status / agents 키 업데이트
        3. 본문 끝에 설계 문서 / 스켈레톤 코드 추가
        4. 파일 쓰기

        Args:
            filepath: 업데이트할 마크다운 파일의 절대 경로.
            status: 변경할 상태 값 (예: "승인 대기중").
            agent_names: 담당 에이전트 이름 리스트.
            design_doc: 추가할 기획안 마크다운.
            skeleton_code: 추가할 스켈레톤 코드.

        Returns:
            ExecutionResult: (성공 여부, 결과 메시지).
        """
        try:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()

            if status:
                content = _set_frontmatter_key(content, "status", status)
            if agent_names:
                content = _set_frontmatter_key(content, "agents", ", ".join(agent_names))

            appended: list[str] = []
            if design_doc:
                appended.append(f"\n---\n\n## 기획안 / 설계도\n\n{design_doc}\n")
            if skeleton_code:
                appended.append(f"\n## 스켈레톤 코드\n\n```python\n{skeleton_code}\n```\n")

            if appended:
                content = content.rstrip() + "\n" + "".join(appended)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

            return (True, f"Obsidian 파일 업데이트 성공: {filepath}")

        except Exception as exc:
            return (False, f"Obsidian 파일 업데이트 실패: {exc}\n{traceback.format_exc()}")

    async def process_task(self, task_data: ParsedTask) -> ExecutionResult:
        """
        ParsedTask를 처리합니다.
        LLM으로 기획 마크다운을 생성하고 원본 파일에 반영합니다.

        Args:
            task_data: parse_obsidian_task()가 반환한 ParsedTask.

        Returns:
            ExecutionResult: (성공 여부, 메시지).
        """
        filepath = task_data["page_id"]   # Obsidian에서 page_id = 파일 경로
        try:
            print(f"[{self.agent_name}] 처리 중: [{task_data['status']}] {task_data['title']}")

            markdown_doc = await self.task_analyzer.analyze_task(task_data)
            print(f"[{self.agent_name}] 기획 마크다운 생성 완료 ({len(markdown_doc)}자)")

            ok, msg = await self.update_obsidian_task(
                filepath=filepath,
                status="승인 대기중",
                agent_names=[self.agent_name],
                design_doc=markdown_doc,
            )

            if ok:
                return (True, f"Obsidian 태스크 처리 완료: {filepath}")
            return (False, f"기획 생성 완료, 파일 업데이트 실패: {msg}")

        except Exception as exc:
            return (False, f"Obsidian 태스크 처리 실패: {exc}")

    async def run(self) -> None:
        """
        Obsidian 기획 에이전트의 단발성 실행 사이클.
        조회 → 파싱 → 처리 → 업데이트 → 종료
        (ephemeral-docker-ops 전략 준수: while True 금지)
        """
        print(f"[{self.agent_name}] 실행 시작 (Vault: {self.vault_path})")

        raw_tasks = await self.fetch_pending_tasks()
        print(f"[{self.agent_name}] 조회된 태스크 수: {len(raw_tasks)}")

        for raw in raw_tasks:
            task = await self.parse_obsidian_task(raw)
            if task is None:
                continue

            success, message = await self.process_task(task)
            label = "완료" if success else "실패"
            print(f"[{self.agent_name}] {label}: {message}")

        print(f"[{self.agent_name}] 실행 종료")
